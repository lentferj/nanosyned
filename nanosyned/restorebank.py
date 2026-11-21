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

r"""The full-restore confirmation screen.

This is a **question, not a write**: it holds a plan built from a file, the
app's shared write gate, and answers the app with that plan once the user
has confirmed twice. It has no device, no worker and no clock, so a unit
test can walk every refusal without a MIDI port.

A full restore is a batch of up to 356 stores across four record kinds. The
screen therefore shows the counts and the exclusions rather than pretending
356 rows fit on one modal; the per-destination old name is still preserved
by the unconditional backup the fence takes before each store.
"""

from __future__ import annotations

from collections import Counter
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from nano import importplan
from nanosyned.editor import EditGate
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen

__all__ = ["FullRestoreScreen"]


class FullRestoreScreen(ModalScreen[importplan.ImportPlan | None]):
    """Confirm a full restore from one selected file, twice.

    ``ctrl+s`` asks how many records and which kinds the file carries, then
    states that every destination is read and backed up before it is
    replaced. ``esc`` and ``q`` cancel. The screen sends nothing itself --
    the app owns the destination read, the backup, the store, the read-back
    and the undo entry.
    """

    DEFAULT_CSS = """
    FullRestoreScreen { align: center middle; }
    FullRestoreScreen > Vertical {
        width: 84; height: auto; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    FullRestoreScreen #restore-title { height: auto; }
    FullRestoreScreen #restore-path { height: auto; color: $text-muted; }
    FullRestoreScreen #restore-summary { height: auto; padding-top: 1; }
    FullRestoreScreen #restore-gate { height: auto; text-style: bold; padding-top: 1; }
    FullRestoreScreen #restore-status { height: auto; padding-top: 1; }
    FullRestoreScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("w", "toggle_gate", "Write gate"),
        Binding("ctrl+s", "confirm", "Restore", priority=True),
    ]

    def __init__(
        self,
        plan: importplan.ImportPlan,
        *,
        path: str,
        gate: EditGate | None = None,
    ) -> None:
        super().__init__()
        self._plan = plan
        self._path = path
        self._gate = gate if gate is not None else EditGate()
        self._notice = ""

    @property
    def plan(self) -> importplan.ImportPlan:
        """The plan this screen would answer with now."""
        return self._plan

    @property
    def path(self) -> str:
        """The file the plan was read from."""
        return self._path

    @property
    def gate(self) -> EditGate:
        """The gate this screen holds."""
        return self._gate

    def compose(self) -> ComposeResult:
        with Vertical(id="restore-dialog"):
            yield Label("Restore full backup", id="restore-title")
            yield Label("", id="restore-path")
            yield Static("", id="restore-summary")
            yield Static("", id="restore-gate")
            yield Static("", id="restore-status")
            yield Static(
                "[dim]Every destination is read and backed up before it is replaced.\n"
                "Program 127 and mix 100 are never destinations.\n"
                "w gate · ctrl+s restore · esc / q cancel[/dim]",
                id="restore-note",
                classes="note",
            )

    def on_mount(self) -> None:
        self.query_one("#restore-path", Label).update(literal(self._path))
        self._refresh()

    def _counts(self) -> Counter[str]:
        return Counter(step.kind for step in self._plan.steps)

    def _summary_line(self) -> str:
        counts = self._counts()
        parts = []
        if counts["program"]:
            parts.append(f"{counts['program']} user program(s) 000-126")
        if counts["effects"]:
            parts.append(f"{counts['effects']} effects patch(es) 000-127")
        if counts["mix"]:
            parts.append(f"{counts['mix']} mix(es) 000-099")
        if counts["global"]:
            parts.append("the global settings")
        text = " · ".join(parts) if parts else "no usable records"
        if self._plan.skipped:
            text += f" · {len(self._plan.skipped)} skipped"
        return text

    def _refresh(self) -> None:
        state = "ARMED" if self._gate.armed else "locked"
        suffix = "" if self._gate.armed else " — press w to arm it"
        self.query_one("#restore-gate", Static).update(f"Write gate: {state}{suffix}")
        self.query_one("#restore-summary", Static).update(self._summary_line())
        if self._notice:
            self.query_one("#restore-status", Static).update(self._notice)
        else:
            self.query_one("#restore-status", Static).update(
                "[dim]nothing is sent until ctrl+s and two confirmations[/dim]"
            )

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        if refused:
            self._notice = f"[b]refused:[/b] {literal(sentence)}"
        else:
            self._notice = literal(sentence)
        self._refresh()

    def _first_prompt(self) -> str:
        return (
            f"restore {len(self._plan.steps)} record(s) from "
            f"{literal(self._path)}?\n{self._summary_line()}"
        )

    def _second_prompt(self) -> str:
        skipped = ""
        if self._plan.skipped:
            skipped = "\n" + "\n".join(literal(s) for s in self._plan.skipped)
        return (
            "every destination is read and backed up before it is replaced."
            f"{skipped}\nrestore now?"
        )

    def action_confirm(self) -> None:
        if not self._plan.steps:
            self._say("nothing to restore; nothing sent", refused=True)
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._first_prompt(), danger=True), self._first_answered
        )

    def _first_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing restored")
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(self._second_prompt(), danger=True), self._second_answered
        )

    def _second_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing restored")
            return
        refusal = self._gate.check()
        self._refresh()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.dismiss(self._plan)

    def action_toggle_gate(self) -> None:
        armed = self._gate.toggle()
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._refresh()

    def action_cancel(self) -> None:
        self.dismiss(None)
