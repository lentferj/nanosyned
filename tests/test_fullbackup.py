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

"""The full backup: one file holding every restorable setting."""

from __future__ import annotations

import dataclasses
import os

import pytest

from nano import dumps, fullbackup
from nano import messages as m
from nano import records as rec
from nanosyned.demo import DemoDevice


class CountingDevice:
    """A DemoDevice that remembers the reads it was asked for."""

    def __init__(self, device: DemoDevice) -> None:
        self._device = device
        self.reads: list[tuple[str, int | None]] = []

    def read_program(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("program", number))
        return self._device.read_program(number, timeout=timeout)

    def read_mix(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("mix", number))
        return self._device.read_mix(number, timeout=timeout)

    def read_effects(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("effects", number))
        return self._device.read_effects(number, timeout=timeout)

    def read_global(self, *, timeout: float | None = None) -> bytes:
        self.reads.append(("global", None))
        return self._device.read_global(timeout=timeout)


class SilentDevice:
    """A device that answers, then goes silent in the middle of a backup."""

    def __init__(self) -> None:
        self.reads: list[tuple[str, int | None]] = []

    def read_program(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("program", number))
        return bytes(rec.PROGRAM_BYTES)

    def read_mix(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("mix", number))
        if number == 3:
            raise m.ProtocolError("the unit went silent mid-backup")
        return bytes(rec.MIX_BYTES)

    def read_effects(self, number: int, *, timeout: float | None = None) -> bytes:
        self.reads.append(("effects", number))
        return bytes(rec.EFFECTS_BYTES)

    def read_global(self, *, timeout: float | None = None) -> bytes:
        self.reads.append(("global", None))
        return bytes(rec.GLOBAL_BYTES)


class TestSlots:
    def test_the_full_slot_list(self) -> None:
        entries = fullbackup.slots()

        assert len(entries) == fullbackup.TOTAL_RECORDS
        assert entries[0] == ("program", 0)
        assert entries[-1] == ("global", None)
        assert ("program", 126) in entries
        assert ("mix", 99) in entries
        assert ("program", 127) not in entries
        assert ("mix", 100) not in entries

    def test_the_order_is_programs_effects_mixes_global(self) -> None:
        entries = fullbackup.slots()

        kinds = [kind for kind, _number in entries]
        assert kinds == ["program"] * 127 + ["effects"] * 128 + ["mix"] * 100 + [
            "global"
        ]
        numbers = [number for _kind, number in entries if number is not None]
        assert numbers == [*range(127), *range(128), *range(100)]
        assert entries[-1] == ("global", None)


class TestReadAll:
    def test_a_full_backup_reads_every_destination_once(self) -> None:
        device = CountingDevice(DemoDevice())
        calls: list[tuple[str, int | None, str, int, int]] = []

        records = fullbackup.read_all(
            device,
            on_read=lambda kind, number, name, done, total: calls.append(
                (kind, number, name, done, total)
            ),
        )

        assert device.reads == [(kind, number) for kind, number in fullbackup.slots()]
        assert len(records) == fullbackup.TOTAL_RECORDS
        assert len(calls) == fullbackup.TOTAL_RECORDS
        assert [call[3] for call in calls] == list(
            range(1, fullbackup.TOTAL_RECORDS + 1)
        )
        assert all(call[4] == fullbackup.TOTAL_RECORDS for call in calls)
        assert [call[0] for call in calls] == [
            kind for kind, _number in fullbackup.slots()
        ]
        assert [call[1] for call in calls] == [
            number for _kind, number in fullbackup.slots()
        ]
        names = [call[2] for call in calls]
        assert all(isinstance(name, str) for name in names)
        assert names[-1] == ""  # the global record has no name of its own


class TestBackupCancelled:
    def test_a_cancel_before_a_read_raises_and_reads_nothing(self) -> None:
        device = CountingDevice(DemoDevice())

        with pytest.raises(fullbackup.BackupCancelled):
            fullbackup.read_all(device, cancelled=lambda: True)

        assert device.reads == []

    def test_a_cancel_after_a_read_raises_and_stops(self) -> None:
        device = CountingDevice(DemoDevice())
        state = {"stop": False}

        def cancelled() -> bool:
            return state["stop"]

        def on_read(
            kind: str, number: int | None, name: str, done: int, total: int
        ) -> None:
            state["stop"] = True

        with pytest.raises(fullbackup.BackupCancelled):
            fullbackup.read_all(device, on_read=on_read, cancelled=cancelled)

        assert device.reads == [("program", 0)]


