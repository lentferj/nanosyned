# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

r"""The append import: free slots, cut list, and two answers."""

from __future__ import annotations

import re
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import importplan
from nanosyned.editor import EditGate
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen

__all__ = ["MANUAL", "AppendBankScreen"]

MANUAL = "manual"


class AppendBankScreen(ModalScreen[importplan.ImportPlan | str | None]):
    DEFAULT_CSS = """
    AppendBankScreen { align: center middle; }
    AppendBankScreen > Vertical {
        width: 96; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    AppendBankScreen #append-title { height: auto; }
    AppendBankScreen #append-source { height: auto; color: $text-muted; }
    AppendBankScreen #append-gate { height: auto; text-style: bold; }
    AppendBankScreen DataTable { height: 1fr; }
    AppendBankScreen #append-plan { height: auto; color: $text-muted; }
    AppendBankScreen #append-warning { height: auto; }
    AppendBankScreen #append-status { height: auto; color: $text; padding-top: 1; }
    AppendBankScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("w", "toggle_gate", "Write gate"),
        Binding("s", "manual", "Single/multiple", priority=True),
        Binding("ctrl+s", "confirm", "Append", priority=True),
    ]

    def __init__(
        self,
        bank=None,
        plan=None,
        start=127,
        gate=None,
        catalog=None,
    ) -> None:
        super().__init__()
        self._bank = bank
        self._plan = (
            plan
            if plan is not None
            else importplan.ImportPlan(steps=(), skipped=(), overwrites=())
        )
        self._start = int(start)
        self._gate = gate if gate is not None else EditGate()
        self._catalog_arg = catalog
        self._notice = ""

    @property
    def plan(self):
        return self._plan

    @property
    def gate(self):
        return self._gate

    @property
    def bank(self):
        return self._bank

    @property
    def start(self):
        return self._start

    def compose(self) -> ComposeResult:
        with Vertical(id="append-dialog"):
            yield Label("", id="append-title")
            yield Label("", id="append-source")
            yield Static("", id="append-gate")
            yield DataTable(id="append-table", cursor_type="row")
            yield Static("", id="append-plan")
            yield Static("", id="append-warning")
            yield Static("", id="append-status")
            yield Static(
                (
                    "[dim]w gate · ctrl+s append · s single/multiple "
                    "· esc / q cancel[/dim]"
                ),
                id="append-note",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#append-table", DataTable)
        for label, key in (
            ("#", "number"),
            ("name", "name"),
            ("target", "target"),
            ("state", "state"),
        ):
            table.add_column(label, key=key)
        self._fill()

    def _fill(self) -> None:
        table = self.query_one("#append-table", DataTable)
        for index, row in enumerate(self._rows()):
            table.add_row(
                row[0],
                literal(row[1]),
                row[2],
                literal(row[3]),
                key=f"row:{index}",
            )
        if table.row_count:
            table.move_cursor(row=0)
            table.focus()
        self._refresh()

    def _refresh(self) -> None:
        self.query_one("#append-title", Label).update(
            f"[b]Append to free slots[/b]  {literal(self._bank_label())}"
        )
        self.query_one("#append-source", Label).update(
            f"Source bank: {literal(self._bank_label())}  ·  destination: User"
        )
        self._show_gate()
        self.query_one("#append-plan", Static).update(self._plan_line())
        self.query_one("#append-warning", Static).update(self._warning_line())
        self.query_one("#append-status", Static).update(self._status())

    def _show_gate(self) -> None:
        state = "ARMED" if self._gate.armed else "locked"
        suffix = "" if self._gate.armed else " — press w to arm it"
        self.query_one("#append-gate", Static).update(f"Write gate: {state}{suffix}")

    def _plan_line(self) -> str:
        source_count = self._source_count()
        free_count = max(0, 127 - self._start)
        range_text = f"{self._start:03d}-126" if free_count else "none"
        cut_count = self._cut_count()
        text = (
            f"{source_count} source program(s); {free_count} free slot(s) "
            f"({range_text}); {cut_count} cut"
        )
        return f"[dim]{text}[/dim]"

    def _warning_line(self) -> str:
        cuts = self._cut_entries()
        if not cuts:
            return ""
        shown = cuts[:3]
        parts = [f"{slot} {literal(name)}" for slot, name in shown]
        text = ", ".join(parts)
        remaining = len(cuts) - len(shown)
        if remaining > 0:
            text += f", and {remaining} more"
        return f"[red]cut: {text}[/red]"

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if not self._plan.steps:
            return (
                "[b]refused:[/b] no free slots; run N init bank "
                "or choose single/multiple"
            )
        return "[dim]nothing is sent until ctrl+s and two confirmations[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        if refused:
            self._notice = f"[b]refused:[/b] {literal(sentence)}"
        else:
            self._notice = literal(sentence)
        self._refresh()

    def _rows(self):
        if self._bank is not None:
            return self._bank_rows()
        return self._plan_rows()

    def _bank_rows(self):
        programs = sorted(self._bank.programs.values(), key=lambda p: p.index)
        program_steps = [s for s in self._plan.steps if s.kind == "program"]
        non127 = [p for p in programs if p.slot != 127]
        rows = []
        for i, program in enumerate(non127):
            if i < len(program_steps):
                target = program_steps[i].target
                target_str = f"[b]{target:03d}[/b]" if target is not None else "---"
                state = "free (Init)"
            else:
                target_str = "---"
                state = "cut"
            rows.append((f"{program.index:03d}", program.name, target_str, state))
        return rows

    def _plan_rows(self):
        rows = []
        program_steps = [s for s in self._plan.steps if s.kind == "program"]
        for index, step in enumerate(program_steps):
            target = step.target
            target_str = f"[b]{target:03d}[/b]" if target is not None else "---"
            name = step.source_label
            rows.append((f"{index:03d}", name, target_str, "free (Init)"))
        return rows

    def _bank_label(self):
        if self._bank is not None:
            return self._bank.label
        return "source bank"

    def _source_count(self):
        if self._bank is not None:
            return len(
                [
                    program
                    for program in self._bank.programs.values()
                    if program.slot != 127
                ]
            )
        program_steps = [s for s in self._plan.steps if s.kind == "program"]
        return len(program_steps) + self._cut_count()

    def _cut_count(self):
        return len(self._cut_entries())

    def _cut_entries(self):
        if self._bank is not None:
            programs = [
                program
                for program in sorted(
                    self._bank.programs.values(), key=lambda p: p.index
                )
                if program.slot != 127
            ]
            steps = [s for s in self._plan.steps if s.kind == "program"]
            return [
                (f"{program.slot:03d}", program.name)
                for program in programs[len(steps) :]
            ]
        entries = []
        for sentence in self._plan.skipped:
            match = re.search(r'source\s+(\d+)\s+"(.*?)"\s+is cut', sentence)
            if match:
                entries.append((match.group(1), match.group(2)))
        return entries

    def _first_prompt(self):
        m_count = len([s for s in self._plan.steps if s.kind == "program"])
        k_count = self._cut_count()
        if k_count > 0:
            return f"Append {m_count} programs? {k_count} will be cut."
        return f"Append {m_count} programs?"

    def _second_prompt(self):
        lines = []
        program_steps = [s for s in self._plan.steps if s.kind == "program"]
        source_names = self._source_names_for_steps()
        for step, name in zip(program_steps, source_names, strict=False):
            target = step.target
            t = f"{target:03d}" if target is not None else "---"
            lines.append(f"{t} <- {literal(name)}")
        if len(lines) > 10:
            extra = len(lines) - 10
            lines = [*lines[:10], f"and {extra} more"]
        lines.append("The current Init placeholders are backed up first.")
        return "\n".join(lines)

    def _source_names_for_steps(self):
        if self._bank is not None:
            programs = [
                p
                for p in sorted(self._bank.programs.values(), key=lambda p: p.index)
                if p.slot != 127
            ]
            steps = [s for s in self._plan.steps if s.kind == "program"]
            names = []
            for i, _ in enumerate(steps):
                if i < len(programs):
                    names.append(programs[i].name)
                else:
                    names.append("?")
            return names
        return [s.source_label for s in self._plan.steps if s.kind == "program"]

    def action_confirm(self):
        if not self._plan.steps:
            self._say(
                "no free slots; run N init bank or choose single/multiple", refused=True
            )
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._first_prompt(), danger=True),
            self._first_answered,
        )

    def _first_answered(self, confirmed):
        if not confirmed:
            self._say("nothing appended")
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._second_prompt(), danger=True),
            self._second_answered,
        )

    def _second_answered(self, confirmed):
        if not confirmed:
            self._say("nothing appended")
            return
        refusal = self._gate.check()
        self._show_gate()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.dismiss(self._plan)

    def action_toggle_gate(self):
        armed = self._gate.toggle()
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._refresh()

    def action_manual(self):
        self.dismiss(MANUAL)

    def action_cancel(self):
        self.dismiss(None)
