# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The escaping of unit-supplied text is ported from the sibling emorphed
# and rxved projects, which fix the same bug, and which carry the same
# licence:
#   Copyright (C) 2026  emorphed / rxved contributors
#                                     - GPL-2.0-or-later
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

r"""The browser's file picker: one folder, one listing, one answer.

Split out of :mod:`nanosyned.app` for the same reason :mod:`nanosyned.screens`
is: the browser itself stays readable, and this widget is the modal the
import flow pushes when the user presses ``I``. It imports nothing from the
app, so the dependency runs one way only.

Keyboard only, and every key the plan names is bound here or caught as it is
typed, because a modal that silently ignores a keypress is worse than no
modal at all: the picker is step one of importing somebody else's program,
and the user should not have to reach for a mouse a terminal does not have.

The listing offers directories and the ``.syx`` / ``.sqs`` files inside
them, and the last folder is remembered rather than the file -- the
remembered value is a *folder*, saved when the user moves or chooses, so
leaving and pressing ``I`` again lands where they left off. A remembered
folder that is gone or not readable is not a condition the picker shows as
a crash: it falls back to the home directory with a note, and the user
keeps moving from there.

It reads no file and sends nothing. The listing is the whole of its
business; reading a chosen file is the next screen's.
"""

from __future__ import annotations

import os
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import config as cfg
from nanosyned.text import literal

__all__ = ["FilePickerScreen"]

#: The file kinds an import may take. Directories are always offered; the
#: files are the kinds the plan names, and nothing else in a folder is an
#: import waiting to happen.
IMPORT_KINDS: tuple[str, ...] = (".syx", ".sqs")


