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

"""Existing slot favourites are adopted the first time their bytes are seen."""

from __future__ import annotations

import time

from nano import catalog as cat
from nano import favorites as fav
from nano import identity, writing
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


def _result(number: int, record: bytes) -> writing.Result:
    return writing.Result(
        kind="program",
        number=number,
        record=record,
        previous=_record("Old", 1),
        read_back=record,
        stage="verified",
    )


class TestAdoption:
    async def test_an_active_slot_favourite_is_adopted(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 5, name="Old", rating=3, tags="pad", note="keep")
        app = _app(tmp_path, store)
        record = _record("Recall", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, record)], None)
                await pilot.pause()
                entry = app.memory.get(identity.digest(record))
                assert entry is not None
                assert entry.favourite is True
                assert entry.rating == 3
                assert entry.tags == "pad"
                assert entry.note == "keep"
        finally:
            app.memory.close()
            store.close()

    async def test_existing_memory_annotations_win(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 5, name="Old", rating=2, tags="slot", note="slot")
        app = _app(tmp_path, store)
        record = _record("Recall", 3)
        memory = app.memory
        assert memory is not None
        entry = memory.remember(record)
        memory.set_favourite(entry.digest, True, rating=5, tags="memory", note="memory")
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, record)], None)
                await pilot.pause()
                entry = memory.get(identity.digest(record))
                assert entry is not None
                assert entry.rating == 5
                assert entry.tags == "memory"
                assert entry.note == "memory"
                marked = store.get("USER", 5)
                assert marked is not None
                assert marked.rating == 5
                assert marked.tags == "memory"
        finally:
            memory.close()
            store.close()

    async def test_two_old_rows_choose_the_earliest_added(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 5, name="First", rating=1, tags="first", note="first")
        time.sleep(0.01)
        store.add("USER", 6, name="Second", rating=4, tags="second", note="second")
        app = _app(tmp_path, store)
        record = _record("Recall", 4)
        memory = app.memory
        assert memory is not None
        entry = memory.remember(record)
        memory.bind_slot("USER", 5, entry.digest)
        memory.bind_slot("USER", 6, entry.digest)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(6, record)], None)
                await pilot.pause()
                entry = memory.get(identity.digest(record))
                assert entry is not None
                assert entry.rating == 1
                assert entry.tags == "first"
                assert entry.note == "first"
        finally:
            memory.close()
            store.close()

    async def test_a_dormant_row_does_not_make_content_favourite(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 5, name="Old", rating=3, tags="pad", note="keep")
        store.remove("USER", 5)
        app = _app(tmp_path, store)
        record = _record("Recall", 5)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, record)], None)
                await pilot.pause()
                entry = app.memory.get(identity.digest(record))
                assert entry is not None
                assert entry.favourite is False
                assert store.get("USER", 5) is None
        finally:
            app.memory.close()
            store.close()
