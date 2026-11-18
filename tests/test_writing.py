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

"""The write loop, against a device that can be told to fail at any stage.

Every test here is synthetic: a dictionary of four record kinds stands in for
the unit, so no port opens and no store happens anywhere real. What is being
checked is not the wire but the order -- read before backup, backup before
store, verify after store -- and the promise that a stage which fails is
named rather than swallowed. ``tests/test_cli_write.py`` holds the other half
of the contract: the lines the CLI prints, which this loop must not move.
"""

import ast
import pathlib
from dataclasses import dataclass

import pytest

from nano import backup as bk
from nano import importplan, writing
from nano import messages as m
from nano import records as rec


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    """Backups go beside the settings directory, not into the checkout."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    return tmp_path / "config-home" / "nanosyned" / "backups"


@dataclass
class Step:
    """A plan step, spelled the way ``nanosyned.cli`` spells one."""

    kind: str
    number: int | None
    record: bytes


def program_step(number: int, name: str = "", fill: int = 0) -> Step:
    """A 350-byte program record, optionally named and marked."""
    record = bytearray(rec.PROGRAM_BYTES)
    record[-1] = fill
    if name:
        m.encode_name(record, name, m.NAME_BIT_OFFSET)
    return Step("program", number, bytes(record))


class FakeDevice:
    """The unit's user bank in memory, with a way to break one call.

    ``fail_read`` makes every destination read raise and ``fail_read_for``
    makes one slot do it; ``fail_write`` refuses every store; ``drop_writes``
    lets a store report success and change nothing, which is the mismatch a
    real unit produces when it ignores a store; and ``fail_read_back``
    raises only for a slot that was just written, so the read that is
    supposed to prove the write is the one that fails. Each switch is a
    different stage, and the loop has to keep them apart.
    """

    def __init__(self, seed: dict[int, bytes] | None = None) -> None:
        self.programs = {number: bytes(rec.PROGRAM_BYTES) for number in range(128)}
        for number, record in (seed or {}).items():
            self.programs[number] = bytes(record)
        self.stores: list[tuple[str, int | None, bytes]] = []
        self.fail_read = False
        self.fail_read_for: set[int] = set()
        self.fail_write = False
        self.drop_writes = False
        self.fail_read_back = False
        self._written: set[int] = set()

    def read_program(self, number, *, timeout=None):
        if self.fail_read or number in self.fail_read_for:
            raise m.ProtocolError(f"no answer for user program {number}")
        if self.fail_read_back and number in self._written:
            raise m.ProtocolError(f"the read-back of user program {number} was silent")
        return self.programs[number]

    def write_program(self, number, record, *, timeout=None):
        if self.fail_write:
            raise m.ProtocolError("the store was refused")
        self.stores.append(("program", number, bytes(record)))
        self._written.add(number)
        if not self.drop_writes:
            self.programs[number] = bytes(record)


class Flag:
    """A cancel: ``is_set()`` is the whole interface :func:`run` uses."""

    def __init__(self, *, set_already: bool = False) -> None:
        self._set = set_already

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True


class TestRead:
    def test_a_read_failure_is_not_written(self):
        device = FakeDevice()
        device.fail_read = True

        results = writing.run(device, [program_step(5)])

        assert device.stores == []
        (result,) = results
        assert result.stage == "read"
        assert result.failure is not None and "no answer" in result.failure
        assert result.previous == b""
        assert result.backup is None

    def test_one_unreadable_slot_does_not_stop_the_others(self):
        device = FakeDevice()
        device.fail_read_for.add(5)

        results = writing.run(device, [program_step(number) for number in (3, 5, 7)])

        assert [result.stage for result in results] == ["verified", "read", "verified"]
        assert [number for _kind, number, _record in device.stores] == [3, 7]


class TestBackup:
    def test_a_backup_failure_stores_nothing(self, tmp_path):
        device = FakeDevice()
        # A plain file where the backup directory belongs: nothing can be
        # written under it, which is the failure a read-only settings
        # directory produces. No internal is patched, so this is the loop's
        # own error path -- and the loop here is whatever object the module
        # holds, which another test's sys.modules cleanup may have replaced.
        blocked = tmp_path / "config-home" / "nanosyned"
        blocked.parent.mkdir(parents=True, exist_ok=True)
        blocked.write_text("not a directory")

        results = writing.run(device, [program_step(5)])

        assert device.stores == []
        (result,) = results
        assert result.stage == "backup"
        assert result.failure is not None and "backups" in result.failure
        assert result.backup is None

    def test_one_backup_per_slot_per_session(self):
        device = FakeDevice()

        results = writing.run(
            device,
            [program_step(5, "First"), program_step(5, "Second")],
        )

        assert [result.stage for result in results] == ["verified", "verified"]
        assert results[0].backup == results[1].backup
        assert len(bk.list_backups()) == 1

    def test_the_backup_holds_what_the_slot_held(self):
        old = program_step(5, "Old Name").record
        device = FakeDevice(seed={5: old})

        writing.run(device, [program_step(5, "New Name")])

        backups = bk.list_backups()
        assert len(backups) == 1
        assert backups[0].slot == "PROGRAM:005"
        assert backups[0].name == "Old Name"
        assert backups[0].blocks["program"] == old


class TestStore:
    def test_a_store_that_fails_is_named_and_not_read_back(self):
        device = FakeDevice()
        device.fail_write = True

        results = writing.run(device, [program_step(5)])

        (result,) = results
        assert result.stage == "store"
        assert result.failure is not None and "refused" in result.failure
        assert result.read_back is None
        assert result.sent is False

    def test_a_store_that_did_not_land_is_a_mismatch(self):
        device = FakeDevice()
        device.drop_writes = True

        results = writing.run(device, [program_step(5, fill=0x40)])

        (result,) = results
        assert result.stage == "verify"
        assert result.sent is True
        assert result.failure == result.sentence
        assert result.failure is not None and "byte(s) differ" in result.failure
        assert result.read_back == bytes(rec.PROGRAM_BYTES)
        assert result.backup is not None

    def test_a_verified_record_says_so_and_keeps_the_read_back(self):
        device = FakeDevice()
        step = program_step(5, "Tin Coil")

        (result,) = writing.run(device, [step])

        assert result.stage == "verified"
        assert result.failure is None
        assert result.sent is True
        assert result.read_back == step.record
        assert "read back byte-for-byte" in result.sentence

    def test_a_silent_read_back_is_its_own_stage(self):
        device = FakeDevice()
        device.fail_read_back = True

        results = writing.run(device, [program_step(5)])

        (result,) = results
        assert result.stage == "read-back"
        assert result.failure is not None and "silent" in result.failure
        assert result.sent is True
        assert result.read_back is None


class TestCancel:
    def test_a_cancel_already_set_attempts_nothing(self):
        device = FakeDevice()

        results = writing.run(device, [program_step(5)], cancel=Flag(set_already=True))

        assert results == []
        assert device.stores == []
        assert bk.list_backups() == []

    def test_cancel_between_streamed_steps_leaves_the_later_alone(self):
        device = FakeDevice()
        flag = Flag()
        reported = []

        def on_result(result):
            reported.append(result)
            flag.set()  # the first record is enough

        results = writing.run(
            device,
            [program_step(number) for number in (3, 4, 5)],
            on_result=on_result,
            cancel=flag,
            read_first=False,
        )

        assert [result.number for result in results] == [3]
        assert [result.number for result in reported] == [3]
        assert [number for _kind, number, _record in device.stores] == [3]
        assert len(bk.list_backups()) == 1

    def test_cancel_in_the_batched_read_phase_stores_nothing(self):
        device = FakeDevice()
        flag = Flag()

        def on_step(result):
            flag.set()  # after the first destination is read, not stored

        results = writing.run(
            device,
            [program_step(number) for number in (3, 4)],
            on_step=on_step,
            cancel=flag,
        )

        assert [result.stage for result in results] == ["read"]
        assert device.stores == []
        assert bk.list_backups() == []


class TestHooks:
    def test_the_batched_run_reports_read_then_backup_then_store(self):
        device = FakeDevice()
        phases = []

        def on_phase(name, results):
            phases.append((name, [result.stage for result in results]))

        writing.run(device, [program_step(3), program_step(4)], on_phase=on_phase)

        assert phases == [
            ("read", ["read", "read"]),
            ("backup", ["backup", "backup"]),
            ("store", ["verified", "verified"]),
        ]

    def test_a_streamed_run_reports_every_stage_of_one_step_at_a_time(self):
        device = FakeDevice()
        stages = []

        writing.run(
            device,
            [program_step(3), program_step(4)],
            on_step=lambda result: stages.append((result.number, result.stage)),
            read_first=False,
        )

        assert stages == [
            (3, "read"),
            (3, "backup"),
            (3, "store"),
            (3, "verified"),
            (4, "read"),
            (4, "backup"),
            (4, "store"),
            (4, "verified"),
        ]

    def test_a_failed_step_stays_visible_in_the_later_phases(self):
        device = FakeDevice()
        device.fail_read_for.add(5)
        listed = []

        def on_phase(name, results):
            listed.append((name, [result.number for result in results]))

        writing.run(
            device, [program_step(number) for number in (3, 5)], on_phase=on_phase
        )

        # A caller is told about every step it has heard of so far, so it
        # never has to remember a failure from one phase to the next; only
        # the step whose read worked is backed up and stored.
        assert listed[0] == ("read", [3, 5])
        assert listed[1] == ("backup", [3, 5])
        assert listed[2] == ("store", [3, 5])
        assert [number for _kind, number, _record in device.stores] == [3]
        assert len(bk.list_backups()) == 1


class TestStepShapes:
    def test_a_planner_step_naming_a_target_is_accepted(self):
        device = FakeDevice()
        step = importplan.Step(
            kind="program",
            target=6,
            record=bytes(rec.PROGRAM_BYTES),
            old_name=None,
            source_label="bank 0 program 006",
        )

        results = writing.run(device, [step])

        (result,) = results
        assert result.number == 6
        assert result.stage == "verified"
        assert [number for _kind, number, _record in device.stores] == [6]


def test_writing_imports_no_tui_no_cli_and_no_argument_parser():
    """The loop must be usable by both callers, so it imports neither one."""
    source = pathlib.Path(writing.__file__).read_text()
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots == {"__future__", "collections", "dataclasses", "nano", "typing"}
