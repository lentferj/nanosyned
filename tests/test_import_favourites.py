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

"""The importer, against an invented listing and a temporary database.

Every name here is invented. No listing or fixture carrying real program
names belongs in this repository: those are the user's own, and possibly
Alesis's.
"""

import importlib.util
import io
from pathlib import Path

import pytest

from nano.favorites import Favorites

TOOL = Path(__file__).resolve().parent.parent / "tools" / "import_favourites.py"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("import_favourites", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(tmp_path, text, name="listing.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_dry_run_writes_nothing(tool, tmp_path, capsys):
    listing = write(tmp_path, "[USER]\nPC 4  Amber Shine\n7  Glass Meridian\n")
    db = tmp_path / "favourites.db"

    status = tool.main(["--dry-run", "--favorites", str(db), str(listing)])

    assert status == 0
    assert not db.exists(), "a dry run must not even create the database"
    output = capsys.readouterr().out
    assert "dry run: nothing written" in output
    assert "Amber Shine" not in output, "the listing's names are not echoed by name"


def test_dry_run_leaves_an_existing_database_alone(tool, tmp_path):
    listing = write(tmp_path, "[USER]\nPC 4  Amber Shine\n")
    db = tmp_path / "favourites.db"
    with Favorites(str(db)) as store:
        store.add("USER", 1, name="Already There")
        before = len(store)

    status = tool.main(["--dry-run", "--favorites", str(db), str(listing)])

    assert status == 0
    with Favorites(str(db)) as store:
        assert len(store) == before
        assert store.get("USER", 4) is None


def test_a_normal_import_round_trips_from_a_file(tool, tmp_path):
    listing = write(
        tmp_path,
        "[USER]\nPC 4  Amber Shine\n7     Glass Meridian\n\n[P2]\nPC 9  Velvet Comb\n",
    )
    db = tmp_path / "favourites.db"

    assert tool.main(["--favorites", str(db), "--tag", "warm", str(listing)]) == 0

    with Favorites(str(db)) as store:
        amber = store.get("USER", 4)
        glass = store.get("USER", 7)
        velvet = store.get("P2", 9)
        assert amber is not None and amber.name == "Amber Shine"
        assert glass is not None and glass.name == "Glass Meridian"
        assert velvet is not None and velvet.name == "Velvet Comb"
        assert {row.tags for row in store.all()} == {"warm"}


def test_standard_input_is_read_when_no_file_is_named(tool, tmp_path, monkeypatch):
    db = tmp_path / "favourites.db"
    monkeypatch.setattr("sys.stdin", io.StringIO("[General MIDI]\nPC 0  Linen Bell\n"))

    assert tool.main(["--favorites", str(db)]) == 0

    with Favorites(str(db)) as store:
        row = store.get("GM", 0)
        assert row is not None and row.name == "Linen Bell"


def test_replace_clears_only_the_banks_the_listing_mentions(tool, tmp_path):
    listing = write(tmp_path, "[USER]\nPC 4  Fresh Name\n")
    db = tmp_path / "favourites.db"
    with Favorites(str(db)) as store:
        store.add("USER", 1, name="Old One")
        store.add("USER", 4, name="Stale")
        store.add("P2", 9, name="Keep Me")

    assert tool.main(["--favorites", str(db), "--replace", str(listing)]) == 0

    with Favorites(str(db)) as store:
        assert store.get("USER", 1) is None, "a slot in a mentioned bank is cleared"
        fresh = store.get("USER", 4)
        assert fresh is not None and fresh.name == "Fresh Name"
        kept = store.get("P2", 9)
        assert kept is not None
        assert kept.name == "Keep Me", "an unmentioned bank is kept"


def test_without_replace_an_existing_row_is_skipped(tool, tmp_path):
    listing = write(tmp_path, "[USER]\nPC 4  Fresh Name\n")
    db = tmp_path / "favourites.db"
    with Favorites(str(db)) as store:
        store.add("USER", 4, name="Mine", rating=4, tags="bright", note="keep")

    assert tool.main(["--favorites", str(db), str(listing)]) == 0

    with Favorites(str(db)) as store:
        row = store.get("USER", 4)
        assert row is not None
        assert (row.name, row.rating, row.tags, row.note) == (
            "Mine",
            4,
            "bright",
            "keep",
        )


def test_an_uncertain_row_is_tagged_not_dropped(tool, tmp_path):
    listing = write(
        tmp_path,
        "[USER]\nPC 4  Amber Shine\nPC 5  Chalk Hum <-- faint in the scan\nPC 6\n",
    )
    db = tmp_path / "favourites.db"

    assert tool.main(["--favorites", str(db), "--tag", "jam", str(listing)]) == 0

    with Favorites(str(db)) as store:
        certain = store.get("USER", 4)
        faint = store.get("USER", 5)
        blank = store.get("USER", 6)
        assert certain is not None and certain.tags == "jam"
        assert faint is not None
        assert faint.name == "Chalk Hum", "the <-- note is not part of the name"
        assert faint.tags == "jam,check-scan"
        assert blank is not None
        assert blank.name == ""
        assert blank.tags == "jam,check-scan"


def test_skip_uncertain_leaves_the_faint_row_out(tool, tmp_path):
    listing = write(
        tmp_path,
        "[USER]\nPC 4  Amber Shine\nPC 5  Chalk Hum <-- faint in the scan\nPC 6\n",
    )
    db = tmp_path / "favourites.db"

    assert tool.main(["--favorites", str(db), "--skip-uncertain", str(listing)]) == 0

    with Favorites(str(db)) as store:
        assert store.get("USER", 4) is not None
        assert store.get("USER", 5) is None
        # A blank name is not an uncertain *mark*: it parses, and is tagged
        # for a second look rather than silently skipped.
        blank = store.get("USER", 6)
        assert blank is not None and blank.tags == "check-scan"


def test_an_entry_before_a_bank_header_is_refused(tool, tmp_path):
    listing = write(tmp_path, "PC 4  Amber Shine\n")

    with pytest.raises(SystemExit) as raised:
        tool.main(["--dry-run", "--favorites", str(tmp_path / "f.db"), str(listing)])

    assert "before any bank header" in str(raised.value)
