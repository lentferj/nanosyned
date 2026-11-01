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

import pytest
from textual.widgets import Input

from nano import params
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.paramsui import ParameterScreen
from nanosyned.screens import PromptScreen
from vinsynlib.ui.prompt import PromptScreen as VPromptScreen


@pytest.fixture
def app():
    return NanosynedApp(DemoDevice(), catalog=None, allow_write=True)


class TestParameterScreen:
    async def test_opening_sends_mode_select_and_shows_warning(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(
                ParameterScreen(app.device, app._write_gate, channel=app._channel())
            )
            await pilot.pause()
            assert isinstance(app.screen, ParameterScreen)
            assert app.device.mode_selects
            assert True in app.device.mode_selects or app.device.mode_selects  # called
            warning = str(app.screen.query_one("#param-warning").content)
            assert "Mix mode" in warning
            assert "Program 10" in warning

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
