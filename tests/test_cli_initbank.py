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

"""CLI ``init-bank`` command, unit-tests only (no hardware)."""

from __future__ import annotations

import pytest

from nano import favorites, identity, preset_memory
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _make_device(monkeypatch, demo):
    """Monkeypatch DemoDevice for use in a test and return the demo instance."""

    def factory(**kwargs):
        if "channel" in kwargs:
            demo.channel = kwargs["channel"]
        return demo

    monkeypatch.setattr("nanosyned.demo.DemoDevice", factory)
    return demo


class PersistentDemo(DemoDevice):
    """A demo the CLI may close between calls without losing its store."""

    def close(self) -> None:
        pass


def test_init_bank_with_allow_yes(capsys, config_path, monkeypatch):
    """init-bank --allow-write --yes: all 127 slots get Init; 127 unchanged; exit 0."""
    device = PersistentDemo()
    _make_device(monkeypatch, device)
    before_127 = device.read_program(127)
    code, out, _ = run(
        capsys,
        "--demo",
        "--config",
        config_path,
        "init-bank",
        "--allow-write",
        "--yes",
    )
    assert code == 0, f"expected exit 0, got {code}"
    assert "127 untouched" in out
    for number in range(127):
        assert rec.program_name(device.read_program(number)).rstrip() == "Init"
    assert device.read_program(127) == before_127


def test_init_bank_preserves_old_favourite_content(
    capsys, config_path, tmp_path, monkeypatch
):
    """Init clears slot marks but keeps the replaced bytes as favourite content."""
    device = PersistentDemo()
    _make_device(monkeypatch, device)
    old = device.read_program(0)
    favs_path = str(tmp_path / "favorites.db")
    memory_path = str(tmp_path / "memory.db")
    with favorites.Favorites(favs_path) as store:
        store.add("USER", 0, name="Old", rating=3, tags="pad", note="keep")

    code, _out, _err = run(
        capsys,
        "--demo",
        "--config",
        config_path,
        "--favorites",
        favs_path,
        "--preset-memory",
        memory_path,
        "init-bank",
        "--allow-write",
        "--yes",
    )
    assert code == 0
    with favorites.Favorites(favs_path) as store:
        assert store.get("USER", 0) is None
    with preset_memory.PresetMemory(memory_path) as memory:
        old_entry = memory.get(identity.digest(old))
        assert old_entry is not None
        assert old_entry.favourite is True
        assert old_entry.rating == 3
        assert old_entry.tags == "pad"
        assert old_entry.note == "keep"


def test_init_bank_dry_run(capsys, config_path, monkeypatch):
    """init-bank --dry-run: no writes, gate not required."""
    device = PersistentDemo()
    _make_device(monkeypatch, device)
    code, _out, _ = run(
        capsys,
        "--demo",
        "--config",
        config_path,
        "init-bank",
        "--dry-run",
    )
    assert code == 0, f"expected exit 0, got {code}"
    assert not device.program_writes


def test_init_bank_gate_refusal(capsys, config_path, monkeypatch):
    """init-bank without --allow-write and --yes: gate refusal."""
    _make_device(monkeypatch, PersistentDemo())
    with pytest.raises(SystemExit) as excinfo:
        run(capsys, "--demo", "--config", config_path, "init-bank")
    message = str(excinfo.value)
    assert "--allow-write" in message or "--yes" in message


def test_init_bank_verify_mismatch_returns_1(capsys, config_path, monkeypatch):
    """A demo that accepts the store but not the bytes returns 1."""

    class NoWrite(PersistentDemo):
        def write_program(self, number, record, *, timeout=None):
            pass

    _make_device(monkeypatch, NoWrite())
    code, _out, _err = run(
        capsys,
        "--demo",
        "--config",
        config_path,
        "init-bank",
        "--allow-write",
        "--yes",
    )
    assert code == 1


def test_init_bank_failure_returns_1(capsys, config_path, monkeypatch):
    """init-bank with a read failure returns exit code 1 if cheap to simulate."""

    class FailingDemo(PersistentDemo):
        def read_program(self, number, *, timeout=None):
            if number == 42:
                raise ValueError("read failed at 42")
            return super().read_program(number, timeout=timeout)

    _make_device(monkeypatch, FailingDemo())
    with pytest.raises(SystemExit) as excinfo:
        run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "init-bank",
            "--allow-write",
            "--yes",
        )
    message = str(excinfo.value)
    assert "read failed" in message.lower() or "42" in message
