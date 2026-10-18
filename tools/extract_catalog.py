#!/usr/bin/env python3
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

"""Build the name catalog from your own copies of Alesis's material.

**The catalog it writes is gitignored and stays that way.** Alesis's
program names are Alesis's work; this project does not redistribute them.
The tool reads sources you already own -- a ``.syx`` dump you made from
your own unit, the Reference Manual's program list, or your own
transcription -- and writes ``nano/data/catalog.json`` locally. nanosyned
runs without it, showing numbers and whatever the instrument tells it.

Three sources, and they are not equally good:

``--syx`` reads a dump. It can only ever fill the **User** bank, because
that is the only bank the protocol dumps, and it is the authoritative
source for that bank: the names come from the instrument itself.

``--pdf`` reads the program list straight out of the Reference Manual --
``Alesis Nanosynth Reference Manual.PDF``, whose program list runs on
**pages 30-33**. Those pages' fonts are subsetted with no ToUnicode map,
so the text layer is mojibake; the pages are rendered to images and read
by OCR instead. That needs ``pdftoppm`` (poppler-utils) and ``tesseract``
on ``PATH``. **The names it produces are OCR and contain errors** -- they
are a first draft, not an authority. ``--draft FILE`` writes them as a
``BANK NNN Name`` transcription to proofread and feed back through
``--manual``.

``--manual`` reads a text file you have made from the manual's program
list. That is the only way to get *verified* names for the General MIDI
bank and the three preset banks, and it is exactly as good as your
transcription.
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import (
    banks,
    dumps,
)
from nano.catalog import (
    Catalog,
    Entry,
    dump,
)

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "nano",
    "data",
    "catalog.json",
)

#: A name is ten characters on this instrument -- see ``nano.messages``.
NAME_CHARS = 10

#: The Reference Manual's program list, by default. ``--pdf`` with no path
#: looks here (and honours ``NANOSYNED_MANUAL``), so the common case is one
#: flag and no path on the command line.
MANUAL_NAME = "Alesis Nanosynth Reference Manual.PDF"
MANUAL_CANDIDATES = (
    os.path.join(
        os.path.expanduser("~"),
        "Seafile",
        "Bibliothek",
        "Handbücher",
        "Audio-Daws_and_Plugins",
        "Synthesizer",
        MANUAL_NAME,
    ),
    os.path.join(
        os.path.expanduser("~"), "Dokumente", "SYNTHS", "Nanosynth", MANUAL_NAME
    ),
    os.path.join(os.path.expanduser("~"), "Downloads", MANUAL_NAME),
)

#: The program-list pages, and the resolution the column geometry below was
#: measured at. The manual's layout is fixed, so a fixed set of x-windows
#: reads the same columns on every one of the four pages.
PAGES_DEFAULT = "30-33"
DPI_DEFAULT = 300

#: One bank column each, as ``(bank_id, left, right)`` in pixels **at 300
#: dpi**. The manual's five bank columns are ``GM Bank(0)``, ``User Bank(1)``
#: and the three MIDI-only banks, whose controller-0 values are 2, 3 and 4.
#: This project calls those ``P1``, ``P2`` and ``P3``; the manual numbers
#: them by their bank-select value, which is the one mismatch that matters
#: and is resolved here by reading the columns left to right.
#:
#: The windows are boundaries between columns, not the names' own extents:
#: each column prints its own index number first and its name a little to
#: the right, and a name may run into the gap before the next boundary.
#: The boundaries sit in the blank gaps *between* a column's last name and
#: the next column's index number -- not on the header labels, which are a
#: pixel or two from the next column's index and would let that index bleed
#: into the cell before it (P1 004 read "Suitcase 4" when they did).
_COLUMNS_300DPI = (
    ("GM", 360, 676),
    ("USER", 676, 1000),
    ("P1", 1000, 1400),
    ("P2", 1400, 1850),
    ("P3", 1850, 2600),
)

#: A manual line: a bank id, a number and a name.
#:    USER 000 Some Name
#:    P1   12  Another
#: The name must begin with a non-space character. ``\s+`` before the group
#: is greedy, so without the ``\S`` a line whose name is only whitespace --
#: "USER 000   " -- leaves one space for the group and parses as a name.
LINE = re.compile(r"^\s*([A-Za-z0-9]+)\s+(\d{1,3})\s+(\S.*?)\s*$")

#: A leading bank-index number, optionally welded to a marker glyph. The
#: manual prints the bank's own program number before each name; the marker
#: is an OCR artefact of the dot or dash the page uses. The lookahead is
#: load-bearing: it must be a *separate* number, so "8va Piano" -- a real
#: User-bank name -- is not mistaken for an index and cut to "va Piano".
_LEADING_INDEX = re.compile(r"^\d{1,3}(?=\s|[*_\u2014\u2013-])[*_\u2014\u2013-]*\s*")

#: Marker glyphs the program list prints around some names: the em and en
#: dashes the page uses, a hyphen, an underscore and a star, in the forms
#: OCR returns them.
_MARKERS = " *_\u2014\u2013-"


def from_syx(path):
    """The User bank, from a dump. Authoritative for that bank only."""
    library = dumps.read_syx_file(path)
    rows = {}
    for number, name in library.program_names().items():
        text = name.rstrip()
        if text:
            rows[("USER", number)] = text
    return rows, f"{os.path.basename(path)} ({library.summary()})"


def from_manual(path):
    """Every bank, from a list you transcribed."""
    rows = {}
    bad = 0
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            found = LINE.match(line)
            if not found:
                bad += 1
                continue
            bank_id, number, name = found.groups()
            bank_id = bank_id.upper()
            try:
                banks.bank(bank_id)
            except LookupError:
                bad += 1
                continue
            number = int(number)
            if not 0 <= number < banks.PROGRAMS_PER_BANK:
                bad += 1
                continue
            rows[(bank_id, number)] = name
    if bad:
        print(f"{path}: {bad} line(s) did not parse and were skipped", file=sys.stderr)
    return rows, os.path.basename(path)


# --- the manual PDF, by OCR ----------------------------------------------


def _column_of(left: int, scale: float) -> str | None:
    """The bank a word at ``left`` pixels belongs to, or ``None``.

    ``None`` for the program-change and ``Prog#`` columns, which are not a
    bank and are read from the row prefix instead.
    """
    for bank_id, lo, hi in _COLUMNS_300DPI:
        if lo * scale <= left < hi * scale:
            return bank_id
    return None


def _clean_cell(tokens: list[str]) -> str:
    """One bank cell's words as a name, with the page's trim removed.

    The manual prints a bank index number before most names and marks a
    couple with a dot or dash; OCR also drops the odd stray glyph. One
    leading index is removed -- one, because a real name may itself begin
    with a number ("61 Tines") and only the printed index is spurious.
    """
    if not tokens:
        return ""
    text = " ".join(tokens).strip()
    text = _LEADING_INDEX.sub("", text, count=1)
    text = text.strip(_MARKERS)
    text = re.sub(r"\s+", " ", text)
    return text[:NAME_CHARS]


def _words_by_line(text: str) -> dict[tuple[str, ...], list[tuple[int, str]]]:
    """Group a TSV page's words by their line, as ``(left, word)`` pairs."""
    lines: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    reader = csv.DictReader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        word = (row.get("text") or "").strip()
        if not word:
            continue
        try:
            left = int(row.get("left", "0"))
        except ValueError:
            continue
        key = (
            row.get("page_num", ""),
            row.get("block_num", ""),
            row.get("par_num", ""),
            row.get("line_num", ""),
        )
        lines.setdefault(key, []).append((left, word))
    return lines


