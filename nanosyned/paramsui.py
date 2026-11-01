# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
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

"""Direct parameter edits through the ``10`` MIDI Edit message."""

from __future__ import annotations

import time
from typing import Any, ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Label, Static

from nano import params
from nano import records as rec
from nanosyned.screens import PromptScreen
from nanosyned.text import literal
from vinsynlib.ui.modals import ChoiceScreen


class ParameterScreen(ModalScreen[None]):
    """Edit verified parameters through MIDI Edit (``10``) with read-back."""

    DEFAULT_CSS = """
    ParameterScreen { align: center middle; }
    ParameterScreen > Vertical {
        width: 110; height: 90%; border: thick $primary;
        background: $surface; padding: 1 2;
    }
    ParameterScreen DataTable { height: 1fr; }
    ParameterScreen .note { height: auto; color: $text-muted; padding-top: 1; }
    ParameterScreen #param-status { height: auto; color: $text; padding-top: 1; }
    ParameterScreen #param-warning { height: auto; color: $warning; padding-top: 1; }
    """

    BINDINGS: ClassVar[list[Any]] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("e", "edit_value", "Edit"),
        Binding("w", "toggle_gate", "Write gate"),
        Binding("m", "cycle_mode", "Mode"),
    ]

    def __init__(
        self, device, gate, *, mode: str = "program", channel: int = 0
    ) -> None:
        super().__init__()
        self._device = device
        self._gate = gate
        self._mode = mode
        self._channel = channel
        self._notice = ""
        self._values: list[int | None] = []
        self._params = [
            self._resolved(param) for param in params.verified_params(self._mode)
        ]

    def compose(self) -> ComposeResult:
        with Vertical(id="param-dialog"):
            yield Label("", id="param-title")
            yield Static("", id="param-warning")
            yield DataTable(id="param-table", cursor_type="row")
            yield Static("", id="param-status")
            yield Static(
                "[dim]↑↓ pick a parameter · enter/e edit · w write gate · "
                "m cycle global/mix/program · esc close[/dim]",
                id="param-note",
                classes="note",
            )

    def on_mount(self) -> None:
        try:
            self._device.mode_select(True)
        except Exception:
            pass
        warning = (
            "Mix mode: a Program 10 lands only in a per-channel buffer. "
            "The unit now plays from Mix mode."
        )
        self.query_one("#param-warning", Static).update(f"[b]{warning}[/b]")
        table = self.query_one("#param-table", DataTable)
        for label, key in (
            ("parameter", "param"),
            ("value", "value"),
            ("choice", "choice"),
            ("range", "range"),
            ("law", "law"),
        ):
            table.add_column(label, key=key)
        self._fill()
        table.focus()

    def _resolved(self, param):
        """The row the ``10`` addresses, with the template's offset applied.

        The program sound table and the mix channel table are templates:
        their ``bit_address`` is relative to their own block until
        ``with_sound``/``with_channel`` (what ``params.at`` does with a
        selector) adds the stride. Reading or editing a template raw would
        touch the common area and report a mismatch that is the table's
        shape, not the unit's.
        """
        if param.mode == "mix":
            found = params.at(
                "mix",
                param.function,
                param.page,
                param.pot,
                channel=self._channel,
            )
        elif param.mode == "program":
            found = params.at("program", param.function, param.page, param.pot, sound=0)
        else:
            found = None
        return found if found is not None else param

    def _buffer_name(self) -> str:
        if self._mode == "global":
            return "global"
        if self._mode == "mix":
            return "mix"
        if self._mode == "program":
            return "program"
        return self._mode

    def _read_record(self):
        if self._mode == "global":
            return self._device.read_global()
        if self._mode == "mix":
            return self._device.read_mix(100)
        if self._mode == "program":
            edit = self._channel + 1
            return self._device.read_edit_program(edit=edit)
        raise ValueError(f"unsupported mode {self._mode}")

    def _fill(self) -> None:
        table = self.query_one("#param-table", DataTable)
        row = table.cursor_row or 0
        table.clear()
        self._params = [
            self._resolved(param) for param in params.verified_params(self._mode)
        ]
        self._values = []
        try:
            record = self._read_record()
        except Exception as exc:
            self.query_one("#param-title", Label).update(
                f"[b]Parameters ({self._mode})[/b]  [dim]{exc}[/dim]"
            )
            self._values = [None] * len(self._params)
            if table.row_count:
                table.move_cursor(row=min(row, table.row_count - 1))
            self._refresh_status()
            return
        for index, param in enumerate(self._params):
            value: int | None = None
            try:
                stored = rec.decode_bit_field(record, param)
                value = params.value_from_stored(param, stored)
                shown = str(value)
            except Exception:
                shown = "-"
            self._values.append(value)
            law = param.value_law or params.law_of(param)
            table.add_row(
                literal(param.label),
                shown,
                self._choice_text(param, value),
                f"{param.low}..{param.high}",
                law,
                key=str(index),
            )
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
        self.query_one("#param-title", Label).update(
            f"[b]Parameters ({self._mode})[/b]  [dim]buffer shown[/dim]"
        )
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self.query_one("#param-status", Static)
        status.update(
            self._notice
            if self._notice
            else "[dim]m cycle mode · enter/e edit · w write gate · esc close[/dim]"
        )

    def _say(self, sentence: str, *, refused: bool = False) -> None:
        self._notice = f"[b]refused:[/b] {literal(sentence)}" if refused else sentence
        self._refresh_status()

    @staticmethod
    def _choice_text(param, value: int | None) -> str:
        """The row's named value for ``value``, or a dash.

        Rows without names leave the column blank; a named row whose value
        is outside its own list shows ``-`` rather than a guess.
        """
        if not param.choices:
            return ""
        if value is None or not 0 <= value < len(param.choices):
            return "-"
        return literal(param.choices[value])

    @staticmethod
    def _choice_value(param, text: str) -> int | None:
        """Resolve a typed name or number to the row's value, or ``None``."""
        typed = text.strip()
        if not typed:
            return None
        for index, name in enumerate(param.choices):
            if name.casefold() == typed.casefold():
                return index
        try:
            number = int(typed)
        except ValueError:
            return None
        return number if 0 <= number < len(param.choices) else None

    def _cursor_row(self) -> int | None:
        if not self._params:
            return None
        table = self.query_one("#param-table", DataTable)
        row = table.cursor_row or 0
        if row < 0 or row >= len(self._params):
            return None
        return row

    def _cursor_param(self):
        row = self._cursor_row()
        return None if row is None else self._params[row]

    def action_cycle_mode(self) -> None:
        modes = ["program", "mix", "global"]
        try:
            idx = modes.index(self._mode)
        except ValueError:
            idx = 0
        self._mode = modes[(idx + 1) % len(modes)]
        self._notice = f"showing {self._mode} buffer"
        self._fill()

    def action_toggle_gate(self) -> None:
        """Flip the app's shared write gate; the flip itself sends nothing."""
        self._gate.toggle()
        armed = self._gate.armed
        self._notice = "write gate ARMED" if armed else "write gate locked"
        self._refresh_status()

    def action_edit_value(self) -> None:
        row = self._cursor_row()
        if row is None:
            return
        param = self._params[row]
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        self._notice = ""
        self._refresh_status()
        if param.choices:
            current = self._values[row] if row < len(self._values) else None
            if current is None or not 0 <= current < len(param.choices):
                current = 0
            self.app.push_screen(
                ChoiceScreen(
                    f"{param.label}: which value?",
                    list(param.choices),
                    current,
                ),
                lambda index: self._choice_picked(param, index),
            )
            return
        self.app.push_screen(
            PromptScreen(
                f"{param.label} ({param.low}..{param.high}):",
                "",
            ),
            lambda text: self._typed(param, text),
        )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row edits it, down the same path as ``e``."""
        self.action_edit_value()

    def _choice_picked(self, param, index: int | None) -> None:
        if index is None:
            self._refresh_status()
            return
        self._typed(param, str(index))

    def _typed(self, param, text: str | None) -> None:
        if text is None:
            self._refresh_status()
            return
        typed = str(text).strip()
        if param.choices:
            value = self._choice_value(param, typed)
            if value is None:
                names = ", ".join(param.choices)
                self._say(f"{typed!r} is not one of: {names}", refused=True)
                return
        else:
            try:
                value = int(typed)
            except ValueError:
                self._say(f"{typed!r} is not a number", refused=True)
                return
        refusal = self._gate.check()
        if refusal is not None:
            self._say(refusal, refused=True)
            return
        clamped = param.clamp(value)
        self._edit_worker(param, clamped)

    @work(thread=True)
    def _edit_worker(self, param, value: int) -> None:
        try:
            mode_num = params.MODE_NUMBERS[param.mode]
        except Exception:
            mode_num = params.MODE_NUMBERS.get(self._mode, 0)
        try:
            sound = param.sound if param.sound is not None else 0
            channel = param.channel if param.channel is not None else self._channel
            self._device.midi_edit(
                mode_num,
                param.function,
                param.page,
                param.pot,
                value,
                sound=sound,
                channel=channel,
            )
            time.sleep(0.05)
            record = self._read_record()
            try:
                stored = rec.decode_bit_field(record, param)
                seen = params.value_from_stored(param, stored)
            except Exception as exc:
                try:
                    self.app.call_from_thread(
                        self._edit_done_mismatch,
                        param,
                        f"read-back failed: {exc}",
                    )
                except Exception:
                    self._edit_done_mismatch(param, f"read-back failed: {exc}")
                return
            expected = param.clamp(value)
            if seen != expected:
                try:
                    self.app.call_from_thread(
                        self._edit_done_mismatch,
                        param,
                        f"{param.label} reads {seen}, not {expected}",
                    )
                except Exception:
                    self._edit_done_mismatch(
                        param, f"{param.label} reads {seen}, not {expected}"
                    )
                return
            try:
                self.app.call_from_thread(self._edit_done_ok, param, seen)
            except Exception:
                self._edit_done_ok(param, seen)
        except Exception as exc:
            try:
                self.app.call_from_thread(self._edit_done_mismatch, param, str(exc))
            except Exception:
                self._edit_done_mismatch(param, str(exc))

    def _edit_done_ok(self, param, value: int) -> None:
        self._notice = f"{param.label} = {value}"
        self._fill()
        self._refresh_status()

    def _edit_done_mismatch(self, param, message: str) -> None:
        self._notice = message
        self._fill()
        self._refresh_status()

    def action_close(self) -> None:
        self.dismiss(None)
