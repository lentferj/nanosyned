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

"""The browser's full-restore flow, against the demo device."""

from __future__ import annotations

import os

from textual.widgets import Static

from nano import catalog as cat
from nano import fullbackup
from nanosyned.app import KEY_HINTS, WRITE_HINTS, NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.picker import FilePickerScreen
from nanosyned.restorebank import FullRestoreScreen
from vinsynlib.ui.confirm import ConfirmScreen


def make(tmp_path, *, allow_write: bool = True) -> NanosynedApp:
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
        allow_write=allow_write,
    )


def backup_file(tmp_path) -> str:
    path = str(tmp_path / "full.syx")
    fullbackup.backup_device(DemoDevice(), path)
    return path


async def _until(pilot, ready, attempts=240):
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _choose_file(app, pilot, path: str) -> None:
    await pilot.press("R")
    await _until(pilot, lambda: isinstance(app.screen, FilePickerScreen))
    app.screen.dismiss(path)
    await _until(pilot, lambda: isinstance(app.screen, FullRestoreScreen))


class TestFullRestoreUI:
    async def test_r_restores_every_kind_and_records_one_undo(self, tmp_path):
        path = backup_file(tmp_path)
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _choose_file(app, pilot, path)
            assert "127 user program" in str(
                app.screen.query_one("#restore-summary", Static).content
            )

            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            assert "restore 356 record(s)" in app.screen.prompt_text
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "backed up before it is replaced" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    len(app.device.program_writes) == 127
                    and len(app.device.effect_writes) == 128
                    and len(app.device.mix_writes) == 100
                    and len(app.device.global_writes) == 1
                    and not isinstance(app.screen, ImportProgressScreen)
                ),
            )
            await pilot.pause()
            status = str(app.query_one("#status", Static).content)
            assert "restore: 356 of 356 stored" in status
            assert len(app._undo_log) == 1

    async def test_a_locked_gate_refuses_before_the_worker(self, tmp_path):
        path = backup_file(tmp_path)
        app = make(tmp_path, allow_write=False)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _choose_file(app, pilot, path)
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert isinstance(app.screen, FullRestoreScreen)
            assert app.device.program_writes == []
            assert app.device.effect_writes == []
            assert app.device.mix_writes == []
            assert app.device.global_writes == []
            status = str(app.screen.query_one("#restore-status", Static).content)
            assert "write gate is locked" in status

    async def test_cancel_at_the_second_confirmation_writes_nothing(self, tmp_path):
        path = backup_file(tmp_path)
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _choose_file(app, pilot, path)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "restore now?" in app.screen.prompt_text
                ),
            )
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, FullRestoreScreen)
            assert app.device.program_writes == []

    async def test_undo_restores_every_kind(self, tmp_path):
        path = backup_file(tmp_path)
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _choose_file(app, pilot, path)
            await pilot.press("ctrl+s")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    isinstance(app.screen, ConfirmScreen)
                    and "restore now?" in app.screen.prompt_text
                ),
            )
            await pilot.press("y")
            await _until(
                pilot,
                lambda: (
                    len(app.device.program_writes) == 127
                    and len(app.device.effect_writes) == 128
                    and len(app.device.mix_writes) == 100
                    and len(app.device.global_writes) == 1
                ),
            )
            await pilot.press("z")
            await _until(
                pilot,
                lambda: (
                    len(app.device.program_writes) == 254
                    and len(app.device.effect_writes) == 256
                    and len(app.device.mix_writes) == 200
                    and len(app.device.global_writes) == 2
                ),
            )
            assert len(app._undo_log) == 0

    def test_key_hints_and_binding(self):
        assert "R restore" in KEY_HINTS
        assert "R restore" in WRITE_HINTS
        bindings = [b.key for b in NanosynedApp.BINDINGS]
        assert "R" in bindings
        actions = {b.key: b.action for b in NanosynedApp.BINDINGS}
        assert actions["R"] == "restore"


def test_backup_file_is_a_full_backup(tmp_path):
    """The fixture really is the 356-record file the screen claims."""
    from nano import dumps

    path = backup_file(tmp_path)
    library = dumps.read_syx_file(path)
    assert len(library.programs) == 127
    assert len(library.effects) == 128
    assert len(library.mixes) == 100
    assert library.globals_ is not None
    assert os.path.getsize(path) == 79071
