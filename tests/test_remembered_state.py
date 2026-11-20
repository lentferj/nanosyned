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

"""The browser remembering where it was, beside the config it was given.

Two halves are pinned together, for the reason the sibling p2ked states:
what was remembered must come back, and whatever comes back must be sane.
A launch that opens on a narrowed view with nothing saying why is the
silent narrowing CLAUDE.md warns about, so the keys below are restored
*and* validated one at a time.

Every path is injected. ``NanosynedApp(config_path=None)`` means a test
asked for no disk access at all, and the last class here proves that
asking for silence really is silent: no config, no ui state, no file in
whatever directory pytest happened to be started from.

Names in the fixtures are invented, per CLAUDE.md. No MIDI port is
opened: the demo device is the only device here.
"""

from __future__ import annotations

import os
import tomllib

import pytest
from textual.widgets import DataTable

from nano import catalog as cat
from nano import config
from nano.favorites import Favorites
from nanosyned.app import (
    VIEW_ALL,
    VIEW_ALL_FAVOURITES,
    VIEW_BANK_FAVOURITES,
    NanosynedApp,
)
from nanosyned.demo import DemoDevice
from nanosyned.scan import ScanOfferScreen
from vinsynlib.ui.modals import RatingFilter

#: Which bank row and slot row the round-trip test remembers. Row 2 is
#: Preset 1; the all-favourites view keeps the same eight rows whichever
#: bank the left pane is on, so the slot row is meaningful on its own.
BANK_ROW = 2
SLOT_ROW = 7
#: How many invented favourites the round-trip test seeds, so row 7 exists.
FAVOURITES = 8


def config_path(tmp_path) -> str:
    """The settings file: the channel and the port live here."""
    return str(tmp_path / "config.toml")


def ui_state_path(tmp_path) -> str:
    """The ui-state sidecar beside the injected settings file."""
    return config.ui_state_path(config_path(tmp_path))


def catalog_path(tmp_path) -> str:
    """A sidecar path inside ``tmp_path``, never the checkout's own."""
    return str(tmp_path / "catalog.json")


def make(tmp_path, *, catalog=None, favorites=None, config_file=None):
    """An app with every path injected, and a small non-empty catalog.

    The catalog is non-empty by default so the deferred scan offer does
    not open a modal over a test that is about cursor rows. A test about
    the offer passes ``catalog=cat.empty()``.
    """
    return NanosynedApp(
        DemoDevice(),
        catalog=catalog
        if catalog is not None
        else cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        favorites=favorites,
        config_path=config_path(tmp_path) if config_file is None else config_file,
        catalog_path=catalog_path(tmp_path),
    )


def seeded_store(tmp_path, count: int = FAVOURITES) -> Favorites:
    """A favourites database with ``count`` invented rows in General MIDI."""
    store = Favorites(str(tmp_path / "favourites.db"))
    for number in range(count):
        store.add("GM", number, name=f"Invented Program {number}", rating=3)
    return store


async def _until(pilot, ready, attempts: int = 100) -> None:
    """Wait until ``ready()``, or fail saying that it never happened.

    A fixed number of pauses would be a guess about how many trips
    through the message loop this machine takes; a guess in a test is a
    flake.
    """
    for _ in range(attempts):
        if ready():
            return
        await pilot.pause()
    raise AssertionError("the app never reached the state the test waited for")


