# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

r"""The whole-bank import: every program, where it lands, and two answers.

This is the screen the flow pushes once the user has chosen whole bank. It
is a **question, not a write**: it holds a plan somebody else built, shows
every program the plan carries (and every program the plan skips), reads the
destination names from the catalog for its ``state`` column, and answers the
app with the same :class:`~nano.importplan.ImportPlan` when the user has
confirmed twice. It has no device, no worker and no clock, so a unit test can
walk every refusal without a MIDI port.

**The gate is held, not copied.** When the app hands its
:class:`~nanosyned.editor.EditGate` in, ``w`` flips that object and
``ctrl+s`` refuses while it is locked, with a sentence on this screen's own
line. The app still asks its gate again when the plan comes back: the gate
can be closed between the second confirmation and the worker. A screen
pushed without a gate gets one of its own, so ``w`` means the same thing in
a test.

**Two confirmations, and the gate between them.** ``ctrl+s`` first asks
"import N programs into the User bank?", then lists every destination by the
name it holds now and the name that will replace it. A refusal or a cancel
at either question leaves the screen where it was and answers nothing; the
gate is checked again after each answer, so arming the screen and then
locking the app's gate cannot slip a write through. Only after the second
``y`` does the screen dismiss with the plan.

**A source slot 127 is shown, not hidden.** It is hardwired silent on this
unit, so the whole-bank planner leaves it out with a sentence. The table
still shows the row, marked ``skipped: hardwired silent``, because a file
that carries 128 programs should not look like a file that carries 127.

**Names are bytes somebody else wrote.** Every program name and every old
name in the table and in the confirmation prompt goes through
:func:`nanosyned.text.literal` before it meets a markup parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import catalog as cat
from nano import importing, importplan
from nano import messages as m
from nano import records as rec
from nanosyned.editor import EditGate
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen

__all__ = ["WholeBankScreen"]

#: The bank an import writes. Only the User bank is writable on this unit.
TARGET_BANK = "User"

#: The words the screen uses for the hardwired row the planner skips.
SKIPPED_PROGRAM = "skipped: hardwired silent"


@dataclass(frozen=True)
class _Row:
    """One line of the preview, already built for the table."""

    number: str
    name: str
    target: str
    state: str
    assigned: bool


class WholeBankScreen(ModalScreen[importplan.ImportPlan | None]):
    """Every program in one source bank, and the plan to write it.

    The plan is handed in already built, because the planner is pure and the
    flow has already chosen the bank. ``bank`` is optional: with it the
    table shows *every* program in file order, including the hardwired one
    the plan skips, and with it absent the rows come from the plan's steps
    and its skip sentences. ``catalog`` is optional too; it supplies the old
    names in the ``state`` column and in the second confirmation. With no
    catalog the column says which slot a row will overwrite rather than
    inventing a name the unit never supplied.

    ``ctrl+s`` returns the plan after the two confirmations; ``esc`` and
    ``q`` return ``None``. **The screen sends nothing itself** -- the app
    owns the destination read, the backup, the store and the read-back.
    """

    DEFAULT_CSS = """
    WholeBankScreen { align: center middle; }
    WholeBankScreen > Vertical {
        width: 96; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    WholeBankScreen #bank-title { height: auto; }
    WholeBankScreen #bank-source { height: auto; color: $text-muted; }
    WholeBankScreen #bank-gate { height: auto; text-style: bold; }
    WholeBankScreen DataTable { height: 1fr; }
    WholeBankScreen #bank-plan { height: auto; color: $text-muted; }
    WholeBankScreen #bank-status { height: auto; color: $text; padding-top: 1; }
    WholeBankScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("w", "toggle_gate", "Write gate"),
        # ``ctrl+s`` starts the import, like every screen in the family.
        # Enter is deliberately absent: the focused table consumes it.
        Binding("ctrl+s", "confirm", "Import", priority=True),
    ]

    def __init__(
        self,
        plan: importplan.ImportPlan,
        *,
        bank: importing.SourceBank | None = None,
        bank_label: str | None = None,
        gate: EditGate | None = None,
        catalog: cat.Catalog | None = None,
    ) -> None:
        super().__init__()
        self._plan = plan
        #: The source bank, when the caller still has it. It names the
        #: skipped row and gives the table the file's own order.
        self._bank = bank
        #: The source bank's label, or one inferred from the plan's labels.
        self._bank_label = bank_label or _label_from(plan, bank)
        #: The app's fence, held so this screen and the app cannot disagree.
        #: A screen pushed without one still gets a gate of its own, so `w`
        #: means the same thing everywhere; the app re-asks its own gate
        #: before it writes.
        self._gate = gate if gate is not None else EditGate()
        #: An injected catalog wins over the app's, which is what a test
        #: wants and what a caller with a second catalog would mean.
        self._catalog_arg = catalog
        self._notice = ""

    @property
    def plan(self) -> importplan.ImportPlan:
        """The plan this screen would answer with now."""
        return self._plan

    @property
    def gate(self) -> EditGate:
        """The gate this screen holds."""
        return self._gate

    @property
    def bank_label(self) -> str:
        """The source bank's label, as the title shows it."""
        return self._bank_label

    # --- layout --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="bank-dialog"):
            yield Label("", id="bank-title")
            yield Label("", id="bank-source")
            yield Static("", id="bank-gate")
            yield DataTable(id="bank-table", cursor_type="row")
            yield Static("", id="bank-plan")
            yield Static("", id="bank-status")
            yield Static(
                "[dim]w gate · ctrl+s import · esc / q cancel. The table "
                "shows every program the file carries; a row marked skipped "
                "is never written.[/dim]",
                id="bank-note",
                classes="note",
            )

    def on_mount(self) -> None:
        table = self.query_one("#bank-table", DataTable)
        for label, key in (
            ("#", "number"),
            ("name", "name"),
            ("target", "target"),
            ("state", "state"),
        ):
            table.add_column(label, key=key)
        self._fill()

    def _fill(self) -> None:
        """Build the preview once; nothing on this screen changes a row."""
        table = self.query_one("#bank-table", DataTable)
        for index, row in enumerate(self._rows()):
            table.add_row(
                row.number,
                literal(row.name),
                row.target,
                literal(row.state),
                key=f"row:{index}",
            )
        if table.row_count:
            table.move_cursor(row=0)
        table.focus()
        self._refresh()

    def _refresh(self) -> None:
        """Redraw the title, the gate line, the plan line and the status."""
        self.query_one("#bank-title", Label).update(
            f"[b]Import whole bank[/b]  {literal(self._bank_label)}"
        )
        self.query_one("#bank-source", Label).update(
            f"Source bank: {literal(self._bank_label)}  ·  destination: {TARGET_BANK}"
        )
        self._show_gate()
        self.query_one("#bank-plan", Static).update(self._plan_line())
        self.query_one("#bank-status", Static).update(self._status())

    def _show_gate(self) -> None:
        """Put the gate's current state on its own line."""
        state = "ARMED" if self._gate.armed else "locked"
        suffix = "" if self._gate.armed else " — press w to arm it"
        self.query_one("#bank-gate", Static).update(f"Write gate: {state}{suffix}")

    def _plan_line(self) -> str:
        """The count line: programs, other parts, and what is skipped."""
        programs = self._program_count()
        parts = len(self._plan.steps) - programs
        text = f"Plan: {programs} program(s)"
        if parts:
            text += f" · {parts} other record(s)"
        if self._plan.skipped:
            text += f" · {len(self._plan.skipped)} skipped"
        return f"[dim]{text}[/dim]"

    def _status(self) -> str:
        if self._notice:
            return self._notice
        if not self._plan.steps:
            return "[b]refused:[/b] nothing selected; nothing sent"
        return "[dim]nothing is sent until ctrl+s and two confirmations[/dim]"

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        """Put one sentence in the screen's own status row."""
        if refused:
            self._notice = f"[b]refused:[/b] {literal(sentence)}"
        else:
            self._notice = literal(sentence)
        self._refresh()

    # --- the table's rows ----------------------------------------------

    def _rows(self) -> list[_Row]:
        """Every program row, then the other parts, then non-program skips."""
        if self._bank is not None:
            rows = self._bank_rows()
            rows.extend(self._part_rows(start=len(rows)))
            return rows
        rows = self._plan_rows()
        rows.extend(self._part_rows(start=len(rows)))
        rows.extend(self._skip_rows(start=len(rows)))
        return rows

    def _bank_rows(self) -> list[_Row]:
        """The bank's programs in file order, including the hardwired one."""
        targets = {
            step.target
            for step in self._plan.steps
            if step.kind == "program" and step.target is not None
        }
        rows: list[_Row] = []
        bank = self._bank
        if bank is None:
            return rows
        for program in sorted(bank.programs.values(), key=lambda p: p.index):
            assigned = program.slot in targets
            rows.append(self._program_row(program, assigned=assigned))
        return rows

    def _plan_rows(self) -> list[_Row]:
        """Program rows from the plan, for a caller that kept no bank."""
        rows: list[_Row] = []
        for index, step in enumerate(
            step for step in self._plan.steps if step.kind == "program"
        ):
            rows.append(self._step_row(index, step))
        return rows

    def _program_row(
        self,
        program: importing.SourceProgram,
        *,
        assigned: bool,
    ) -> _Row:
        target = f"{program.slot:03d}" if assigned else "---"
        state = self._program_state(program.slot, assigned=assigned)
        return _Row(
            number=f"{program.index:03d}",
            name=program.name,
            target=f"[b]{target}[/b]" if assigned else target,
            state=state,
            assigned=assigned,
        )

    def _step_row(self, index: int, step: importplan.Step) -> _Row:
        assigned = step.target is not None
        target = "---" if step.target is None else f"{step.target:03d}"
        state = self._program_state(step.target, assigned=assigned)
        return _Row(
            number=f"{index:03d}",
            name=self._step_name(step),
            target=f"[b]{target}[/b]" if assigned else target,
            state=state,
            assigned=assigned,
        )

    def _part_rows(self, *, start: int) -> list[_Row]:
        """Effects, mixes and global rows the plan carries."""
        rows: list[_Row] = []
        for offset, step in enumerate(
            step for step in self._plan.steps if step.kind != "program"
        ):
            if step.target is None:
                target = "---"
                state = "the global settings will be overwritten"
            else:
                target = f"[b]{step.target:03d}[/b]"
                state = self._part_state(step)
            rows.append(
                _Row(
                    number=f"{start + offset:03d}",
                    name=step.source_label,
                    target=target,
                    state=state,
                    assigned=True,
                )
            )
        return rows

    def _skip_rows(self, *, start: int) -> list[_Row]:
        """Rows for the plan's skip sentences when no bank was handed in."""
        return [
            _Row(
                number=f"{start + offset:03d}",
                name=_skip_name(sentence),
                target="---",
                state=SKIPPED_PROGRAM if "hardwired silent" in sentence else "skipped",
                assigned=False,
            )
            for offset, sentence in enumerate(self._plan.skipped)
        ]

    def _program_state(self, target: int | None, *, assigned: bool) -> str:
        """``free``, ``used: Old Name`` or the slot a row will overwrite."""
        if not assigned:
            return SKIPPED_PROGRAM
        names = self._catalog()
        if names is None:
            return f"overwrites {target:03d}" if target is not None else "free"
        return self._state_from(names, target)

    def _part_state(self, step: importplan.Step) -> str:
        """A part's state: the slot it will overwrite, without a name.

        The catalog in this browser names User programs; it knows nothing
        honest about an effects or mix slot, so this column does not borrow
        a program's name for one.
        """
        if step.target is None:
            return "the global settings will be overwritten"
        return f"overwrites {step.target:03d}"

    def _state_from(self, names: cat.Catalog, target: int | None) -> str:
        if target is None:
            return "free"
        old = _old_name(names, target)
        if old is None:
            return "free"
        return f"used: {old}"

    # --- the plan's names ----------------------------------------------

    def _program_count(self) -> int:
        return sum(1 for step in self._plan.steps if step.kind == "program")

    def _step_name(self, step: importplan.Step) -> str:
        if step.kind != "program":
            return step.source_label
        return _record_name(step.record)

    def _catalog(self) -> cat.Catalog | None:
        """The catalog for old names: the injected one, else the app's."""
        if self._catalog_arg is not None:
            return self._catalog_arg
        return getattr(self.app, "catalog", None)

    # --- the two confirmations -----------------------------------------

    def _first_prompt(self) -> str:
        """The count question: what, and how many, into which bank."""
        programs = self._program_count()
        prompt = f"import {programs} programs into the {TARGET_BANK} bank?"
        parts = len(self._plan.steps) - programs
        if parts:
            prompt += f"\nand {parts} other record(s) from the same bank"
        return prompt

    def _second_prompt(self) -> str:
        """The name question: every destination, old name, and new name."""
        lines = self._overwrite_lines()
        return "these User slots will be overwritten:\n" + "\n".join(lines)

    def _overwrite_lines(self) -> list[str]:
        """One line per step, by old name and new name, plus every skip."""
        lines: list[str] = []
        names = self._catalog()
        for step in self._plan.steps:
            where = (
                "global settings" if step.target is None else f"User {step.target:03d}"
            )
            old = (
                _old_name(names, step.target)
                if names is not None
                and step.kind == "program"
                and step.target is not None
                else None
            )
            new = self._step_name(step)
            if old is not None:
                old_text = literal(old)
            else:
                old_text = "(free)" if step.kind == "program" else "(existing)"
            lines.append(f"{where}: {old_text} -> {literal(new)}")
        for sentence in self._plan.skipped:
            lines.append(f"skipped: {literal(sentence)}")
        return lines

    def action_confirm(self) -> None:
        """``ctrl+s``: start the two questions, or say why not."""
        if not self._plan.steps:
            self._say("nothing selected; nothing sent", refused=True)
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._first_prompt(), danger=True),
            self._first_answered,
        )

    def _first_answered(self, confirmed: bool | None) -> None:
        """The count question's answer: ask the names, or stay here."""
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
        """The name question's answer: re-check the gate, then answer the app."""
        if not confirmed:
            self._say("nothing imported")
            return
        # Asked again, and not only at ``ctrl+s``: ``w`` can be pressed on
        # the app while this dialog is up, and the gate is the last word.
        refusal = self._gate.check()
        self._show_gate()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.dismiss(self._plan)

    # --- the keys ------------------------------------------------------

    def action_toggle_gate(self) -> None:
        """``w``: flip the app's shared gate; the flip itself sends nothing."""
        armed = self._gate.toggle()
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._refresh()

    def action_cancel(self) -> None:
        """``esc`` and ``q``: nothing was imported."""
        self.dismiss(None)


def _record_name(record: bytes) -> str:
    """The program's name, or ``?`` when the record cannot be read."""
    try:
        return rec.program_name(record).strip() or "?"
    except m.ProtocolError:
        return "?"


def _old_name(names: cat.Catalog, target: int) -> str | None:
    """The destination's current name, or ``None`` when it has none."""
    name = names.display_name("USER", target)
    return None if name == cat.UNNAMED else name


def _skip_name(sentence: str) -> str:
    """The row name for a plan's skip sentence, when no bank was handed in."""
    parts = sentence.split()
    if len(parts) >= 2 and parts[0] == "source":
        return f"source {parts[1]}"
    return sentence


def _label_from(
    plan: importplan.ImportPlan,
    bank: importing.SourceBank | None,
) -> str:
    """The source bank's label, inferred when the caller did not name one."""
    if bank is not None:
        return bank.label
    for step in plan.steps:
        if step.kind == "program" and " program " in step.source_label:
            return step.source_label.rsplit(" program ", 1)[0]
    return "source bank"
