# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""``nanocli import --append``: free trailing slots, cut warning, dry run."""

from __future__ import annotations

import pytest

from nano import initbank
from nano import messages as m
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "config.toml")


class PersistentDemo(DemoDevice):
    def close(self) -> None:
        pass


def use_device(monkeypatch, device):
    def factory(**kwargs):
        if "channel" in kwargs:
            device.channel = kwargs["channel"]
        return device

    monkeypatch.setattr("nanosyned.demo.DemoDevice", factory)
    return device


def run(capsys, *argv):
    code = 0
    try:
        code = cli.main(list(argv))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _record(name: str, seed: int = 0) -> bytes:
    data = bytearray(
        (index * 7 + 3 + seed) & 0x7F for index in range(rec.PROGRAM_BYTES)
    )
    m.encode_name(data, name, m.NAME_BIT_OFFSET)
    return bytes(data)


def _file(path, records):
    path.write_bytes(b"".join(m.program_dump(i, r) for i, r in enumerate(records)))


def _init_slots(device, first: int, last: int = 126):
    template = initbank.init_record(device.read_program(127))
    for number in range(first, last + 1):
        device.write_program(number, template)


class TestAppend:
    def test_two_programs_fill_the_trailing_free_slots(
        self, capsys, config_path, tmp_path, monkeypatch
    ):
        device = use_device(monkeypatch, PersistentDemo())
        _init_slots(device, 5)
        one, two = _record("One", 1), _record("Two", 2)
        source = tmp_path / "two.syx"
        _file(source, [one, two])

        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert device.read_program(5) == one
        assert device.read_program(6) == two
        assert "does not fit" not in err

    def test_overflow_refuses_without_cut(
        self, capsys, config_path, tmp_path, monkeypatch
    ):
        device = use_device(monkeypatch, PersistentDemo())
        _init_slots(device, 125)
        device.program_writes.clear()
        records = [_record("A", 1), _record("B", 2), _record("C", 3)]
        source = tmp_path / "three.syx"
        _file(source, records)

        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "does not fit" in err
        assert device.program_writes == []

    def test_overflow_with_cut_writes_the_first_fit(
        self, capsys, config_path, tmp_path, monkeypatch
    ):
        device = use_device(monkeypatch, PersistentDemo())
        _init_slots(device, 125)
        records = [_record("A", 1), _record("B", 2), _record("C", 3)]
        source = tmp_path / "three.syx"
        _file(source, records)

        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--cut",
            "--allow-write",
            "--yes",
        )
        assert code == 0
        assert device.read_program(125) == records[0]
        assert device.read_program(126) == records[1]

    def test_no_free_slots_is_refused(self, capsys, config_path, tmp_path, monkeypatch):
        device = use_device(monkeypatch, PersistentDemo())
        source = tmp_path / "one.syx"
        _file(source, [_record("One", 1)])

        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "no free slots" in err
        assert device.program_writes == []

    def test_append_and_program_are_refused(
        self, capsys, config_path, tmp_path, monkeypatch
    ):
        use_device(monkeypatch, PersistentDemo())
        source = tmp_path / "one.syx"
        _file(source, [_record("One", 1)])

        code, _out, err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--program",
            "0=5",
            "--allow-write",
            "--yes",
        )
        assert code == 2
        assert "cannot be combined" in err

    def test_dry_run_writes_nothing(self, capsys, config_path, tmp_path, monkeypatch):
        device = use_device(monkeypatch, PersistentDemo())
        _init_slots(device, 5)
        device.program_writes.clear()
        source = tmp_path / "one.syx"
        _file(source, [_record("One", 1)])

        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "import",
            str(source),
            "--append",
            "--dry-run",
        )
        assert code == 0
        assert device.program_writes == []
