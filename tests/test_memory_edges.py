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

"""Failure modes the happy-path memory tests can hide."""

from __future__ import annotations

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


def _app(tmp_path, store, *, catalog_path=None):
    return NanosynedApp(
        DemoDevice(),
        catalog=cat.empty(),
        favorites=store,
        memory_path=str(tmp_path / "memory.db"),
        catalog_path=catalog_path,
    )


def _result(number: int, record: bytes) -> writing.Result:
    return writing.Result(
        kind="program",
        number=number,
        record=record,
        previous=_record("Old", 9),
        read_back=record,
        stage="verified",
    )


async def _cursor(app, pilot, number: int) -> None:
    app._fill("USER")
    await pilot.pause()
    app.query_one("#slot-table").move_cursor(row=number)
    await pilot.pause()


class TestNoFalseMatch:
    async def test_a_changed_name_is_a_different_content_identity(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        first = memory.remember(_record("First", 1))
        memory.set_favourite(first.digest, True)
        second_record = _record("Second", 1)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, second_record)], None)
                await pilot.pause()
                assert memory.get(first.digest).favourite is True
                second = memory.get(identity.digest(second_record))
                assert second is not None and second.favourite is False
                assert store.get("USER", 5) is None
        finally:
            memory.close()
            store.close()

    async def test_changed_bytes_with_the_same_name_do_not_match(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        first = memory.remember(_record("Same", 1))
        memory.set_favourite(first.digest, True)
        second_record = _record("Same", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, second_record)], None)
                await pilot.pause()
                assert memory.get(first.digest).favourite is True
                second = memory.get(identity.digest(second_record))
                assert second is not None and second.favourite is False
                assert store.get("USER", 5) is None
        finally:
            memory.close()
            store.close()


class TestDuplicates:
    async def test_turning_on_marks_the_current_occurrence(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        entry = memory.remember(_record("Twin", 3))
        memory.bind_slot("USER", 5, entry.digest)
        memory.bind_slot("USER", 6, entry.digest)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                await _cursor(app, pilot, 5)
                app.action_toggle_favorite()
                await pilot.pause()
                assert memory.get(entry.digest).favourite is True
                assert store.get("USER", 5) is not None
                # The contract marks the current occurrence; the other bound
                # slot is left for the next explicit action or import.
                assert store.get("USER", 6) is None
        finally:
            memory.close()
            store.close()


class TestIsolation:
    async def test_an_import_does_not_write_the_catalog_file(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        catalog_path = str(tmp_path / "catalog.json")
        app = _app(tmp_path, store, catalog_path=catalog_path)
        memory = app.memory
        assert memory is not None
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(None, [_result(5, _record("New", 7))], None)
                await pilot.pause()
                assert not (tmp_path / "catalog.json").exists()
        finally:
            memory.close()
            store.close()

    def test_the_memory_survives_an_app_restart(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        first = _app(tmp_path, store)
        record = _record("Remembered", 8)
        try:
            entry = first.memory.remember(record)
            first.memory.close()
        finally:
            store.close()

        second_store = fav.Favorites(str(tmp_path / "favorites.db"))
        second = _app(tmp_path, second_store)
        try:
            recovered = second.memory.get(entry.digest)
            assert recovered is not None
            assert recovered.name == "Remembered"
        finally:
            second.memory.close()
            second_store.close()
