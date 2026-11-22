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

``F`` cycles the same three views as the main browser: every slot, the
favourites in the bank under the cursor, and every favourite in every bank.
The letter keys jump by name; pressing the same letter again moves to the
next match and wraps at the end.
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
from nano.favorites import Favorites
from nanosyned.text import literal

__all__ = ["ProgramPickerScreen"]

#: The same three views as the main browser. They are repeated here rather
#: than imported from ``nanosyned.app`` because app imports this screen, and
#: the picker must not turn that into an import cycle.
VIEW_ALL = "all"
VIEW_BANK_FAVOURITES = "bank-favourites"
VIEW_ALL_FAVOURITES = "all-favourites"
VIEW_CYCLE = (VIEW_ALL, VIEW_BANK_FAVOURITES, VIEW_ALL_FAVOURITES)
VIEW_LABELS = {
    VIEW_ALL: "all slots",
    VIEW_BANK_FAVOURITES: "favourites in this bank",
    VIEW_ALL_FAVOURITES: "every favourite, all banks",
}


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
    ProgramPickerScreen #program-view { height: auto; color: $text; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("F", "cycle_favorites", "Favourites view"),
    ]

    def __init__(
        self,
        catalog: cat.Catalog | None = None,
        *,
        current_bank: int | None = None,
        current_program: int | None = None,
        favorites: Favorites | None = None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._current_bank = current_bank
        self._current_program = current_program
        self._favorites = favorites
        self._entries: list[tuple[int, int]] = []
        self._view = VIEW_ALL
        self._view_bank: int = (
            current_bank
            if current_bank is not None and current_bank in range(len(banks.BANKS))
            else 0
        )
        self._last_letter = ""
        self._last_letter_row = -1

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Pick a program[/b]", id="program-title")
            yield Static("", id="program-view")
            yield DataTable(id="program-table", cursor_type="row")
            yield Static(
                "[dim]↑↓ move · a letter jumps by name (press again for the "
                "next match) · F favourites view · enter picks · esc cancels. "
                "Every bank is selectable; the pair stored in the mix channel "
                "is the bank and program number.[/dim]",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#program-table", DataTable)
        table.add_column("bank", key="bank")
        table.add_column("#", key="number")
        table.add_column("program", key="name")
        preferred = None
        if self._current_bank is not None and self._current_program is not None:
            preferred = f"{self._current_bank}:{self._current_program}"
        self._fill_table(preferred)
        table.focus()

    def _program_name(self, bank_id: str, number: int) -> str:
        if self._catalog is None:
            return ""
        name = self._catalog.display_name(bank_id, number)
        return "" if name == cat.UNNAMED else name

    def _bank(self, select: int) -> banks.Bank | None:
        for bank in banks.BANKS:
            if bank.select == select:
                return bank
        return None

    def _bank_id(self, select: int) -> str:
        bank = self._bank(select)
        return bank.id if bank is not None else ""

    def _favourite_numbers(self, select: int) -> set[int]:
        if self._favorites is None:
            return set()
        bank = self._bank(select)
        return set() if bank is None else self._favorites.keys_for_bank(bank.id)

    def _visible_entries(self) -> list[tuple[int, int]]:
        if self._view == VIEW_ALL:
            return [
                (bank.select, number)
                for bank in banks.BANKS
                for number in range(banks.PROGRAMS_PER_BANK)
            ]
        if self._view == VIEW_BANK_FAVOURITES:
            numbers = self._favourite_numbers(self._view_bank)
            return [
                (self._view_bank, number)
                for number in range(banks.PROGRAMS_PER_BANK)
                if number in numbers
            ]
        entries: list[tuple[int, int]] = []
        for bank in banks.BANKS:
            numbers = self._favourite_numbers(bank.select)
            entries.extend(
                (bank.select, number)
                for number in range(banks.PROGRAMS_PER_BANK)
                if number in numbers
            )
        return entries

    def _current_key(self) -> str | None:
        table = self.query_one("#program-table", DataTable)
        row = table.cursor_row
        if 0 <= row < len(self._entries):
            select, number = self._entries[row]
            return f"{select}:{number}"
        return None

    def _fill_table(self, preferred: str | None = None) -> None:
        table = self.query_one("#program-table", DataTable)
        self._entries = self._visible_entries()
        table.clear()
        cursor = 0
        for row, (select, number) in enumerate(self._entries):
            bank_id = self._bank_id(select)
            table.add_row(
                literal(bank_id),
                f"{number:03d}",
                literal(self._program_name(bank_id, number)),
                key=f"{select}:{number}",
            )
            if preferred == f"{select}:{number}":
                cursor = row
        if self._entries:
            table.move_cursor(row=cursor)
        self._last_letter = ""
        self._last_letter_row = -1
        self._update_view()

    def _bank_at_cursor(self) -> int:
        key = self._current_key()
        if key is not None:
            return int(key.split(":", 1)[0])
        return self._view_bank

    def _update_view(self) -> None:
        view = self.query_one("#program-view", Static)
        if self._view == VIEW_BANK_FAVOURITES:
            seek = self._view_bank
            bank = self._bank(seek)
            where = f" in {bank.label}" if bank is not None else ""
            view.update(f"[b]Favourites{where}[/b] · {len(self._entries)} shown")
        else:
            view.update(
                f"[b]{VIEW_LABELS[self._view]}[/b] · {len(self._entries)} shown"
            )

    def action_cycle_favorites(self) -> None:
        """Step: all slots -> this bank's favourites -> every favourite."""
        if self._favorites is None:
            view = self.query_one("#program-view", Static)
            view.update("[b]No favourites database[/b]")
            return
        bank = self._bank_at_cursor()
        index = VIEW_CYCLE.index(self._view)
        self._view = VIEW_CYCLE[(index + 1) % len(VIEW_CYCLE)]
        if self._view == VIEW_BANK_FAVOURITES:
            self._view_bank = bank
        self._fill_table(self._current_key())

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "program-table":
            return
        key = event.row_key.value
        if key is None:
            return
        bank_text, number_text = str(key).split(":", 1)
        self.dismiss((int(bank_text), int(number_text)))

    def on_key(self, event) -> None:
        """Jump by name; repeat the same letter to reach the next match."""
        if not event.is_printable or not event.character:
            return
        letter = event.character.casefold()
        if not letter.isalpha():
            return
        table = self.query_one("#program-table", DataTable)
        if not self._entries:
            return
        current = table.cursor_row
        if letter == self._last_letter and current == self._last_letter_row:
            start = current + 1
        else:
            start = 0
        for offset in range(len(self._entries)):
            row = (start + offset) % len(self._entries)
            select, number = self._entries[row]
            name = self._program_name(self._bank_id(select), number)
            if name.casefold().startswith(letter):
                table.move_cursor(row=row)
                self._last_letter = letter
                self._last_letter_row = row
                event.stop()
                return
        self._last_letter = ""
        self._last_letter_row = -1

    def action_cancel(self) -> None:
        self.dismiss(None)
