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
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

from __future__ import annotations

import os

from textual.widgets import Static

from nano import catalog as cat
from nano import config, dumps
from nanosyned.app import KEY_HINTS, NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.screens import PromptScreen
from vinsynlib.ui.confirm import ConfirmScreen


def make(tmp_path):
    ui_path = config.ui_state_path(str(tmp_path / "config.toml"))
    config.save_ui_state("import.folder", str(tmp_path), ui_path)
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
    )


async def _until(pilot, ready, attempts=300):
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestBackupUI:
    async def test_b_backs_up_full_unit(self, tmp_path):
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("B")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            # accept default path
            await pilot.press("enter")
            await _until(
                pilot, lambda: not isinstance(app.screen, ImportProgressScreen)
            )
            await pilot.pause()
            # find the backup file created
            files = [
                f
                for f in os.listdir(tmp_path)
                if f.startswith("nanosyned-backup-") and f.endswith(".syx")
            ]
            assert len(files) == 1
            path = os.path.join(tmp_path, files[0])
            lib = dumps.read_syx_file(path)
            # programs 0..126 (127 programs), no 127
            assert set(lib.programs.keys()) == set(range(127))
            # effects 0..127 (128 effects)
            assert set(lib.effects.keys()) == set(range(128))
            # mixes 0..99 (100 mixes)
            assert set(lib.mixes.keys()) == set(range(100))
            # global present
            assert lib.globals_ is not None
            # total records = 127 + 128 + 100 + 1 = 356
            status = str(app.query_one("#status", Static).content)
            assert "backed up 356 record(s)" in status

    async def test_backup_works_with_write_gate_locked(self, tmp_path):
        """Backup is read-only from the unit's perspective.

        It does not need the write gate.
        """
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            # Ensure write gate is locked (default)
            device = app.device
            assert device.program_writes == []
            assert device.effect_writes == []
            assert device.mix_writes == []
            assert device.global_writes == []
            await pilot.press("B")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("enter")
            await _until(
                pilot, lambda: not isinstance(app.screen, ImportProgressScreen)
            )
            await pilot.pause()
            # No writes should have occurred
            assert device.program_writes == []
            assert device.effect_writes == []
            assert device.mix_writes == []
            assert device.global_writes == []
            # Backup file should exist and be parseable
            files = [
                f
                for f in os.listdir(tmp_path)
                if f.startswith("nanosyned-backup-") and f.endswith(".syx")
            ]
            assert len(files) == 1
            path = os.path.join(tmp_path, files[0])
            lib = dumps.read_syx_file(path)
            assert set(lib.programs.keys()) == set(range(127))
            assert set(lib.effects.keys()) == set(range(128))
            assert set(lib.mixes.keys()) == set(range(100))
            assert lib.globals_ is not None

    async def test_existing_path_confirms(self, tmp_path):
        app = make(tmp_path)
        # Create a backup file first
        path = os.path.join(tmp_path, "nanosyned-backup-existing.syx")
        with open(path, "wb") as f:
            f.write(b"old")
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("B")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            # Type the existing path
            await pilot.press(*list(path))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            # n leaves file untouched
            await pilot.press("n")
            await _until(pilot, lambda: not isinstance(app.screen, ConfirmScreen))
            await pilot.pause()
            with open(path, "rb") as f:
                assert f.read() == b"old"
            # second run, y replaces
            await pilot.press("B")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press(*list(path))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot, lambda: not isinstance(app.screen, ImportProgressScreen)
            )
            await pilot.pause()
            with open(path, "rb") as f:
                assert f.read() != b"old"
            lib = dumps.read_syx_file(path)
            assert set(lib.programs.keys()) == set(range(127))
            assert set(lib.effects.keys()) == set(range(128))
            assert set(lib.mixes.keys()) == set(range(100))
            assert lib.globals_ is not None

    def test_key_hints_and_binding(self):
        assert "B backup" in KEY_HINTS
        bindings = [b.key for b in NanosynedApp.BINDINGS]
        assert "B" in bindings
        actions = {b.key: b.action for b in NanosynedApp.BINDINGS}
        assert actions["B"] == "backup"
