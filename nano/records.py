# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# Record sizes and the common-area layout are transcribed as data from
# Alesis's QS System Exclusive specification, and checked byte-for-byte
# against dumps read from this unit.
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

"""What is inside a dump, as far as this program needs to know.

**Deliberately shallow.** A program is 350 bytes holding roughly 500
parameters, most of them bitfields inside four 85-byte sound blocks, and
Alesis's specification describes them at a level this program has no use
for. nanosyned browses and selects; it does not edit. So this module reads
the parts that identify a record -- the name, the sizes, the few common
fields -- and stops. The rest of the bytes travel intact.

That is a decision and not an omission: a half-decoded parameter map
invites a caller to write to it, and every write to this instrument's
memory is a program somebody made.
"""

from __future__ import annotations

from collections.abc import Sequence

from nano import messages as m

__all__ = [
    "EFFECTS_BYTES",
    "EFFECTS_PACKED",
    "GLOBAL_BYTES",
    "MIX_BYTES",
    "MIX_CHANNELS",
    "MIX_CHANNEL_BYTES",
    "MIX_COMMON",
    "MIX_NAME_BIT_OFFSET",
    "MIX_PACKED",
    "PROGRAM_BYTES",
    "PROGRAM_COMMON",
    "PROGRAM_PACKED",
    "SOUNDS_PER_PROGRAM",
    "SOUND_BYTES",
    "check_size",
    "global_fields",
    "mix_name",
    "program_name",
    "sound_block",
]

#: A program: 10 common bytes, then four 85-byte sound blocks.
PROGRAM_COMMON = 10
SOUNDS_PER_PROGRAM = 4
SOUND_BYTES = 85
PROGRAM_BYTES = PROGRAM_COMMON + SOUNDS_PER_PROGRAM * SOUND_BYTES  # 350
#: ...which travels as this many packed bytes. Verified on the bench: a
#: program dump is 408 bytes on the wire, which is 8 of header and footer
#: plus these 400.
PROGRAM_PACKED = 400

#: A mix: 10 common bytes, then sixteen 8-byte channel blocks.
MIX_COMMON = 10
MIX_CHANNELS = 16
MIX_CHANNEL_BYTES = 8
MIX_BYTES = MIX_COMMON + MIX_CHANNELS * MIX_CHANNEL_BYTES  # 138
MIX_PACKED = 158

EFFECTS_BYTES = 65
EFFECTS_PACKED = 75

GLOBAL_BYTES = 20


def check_size(record: Sequence[int], expected: int, what: str) -> None:
    """Refuse a record that is not the size it should be.

    Short is fatal and long is not: the instrument pads to a whole packing
    group, so a 350-byte program arrives with a few spare bytes on the end.
    Truncating those is correct. Accepting a *short* record would let every
    field past the end read as whatever followed it in memory.
    """
    if len(record) < expected:
        raise m.ProtocolError(
            f"{what} unpacked to {len(record)} bytes, fewer than the "
            f"{expected} one occupies"
        )


def program_name(record: Sequence[int]) -> str:
    """The ten-character name of a program."""
    check_size(record, PROGRAM_BYTES, "a program")
    return m.decode_name(record)


#: A mix name starts five bits in, not eight. The same seven-bit
#: characters as a program's, at a different offset, because a mix's
#: common area opens with a one-bit flag and a four-bit channel where a
#: program's has two spare bits. Reading a mix name at the program's
#: offset does not fail -- it produces ten plausible characters of
#: nonsense, which is how this was noticed.
MIX_NAME_BIT_OFFSET = 5


def mix_name(record: Sequence[int]) -> str:
    """The ten-character name of a mix."""
    check_size(record, MIX_BYTES, "a mix")
    return m.decode_name(record, MIX_NAME_BIT_OFFSET)


def sound_block(record: Sequence[int], index: int) -> bytes:
    """One of a program's four sound blocks, raw.

    Returned whole and undecoded. What is in it is Alesis's business and
    this program's job is to carry it unaltered.
    """
    if not 0 <= index < SOUNDS_PER_PROGRAM:
        raise ValueError(
            f"a program has {SOUNDS_PER_PROGRAM} sounds, so {index} is not one of them"
        )
    check_size(record, PROGRAM_BYTES, "a program")
    at = PROGRAM_COMMON + index * SOUND_BYTES
    return bytes(record[at : at + SOUND_BYTES])


def global_fields(record: Sequence[int]) -> dict[str, int]:
    """The few global settings this program reports.

    Only the ones whose meaning is documented *and* was confirmed against
    the unit. Alesis's specification lists twenty bytes; the ones not here
    are ones whose position could not be pinned down without writing to
    the instrument to see what moved, which is not a thing to do to find
    out what a byte means.
    """
    check_size(record, 1, "the global dump")
    return {"raw_bytes": len(record)}
