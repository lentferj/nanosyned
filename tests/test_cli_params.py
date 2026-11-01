# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

import pytest

from nano import params
from nanosyned import cli


@pytest.fixture
def config_path(tmp_path):
    return str(tmp_path / "config.toml")


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestParams:
    def test_main_params_opens_no_port(self, config_path, monkeypatch, capsys):
        from nano import bridge as b

        def fail_open(*args, **kwargs):
            raise AssertionError("opened port")

        def fail_connect(*args, **kwargs):
            raise AssertionError("connected")

        monkeypatch.setattr(b.NanoBridge, "open", classmethod(fail_open))
        monkeypatch.setattr(b.NanoBridge, "connect", classmethod(fail_connect))
        code, out, _ = run(capsys, "--config", config_path, "params")
        assert code == 0
        assert "75 of 178 rows verified on the bench unit (2026-11-01)" in out

    def test_params_global_shows_only_global_and_known_verified(
        self, config_path, capsys
    ):
        code, out, _ = run(capsys, "--config", config_path, "params", "global")
        assert code == 0
        assert "Pitch transpose*" in out
        line = next(line for line in out.splitlines() if "Pitch transpose*" in line)
        assert line.split()[0] == "yes"
        assert "twos" in line

    def test_params_effects_shows_all_unverified_and_summary(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "params", "effects")
        assert code == 0
        for line in out.splitlines():
            if "Effect" not in line:
                continue
            # Every effects row is a transcription: the unit ignored every
            # effects 10 the bench sent, so none may say yes.
            assert line.lstrip().startswith("no"), line
        assert "0 of 81 effects rows verified" in out

    def test_summary_matches_params_data(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "params")
        assert code == 0
        verified = len(params.verified_params())
        total = len(params.PARAMS)
        assert f"{verified} of {total} rows verified" in out