class TestTheStoreRoundTrips:
    """``nano.config`` alone: write a key, read it back, forget it.

    The store is vinsynlib's, bound here as ``nano.config``. The app can
    only be as honest as this file, so the round trip is checked first.
    """

    def test_each_scalar_type_round_trips(self, tmp_path):
        path = ui_state_path(tmp_path)
        config.save_ui_state("bank_index", 3, path)
        config.save_ui_state("slot_cursor", 17, path)
        config.save_ui_state("view_mode", VIEW_BANK_FAVOURITES, path)
        config.save_ui_state("rating_stars", 3, path)
        config.save_ui_state("rating_at_least", True, path)
        config.save_ui_state("scan_offer_dismissed", True, path)

        assert config.load_ui_int("bank_index", path) == 3
        assert config.load_ui_int("slot_cursor", path) == 17
        assert config.load_ui_str("view_mode", path) == VIEW_BANK_FAVOURITES
        assert config.load_ui_int("rating_stars", path) == 3
        assert config.load_ui_bool("rating_at_least", path) is True
        assert config.load_ui_bool("scan_offer_dismissed", path) is True

    def test_a_missing_file_is_nothing_remembered(self, tmp_path):
        missing = str(tmp_path / "absent.toml")
        assert config.load_ui_int("bank_index", missing) is None
        assert config.load_ui_str("view_mode", missing) is None

    def test_a_missing_key_is_nothing_remembered(self, tmp_path):
        path = ui_state_path(tmp_path)
        config.save_ui_state("view_mode", VIEW_ALL, path)
        assert config.load_ui_int("bank_index", path) is None
        assert config.load_ui_bool("scan_offer_dismissed", path) is None

    def test_none_forgets_the_key(self, tmp_path):
        """Clearing writes an absence, not a false.

        A filter remembered as ``False`` would come back as a filter that
        matches nothing but its own tombstone.
        """
        path = ui_state_path(tmp_path)
        config.save_ui_state("rating_stars", 3, path)
        config.save_ui_state("rating_stars", None, path)
        assert config.load_ui_int("rating_stars", path) is None

    def test_a_bool_is_not_an_int_and_an_int_is_not_a_bool(self, tmp_path):
        """``isinstance(True, int)`` is how a wrong channel shipped once.

        A hand-edited ``rating_stars = true`` must not come back as one
        star, and ``rating_at_least = 3`` is not a bool.
        """
        path = ui_state_path(tmp_path)
        config.save_ui_state("rating_stars", True, path)
        config.save_ui_state("rating_at_least", 3, path)
        assert config.load_ui_int("rating_stars", path) is None
        assert config.load_ui_bool("rating_at_least", path) is None

    def test_a_non_scalar_is_refused_not_rounded(self, tmp_path):
        with pytest.raises(TypeError):
            config.save_ui_state("view_mode", ["all"], ui_state_path(tmp_path))


class TestSavingOneKeyLeavesTheOthersAlone:
    """One save call, one key -- every other key in the file survives.

    The trap the first ``_save_ui_state`` in the family shipped: rewriting
    the whole map with only the latest key in it. A store that cannot
    pass this class cannot hold a cleared filter and a saved position at
    the same time.
    """

    @staticmethod
    def _deposit(path: str) -> None:
        config.save_ui_state("bank_index", 2, path)
        config.save_ui_state("slot_cursor", 40, path)
        config.save_ui_state("rating_stars", 3, path)
        config.save_ui_state("rating_at_least", False, path)

    def test_saving_a_fourth_key_keeps_three(self, tmp_path):
        path = ui_state_path(tmp_path)
        self._deposit(path)
        config.save_ui_state("view_mode", VIEW_ALL_FAVOURITES, path)
        assert config.load_ui_int("bank_index", path) == 2
        assert config.load_ui_int("slot_cursor", path) == 40
        assert config.load_ui_int("rating_stars", path) == 3
        assert config.load_ui_bool("rating_at_least", path) is False
        assert config.load_ui_str("view_mode", path) == VIEW_ALL_FAVOURITES

    def test_clearing_the_filter_keeps_the_position(self, tmp_path):
        path = ui_state_path(tmp_path)
        self._deposit(path)
        config.save_ui_state("rating_stars", None, path)
        config.save_ui_state("rating_at_least", None, path)
        assert config.load_ui_int("bank_index", path) == 2
        assert config.load_ui_int("slot_cursor", path) == 40
        assert config.load_ui_int("rating_stars", path) is None
        assert config.load_ui_bool("rating_at_least", path) is None


class TestAnOldSettingsFileIsMigrated:
    """The pre-sidecar file must heal, not wedge every later save."""

    async def test_old_screen_keys_move_to_the_ui_state_file(self, tmp_path):
        folder = str(tmp_path / "programs")
        (tmp_path / "programs").mkdir()
        settings = tmp_path / "config.toml"
        settings.write_text(
            "# nanosyned local config - gitignored, safe to delete.\n"
            'port = "Invented Port"\n'
            "channel = 4\n"
            "bank_index = 2\n"
            "slot_cursor = 33\n"
            "mix_number = 0\n"
            f'import.folder = "{folder}"\n',
            encoding="utf-8",
        )
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app._ui_state_path is not None
            assert config.load_ui_str("import.folder", app._ui_state_path) == folder
            assert config.load_ui_int("bank_index", app._ui_state_path) == 2
            assert config.load_ui_int("slot_cursor", app._ui_state_path) == 33
            assert config.load_ui_int("mix_number", app._ui_state_path) == 0
            text = settings.read_text(encoding="utf-8")
            for key in ("bank_index", "slot_cursor", "mix_number", "import.folder"):
                assert key not in text
            data = tomllib.loads(text)
            assert not any(isinstance(value, (dict, list)) for value in data.values())
            # The settings writer accepts the file again, which is the
            # half the warning was about.
            config.save_channel(7, str(settings))
            assert config.load_channel(str(settings)) == 7

    def test_a_newer_sidecar_value_wins(self, tmp_path):
        """Migrating must not undo where the user has been since."""
        settings = tmp_path / "config.toml"
        settings.write_text(
            "# nanosyned local config - gitignored, safe to delete.\nbank_index = 2\n",
            encoding="utf-8",
        )
        ui_path = config.ui_state_path(str(settings))
        config.save_ui_state("bank_index", 4, ui_path)

        assert config.migrate_legacy_ui_state(str(settings), ui_path) == ("bank_index",)
        assert config.load_ui_int("bank_index", ui_path) == 4
        assert "bank_index" not in settings.read_text(encoding="utf-8")


