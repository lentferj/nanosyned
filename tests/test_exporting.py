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

"""Export: the selection, the reads, the file. Names here are invented."""

from __future__ import annotations

import dataclasses
import os

import pytest

from nano import dumps, messages
from nano import records as rec
from nano.exporting import (
    USER_BANK,
    ExportCancelled,
    ExportResult,
    export_favourites,
    favourite_numbers,
    read_programs,
    write_syx,
)
from nano.favorites import Favorites

#: The refusal ``favourite_numbers`` makes when nothing is favourited.
_NO_FAVOURITES = "no favourited User programs to export; nothing written"


def _record(name: str) -> bytes:
    """A real 350-byte program record, named, the way the unit keeps them."""
    record = bytearray(rec.PROGRAM_BYTES)
    messages.encode_name(record, name)
    return bytes(record)


class FakeDevice:
    """A dict of User records, standing in for the bridge.

    ``nano.writing.read_record`` asks exactly one method for a program --
    ``read_program`` -- so a dict of records is the whole fake: no port,
    no GUI, no store. A number with no record raises, the way a slot the
    unit cannot answer does.
    """

    def __init__(self, programs: dict[int, bytes]) -> None:
        self.programs = programs
        self.reads: list[int] = []

    def read_program(self, number: int) -> bytes:
        self.reads.append(number)
        if number not in self.programs:
            raise LookupError(f"user program {number:03d} did not answer")
        return self.programs[number]


class TestFavouriteNumbers:
    def test_active_user_favourites_come_back_sorted(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 5, name="Five")
            store.add(USER_BANK, 1, name="One")
            store.add(USER_BANK, 9, name="Nine")
            assert favourite_numbers(store) == (1, 5, 9)

    def test_slot_127_is_excluded(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 3, name="Three")
            store.add(USER_BANK, 127, name="Off")
            assert favourite_numbers(store) == (3,)

    def test_non_user_favourites_are_ignored(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add("GM", 1, name="Gm")
            store.add("P1", 2, name="Preset")
            with pytest.raises(ValueError, match=_NO_FAVOURITES):
                favourite_numbers(store)

    def test_a_dropped_favourite_is_not_one(self, tmp_path):
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 4, name="Four")
            store.remove(USER_BANK, 4)
            with pytest.raises(ValueError, match=_NO_FAVOURITES):
                favourite_numbers(store)

    def test_empty_refuses(self, tmp_path):
        with (
            Favorites(str(tmp_path / "f.db")) as store,
            pytest.raises(ValueError, match=_NO_FAVOURITES),
        ):
            favourite_numbers(store)


class TestReadPrograms:
    def test_reads_in_the_given_order_and_reports_progress(self):
        records = {
            3: _record("Prog 3"),
            1: _record("Prog 1"),
            2: _record("Prog 2"),
        }
        device = FakeDevice(records)
        calls: list[tuple[int, str, int, int]] = []
        programs = read_programs(
            device,
            [3, 1, 2],
            on_read=lambda number, name, done, total: calls.append(
                (number, name, done, total)
            ),
        )
        assert device.reads == [3, 1, 2]
        assert programs == [(3, records[3]), (1, records[1]), (2, records[2])]
        assert calls == [
            (3, "Prog 3", 1, 3),
            (1, "Prog 1", 2, 3),
            (2, "Prog 2", 3, 3),
        ]

    def test_a_read_failure_propagates(self):
        device = FakeDevice({1: _record("Prog 1")})  # 2 is missing
        with pytest.raises(LookupError):
            read_programs(device, [1, 2])
        assert device.reads == [1, 2]

    def test_a_short_read_aborts(self):
        device = FakeDevice({1: b"short"})
        with pytest.raises(messages.ProtocolError):
            read_programs(device, [1])

    def test_a_long_record_is_truncated(self):
        record = bytearray(rec.PROGRAM_BYTES + 50)
        messages.encode_name(record, "Long")
        device = FakeDevice({1: bytes(record)})
        programs = read_programs(device, [1])
        assert len(programs[0][1]) == rec.PROGRAM_BYTES

    def test_cancel_before_a_read_raises(self):
        device = FakeDevice({1: _record("Prog 1")})
        with pytest.raises(ExportCancelled):
            read_programs(device, [1], cancelled=lambda: True)
        assert device.reads == []


