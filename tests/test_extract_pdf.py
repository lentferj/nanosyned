# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors

"""The manual-PDF extractor's parser, exercised without OCR.

``tools/extract_catalog.py --pdf`` renders the Reference Manual's program
list and reads it with tesseract, which is not something CI can do. The
part that can be wrong in an interesting way is not the OCR call but the
**parsing** -- which column a word belongs to, and how the page's own
index number and marker glyphs are trimmed off a name -- so that part is a
pure function over tesseract's TSV text and is tested here.

The TSV below is invented: the words and their x positions are made up to
match the manual's geometry, and the names are from the demo's word pool.
No Alesis name appears, and no OCR runs.
"""

from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.join(os.path.dirname(_HERE), "tools", "extract_catalog.py")

_HEADER = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
    "left\ttop\twidth\theight\tconf\ttext"
)


def _tool():
    spec = importlib.util.spec_from_file_location("extract_catalog_pdf", _TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract = _tool()


def _w(line: int, left: int, text: str, page: int = 1) -> str:
    return f"5\t{page}\t1\t1\t{line}\t{left}\t{left}\t100\t40\t20\t96\t{text}"


def _tsv(*rows: str) -> str:
    return "\n".join((_HEADER, *rows)) + "\n"


#: One full data row, at the manual's x positions (300 dpi), plus a
#: category heading, a page header and a footer that must all be ignored.
FULL_PAGE = _tsv(
    _w(1, 226, "NanoSynth"),
    _w(1, 445, "Program"),
    _w(2, 413, "Piano"),
    _w(3, 226, "000"),
    _w(3, 339, "1"),
    _w(3, 413, "Tin"),
    _w(3, 500, "Bell"),
    _w(3, 676, "9"),
    _w(3, 726, "_"),
    _w(3, 770, "Paper"),
    _w(3, 845, "Stab"),
    _w(3, 1013, "0"),
    _w(3, 1126, "Copper"),
    _w(3, 1425, "4"),
    _w(3, 1576, "Wool"),
    _w(3, 1876, "0"),
    _w(3, 2026, "Amber"),
    _w(4, 226, "001"),
    _w(4, 339, "2"),
    _w(4, 413, "Glass"),
    _w(4, 529, "2"),
    _w(4, 677, "13"),
    _w(4, 771, "61"),
    _w(4, 822, "Tines"),
    _w(4, 1013, "1"),
    _w(4, 1126, "Rubber"),
    _w(4, 1425, "5"),
    _w(4, 1576, "Slate"),
    _w(4, 1876, "1"),
    _w(4, 2026, "Iron"),
    _w(20, 226, "NanoSynth"),
    _w(20, 445, "Reference"),
)


class TestTheColumnGeometry:
    def test_one_row_lands_in_all_five_banks(self):
        rows = extract.parse_tsv(FULL_PAGE)
        assert rows[("GM", 0)] == "Tin Bell"
        assert rows[("USER", 0)] == "Paper Stab"
        assert rows[("P1", 0)] == "Copper"
        assert rows[("P2", 0)] == "Wool"
        assert rows[("P3", 0)] == "Amber"

    def test_headings_and_the_page_footer_are_not_rows(self):
        rows = extract.parse_tsv(FULL_PAGE)
        # Two data rows only: no "Piano" heading, no footer.
        assert len(rows) == 10

    def test_the_next_columns_index_does_not_bleed_left(self):
        # 1425 is the *next* column's index in this layout; it must not be
        # appended to P1's name (the "Suitcase 4" bug).
        rows = extract.parse_tsv(FULL_PAGE)
        assert rows[("P1", 0)] == "Copper"


class TestTheTrim:
    def test_a_printed_index_and_marker_are_removed(self):
        assert extract._clean_cell(["9", "_", "Paper", "Stab"]) == "Paper Stab"

    def test_a_name_that_starts_with_a_number_survives(self):
        # "61 Tines" is a real User-bank name; only the printed index in
        # front of it is spurious.
        assert extract._clean_cell(["13", "61", "Tines"]) == "61 Tines"

    def test_a_word_that_only_starts_with_a_digit_is_not_trimmed(self):
        # "8va Piano": an over-eager rule would cut it to "va Piano".
        assert extract._clean_cell(["9", "_", "8va", "Piano"]) == "8va Piano"

    def test_an_index_welded_to_a_marker_comes_off(self):
        assert extract._clean_cell(["16*silentprog*"]) == "silentprog"

    def test_a_marker_only_cell_is_empty(self):
        assert extract._clean_cell(["_"]) == ""
        assert extract._clean_cell([]) == ""

    def test_a_long_name_is_cut_to_ten(self):
        assert extract._clean_cell(["ABCDEFGHIJKLMNO"]) == "ABCDEFGHIJ"


class TestPageSpec:
    def test_a_range(self):
        assert extract._pages("30-33") == (30, 33)

    def test_a_single_page(self):
        assert extract._pages("30") == (30, 30)
