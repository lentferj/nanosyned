# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

from __future__ import annotations

from textual.widgets import Static

from nano import catalog as cat
from nano import records as rec
from nanosyned.app import KEY_HINTS, WRITE_HINTS, NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.initbank import InitBankScreen
from vinsynlib.ui.confirm import ConfirmScreen


async def _until(pilot, ready, attempts=300):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the init screen never finished")


class TestInitBankUI:
    async def test_n_opens_init_bank_screen(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            assert isinstance(app.screen, InitBankScreen)

    async def test_two_confirmations_initialise_the_bank(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        before_127 = app.device.read_program(127)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            assert isinstance(app.screen, InitBankScreen)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            assert "Initialise all 127 User programs 000-126?" in app.screen.prompt_text
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "000-126" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(
                pilot,
                lambda: not isinstance(app.screen, ImportProgressScreen),
            )
            await pilot.pause()
            for number in range(127):
                assert (
                    rec.program_name(app.device.read_program(number)).rstrip() == "Init"
                )
            assert app.device.read_program(127) == before_127
            status = str(app.query_one("#status", Static).content)
            assert status.startswith("init:")

    async def test_locked_gate_refuses_before_start(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=False)
        before = app.device.read_program(0)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            assert isinstance(app.screen, InitBankScreen)
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert not isinstance(app.screen, ImportProgressScreen)
            assert app.device.read_program(0) == before
            status = str(app.screen.query_one("#init-status", Static).content)
            assert "write gate is locked" in status

    async def test_cancel_at_first_confirmation_writes_nothing(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        before = app.device.read_program(0)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("n")
            await pilot.pause()
            assert not isinstance(app.screen, ImportProgressScreen)
            assert app.device.read_program(0) == before

    async def test_cancel_at_second_confirmation_writes_nothing(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        before = app.device.read_program(0)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: isinstance(app.screen, ConfirmScreen),
            )
            await pilot.press("n")
            await pilot.pause()
            assert not isinstance(app.screen, ImportProgressScreen)
            assert app.device.read_program(0) == before

    def test_key_hints_and_binding(self):
        assert "N init bank" in KEY_HINTS
        assert "N init bank" in WRITE_HINTS
        bindings = [b.key for b in NanosynedApp.BINDINGS]
        assert "N" in bindings
