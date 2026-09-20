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

"""Build the name catalog from your own copies of Alesis's material.

**The catalog it writes is gitignored and stays that way.** Alesis's
program names are Alesis's work; this project does not redistribute them.
The tool reads sources you already own -- a ``.syx`` dump you made from
your own unit, or the program list in the Reference Manual -- and writes
``nano/data/catalog.json`` locally. nanosyned runs without it, showing
numbers and whatever the instrument tells it.

Two sources, and they are not equally good:

``--syx`` reads a dump. It can only ever fill the **User** bank, because
that is the only bank the protocol dumps, and it is the authoritative
source for that bank: the names come from the instrument itself.

``--manual`` reads a text file you have made from the manual's program
list. That is the only way to get names for the General MIDI bank and the
three preset banks, and it is exactly as good as your transcription.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import banks                                        # noqa: E402
from nano import dumps                                        # noqa: E402

DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "nano", "data", "catalog.json")

#: A manual line: a bank id, a number and a name.
#:    USER 000 Some Name
#:    P1   12  Another
LINE = re.compile(r"^\s*([A-Za-z0-9]+)\s+(\d{1,3})\s+(.+?)\s*$")


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
        for lineno, line in enumerate(handle, 1):
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
        print(f"{path}: {bad} line(s) did not parse and were skipped",
              file=sys.stderr)
    return rows, os.path.basename(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--syx", action="append", default=[],
                        help="a .syx dump; fills the User bank")
    parser.add_argument("--manual", action="append", default=[],
                        help="a transcribed list; fills any bank")
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    if not args.syx and not args.manual:
        parser.error("give at least one --syx or --manual source")

    rows = {}
    sources = []
    # Manual first, dumps second: a name read from the instrument beats a
    # name transcribed from a page, and should win where they overlap.
    for path in args.manual:
        found, label = from_manual(path)
        rows.update(found)
        sources.append(label)
    for path in args.syx:
        found, label = from_syx(path)
        rows.update(found)
        sources.append(label)

    payload = {"banks": {}, "source": "; ".join(sources),
               "generated": __import__("datetime").date.today().isoformat()}
    for (bank_id, number), name in sorted(rows.items()):
        payload["banks"].setdefault(bank_id, []).append(
            {"pc": number, "name": name})

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=1, ensure_ascii=False)
        handle.write("\n")

    per_bank = ", ".join(f"{k} {len(v)}"
                         for k, v in sorted(payload["banks"].items()))
    print(f"wrote {len(rows)} name(s) to {args.output}")
    print(f"  {per_bank}")
    print("\nThis file is gitignored. Alesis's names are not this "
          "project's to redistribute.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
