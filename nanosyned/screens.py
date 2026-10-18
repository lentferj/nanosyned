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

"""The widgets the application opens.

Split out of :mod:`nanosyned.app` so the browser itself stays readable, on
the same shape as :mod:`rxved.screens` and :mod:`emorphed.screens`. This
module holds every widget the application opens. It imports nothing from
:mod:`nanosyned.app`, so the dependency runs one way only and any part of
the program can import it without a cycle.

``ReportScreen`` and ``PromptScreen`` used to be defined in the browser
itself, eight copies of the same class across the family. They are the
library's now -- :mod:`vinsynlib.ui.report` and
:mod:`vinsynlib.ui.prompt`, imported below and re-exported so every call
site reads exactly as it did, with the one difference each sibling keeps:
``enter`` closes the report, so the frame's words are the library's and the
key is this tool's.

``EditorScreen`` is the one screen here that can destroy something. It
follows the sibling projects' rule for a destructive operation -- arm, then
fire with a *different* key, and anything that moves disarms -- because the
thing it replaces is a program somebody made.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from nanosyned.editor import ProgramEditor
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen
from vinsynlib.ui.hints import KeyHints as _LibraryKeyHints
from vinsynlib.ui.prompt import PromptScreen
from vinsynlib.ui.report import ReportScreen as _Frame

__all__ = [
    "ConfirmScreen",
    "EditorScreen",
    "KeyHints",
    "PromptScreen",
    "ReportScreen",
]


#: rxved's shape: ``enter`` closes as well. Three lines, no rewrite --
#: so the frame's words are the library's and the only difference is the
#: key that closes it.
class ReportScreen(_Frame):
    """nanosyned's shape: ``enter`` closes as well. Three lines, no rewrite."""

    BINDINGS: ClassVar[list[Any]] = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("enter", "close", "Close"),
    ]


class KeyHints(_LibraryKeyHints):
    """The library legend, relaid out after every re-wrap.

    The library widget re-wraps its text on mount and on resize but never
    asks for a layout, so ``height: auto`` keeps whatever height the first
    render gave it. That first render happens before the widget has a width:
    the wrap falls back to its minimum, the whole legend stacks into about a
    dozen lines, and the footer stays that tall -- a band of empty panel
    under the keys -- until the terminal is resized. Requesting the layout
    after each re-wrap keeps the footer only as tall as the wrapped text,
    which is the point of wrapping it here at all.
    """

    def on_mount(self) -> None:
        super().on_mount()
        self.call_after_refresh(self.refresh, layout=True)

    def on_resize(self) -> None:
        super().on_resize()
        self.call_after_refresh(self.refresh, layout=True)


class EditorScreen(ModalScreen[bytes | None]):
    """One User program's name, and an arm-then-fire store.

    Returns the new 350-byte record when the user fires, ``None`` when they
    close without storing. **It sends nothing itself** -- there is no device
    and no clock in this screen -- so the app can claim its exchange on the
    main thread, back the slot up, write it and read it back in the one
    worker every other MIDI action uses.

    Three deliberate steps, none of them a single keystroke:

    1. Pick the new name with `n` (the library's prompt) and press `a` to
       arm. Arming names the destination **and what is about to be
       replaced** -- "User 005" means nothing; the name it holds means
       everything.
    2. Press `w`, a different key, while armed. Only then does the screen
       return the record.
    3. Anything that changes where the user is looking -- the arrow keys,
       typing a name, reverting -- disarms.

    Escape closes without storing, armed or not.
    """

    DEFAULT_CSS = """
    EditorScreen { align: center middle; }
    EditorScreen > Vertical {
        width: 74; height: auto; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    EditorScreen .armed {
        color: $error;
        text-style: bold;
    }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "close", "Cancel"),
        Binding("q", "close", "Cancel"),
        Binding("n", "edit_name", "Name"),
        Binding("a", "arm", "Arm"),
        # Deliberately not Enter, and deliberately not next to "a": the fire
        # key should not be the one a finger is resting on after arming.
        Binding("w", "fire", "Store"),
        Binding("r", "revert", "Revert"),
        # There is no table to move a cursor over here, but reaching for one
        # is still a change of mind: any movement disarms, as it does in the
        # family's store screens.
        Binding("up", "disarm", "Disarm", show=False),
        Binding("down", "disarm", "Disarm", show=False),
        Binding("left", "disarm", "Disarm", show=False),
        Binding("right", "disarm", "Disarm", show=False),
    ]

    def __init__(
        self,
        editor: ProgramEditor,
        *,
        slot: str,
        replaced: str,
    ) -> None:
        super().__init__()
        self._editor = editor
        #: The destination, as the browser names it ("User 005").
        self._slot = slot
        #: The name the destination holds now -- what firing destroys.
        self._replaced = replaced
        self._armed = False
        self._notice = ""

    @property
    def armed(self) -> bool:
        """Whether `w` would store right now."""
        return self._armed

    def compose(self) -> ComposeResult:
        with Vertical(id="editor-dialog"):
            yield Label(f"[b]Edit {literal(self._slot)}[/b]", id="editor-title")
            yield Static("", id="editor-name")
            yield Static("", id="editor-status")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        name = literal(self._editor.name.rstrip()) or "[dim](blank)[/dim]"
        state = "unsaved changes" if self._editor.dirty else "unchanged"
        self.query_one("#editor-name", Static).update(
            f"[b]{name}[/b]   [dim]{state}[/dim]"
        )
        status = self.query_one("#editor-status", Static)
        status.update(self._status())
        status.set_class(self._armed, "armed")

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if self._armed:
            return (
                f"[b]ARMED[/b] — about to overwrite {literal(self._slot)} — "
                f"{literal(self._replaced) or '(blank)'}.\n"
                f"[b]w[/b] stores it and reads it back; its current contents "
                f"are saved to a backup file first. Any other key disarms."
            )
        return "[dim]n name · a arm the store · r revert · esc cancel[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        """Put one sentence in the screen's own status row.

        ``sentence`` is escaped here rather than at every call site: the
        rename refusal quotes the character the user typed, and a bracket
        in that character would otherwise be read as markup.
        """
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh()

    def _disarm(self) -> None:
        self._armed = False

    def action_edit_name(self) -> None:
        """Open the text prompt. Typing is a change of mind: disarm first."""
        self._disarm()
        self._notice = ""
        self._refresh()
        self.app.push_screen(
            PromptScreen("Program name:", self._editor.name.rstrip()), self._named
        )

    def _named(self, text: str | None) -> None:
        if text is None:
            self._refresh()
            return
        problem = self._editor.set_name(text)
        if problem is not None:
            self._say(problem, refused=True)
            return
        self._notice = ""
        self._refresh()

    def action_arm(self) -> None:
        if not self._editor.dirty:
            self._say("nothing to store — the name is unchanged", refused=True)
            return
        self._armed = True
        self._notice = ""
        self._refresh()

    def action_disarm(self) -> None:
        if self._armed:
            self._disarm()
            self._refresh()

    def action_revert(self) -> None:
        """Undo the edits in this dialog. Sends nothing; disarms."""
        self._disarm()
        self._editor.reset()
        self._notice = ""
        self._refresh()

    def action_fire(self) -> None:
        """Return the record, but only while armed. A second look first."""
        if not self._armed:
            self._say("not armed — press a first", refused=True)
            return
        if not self._editor.dirty:
            self._disarm()
            self._say("nothing to store — the name is unchanged", refused=True)
            return
        record = self._editor.record()
        self._disarm()
        self.dismiss(record)

    def action_close(self) -> None:
        self.dismiss(None)
