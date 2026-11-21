# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The restore point the write path takes before it overwrites a program.

``nano.backup`` is a binding of the family's envelope, so what is pinned
here is the binding's side of the bargain plus the library's promises the
app relies on:

* a record's blocks round-trip through JSON and base64 unchanged;
* two saves of one slot and name are two files, never one replaced;
* a corrupt file is listed with its ``error`` rather than dropped --
  a restore point you cannot read is exactly the thing to be told about;
* a wrong or absent ``format`` is refused instead of guessed at;
* an empty block set is legal: the binding does not pretend to know what
  the record kinds must contain;
* the default directory is the per-platform settings directory, not the
  checkout that ``git clean`` empties;
* the CLI's offline commands never construct a bridge.

**Nothing here talks to MIDI.** The bridge is monkeypatched to explode in
the one test that goes through ``main()``, and every save is redirected
into ``tmp_path`` by the autouse fixture, so no test can drop a restore
point into the user's real settings directory.
"""

from __future__ import annotations

import json
import os

import pytest

from nano import backup as bk
from nanosyned import cli
from vinsynlib.config import config_dir

#: The real function, captured before the autouse fixture replaces it.
#: The default-directory test is the one caller that needs the real one.
REAL_BACKUP_DIR = bk.backup_dir

#: One invented 350-byte record. The high bytes prove the base64 layer is
#: doing something; an all-ASCII block would pass through almost anything.
BLOCK = bytes((number * 7) & 0xFF for number in range(350))


@pytest.fixture(autouse=True)
def backups_stay_in_tmp(tmp_path, monkeypatch):
    """Redirect every save and listing into ``tmp_path``.

    Autouse on purpose: a test that forgets to ask for the fixture must
    still not write ``~/.config/nanosyned/backups``. The directory is not
    created here -- ``save`` creates it, which is the behaviour under
    test.
    """
    target = tmp_path / "backups"
    monkeypatch.setattr(bk, "backup_dir", lambda: str(target))
    return target


def save_program(*, name: str = "Invented Bell", blocks=None) -> str:
    """One program backup, through the binding, into the patched directory."""
    return bk.save(
        "USER:000",
        kind="program",
        name=name,
        blocks={"program": BLOCK} if blocks is None else blocks,
        device_id="demo-device",
        source="tests/test_backup.py",
    )


class TestTheEnvelope:
    """``nano.backup``: the library's envelope, this unit's kinds."""

    def test_a_program_block_round_trips(self, backups_stay_in_tmp):
        path = save_program()
        assert os.path.dirname(path) == str(backups_stay_in_tmp)

        loaded = bk.load(path)
        assert loaded.kind == "program"
        assert loaded.slot == "USER:000"
        assert loaded.name == "Invented Bell"
        assert loaded.device_id == "demo-device"
        assert loaded.source == "tests/test_backup.py"
        assert loaded.blocks == {"program": BLOCK}
        assert loaded.error is None

        rows = bk.list_backups()
        assert len(rows) == 1
        assert rows[0].blocks == {"program": BLOCK}
        assert rows[0].error is None

    def test_the_filename_never_overwrites(self, backups_stay_in_tmp):
        """Two saves are two files, not one replaced. The library's rule."""
        first = save_program()
        second = save_program()
        assert first != second
        assert os.path.isfile(first)
        assert os.path.isfile(second)
        assert len(bk.list_backups()) == 2

    def test_a_corrupt_file_is_listed_with_its_error(self, backups_stay_in_tmp):
        save_program()
        corrupt = backups_stay_in_tmp / "corrupt.json"
        corrupt.write_text("not json", encoding="utf-8")

        rows = bk.list_backups()
        good = [row for row in rows if row.error is None]
        broken = [row for row in rows if row.error is not None]
        assert len(good) == 1
        assert len(broken) == 1
        # A Backup carries no filename, but it carries the reason it could
        # not be read -- which is the useful half.
        assert "Expecting" in (broken[0].error or "")

    @pytest.mark.parametrize(
        "payload",
        [
            {"format": bk.FORMAT + 1, "kind": "program", "blocks": {}},
            {"kind": "program", "blocks": {}},
        ],
        ids=["wrong-version", "no-format"],
    )
    def test_a_wrong_or_absent_format_is_refused(self, tmp_path, payload):
        path = tmp_path / "bad-format.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="wrong version"):
            bk.load(str(path))

    def test_an_empty_block_set_is_legal(self, backups_stay_in_tmp):
        """The binding does not pretend to know what a kind must contain.

        What a ``program`` block holds is the SysEx record's business;
        the envelope's is to carry whatever it is handed.
        """
        path = save_program(blocks={})
        loaded = bk.load(path)
        assert loaded.blocks == {}
        assert loaded.error is None
        assert bk.list_backups()[0].blocks == {}

    def test_a_missing_directory_lists_nothing(self):
        """The autouse fixture's directory is not created until a save."""
        assert bk.list_backups() == []

    def test_the_default_directory_is_not_the_checkout(self, monkeypatch, tmp_path):
        """Beside ``config.toml``, because ``git clean`` empties a checkout."""
        # Point every platform branch at this test's tree: Linux reads XDG,
        # macOS reads HOME, and Windows reads LOCALAPPDATA.
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
        monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
        default = REAL_BACKUP_DIR()
        assert default == os.path.join(config_dir("nanosyned"), "backups")
        assert default.startswith(str(tmp_path))
        assert os.path.basename(default) == "backups"
        assert "nanosyned" in default

        checkout = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert not default.startswith(checkout + os.sep), (
            "the default backup directory is inside the checkout"
        )

    def test_the_kinds_are_the_records_this_unit_can_save(self):
        assert bk.KINDS == ("program", "mix", "effects", "global")
        assert bk.FORMAT >= 1


class TestTheCliIsOffline:
    """No command that says it needs no unit may open a port."""

    @staticmethod
    def _no_bridge(monkeypatch):
        from nano import bridge

        def explode(*args, **kwargs):
            raise AssertionError("an offline command constructed a bridge")

        monkeypatch.setattr(bridge.NanoBridge, "open", classmethod(explode))
        monkeypatch.setattr(bridge.NanoBridge, "connect", classmethod(explode))

    def test_banks_and_list_need_no_unit(self, monkeypatch, capsys, tmp_path):
        self._no_bridge(monkeypatch)
        path = str(tmp_path / "config.toml")
        assert cli.main(["--config", path, "banks"]) == 0
        assert cli.main(["--config", path, "list", "GM"]) == 0
        out = capsys.readouterr().out
        assert "General MIDI" in out

    def test_backup_list_is_offline_if_the_command_exists(
        self, monkeypatch, capsys, tmp_path, backups_stay_in_tmp
    ):
        if "backup" not in cli.COMMANDS:
            pytest.skip(
                "nanocli has no backup command in this build; nano.backup is "
                "tested directly above and the envelope is the library's"
            )
        save_program(name="Invented Offline Backup")
        self._no_bridge(monkeypatch)
        path = str(tmp_path / "config.toml")
        assert cli.main(["--config", path, "backup", "list"]) == 0
        out = capsys.readouterr().out
        # The listing names the directory it read and the backup it found;
        # no bridge was constructed above, which is the point.
        assert str(backups_stay_in_tmp) in out
        assert "Invented Offline Backup" in out
