# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""The browser's append path: scan free slots, plan, append or go manual."""

from __future__ import annotations

from textual.widgets import Static

from nano import catalog as cat
from nano import importing, initbank
from nano import messages as m
from nano import records as rec
from nanosyned.app import NanosynedApp
from nanosyned.appendbank import AppendBankScreen
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.importsingle import SingleMappingScreen
from vinsynlib.ui.confirm import ConfirmScreen


def _record(name: str, seed: int = 0) -> bytes:
    data = bytearray(
        (index * 7 + 3 + seed) & 0x7F for index in range(rec.PROGRAM_BYTES)
    )
    m.encode_name(data, name, m.NAME_BIT_OFFSET)
    return bytes(data)


def _bank(*records):
    programs = {
        index: importing.SourceProgram(
            index=index,
            slot=index,
            name=name,
            record=record,
        )
        for index, (name, record) in enumerate(records)
    }
    return importing.SourceBank(index=0, label="Test bank", programs=programs)


async def _until(pilot, ready, attempts=300):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the append flow never reached the expected state")


class TestAppend:
    async def test_it_finds_free_trailing_slots_and_appends(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        template = initbank.init_record(app.device.read_program(127))
        for number in range(5, 127):
            app.device.write_program(number, template)
        one, two = _record("One", 1), _record("Two", 2)
        bank = _bank(("One", one), ("Two", two))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._open_append(bank)
            await _until(pilot, lambda: isinstance(app.screen, AppendBankScreen))
            screen = app.screen
            assert screen.start == 5
            assert [step.target for step in screen.plan.steps] == [5, 6]
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot, lambda: not isinstance(app.screen, ImportProgressScreen)
            )
            await pilot.pause()
            assert app.device.read_program(5) == one
            assert app.device.read_program(6) == two
            assert "import: 2 of 2 stored" in str(
                app.query_one("#status", Static).content
            )

    async def test_no_free_slots_offers_the_single_picker(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        bank = _bank(("One", _record("One", 1)))
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._open_append(bank)
            await _until(pilot, lambda: isinstance(app.screen, AppendBankScreen))
            screen = app.screen
            assert screen.start == 127
            assert screen.plan.steps == ()
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, AppendBankScreen)
            await pilot.press("s")
            await _until(pilot, lambda: isinstance(app.screen, SingleMappingScreen))