class FilePickerScreen(ModalScreen[str | None]):
    """One folder of import files, with the plan's keys.

    Returns the chosen file's path as a string -- the caller reads it, and
    reads it as an import rather than as a browser choice -- or ``None``
    when the user cancels. **It sends nothing and reads no file**; the
    listing is the whole of its business.

    ``enter`` descends a directory and chooses a file; ``backspace`` goes
    up a level (or the last character off a filter); ``~`` goes home;
    ``/`` narrows the listing; ``esc`` and ``q`` close with nothing chosen.
    """

    DEFAULT_CSS = """
    FilePickerScreen { align: center middle; }
    FilePickerScreen > Vertical {
        width: 84; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    FilePickerScreen #picker-title { margin-bottom: 1; }
    FilePickerScreen DataTable { height: 1fr; }
    FilePickerScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    FilePickerScreen #picker-status { height: auto; color: $text; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "choose", "Choose", priority=True),
        Binding("backspace", "parent", "Parent directory"),
        Binding("~", "home", "Home"),
        Binding("/", "filter", "Filter"),
    ]

    def __init__(
        self,
        *,
        status_message: str = "",
        path: str | None = None,
    ) -> None:
        super().__init__()
        #: What the caller asked for, if anything; the remembered folder
        #: is only consulted when the caller did not name one.
        self._asked: str | None = path
        #: The folder the user is looking in. Resolved on mount.
        self._path: str = path if path is not None else os.path.expanduser("~")
        #: The narrowing the user asked for with ``/``. Empty means all.
        self._filter = ""
        self._filtering = False
        #: The listing on screen, as ``(is_dir, name)`` pairs.
        self._rows: list[tuple[bool, str]] = []
        self._cursor = 0
        self._notice = status_message

    @property
    def folder(self) -> str:
        """The folder the user is looking in."""
        return self._path

    @property
    def _config_path(self) -> str | None:
        """The injected config path, so a screen without one remembers nothing."""
        return getattr(self.app, "_config_path", None)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-dialog"):
            yield Label("", id="picker-title")
            picker_table: DataTable = DataTable(id="picker-table", cursor_type="row")
            picker_table.add_column("name", key="name")
            yield picker_table
            yield Static("", id="picker-status")
            yield Static(
                "[dim]↑↓ move · enter choose · backspace up · ~ home · / "
                "filter · esc cancel[/dim]",
                id="picker-note",
                classes="note",
            )

    def on_mount(self) -> None:
        self._path = self._start_path()
        self._populate()
        self.query_one("#picker-table", DataTable).focus()
        self._refresh()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "picker-table":
            return
        self._cursor = event.cursor_row

    def on_key(self, event) -> None:
        """Collect the filter's characters as they are typed.

        Bound keys never reach this handler -- the binding check runs
        before the key handler -- so everything arriving here while a
        filter is open is typed text, and the rest is the cancel key.
        """
        if self._filtering and event.is_printable:
            self._filter += event.character or event.key
            self._populate()
            return
        if event.key == "q":
            self.action_cancel()
            return
        if not self._filtering and event.is_printable and event.key.isalpha():
            # Jump to the first entry starting with the pressed letter,
            # without narrowing the listing: the filter is a separate,
            # deliberate mode (``/``), this is one keystroke of type-ahead.
            letter = event.key.casefold()
            table = self.query_one("#picker-table", DataTable)
            for index, (_, name) in enumerate(self._rows):
                if name.casefold().startswith(letter):
                    table.move_cursor(row=index)
                    break

    def _start_path(self) -> str:
        """The remembered folder, or the home directory when it is gone.

        An explicit ``path`` wins -- a caller that already knows where the
        user was -- and the remembered folder is consulted only when the
        caller did not name one.
        """
        if self._asked is not None:
            return self._asked
        remembered = self._remembered()
        if remembered is not None and self._usable(remembered):
            return remembered
        if remembered is not None:
            self._note(f"{remembered} is gone or unreadable; showing your home folder")
        return os.path.expanduser("~")

    def _remembered(self) -> str | None:
        """The folder the user last picked from, from the ui state."""
        return cfg.load_ui_str("import.folder", self._config_path)

    def _usable(self, path: str) -> bool:
        """Whether the folder is there and readable by this user."""
        return os.path.isdir(path) and os.access(path, os.R_OK)

    def _save_folder(self) -> None:
        """Remember the folder the user is in; never the file they chose."""
        try:
            cfg.save_ui_state("import.folder", self._path, self._config_path)
        except OSError:
            # A read-only cache must not cost the picker its memory.
            pass

    def _populate(self) -> None:
        """Redraw the listing for the current folder and filter."""
        table = self.query_one("#picker-table", DataTable)
        table.clear()
        self._rows = self._listing()
        for is_dir, name in self._rows:
            table.add_row(
                f"{name}/" if is_dir else literal(name),
                key=name,
            )
        self._cursor = 0
        if self._rows:
            table.move_cursor(row=0)
        self._refresh()

    def _listing(self) -> list[tuple[bool, str]]:
        """The directories and import files in the folder being browsed."""
        try:
            names = os.listdir(self._path)
        except OSError:
            return []
        needle = self._filter.casefold()
        rows: list[tuple[bool, str]] = []
        for name in sorted(names):
            if needle and needle not in name.casefold():
                continue
            full = os.path.join(self._path, name)
            is_dir = os.path.isdir(full)
            if is_dir or name.casefold().endswith(IMPORT_KINDS):
                rows.append((is_dir, name))
        return rows

    def _refresh(self) -> None:
        """Redraw the title and the status row from current state."""
        self.query_one("#picker-title", Label).update(
            f"[b]Import: {literal(self._path)}[/b]"
        )
        self.query_one("#picker-status", Static).update(self._status())

    def _status(self) -> str:
        """The status row: the notice, or the hint for the current listing."""
        if self._notice:
            return self._notice
        if not self._rows:
            return "[dim]no import files in this folder[/dim]"
        return (
            "[dim]↑↓ move · enter choose · backspace up · ~ home · / filter · "
            "esc cancel[/dim]"
        )

    def _note(self, sentence: str) -> None:
        """Put a status note in the screen's own status row."""
        self._notice = sentence
        self._refresh()

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        """Put one sentence in the screen's own status row."""
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh()

    def action_cancel(self) -> None:
        """``esc`` closes with nothing chosen."""
        self._notice = ""
        self._refresh()
        self.dismiss(None)

    def action_choose(self) -> None:
        """``enter``: descend a directory, or choose the highlighted file."""
        if not self._rows:
            self._say("nothing to choose in this folder", refused=True)
            return
        is_dir, name = self._rows[self._cursor]
        if is_dir:
            self._path = os.path.join(self._path, name)
            self._filtering = False
            self._filter = ""
            self._save_folder()
            self._populate()
            return
        chosen = os.path.join(self._path, name)
        self._save_folder()
        self.dismiss(chosen)

    def action_parent(self) -> None:
        """``backspace``: one level up, or the last character off a filter."""
        if self._filtering:
            self._filter = self._filter[:-1]
            if not self._filter:
                self._filtering = False
            self._populate()
            return
        parent = os.path.dirname(self._path)
        if parent == self._path:
            self._say("already at the top of the folder tree", refused=True)
            return
        self._path = parent
        self._filtering = False
        self._filter = ""
        self._save_folder()
        self._populate()

    def action_home(self) -> None:
        """``~``: go back to the home folder."""
        self._path = os.path.expanduser("~")
        self._filtering = False
        self._filter = ""
        self._save_folder()
        self._populate()

    def action_filter(self) -> None:
        """``/``: start narrowing the listing to what is typed."""
        self._filtering = True
        self._filter = ""
        self._populate()
