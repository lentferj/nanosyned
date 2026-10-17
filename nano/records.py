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
from typing import TYPE_CHECKING

from nano import messages as m

if TYPE_CHECKING:
    from nano.params import Param

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
    "decode_bit_field",
    "encode_bit_field",
    "global_fields",
    "global_record_bytes",
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


# --- parameters into records ------------------------------------------------
#
# Alesis prints a parameter's bit address as a range from its *most*
# significant bit to its *least* significant one, with the byte number first
# and bit 7 the most significant bit of a byte:
#
#     1:6-1:0     byte 1, bit 6 ... byte 1, bit 0     (7 bits)
#     2:2-1:4     byte 2, bit 2 ... byte 1, bit 4     (7 bits, crosses a byte)
#
# ``Param.bit_address`` stores the range's *last* address: the index of the
# field's least significant bit in the unpacked record. The strip below walks
# the field from its most significant bit down, which is the direction the
# spec prints.
#
# This is deliberately not ``messages.bit_field``/``set_bit_field``. Those
# are low-bit-first helpers kept for the ten-character names; they take a
# raw low-bit offset. Passing the spec's *first* (most significant) address
# to them shifts the field by ``bits - 1`` bits and still returns a value --
# a plausible wrong one, in the neighbouring bits. See
# ``encode_bit_field``'s docstring: the trap is documented there because
# that is where a reader will be.


def encode_bit_field(record: bytearray, param: Param, value: int) -> None:
    """Write ``param``'s value into an unpacked record, **MSB first**.

    The spec prints each field most-significant-bit first, and this walks
    the field in that order: the value's bit ``bits - 1`` lands at
    ``bit_address + bits - 1`` (the spec's *first* printed address) and bit
    0 lands at ``bit_address``. It is the exact inverse of
    :func:`decode_bit_field`.

    ``value`` is the raw stored field, ``0 <= value < 1 << param.bits``: for
    a Global parameter that is the two's-complement bit pattern, and for a
    Mix, Program or Effects parameter it is the offset-binary value, i.e.
    ``twos_complement - param.offset``.

    **Do not confuse this address convention with the name helpers'.**
    :func:`nano.messages.set_bit_field` also writes a low bit first, but it
    takes a raw offset and has no idea a spec range was involved. Handing it
    the spec's first address (``1:6``) instead of the low end of the range
    (``1:0``) moves the field up by ``bits - 1`` bits. Nothing raises: the
    record is the right length and the field decodes to a different, legal
    value, which is why this module converts in one place.
    """
    if not 0 <= value < (1 << param.bits):
        raise m.ProtocolError(f"{value} does not fit in {param.bits} bits")
    top = param.bit_address + param.bits - 1
    for step in range(param.bits):
        at = top - step  # most significant bit first
        byte, bit = at >> 3, at & 7
        if byte >= len(record):
            raise m.ProtocolError(
                f"bit {at} is past the end of a {len(record)}-byte record"
            )
        mask = 1 << bit
        if (value >> (param.bits - 1 - step)) & 1:
            record[byte] |= mask
        else:
            record[byte] &= ~mask & 0xFF


def decode_bit_field(record: Sequence[int], param: Param) -> int:
    """Read ``param``'s raw field out of an unpacked record.

    The exact inverse of :func:`encode_bit_field`: most significant bit
    first, starting at the spec's first printed address and ending at
    ``bit_address``. The result is the *stored* value -- two's complement
    for a Global parameter, offset binary for a packed one -- so a
    Mix/Program/Effects caller adds ``param.offset`` to see the value the
    ``10`` message takes.
    """
    value = 0
    top = param.bit_address + param.bits - 1
    for step in range(param.bits):
        at = top - step
        byte, bit = at >> 3, at & 7
        if byte >= len(record):
            raise m.ProtocolError(
                f"bit {at} is past the end of a {len(record)}-byte record"
            )
        if (record[byte] >> bit) & 1:
            value |= 1 << (param.bits - 1 - step)
    return value


def global_record_bytes(record: Sequence[int]) -> dict[str, int]:
    """Every Global parameter that fits in ``record``, label to value.

    The Global record is not bit-packed: each parameter is right-justified
    in its own byte, so a ``bit_address`` of ``byte * 8`` and the
    parameter's width recover the field. Signed parameters are stored in
    two's complement (the spec says so, and gives no Offset column), so a
    parameter whose ``low`` is negative is sign-extended here rather than
    returned as its unsigned bit pattern.

    "That fits" matters: dumps from software before version 2.00 carry only
    the first seventeen of the twenty bytes, and a field past the end is
    skipped rather than raising.
    """
    from nano import params  # deferred: params imports this module's sizes

    values: dict[str, int] = {}
    for param in params.GLOBAL_PARAMS:
        last_bit = param.bit_address + param.bits - 1
        if last_bit >> 3 >= len(record):
            continue
        value = decode_bit_field(record, param)
        if param.low < 0 and value >= 1 << (param.bits - 1):
            value -= 1 << param.bits
        values[param.label] = value
    return values
