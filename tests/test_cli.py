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

"""``nanocli``. Every command here runs against ``--demo`` or a file, so no
MIDI port is opened and no hardware is touched."""

import json

import pytest

from nano import banks
from nanosyned import cli


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


class TestOfflineCommands:
    def test_banks_lists_all_five(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "banks")
        assert code == 0
        for entry in banks.banks():
            assert entry.id in out

    def test_list_shows_the_bank_and_its_slots(self, config_path, capsys):
        code, out, _ = run(capsys, "--config", config_path, "list", "GM")
        assert code == 0
        assert "General MIDI" in out

    def test_find_reports_a_match(self, tmp_path, capsys):
        path = tmp_path / "catalog.json"
        path.write_text(
            json.dumps(
                {
                    "banks": {"GM": [{"pc": 0, "name": "Invented Name"}]},
                    "source": "test",
                    "generated": "2026-01-01",
                }
            )
        )
        code, out, _ = run(capsys, "--catalog", str(path), "find", "Invented")
        assert code == 0
        assert "Invented Name" in out

    def test_find_with_no_match_says_so(self, config_path, capsys):
        code, _out, err = run(capsys, "--config", config_path, "find", "zzz-nothing")
        assert code == 0
        assert "nothing matching" in err

    def test_syx_summarises_a_file(self, tmp_path, capsys):
        path = tmp_path / "empty.syx"
        path.write_bytes(b"")
        code, out, _ = run(capsys, "syx", str(path))
        assert code == 0
        assert "0 program(s)" in out

    def test_an_out_of_range_channel_is_refused(self, config_path):
        with pytest.raises(SystemExit):
            cli.main(["--config", config_path, "--channel", "17", "banks"])


class TestDemoCommands:
    def test_status_identifies_the_demo(self, config_path, capsys):
        code, out, _ = run(capsys, "--demo", "--config", config_path, "status")
        assert code == 0
        assert "Alesis" in out

    def test_current_reads_the_edit_buffer(self, config_path, capsys):
        code, out, _ = run(capsys, "--demo", "--config", config_path, "current")
        assert code == 0
        assert "edit buffer:" in out

    def test_read_returns_the_user_bank(self, config_path, capsys):
        code, out, _ = run(capsys, "--demo", "--config", config_path, "read")
        assert code == 0
        assert "User bank" in out

    def test_mixes_are_listed(self, config_path, capsys):
        code, out, _ = run(capsys, "--demo", "--config", config_path, "mixes")
        assert code == 0
        assert "mix(es)" in out

    def test_select_in_demo(self, config_path, capsys):
        code, out, _ = run(
            capsys, "--demo", "--config", config_path, "--yes", "select", "GM", "0"
        )
        assert code == 0
        assert "selected" in out

    def test_select_can_be_declined(self, config_path, capsys, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda *_args: "n")
        code, out, _ = run(
            capsys, "--demo", "--config", config_path, "select", "GM", "0"
        )
        assert code == 1
        assert "nothing sent" in out