class TestReadFailure:
    def test_a_read_failure_propagates_and_writes_nothing(self, tmp_path) -> None:
        device = SilentDevice()
        path = str(tmp_path / "full.syx")

        with pytest.raises(m.ProtocolError, match="the unit went silent"):
            fullbackup.backup_device(device, path)

        assert not os.path.exists(path)
        assert not (tmp_path / "full.syx.tmp").exists()


class TestBackupDeviceCancellation:
    def test_a_cancelled_backup_leaves_no_file_behind(self, tmp_path) -> None:
        device = CountingDevice(DemoDevice())
        state = {"stop": False}

        def cancelled() -> bool:
            return state["stop"]

        def on_read(
            kind: str, number: int | None, name: str, done: int, total: int
        ) -> None:
            state["stop"] = True

        path = str(tmp_path / "full.syx")

        with pytest.raises(fullbackup.BackupCancelled):
            fullbackup.backup_device(device, path, on_read=on_read, cancelled=cancelled)

        assert not os.path.exists(path)
        assert not (tmp_path / "full.syx.tmp").exists()


class TestWriteSyx:
    def test_refuses_an_existing_path(self, tmp_path) -> None:
        path = str(tmp_path / "full.syx")
        with open(path, "wb") as handle:
            handle.write(b"junk")

        with pytest.raises(FileExistsError):
            fullbackup.write_syx(path, fullbackup.read_all(DemoDevice()))

        with open(path, "rb") as handle:
            assert handle.read() == b"junk"
        assert not (tmp_path / "full.syx.tmp").exists()


class TestBackupDevice:
    def test_a_full_backup_writes_one_parseable_file(self, tmp_path) -> None:
        device = DemoDevice()
        path = str(tmp_path / "full.syx")

        result = fullbackup.backup_device(device, path)

        library = dumps.read_syx_file(path)
        assert set(library.programs) == set(range(127))
        assert set(library.effects) == set(range(128))
        assert set(library.mixes) == set(range(100))
        assert library.globals_ is not None
        assert 127 not in library.programs
        assert result.path == path
        assert result.byte_count > 0
        assert result.count == fullbackup.TOTAL_RECORDS
        assert result.programs == 127
        assert result.effects == 128
        assert result.mixes == 100
        assert result.globals_ == 1

    def test_the_result_is_frozen(self) -> None:
        result = fullbackup.BackupResult(
            path="a.syx", byte_count=10, programs=1, effects=0, mixes=0, globals_=0
        )

        assert result.count == 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.path = "b.syx"  # type: ignore[misc]


class TestDemoBackup:
    def test_the_demo_backup_is_seventy_nine_thousand_seventy_one_bytes(
        self, tmp_path
    ) -> None:
        path = str(tmp_path / "full.syx")

        result = fullbackup.backup_device(DemoDevice(), path)

        assert result.byte_count == 79071
        assert os.path.getsize(path) == 79071
        assert result.count == fullbackup.TOTAL_RECORDS
        assert result.programs == 127
        assert result.effects == 128
        assert result.mixes == 100
        assert result.globals_ == 1


def _program(number: int, name: str, fill: int) -> tuple[str, int, bytes]:
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name, m.NAME_BIT_OFFSET)
    record[-1] = fill
    return ("program", number, bytes(record))


def _effects(number: int, fill: int) -> tuple[str, int, bytes]:
    return ("effects", number, bytes([fill]) * rec.EFFECTS_BYTES)


def _mix(number: int, fill: int) -> tuple[str, int, bytes]:
    record = bytearray(rec.MIX_BYTES)
    m.encode_name(record, f"Set {number:03d}", rec.MIX_NAME_BIT_OFFSET)
    return ("mix", number, bytes(record))


def _global(fill: int) -> tuple[str, int | None, bytes]:
    return ("global", None, bytes([fill]) * rec.GLOBAL_BYTES)


class TestWriteSyxRoundTrip:
    def test_arbitrary_records_round_trip(self, tmp_path) -> None:
        path = str(tmp_path / "one.syx")
        records = (
            _program(2, "Round Two", 0x40),
            _program(7, "Round Seven", 0x41),
            _effects(3, 0x42),
            _mix(4, 0x43),
            _global(0x44),
        )

        byte_count = fullbackup.write_syx(path, records)

        assert byte_count == os.path.getsize(path) > 0
        library = dumps.read_syx_file(path)
        assert set(library.programs) == {2, 7}
        assert library.programs[2] == records[0][2]
        assert library.programs[7] == records[1][2]
        assert set(library.effects) == {3}
        assert library.effects[3] == records[2][2]
        assert set(library.mixes) == {4}
        assert library.mixes[4] == records[3][2]
        assert library.globals_ is not None
        assert library.globals_ == records[4][2]