class TestWriteSyx:
    def test_round_trips_through_read_syx_file(self, tmp_path):
        path = str(tmp_path / "favourites.syx")
        programs = [(2, _record("Prog 2")), (7, _record("Prog 7"))]
        byte_count = write_syx(path, programs)
        library = dumps.read_syx_file(path)
        assert library.programs == {2: programs[0][1], 7: programs[1][1]}
        assert all(
            len(record) == rec.PROGRAM_BYTES for record in library.programs.values()
        )
        assert byte_count == os.path.getsize(path)
        assert byte_count > 0

    def test_existing_path_refused_without_overwrite(self, tmp_path):
        path = tmp_path / "favourites.syx"
        path.write_bytes(b"junk")
        with pytest.raises(FileExistsError):
            write_syx(str(path), [(1, _record("Prog 1"))])
        assert path.read_bytes() == b"junk"
        assert not (tmp_path / "favourites.syx.tmp").exists()

    def test_overwrite_replaces_and_leaves_no_temp(self, tmp_path):
        path = tmp_path / "favourites.syx"
        path.write_bytes(b"junk")
        write_syx(str(path), [(1, _record("Prog 1"))], overwrite=True)
        assert dumps.read_syx_file(str(path)).programs == {1: _record("Prog 1")}
        assert not (tmp_path / "favourites.syx.tmp").exists()

    def test_a_write_error_removes_the_temp(self, tmp_path, monkeypatch):
        path = tmp_path / "favourites.syx"

        def broken_replace(source: str, destination: str) -> None:
            raise OSError("the disk went away")

        monkeypatch.setattr(os, "replace", broken_replace)
        with pytest.raises(OSError, match="the disk went away"):
            write_syx(str(path), [(1, _record("Prog 1"))])
        assert not (tmp_path / "favourites.syx.tmp").exists()
        assert not path.exists()


class TestExportFavourites:
    def test_writes_only_the_selected_programs(self, tmp_path):
        records = {
            1: _record("Prog 1"),
            2: _record("Prog 2"),
            3: _record("Prog 3"),
        }
        device = FakeDevice(records)
        path = str(tmp_path / "favourites.syx")
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 1, name="Prog 1")
            store.add(USER_BANK, 3, name="Prog 3")
            result = export_favourites(device, store, path)
        assert isinstance(result, ExportResult)
        assert result.path == path
        assert result.count == 2
        assert result.byte_count == os.path.getsize(path)
        assert device.reads == [1, 3]  # the un-favourited slot is not read
        library = dumps.read_syx_file(path)
        assert library.programs == {1: records[1], 3: records[3]}
        assert all(
            len(record) == rec.PROGRAM_BYTES for record in library.programs.values()
        )

    def test_the_result_is_frozen(self):
        result = ExportResult(path="a.syx", count=3, byte_count=30)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.count = 0

    def test_a_failed_read_leaves_no_file(self, tmp_path):
        device = FakeDevice({1: _record("Prog 1")})  # 2 is missing
        path = str(tmp_path / "favourites.syx")
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 1, name="Prog 1")
            store.add(USER_BANK, 2, name="Prog 2")
            with pytest.raises(LookupError):
                export_favourites(device, store, path)
        assert not os.path.exists(path)
        assert not (tmp_path / "favourites.syx.tmp").exists()

    def test_cancel_leaves_no_file(self, tmp_path):
        device = FakeDevice({1: _record("Prog 1"), 2: _record("Prog 2")})
        path = str(tmp_path / "favourites.syx")
        with Favorites(str(tmp_path / "f.db")) as store:
            store.add(USER_BANK, 1, name="Prog 1")
            store.add(USER_BANK, 2, name="Prog 2")
            with pytest.raises(ExportCancelled):
                export_favourites(
                    device, store, path, cancelled=lambda: len(device.reads) > 0
                )
        assert device.reads == [1]
        assert not os.path.exists(path)