def _row_cells(words: list[tuple[int, str]], scale: float) -> dict[str, list[str]]:
    """The words of one row, bucketed into the five bank columns by x."""
    cells: dict[str, list[str]] = {bank_id: [] for bank_id, _, _ in _COLUMNS_300DPI}
    for left, word in words:
        bank_id = _column_of(left, scale)
        if bank_id is not None:
            cells[bank_id].append(word)
    return cells


def _sorted_lines(text: str) -> list[list[tuple[int, str]]]:
    """Every line's words, each sorted left to right, in reading order."""
    grouped = _words_by_line(text)
    return [sorted(grouped[key]) for key in sorted(grouped) if grouped[key]]


def parse_tsv(text: str, scale: float = 1.0) -> dict[tuple[str, int], str]:
    """Every ``(bank, number) -> name`` a page's tesseract TSV holds.

    Pure: it takes the TSV text, so the parsing is testable without OCR.
    A data row is one whose first word is a three-digit program change near
    the left edge; a category heading ("Piano"), the page header and the
    footer are not. Words are assigned to a bank column by x, then the
    column's words are joined and trimmed by :func:`_clean_cell`.
    """
    rows: dict[tuple[str, int], str] = {}
    for words in _sorted_lines(text):
        first = words[0][1]
        if not re.fullmatch(r"\d{3}", first):
            continue
        number = int(first)
        if not 0 <= number < banks.PROGRAMS_PER_BANK:
            continue
        for bank_id, tokens in _row_cells(words, scale).items():
            name = _clean_cell(tokens)
            if name:
                rows[(bank_id, number)] = name
    return rows


def _tesseract() -> str:
    """The tesseract binary, or a refusal naming how to point at one."""
    found = os.environ.get("NANOSYNED_TESSERACT") or shutil.which("tesseract")
    if not found:
        raise SystemExit(
            "error: --pdf needs tesseract on PATH (install it, or set "
            "NANOSYNED_TESSERACT to the binary)"
        )
    return found


def _pages(spec: str) -> tuple[int, int]:
    """``"30-33"`` as ``(30, 33)``; a single number means one page."""
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return int(lo), int(hi)
    return int(spec), int(spec)


