# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""``nanocli import`` and its parser — offline and offline-only flags."""

from __future__ import annotations

import pytest

from nano import backup as bk
from nano import importing
from nano import messages as m
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    """Backups and settings stay beside the test, not in the checkout."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    return tmp_path / "config-home" / "nanosyned" / "backups"


class PersistentDemo(DemoDevice):
    """A demo the CLI may close between calls without losing its store."""

    def close(self) -> None:
        pass


def use_device(monkeypatch, device):
    """Make ``--demo`` hand every invocation the same device."""

    def factory(**kwargs):
        if "channel" in kwargs:
            device.channel = kwargs["channel"]
        return device

    monkeypatch.setattr("nanosyned.demo.DemoDevice", factory)
    return device


def _chunk(kind, payload):
    return kind + len(payload).to_bytes(4, "big") + payload


def sqs_container(*bodies):
    """One MidiQuest BODY per body, wrapped in the standard LIST container."""
    forms = b"".join(
        b"FORM"
        + len(_chunk(b"FORM", _chunk(b"BODY", body))).to_bytes(4, "big")
        + b"    "
        + _chunk(b"FORM", _chunk(b"BODY", body))
        for body in bodies
    )
    return b"LIST" + len(forms).to_bytes(4, "big") + b"    " + forms


def _program(number, name):
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    return m.program_dump(number, record)


def _effects(number, fill=0x40):
    """One effects patch of rec.EFFECTS_BYTES."""
    return m.effects_dump(number, bytes([fill]) * rec.EFFECTS_BYTES)


def _mix(number, name=None):
    """One mix of rec.MIX_BYTES."""
    record = bytearray(rec.MIX_BYTES)
    if name is not None:
        m.encode_name(record, name, bit_offset=rec.MIX_NAME_BIT_OFFSET)
    return m.mix_dump(number, record)


def _global(fill=0x00):
    """One global settings dump of rec.GLOBAL_BYTES."""
    return m.global_dump(bytes([fill]) * rec.GLOBAL_BYTES)


def run(capsys, *argv):
    code = 0
    try:
        code = cli.main(list(argv))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestImportList:
    def test_list_one_syx(self, config_path, tmp_path, capsys):
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, out, _ = run(
            capsys, "--config", config_path, "import", str(path), "--list"
        )
        assert code == 0
        assert "1 bank(s)" in out
        assert "1 program(s)" in out
        assert "Invented7" in out

    def test_list_multi_bank_sqs(self, config_path, tmp_path, capsys):
        first = _program(0, "BankZero")
        second = _program(0, "BankOne")
        path = tmp_path / "two.sqs"
        path.write_bytes(sqs_container(first, second))
        code, out, _ = run(
            capsys, "--config", config_path, "import", str(path), "--list"
        )
        assert code == 0
        assert "bank 0" in out
        assert "bank 1" in out

    def test_list_unknown_bank(self, config_path, tmp_path):
        first = _program(0, "BankZero")
        path = tmp_path / "two.sqs"
        path.write_bytes(sqs_container(first, first))
        with pytest.raises(SystemExit) as caught:
            cli.main(
                ["--config", config_path, "import", str(path), "--list", "--bank", "99"]
            )
        message = str(caught.value).lower()
        assert "available" in message or "bank 0" in message

    def test_list_sqs_chooses_one_bank(self, config_path, tmp_path, capsys):
        first = _program(0, "BankZero")
        second = _program(0, "BankOne")
        path = tmp_path / "two.sqs"
        path.write_bytes(sqs_container(first, second))
        code, out, _ = run(
            capsys,
            "--config",
            config_path,
            "import",
            str(path),
            "--list",
            "--bank",
            "0",
        )
        assert code == 0
        assert "bank 0" in out
        assert "bank 1" not in out


class TestImportHelp:
    def test_help_mentions_flags(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "import", "--help")
        assert code == 0
        assert "--list" in out
        assert "--bank" in out
        assert "--program" in out
        assert "--dry-run" in out
        assert "--effects" in out
        assert "--mixes" in out
        assert "--global" in out


class TestImportWrite:
    """``--program SRC=DST`` and ``--all`` write with the family's safety."""

    def test_all_and_program_together_is_refused(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        """--all and --program together must be refused; no device write occurs."""
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--program",
            "7=5",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "--all" in err.lower() and "--program" in err.lower()
        assert device.program_writes == []
        assert len(bk.list_backups()) == 0

    def test_one_program_maps_to_one_destination(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        expected = importing.read_import(str(path)).banks[0].programs[7].record
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=5",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "user program 005" in out
        assert "Invented7" in out
        assert "read back byte-for-byte" in out
        assert "backup " in out
        assert device.read_program(5)[: rec.PROGRAM_BYTES] == expected
        backups = bk.list_backups()
        assert len(backups) == 1
        assert backups[0].slot == "PROGRAM:005"

    def test_two_programs_write_in_source_order(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "two.syx"
        path.write_bytes(_program(0, "Alpha") + _program(3, "Beta"))
        code, _, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "0=10",
            "--program",
            "3=11",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device.program_writes] == [10, 11]
        assert len(bk.list_backups()) == 2

    def test_duplicate_target_is_refused(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "two.syx"
        path.write_bytes(_program(0, "Alpha") + _program(3, "Beta"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "0=5",
            "--program",
            "3=5",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "assigned twice" in err
        assert device.program_writes == []

    def test_target_127_is_refused(self, config_path, tmp_path, monkeypatch, capsys):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=127",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "hardwired silent" in err
        assert device.program_writes == []

    def test_target_out_of_range_is_refused(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=128",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "outside" in err
        assert device.program_writes == []

    def test_missing_source_slot_is_refused(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "9=5",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "not in" in err
        assert device.program_writes == []

    def test_empty_selection_is_refused(self, config_path, tmp_path, capsys):
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "nothing selected" in err

    def test_multi_bank_file_needs_bank(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "two.sqs"
        path.write_bytes(sqs_container(_program(0, "BankZero"), _program(0, "BankOne")))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "0=5",
            "--dry-run",
        )
        assert code == 2
        assert "--bank" in err
        assert device.program_writes == []

    def test_dry_run_writes_nothing(self, config_path, tmp_path, monkeypatch, capsys):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        before = bytes(device.read_program(5))
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=5",
            "--dry-run",
        )
        assert code == 0
        assert "record(s) to write" in out
        assert "->" in out
        assert "Invented7" in out
        assert device.program_writes == []
        assert len(bk.list_backups()) == 0
        assert bytes(device.read_program(5)) == before

    def test_gate_refusal_opens_nothing(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setattr(
            "nanosyned.demo.DemoDevice",
            lambda **_kw: pytest.fail("a gated import opened a device"),
        )
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        with pytest.raises(SystemExit) as caught:
            cli.main(
                [
                    "--demo",
                    "--config",
                    config_path,
                    "import",
                    str(path),
                    "--program",
                    "7=5",
                ]
            )
        message = str(caught.value)
        assert "--allow-write" in message
        assert "--yes" in message

    def test_forced_mismatch_exits_one(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        device.write_program = lambda *a, **_kw: None
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, out, _ = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=5",
            "--allow-write",
            "--yes",
        )
        assert code == 1
        assert "MISMATCH" in out
        assert "the backup is" in out

    def test_failed_destination_read_writes_nothing(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())

        def bad_read(number, *, timeout=None):
            raise RuntimeError(f"user program {number} did not answer")

        device.read_program = bad_read
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7"))
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--program",
            "7=5",
            "--allow-write",
            "--yes",
        )
        assert code == 1
        assert device.program_writes == []
        assert len(bk.list_backups()) == 0


class PartsDemo(PersistentDemo):
    """A demo whose effects writes update the read-back store.

    The base :class:`DemoDevice` records an effects write but does not
    update ``_effects``, so a read-back would compare against the old
    value. A real unit reads back what it stored; this keeps the demo
    honest for the parts tests.
    """

    def write_effects(self, number, record, *, timeout=None):
        super().write_effects(number, record, timeout=timeout)
        self._effects[number] = bytes(record)


class TestImportParts:
    """``--effects``, ``--mixes`` and ``--global`` extend a bank import."""

    def test_all_three_flags_write_the_parts_too(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PartsDemo())
        path = tmp_path / "bank.syx"
        path.write_bytes(
            _program(3, "Invented3") + _effects(5) + _mix(10, "Bank10") + _global()
        )
        code, out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--effects",
            "--mixes",
            "--global",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device.program_writes] == [3]
        assert [number for number, _ in device.effect_writes] == [5]
        assert [number for number, _ in device.mix_writes] == [10]
        assert len(device.global_writes) == 1
        assert "4 record(s) to write" in out

    def test_each_part_flag_alone_writes_only_that_part(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        # --effects alone: programs + effects.
        device = use_device(monkeypatch, PartsDemo())
        path = tmp_path / "one.syx"
        path.write_bytes(_program(7, "Invented7") + _effects(5))
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--effects",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device.program_writes] == [7]
        assert [number for number, _ in device.effect_writes] == [5]
        assert device.mix_writes == []
        assert device.global_writes == []

        # --mixes alone: programs + mixes.
        device2 = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "two.syx"
        path.write_bytes(_program(3, "Alpha") + _mix(0, "MixA"))
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--mixes",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device2.program_writes] == [3]
        assert [number for number, _ in device2.mix_writes] == [0]
        assert device2.effect_writes == []
        assert device2.global_writes == []

        # --global alone: programs + global.
        device3 = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "three.syx"
        path.write_bytes(_program(9, "Gamma") + _global())
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--global",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device3.program_writes] == [9]
        assert len(device3.global_writes) == 1

    def test_missing_part_is_a_note_not_error(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "noeffects.syx"
        path.write_bytes(_program(7, "OnlyProgram"))
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--effects",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert device.effect_writes == []
        assert [number for number, _ in device.program_writes] == [7]

    def test_mix_100_is_skipped_with_a_note(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        device = use_device(monkeypatch, PersistentDemo())
        path = tmp_path / "mix100.syx"
        path.write_bytes(_program(3, "Alpha") + _mix(100, "EditBuffer"))
        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--mixes",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert "edit buffer" in err.lower()
        assert device.mix_writes == []
        assert [number for number, _ in device.program_writes] == [3]

    def test_global_last_in_order(self, config_path, tmp_path, monkeypatch, capsys):
        _device = use_device(monkeypatch, PartsDemo())
        path = tmp_path / "allparts.syx"
        path.write_bytes(
            _program(1, "One") + _effects(5) + _mix(10, "Mix10") + _global()
        )
        code, out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--effects",
            "--mixes",
            "--global",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        prog_pos = out.find("user program")
        eff_pos = out.find("effects patch")
        mix_pos = out.find("mix 010")
        glob_pos = out.find("the global settings")
        assert prog_pos < eff_pos < mix_pos < glob_pos

    def test_effect_and_mix_read_back(self, config_path, tmp_path, monkeypatch, capsys):
        device = use_device(monkeypatch, PartsDemo())
        path = tmp_path / "readback.syx"
        path.write_bytes(_program(3, "Program3") + _effects(5) + _mix(10, "Mix10"))
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(path),
            "--all",
            "--effects",
            "--mixes",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert [number for number, _ in device.effect_writes] == [5]
        assert [number for number, _ in device.mix_writes] == [10]
