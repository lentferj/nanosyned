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

"""The Mixes pseudo-bank: names, selection, and mode tracking."""

from __future__ import annotations

from textual.widgets import DataTable

from nano import banks
from nano import catalog as cat
from nanosyned.app import MIXES_BANK, NanosynedApp
from nanosyned.demo import DemoDevice


async def _until(pilot, ready, attempts=1500):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause(0.01)
    raise AssertionError("the app never reached the expected state")


class TestMixesPane:
    async def test_mixes_is_a_left_pane_row_with_one_hundred_rows(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            table = app.query_one("#bank-table", DataTable)
            assert table.row_count == len(banks.bank_ids()) + 1
            app._fill(MIXES_BANK)
            await _until(pilot, lambda: app._mix_names_loaded)
            assert app._current_bank == MIXES_BANK
            assert len(app._current) == banks.MIXES
            assert app.query_one("#slot-table", DataTable).row_count == banks.MIXES

    async def test_selecting_a_mix_sends_mix_mode_then_program_change(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._fill(MIXES_BANK)
            await _until(pilot, lambda: app._mix_names_loaded)
            app.query_one("#slot-table").focus()
            app.query_one("#slot-table").move_cursor(row=5)
            app.action_select()
            await _until(pilot, lambda: bool(app.device.mix_selects))
            assert app.device.mode_selects == [True]
            assert app.device.mix_selects[-1][0] == 5
            assert app._unit_mode == "mix"

    async def test_a_program_selected_from_mix_mode_sends_program_mode_first(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._unit_mode = "mix"
            app._fill("USER")
            app.query_one("#slot-table").focus()
            app.query_one("#slot-table").move_cursor(row=3)
            app.action_select()
            await _until(pilot, lambda: bool(app.device.selected_log))
            assert app.device.mode_selects == [False]
            assert app.device.selected_log[-1][0].program_change == 3
            assert app._unit_mode == "program"