class TestTheAppStartsWhereItLeftOff:
    """A second launch with the same config path restores the first one."""

    async def test_the_bank_view_and_slot_row_come_back(self, tmp_path):
        store = seeded_store(tmp_path)
        try:
            catalog = cat.Catalog([cat.Entry("GM", 0, "Invented One")])
            first = make(tmp_path, catalog=catalog, favorites=store)
            async with first.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                first.view_mode = VIEW_ALL_FAVOURITES
                first._fill("GM")
                await pilot.pause()
                assert len(first._current) == FAVOURITES
                first._save_ui_state(
                    bank_index=BANK_ROW,
                    slot_cursor=SLOT_ROW,
                    view_mode=VIEW_ALL_FAVOURITES,
                )

            assert config.load_ui_int("bank_index", ui_state_path(tmp_path)) == BANK_ROW
            assert (
                config.load_ui_int("slot_cursor", ui_state_path(tmp_path)) == SLOT_ROW
            )
            assert (
                config.load_ui_str("view_mode", ui_state_path(tmp_path))
                == VIEW_ALL_FAVOURITES
            )

            second = make(tmp_path, catalog=catalog, favorites=store)
            async with second.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert second.view_mode == VIEW_ALL_FAVOURITES
                assert second._current_bank == "P1"
                assert second.query_one("#bank-table", DataTable).cursor_row == (
                    BANK_ROW
                )
                slots = second.query_one("#slot-table", DataTable)
                # The settle timer re-applies the row; wait for it rather
                # than guessing a delay, and prove it stays put.
                await _until(pilot, lambda: slots.cursor_row == SLOT_ROW)
                await pilot.pause()
                assert slots.cursor_row == SLOT_ROW
                assert len(second._current) == FAVOURITES
                # One-shot: yesterday's row is applied once, then gone.
                assert second._saved_slot_cursor is None
        finally:
            store.close()

    async def test_the_slot_row_lands_on_the_remembered_bank(self, tmp_path):
        """A slot row is an index into the bank on screen.

        Restoring it without the bank would point at a different slot --
        the one way "remember where I was" can quietly mean "somewhere
        else".
        """
        store = seeded_store(tmp_path)
        try:
            app = make(tmp_path, favorites=store)
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                app.view_mode = VIEW_ALL
                app._fill("P1")
                await pilot.pause()
                app._save_ui_state(bank_index=BANK_ROW, slot_cursor=SLOT_ROW)
            again = make(tmp_path, favorites=store)
            async with again.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert again._current_bank == "P1"
                table = again.query_one("#slot-table", DataTable)
                # The restore runs once at startup and is re-applied by a
                # settle timer; a fixed sleep races it on a busy machine.
                await _until(pilot, lambda: table.cursor_row == SLOT_ROW)
                await pilot.pause()
                assert table.cursor_row == SLOT_ROW
                assert table.get_row_at(SLOT_ROW)[1] == "Preset 1 007"
        finally:
            store.close()


class TestAHandEditedFileMustNotWedge:
    """Bad values are ignored, not obeyed, one key at a time."""

    async def test_an_unknown_view_is_ignored(self, tmp_path):
        config.save_ui_state(
            "view_mode", "a-view-from-another-build", ui_state_path(tmp_path)
        )
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app.view_mode == VIEW_ALL

    @pytest.mark.parametrize("stale", [99999, -1, 6])
    async def test_an_out_of_range_bank_is_ignored(self, tmp_path, stale):
        config.save_ui_state("bank_index", stale, ui_state_path(tmp_path))
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app._current_bank == "GM"
            assert app.query_one("#bank-table", DataTable).cursor_row == 0

    async def test_good_keys_of_a_bad_file_still_apply(self, tmp_path):
        """Ignoring one key is not ignoring the file."""
        config.save_ui_state("bank_index", BANK_ROW, ui_state_path(tmp_path))
        config.save_ui_state("view_mode", "somewhere-else", ui_state_path(tmp_path))
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app._current_bank == "P1"
            assert app.query_one("#bank-table", DataTable).cursor_row == BANK_ROW
            assert app.view_mode == VIEW_ALL

    async def test_a_stale_slot_row_is_clamped_rather_than_raising(self, tmp_path):
        """The row may not exist any more; the launch must still open."""
        config.save_ui_state("bank_index", 0, ui_state_path(tmp_path))
        config.save_ui_state("slot_cursor", 5000, ui_state_path(tmp_path))
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            await pilot.pause(0.15)
            table = app.query_one("#slot-table", DataTable)
            assert table.cursor_row == len(app._current) - 1


