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

"""The browser remembers verified imports and manual stores."""

from __future__ import annotations

from nano import banks, identity, writing
from nano import catalog as cat
from nano import favorites as fav
from nano import livenames as ln
from nano import messages as m
from nano import records as rec
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice
from nanosyned.editor import EditRecord, ImportRecord
from vinsynlib.undo import Record


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


def _result(number: int, record: bytes, previous: bytes, **changes) -> writing.Result:
    values = {
        "kind": "program",
        "number": number,
        "record": record,
        "previous": previous,
        "read_back": record,
        "stage": "verified",
    }
    values.update(changes)
    return writing.Result(**values)


class TestImport:
    async def test_a_remembered_favourite_is_re_marked_with_its_annotations(
        self, tmp_path
    ):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        record = _record("Recall", 5)
        memory = app.memory
        assert memory is not None
        entry = memory.remember(record)
        memory.set_favourite(
            entry.digest, True, rating=4, tags="pad, warm", note="remembered"
        )
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(
                    None,
                    [_result(3, record, _record("Old", 6))],
                    None,
                )
                await pilot.pause()
                marked = store.get("USER", 3)
                assert marked is not None
                assert marked.rating == 4
                assert marked.tags == "pad, warm"
                assert marked.note == "remembered"
                assert memory.slot_digest("USER", 3) == entry.digest
        finally:
            memory.close()
            store.close()

    async def test_a_non_favourite_import_clears_the_old_mark(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 3, name="Old", rating=5, tags="lead", note="old")
        app = _app(tmp_path, store)
        record = _record("New", 7)
        old = _record("Old", 6)
        memory = app.memory
        assert memory is not None
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(
                    None,
                    [_result(3, record, old)],
                    None,
                )
                await pilot.pause()
                assert store.get("USER", 3) is None
                entry = memory.get(identity.digest(record))
                assert entry is not None
                assert entry.favourite is False
                assert memory.slot_digest("USER", 3) == entry.digest
                old_entry = memory.get(identity.digest(old))
                assert old_entry is not None
                assert old_entry.favourite is True
                assert old_entry.rating == 5
                assert old_entry.tags == "lead"
                assert old_entry.note == "old"
        finally:
            memory.close()
            store.close()

    async def test_reimporting_the_old_file_brings_the_mark_back(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        old_digest = identity.digest(old)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                # The old content is imported, then marked the way a
                # pre-memory favourite was marked: a slot row only.
                app._import_done(None, [_result(5, old, _record("Before", 9))], None)
                store.add("USER", 5, name="Old", rating=3, tags="pad", note="keep")
                await pilot.pause()

                # A whole-bank overwrite clears the slot mark but must keep
                # the old content as a favourite identity.
                app._import_done(None, [_result(5, new, old)], None)
                await pilot.pause()
                assert store.get("USER", 5) is None
                preserved = memory.get(old_digest)
                assert preserved is not None and preserved.favourite is True

                # Loading the old file again restores the heart.
                app._import_done(None, [_result(5, old, new)], None)
                await pilot.pause()
                restored = store.get("USER", 5)
                assert restored is not None
                assert restored.rating == 3
                assert restored.tags == "pad"
                assert restored.note == "keep"
        finally:
            memory.close()
            store.close()

    async def test_only_verified_results_are_remembered(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        record = _record("Good", 8)
        memory = app.memory
        assert memory is not None
        failed_record = _record("Bad", 9)
        failed = _result(
            4,
            failed_record,
            _record("Old", 10),
            read_back=None,
            failure="no reply",
            stage="read",
        )
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(
                    None,
                    [_result(3, record, _record("Old", 6)), failed],
                    None,
                )
                await pilot.pause()
                assert memory.get(identity.digest(record)) is not None
                assert memory.get(identity.digest(failed_record)) is None
        finally:
            memory.close()
            store.close()

    async def test_no_memory_keeps_the_existing_behaviour(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = NanosynedApp(DemoDevice(), catalog=cat.empty(), favorites=store)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_done(
                    None,
                    [_result(3, _record("New", 7), _record("Old", 6))],
                    None,
                )
                await pilot.pause()
                assert store.get("USER", 3) is None
        finally:
            store.close()


class TestUndo:
    async def test_undo_rebinds_the_restored_content(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        entry = memory.remember(new)
        memory.bind_slot("USER", 5, entry.digest)
        payload = ImportRecord(edits=(EditRecord(number=5, previous=old, name="Old"),))
        record = Record("import", payload)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._undo_done([record], [True], [""])
                await pilot.pause()
                assert memory.slot_digest("USER", 5) == identity.digest(old)
        finally:
            memory.close()
            store.close()

    async def test_a_store_and_its_undo_persist_the_live_name(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        catalog_path = str(tmp_path / "catalog.json")
        app = NanosynedApp(
            DemoDevice(),
            catalog=cat.empty(),
            favorites=store,
            memory_path=str(tmp_path / "memory.db"),
            catalog_path=catalog_path,
        )
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._store_done(
                    banks.slot("USER", 4),
                    new,
                    old,
                    None,
                    new,
                    None,
                    "verified",
                )
                names = ln.load(ln.path_for(catalog_path))
                assert names[ln.key("USER", 4)] == "New"

                records = app._undo_log.plan(1)
                app._undo_done(records, [True], [""])
                await pilot.pause()
                names = ln.load(ln.path_for(catalog_path))
                assert names[ln.key("USER", 4)] == "Old"
        finally:
            if app.memory is not None:
                app.memory.close()
            store.close()

    async def test_undo_restores_the_slot_favourite_snapshot(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 4, name="Old", rating=3, tags="bass", note="keep")
        app = _app(tmp_path, store)
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._store_done(
                    banks.slot("USER", 4),
                    new,
                    old,
                    None,
                    new,
                    None,
                    "verified",
                )
                # A later metadata edit must not survive the undo of the
                # program store: the snapshot is what the slot held first.
                store.set_rating("USER", 4, 1)
                store.set_tags("USER", 4, "changed")
                records = app._undo_log.plan(1)
                app._undo_done(records, [True], [""])
                await pilot.pause()
                marked = store.get("USER", 4)
                assert marked is not None
                assert marked.rating == 3
                assert marked.tags == "bass"
                assert marked.note == "keep"
        finally:
            if app.memory is not None:
                app.memory.close()
            store.close()

    async def test_undo_restores_the_favourite_snapshot_from_an_import(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 3, name="Old", rating=5, tags="lead", note="keep")
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._import_favourites = {("program", 3): (True, store.get("USER", 3))}
                app._import_done(
                    None,
                    [_result(3, new, old)],
                    None,
                )
                await pilot.pause()
                store.remove("USER", 3)
                records = app._undo_log.plan(1)
                app._undo_done(records, [True], [""])
                await pilot.pause()
                marked = store.get("USER", 3)
                assert marked is not None
                assert marked.rating == 5
                assert marked.tags == "lead"
                assert marked.note == "keep"
        finally:
            memory.close()
            store.close()


class TestManualStore:
    async def test_editing_a_favourite_carries_the_annotations(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        store.add("USER", 4, name="Old", rating=3, tags="bass", note="keep")
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._store_done(
                    banks.slot("USER", 4),
                    new,
                    old,
                    None,
                    new,
                    None,
                    "verified",
                )
                await pilot.pause()
                marked = store.get("USER", 4)
                assert marked is not None
                assert marked.rating == 3
                assert marked.tags == "bass"
                assert marked.note == "keep"
                new_entry = memory.get(identity.digest(new))
                old_entry = memory.get(identity.digest(old))
                assert new_entry is not None and new_entry.favourite is True
                assert old_entry is not None and old_entry.favourite is True
        finally:
            memory.close()
            store.close()

    async def test_editing_a_non_favourite_only_remembers_the_new_bytes(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._store_done(
                    banks.slot("USER", 4),
                    new,
                    old,
                    None,
                    new,
                    None,
                    "verified",
                )
                await pilot.pause()
                assert store.get("USER", 4) is None
                entry = memory.get(identity.digest(new))
                assert entry is not None
                assert entry.favourite is False
        finally:
            memory.close()
            store.close()

    async def test_an_unverified_store_does_not_touch_memory(self, tmp_path):
        store = fav.Favorites(str(tmp_path / "favorites.db"))
        app = _app(tmp_path, store)
        memory = app.memory
        assert memory is not None
        old = _record("Old", 1)
        new = _record("New", 2)
        try:
            async with app.run_test(size=(160, 50)) as pilot:
                await pilot.pause()
                app._store_done(
                    banks.slot("USER", 4),
                    new,
                    old,
                    None,
                    _record("Different", 3),
                    "mismatch",
                    "verify",
                )
                await pilot.pause()
                assert memory.get(identity.digest(new)) is None
        finally:
            memory.close()
            store.close()