def from_pdf(path: str, pages: str = PAGES_DEFAULT, dpi: int = DPI_DEFAULT):
    """Every bank, from the manual's program list, read by OCR.

    The names are OCR: expect errors, and proofread. ``--draft`` writes the
    same rows as a transcription to correct.
    """
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise SystemExit(
            "error: --pdf needs pdftoppm on PATH (the poppler-utils package)"
        )
    tesseract = _tesseract()
    if not os.path.exists(path):
        raise SystemExit(f"error: no manual at {path!r}")
    lo, hi = _pages(pages)
    scale = dpi / DPI_DEFAULT
    rows: dict[tuple[str, int], str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(  # noqa: S603
            [
                pdftoppm,
                "-r",
                str(dpi),
                "-gray",
                "-png",
                "-f",
                str(lo),
                "-l",
                str(hi),
                path,
                os.path.join(tmp, "page"),
            ],
            check=True,
        )
        images = sorted(glob.glob(os.path.join(tmp, "page-*.png")))
        if not images:
            raise SystemExit(
                f"error: pdftoppm produced no pages for {path!r} pages {pages}"
            )
        for image in images:
            result = subprocess.run(  # noqa: S603
                [tesseract, image, "stdout", "-l", "eng", "--psm", "6", "tsv"],
                check=True,
                capture_output=True,
                text=True,
            )
            rows.update(parse_tsv(result.stdout, scale=scale))
    label = f"{os.path.basename(path)} (pages {pages}, OCR)"
    return rows, label


def write_draft(path: str, rows: dict[tuple[str, int], str]) -> None:
    """Write the OCR rows as a ``BANK NNN Name`` list to proofread.

    The same grammar ``--manual`` reads, so a corrected draft is one flag
    away from being the verified source.
    """
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(
            "# OCR draft of the NanoSynth Reference Manual's program list,\n"
            "# pages " + PAGES_DEFAULT + ".\n"
            "#\n"
            "# Every line is BANK NNN Name. The names are OCR and contain\n"
            "# errors: fix them here, then rebuild with\n"
            "#     tools/extract_catalog.py --manual <this file> --syx <dump>\n"
            "# A .syx dump wins over this file for the User bank.\n"
        )
        for (bank_id, number), name in sorted(rows.items()):
            handle.write(f"{bank_id} {number:03d} {name}\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--syx", action="append", default=[], help="a .syx dump; fills the User bank"
    )
    parser.add_argument(
        "--manual",
        action="append",
        default=[],
        help="a transcribed list; fills any bank",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        nargs="?",
        const="",
        default=[],
        metavar="PATH",
        help=(
            "the Reference Manual PDF; OCRs its program list (default: "
            f"{MANUAL_NAME}, pages {PAGES_DEFAULT})"
        ),
    )
    parser.add_argument(
        "--pages",
        default=PAGES_DEFAULT,
        help=f"the program-list pages to OCR (default: {PAGES_DEFAULT})",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=DPI_DEFAULT,
        help=f"render resolution for OCR (default: {DPI_DEFAULT})",
    )
    parser.add_argument(
        "--draft",
        metavar="FILE",
        help="write the OCR names as a BANK NNN Name list to proofread",
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.syx and not args.manual and not args.pdf:
        parser.error("give at least one --syx, --pdf or --manual source")

    rows = {}
    sources = []
    # Transcriptions and OCR first, dumps second: a name read from the
    # instrument beats a name read off a page, and should win where they
    # overlap (the User bank).
    for path in args.manual:
        found, label = from_manual(path)
        rows.update(found)
        sources.append(label)
    for given in args.pdf:
        resolved = given
        if not resolved:
            resolved = os.environ.get("NANOSYNED_MANUAL") or next(
                (p for p in MANUAL_CANDIDATES if os.path.exists(p)),
                MANUAL_CANDIDATES[0],
            )
        found, label = from_pdf(resolved, pages=args.pages, dpi=args.dpi)
        rows.update(found)
        sources.append(label)
    for path in args.syx:
        found, label = from_syx(path)
        rows.update(found)
        sources.append(label)

    if args.draft:
        write_draft(args.draft, rows)
        print(f"wrote an OCR draft to {args.draft} -- proofread it")

    payload_rows = [
        Entry(bank_id=bank_id, number=number, name=name)
        for (bank_id, number), name in sorted(rows.items())
    ]
    # The generated file is the browser's default catalog, on formats the
    # row grammar inherited from the binding: rows carry the display
    # number in "n", which on this instrument is the program change, both
    # 0-based, so no "pc" row is ever written -- a "pc" row would come
    # back one higher.
    catalog = Catalog(
        payload_rows,
        source="; ".join(sources),
        generated=__import__("datetime").date.today().isoformat(),
    )
    dump(catalog, args.output)

    counts: dict[str, int] = {}
    for entry in payload_rows:
        counts[entry.bank_id] = counts.get(entry.bank_id, 0) + 1
    per_bank = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
    print(f"wrote {len(rows)} name(s) to {args.output}")
    print(f"  {per_bank}")
    print(
        "\nThis file is gitignored. Alesis's names are not this "
        "project's to redistribute."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
