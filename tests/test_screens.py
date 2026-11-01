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

"""The modal screens the editors hand rows to, with no MIDI and no unit.

Every fixture here is invented; the device is the demo, and no port is
opened. The screens are driven the way the browser drives them -- one key
to open, then the row list the editor offers -- because a row the editor
does not offer is a row the screen must not show.
"""

from __future__ import annotations

from textual.widgets import DataTable

from nano import catalog as cat
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.screens import EffectsScreen


async def _until(pilot, ready, attempts: int = 200) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestEffectsScreen:
    async def test_the_table_offers_no_deleted_row(self) -> None:
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await _until(pilot, lambda: isinstance(app.screen, EffectsScreen))
            screen = app.screen
            rows = screen.editor.rows()
            labels = [row.param.label for row in rows]
            assert all("deleted parameter" not in label for label in labels)
            assert "Effect configuration" in labels
            table = screen.query_one("#effects-table", DataTable)
            assert table.row_count == len(rows)
