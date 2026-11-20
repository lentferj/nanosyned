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

"""The browser's init worker, without the confirmation screen."""

from __future__ import annotations

from textual.widgets import Static

from nano import catalog as cat
from nano import favorites, identity
from nano import records as rec
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen


async def _until(pilot, ready, attempts=300):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the init worker never finished")


class TestInitWorker:
    async def test_it_initialises_000_to_126_and_leaves_127_alone(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        before_127 = app.device.read_program(127)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._start_init()
            await _until(
                pilot,
                lambda: not isinstance(app.screen, ImportProgressScreen),
            )
            await pilot.pause()
            for number in range(127):
                assert rec.program_name(app.device.read_program(number)).rstrip() == (
                    "Init"
                )
            assert app.device.read_program(127) == before_127
            status = str(app.query_one("#status", Static).content)
            assert "init: 127 of 127 stored" in status

    async def test_init_preserves_the_old_favourite_content(self, tmp_path):
        store = favorites.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 0, name="Old", rating=3, tags="pad", note="keep")
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.empty(),
            favorites=store,
            memory_path=str(tmp_path / "memory.db"),
            allow_write=True,
        )
        old = app.device.read_program(0)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._start_init()
                await _until(
                    pilot,
                    lambda: not isinstance(app.screen, ImportProgressScreen),
                )
                await pilot.pause()
                assert store.get("USER", 0) is None
                entry = app.memory.get(identity.digest(old))
                assert entry is not None
                assert entry.favourite is True
                assert entry.rating == 3
                assert entry.tags == "pad"
                assert entry.note == "keep"
        finally:
            app.memory.close()
            store.close()

    async def test_a_locked_gate_sends_nothing(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=False)
        before = app.device.read_program(0)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._start_init()
            await pilot.pause()
            assert app.device.read_program(0) == before
            assert app.device.program_writes == []
            assert "write gate" in str(app.query_one("#status", Static).content)
