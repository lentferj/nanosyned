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
from nano import messages as m
from nano import records as rec
from nanosyned import cli


@pytest.fixture
def config_path(tmp_path):
    """Keep channel/config reads out of the working directory."""
    return str(tmp_path / "config.toml")


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def sqs_container(body: bytes) -> bytes:
    """One MidiQuest BODY, for a file whose SysEx is ``body``."""
    body_chunk = b"BODY" + len(body).to_bytes(4, "big") + body
    form = b"FORM" + len(body_chunk).to_bytes(4, "big") + body_chunk
    return b"LIST" + (len(form) + 4).to_bytes(4, "big") + b"    " + form


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
                    "banks": {"GM": [{"n": 0, "name": "Invented Name"}]},
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

    def test_syx_reads_an_sqs_bank_like_the_syx_it_holds(self, tmp_path, capsys):
        record = bytearray(rec.PROGRAM_BYTES)
        m.encode_name(record, "Invented0")
        raw = m.program_dump(0, record) + m.global_dump(bytes(rec.GLOBAL_BYTES))
        syx_path = tmp_path / "bank.syx"
        sqs_path = tmp_path / "bank.sqs"
        syx_path.write_bytes(raw)
        sqs_path.write_bytes(sqs_container(raw))
        code, syx_out, _ = run(capsys, "syx", str(syx_path))
        assert code == 0
        code, sqs_out, _ = run(capsys, "syx", str(sqs_path))
        assert code == 0
        assert sqs_out.replace(str(sqs_path), "") == syx_out.replace(str(syx_path), "")
        assert "1 program(s)" in sqs_out
        assert "Invented0" in sqs_out

    def test_fav_and_tags_need_no_device(self, config_path, tmp_path, capsys):
        store = str(tmp_path / "favorites.db")
        code, _out, _ = run(
            capsys,
            "--config",
            config_path,
            "--favorites",
            store,
            "fav",
            "USER",
            "1",
            "--add",
            "--rate",
            "4",
        )
        assert code == 0
        code, out, _ = run(capsys, "--config", config_path, "--favorites", store, "fav")
        assert code == 0
        assert "★★★★·" in out
        code, _out, err = run(
            capsys, "--config", config_path, "--favorites", store, "tags"
        )
        assert code == 0
        assert "no tags" in err

    def test_a_swept_connect_says_so_on_stderr(self, config_path, monkeypatch, capsys):
        from nano import bridge as b

        class Fake:
            swept = True
            probe_seconds = 2.0
            port = "Fake Port 24"
            channel = 0
            description = "fake"

            def read_edit_program(self):
                return b"\x00" * 350

            def close(self):
                pass

        monkeypatch.setattr(
            b.NanoBridge, "connect", classmethod(lambda cls, **_kw: Fake())
        )
        code, _out, err = run(capsys, "--config", config_path, "current")
        assert code == 0
        assert "swept for 2.0 s; found Fake Port 24" in err

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


class TestWriteSurfaceParser:
    """The write commands' shape, before any of them runs."""

    def test_write_flags_may_follow_the_subcommand(self):
        args = cli.build_parser().parse_args(
            ["send", "x.syx", "--allow-write", "--yes"]
        )
        assert args.allow_write is True
        assert args.yes is True

    def test_write_flags_still_work_before_the_subcommand(self):
        args = cli.build_parser().parse_args(
            ["--allow-write", "--yes", "send", "x.syx"]
        )
        assert args.allow_write is True
        assert args.yes is True

    def test_a_flag_before_the_subcommand_is_not_overwritten(self):
        args = cli.build_parser().parse_args(
            ["--channel", "5", "set", "program", "0", "0", "0", "5"]
        )
        assert args.channel == 5

    def test_dump_names_a_number_and_a_file(self):
        args = cli.build_parser().parse_args(["dump", "mix", "7", "--file", "m.syx"])
        assert args.dump_command == "mix"
        assert args.number == 7
        assert args.file == "m.syx"

    def test_a_global_dump_has_no_number(self):
        args = cli.build_parser().parse_args(["dump", "global", "--file", "g.syx"])
        assert args.dump_command == "global"
        assert not hasattr(args, "number")

    def test_backup_list_needs_no_destination(self):
        args = cli.build_parser().parse_args(["backup", "list"])
        assert args.backup_command == "list"
        assert not hasattr(args, "number")

    def test_backup_restore_takes_a_file_and_an_optional_number(self):
        args = cli.build_parser().parse_args(
            ["backup", "restore", "b.json", "--number", "5"]
        )
        assert args.backup_command == "restore"
        assert args.number == 5
