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

"""Preset names, and where each one came from.

Two sources, kept apart all the way to the screen:

* **Printed** names, transcribed from the program lists in the NanoSynth Reference
  Manual. Generated locally into
  ``nano/data/catalog.json``, which is gitignored -- those names are
  Alesis's and are not redistributed here.
* **Live** names, read from a unit over System Exclusive.

A single mapping cannot keep them distinguishable, and the distinction is
the useful part: a user slot whose live name differs from the printed one
is one somebody has saved their own work into, and that is the single
most informative thing this program can put on a screen.

**Four of this instrument's five banks can only come from a catalog.**
The protocol has a dump request for the 128 user programs and for
nothing else; General MIDI and the three preset banks are ROM. So most
of what the browser shows is printed names and one fifth is the
instrument's own, which is exactly why the two are kept apart and marked
differently.

**The storage layer is vinsynlib's now.** Keys, rows, splitting, dumping
and the printed-versus-live separation live in
:mod:`vinsynlib.catalog`; this module binds it to the instrument.
That grammar keys on the **display** number, which on this instrument is
the same as the program change -- the CLI prints 000..127 and both
count 000..127 -- so no offset arithmetic happens anywhere in it.

Nothing in this module plays anything. Reading names is silent on this
instrument whichever way it is done.
"""

from __future__ import annotations

import json
import os
import sys

from vinsynlib.catalog import (
    UNNAMED,
    Entry,
    display_to_wire,
    dump,
    make_key,
    split_key,
    wire_to_display,
)
from vinsynlib.catalog import (
    Catalog as _Catalog,
)

__all__ = [
    "DEFAULT_PATH",
    "UNNAMED",
    "Catalog",
    "Entry",
    "display_to_wire",
    "dump",
    "empty",
    "load",
    "make_key",
    "split_key",
    "wire_to_display",
]

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "catalog.json"
)


class Catalog(_Catalog):
    """Printed names, plus whatever has been read from a unit.

    A thin binding over :class:`vinsynlib.catalog.Catalog`, keeping the
    one project-specific name semantics: in a writable bank a
    disagreement means somebody's work is on the machine, and in a ROM
    one it means the printed list is wrong. The library reports only
    that the two differ; which of those is true on this instrument is
    what :meth:`disagreement` is here for.
    """

    def disagreement(self, bank_id: str, number: int, writable: bool) -> str | None:
        """Why the unit and the catalog differ here, in words.

        ``writable`` controls the wording: a writable bank that differs
        means somebody saved their own work over the factory preset;
        otherwise the printed list is wrong, and the unit is right.
        ``None`` when they agree or the slot has not been read.
        """
        if not self.differs(bank_id, number):
            return None
        if writable:
            return "saved over the factory preset"
        return "the printed list is wrong; the unit is right"


def empty() -> Catalog:
    """A catalog that knows no names. What you get with no data file."""
    return Catalog()


def _row_number(row: dict) -> int:
    """The 0-based slot number from a generated row, in either grammar.

    This instrument counts from zero exactly as MIDI does, so the display
    number and the program change are one number and neither carries an
    offset. A row may hold it as ``"n"`` (what the current extractor writes)
    or the older ``"pc"`` (the wire number); they are the same integer here,
    which is why :func:`vinsynlib.catalog.load` must **not** be used to read
    this file: it adds one to a ``"pc"`` row, right for a tool whose first
    patch is number 1, and on this unit that would shift every catalog
    written before the grammar changed by one slot -- silently, which is the
    failure mode the whole module is written against.
    """
    if "n" in row:
        return int(row["n"])
    return int(row["pc"])


def _entry_of(bank_id: str, row: object) -> Entry:
    """One generated row as an :class:`Entry`, or raise for a bad one."""
    if not isinstance(row, dict):
        raise TypeError("row is not a dict")
    name = row["name"]
    kind = row.get("kind", "")
    if not isinstance(name, str) or not isinstance(kind, str):
        raise TypeError("name or kind is not a string")
    return Entry(bank_id=bank_id, number=_row_number(row), name=name, kind=kind)


def _entries_from_banks(banks: dict, target: str) -> list[Entry]:
    """Every readable row, with the unreadable ones counted to stderr."""
    entries: list[Entry] = []
    skipped = 0
    for bank_id, rows in banks.items():
        if not isinstance(rows, list):
            skipped += 1
            continue
        for row in rows:
            try:
                entries.append(_entry_of(bank_id, row))
            except (KeyError, TypeError, ValueError):
                skipped += 1
    if skipped:
        print(
            f"warning: {target} has {skipped} unreadable row(s), skipped; "
            f"regenerate it with tools/extract_catalog.py",
            file=sys.stderr,
        )
    return entries


def load(path: str | None = None) -> Catalog:
    """Load the generated catalog, or an empty one.

    A missing catalog is normal and not an error: nanosyned works without it,
    showing numbers only, and a connected unit can supply every name itself.
    A file that cannot be read as a catalog is a warning and an empty
    catalog, not a refusal to start -- names are a convenience, and the user
    is told rather than left with "numbers only" and no reason. One bad row
    costs one row, not the file.
    """
    target = path or DEFAULT_PATH
    if not os.path.exists(target):
        return empty()
    try:
        with open(target, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"warning: {target} could not be read as a catalog ({exc}); "
            f"showing numbers only",
            file=sys.stderr,
        )
        return empty()
    banks = payload.get("banks", {}) if isinstance(payload, dict) else None
    if not isinstance(banks, dict):
        print(
            f"warning: {target} is not a catalog; showing numbers only",
            file=sys.stderr,
        )
        return empty()
    source = payload.get("source", "")
    generated = payload.get("generated", "")
    return Catalog(
        _entries_from_banks(banks, target),
        source=source if isinstance(source, str) else "",
        generated=generated if isinstance(generated, str) else "",
    )
