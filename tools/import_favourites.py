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
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""Import favourites from a marked-up listing into the favourites database.

The listing is the format the family's paper-and-highlighter workflow leaves
behind: a bank header naming the bank in brackets, then one line per
favourite. Two entry spellings are read, because the two siblings that make
these listings disagree:

    [USER]
    PC 4  Amber Shine
    7     Glass Meridian

``PC nnn name`` is p2ked's grammar, and is what its importer has always
written. The shorter ``nnn name`` is what a marked list reads like when the
number is the only thing on the line. Both mean the same thing here: the
number is the **program change**, which on this instrument is also the
number the browser displays, so it is 0-127 and no conversion happens.

**A faint mark is not a decision.** A line ending in ``<--`` marks a mark the
scan was less than sure about. It is imported, because the user can see and
correct it, but it carries the ``check-scan`` tag so a later pass knows which
rows to look at again. ``--skip-uncertain`` leaves those rows out instead. A
line whose name is empty -- what a truncated scan looks like -- is treated
the same way and tagged rather than imported as a deliberately anonymous
favourite.

**Existing favourites are left alone unless ``--replace`` is given**, and
even then only the banks the listing mentions are cleared: a listing that
covers the User bank must not delete favourites in the preset banks. A row
already favourited is skipped, annotations and all, so re-running an
unchanged listing is harmless.

Nothing here reads a scan or opens a MIDI port. Turning marks on paper into
this listing is a separate job; this only loads what that produced.

    python3 tools/import_favourites.py Favourites.txt
    python3 tools/import_favourites.py --dry-run Favourites.txt
    python3 tools/import_favourites.py --replace --skip-uncertain - < list.txt

**The names are the user's own**, and possibly Alesis's. They are never part
of this repository: no listing or fixture containing real program names is
committed, and the tests use invented ones.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import banks
from nano import favorites as fav

#: A bank header anywhere on a line: ``[USER]``, ``[P1]``, ``[General MIDI]``.
BANK = re.compile(r"\[([^\[\]]+)\]")

#: An entry: p2ked's ``PC nnn name`` or the shorter ``nnn name``. The name
#: may be empty, which is what a truncated scan leaves; the caller decides
#: what that means rather than the parser silently dropping the row.
ENTRY = re.compile(r"^\s*(?:PC\s+)?(\d{1,3})(?:\s+(.*?))?\s*$", re.IGNORECASE)

#: What a faint mark looks like, and the note after the name that it starts.
UNCERTAIN = "<--"
NOTE = re.compile(r"\s*<--.*$")

#: The tag a row carries when it needs a second look on the paper copy.
CHECK_TAG = "check-scan"

#: Bank spellings accepted in a header, mapped to the ids the store uses.
#: The labels are here because a listing typed from the front panel is as
#: likely to say "General MIDI" as "GM".
BANK_NAMES = {
    **{bank.id.lower(): bank.id for bank in banks.banks()},
    **{bank.label.lower(): bank.id for bank in banks.banks()},
}


def bank_id_of(text: str) -> str:
    """The canonical bank id for a header's text.

    A listing's header is written by a person, so its capitalisation is not
    evidence of anything; an unknown name is an error rather than a guess,
    because a favourite filed under the wrong bank is silently wrong.
    """
    key = " ".join(text.split()).lower()
    try:
        return BANK_NAMES[key]
    except KeyError:
        known = ", ".join(bank.id for bank in banks.banks())
        raise SystemExit(
            f"unknown bank [{text.strip()}]; this instrument has {known} "
            f"(or write the bank's label, e.g. [General MIDI])"
        ) from None


def parse(text: str, label: str = "<stdin>") -> list[tuple[str, int, str, bool]]:
    """``[(bank_id, program_change, name, uncertain)]`` from the listing.

    A header sets the bank for the lines that follow it; an entry before any
    header is a mistake, not a default, because defaulting would put rows in
    a bank the user did not name.
    """
    rows: list[tuple[str, int, str, bool]] = []
    bank: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        header = BANK.search(line)
        if header:
            bank = bank_id_of(header.group(1))
            continue
        found = ENTRY.match(line)
        if not found:
            continue
        if bank is None:
            raise SystemExit(
                f"{label}:{lineno}: an entry before any bank header. Each "
                f"bank's rows must follow a header naming it in brackets, "
                f"e.g. [USER]."
            )
        number = int(found.group(1))
        if not 0 <= number < banks.PROGRAMS_PER_BANK:
            raise SystemExit(
                f"{label}:{lineno}: program {number} is outside "
                f"0-{banks.PROGRAMS_PER_BANK - 1}"
            )
        rest = found.group(2) or ""
        uncertain = UNCERTAIN in rest
        rows.append((bank, number, NOTE.sub("", rest).strip(), uncertain))
    return rows


