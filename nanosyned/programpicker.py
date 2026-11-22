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

"""Pick a User program by name, for a mix channel.

A mix channel stores a program number, not a bank, and on this unit the
writable program bank is the User bank. The picker therefore lists its 128
numbers with the names the catalog or the unit supplied, rather than asking
somebody to remember that ``VH Piano`` is number 0.

It sends nothing and owns no device: the mix screen applies the answer
through the same live-edit path as every other field.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import banks
from nano import catalog as cat
from nanosyned.text import literal

__all__ = ["ProgramPickerScreen"]


class ProgramPickerScreen(ModalScreen[int | None]):
    """The User bank's 128 programs, by number and name."""

    DEFAULT_CSS = """
    ProgramPickerScreen { align: center middle; }
    ProgramPickerScreen > Vertical {
        width: 72; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    ProgramPickerScreen DataTable { height: 1fr; }
    ProgramPickerScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        catalog: cat.Catalog | None = None,
        *,
        current: int | None = None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._current = current
        self._numbers: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Pick a User program[/b]", id="program-title")
            yield DataTable(id="program-table", cursor_type="row")
            yield Static(
                "[dim]↑↓ move · a letter jumps by name · enter picks · "
                "esc cancels. Mix channels store the User-bank program "
                "number; 127 is Off.[/dim]",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#program-table", DataTable)
        table.add_column("#", key="number")
        table.add_column("program", key="name")
        for number in range(banks.PROGRAMS_PER_BANK):
            table.add_row(
                f"{number:03d}",
                literal(self._program_name(number)),
                key=str(number),
            )
            self._numbers.append(number)
        if self._current is not None and 0 <= self._current < table.row_count:
            table.move_cursor(row=self._current)
        table.focus()

    def _program_name(self, number: int) -> str:
        if self._catalog is None:
            return ""
        name = self._catalog.display_name("USER", number)
        return "" if name == cat.UNNAMED else name

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "program-table":
            return
        key = event.row_key.value
        if key is not None:
            self.dismiss(int(str(key)))

    def on_key(self, event) -> None:
        """Jump to the first program whose name starts with a typed letter."""
        if not event.is_printable or not event.character:
            return
        letter = event.character.casefold()
        if not letter.isalpha():
            return
        table = self.query_one("#program-table", DataTable)
        for row, number in enumerate(self._numbers):
            if self._program_name(number).casefold().startswith(letter):
                table.move_cursor(row=row)
                event.stop()
                return

    def action_cancel(self) -> None:
        self.dismiss(None)
