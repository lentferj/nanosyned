# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The bank layout is transcribed as data from Alesis's NanoSynth Reference
# Manual, pages 22-23 and 43-45, and checked against the unit.
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

"""The 640 programs, and which of them you can actually get at.

Five banks of 128. Two of them -- General MIDI and User -- are reachable
from the front panel; the other three are reachable only over MIDI, which
the manual says plainly and which is the single best reason for a program
like this one to exist.

**Only the User bank can be read back.** The protocol's program dump
request covers the 128 user programs and nothing else; the General MIDI
bank and the three preset banks are ROM and have no request. So this
program knows the *names* in those banks only from a catalog generated
from the manual, and knows the User bank's names from the instrument
itself. Those are different kinds of knowledge and the browser marks
which is which.

**Bank Select is Controller 0 and only Controller 0.** The manual is
explicit that the unit ignores Controller 32. Many sequencers send 32.
That is not an inconsistency to paper over with a helper that sends both.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "BANKS",
    "CATEGORIES",
    "CATEGORY_SIZE",
    "MIXES",
    "PROGRAMS_PER_BANK",
    "TOTAL_PROGRAMS",
    "Bank",
    "Slot",
    "bank",
    "bank_ids",
    "banks",
    "front_panel_banks",
    "lookup",
    "readable_banks",
    "slot",
    "slots",
]

#: Every bank holds this many, and MIDI program numbers run 0-127, which is
#: the whole reason the banks exist.
PROGRAMS_PER_BANK = 128

#: 100 user mixes. The manual never mentions them; the unit answers for
#: them. See docs/RESOLUTION_NOTES.md.
MIXES = 100


@dataclass(frozen=True)
class Bank:
    """One bank of 128 programs."""

    id: str
    label: str
    #: The Controller 0 value that selects it.
    select: int
    #: Whether the unit will dump these programs. Only the user bank will.
    readable: bool
    #: Whether the front panel can reach it at all.
    front_panel: bool
    note: str = ""

    @property
    def count(self) -> int:
        return PROGRAMS_PER_BANK


@dataclass(frozen=True)
class Slot:
    """One program in one bank.

    ``number`` and ``program_change`` are the same here, and are still kept
    apart. This instrument happens to count programs from 0 exactly as MIDI
    does -- the manual's own examples say "Bank 0, Program 33" -- so no
    conversion is needed. The sibling rxved's instrument does not, and a
    helper that quietly converted was a real bug there. Keeping both names
    costs a line and means no caller has to remember which machine it is
    talking to.
    """

    bank: Bank
    number: int
    program_change: int

    @property
    def bank_id(self) -> str:
        return self.bank.id

    @property
    def key(self) -> str:
        return f"{self.bank.id}:{self.number:03d}"

    @property
    def display(self) -> str:
        return f"{self.bank.label} {self.number:03d}"

    @property
    def category(self) -> str:
        """Which of the sixteen front-panel categories this falls in.

        Only meaningful for the two front-panel banks: the CATEGORY knob
        selects a group of sixteen, eight from General MIDI and eight from
        User. For the preset banks the grouping has no panel behind it, so
        it is reported as a grouping and not as a knob position.
        """
        return CATEGORIES[self.number // CATEGORY_SIZE]


#: The sixteen categories on the front panel, in knob order, from the
#: manual page 43. General MIDI orders its sounds in groups of eight and
#: the panel follows it.
CATEGORIES: tuple[str, ...] = (
    "Piano",
    "Chromatic",
    "Organ",
    "Guitar",
    "Bass",
    "Strings",
    "Ensemble",
    "Brass",
    "Reed",
    "Pipe",
    "Synth Lead",
    "Synth Pad",
    "Synth FX",
    "Ethnic",
    "Drums/Percussion",
    "Effects",
)

CATEGORY_SIZE = PROGRAMS_PER_BANK // len(CATEGORIES)  # 8

#: The five banks, in Bank Select order.
#:
#: The manual contradicts itself once, and it is worth recording which way
#: it was resolved. The heading on page 22 says the MIDI-only banks are
#: "1, 2, AND 3"; the body of the same section, page 23, says "you can't
#: call up a program in Banks 2, 3, or 4", and page 43 says General MIDI is
#: Bank Select 0, User is 1, "and Banks 2, 3, and 4 are selected using Bank
#: Select commands with values of 2, 3, and 4 (respectively)". Two places
#: against one, and the two agree with the arithmetic: 640 programs less
#: the 256 on the front panel leaves 384, which is three banks. The heading
#: is the error.
BANKS: tuple[Bank, ...] = (
    Bank(
        "GM",
        "General MIDI",
        0,
        readable=False,
        front_panel=True,
        note="ROM. The General MIDI set, in GM order.",
    ),
    Bank(
        "USER",
        "User",
        1,
        readable=True,
        front_panel=True,
        note="The 128 programs the unit will dump. Program 127 is the "
        "silent one and cannot be changed.",
    ),
    Bank(
        "P1",
        "Preset 1",
        2,
        readable=False,
        front_panel=False,
        note="ROM, and reachable only over MIDI.",
    ),
    Bank(
        "P2",
        "Preset 2",
        3,
        readable=False,
        front_panel=False,
        note="ROM, and reachable only over MIDI.",
    ),
    Bank(
        "P3",
        "Preset 3",
        4,
        readable=False,
        front_panel=False,
        note="ROM, and reachable only over MIDI.",
    ),
)

TOTAL_PROGRAMS = len(BANKS) * PROGRAMS_PER_BANK  # 640

_BY_ID: dict[str, Bank] = {b.id: b for b in BANKS}
_BY_SELECT: dict[int, Bank] = {b.select: b for b in BANKS}

#: The one program that is hardwired silent. The manual: "User bank Program
#: 127 has been hardwired permanently into the NanoSynth. It cannot be
#: deleted, edited, overwritten, or changed." The unit calls it "Off", which
#: this program found by reading it rather than by being told.
SILENT_PROGRAM = ("USER", 127)


def bank(bank_id: str) -> Bank:
    """One bank by id, or :class:`LookupError`."""
    try:
        return _BY_ID[bank_id]
    except KeyError:
        raise LookupError(
            f"no bank {bank_id!r}; have {', '.join(b.id for b in BANKS)}"
        ) from None


def banks() -> tuple[Bank, ...]:
    return BANKS


def bank_ids() -> list[str]:
    return [b.id for b in BANKS]


def by_select(value: int) -> Bank:
    """The bank a Controller 0 value selects."""
    try:
        return _BY_SELECT[value]
    except KeyError:
        raise LookupError(
            f"no bank answers Bank Select {value}; this unit has "
            f"{', '.join(str(b.select) for b in BANKS)}"
        ) from None


def readable_banks() -> list[Bank]:
    """The banks the unit will dump. There is one."""
    return [b for b in BANKS if b.readable]


def front_panel_banks() -> list[Bank]:
    return [b for b in BANKS if b.front_panel]


def slots(bank_id: str) -> list[Slot]:
    entry = bank(bank_id)
    return [Slot(entry, n, n) for n in range(PROGRAMS_PER_BANK)]


def slot(bank_id: str, number: int) -> Slot:
    entry = bank(bank_id)
    if not 0 <= number < PROGRAMS_PER_BANK:
        raise LookupError(
            f"{entry.label} has {PROGRAMS_PER_BANK} programs, so {number} "
            f"is not one of them"
        )
    return Slot(entry, number, number)


def lookup(select: int, program: int) -> Slot | None:
    """What a Bank Select and Program Change together address."""
    try:
        entry = by_select(select)
    except LookupError:
        return None
    if not 0 <= program < PROGRAMS_PER_BANK:
        return None
    return Slot(entry, program, program)
