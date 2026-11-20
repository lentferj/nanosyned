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

"""``nanocli import`` and ``nanocli send`` remember content identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from nano import favorites, identity, preset_memory
from nano import messages as m
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@dataclass(frozen=True)
class Paths:
    root: Path
    config: str
    favorites: str
    memory: str


@pytest.fixture
def paths(tmp_path):
    return Paths(
        root=tmp_path,
        config=str(tmp_path / "config.toml"),
        favorites=str(tmp_path / "favorites.db"),
        memory=str(tmp_path / "memory.db"),
    )


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
    record = bytearray(
        (index * 7 + 3 + seed) & 0x7F for index in range(rec.PROGRAM_BYTES)
    )
    m.encode_name(record, name, m.NAME_BIT_OFFSET)
    return bytes(record)


def _file(path: Path, number: int, record: bytes) -> None:
    path.write_bytes(m.program_dump(number, record))


def _seed(memory_path: str, record: bytes) -> str:
    with preset_memory.PresetMemory(memory_path) as memory:
        entry = memory.remember(record)
        memory.set_favourite(
            entry.digest, True, rating=4, tags="pad, warm", note="remembered"
        )
        return entry.digest


def _args(paths: Paths, *rest):
    return (
        "--demo",
        "--config",
        paths.config,
        "--favorites",
        paths.favorites,
        "--preset-memory",
        paths.memory,
        *rest,
    )


class TestImport:
    def test_a_known_favourite_is_remembered_and_re_marked(
        self, paths, capsys, monkeypatch
    ):
        use_device(monkeypatch, PersistentDemo())
        record = _record("Recall", 4)
        digest = _seed(paths.memory, record)
        source = paths.root / "one.syx"
        _file(source, 0, record)

        code, _out, err = run(
            capsys,
            *_args(
                paths,
                "import",
                str(source),
                "--program",
                "0=5",
                "--allow-write",
                "--yes",
            ),
        )
        assert code == 0
        assert "re-marked 1" in err
        with favorites.Favorites(paths.favorites) as store:
            marked = store.get("USER", 5)
            assert marked is not None
            assert marked.rating == 4
            assert marked.tags == "pad, warm"
            assert marked.note == "remembered"
        with preset_memory.PresetMemory(paths.memory) as memory:
            assert memory.slot_digest("USER", 5) == digest

    def test_an_overwrite_preserves_the_old_favourite_content(
        self, paths, capsys, monkeypatch
    ):
        use_device(monkeypatch, PersistentDemo())
        old = DemoDevice().read_program(5)
        with favorites.Favorites(paths.favorites) as store:
            store.add("USER", 5, name="Old", rating=3, tags="pad", note="keep")
        source = paths.root / "one.syx"
        _file(source, 0, _record("New", 7))

        code, _out, _err = run(
            capsys,
            *_args(
                paths,
                "import",
                str(source),
                "--program",
                "0=5",
                "--allow-write",
                "--yes",
            ),
        )
        assert code == 0
        with favorites.Favorites(paths.favorites) as store:
            assert store.get("USER", 5) is None
        with preset_memory.PresetMemory(paths.memory) as memory:
            old_entry = memory.get(identity.digest(old))
            assert old_entry is not None
            assert old_entry.favourite is True
            assert old_entry.rating == 3
            assert old_entry.tags == "pad"
            assert old_entry.note == "keep"

    def test_a_dry_run_does_not_create_the_memory(self, paths, capsys, monkeypatch):
        use_device(monkeypatch, PersistentDemo())
        source = paths.root / "one.syx"
        _file(source, 0, _record("Dry", 1))

        code, _out, _err = run(
            capsys,
            *_args(
                paths,
                "import",
                str(source),
                "--program",
                "0=5",
                "--dry-run",
            ),
        )
        assert code == 0
        assert not Path(paths.memory).exists()

    def test_a_failed_verify_does_not_remember(self, paths, capsys, monkeypatch):
        class NoWrite(PersistentDemo):
            def write_program(self, number, record, *, timeout=None):
                pass

        use_device(monkeypatch, NoWrite())
        source = paths.root / "one.syx"
        _file(source, 0, _record("Refused", 2))

        code, _out, _err = run(
            capsys,
            *_args(
                paths,
                "import",
                str(source),
                "--program",
                "0=5",
                "--allow-write",
                "--yes",
            ),
        )
        assert code == 1
        assert not Path(paths.memory).exists()


class TestSend:
    def test_a_sent_program_re_marks_its_known_favourite(
        self, paths, capsys, monkeypatch
    ):
        use_device(monkeypatch, PersistentDemo())
        record = _record("Recall", 5)
        digest = _seed(paths.memory, record)
        source = paths.root / "one.syx"
        _file(source, 0, record)

        code, _out, err = run(
            capsys,
            *_args(
                paths,
                "send",
                str(source),
                "--allow-write",
                "--yes",
            ),
        )
        assert code == 0
        assert "re-marked 1" in err
        with favorites.Favorites(paths.favorites) as store:
            assert store.get("USER", 0) is not None
        with preset_memory.PresetMemory(paths.memory) as memory:
            assert memory.slot_digest("USER", 0) == digest
