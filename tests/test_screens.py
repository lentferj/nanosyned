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
from nano import records as rec
from nanosyned import mix as mixview
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditGate, EffectsEditor
from nanosyned.programpicker import ProgramPickerScreen
from nanosyned.screens import EffectsScreen, GlobalScreen, MixScreen


async def _until(pilot, ready, attempts: int = 200) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open_mix(
    pilot,
    record: bytes,
    seen: list[bytes | None],
    gate: EditGate | None = None,
) -> MixScreen:
    """Push a mix screen over the running app and return it, mounted."""
    app = pilot.app
    app.push_screen(
        MixScreen(record, number=0, replaced="Invented", gate=gate), seen.append
    )
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
            screen = await _open_mix(pilot, record, seen, EditGate(armed=True))
            table = screen.query_one("#mix-table", DataTable)

            # Expand part 1 and edit its program field.
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
            picker = app.screen
            picker.query_one("#program-table", DataTable).move_cursor(row=42)
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            await _until(
                pilot,
                lambda: mixview.get_channel_field(screen.record, 0, "program") == 42,
            )
            assert mixview.get_channel_field(screen.record, 1, "program") == 0
            assert (
                mixview.get_channel_field(app.device.read_mix(100), 0, "program") == 42
            )

            # Part 2 is its own block: expand it and give it another program.
            second_part = 1 + len(mixview.FIELDS)
            table.move_cursor(row=second_part)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=second_part + 1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
            picker = app.screen
            picker.query_one("#program-table", DataTable).move_cursor(row=9)
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            await _until(
                pilot,
                lambda: mixview.get_channel_field(screen.record, 1, "program") == 9,
            )
            assert mixview.get_channel_field(screen.record, 0, "program") == 42

            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is True
            await pilot.press("s")
            await _until(pilot, lambda: bool(seen))
            assert seen[0] is not None
            assert mixview.get_channel_field(seen[0], 0, "program") == 42
            assert mixview.get_channel_field(seen[0], 1, "program") == 9

    async def test_program_field_opens_a_named_program_browser(self, tmp_path) -> None:
        record = bytes(rec.MIX_BYTES)
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.Catalog([cat.Entry("USER", 42, "Invented Program")]),
            catalog_path=str(tmp_path / "catalog.json"),
            allow_write=True,
        )
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, [], EditGate(armed=True))
            table = screen.query_one("#mix-table", DataTable)
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
            picker = app.screen
            picker_table = picker.query_one("#program-table", DataTable)
            user_row = 128 + 42
            assert "Invented Program" in str(picker_table.get_row_at(user_row)[2])
            picker_table.move_cursor(row=user_row)
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            await _until(
                pilot,
                lambda: (
                    mixview.get_channel_field(screen.record, 0, "program") == 42
                    and mixview.get_channel_field(screen.record, 0, "program_type") == 1
                ),
            )
            assert "User 042 Invented Program" in str(table.get_row_at(1)[1])

    async def test_switches_toggle_with_space_and_enter(self) -> None:
        record = bytes(rec.MIX_BYTES)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, [], EditGate(armed=True))
            table = screen.query_one("#mix-table", DataTable)
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1 + mixview.FIELDS.index("enable"))
            await pilot.pause()

            await pilot.press("space")
            await _until(
                pilot,
                lambda: mixview.get_channel_field(screen.record, 0, "enable") == 1,
            )
            assert mixview.get_channel_field(app.device.read_mix(100), 0, "enable")
            await pilot.press("enter")
            await _until(
                pilot,
                lambda: mixview.get_channel_field(screen.record, 0, "enable") == 0,
            )

    async def test_r_reverts_the_staged_edit(self) -> None:
        record = bytes(rec.MIX_BYTES)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, [], EditGate(armed=True))
            table = screen.query_one("#mix-table", DataTable)
            await pilot.press("enter")
            await pilot.pause()
            table.move_cursor(row=1)
            await pilot.pause()
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
            picker = app.screen
            picker.query_one("#program-table", DataTable).move_cursor(row=42)
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, MixScreen))
            await _until(
                pilot,
                lambda: mixview.get_channel_field(screen.record, 0, "program") == 42,
            )
            assert screen.record != record

            await pilot.press("r")
            await pilot.pause()
            assert screen.record == record
            assert mixview.get_channel_field(screen.record, 0, "program") == 0

    async def _stage_program(self, pilot, app, screen, table, value: int) -> None:
        """Expand part 1 and pick its program through the browser."""
        await pilot.press("enter")
        await pilot.pause()
        table.move_cursor(row=1)
        await pilot.pause()
        await pilot.press("enter")
        await _until(pilot, lambda: isinstance(app.screen, ProgramPickerScreen))
        picker = app.screen
        picker.query_one("#program-table", DataTable).move_cursor(row=value)
        await pilot.press("enter")
        await _until(pilot, lambda: isinstance(app.screen, MixScreen))
        await _until(
            pilot,
            lambda: mixview.get_channel_field(screen.record, 0, "program") == value,
        )

    async def test_w_toggles_the_gate_and_the_status_and_stores_nothing(
        self,
    ) -> None:
        record = bytes(rec.MIX_BYTES)
        gate = EditGate()
        seen: list[bytes | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, seen, gate)
            status = screen.query_one("#mix-status")
            note = str(screen.query_one("#mix-note").content)
            assert "w gate" in note
            assert "a arm" in note
            assert "s store" in note

            await pilot.press("w")
            await pilot.pause()
            assert gate.armed is True
            assert "write gate ARMED" in str(status.content)
            await pilot.press("w")
            await pilot.pause()
            assert gate.armed is False
            assert "write gate locked" in str(status.content)
            assert seen == []

    async def test_a_locked_gate_refuses_and_s_unarmed_says_what_to_press(
        self,
    ) -> None:
        record = bytes(rec.MIX_BYTES)
        gate = EditGate(armed=True)
        seen: list[bytes | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, seen, gate)
            table = screen.query_one("#mix-table", DataTable)
            status = screen.query_one("#mix-status")
            await self._stage_program(pilot, app, screen, table, 5)

            # Lock the gate after the live edit: `a` refuses by name.
            gate.toggle()
            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is False
            assert "write gate is locked" in str(status.content)

            # Nothing is armed, so `s` says what to press first.
            await pilot.press("s")
            await pilot.pause()
            assert "press a to arm the store" in str(status.content)
            assert seen == []

    async def test_any_other_key_disarms_and_a_gate_locked_after_arming_refuses(
        self,
    ) -> None:
        record = bytes(rec.MIX_BYTES)
        gate = EditGate(armed=True)
        seen: list[bytes | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            screen = await _open_mix(pilot, record, seen, gate)
            table = screen.query_one("#mix-table", DataTable)
            status = screen.query_one("#mix-status")
            await self._stage_program(pilot, app, screen, table, 5)

            # Arm the store while the live-edit gate is already armed.
            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is True

            # Any key but `s` is a change of mind -- `w` included, and it
            # toggles the gate on its way.
            await pilot.press("w")
            await pilot.pause()
            assert screen.armed is False
            assert gate.armed is False
            assert "write gate locked" in str(status.content)
            await pilot.press("s")
            await pilot.pause()
            assert "press a to arm the store" in str(status.content)
            assert seen == []

            # Arm both again, then lock the gate underneath the store: firing
            # refuses with the gate's own sentence.
            await pilot.press("w")
            await pilot.press("a")
            await pilot.pause()
            assert gate.armed is True
            assert screen.armed is True
            gate.toggle()
            await pilot.press("s")
            await pilot.pause()
            assert "write gate is locked" in str(status.content)
            assert seen == []


class TestGlobalScreen:
    async def test_w_toggles_the_apps_gate_and_stores_nothing(self) -> None:
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("g")
            await _until(pilot, lambda: isinstance(app.screen, GlobalScreen))
            screen = app.screen
            status = screen.query_one("#global-status")
            note = str(screen.query_one("#global-note").content)
            assert "w gate" in note
            assert "a arm" in note
            assert "s store" in note

            await pilot.press("w")
            await pilot.pause()
            assert app._write_gate.armed is False
            assert "write gate locked" in str(status.content)
            assert app.device.global_writes == []

            await pilot.press("w")
            await pilot.pause()
            assert app._write_gate.armed is True
            assert "write gate ARMED" in str(status.content)
            assert app.device.global_writes == []


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

    async def test_the_table_has_a_choice_column_and_a_known_name(self) -> None:
        editor = EffectsEditor(bytes(rec.EFFECTS_BYTES))
        assert editor.set_value("Effect configuration", 3) is None
        seen: list[bytes | None] = []
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(EffectsScreen(editor), seen.append)
            await _until(pilot, lambda: isinstance(app.screen, EffectsScreen))
            await pilot.pause()
            table = app.screen.query_one("#effects-table", DataTable)
            assert "choice" in table.columns
            labels = [row.param.label for row in editor.rows()]
            index = labels.index("Effect configuration")
            assert table.get_row_at(index)[2] == "2 sends, with EQ"

    async def test_w_toggles_the_gate_and_a_then_s_returns_the_record(
        self,
    ) -> None:
        record = bytes(rec.EFFECTS_BYTES)
        seen: list[bytes | None] = []
        gate = EditGate()
        editor = EffectsEditor(record)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app.push_screen(EffectsScreen(editor, gate=gate), seen.append)
            await _until(pilot, lambda: isinstance(app.screen, EffectsScreen))
            await pilot.pause()
            screen = app.screen
            status = screen.query_one("#effects-status")
            note = str(screen.query_one("#effects-note").content)
            assert "w gate" in note
            assert "a arm" in note
            assert "s store" in note

            assert editor.set_value("Effect configuration", 2) is None
            await pilot.press("w")
            await pilot.pause()
            assert gate.armed is True
            assert "write gate ARMED" in str(status.content)
            await pilot.press("w")
            await pilot.pause()
            assert gate.armed is False
            assert "write gate locked" in str(status.content)

            # Locked: `a` refuses by name and does not arm.
            await pilot.press("a")
            await pilot.pause()
            assert screen.armed is False
            assert "write gate is locked" in str(status.content)

            await pilot.press("w")
            await pilot.press("a")
            await pilot.pause()
            assert gate.armed is True
            assert screen.armed is True
            await pilot.press("s")
            await _until(pilot, lambda: bool(seen))
            assert seen[0] == editor.record()
