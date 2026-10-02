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

import pytest

from nano import banks
from nano import catalog as cat
from nano import favorites as fav
from nanosyned.app import VIEW_ALL_FAVOURITES, NanosynedApp
from nanosyned.demo import DemoDevice


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
                await pilot.press("F")
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
    """The search callback takes the four-tuples Catalog.search returns.

    It used to unpack three, so any search that found a match raised
    ValueError instead of showing the match -- the bug was invisible
    because nothing exercised the callback.
    """

    async def test_a_match_is_shown(self):
        catalog = cat.Catalog([cat.Entry("GM", 0, "Invented Name")])
        app = NanosynedApp(DemoDevice(), catalog=catalog)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.action_search()
            await pilot.pause()
            app.screen.dismiss("Invented")
            await pilot.pause()
            assert "Invented Name" in app.screen._body
