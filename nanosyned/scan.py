# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The empty-catalog offer and a scan's progress: two screens.

Split out of :mod:`nanosyned.app` for the same reason :mod:`nanosyned.screens`
is: the browser itself stays readable, and these widgets can be tested without
a bridge. This module imports nothing from :mod:`nanosyned.app`, so the
dependency runs one way only. It also knows nothing about MIDI: the app passes
a callable, and the worker here only calls it.

**What "scan" can honestly mean on this instrument.** The protocol has a dump
request for the 128 User programs and for nothing else. The General MIDI bank
and the three preset banks are ROM, and the unit will not answer for them at
all -- their names come from a printed catalog transcribed from the manual by
``tools/extract_catalog.py``, which is the owner's own work, not a question
the unit can answer. So a scan here reads the User bank's 128 names -- five
banks' worth of what this browser shows, one fifth of it -- and the prompt
below says so rather than borrowing a sibling's promise about its own synth.

The offer has three answers rather than a yes/no because "not now" and
"never ask again" are different questions, and only one of them should stop
the offer coming back. Escape is the first, not the second: a key pressed to
make a dialog go away must never quietly change a preference.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, ProgressBar, Static

__all__ = [
    "SCAN_OFFER",
    "ReadNames",
    "ScanOffer",
    "ScanOfferScreen",
    "ScanScreen",
]

#: The offer's three answers. Plain strings rather than an enum: they cross
#: a screen boundary as a value, and there is nothing to serialise.
ScanOffer = str

#: What the offer says. It has to be honest about the hardware, so it names
#: the one bank the unit will dump and says plainly where the other four
#: names come from. Kept here rather than in the app so the sentence a person
#: actually reads lives beside the screen that shows it -- and so a test can
#: assert the claim rather than trust a call site to repeat it.
SCAN_OFFER = (
    "There is no name catalog yet, so the sounds show as numbers.\n\n"
    "Scanning reads the User bank's 128 names back from the unit. That is "
    "the only bank this instrument will dump: General MIDI and the three "
    "preset banks are ROM, and the protocol has no request for them. Their "
    "names come from a printed catalog transcribed separately -- there is "
    "nothing on the unit to ask.\n\n"
    "The read is silent: nothing is selected, nothing plays, and nothing "
    "is written to the instrument. It asks for one program at a time, so "
    "it takes a moment."
)

#: What a scan screen calls to read the names. The app supplies one that
#: speaks to the unit; this module never does. ``cancel`` is the screen's
#: flag, checked by the callable between requests; the return is the names,
#: or ``None`` when the flag stopped it.
ReadNames = Callable[
    [Callable[[int, int], None], threading.Event], "dict[int, str] | None"
]


