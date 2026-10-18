# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""The catalog binding, and the one grammar trap it is written around.

``nano.catalog`` binds :mod:`vinsynlib.catalog`. The library keys on the
**display** number and, for an older file, converts a ``"pc"`` row with a
``+1`` offset -- right for a tool whose first patch is number 1. This
instrument counts from zero exactly as MIDI does, so on this unit the wire
number *is* the display number and a ``"pc"`` row must land on the same
slot it names. Reading it through the library's loader would shift every
catalog written before the grammar changed by one slot, silently, and a
one-slot shift is a plausible wrong answer rather than an error.
"""

from __future__ import annotations

import json

from nano import catalog as cat

#: An invented name, per CLAUDE.md: no Alesis name appears in a test.
NAME = "Invented Bell"


def _write(tmp_path, payload) -> str:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestTheRowGrammar:
    def test_a_legacy_pc_row_lands_on_the_same_slot(self, tmp_path):
        """``"pc": 0`` is slot 0, not slot 1 -- the whole trap."""
        path = _write(tmp_path, {"banks": {"USER": [{"pc": 0, "name": NAME}]}})
        loaded = cat.load(path)
        assert loaded.display_name("USER", 0) == NAME
        assert loaded.name("USER", 1) is None

    def test_an_n_row_lands_on_its_own_slot(self, tmp_path):
        path = _write(
            tmp_path,
            {"banks": {"USER": [{"n": 5, "name": NAME}]}},
        )
        loaded = cat.load(path)
        assert loaded.display_name("USER", 5) == NAME
        assert loaded.name("USER", 0) is None

    def test_both_grammars_agree_on_the_slot(self, tmp_path):
        legacy = cat.load(
            _write(tmp_path, {"banks": {"GM": [{"pc": 7, "name": NAME}]}})
        )
        current = cat.load(
            _write(tmp_path, {"banks": {"GM": [{"n": 7, "name": NAME}]}})
        )
        assert legacy.name("GM", 7) == current.name("GM", 7) == NAME


class TestWhatItDoesWithABadFile:
    def test_a_missing_catalog_is_empty_and_silent(self, tmp_path):
        assert not cat.load(str(tmp_path / "nope.json"))
        assert cat.load(str(tmp_path / "nope.json")).source == ""

    def test_a_file_that_is_not_json_warns_and_is_empty(self, tmp_path, capsys):
        path = tmp_path / "catalog.json"
        path.write_text("this is not json", encoding="utf-8")
        assert not cat.load(str(path))
        assert "could not be read as a catalog" in capsys.readouterr().err

    def test_a_json_file_that_is_not_a_catalog_warns_and_is_empty(
        self, tmp_path, capsys
    ):
        path = tmp_path / "catalog.json"
        path.write_text(json.dumps(["not", "a", "catalog"]), encoding="utf-8")
        assert not cat.load(str(path))
        assert "is not a catalog" in capsys.readouterr().err

    def test_one_bad_row_costs_one_row(self, tmp_path, capsys):
        path = _write(
            tmp_path,
            {
                "banks": {
                    "USER": [
                        {"n": 0, "name": NAME},
                        {"n": 1},
                        "not a row",
                        {"pc": 2, "name": 5},
                        {"n": 3, "name": "Kept"},
                    ]
                }
            },
        )
        loaded = cat.load(path)
        assert loaded.name("USER", 0) == NAME
        assert loaded.name("USER", 3) == "Kept"
        assert loaded.name("USER", 1) is None
        assert "3 unreadable row(s)" in capsys.readouterr().err


class TestDisagreementSemantics:
    """The one thing the library cannot own: what a difference means here.

    In a writable bank it is somebody's saved work; in a ROM bank it is the
    printed list that is wrong. The library only reports *that* the two
    differ.
    """

    def test_a_writable_bank_differing_is_saved_work(self, tmp_path):
        loaded = cat.load(
            _write(tmp_path, {"banks": {"USER": [{"n": 0, "name": NAME}]}})
        )
        loaded.set_live_name("USER", 0, "Something Else")
        assert loaded.differs("USER", 0)
        assert loaded.disagreement("USER", 0, writable=True) == (
            "saved over the factory preset"
        )

    def test_a_rom_bank_differing_is_a_wrong_printed_list(self, tmp_path):
        loaded = cat.load(_write(tmp_path, {"banks": {"GM": [{"n": 0, "name": NAME}]}}))
        loaded.set_live_name("GM", 0, "Something Else")
        assert loaded.disagreement("GM", 0, writable=False) == (
            "the printed list is wrong; the unit is right"
        )

    def test_no_disagreement_reads_as_none(self, tmp_path):
        loaded = cat.load(_write(tmp_path, {"banks": {"GM": [{"n": 0, "name": NAME}]}}))
        assert loaded.disagreement("GM", 0, writable=False) is None
