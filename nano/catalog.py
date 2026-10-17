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

import os

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
from vinsynlib.catalog import (
    load as _load,
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


def load(path: str | None = None) -> Catalog:
    """Load the generated catalog, or an empty one.

    A missing catalog is normal and not an error: nanosyned works without it,
    showing numbers only, and a connected unit can supply every name itself.
    A file that exists but is not a catalog raises, because silently browsing
    unnamed slots would be a poor way to find out the extractor broke. One
    bad row costs one row, not the file: unreadable rows are counted to
    stderr and skipped.
    """
    # The library builds the base class; hand its state to the subclass so
    # the browser keeps disagreement() without a second copy of the layer.
    base = _load(path or DEFAULT_PATH)
    out = Catalog.__new__(Catalog)
    out.__dict__.update(base.__dict__)
    return out
