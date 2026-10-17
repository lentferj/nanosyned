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

"""The live-name sidecar: where it sits, and that it survives a round trip.

Offline throughout -- every path is under ``tmp_path`` -- because the
sidecar is a file cache and the unit it caches names from is not needed
to test the caching.
"""

import os

from nano import catalog
from nano import livenames as ln


class TestWhereTheSidecarSits:
    def test_it_lives_beside_the_catalog_it_was_read_against(self, tmp_path):
        catalog_path = str(tmp_path / "catalog.json")
        found = ln.path_for(catalog_path)
        assert found.endswith(ln.FILE_NAME)
        assert os.path.dirname(found) == os.path.dirname(os.path.abspath(catalog_path))

    def test_without_a_catalog_it_sits_beside_the_built_in_one(self):
        assert ln.path_for() == ln.path_for(catalog.DEFAULT_PATH)

    def test_the_name_is_the_librarys(self):
        from vinsynlib import livenames as _livenames

        assert ln.FILE_NAME == _livenames.FILE_NAME


class TestTheRoundTrip:
    def test_saved_names_come_back(self, tmp_path):
        path = ln.path_for(str(tmp_path / "catalog.json"))
        names = {ln.key("USER", 1): "Mine", ln.key("USER", 2): "Yours"}
        ln.save(path, names)
        assert ln.load(path) == names

    def test_a_missing_file_is_simply_empty(self, tmp_path):
        assert ln.load(str(tmp_path / "nothing.json")) == {}

    def test_a_later_save_keeps_what_was_already_there(self, tmp_path):
        path = str(tmp_path / ln.FILE_NAME)
        ln.save(path, {ln.key("USER", 1): "Mine"})
        ln.save(path, {ln.key("USER", 2): "Yours"})
        assert ln.load(path) == {ln.key("USER", 1): "Mine", ln.key("USER", 2): "Yours"}


class TestApplyingToACatalog:
    def test_it_lays_names_onto_the_live_layer(self, tmp_path):
        names = catalog.empty()
        path = str(tmp_path / ln.FILE_NAME)
        ln.save(path, {ln.key("USER", 1): "Mine", ln.key("USER", 2): "Yours"})
        applied = ln.apply_to(names, path)
        assert applied == 2
        assert names.live_name("USER", 1) == "Mine"
        assert names.live_name("USER", 2) == "Yours"

    def test_a_malformed_key_is_skipped_rather_than_guessed(self, tmp_path):
        names = catalog.empty()
        path = str(tmp_path / ln.FILE_NAME)
        ln.save(
            path,
            {
                ln.key("USER", 1): "Good",
                "not a key": "Bad",
                "USER:xx": "Also bad",
            },
        )
        applied = ln.apply_to(names, path)
        assert applied == 1
        assert names.live_name("USER", 1) == "Good"
        assert names.live_name("USER", 0) is None
        assert names.live_name("USER", 2) is None
