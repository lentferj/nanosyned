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

"""CLI ``dump favourites`` end-to-end with a demo device."""

from __future__ import annotations

import pytest

from nano import dumps
from nano.favorites import Favorites
from nanosyned import cli
from nanosyned.demo import DemoDevice


def _argv(tmp_path, *argv):
    return ["--favorites", str(tmp_path / "favorites.db"), *argv]


def _args(tmp_path, *argv):
    return cli.build_parser().parse_args(_argv(tmp_path, *argv))


def _seeded_favorites(tmp_path, numbers):
    """Seed the favorites DB with the given slot numbers."""
    favs = Favorites(str(tmp_path / "favorites.db"))
    for number in numbers:
        favs.add("USER", number, name=f"Prog {number}", rating=3, tags="", note="")
    return favs


class TestDumpFavourites:
    def test_dump_favourites_with_two_programs(self, tmp_path):
        """Dump two favourited programs; verify count, path, and file contents."""
        _ = _seeded_favorites(tmp_path, (5, 20))
        args = _args(
            tmp_path, "dump", "favourites", "--file", str(tmp_path / "out.syx")
        )
        device = DemoDevice(channel=0)
        cli._cmd_dump(device, args)

        # The output file should exist and contain exactly two programs
        out_file = tmp_path / "out.syx"
        assert out_file.exists()
        library = dumps.read_syx_file(str(out_file))
        assert set(library.programs.keys()) == {5, 20}
        assert len(library.programs) == 2

    def test_no_favourites_refusal(self, tmp_path):
        """No active favorites should cause a refusal."""
        args = _args(
            tmp_path, "dump", "favourites", "--file", str(tmp_path / "out.syx")
        )
        device = DemoDevice(channel=0)
        with pytest.raises(SystemExit) as caught:
            cli._cmd_dump(device, args)
        # ValueError from favourite_numbers is caught and re-raised as SystemExit
        assert "no favourited User programs to export" in str(caught.value)

        # No file should have been created
        assert not (tmp_path / "out.syx").exists()

    def test_existing_file_without_force_refusal(self, tmp_path):
        """Existing file without --force should be refused; bytes untouched."""
        # Seed one favourite so a file would be written
        _ = _seeded_favorites(tmp_path, (5,))
        args = _args(
            tmp_path, "dump", "favourites", "--file", str(tmp_path / "out.syx")
        )
        device = DemoDevice(channel=0)

        # Pre-create the output file with some content
        out_file = tmp_path / "out.syx"
        out_file.write_bytes(b"existing file content")

        with pytest.raises(SystemExit) as caught:
            cli._cmd_dump(device, args)
        assert "already exists" in str(caught.value)

        # Original bytes should be untouched
        assert out_file.read_bytes() == b"existing file content"

    def test_existing_file_with_force_replaced(self, tmp_path):
        """Existing file with --force should be replaced."""
        # Seed one favourite
        _ = _seeded_favorites(tmp_path, (5,))
        args = _args(
            tmp_path,
            "dump",
            "favourites",
            "--file",
            str(tmp_path / "out.syx"),
            "--force",
        )
        device = DemoDevice(channel=0)

        # Pre-create the output file with some content
        out_file = tmp_path / "out.syx"
        out_file.write_bytes(b"existing file content")

        # This should not raise
        cli._cmd_dump(device, args)

        # File should now contain the exported program
        library = dumps.read_syx_file(str(out_file))
        assert 5 in library.programs
