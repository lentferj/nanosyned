# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

from __future__ import annotations

import os

from textual.widgets import Static

from nano import catalog as cat
from nano import config, dumps
from nano import favorites as favmod
from nanosyned.app import KEY_HINTS, NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.importprogress import ImportProgressScreen
from nanosyned.screens import PromptScreen
from vinsynlib.ui.confirm import ConfirmScreen


def make(tmp_path, favorites=None):
    ui_path = config.ui_state_path(str(tmp_path / "config.toml"))
    config.save_ui_state("import.folder", str(tmp_path), ui_path)
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        config_path=str(tmp_path / "config.toml"),
        catalog_path=str(tmp_path / "catalog.json"),
        favorites=favorites,
    )


async def _until(pilot, ready, attempts=200):
    for _ in range(attempts):
        if ready():
            return True
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


def seed_favorites(tmp_path):
    db = favmod.Favorites(str(tmp_path / "fav.db"))
    db.add("USER", 0, name="Zero")
    db.add("USER", 1, name="One")
    db.close()
    return favmod.Favorites(str(tmp_path / "fav.db"))


class TestExportUI:
    async def test_e_exports_two_favourites(self, tmp_path):
        favs = seed_favorites(tmp_path)
        app = make(tmp_path, favorites=favs)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("E")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            # accept default path
            await pilot.press("enter")
            await _until(
                pilot, lambda: not isinstance(app.screen, ImportProgressScreen)
            )
            await pilot.pause()
            path = os.path.join(str(tmp_path), "nanosyned-favourites.syx")
            assert os.path.exists(path)
            lib = dumps.read_syx_file(path)
            assert len(lib.programs) == 2
            assert set(lib.programs) == {0, 1}
            status = str(app.query_one("#status", Static).content)
            assert "exported 2 program(s)" in status

    async def test_existing_path_confirms(self, tmp_path):
        favs = seed_favorites(tmp_path)
        path = os.path.join(str(tmp_path), "nanosyned-favourites.syx")
        with open(path, "wb") as f:
            f.write(b"old")
        app = make(tmp_path, favorites=favs)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("E")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("enter")
            await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
            # n leaves file untouched
            await pilot.press("n")
            await _until(pilot, lambda: not isinstance(app.screen, ConfirmScreen))
            await pilot.pause()
            with open(path, "rb") as f:
                assert f.read() == b"old"
            # second run, y replaces
            await pilot.press("E")
            await _until(pilot, lambda: isinstance(app.screen, PromptScreen))
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
            assert len(lib.programs) == 2

    async def test_no_favourites_refused(self, tmp_path):
        favs = favmod.Favorites(str(tmp_path / "fav.db"))
        app = make(tmp_path, favorites=favs)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("E")
            await pilot.pause()
            path = os.path.join(str(tmp_path), "nanosyned-favourites.syx")
            assert not os.path.exists(path)
            status = str(app.query_one("#status", Static).content)
            assert "no favourited" in status or "no favourites" in status

    async def test_no_store_refused(self, tmp_path):
        app = make(tmp_path, favorites=None)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await pilot.press("E")
            await pilot.pause()
            path = os.path.join(str(tmp_path), "nanosyned-favourites.syx")
            assert not os.path.exists(path)

    def test_key_hints_and_binding(self):
        assert "E export favourites" in KEY_HINTS
        bindings = [b.key for b in NanosynedApp.BINDINGS]
        assert "E" in bindings
        actions = {b.key: b.action for b in NanosynedApp.BINDINGS}
        assert actions["E"] == "export_favourites"


class TestVerbDefault:
    def test_default_verb_importing(self):
        s = ImportProgressScreen(total=1)
        assert s._verb == "importing"
