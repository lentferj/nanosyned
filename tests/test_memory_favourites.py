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

"""`f` follows the content identity when the slot digest is known."""

from __future__ import annotations

from nano import catalog as cat
from nano import favorites as fav
from nano import messages as m
from nano import records as rec
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice


def _record(name: str, seed: int = 0) -> bytes:
    record = bytearray(
        (index * 7 + 3 + seed) & 0x7F for index in range(rec.PROGRAM_BYTES)
    )
    m.encode_name(record, name, m.NAME_BIT_OFFSET)
    return bytes(record)


def _app(tmp_path, store):
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.empty(),
        favorites=store,
        memory_path=str(tmp_path / "memory.db"),
    )


def _bind(app, number: int, record: bytes) -> str:
    memory = app.memory
    assert memory is not None
    entry = memory.remember(record)
    memory.bind_slot("USER", number, entry.digest)
    return entry.digest


async def _cursor(app, pilot, number: int) -> None:
    app._fill("USER")
    await pilot.pause()
    table = app.query_one("#slot-table")
    table.move_cursor(row=number)
    for _ in range(200):
        await pilot.pause(0.01)
        if table.cursor_row == number:
            break


class TestKnownDigest:
    async def test_one_slot_toggles_content_and_occurrence(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        digest = _bind(app, 5, _record("Recall", 1))
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                entry = app.memory.get(digest)
                assert entry is not None and entry.favourite is True
                assert store.get("USER", 5) is not None

                app.action_toggle_favorite()
                await pilot.pause()
                entry = app.memory.get(digest)
                assert entry is not None and entry.favourite is False
                assert store.get("USER", 5) is None
        finally:
            app.memory.close()
            store.close()

    async def test_dormant_annotations_move_into_the_memory(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 5, name="Old", rating=3, tags="pad", note="keep")
        store.remove("USER", 5)
        app = _app(tmp_path, store)
        digest = _bind(app, 5, _record("Recall", 2))
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                entry = app.memory.get(digest)
                assert entry is not None
                assert entry.favourite is True
                assert entry.rating == 3
                assert entry.tags == "pad"
                assert entry.note == "keep"
                assert store.get("USER", 5) is not None
        finally:
            app.memory.close()
            store.close()

    async def test_memory_annotations_fill_a_blank_slot(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        digest = _bind(app, 5, _record("Recall", 3))
        app.memory.set_favourite(digest, True, rating=5, tags="lead", note="remembered")
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                marked = store.get("USER", 5)
                assert marked is not None
                assert marked.rating == 5
                assert marked.tags == "lead"
                assert marked.note == "remembered"
        finally:
            app.memory.close()
            store.close()

    async def test_turning_off_clears_every_bound_occurrence(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        digest = _bind(app, 5, _record("Recall", 4))
        _bind(app, 6, _record("Recall", 4))
        app.memory.set_favourite(digest, True)
        store.add("USER", 5, name="Recall")
        store.add("USER", 6, name="Recall")
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                assert app.memory.get(digest).favourite is False
                assert store.get("USER", 5) is None
                assert store.get("USER", 6) is None
        finally:
            app.memory.close()
            store.close()


class TestUnknownDigest:
    async def test_an_unbound_slot_keeps_the_slot_only_behaviour(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                assert store.get("USER", 5) is not None
                assert app.memory.seen() == []
        finally:
            app.memory.close()
            store.close()
