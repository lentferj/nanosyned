# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

import pytest

from nano import dumps
from nanosyned import cli
from nanosyned.demo import DemoDevice


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "config.toml")


class PersistentDemo(DemoDevice):
    def close(self) -> None:
        pass


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def use_device(monkeypatch, device):
    def factory(**kwargs):
        if "channel" in kwargs:
            device.channel = kwargs["channel"]
        return device

    monkeypatch.setattr("nanosyned.demo.DemoDevice", factory)
    return device


CASES = [
    ("program", ["dump", "program", "5", "--file", "{path}"]),
    ("mix", ["dump", "mix", "7", "--file", "{path}"]),
    ("effects", ["dump", "effects", "3", "--file", "{path}"]),
    ("global", ["dump", "global", "--file", "{path}"]),
]


class TestCliDump:
    @pytest.mark.parametrize("kind,argv", CASES, ids=[c[0] for c in CASES])
    def test_refuses_existing_without_force(
        self, kind, argv, tmp_path, monkeypatch, capsys
    ):
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / f"{kind}.syx")
        config_path = str(tmp_path / "config.toml")
        with open(out_path, "wb") as handle:
            handle.write(b"OLD BYTES")

        full_argv = ["--demo", "--config", config_path] + [
            a.format(path=out_path) for a in argv
        ]
        with pytest.raises(SystemExit) as exc:
            run(capsys, *full_argv)
        assert "already exists" in str(exc.value)
        assert "--force" in str(exc.value)

        with open(out_path, "rb") as handle:
            assert handle.read() == b"OLD BYTES"

    @pytest.mark.parametrize("kind,argv", CASES, ids=[c[0] for c in CASES])
    def test_with_force_overwrites(self, kind, argv, tmp_path, monkeypatch, capsys):
        use_device(monkeypatch, PersistentDemo())
        out_path = str(tmp_path / f"{kind}.syx")
        config_path = str(tmp_path / "config.toml")
        with open(out_path, "wb") as handle:
            handle.write(b"OLD BYTES")

        full_argv = (
            ["--demo", "--config", config_path]
            + [a.format(path=out_path) for a in argv]
            + ["--force"]
        )
        code, _out, _err = run(capsys, *full_argv)
        assert code == 0

        with open(out_path, "rb") as handle:
            data = handle.read()
        assert data != b"OLD BYTES"
        library = dumps.read_syx_file(out_path)
        if kind == "program":
            assert 5 in library.programs
        elif kind == "mix":
            assert 7 in library.mixes
        elif kind == "effects":
            assert 3 in library.effects
        elif kind == "global":
            assert library.globals_ is not None
