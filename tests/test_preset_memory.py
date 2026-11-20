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

"""The sidecar content-addressed preset memory."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from nano import identity, preset_memory
from nano import messages as m
from nano import records as rec
from nano.preset_memory import PresetMemory


def _record(name: str = "Init", seed: int = 0) -> bytes:
    """One synthetic 350-byte program with a real encoded name."""
    record = bytearray(
        (index * 7 + 3 + seed) & 0x7F for index in range(rec.PROGRAM_BYTES)
    )
    m.encode_name(record, name, m.NAME_BIT_OFFSET)
    return bytes(record)


class TestTheStore:
    def test_the_default_path_is_beside_the_favourites_database(self):
        path = preset_memory.default_path()

        assert path.endswith("preset-memory.db")
        assert path != "preset-memory.db"

    def test_rows_persist_across_close_and_reopen(self, tmp_path):
        path = str(tmp_path / "memory.db")
        record = _record()
        with PresetMemory(path) as store:
            store.remember(record, name="Init")

        with PresetMemory(path) as store:
            entry = store.get(identity.digest(record))

        assert entry is not None
        assert entry.name == "Init"
        assert entry.seen_count == 1

    def test_a_newer_schema_is_refused(self, tmp_path):
        path = str(tmp_path / "memory.db")
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
        connection.close()

        with pytest.raises(RuntimeError, match="newer preset memory"):
            PresetMemory(path)

    def test_two_threads_can_remember_and_bind(self, tmp_path):
        path = str(tmp_path / "memory.db")
        store = PresetMemory(path)
        records = [_record("One", 1), _record("Two", 2)]
        threads: list[threading.Thread] = []

        def work(index: int) -> None:
            record = records[index]
            number = index + 1
            entry = store.remember(record)
            store.bind_slot("USER", number, entry.digest)

        for index in range(2):
            thread = threading.Thread(target=work, args=(index,))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        try:
            assert len(store.seen()) == 2
            assert store.slot_digest("USER", 1) == identity.digest(records[0])
            assert store.slot_digest("USER", 2) == identity.digest(records[1])
        finally:
            store.close()


class TestRemember:
    def test_a_new_record_is_seen_but_not_favourite(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            assert entry.favourite is False
            assert entry.rating == 0
            assert entry.tags == ""
            assert entry.note == ""
            assert entry.first_seen > 0
            assert entry.last_seen >= entry.first_seen
            assert entry.seen_count == 1
        finally:
            store.close()

    def test_a_second_remember_advances_count_and_name(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            first = store.remember(_record("Init"))
            second = store.remember(_record("Init"), name="Renamed")
            assert second.seen_count == 2
            assert second.first_seen == first.first_seen
            assert second.last_seen >= first.last_seen
            assert second.name == "Renamed"
        finally:
            store.close()

    def test_remember_preserves_annotations_and_favourite(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            store.set_favourite(
                entry.digest, True, rating=4, tags="pad, warm", note="keep me"
            )
            again = store.remember(_record())
            assert again.favourite is True
            assert again.rating == 4
            assert again.tags == "pad, warm"
            assert again.note == "keep me"
        finally:
            store.close()

    def test_an_empty_name_does_not_erase_the_label(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            store.remember(_record("Init"))
            entry = store.remember(_record("Init"), name="")
            assert entry.name == "Init"
        finally:
            store.close()


class TestFavourite:
    def test_toggle_keeps_the_annotations(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            marked = store.set_favourite(
                entry.digest, True, rating=3, tags="lead", note="n"
            )
            assert marked.favourite is True
            clear = store.set_favourite(entry.digest, False)
            assert clear.favourite is False
            assert clear.rating == 3
            assert clear.tags == "lead"
            assert clear.note == "n"
        finally:
            store.close()

    def test_rating_out_of_range_is_refused(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            with pytest.raises(ValueError, match="outside 0-5"):
                store.set_favourite(entry.digest, True, rating=6)
        finally:
            store.close()

    def test_a_missing_digest_is_refused(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            with pytest.raises(KeyError):
                store.set_favourite("0" * 64, True)
        finally:
            store.close()

    def test_favourites_and_seen_are_deterministic(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            one = store.remember(_record("One", 1))
            two = store.remember(_record("Two", 2))
            store.set_favourite(two.digest, True)
            assert [entry.digest for entry in store.favourites()] == [two.digest]
            assert len(store.seen()) == 2
            assert {entry.digest for entry in store.seen()} == {
                one.digest,
                two.digest,
            }
        finally:
            store.close()


class TestSlots:
    def test_bind_and_forget_a_slot(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            store.bind_slot("USER", 5, entry.digest)
            assert store.slot_digest("USER", 5) == entry.digest
            assert store.slots_for(entry.digest) == [("USER", 5)]
            store.forget_slot("USER", 5)
            assert store.slot_digest("USER", 5) is None
        finally:
            store.close()

    @pytest.mark.parametrize(
        ("bank_id", "number"),
        [("USER", 127), ("P1", 0), ("USER", -1), ("USER", 128)],
    )
    def test_an_unwritable_slot_is_refused(self, tmp_path, bank_id, number):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            entry = store.remember(_record())
            with pytest.raises(ValueError):
                store.bind_slot(bank_id, number, entry.digest)
        finally:
            store.close()

    def test_binding_unknown_content_is_refused(self, tmp_path):
        store = PresetMemory(str(tmp_path / "memory.db"))
        try:
            with pytest.raises(KeyError):
                store.bind_slot("USER", 0, "0" * 64)
        finally:
            store.close()
