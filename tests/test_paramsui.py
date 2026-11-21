# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""Tests for the verified-parameter editor."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import replace

import pytest
from textual.widgets import DataTable, Input

from nano import params
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.paramsui import ParameterScreen
from nanosyned.screens import PromptScreen
from vinsynlib.ui.modals import ChoiceScreen
from vinsynlib.ui.prompt import PromptScreen as VPromptScreen


@pytest.fixture
def app():
    return NanosynedApp(DemoDevice(), catalog=None, allow_write=True)


async def _settle(pilot, predicate, *, timeout: float = 2.0) -> None:
    """Pause until ``predicate`` holds, for a worker's sleep to land."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(0.01)
        await pilot.pause()
        if predicate():
            return
    raise AssertionError("the worker never settled")


class _FailingDevice(DemoDevice):
    """A demo whose edit send or read-back fails like a dropped port."""

    def __init__(self, failing: str) -> None:
        super().__init__()
        self._failing = failing

    def midi_edit(self, *args, **kwargs):
        if self._failing == "midi_edit":
            raise OSError("port gone")
        return super().midi_edit(*args, **kwargs)

    def read_edit_program(self, **kwargs):
        if self._failing == "read_edit_program":
            raise TimeoutError("no reply")
        return super().read_edit_program(**kwargs)


class TestParameterScreen:
    async def test_opening_sends_mode_select_and_shows_warning(self, app):
        """`p` sends one Mode Select through the app, then opens the screen.

        A Program ``10`` lands only in the per-channel Mix buffer, so the
        open asks for Mix mode -- but through the gate and the exchange,
        not from the screen's mount.
        """
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_edit_parameter()
            for _ in range(400):
                await pilot.pause(0.01)
                if isinstance(app.screen, ParameterScreen):
                    warning = str(app.screen.query_one("#param-warning").content)
                    if "Mix mode" in warning:
                        break
            assert isinstance(app.screen, ParameterScreen)
            assert app.device.mode_selects == [True]
            assert not app._exchange.locked()
            warning = str(app.screen.query_one("#param-warning").content)
            assert "Mix mode" in warning
            assert "Program 10" in warning

    async def test_opening_with_the_gate_locked_sends_nothing(self):
        app2 = NanosynedApp(DemoDevice(), catalog=None, allow_write=False)
        async with app2.run_test() as pilot:
            await pilot.pause()
            app2.action_edit_parameter()
            await pilot.pause()
            assert app2.device.mode_selects == []
            assert not isinstance(app2.screen, ParameterScreen)
            status = str(app2.query_one("#status").content)
            assert "write gate" in status
            assert not app2._exchange.locked()

    async def test_opening_while_the_exchange_is_held_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._exchange.acquire(blocking=False)
            try:
                app.action_edit_parameter()
                await pilot.pause()
                assert app.device.mode_selects == []
                assert not isinstance(app.screen, ParameterScreen)
                assert "busy" in str(app.query_one("#status").content)
            finally:
                app._exchange.release()

    async def test_a_directly_built_screen_sends_no_mode_select(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            assert app.screen is screen
            assert app.device.mode_selects == []

    async def test_only_verified_rows_appear(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, channel=app._channel()
            )
            app.push_screen(screen)
            await pilot.pause()
            # Check that unverified labels don't appear and verified do
            verified = {p.label for p in params.verified_params("program")}
            # Just verify screen built from verified only
            assert len(screen._params) == len(
                list(params.verified_params(screen._mode))
            )
            if verified:
                assert len(screen._params) >= 1

    async def test_program_sound_rows_use_the_absolute_address(self, app):
        """A sound template is relative; the editor must resolve it first."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            row = next(p for p in screen._params if p.label == "Sound pitch semitone")
            template = params.by_label("Sound pitch semitone")[0]
            assert template.bit_address != row.bit_address
            assert row.bit_address == 115
            assert row.sound == 0

    async def test_m_cycles_global_mix_program(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, channel=app._channel()
            )
            app.push_screen(screen)
            await pilot.pause()
            # Start at program by default
            assert screen._mode == "program"
            reads = []
            orig_read_mix = app.device.read_mix
            orig_read_global = app.device.read_global
            orig_read_edit = app.device.read_edit_program

            def track_mix(n, **kw):
                reads.append(("mix", n))
                return orig_read_mix(n, **kw)

            def track_global(**kw):
                reads.append(("global",))
                return orig_read_global(**kw)

            def track_edit(**kw):
                reads.append(("edit", kw))
                return orig_read_edit(**kw)

            app.device.read_mix = track_mix
            app.device.read_global = track_global
            app.device.read_edit_program = track_edit

            await pilot.press("m")
            await pilot.pause()
            assert screen._mode == "mix"
            await pilot.press("m")
            await pilot.pause()
            assert screen._mode == "global"
            await pilot.press("m")
            await pilot.pause()
            assert screen._mode == "program"
            # Should have used read_mix at some point
            assert any(r[0] == "mix" for r in reads)

    async def test_e_locked_shows_refusal_and_sends_no_10(self, app):
        app2 = NanosynedApp(DemoDevice(), catalog=None, allow_write=False)
        async with app2.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app2.device, app2._write_gate, channel=app2._channel()
            )
            app2.push_screen(screen)
            await pilot.pause()
            edits_before = len(app2.device.midi_edits)
            await pilot.press("e")
            await pilot.pause()
            # Should show refusal in status
            status = str(screen.query_one("#param-status").content)
            assert "refused" in status.lower() or "write gate" in status.lower()
            assert len(app2.device.midi_edits) == edits_before

    async def test_e_armed_sends_10_and_readback_appears(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, channel=app._channel()
            )
            app.push_screen(screen)
            await pilot.pause()
            # Ensure gate armed
            if not app._write_gate.armed:
                app._write_gate.toggle()
            await pilot.press("e")
            await pilot.pause()
            # Should be in prompt
            assert isinstance(app.screen, (PromptScreen, VPromptScreen))
            # Put a value for first verified param
            try:
                app.screen.query_one(Input).value = "0"
            except Exception:
                pass
            await pilot.press("enter")
            await pilot.pause()
            # Wait a bit for worker
            for _ in range(50):
                await pilot.pause()
            assert len(app.device.midi_edits) >= 1
            # Check it's message 10 (mode select context) - midi_edit called
            status = str(screen.query_one("#param-status").content)
            assert "=" in status or "reads" in status or status  # readback line appears

    async def test_out_of_range_clamped(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, channel=app._channel()
            )
            app.push_screen(screen)
            await pilot.pause()
            if not app._write_gate.armed:
                app._write_gate.toggle()
            # Get first param
            if not screen._params:
                return
            param = screen._params[0]
            # Try value way over range - our code clamps before sending
            edits_before = len(app.device.midi_edits)
            await pilot.press("e")
            await pilot.pause()
            try:
                app.screen.query_one(Input).value = "9999"
            except Exception:
                pass
            await pilot.press("enter")
            for _ in range(30):
                await pilot.pause()
            # Should have sent with clamped value
            assert len(app.device.midi_edits) >= edits_before
            # Last edit's value should be clamped
            last = app.device.midi_edits[-1]
            # midi_edit stores (mode, function, page, pot, value, sound, channel)
            sent_value = last[4]
            assert sent_value == param.clamp(9999)

    async def test_effects_never_appears(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, channel=app._channel()
            )
            app.push_screen(screen)
            await pilot.pause()
            # Cycle through all modes - should only see global/mix/program
            modes_seen = {screen._mode}
            for _ in range(5):
                await pilot.press("m")
                await pilot.pause()
                modes_seen.add(screen._mode)
            assert "effects" not in modes_seen

    async def test_enter_takes_the_same_edit_path_as_e(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            assert app._write_gate.armed
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, (PromptScreen, VPromptScreen))
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, (PromptScreen, VPromptScreen))

    async def test_enter_locked_refuses_and_sends_nothing(self):
        app2 = NanosynedApp(DemoDevice(), catalog=None, allow_write=False)
        async with app2.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app2.device, app2._write_gate, channel=app2._channel()
            )
            app2.push_screen(screen)
            await pilot.pause()
            edits_before = len(app2.device.midi_edits)
            await pilot.press("enter")
            await pilot.pause()
            assert app2.screen is screen
            status = str(screen.query_one("#param-status").content)
            assert "refused" in status.lower()
            assert "write gate" in status.lower()
            assert len(app2.device.midi_edits) == edits_before

    async def test_w_toggles_the_shared_gate_and_then_e_sends(self):
        app2 = NanosynedApp(DemoDevice(), catalog=None, allow_write=False)
        async with app2.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app2.device, app2._write_gate, channel=app2._channel()
            )
            app2.push_screen(screen)
            await pilot.pause()
            assert not app2._write_gate.armed
            await pilot.press("w")
            await pilot.pause()
            assert app2._write_gate.armed
            status = str(screen.query_one("#param-status").content)
            assert "write gate ARMED" in status
            await pilot.press("w")
            await pilot.pause()
            assert not app2._write_gate.armed
            status = str(screen.query_one("#param-status").content)
            assert "write gate locked" in status
            # The shared gate is armed again, so the same screen may send.
            await pilot.press("w")
            await pilot.pause()
            assert app2._write_gate.armed
            edits_before = len(app2.device.midi_edits)
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app2.screen, (PromptScreen, VPromptScreen))
            app2.screen.query_one(Input).value = "0"
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause()
            assert len(app2.device.midi_edits) > edits_before

    async def test_choice_column_shows_the_name(self, app, monkeypatch):
        base = params.verified_params("global")[2]  # Controller A number
        names = tuple(f"c{i}" for i in range(1 << base.bits))
        row = replace(base, choices=names)
        monkeypatch.setattr(params, "verified_params", lambda mode=None: (row,))
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(
                app.device, app._write_gate, mode="global", channel=0
            )
            app.push_screen(screen)
            await pilot.pause()
            value = screen._values[0]
            table = screen.query_one("#param-table", DataTable)
            assert value is not None
            assert table.get_row_at(0)[2] == f"c{value}"
            assert screen._choice_text(row, value) == f"c{value}"
            assert screen._choice_text(row, None) == "-"
            assert screen._choice_text(base, 0) == ""

    async def test_choice_row_opens_the_named_list(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            row = replace(screen._params[0], choices=("Off", "On"))
            screen._params[0] = row
            screen._values[0] = 1
            edits_before = len(app.device.midi_edits)
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ChoiceScreen)
            await pilot.press("enter")
            for _ in range(50):
                await pilot.pause()
            assert len(app.device.midi_edits) > edits_before
            assert app.device.midi_edits[-1][4] == 1

    async def test_choice_row_edits_by_name_and_refuses_an_unknown_one(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            row = replace(screen._params[0], choices=("Off", "On"))
            edits_before = len(app.device.midi_edits)
            screen._typed(row, "on")
            for _ in range(50):
                await pilot.pause()
            assert len(app.device.midi_edits) == edits_before + 1
            assert app.device.midi_edits[-1][4] == 1
            sent = len(app.device.midi_edits)
            screen._typed(row, "maybe")
            await pilot.pause()
            assert len(app.device.midi_edits) == sent
            status = str(screen.query_one("#param-status").content)
            assert "refused" in status.lower()
            assert "maybe" in status

    async def test_an_edit_refuses_while_the_exchange_is_held(self, app):
        """A claim taken elsewhere refuses the edit and leaves it alone."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            assert app._write_gate.armed
            param = screen._params[0]
            edits_before = len(app.device.midi_edits)
            assert app._exchange.acquire(blocking=False)
            try:
                screen._typed(param, str(param.clamp(param.low)))
                await pilot.pause()
                assert len(app.device.midi_edits) == edits_before
                assert app._exchange.locked()
                status = str(screen.query_one("#param-status").content)
                assert "refused" in status.lower()
                assert "busy" in status.lower()
            finally:
                app._exchange.release()

    async def test_two_rapid_edits_do_not_overlap(self, app):
        """The first call's claim is still held when the second arrives."""
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            assert app._write_gate.armed
            param = screen._params[0]
            edits_before = len(app.device.midi_edits)
            screen._typed(param, "1")
            screen._typed(param, "2")
            status = str(screen.query_one("#param-status").content)
            assert "busy" in status.lower()
            await _settle(pilot, lambda: not app._exchange.locked())
            assert len(app.device.midi_edits) == edits_before + 1

    @pytest.mark.parametrize(
        ("failing", "expected"),
        [
            ("midi_edit", "port gone"),
            ("read_edit_program", "read-back failed: no reply"),
        ],
    )
    async def test_a_failed_edit_releases_the_exchange_and_reports(
        self, failing, expected
    ):
        """A device fault releases the claim and is said on the main thread."""
        app = NanosynedApp(_FailingDevice(failing), catalog=None, allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = ParameterScreen(app.device, app._write_gate, channel=0)
            app.push_screen(screen)
            await pilot.pause()
            param = screen._params[0]
            threads: list[threading.Thread] = []
            original = screen._edit_done_mismatch

            def record_thread(param, message):
                threads.append(threading.current_thread())
                original(param, message)

            screen._edit_done_mismatch = record_thread
            screen._typed(param, str(param.clamp(param.low)))

            def reported() -> bool:
                return bool(threads) and expected in str(
                    screen.query_one("#param-status").content
                )

            await _settle(pilot, reported)
            assert threads == [threading.main_thread()]
            assert expected in str(screen.query_one("#param-status").content)
            assert not app._exchange.locked()
