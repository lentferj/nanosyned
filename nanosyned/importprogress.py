# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""Import progress screen for the cooperative cancel flow.

Shows ``n/N``, the current slot and name, how many failures so far, and an
``esc`` hint.  Reading and writing happen one record at a time in the
caller's worker thread; this screen only displays what the worker reports
and forwards the cooperative cancel request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.screen import ModalScreen
from textual.widgets import Static

__all__ = ["ImportProgressScreen"]


class ImportProgressScreen(ModalScreen[str | None]):
    """Show progress of an import with cooperative cancel.

    The caller (``_import_worker``) updates the display between steps by
    calling ``set_progress``; the screen forwards ``esc`` / ``q`` to
    ``action_request_stop`` so the worker can stop between records.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "request_stop", "Cancel"),
        Binding("q", "request_stop", "Cancel"),
    ]

    def __init__(
        self, *, total: int, on_stop: Callable[[], None] | None = None
    ) -> None:
        super().__init__()
        self.total = total
        self.done = 0
        self.failures = 0
        self.current_slot: int | None = None
        self.current_name: str = ""
        self._on_stop = on_stop
        self._request_stop = False

    def compose(self):
        yield Static(id="import-progress")

    def on_mount(self) -> None:
        self._show()

    def _show(self) -> None:
        slot = "" if self.current_slot is None else f"{self.current_slot:03d}"
        lines = [
            f"importing {self.done}/{self.total}",
            f"current: {slot}  {self.current_name or '?'}",
            f"failures: {self.failures}",
            "",
            "esc / q: stop",
        ]
        self.query_one("#import-progress", Static).update("\n".join(lines))

    def set_progress(
        self, done: int, total: int, slot: int | None, name: str, failures: int
    ) -> None:
        """Update the display on the main thread via ``call_from_thread``."""
        self.done = done
        self.total = total
        self.failures = failures
        self.current_slot = slot
        self.current_name = name or "?"
        self._show()

    def action_request_stop(self) -> None:
        """Called when the user presses esc or q."""
        self._request_stop = True
        if self._on_stop is not None:
            self._on_stop()

    @property
    def should_stop(self) -> bool:
        """True if the worker asked to stop; the caller checks this."""
        return self._request_stop
