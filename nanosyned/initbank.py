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
# nanosyned is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.

r"""The init-bank confirmation screen.

This is a **question, not a write**: it holds the app's write gate, shows
the fixed copy for initialising the User bank, and answers the app with
``True`` once the user has confirmed twice. It has no device, no worker and
no clock, so a unit test can walk every refusal without a MIDI port.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from nanosyned.editor import EditGate
from nanosyned.text import literal
from vinsynlib.ui.confirm import ConfirmScreen

__all__ = ["InitBankScreen"]


class InitBankScreen(ModalScreen[bool | None]):
    """Confirm the init of User programs 000-126, twice.

    ``ctrl+s`` asks first whether to initialise all 127 User programs
    000-126, then names the range and count and says that every destination
    is read and backed up first. ``esc`` and ``q`` return ``None``. The
    screen sends nothing itself -- the app owns the gate, the worker and the
    store.
    """

    DEFAULT_CSS = """
    InitBankScreen { align: center middle; }
    InitBankScreen > Vertical {
        width: 72; height: auto; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    InitBankScreen #init-title { height: auto; }
    InitBankScreen #init-text { height: auto; color: $text-muted; padding-top: 1; }
    InitBankScreen #init-gate { height: auto; text-style: bold; padding-top: 1; }
    InitBankScreen #init-status { height: auto; padding-top: 1; }
    InitBankScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("w", "toggle_gate", "Write gate"),
        Binding("ctrl+s", "confirm", "Init", priority=True),
    ]

    def __init__(self, *, gate: EditGate | None = None) -> None:
        super().__init__()
        self._gate = gate if gate is not None else EditGate()
        self._notice = ""

    @property
    def gate(self) -> EditGate:
        return self._gate

    def compose(self) -> ComposeResult:
        with Vertical(id="init-dialog"):
            yield Label("Initialise the User bank", id="init-title")
            yield Static(
                "Programs 000-126 will be replaced with the unit's Init "
                "program. Program 127 (Off) is untouched. Every replaced "
                "slot is backed up first. One z restores the programs, not "
                "the favourite marks; those are hidden, and their old content "
                "and annotations stay in the preset memory.",
                id="init-text",
            )
            yield Static("", id="init-gate")
            yield Static("", id="init-status")
            yield Static(
                "[dim]w gate · ctrl+s init · esc / q cancel[/dim]",
                id="init-note",
                classes="note",
            )

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        state = "ARMED" if self._gate.armed else "locked"
        suffix = "" if self._gate.armed else " — press w to arm it"
        self.query_one("#init-gate", Static).update(f"Write gate: {state}{suffix}")
        if self._notice:
            self.query_one("#init-status", Static).update(self._notice)
        else:
            self.query_one("#init-status", Static).update(
                "[dim]nothing is sent until ctrl+s and two confirmations[/dim]"
            )

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        if refused:
            self._notice = f"[b]refused:[/b] {literal(sentence)}"
        else:
            self._notice = literal(sentence)
        self._refresh()

    def action_confirm(self) -> None:
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen("Initialise all 127 User programs 000-126?", danger=True),
            self._first_answered,
        )

    def _first_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing initialised")
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.app.push_screen(
            ConfirmScreen(
                "User programs 000-126 (127 programs): all 127 "
                "destinations are read and backed up first.",
                danger=True,
            ),
            self._second_answered,
        )

    def _second_answered(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._say("nothing initialised")
            return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self.dismiss(True)

    def action_toggle_gate(self) -> None:
        armed = self._gate.toggle()
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._refresh()

    def action_cancel(self) -> None:
        self.dismiss(None)
