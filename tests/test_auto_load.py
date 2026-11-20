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

"""Cursor-follow selection and left/right pane navigation."""

from __future__ import annotations

from nano import catalog as cat
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice


async def _until(pilot, ready, attempts=200):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the expected state")


class TestPaneNavigation:
    async def test_left_and_right_move_between_the_panes(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.action_focus_left_pane()
            assert app.query_one("#bank-table").has_focus
            await pilot.press("right")
            await pilot.pause()
            assert app.query_one("#slot-table").has_focus
            await pilot.press("left")
            await pilot.pause()
            assert app.query_one("#bank-table").has_focus


class TestAutoLoad:
    async def test_off_by_default_and_cursor_is_silent(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.action_focus_right_pane()
            await pilot.press("down")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_enabled_cursor_sends_the_focused_program(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.action_focus_right_pane()
            await pilot.press("a")
            await _until(pilot, lambda: bool(app.device.selected_log))
            app.device.selected_log.clear()
            await pilot.press("down")
            await _until(pilot, lambda: bool(app.device.selected_log))
            table = app.query_one("#slot-table")
            entry = app._current[table.cursor_row]
            sent = app.device.selected_log[-1][0]
            assert sent.bank_id == entry.bank_id
            assert sent.program_change == entry.program_change
            before = len(app.device.selected_log)
            await pilot.press("a")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert len(app.device.selected_log) == before

    async def test_the_toggle_is_remembered(self, tmp_path):
        path = str(tmp_path / "config.toml")
        first = NanosynedApp(DemoDevice(), catalog=cat.empty(), config_path=path)
        async with first.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            first.action_focus_right_pane()
            await pilot.press("a")
            await pilot.pause()
            assert first._auto_load is True

        second = NanosynedApp(DemoDevice(), catalog=cat.empty(), config_path=path)

        assert second._auto_load is True
