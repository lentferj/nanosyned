# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

import pytest

from nano import dumps
from nano import records as rec
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    """Backups go beside the settings directory, not into the checkout."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))
    return tmp_path / "config-home" / "nanosyned" / "backups"


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


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


class TestBackupSave:
    def test_save_returns_zero_and_creates_parseable_file(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0

        library = dumps.read_syx_file(out_path)
        # Exactly programs 0..126 (127 is hardwired silent and excluded)
        assert sorted(library.programs.keys()) == list(range(127))
        assert len(library.programs) == 127
        # All 128 effects
        assert sorted(library.effects.keys()) == list(range(128))
        assert len(library.effects) == 128
        # All 100 mixes
        assert sorted(library.mixes.keys()) == list(range(100))
        assert len(library.mixes) == 100
        # One global
        assert library.globals_ is not None
        # No program 127
        assert 127 not in library.programs

    def test_save_needs_no_write_flags(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        """No --allow-write / --yes required, and demo records no writes."""
        device = use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        # Should succeed without --allow-write and --yes
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0

        # Demo should record no program/effect/mix/global writes
        assert device.program_writes == []
        assert device.effect_writes == []
        assert device.mix_writes == []
        assert device.global_writes == []

    def test_save_refuses_existing_without_force(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        # First save
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0
        with open(out_path, "rb") as handle:
            first_bytes = handle.read()

        # Second save without --force should fail with SystemExit
        with pytest.raises(SystemExit) as exc:
            run(
                capsys,
                "--demo",
                "--config",
                config_path,
                "backup",
                "save",
                "--file",
                out_path,
            )
        assert "already exists" in str(exc.value)
        assert "--force" in str(exc.value)

        # Old bytes unchanged
        with open(out_path, "rb") as handle:
            second_bytes = handle.read()
        assert second_bytes == first_bytes

    def test_save_with_force_replaces(self, config_path, tmp_path, monkeypatch, capsys):
        device = use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        # First save
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0
        with open(out_path, "rb") as handle:
            first_bytes = handle.read()

        # Modify the device state slightly so the second save differs
        device.write_program(0, bytes(rec.PROGRAM_BYTES))

        # Second save with --force should succeed
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
            "--force",
        )
        assert code == 0

        # New bytes should be different
        with open(out_path, "rb") as handle:
            second_bytes = handle.read()
        assert second_bytes != first_bytes

    def test_save_output_mentions_breakdown(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        code, out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0

        # Output should mention the breakdown
        assert "127 programs" in out
        assert "128 effects" in out
        assert "100 mixes" in out
        assert "1 global" in out
        assert "356 records" in out
        assert out_path in out

    def test_round_trip_save_then_send(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        """Save a full backup, then send it back --allow-write --yes."""
        device = use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        # Capture original state of key records
        orig_prog_0 = bytes(device.read_program(0))
        orig_prog_126 = bytes(device.read_program(126))
        orig_effect_127 = bytes(device.read_effects(127))
        orig_mix_99 = bytes(device.read_mix(99))
        orig_global = bytes(device.read_global())

        # Save
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0

        # Send it back with write flags
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "--allow-write",
            "--yes",
            "send",
            out_path,
        )
        assert code == 0

        # Verify key records match
        assert (
            bytes(device.read_program(0))[: rec.PROGRAM_BYTES]
            == orig_prog_0[: rec.PROGRAM_BYTES]
        )
        assert (
            bytes(device.read_program(126))[: rec.PROGRAM_BYTES]
            == orig_prog_126[: rec.PROGRAM_BYTES]
        )
        assert (
            bytes(device.read_effects(127))[: rec.EFFECTS_BYTES]
            == orig_effect_127[: rec.EFFECTS_BYTES]
        )
        assert (
            bytes(device.read_mix(99))[: rec.MIX_BYTES] == orig_mix_99[: rec.MIX_BYTES]
        )
        assert (
            bytes(device.read_global())[: rec.GLOBAL_BYTES]
            == orig_global[: rec.GLOBAL_BYTES]
        )


class TestBackupSaveGate:
    def test_save_without_allow_write_opens_device_but_no_gate_error(
        self, config_path, tmp_path, monkeypatch, capsys
    ):
        """backup save should not require --allow-write or --yes."""
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / "full.syx")

        # Should not raise SystemExit about --allow-write or --yes
        code, _out, _err = run(
            capsys,
            "--demo",
            "--config",
            config_path,
            "backup",
            "save",
            "--file",
            out_path,
        )
        assert code == 0
