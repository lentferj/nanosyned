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

"""Pick a program for a mix channel by bank, number and name.

A mix channel stores a bank code plus a program number. This screen lists
all five internal banks and their 128 programs, so a channel can point at
any bank; the returned pair is the bank-select value and the program number.
It sends nothing and owns no device: the mix screen applies the answer
through its live-buffer path.
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


class ProgramPickerScreen(ModalScreen[tuple[int, int] | None]):
    """All five internal banks by name; returns ``(bank select, program)``."""

    DEFAULT_CSS = """
    ProgramPickerScreen { align: center middle; }
    ProgramPickerScreen > Vertical {
        width: 86; height: 90%; border: thick $primary;
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
        current_bank: int | None = None,
        current_program: int | None = None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._current_bank = current_bank
        self._current_program = current_program
        self._entries: list[tuple[int, int]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Pick a program[/b]", id="program-title")
            yield DataTable(id="program-table", cursor_type="row")
            yield Static(
                "[dim]↑↓ move · a letter jumps by name · enter picks · "
                "esc cancels. Every bank is selectable; the pair stored in "
                "the mix channel is the bank and program number.[/dim]",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#program-table", DataTable)
        table.add_column("bank", key="bank")
        table.add_column("#", key="number")
        table.add_column("program", key="name")
        cursor = 0
        for bank in banks.BANKS:
            for number in range(banks.PROGRAMS_PER_BANK):
                table.add_row(
                    literal(bank.label),
                    f"{number:03d}",
                    literal(self._program_name(bank.id, number)),
                    key=f"{bank.select}:{number}",
                )
                self._entries.append((bank.select, number))
                if (
                    bank.select == self._current_bank
                    and number == self._current_program
                ):
                    cursor = len(self._entries) - 1
        table.move_cursor(row=cursor)
        table.focus()

    def _program_name(self, bank_id: str, number: int) -> str:
        if self._catalog is None:
            return ""
        name = self._catalog.display_name(bank_id, number)
        return "" if name == cat.UNNAMED else name

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "program-table":
            return
        key = event.row_key.value
        if key is None:
            return
        bank_text, number_text = str(key).split(":", 1)
        self.dismiss((int(bank_text), int(number_text)))

    def on_key(self, event) -> None:
        """Jump to the first program whose name starts with a typed letter."""
        if not event.is_printable or not event.character:
            return
        letter = event.character.casefold()
        if not letter.isalpha():
            return
        table = self.query_one("#program-table", DataTable)
        for row, (bank_select, number) in enumerate(self._entries):
            bank_id = banks.BANKS[bank_select].id
            if self._program_name(bank_id, number).casefold().startswith(letter):
                table.move_cursor(row=row)
                event.stop()
                return

    def action_cancel(self) -> None:
        self.dismiss(None)