class ScanOfferScreen(ModalScreen[ScanOffer]):
    """Offer to read what the unit can answer when there is nothing to show.

    Three answers rather than a yes/no, because "not now" and "never ask
    again" are different, and only one of them should stop the question
    coming back. ``y`` scans, ``n`` and escape defer, ``d`` dismisses it for
    good; the three buttons say the same. Escape and ``n`` both mean
    "later" and never "never" -- a reflex dismissal must not change a
    preference.

    It displays the prompt it is handed and nothing else. Whether the answer
    starts a scan, is remembered, or is ignored is the app's to decide, which
    is what keeps this file free of MIDI.
    """

    DEFAULT_CSS = """
    ScanOfferScreen { align: center middle; }
    ScanOfferScreen > Vertical {
        width: 72; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    ScanOfferScreen .prompt { margin-bottom: 1; }
    ScanOfferScreen > Vertical > Horizontal {
        height: auto; align: center middle;
    }
    ScanOfferScreen Button { margin: 0 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "scan", "Scan"),
        Binding("n", "later", "Not now"),
        Binding("d", "never", "Don't ask again"),
        # Escape leans the same way as `n`. It is the nearest key to hand and
        # the one most likely pressed without reading, so it must be the
        # reversible answer; `d` is the one that has to be meant.
        Binding("escape", "later", "Not now"),
    ]

    def __init__(self, prompt: str = SCAN_OFFER) -> None:
        super().__init__()
        self.prompt_text = prompt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.prompt_text, classes="prompt")
            with Horizontal():
                yield Button("Scan", variant="primary", id="scan")
                yield Button("Not now", id="later")
                yield Button("Don't ask again", id="never")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        # The ids are the answers, so a press needs no lookup table. An id
        # of None should not happen, and "later" is the safe reading of it.
        self.dismiss(event.button.id or "later")

    def action_scan(self) -> None:
        self.dismiss("scan")

    def action_later(self) -> None:
        self.dismiss("later")

    def action_never(self) -> None:
        self.dismiss("never")


class ScanScreen(ModalScreen["dict[int, str] | None"]):
    """Progress for a scan, with a Cancel button and the worker behind it.

    The worker lives here rather than in the app so the modal owns its own
    cancellation: the button, the flag the read checks, and the progress bar
    are the same object, and no screen boundary has to carry a flag back.
    What it must *not* own is a port -- the read is a callable the app
    supplies, so this file stays cycle-free and MIDI-free, and the rule that
    the main thread never touches a port holds by construction.

    Cancel is read between requests, not mid-message: the callable sees the
    flag at each boundary it chooses, and a half-read bank is never left
    that way.

    Progress can arrive before this screen has composed: the worker is
    started in ``on_mount`` and the first report can beat the first paint.
    ``set_progress`` therefore treats a missing widget as "not mounted yet"
    rather than an error, and keeps the latest line itself.
    """

    DEFAULT_CSS = """
    ScanScreen { align: center middle; }
    ScanScreen > Vertical {
        width: 72; height: auto; border: thick $accent;
        background: $surface; padding: 1 2;
    }
    ScanScreen .title { margin-bottom: 1; }
    ScanScreen > Vertical > Horizontal {
        height: auto; align: center middle;
    }
    ScanScreen ProgressBar { margin: 1 0; }
    ScanScreen Button { margin: 0 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        read: ReadNames,
        *,
        title: str = "Scanning the unit",
        total: int = 128,
    ) -> None:
        super().__init__()
        self._read = read
        self._title = title
        self._total = total
        self._cancel = threading.Event()
        self._cancelled = False
        #: The latest line, kept here as well as on screen: a report can
        #: arrive before this screen has composed, and a query for a widget
        #: that is not there yet must not raise.
        self._line = "starting…"
        self._thread: threading.Thread | None = None
        self._finished = False
        #: What the read raised, if anything. The screen reports only
        #: "no result"; the app decides whether that is a device fault to
        #: show or a programming error to raise. Set on the worker, read on
        #: the main thread after the dismiss callback runs.
        self.error: BaseException | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[b]{self._title}[/b]", classes="title")
            yield Static(self._line, id="scan-line")
            yield ProgressBar(total=self._total, id="scan-progress", show_eta=False)
            with Horizontal():
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self._thread = threading.Thread(
            target=self._work, name="nanosyned-scan", daemon=True
        )
        self._thread.start()

    def _work(self) -> None:
        """**The read only.** Runs on its own thread; says nothing itself."""
        result: dict[int, str] | None = None
        try:
            result = self._read(self._report, self._cancel)
        except Exception as exc:
            self.error = exc
        if self._cancelled:
            result = None
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._finish, result)

    def _report(self, done: int, total: int) -> None:
        """Called on the worker thread by the read callable."""
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self.set_progress, done, total)

    def _finish(self, result: dict[int, str] | None) -> None:
        """Main thread. One dismiss, whichever path got here."""
        if self._finished or not self.is_current:
            # The read can outlive the screen if the app is closing; there
            # is nothing left to dismiss it to, and popping another screen
            # would be worse than dropping this result.
            return
        self._finished = True
        self.dismiss(result)

    def set_progress(self, done: int, total: int) -> None:
        """Main thread. What the worker wants shown. Safe before mount."""
        self._total = total
        self._line = f"read {done}/{total} names (silent)…"
        with contextlib.suppress(NoMatches):
            self.query_one("#scan-line", Static).update(self._line)
        with contextlib.suppress(NoMatches):
            bar = self.query_one("#scan-progress", ProgressBar)
            bar.total = total
            bar.progress = done

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()

    def action_cancel(self) -> None:
        """Raise the flag; the read stops at its next boundary."""
        if self._cancelled:
            return
        self._cancelled = True
        self._cancel.set()
        self._line = "cancelling — stopping after this program…"
        with contextlib.suppress(NoMatches):
            self.query_one("#scan-line", Static).update(self._line)
        with contextlib.suppress(NoMatches):
            self.query_one("#cancel", Button).disabled = True

    @property
    def cancelled(self) -> bool:
        """Whether Cancel has been pressed, for a test to ask."""
        return self._cancelled
