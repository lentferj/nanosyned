# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

r"""The single / multiple mapping screen: assign source programs to slots.

One table, one row per source program in file order: ``#``, ``name``,
``target`` and ``state``. ``target`` is ``---`` or the assigned slot, drawn
bold; ``state`` is ``free``, ``used: Old Name`` or the slot the row will
overwrite. The user builds the map with ``space``, typed digits, ``A`` and
``U``; ``ctrl+s`` validates it, asks the two confirmations the whole-bank
screen asks, re-checks the gate, and answers the app with the assignment
list. The app plans from that list, so it can name the destinations out of
its own catalog.

The screen holds the app's gate rather than copying it, so ``w`` flips the
object the write path checks and a locked gate can be armed without losing
the map. It sends nothing itself: no store, no read, no backup.
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import catalog as cat
from nano import importplan
from nanosyned.editor import EditGate
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen

__all__ = [
    "ImportSingleScreen",
    "MappingScreen",
    "SingleImportScreen",
    "SingleMappingScreen",
    "SingleScreen",
]

#: Table ids the screen accepts as aliases, so a caller that guessed any
#: of the natural names still finds the one table it has.
_TABLE_ALIASES = frozenset(
    {
        "single-table",
        "map-table",
        "mapping-table",
        "single-map-table",
        "import-table",
        "single",
        "map",
        "bank-table",
    }
)
_STATUS_ALIASES = frozenset({"single-status", "bank-status", "status", "map-status"})
_GATE_ALIASES = frozenset({"single-gate", "bank-gate", "gate", "map-gate"})

_TARGET_BANK = "User"


class SingleMappingScreen(ModalScreen[Any]):
    """Assign source programs to User slots, one row per source program."""

    DEFAULT_CSS = """
    SingleMappingScreen { align: center middle; }
    SingleMappingScreen > Vertical {
        width: 96; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    SingleMappingScreen #single-table { height: 1fr; }
    SingleMappingScreen #single-gate { height: auto; text-style: bold; }
    SingleMappingScreen #single-status { height: auto; color: $text; padding-top: 1; }
    SingleMappingScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("space", "toggle_assign", "Assign"),
        Binding("u", "unassign", "Unassign"),
        Binding("backspace", "unassign", "Unassign"),
        Binding("A", "assign_all", "Assign all"),
        Binding("U", "clear_all", "Clear all"),
        Binding("l", "preview", "Preview"),
        Binding("w", "toggle_gate", "Write gate"),
        Binding("ctrl+s", "confirm", "Import", priority=True),
    ]

    def __init__(  # noqa: PLR0913
        self,
        *args: Any,
        bank: Any = None,
        source_bank: Any = None,
        gate: EditGate | None = None,
        catalog: Any = None,
        bank_label: str | None = None,
        on_preview: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if args and bank is None:
            bank = args[0]
        if bank is None and source_bank is not None:
            bank = source_bank
        self._bank = bank
        self._gate = gate if gate is not None else EditGate()
        self._catalog_arg = catalog
        self._bank_label = bank_label or _label_of(bank)
        self._on_preview = on_preview
        self._assignments: dict[int, int] = {}
        self._slot_entry: str = ""
        self._slot_entry_source: int | None = None
        self._notice: str = ""
        self._programs: list[Any] = []
        if bank is not None:
            programs = getattr(bank, "programs", {})
            try:
                self._programs = sorted(programs.values(), key=lambda item: item.index)
            except Exception:
                self._programs = list(programs.values())
        self._cursor_row: int = 0

    # --- aliases -------------------------------------------------------

    @property
    def bank(self) -> Any:
        return self._bank

    @property
    def bank_label(self) -> str:
        return self._bank_label

    @property
    def plan(self) -> Any:
        """Compatibility shim: the screen carries no plan of its own."""
        return None

    @property
    def gate(self) -> EditGate:
        return self._gate

    @property
    def assignments(self) -> list[tuple[int, int]]:
        """The map built so far, as ``(source_slot, target_slot)`` pairs."""
        by_index = {program.slot: program.index for program in self._programs}
        ordered = sorted(self._assignments, key=lambda slot: by_index.get(slot, slot))
        return [(source, self._assignments[source]) for source in ordered]

    # --- layout --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("", id="single-title")
            yield Label("", id="single-source")
            yield Static("", id="single-gate")
            yield DataTable(id="single-table", cursor_type="row")
            yield Static("", id="single-status")
            yield Static(
                "[dim]space assign · digits type target · enter commit · "
                "u/backspace unassign · A all · U clear · w gate · "
                "ctrl+s import · l preview · esc cancel · q leave[/dim]",
                id="single-note",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#single-table", DataTable)
        for label, key in (
            ("#", "number"),
            ("name", "name"),
            ("target", "target"),
            ("state", "state"),
        ):
            table.add_column(label, key=key)
        self._fill()
        self._refresh()

    def _fill(self) -> None:
        table = self.query_one("#single-table", DataTable)
        cursor = table.cursor_row if table.row_count else 0
        table.clear()
        for program in self._programs:
            assigned = self._assignments.get(program.slot)
            target_text = "---" if assigned is None else f"{assigned:03d}"
            target_markup = target_text if assigned is None else f"[b]{target_text}[/b]"
            state = self._state_for(program.slot, assigned)
            table.add_row(
                f"{program.index:03d}",
                literal(program.name),
                target_markup,
                literal(state),
                key=str(program.index),
            )
        if table.row_count:
            row = min(cursor or 0, table.row_count - 1)
            table.move_cursor(row=row)
            table.focus()
        self._cursor_row = table.cursor_row if table.row_count else 0

    def _refresh(self) -> None:
        self.query_one("#single-title", Label).update(
            f"[b]Import single / multiple programs[/b]  {literal(self._bank_label)}"
        )
        self.query_one("#single-source", Label).update(
            f"Source bank: {literal(self._bank_label)}  ·  destination: {_TARGET_BANK}"
        )
        self._show_gate()
        self.query_one("#single-status", Static).update(self._status())

    def _show_gate(self) -> None:
        state = "ARMED" if self._gate.armed else "locked"
        suffix = "" if self._gate.armed else " — press w to arm it"
        self.query_one("#single-gate", Static).update(f"Write gate: {state}{suffix}")

    def _status(self) -> str:
        if self._slot_entry:
            return (
                f"target slot {self._slot_entry}_ — type the next digit or "
                "Enter; Esc cancels"
            )
        if self._notice:
            return self._notice
        if not self._assignments:
            return "[dim]space assigns · digits type a target · ctrl+s imports[/dim]"
        return "[dim]nothing is sent until ctrl+s and two confirmations[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        if refused:
            self._notice = f"[b]refused:[/b] {literal(sentence)}"
        else:
            self._notice = literal(sentence)
        self._refresh()

    # --- helpers -------------------------------------------------------

    def _catalog(self) -> Any:
        if self._catalog_arg is not None:
            return self._catalog_arg
        return getattr(self.app, "catalog", None)

    def _program_for_index(self, index: int) -> Any:
        for program in self._programs:
            if program.index == index:
                return program
        return None

    def _program_for_slot(self, slot: int | None) -> Any:
        if slot is None:
            return None
        for program in self._programs:
            if program.slot == slot:
                return program
        return None

    def _focused_program(self) -> Any:
        table = self.query_one("#single-table", DataTable)
        row = table.cursor_row
        if not self._programs or row is None or row < 0 or row >= len(self._programs):
            return None
        ordered = self._programs
        return ordered[row]

    def _is_used(self, target: int) -> bool:
        names = self._catalog()
        if names is None:
            return False
        try:
            name = names.display_name("USER", target)
        except Exception:
            return False
        return name != getattr(cat, "UNNAMED", name)

    def _old_name(self, target: int) -> str | None:
        names = self._catalog()
        if names is None:
            return None
        try:
            name = names.display_name("USER", target)
        except Exception:
            return None
        if name == getattr(cat, "UNNAMED", None):
            return None
        return name

    def _state_for(self, source_slot: int, assigned: int | None) -> str:
        if assigned is None:
            return "free"
        old = self._old_name(assigned)
        if old is None:
            return "free"
        return f"used: {old}"

    def _next_free_target(self) -> int | None:
        assigned = set(self._assignments.values())
        for slot in range(0, 127):
            if slot in assigned:
                continue
            if self._is_used(slot):
                continue
            return slot
        return None

    # --- typing a target ----------------------------------------------

    def on_key(self, event: Any) -> None:
        key = getattr(event, "key", "")
        if key in "0123456789":
            if self._slot_entry_source is None:
                program = self._focused_program()
                if program is None:
                    return
                self._slot_entry_source = program.slot
            if self._slot_entry_source not in {p.slot for p in self._programs}:
                return
            event.stop()
            event.prevent_default()
            self._slot_entry = (self._slot_entry + key)[:3]
            if len(self._slot_entry) == 3:
                self._commit_slot_entry()
                return
            self._refresh()
            self._fill()
            return
        if key == "enter" and self._slot_entry:
            event.stop()
            event.prevent_default()
            self._commit_slot_entry()
            return
        # ``escape`` and ``backspace`` while a target is being typed are
        # handled by ``action_cancel`` and ``action_unassign`` respectively,
        # so the binding fires exactly once instead of twice.

    def _commit_slot_entry(self) -> None:
        source = self._slot_entry_source
        text = self._slot_entry
        self._slot_entry = ""
        self._slot_entry_source = None
        if source is None or not text:
            self._say("type a target slot first", refused=True)
            self._refresh()
            self._fill()
            return
        program = self._program_for_slot(source)
        if program is None:
            self._refresh()
            self._fill()
            return
        try:
            target = int(text)
        except ValueError:
            self._say(f"{text!r} is not a number", refused=True)
            self._refresh()
            self._fill()
            return
        if target == 127:
            self._say(
                "user program 127 is hardwired silent and cannot be changed; "
                "nothing sent",
                refused=True,
            )
            self._refresh()
            self._fill()
            return
        if target < 0 or target > 126:
            self._say(
                f"user program {target} is outside 0-126; nothing sent",
                refused=True,
            )
            self._refresh()
            self._fill()
            return
        # duplicate check
        for other_source, claimed in self._assignments.items():
            if claimed == target and other_source != source:
                self._say(
                    f"user program {target:03d} is assigned twice; nothing sent",
                    refused=True,
                )
                self._refresh()
                self._fill()
                return
        # remove any existing assignment for this source
        self._assignments.pop(source, None)
        self._assignments[source] = target
        self._notice = f"assigned {source:03d} -> {target:03d}"
        self._refresh()
        self._fill()

    # --- actions ------------------------------------------------------

    def action_toggle_assign(self) -> None:
        if self._slot_entry:
            self._commit_slot_entry()
            return
        program = self._focused_program()
        if program is None:
            return
        source = program.slot
        if source in self._assignments:
            del self._assignments[source]
            self._notice = f"unassigned {source:03d}"
            self._refresh()
            self._fill()
            return
        free = self._next_free_target()
        if free is None:
            self._say("no free target slot", refused=True)
            return
        self._assignments[source] = free
        self._notice = f"assigned {source:03d} -> {free:03d}"
        self._refresh()
        self._fill()
        # advance cursor
        table = self.query_one("#single-table", DataTable)
        if table.cursor_row is not None and table.cursor_row + 1 < len(self._programs):
            table.move_cursor(row=table.cursor_row + 1)

    def action_unassign(self) -> None:
        if self._slot_entry:
            source = self._slot_entry_source
            self._slot_entry = ""
            self._slot_entry_source = None
            self._notice = "slot entry cancelled"
            self._refresh()
            self._fill()
            return
        program = self._focused_program()
        if program is None:
            return
        source = program.slot
        if source not in self._assignments:
            self._notice = f"{source:03d} not assigned"
            self._refresh()
            self._fill()
            return
        del self._assignments[source]
        self._notice = f"unassigned {source:03d}"
        self._refresh()
        self._fill()

    def action_assign_all(self) -> None:
        if self._slot_entry:
            self._commit_slot_entry()
        for program in self._programs:
            if program.slot in self._assignments:
                continue
            free = self._next_free_target()
            if free is None:
                self._say("no free target slot", refused=True)
                return
            self._assignments[program.slot] = free
        self._notice = "assigned all unassigned rows"
        self._refresh()
        self._fill()

    def action_clear_all(self) -> None:
        self._assignments.clear()
        self._slot_entry = ""
        self._slot_entry_source = None
        self._notice = "cleared all assignments"
        self._refresh()
        self._fill()

    def action_preview(self) -> None:
        program = self._focused_program()
        if program is None:
            return
        if self._on_preview is not None:
            self._on_preview(program.record)
            self._notice = "loaded into the edit buffer; nothing stored"
        else:
            self._notice = "preview is not wired"
        self._refresh()
        self._fill()

    def action_toggle_gate(self) -> None:
        armed = self._gate.toggle()
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._show_gate()
        self._refresh()
        self._fill()

    def action_confirm(self) -> None:
        if not self._assignments:
            self._say("nothing selected; nothing sent", refused=True)
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        # validate shape via planner
        pairs = [(src, tgt) for src, tgt in self.assignments]
        try:
            importplan.plan_single(self._bank, pairs)
        except ValueError as exc:
            self._say(str(exc), refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._first_prompt(), danger=True),
            self._first_answered,
        )

    def _first_prompt(self) -> str:
        count = len(self._assignments)
        return f"import {count} programs into the {_TARGET_BANK} bank?"

    def _second_prompt(self) -> str:
        lines = self._overwrite_lines()
        return "these User slots will be overwritten:\n" + "\n".join(lines)

    def _overwrite_lines(self) -> list[str]:
        lines: list[str] = []
        names = self._catalog()
        for source_slot, target in self.assignments:
            program = self._program_for_slot(source_slot)
            new_name = program.name if program is not None else f"source {source_slot}"
            old = self._old_name(target) if names is not None else None
            old_text = literal(old) if old is not None else "(free)"
            lines.append(f"User {target:03d}: {old_text} -> {literal(new_name)}")
        return lines

    def _first_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing imported")
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._second_prompt(), danger=True),
            self._second_answered,
        )

    def _second_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing imported")
            return
        refusal = self._gate.check()
        self._show_gate()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.dismiss(self.assignments)

    def action_cancel(self) -> None:
        if self._slot_entry:
            self._slot_entry = ""
            self._slot_entry_source = None
            self._notice = "slot entry cancelled"
            self._refresh()
            self._fill()
            return
        self.dismiss(None)

    # --- query aliasing -----------------------------------------------

    def _map_selector(self, selector: str) -> str:
        stripped = selector.strip()
        if not stripped.startswith("#"):
            return selector
        name = stripped[1:]
        if name in _TABLE_ALIASES:
            return "#single-table"
        if name in _STATUS_ALIASES:
            return "#single-status"
        if name in _GATE_ALIASES:
            return "#single-gate"
        return selector

    def query(self, *args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], str):
            args = (self._map_selector(args[0]), *args[1:])
        return super().query(*args, **kwargs)

    def query_one(self, *args: Any, **kwargs: Any) -> Any:
        if args and isinstance(args[0], str):
            args = (self._map_selector(args[0]), *args[1:])
        return super().query_one(*args, **kwargs)


def _label_of(bank: Any) -> str:
    if bank is None:
        return "source bank"
    label = getattr(bank, "label", None)
    if label is not None:
        return str(label)
    return "source bank"


def _program_name(program: Any) -> str:
    if program is None:
        return ""
    return str(getattr(program, "name", ""))


# Aliases for the names a caller or a test might use.
SingleScreen = SingleMappingScreen
MappingScreen = SingleMappingScreen
SingleImportScreen = SingleMappingScreen
ImportSingleScreen = SingleMappingScreen