def read_listing(path: str) -> tuple[str, str]:
    """The listing text and a label for messages. ``-`` means stdin."""
    if path == "-":
        return sys.stdin.read(), "<stdin>"
    with open(path, encoding="utf-8") as handle:
        return handle.read(), path


def describe(
    rows: list[tuple[str, int, str, bool]], label: str, skipped: int
) -> list[str]:
    """The summary a person reads before the database is touched."""
    mentioned = sorted({row[0] for row in rows})
    faint = sum(1 for row in rows if row[3])
    lines = [
        f"{len(rows)} favourite(s) across {len(mentioned)} bank(s) "
        f"in {os.path.basename(label) if label != '<stdin>' else label}"
    ]
    if skipped:
        lines.append(f"  {skipped} flagged faint left out by --skip-uncertain")
    if faint:
        lines.append(f"  {faint} of them flagged faint in the listing")
    return lines


def tags_for(tag: str, uncertain: bool, name: str) -> tuple[str, bool]:
    """The tags one row carries, and whether it arrived without a name.

    A faint mark and a truncated line are two ways of saying "look at this
    again", so both carry :data:`CHECK_TAG`. A blank name is also counted,
    because the importer otherwise cannot tell it from a deliberately
    anonymous favourite.
    """
    if uncertain or not name:
        tag = ",".join(part for part in (tag, CHECK_TAG) if part)
    return tag, not name


def clear_banks(store: fav.Favorites, mentioned: list[str]) -> int:
    """Un-favourite every live row in the named banks. Returns the count."""
    removed = 0
    for bank in mentioned:
        for number in store.keys_for_bank(bank):
            if store.remove(bank, number):
                removed += 1
    return removed


def import_rows(
    args: argparse.Namespace,
    rows: list[tuple[str, int, str, bool]],
    path: str,
) -> int:
    """Write the rows, and say what changed. Returns a process status."""
    mentioned = sorted({row[0] for row in rows})
    added = skipped = removed = nameless = 0
    try:
        with fav.Favorites(path) as store:
            if args.replace:
                removed = clear_banks(store, mentioned)
            for bank, number, name, uncertain in rows:
                if store.get(bank, number) is not None:
                    skipped += 1
                    continue
                tags, blank = tags_for(args.tag, uncertain, name)
                nameless += blank
                store.add(bank, number, name=name, tags=tags)
                added += 1
            total = len(store)
    except (OSError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if removed:
        print(f"removed {removed} existing favourite(s) in those banks")
    print(f"added {added}, already present {skipped}")
    if nameless:
        print(
            f"{nameless} had no name on their line and are tagged {CHECK_TAG}; "
            f"a truncated scan looks like this"
        )
    print(f"{total} favourite(s) now in {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "the listing is a [BANK] header followed by one 'PC nnn name' or "
            "'nnn name' row per favourite; a row ending in '<--' is flagged "
            "faint and is tagged check-scan unless --skip-uncertain is given"
        ),
    )
    parser.add_argument(
        "listing",
        nargs="?",
        default="-",
        help="the marked-up listing; '-' or no argument reads standard input",
    )
    parser.add_argument(
        "--favorites",
        default=None,
        metavar="PATH",
        help="database path (default: the per-platform one)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="say what would be imported and write nothing",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="first clear existing favourites in the banks this file mentions",
    )
    parser.add_argument(
        "--tag", default="", metavar="TAG", help="tag every imported favourite"
    )
    parser.add_argument(
        "--skip-uncertain",
        action="store_true",
        help="leave out marks the listing flags as faint",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    text, label = read_listing(args.listing)
    rows = parse(text, label)
    skipped_uncertain = 0
    if args.skip_uncertain:
        skipped_uncertain = sum(1 for row in rows if row[3])
        rows = [row for row in rows if not row[3]]

    for line in describe(rows, label, skipped_uncertain):
        print(line)
    if not rows:
        print("nothing to import")
        return 0

    if args.dry_run:
        for bank in sorted({row[0] for row in rows}):
            numbers = [row[1] for row in rows if row[0] == bank]
            print(f"  {bank:14s} {len(numbers):3d}  {numbers}")
        print("dry run: nothing written")
        return 0

    path = args.favorites or fav.default_path()
    return import_rows(args, rows, path)


if __name__ == "__main__":
    raise SystemExit(main())
