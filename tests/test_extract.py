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

"""The catalog extractor: manual grammar, dump precedence and round-trip.

Every name here is invented, from the demo's word pool. No Alesis name is
used, no port is opened, and no real ``.syx`` file is read: the dump in
these tests is built frame by frame from :mod:`nano.messages` and
:mod:`nano.records`.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from nano import catalog as cat
from nano import messages as m
from nano import records as rec

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "extract_catalog.py")
_FIXTURE = os.path.join(_HERE, "fixtures", "invented.ins")

#: What the fixture says, per bank, in display-number order. The "p3" line
#: is deliberately lower case: the extractor upper-cases a bank id.
EXPECTED: dict[str, list[tuple[int, str]]] = {
    "GM": [(0, "Tin Bell"), (1, "Glass Drone")],
    "USER": [(0, "Paper Pluck"), (1, "Rubber Wash")],
    "P1": [(10, "Copper Stab"), (127, "Velvet Sweep")],
    "P2": [(0, "Chalk Hum"), (5, "Iron Bow")],
    "P3": [(64, "Wool Choir"), (127, "Amber Reed")],
}

#: The two names the synthetic dump puts in the User bank. The first
#: deliberately disagrees with the fixture, which is what makes the
#: precedence test meaningful.
UNIT_NAMES = {0: "Unit Wash", 64: "Slate Thud"}


def _tool():
    """Load ``tools/`` by path; it is not an importable package."""
    spec = importlib.util.spec_from_file_location("extract_catalog", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract = _tool()


def _program(name: str) -> bytes:
    """One 350-byte program record carrying an invented name."""
    record = bytearray(rec.PROGRAM_BYTES)
    m.encode_name(record, name)
    # A byte past the name with bit 7 set, so the pack/unpack path is
    # actually exercised. A record of all 7-bit bytes would let a broken
    # packing pass this test.
    record[-1] = 0x80
    return bytes(record)


def _write_syx(path: Path, programs: dict[int, bytes]) -> None:
    """A ``.syx`` holding nothing but user program dumps."""
    path.write_bytes(
        b"".join(
            m.program_dump(number, record)
            for number, record in sorted(programs.items())
        )
    )


def _rows(names: list[tuple[int, str]]) -> list[dict[str, object]]:
    return [{"n": number, "name": name} for number, name in names]


def _extract_both(tmp_path: Path) -> Path:
    """Run the extractor over the fixture and a small synthetic dump."""
    syx = tmp_path / "invented.syx"
    _write_syx(syx, {number: _program(name) for number, name in UNIT_NAMES.items()})
    out = tmp_path / "catalog.json"
    assert (
        extract.main(
            [
                "--manual",
                _FIXTURE,
                "--syx",
                str(syx),
                "--output",
                str(out),
            ]
        )
        == 0
    )
    return out


class TestManualSource:
    def test_it_writes_every_bank_with_display_numbers(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "catalog.json"
        assert extract.main(["--manual", _FIXTURE, "--output", str(out)]) == 0

        payload = json.loads(out.read_text(encoding="utf-8"))
        assert set(payload["banks"]) == set(EXPECTED)
        for bank_id, names in EXPECTED.items():
            assert payload["banks"][bank_id] == _rows(names)

        # Rows carry the display number in "n", and on this instrument that
        # is the program change, both 0-based. A "pc" row would load back
        # one number higher, so none is written.
        for rows in payload["banks"].values():
            assert all(set(row) == {"n", "name"} for row in rows)
            assert all(isinstance(row["n"], int) for row in rows)

        assert "invented.ins" in payload["source"]
        # The fixture's one prose line is counted, not fatal, and does not
        # stop the ten real rows from being written.
        assert "1 line(s) did not parse and were skipped" in capsys.readouterr().err

    def test_malformed_lines_are_counted_and_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        source = tmp_path / "invented.ins"
        source.write_text(
            "# a comment\n"
            "\n"
            "GM 0 Tin Bell\n"
            "the list continues overleaf\n"  # prose: no number
            "NOPE 3 Unknown Bank\n"  # a bank that does not exist
            "USER 128 Out Of Range\n"  # one past the last program
            "P1 12Tight Name\n"  # no separator between number and name
            "USER 4 Glass Drone\n",
            encoding="utf-8",
        )
        out = tmp_path / "catalog.json"
        assert extract.main(["--manual", str(source), "--output", str(out)]) == 0

        err = capsys.readouterr().err
        assert f"{source}: 4 line(s) did not parse and were skipped" in err
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["banks"] == {
            "GM": [{"n": 0, "name": "Tin Bell"}],
            "USER": [{"n": 4, "name": "Glass Drone"}],
        }

    def test_a_whitespace_only_name_is_malformed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # "USER 000" followed by trailing spaces: the greedy separator used
        # to leave one space for the name group, so this parsed as a name
        # and was stored silently. It is a blank name and is counted, not
        # stored.
        source = tmp_path / "invented.ins"
        source.write_text("GM 0 Tin Bell\nUSER 000    \n", encoding="utf-8")
        out = tmp_path / "catalog.json"
        assert extract.main(["--manual", str(source), "--output", str(out)]) == 0

        err = capsys.readouterr().err
        assert f"{source}: 1 line(s) did not parse and were skipped" in err
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["banks"] == {"GM": [{"n": 0, "name": "Tin Bell"}]}

    def test_it_refuses_to_run_without_a_source(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            extract.main(["--output", str(tmp_path / "catalog.json")])


class TestDumpSource:
    def test_the_instrument_beats_the_page_in_the_user_bank(
        self, tmp_path: Path
    ) -> None:
        out = _extract_both(tmp_path)
        payload = json.loads(out.read_text(encoding="utf-8"))

        user = {row["n"]: row["name"] for row in payload["banks"]["USER"]}
        # USER 000 is transcribed as "Paper Pluck" in the fixture; the dump
        # says otherwise, and the dump wins.
        assert user[0] == UNIT_NAMES[0]
        assert user[64] == UNIT_NAMES[64]
        # A slot only the page names is untouched.
        assert user[1] == "Rubber Wash"

        # A dump fills the User bank and only the User bank.
        for bank_id, names in EXPECTED.items():
            if bank_id != "USER":
                assert payload["banks"][bank_id] == _rows(names)
        assert "invented.syx" in payload["source"]


class TestRoundTrip:
    def test_the_written_catalog_loads_back(self, tmp_path: Path) -> None:
        out = _extract_both(tmp_path)
        loaded = cat.load(str(out))

        expected_count = sum(len(names) for names in EXPECTED.values())
        # Two dump names, one of which replaces the page's USER 000.
        assert len(loaded) == expected_count + 1

        for bank_id, names in EXPECTED.items():
            for number, name in names:
                if (bank_id, number) == ("USER", 0):
                    assert loaded.display_name(bank_id, number) == UNIT_NAMES[0]
                else:
                    assert loaded.display_name(bank_id, number) == name

        assert loaded.display_name("USER", 64) == UNIT_NAMES[64]
        assert loaded.display_name("USER", 99) == cat.UNNAMED
        assert loaded.name("P3", 64) == "Wool Choir"
        # The extractor writes a catalog file; live names are still the
        # instrument's to supply.
        assert not loaded.is_live("USER", 0)
        assert "invented.ins" in loaded.source
        assert "invented.syx" in loaded.source

    def test_display_name_prefers_a_live_read_over_the_written_row(self) -> None:
        from_file = cat.Catalog([cat.Entry("USER", 0, "Page Pluck")])
        assert from_file.display_name("USER", 0) == "Page Pluck"
        from_file.set_live_name("USER", 0, "Unit Wash")
        assert from_file.display_name("USER", 0) == "Unit Wash"