class TestTheRatingFilterRoundTrips:
    """The filter is remembered as two keys, and cleared as two absences."""

    def test_it_round_trips_and_clears(self, tmp_path):
        store = seeded_store(tmp_path)
        path = ui_state_path(tmp_path)

        def open_app():
            return make(tmp_path, favorites=store)

        try:
            first = open_app()
            first.rating_filter = RatingFilter(stars=4, at_least=True)
            first._save_rating_filter()

            again = open_app()
            assert again.rating_filter == RatingFilter(stars=4, at_least=True)
            assert config.load_ui_int("rating_stars", path) == 4
            assert config.load_ui_bool("rating_at_least", path) is True

            again.rating_filter = None
            again._save_rating_filter()

            third = open_app()
            assert third.rating_filter is None
            assert config.load_ui_int("rating_stars", path) is None
            assert config.load_ui_bool("rating_at_least", path) is None
        finally:
            store.close()

    async def test_a_hand_edited_six_stars_is_not_a_filter(self, tmp_path):
        """Nine stars is a typo, not a filter nobody would have chosen."""
        config.save_ui_state("rating_stars", 9, ui_state_path(tmp_path))
        config.save_ui_state("rating_at_least", True, ui_state_path(tmp_path))
        app = make(tmp_path)
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            assert app.rating_filter is None

    async def test_the_filter_narrows_the_first_fill(self, tmp_path):
        """Restored before ``on_mount``, so the first fill already obeys it."""
        store = seeded_store(tmp_path, count=4)
        try:
            store.set_rating("GM", 0, 1)
            store.set_rating("GM", 1, 5)
            store.set_rating("GM", 2, 5)
            config.save_ui_state("rating_stars", 5, ui_state_path(tmp_path))
            config.save_ui_state("rating_at_least", False, ui_state_path(tmp_path))
            app = make(tmp_path, favorites=store)
            async with app.run_test(size=(200, 50)) as pilot:
                await pilot.pause()
                assert [entry.number for entry in app._current] == [1, 2]
        finally:
            store.close()


class TestTheScanOfferIsRemembered:
    """``scan_offer_dismissed`` is honoured from the file it was written to."""

    async def test_a_dismissal_in_the_file_stops_the_offer(self, tmp_path):
        config.save_ui_state("scan_offer_dismissed", True, ui_state_path(tmp_path))
        app = make(tmp_path, catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_without_a_dismissal_the_offer_is_still_made(self, tmp_path):
        app = make(tmp_path, catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            assert isinstance(app.screen, ScanOfferScreen)


class TestNoPathNoFile:
    """``NanosynedApp(DemoDevice())`` must not invent a place to remember."""

    async def test_without_a_path_it_runs_and_remembers_nothing(
        self, tmp_path, monkeypatch
    ):
        scratch = tmp_path / "elsewhere"
        scratch.mkdir()
        monkeypatch.chdir(scratch)
        here = os.getcwd()
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.Catalog([cat.Entry("GM", 0, "Invented One")]),
        )
        assert app._config_path is None
        assert app._ui_state_path is None
        async with app.run_test(size=(200, 50)) as pilot:
            await pilot.pause()
            app._save_ui_state(
                bank_index=BANK_ROW,
                slot_cursor=SLOT_ROW,
                view_mode=VIEW_ALL_FAVOURITES,
                rating_stars=3,
                rating_at_least=True,
                scan_offer_dismissed=True,
            )
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            app._save_rating_filter()
            app._set_channel(4)
            await pilot.pause()
        assert app.device.channel == 4
        assert os.getcwd() == here, "the app moved somewhere to remember"
        assert list(scratch.iterdir()) == []
        assert not list(tmp_path.rglob("config.toml"))
        assert not list(tmp_path.rglob("ui-state.toml"))
