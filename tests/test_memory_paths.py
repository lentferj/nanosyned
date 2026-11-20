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

"""The preset-memory path and its CLI/app injection."""

from __future__ import annotations

import os

from nano import favorites
from nanosyned import cli
from nanosyned.app import NanosynedApp
from nanosyned.demo import DemoDevice


class TestThePath:
    def test_the_sidecar_sits_beside_the_favourites_database(self):
        path = favorites.memory_path()

        assert path.endswith("preset-memory.db")
        assert os.path.dirname(path) == favorites.data_dir()


class TestTheCli:
    def test_preset_memory_works_before_import(self, tmp_path):
        path = str(tmp_path / "before.db")
        args = cli.build_parser().parse_args(
            ["--preset-memory", path, "import", "bank.syx"]
        )

        assert args.preset_memory == path

    def test_preset_memory_works_after_import(self, tmp_path):
        path = str(tmp_path / "after.db")
        args = cli.build_parser().parse_args(
            ["import", "bank.syx", "--preset-memory", path]
        )

        assert args.preset_memory == path

    def test_preset_memory_works_before_send(self, tmp_path):
        path = str(tmp_path / "before.db")
        args = cli.build_parser().parse_args(
            ["--preset-memory", path, "send", "bank.syx"]
        )

        assert args.preset_memory == path

    def test_preset_memory_works_after_send(self, tmp_path):
        path = str(tmp_path / "after.db")
        args = cli.build_parser().parse_args(
            ["send", "bank.syx", "--preset-memory", path]
        )

        assert args.preset_memory == path


class TestTheApp:
    def test_a_path_opens_the_memory(self, tmp_path):
        app = NanosynedApp(DemoDevice(), memory_path=str(tmp_path / "memory.db"))
        try:
            assert app.memory is not None
            assert app.memory.path == str(tmp_path / "memory.db")
        finally:
            app.memory.close()

    def test_no_path_keeps_the_app_slot_based(self):
        app = NanosynedApp(DemoDevice())

        assert app.memory is None
