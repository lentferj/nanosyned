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

"""The browser. Every fixture is invented; no MIDI port is ever opened."""

import ast
import os
import threading

import pytest
from textual.widgets import Input

from nano import banks, verify
from nano import catalog as cat
from nano import config as cfg
from nano import favorites as fav
from nano import records as rec
from nanosyned.app import VIEW_ALL_FAVOURITES, NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.scan import ScanOfferScreen, ScanScreen
from nanosyned.screens import EditorScreen
from vinsynlib.ui.modals import RatingFilter
from vinsynlib.ui.prompt import PromptScreen


@pytest.fixture
def app():
    catalog = cat.Catalog([cat.Entry("GM", 0, "Invented Name")])
    return NanosynedApp(DemoDevice(), catalog=catalog)


class TestStartup:
    async def test_both_panes_fill(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#bank-table").row_count == len(banks.BANKS)
            assert app.query_one("#slot-table").row_count == banks.PROGRAMS_PER_BANK


class TestCursorIsSilent:
    """The property that decides whether this can sit open next to a
    running sequencer. It is the first test in every sibling project."""

    async def test_moving_in_the_program_pane_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            for _ in range(12):
                await pilot.press("down")
            await pilot.press("end")
            for _ in range(6):
                await pilot.press("up")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_moving_between_banks_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#bank-table").focus()
            for _ in range(len(banks.BANKS) + 2):
                await pilot.press("down")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_changing_the_channel_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("]")
            await pilot.press("[")
            await pilot.pause()
            assert app.device.selected_log == []

    async def test_cycling_the_view_sends_nothing(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(4):
                await pilot.press("v")
            await pilot.pause()
            assert app.device.selected_log == []


class TestSelection:
    async def test_enter_selects_and_says_which_bank(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert len(app.device.selected_log) == 1
            slot, channel = app.device.selected_log[0]
            assert slot.bank_id == banks.BANKS[0].id
            assert channel == app.device.channel

    async def test_the_channel_goes_with_it(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app.device.channel = 9
            app.query_one("#slot-table").focus()
            await pilot.press("enter")
            for _ in range(8):
                await pilot.pause()
            assert app.device.selected_log[0][1] == 9

    async def test_two_selections_in_a_row_send_one(self):
        """The busy guard is set where it is checked, on the main thread."""
        app = NanosynedApp(DemoDevice(latency=0.5), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.pause()
            app.action_select()
            app.action_select()
            for _ in range(60):
                await pilot.pause()
            assert len(app.device.selected_log) == 1


class TestReadingNames:
    async def test_a_rom_bank_is_refused_before_anything_is_sent(self, app):
        """Four of the five banks have no dump request at all."""
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("GM")
            await pilot.pause()
            await pilot.press("r")
            for _ in range(6):
                await pilot.pause()
            assert app.catalog.live_name("GM", 0) is None

    async def test_the_user_bank_is_read(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("USER")
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.catalog.live_name("USER", 0) is not None

    async def test_reading_names_makes_no_sound(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("USER")
            await pilot.pause()
            await pilot.press("r")
            for _ in range(40):
                await pilot.pause()
            assert app.device.selected_log == []


class TestFavouritesActOnTheRowNotThePane:
    """The all-favourites view spans banks; the bank pane sits on one.

    The sibling x5ded read the pane's bank in two actions while its fill
    read the row's, so `f` favourited a slot the user was not looking at.
    """

    async def test_f_uses_the_rows_own_bank(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("P2", 5, name="Invented", rating=3)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.view_mode = VIEW_ALL_FAVOURITES
            app._fill("GM")  # pane elsewhere; row is P2:5
            await pilot.pause()
            assert [(e.bank_id, e.number) for e in app._current] == [("P2", 5)]
            app.query_one("#slot-table").focus()
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()
            assert store.get("GM", 5) is None, "favourited the wrong bank"
            assert store.get("P2", 5) is None, "P2:5 should be unfavourited"
        store.close()

    async def test_the_bank_table_count_updates_on_toggle(self, tmp_path):
        """Toggling a favourite on a Preset updates the bank-table counter."""
        store = fav.Favorites(str(tmp_path / "f.db"))
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            bank_table = app.query_one("#bank-table")
            # Find the P2 row's initial count (should be empty).
            p2_row = bank_table.get_row("P2")
            assert p2_row[3] == ""  # no favourites in P2 yet

            app._fill("P2")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()

            # The count column should now show "1".
            p2_row = bank_table.get_row("P2")
            assert p2_row[3] == "1"

            # Toggle off: count goes back to empty.
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()
            p2_row = bank_table.get_row("P2")
            assert p2_row[3] == ""
        store.close()

    async def test_f_keeps_the_cursor_row(self, tmp_path):
        """Marking a favourite keeps the cursor where it was, not at the end."""
        store = fav.Favorites(str(tmp_path / "f.db"))
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Add several favourites so the all-favourites view has rows
            # in the middle to land on.
            for n in (0, 1, 2, 3, 4):
                store.add("P2", n, name=f"Prog {n}")
            app.view_mode = VIEW_ALL_FAVOURITES
            app._fill("P2")
            await pilot.pause()
            table = app.query_one("#slot-table")
            assert len(app._current) == 5
            # Put the cursor on the middle row.
            table.move_cursor(row=2)
            await pilot.pause()
            assert table.cursor_row == 2
            # Mark it as a favourite (it already is; toggling removes it).
            app.query_one("#slot-table").focus()
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()
            # The view stays put: the cursor is still on the same slot,
            # now gone, so it clamps to the row that took its place.
            assert table.cursor_row == 2
            assert [e.number for e in app._current] == [0, 1, 3, 4]
            # The scroll offset must also stay: a refill that cleared and
            # re-added every row used to leave the table scrolled to the
            # bottom, so the row under the cursor was off-screen.
            assert table.scroll_y == 0 or table.scroll_y < 4
        store.close()

    async def test_f_keeps_scroll_with_long_list(self, tmp_path):
        """Scroll position is preserved with a long favourite list."""
        store = fav.Favorites(str(tmp_path / "f.db"))
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Add many favourites to make a long list that scrolls.
            for n in range(20):
                store.add("P2", n, name=f"Prog {n}")
            app.view_mode = VIEW_ALL_FAVOURITES
            app._fill("P2")
            await pilot.pause()
            table = app.query_one("#slot-table")
            assert len(app._current) == 20
            # Scroll down so the cursor is on row 10 but visually the table
            # is scrolled (rows 0-9 are off-screen).
            table.move_cursor(row=10)
            await pilot.pause()
            # In the test harness the DataTable may not report a scroll offset
            # unless we use keyboard navigation, so simulate down-arrow.
            for _ in range(10):
                await pilot.press("down")
            await pilot.pause()
            cursor_before = table.cursor_row
            scroll_before = table.scroll_y
            # Toggle favourite on the current row.
            await pilot.press("f")
            for _ in range(4):
                await pilot.pause()
            # Cursor and scroll should stay on the same visual position.
            assert table.cursor_row == cursor_before
            # The scroll should not jump to the end.
            assert table.scroll_y <= scroll_before + 1
        store.close()


class TestTheLegendIsComplete:
    def _app_source(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "nanosyned",
            "app.py",
        )
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def _workers(self):
        tree = ast.parse(self._app_source())
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if any(
                (isinstance(d, ast.Call) and getattr(d.func, "id", "") == "work")
                or getattr(d, "id", "") == "work"
                for d in node.decorator_list
            ):
                yield node

    def test_there_are_workers_to_check(self):
        assert list(self._workers())

    def test_no_worker_touches_the_favourites_store(self):
        """SQLite refuses cross-thread use, and a worker that asks for
        `len(self.favorites)` raises out of the worker, which ends the
        application. That is exactly what `i` did in the sibling rxved."""
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Attribute)
                    and inner.attr in ("favorites", "catalog")
                    and isinstance(inner.value, ast.Name)
                    and inner.value.id == "self"
                ):
                    offenders.append(node.name)
        assert not offenders, (
            f"worker(s) {sorted(set(offenders))} reach self.favorites or "
            f"self.catalog; workers do MIDI and hand off with "
            f"call_from_thread"
        )

    def test_no_worker_sets_the_busy_flag_itself(self):
        """By the time a worker runs, a second keypress has already passed
        the check its caller made."""
        offenders = []
        for node in self._workers():
            for inner in ast.walk(node):
                if (
                    isinstance(inner, ast.Assign)
                    and any(
                        isinstance(t, ast.Attribute) and t.attr == "_busy"
                        for t in inner.targets
                    )
                    and getattr(inner.value, "value", None) is True
                ):
                    offenders.append(node.name)
        assert not offenders, f"worker(s) {offenders} set _busy themselves"


class TestSearch:
    """The search form returns ``(needle, {field: enabled})``.

    It used to be a name-only prompt, and the callback used to unpack the
    catalog's four-tuples as three, so any search that found a match
    raised ValueError instead of showing the match -- the bug was
    invisible because nothing exercised the callback.
    """

    async def test_a_match_is_shown(self):
        catalog = cat.Catalog([cat.Entry("GM", 0, "Invented Name")])
        app = NanosynedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_search()
            await pilot.pause()
            app.screen.dismiss(
                ("Invented", {"names": True, "tags": True, "notes": True})
            )
            await pilot.pause()
            assert "Invented Name" in app.screen.body

    def test_each_field_scopes_its_own_source(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("GM", 3, name="Invented", tags="warm, pad", note="a soft pad")
        catalog = cat.Catalog([cat.Entry("GM", 0, "Invented Name")])
        app = NanosynedApp(DemoDevice(), catalog=catalog, favorites=store)
        names_only = app._search_rows(
            "Invented", {"names": True, "tags": False, "notes": False}
        )
        assert ("GM", 0) in names_only
        tags_only = app._search_rows(
            "warm", {"names": False, "tags": True, "notes": False}
        )
        assert tags_only == {("GM", 3): ["tags warm, pad"]}
        notes_only = app._search_rows(
            "soft", {"names": False, "tags": False, "notes": True}
        )
        assert notes_only == {("GM", 3): ["note a soft pad"]}
        store.close()

    def test_tags_and_notes_are_escaped(self, tmp_path):
        """Both are user-supplied text rendered into a markup widget."""
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("GM", 3, name="Invented", tags="[b]pad", note="[i]soft")
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        rows = app._search_rows(
            "[b]pad", {"names": False, "tags": True, "notes": False}
        )
        assert rows[("GM", 3)] == [r"tags \[b]pad"]
        rows = app._search_rows("soft", {"names": False, "tags": False, "notes": True})
        assert rows[("GM", 3)] == [r"note \[i]soft"]
        store.close()


class TestRatings:
    async def test_the_slot_table_has_a_five_wide_rating_column(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            column = app.query_one("#slot-table").columns["rating"]
            assert column.width == 5

    async def test_rating_creates_the_favourite(self, tmp_path):
        """``set_rating`` routes through ``add``; the library pins that."""
        store = fav.Favorites(str(tmp_path / "f.db"))
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#slot-table").focus()
            app.action_edit_rating()
            await pilot.pause()
            app.screen.dismiss(4)
            for _ in range(4):
                await pilot.pause()
            favourite = store.get("GM", 0)
            assert favourite is not None
            assert favourite.rating == 4
            assert "rated 4" in str(app.query_one("#status").content)
        store.close()

    async def test_the_cell_shows_the_rating(self, tmp_path):
        from nano.favorites import rating_cell

        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("GM", 0, name="Invented", rating=3)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("GM")
            await pilot.pause()
            table = app.query_one("#slot-table")
            assert table.get_cell("GM:000", "rating") == rating_cell(3)
        store.close()

    async def test_the_filter_is_exactly_or_at_least(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "f.db"))
        store.add("GM", 0, rating=1)
        store.add("GM", 2, rating=3)
        store.add("GM", 4, rating=5)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.rating_filter = RatingFilter(stars=3, at_least=False)
            app._fill("GM")
            await pilot.pause()
            assert [entry.number for entry in app._current] == [2]
            app.rating_filter = RatingFilter(stars=3, at_least=True)
            app._fill("GM")
            await pilot.pause()
            assert [entry.number for entry in app._current] == [2, 4]
            # Zero means "any", not "the unrated ones": it is the value
            # the dialog produces when the filter is cleared.
            app.rating_filter = RatingFilter(stars=0, at_least=False)
            app._fill("GM")
            await pilot.pause()
            assert len(app._current) == banks.PROGRAMS_PER_BANK
            # Unfavourited slots have rating 0, and "exactly 0" is a real
            # question with those 125 as its answer.
            app.rating_filter = RatingFilter(stars=0, at_least=True)
            app._fill("GM")
            await pilot.pause()
            assert len(app._current) == banks.PROGRAMS_PER_BANK
        store.close()

    def test_the_filter_is_remembered_and_forgotten(self, tmp_path):
        path = str(tmp_path / "config.toml")
        store = fav.Favorites(str(tmp_path / "f.db"))

        def open_app():
            return NanosynedApp(
                DemoDevice(),
                catalog=cat.empty(),
                favorites=store,
                config_path=path,
            )

        app = open_app()
        app.rating_filter = RatingFilter(stars=3, at_least=True)
        app._save_rating_filter()
        again = open_app()
        assert again.rating_filter == RatingFilter(stars=3, at_least=True)
        assert cfg.load_ui_int("rating_stars", path) == 3
        assert cfg.load_ui_bool("rating_at_least", path) is True

        again.rating_filter = None
        again._save_rating_filter()
        third = open_app()
        assert third.rating_filter is None
        assert cfg.load_ui_int("rating_stars", path) is None
        assert cfg.load_ui_bool("rating_at_least", path) is None
        store.close()

    async def test_the_channel_is_remembered_across_restarts(self, tmp_path):
        """The last send channel survives a restart, like the other UI state.

        The channel is written by ``_remember_channel`` and read by
        ``main`` for hardware, but the TUI never loaded it back, so a
        session that moved off channel 1 opened on channel 1 again.
        """
        path = str(tmp_path / "config.toml")

        def open_app():
            return NanosynedApp(
                DemoDevice(),
                catalog=cat.empty(),
                config_path=path,
            )

        app = open_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            app._set_channel(7)
            await pilot.pause()

        assert cfg.load_channel(path) == 7

        again = open_app()
        assert again._channel() == 7

        # A bad value is not trusted: the app opens on the default.
        cfg.save_channel(99, path)
        third = open_app()
        assert third._channel() == 0


class TestScan:
    async def test_the_offer_has_three_answers(self):
        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ScanOfferScreen())
            await pilot.pause()
            ids = {button.id for button in app.screen.query("Button")}
            assert ids == {"scan", "later", "never"}

    async def test_an_empty_browser_offers_a_scan(self, tmp_path):
        path = str(tmp_path / "config.toml")
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.empty(),
            config_path=path,
            # A sidecar beside a catalog of its own: the checkout's real
            # live-names file would otherwise make this browser look full.
            catalog_path=str(tmp_path / "catalog.json"),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            assert isinstance(app.screen, ScanOfferScreen)

    async def test_a_full_catalog_is_not_offered(self, tmp_path):
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.Catalog([cat.Entry("GM", 0, "Invented Name")]),
            config_path=str(tmp_path / "config.toml"),
            catalog_path=str(tmp_path / "catalog.json"),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)

    async def test_never_is_remembered(self, tmp_path):
        path = str(tmp_path / "config.toml")
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.empty(),
            config_path=path,
            catalog_path=str(tmp_path / "catalog.json"),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            app.screen.dismiss("never")
            await pilot.pause()
            app._maybe_offer_scan()
            await pilot.pause()
            assert not isinstance(app.screen, ScanOfferScreen)
            assert cfg.load_ui_bool("scan_offer_dismissed", path, default=False) is True

    async def test_the_scan_screen_returns_the_names(self):
        def read(on_progress, cancel):
            on_progress(1, 2)
            on_progress(2, 2)
            return {0: "Invented"}

        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        seen = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ScanScreen(read, total=2), seen.append)
            for _ in range(40):
                await pilot.pause()
                if seen:
                    break
            assert seen == [{0: "Invented"}]

    async def test_cancel_stops_the_scan(self):
        started = threading.Event()

        def read(on_progress, cancel):
            on_progress(1, 2)
            started.set()
            while not cancel.wait(0.01):
                pass
            return {0: "never"}

        app = NanosynedApp(DemoDevice(), catalog=cat.empty())
        seen = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ScanScreen(read, total=2), seen.append)
            await pilot.pause()
            assert started.wait(1)
            await pilot.press("escape")
            for _ in range(60):
                await pilot.pause()
                if seen:
                    break
            assert seen == [None]

    async def test_scanning_reads_the_user_bank_and_makes_no_sound(self, tmp_path):
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.empty(),
            catalog_path=str(tmp_path / "catalog.json"),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.catalog.live_name("USER", 0) is None
            app.action_scan_device()
            for _ in range(200):
                await pilot.pause()
                if app.catalog.live_name("USER", 0) is not None:
                    break
            assert app.catalog.live_name("USER", 0) is not None
            assert app.device.selected_log == []


class TestWriting:
    """T4.5 + T5.1: the gate, the store sequence, and undo.

    The assertions are on the demo's ``program_writes`` log and on the
    record the demo holds, not on status sentences: the log is what actually
    crossed the wire, and a sentence can claim anything. The backup is
    redirected into ``tmp_path`` so a test never writes a restore point into
    the user's real settings directory.
    """

    @staticmethod
    def _backup_into(monkeypatch, tmp_path, saved):
        """Replace ``nano.backup.save`` with a recorder.

        The app imports the module inside its worker and calls ``bk.save``,
        so patching the attribute is enough -- and it keeps the test's
        backup in ``tmp_path`` rather than in ``~/.config/nanosyned``.
        """
        from nano import backup as bk

        def save(slot, *, kind, name, blocks, **kwargs):
            saved.append(
                {"slot": slot, "kind": kind, "name": name, "blocks": dict(blocks)}
            )
            return str(tmp_path / "program.backup.json")

        monkeypatch.setattr(bk, "save", save)

    @staticmethod
    async def _wait(pilot, predicate, tries=160):
        """Pause until ``predicate()`` holds; the work runs on a worker."""
        for _ in range(tries):
            await pilot.pause()
            if predicate():
                return
        assert predicate(), "the worker never finished"

    async def _open_editor(self, pilot, app, row=0):
        app._fill("USER")
        await pilot.pause()
        table = app.query_one("#slot-table")
        table.focus()
        if row:
            table.move_cursor(row=row)
        await pilot.pause()
        await pilot.press("e")
        await self._wait(pilot, lambda: isinstance(app.screen, EditorScreen))

    async def _name_and_store(self, pilot, app, name="Fresh Name"):
        await pilot.press("n")
        await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
        app.screen.query_one(Input).value = name
        await pilot.press("enter")
        await self._wait(pilot, lambda: isinstance(app.screen, EditorScreen))
        await pilot.press("a")
        await pilot.pause()
        assert app.screen.armed is True
        await pilot.press("w")
        await self._wait(pilot, lambda: len(app._undo_log) == 1)

    async def test_e_while_locked_refuses_and_sends_nothing(self):
        """The gate is asked before the read, so the unit sees no traffic."""
        reads = []

        class CountingDevice(DemoDevice):
            def read_program(self, number, *, timeout=None):
                reads.append(number)
                return super().read_program(number, timeout=timeout)

        app = NanosynedApp(CountingDevice(), catalog=cat.empty())
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("USER")
            await pilot.pause()
            app.query_one("#slot-table").focus()
            await pilot.press("e")
            for _ in range(8):
                await pilot.pause()
            assert not isinstance(app.screen, EditorScreen)
            assert reads == []
            assert app.device.program_writes == []
            assert "write gate" in str(app.query_one("#status").content)

    async def test_an_armed_edit_stores_once_and_reads_back(
        self, monkeypatch, tmp_path
    ):
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_program(0)
            await self._open_editor(pilot, app)
            await self._name_and_store(pilot, app)

            assert len(app.device.program_writes) == 1
            number, written = app.device.program_writes[0]
            assert number == 0
            assert rec.program_name(written).rstrip() == "Fresh Name"
            read_back = app.device.read_program(0)
            assert verify.mismatches(written, read_back) == []
            # Backed up, once, with what the slot held before the store.
            assert len(saved) == 1
            assert saved[0]["slot"] == "USER:000"
            assert saved[0]["kind"] == "program"
            assert saved[0]["blocks"]["program"] == original
            assert saved[0]["name"] == rec.program_name(original).rstrip()
            # Only an agreed read-back is undoable.
            assert len(app._undo_log) == 1

    async def test_user_127_is_refused_and_nothing_is_sent(self, monkeypatch, tmp_path):
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            app._fill("USER")
            await pilot.pause()
            table = app.query_one("#slot-table")
            table.focus()
            table.move_cursor(row=banks.SILENT_PROGRAM[1])
            await pilot.pause()
            await pilot.press("e")
            for _ in range(10):
                await pilot.pause()
            assert not isinstance(app.screen, EditorScreen)
            assert app.device.program_writes == []
            assert saved == []

    async def test_undo_re_sends_the_previous_record(self, monkeypatch, tmp_path):
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_program(0)
            await self._open_editor(pilot, app)
            await self._name_and_store(pilot, app)
            assert app.device.program_writes[0][1] != original

            await pilot.press("z")
            await self._wait(pilot, lambda: len(app.device.program_writes) == 2)
            for _ in range(10):
                await pilot.pause()
            assert app.device.program_writes[-1] == (0, original)
            assert app.device.read_program(0) == original

    async def test_store_is_never_one_keystroke(self, monkeypatch, tmp_path):
        """`w` without `a` sends nothing; typing disarms an armed screen."""
        saved = []
        self._backup_into(monkeypatch, tmp_path, saved)
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), allow_write=True)
        async with app.run_test() as pilot:
            await pilot.pause()
            original = app.device.read_program(0)
            await self._open_editor(pilot, app)

            # A name alone does not store: the fire key does nothing unarmed.
            await pilot.press("n")
            await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
            app.screen.query_one(Input).value = "Fresh Name"
            await pilot.press("enter")
            await self._wait(pilot, lambda: isinstance(app.screen, EditorScreen))
            await pilot.press("w")
            for _ in range(6):
                await pilot.pause()
            assert isinstance(app.screen, EditorScreen)
            assert app.device.program_writes == []

            # Arming, then typing, disarms -- so a second `w` still refuses.
            await pilot.press("a")
            await pilot.pause()
            assert app.screen.armed is True
            await pilot.press("n")
            await self._wait(pilot, lambda: isinstance(app.screen, PromptScreen))
            await pilot.press("escape")
            await self._wait(pilot, lambda: isinstance(app.screen, EditorScreen))
            assert app.screen.armed is False
            await pilot.press("w")
            for _ in range(6):
                await pilot.pause()
            assert isinstance(app.screen, EditorScreen)
            assert app.device.program_writes == []
            assert app.device.read_program(0) == original


class TestTheSubtitleShowsTheChannel:
    """The send channel is always in play and never asked about.

    ``[`` and ``]`` move it silently, and a Bank Select plus Program Change
    sent on the wrong channel is silent too, so it belongs somewhere always
    visible -- the header, which is the one line every sibling uses for it.
    """

    async def test_the_channel_is_in_the_subtitle(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "ch 1" in app.sub_title

    async def test_moving_the_channel_moves_the_subtitle(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("]")
            await pilot.pause()
            assert "ch 2" in app.sub_title
            await pilot.press("[")
            await pilot.pause()
            assert "ch 1" in app.sub_title

    async def test_the_subtitle_names_the_bank(self, app):
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "General MIDI" in app.sub_title
            app._fill("USER")
            await pilot.pause()
            assert "User" in app.sub_title
