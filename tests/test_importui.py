# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The escaping of unit-supplied text is ported from the sibling emorphed
# and rxved projects, which fix the same bug, and which carry the same
# licence:
#   Copyright (C) 2026  emorphed / rxved contributors
#                                     - GPL-2.0-or-later
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

"""The import picker: listing, filter, descend, choose, remember, cancel.

No hardware, no parse, no device: the screen only lists folders, so every
fixture here is invented and lives in a temporary directory. The app is the
demo, and its config path is injected, so the remembered folder is a
temporary file rather than somebody's.
"""

from __future__ import annotations

import os

import pytest
from textual.widgets import DataTable, Static

from nano import catalog as cat
from nano import config
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.picker import FilePickerScreen


def make(tmp_path) -> NanosynedApp:
    """An offline app whose config path is a temporary file."""
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
    )


async def _until(pilot, ready, attempts: int = 100) -> bool:
    """Wait until ``ready()``, or fail saying that it never happened."""
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


async def _open(pilot, screen, seen) -> None:
    """Push a picker over the running app and wait for it to mount."""
    app = pilot.app
    app.push_screen(screen, seen.append)
    await _until(pilot, lambda: isinstance(app.screen, FilePickerScreen))
    await _until(pilot, lambda: len(app.screen.query("#picker-table")) == 1)


class TestTheFilePicker:
    """The picker's own keys, with no import behind them yet."""

    async def test_lists_the_folder_and_its_import_files(self, tmp_path):
        (tmp_path / "programs").mkdir()
        (tmp_path / "qesence1.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2
            assert str(table.get_row_at(0)[0]) == "programs/"
            assert str(table.get_row_at(1)[0]) == "qesence1.syx"

    async def test_the_filter_narrows_the_listing(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        (tmp_path / "qesence2.syx").touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 2
            await pilot.press("slash")
            await pilot.press("q", "e", "s", "e", "n", "c", "e", "1")
            await pilot.pause()
            assert table.row_count == 1
            assert str(table.get_row_at(0)[0]) == "qesence1.syx"

    async def test_enter_enters_a_directory(self, tmp_path):
        (tmp_path / "programs").mkdir()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            await pilot.press("enter")
            await pilot.pause()
            assert screen.folder == str(tmp_path / "programs")
            assert screen._rows == []

    async def test_enter_on_a_file_returns_its_path(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        seen: list[str | None] = []
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            await pilot.press("enter")
            await _until(pilot, lambda: bool(seen))
            assert seen == [str(tmp_path / "qesence1.syx")]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))

    async def test_the_folder_is_remembered_across_two_mounts(self, tmp_path):
        (tmp_path / "qesence1.syx").touch()
        config.save_ui_state(
            "import.folder", str(tmp_path), str(tmp_path / "config.toml")
        )
        seen: list[str | None] = []
        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            first = app.screen
            assert first.folder == str(tmp_path)
            await pilot.press("enter")
            await _until(pilot, lambda: bool(seen))
            assert seen == [str(tmp_path / "qesence1.syx")]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))
        assert config.load_ui_str(
            "import.folder", str(tmp_path / "config.toml")
        ) == str(tmp_path)

        app = make(tmp_path)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            assert app.screen.folder == str(tmp_path)

    async def test_a_remembered_folder_that_is_gone_falls_back_to_home(self, tmp_path):
        config.save_ui_state(
            "import.folder", str(tmp_path / "absent"), str(tmp_path / "config.toml")
        )
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(), seen)
            screen = app.screen
            assert screen.folder == os.path.expanduser("~")
            status = screen.query_one("#picker-status", Static)
            assert "gone or unreadable" in str(status.content)

    async def test_a_long_or_bracketed_name_does_not_crash_the_markup(
        self, tmp_path
    ) -> None:
        long_name = "q" * 200 + "[bracketed].syx"
        (tmp_path / long_name).touch()
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            screen = app.screen
            table = screen.query_one("#picker-table", DataTable)
            assert table.row_count == 1
            assert str(screen.query_one("#picker-status", Static).content)

    @pytest.mark.parametrize("key", ["escape", "q"])
    async def test_escape_and_q_return_none(self, tmp_path, key):
        app = make(tmp_path)
        seen: list[str | None] = []
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _open(pilot, FilePickerScreen(path=str(tmp_path)), seen)
            await pilot.press(key)
            await _until(pilot, lambda: bool(seen))
            assert seen == [None]
            await _until(pilot, lambda: not isinstance(app.screen, FilePickerScreen))
