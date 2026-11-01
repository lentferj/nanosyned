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

from textual.widgets import DataTable, Input

from nano import catalog as cat
from nano import records as rec
from nanosyned import mix as mixview
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditGate
from nanosyned.screens import EffectsScreen, MixScreen
from vinsynlib.ui.prompt import PromptScreen


async def _until(pilot, ready, attempts: int = 200) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open_mix(pilot, record: bytes, seen: list[bytes | None]) -> MixScreen:
    """Push a mix screen over the running app and return it, mounted."""
    app = pilot.app
    app.push_screen(MixScreen(record, number=0, replaced="Invented"), seen.append)
    await _until(
        pilot,
        lambda: (
            isinstance(app.screen, MixScreen)
            and len(app.screen.query("#mix-table")) == 1
        ),
    )
    await pilot.pause()
    return app.screen


class TestMixScreen:
    async def test_parts_start_collapsed_and_enter_expands_one(self) -> None:
        record = bytes(rec.MIX_BYTES)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, [])
            table = screen.query_one("#mix-table", DataTable)
            assert table.row_count == rec.MIX_CHANNELS
            assert screen.expanded == frozenset()
            assert "enter" in str(screen.query_one("#mix-note").content)

            await pilot.press("enter")
            await pilot.pause()
            assert screen.expanded == frozenset({0})
            assert table.row_count == rec.MIX_CHANNELS + len(mixview.FIELDS)
            assert "program" in str(table.get_row_at(1)[0])

            # Enter on the part row again collapses it.
            table.move_cursor(row=0)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert screen.expanded == frozenset()
            assert table.row_count == rec.MIX_CHANNELS

    async def test_enter_edits_one_channel_and_arm_fire_returns_it(self) -> None:
        record = bytes(rec.MIX_BYTES)
        seen: list[bytes | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, seen)
            table = screen.query_one("#mix-table", DataTable)

            # Expand part 1 and edit its program field.
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "42"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            assert mixview.get_channel_field(screen.record, 0, "program") == 42
            assert mixview.get_channel_field(screen.record, 1, "program") == 0

            # Part 2 is its own block: expand it and give it another program.
            second_part = 1 + len(mixview.FIELDS)
            table.move_cursor(row=second_part)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=second_part + 1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "9"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            assert mixview.get_channel_field(screen.record, 0, "program") == 42
            assert mixview.get_channel_field(screen.record, 1, "program") == 9

            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is True
            await pilot.press("w")
            await _until(pilot, lambda: bool(seen))
            assert seen[0] is not None
            assert mixview.get_channel_field(seen[0], 0, "program") == 42
            assert mixview.get_channel_field(seen[0], 1, "program") == 9

    async def test_r_reverts_the_staged_edit(self) -> None:
        record = bytes(rec.MIX_BYTES)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, [])
            table = screen.query_one("#mix-table", DataTable)
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "42"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            assert screen.record != record

            await pilot.press("r")
            await pilot.pause()
            assert screen.record == record
            assert mixview.get_channel_field(screen.record, 0, "program") == 0

    async def test_a_locked_gate_refusal_is_shown(self) -> None:
        record = bytes(rec.MIX_BYTES)
        gate = EditGate()
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(
                MixScreen(record, number=0, replaced="Invented", gate=gate),
                lambda _: None,
            )
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, MixScreen)
                    and len(app.screen.query("#mix-table")) == 1
                ),
            )
            await pilot.pause()
            screen = app.screen
            table = screen.query_one("#mix-table", DataTable)
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "5"
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))

            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is False
            assert "write gate" in str(screen.query_one("#mix-status").content)
            gate.toggle()
            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is True


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
