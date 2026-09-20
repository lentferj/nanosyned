# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The wire protocol is transcribed as data from Alesis's published
# QS6/7/8/R System Exclusive specification, and from what this NanoSynth
# answered on the bench. The transport layer is ported from the sibling
# x5ded, s3ked, eosed, k2kremote and mpc2emu projects.
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

"""The NanoSynth's System Exclusive messages.

**The NanoSynth's own manual says nothing about System Exclusive.** Its
MIDI Implementation Chart has one line for it -- and that chart's legend is
inverted from the usual convention, reading ``X = YES, O = NO``, so the
line means the unit both sends and receives it. What it sends and receives
is not in the manual at all.

What it speaks is the **Alesis QS protocol**. The NanoSynth is a QS engine
in a box without a display, and it answers the QS6/7/8/R message set. That
specification is published, and this module is transcribed from it; every
message here was then confirmed against the unit, which is the only reason
any of it is stated as fact rather than as a guess.

The unit identifies itself as family member **7**. Alesis's published list
covers QS6 (3), QS8 (4), QS7 (5) and QSR (6) and stops there; 7 is this
box, and it is recorded here because nothing else records it.

Two things about this protocol that shape every caller:

1. **Packing is a bitstream, not a byte transform.** Seven 8-bit bytes
   travel as eight 7-bit ones, low bits first. Get the direction wrong and
   the data still unpacks, to plausible nonsense -- which is worse than
   failing.
2. **A name is not bytes.** Ten characters of seven bits each, starting
   eight bits into the record and not aligned to anything. ``value + 32``
   is the ASCII character.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

__all__ = [
    "SYSEX_START", "SYSEX_END", "ALESIS_ID", "QS_FAMILY", "NANOSYNTH_MEMBER",
    "Function", "ProtocolError", "Packet",
    "frame", "parse", "pack7", "unpack7",
    "NAME_CHARS", "NAME_BIT_OFFSET", "decode_name", "encode_name",
    "bit_field", "set_bit_field",
    "identity_request", "identity_reply_fields",
    "program_dump_request", "edit_program_dump_request",
    "effects_dump_request", "edit_effects_dump_request",
    "mix_dump_request", "global_dump_request", "all_dump_request",
    "mode_select", "bank_select", "program_change",
]

SYSEX_START = 0xF0
SYSEX_END = 0xF7

#: Alesis, as an MMA *extended* three-byte manufacturer ID. The leading
#: zero is what marks it extended; a one-byte ID could never be 0x00.
ALESIS_ID = (0x00, 0x00, 0x0E)

#: The Quadrasynth/QS product family, which the NanoSynth belongs to.
QS_FAMILY = 0x0E

#: What this unit answers an Identity Request with. Alesis's published list
#: stops at QSR; this number came off the bench.
NANOSYNTH_MEMBER = 0x07


class ProtocolError(ValueError):
    """A message that is not what it claims to be."""


class Function:
    """Opcodes, from Alesis's QS specification.

    The request/reply pairing is not a pattern you can derive: requests are
    odd and dumps even up to ``0x0B`` and then it stops, so
    :data:`REPLY_TO` is a table rather than arithmetic. The sibling kwsed
    guessed such a pattern from four of five pairs, probed it, and got
    silence.
    """

    USER_PROGRAM_DUMP = 0x00
    USER_PROGRAM_REQUEST = 0x01
    EDIT_PROGRAM_DUMP = 0x02
    EDIT_PROGRAM_REQUEST = 0x03
    OLD_MIX_DUMP = 0x04
    OLD_MIX_REQUEST = 0x05
    USER_EFFECTS_DUMP = 0x06
    USER_EFFECTS_REQUEST = 0x07
    EDIT_EFFECTS_DUMP = 0x08
    EDIT_EFFECTS_REQUEST = 0x09
    GLOBAL_DUMP = 0x0A
    GLOBAL_REQUEST = 0x0B
    ALL_REQUEST = 0x0C
    MODE_SELECT = 0x0D
    MIX_DUMP = 0x0E
    MIX_REQUEST = 0x0F
    MIDI_EDIT = 0x10
    SECTOR_ERASE = 0x11
    SECTOR_WRITE = 0x12
    SECTOR_REQUEST = 0x13
    FLASH_ACK = 0x14
    FLASH_NACK = 0x15

    #: Every opcode by name, requests included. A timeout message that can
    #: say "no User Program Dump came back" is worth more than one that
    #: says "no 0x00 came back", and leaving the requests out of this table
    #: is how the sibling x5ded ended up printing the latter.
    NAMES = {
        0x00: "User Program Dump", 0x01: "User Program Dump Request",
        0x02: "Edit Program Dump", 0x03: "Edit Program Dump Request",
        0x04: "Old Mix Dump", 0x05: "Old Mix Dump Request",
        0x06: "User Effects Dump", 0x07: "User Effects Dump Request",
        0x08: "Edit Effects Dump", 0x09: "Edit Effects Dump Request",
        0x0A: "Global Dump", 0x0B: "Global Dump Request",
        0x0C: "All Dump Request", 0x0D: "Mode Select",
        0x0E: "Mix Dump", 0x0F: "Mix Dump Request",
        0x10: "MIDI Edit", 0x11: "Sector Erase", 0x12: "Sector Write",
        0x13: "Sector Request", 0x14: "FLASH ACK", 0x15: "FLASH NACK",
    }

    #: Which dump answers which request.
    REPLY_TO = {
        USER_PROGRAM_REQUEST: USER_PROGRAM_DUMP,
        EDIT_PROGRAM_REQUEST: EDIT_PROGRAM_DUMP,
        OLD_MIX_REQUEST: OLD_MIX_DUMP,
        USER_EFFECTS_REQUEST: USER_EFFECTS_DUMP,
        EDIT_EFFECTS_REQUEST: EDIT_EFFECTS_DUMP,
        GLOBAL_REQUEST: GLOBAL_DUMP,
        MIX_REQUEST: MIX_DUMP,
    }

    @staticmethod
    def name(opcode: int) -> str:
        return Function.NAMES.get(opcode, f"function {opcode:#04x}")


class Packet:
    """One parsed Alesis message."""

    __slots__ = ("function", "number", "payload")

    def __init__(self, function: int, number: Optional[int],
                 payload: bytes) -> None:
        self.function = function
        #: The object number a dump carries, or ``None`` for those that
        #: carry none. Kept separate from the payload because every caller
        #: that files a dump needs it and none of them should be slicing
        #: the payload to find it.
        self.number = number
        self.payload = payload

    @property
    def function_name(self) -> str:
        return Function.name(self.function)

    def data(self) -> bytes:
        """The payload unpacked back to 8-bit bytes."""
        return unpack7(self.payload)

    def __repr__(self) -> str:
        return (f"Packet({self.function_name!r}, number={self.number}, "
                f"{len(self.payload)} packed bytes)")


#: Opcodes whose message carries a number byte after the opcode.
#:
#: **The edit-buffer dumps are in here**, which is not obvious: an edit
#: buffer is a single thing and the number is always zero, so it looks
#: like a dump that would carry none. Leaving them out does not raise --
#: the number byte is simply read as the first byte of packed data, every
#: field shifts by eight bits, and the record comes out the right length
#: with a name one character out -- ``' Invented1'`` where the record
#: holds ``'Invented12'``. That is a name a person would accept at a
#: glance, which is what makes it worth a table rather than a comment.
NUMBERED = frozenset({
    Function.USER_PROGRAM_DUMP, Function.USER_PROGRAM_REQUEST,
    Function.EDIT_PROGRAM_DUMP, Function.EDIT_PROGRAM_REQUEST,
    Function.OLD_MIX_DUMP, Function.OLD_MIX_REQUEST,
    Function.USER_EFFECTS_DUMP, Function.USER_EFFECTS_REQUEST,
    Function.EDIT_EFFECTS_DUMP, Function.EDIT_EFFECTS_REQUEST,
    Function.MIX_DUMP, Function.MIX_REQUEST,
    Function.GLOBAL_DUMP, Function.GLOBAL_REQUEST,
})


def frame(function: int, body: Sequence[int] = ()) -> bytes:
    """One Alesis message, ready to send."""
    for byte in body:
        if not 0 <= byte <= 0x7F:
            raise ProtocolError(
                f"{byte:#04x} is not a 7-bit data byte; SysEx carries no "
                f"byte with bit 7 set")
    return bytes([SYSEX_START, *ALESIS_ID, QS_FAMILY, function, *body,
                  SYSEX_END])


def parse(message: Sequence[int]) -> Optional[Packet]:
    """Parse one Alesis QS message, or ``None`` if it is not one.

    ``None`` rather than an exception for foreign traffic: a shared MIDI
    port carries other manufacturers' messages and other Alesis models',
    and none of those are errors.

    **This is also what rejects our own requests.** The chain this was
    written against has a soft thru in it, so every message sent comes
    back. A request is a well-formed Alesis message and parses cleanly;
    telling it from a reply is the caller's job, by opcode, and
    :data:`Function.REPLY_TO` exists so that no caller has to guess.
    """
    data = bytes(message)
    if len(data) < 7:
        return None
    if data[0] != SYSEX_START or data[-1] != SYSEX_END:
        return None
    if tuple(data[1:4]) != ALESIS_ID or data[4] != QS_FAMILY:
        return None
    function = data[5]
    rest = data[6:-1]
    if function in NUMBERED and rest:
        return Packet(function, rest[0], bytes(rest[1:]))
    return Packet(function, None, bytes(rest))


def pack7(data: Sequence[int]) -> bytes:
    """Plain bytes to Alesis's packed form, **low bits first**.

    Seven 8-bit bytes become eight 7-bit ones. Alesis documents it as a bit
    table rather than a formula; written as a bitstream it is the same
    thing and harder to get subtly wrong.
    """
    out = bytearray()
    acc = bits = 0
    for byte in data:
        if not 0 <= byte <= 0xFF:
            raise ProtocolError(f"{byte} is not a byte")
        acc |= byte << bits
        bits += 8
        while bits >= 7:
            out.append(acc & 0x7F)
            acc >>= 7
            bits -= 7
    if bits:
        out.append(acc & 0x7F)
    return bytes(out)


def unpack7(data: Sequence[int]) -> bytes:
    """Alesis's packed form back to plain bytes. Inverse of :func:`pack7`.

    Every byte is checked. A byte with bit 7 set cannot appear inside a
    SysEx message on the wire -- it would have ended it -- but it can
    appear in a ``.syx`` file somebody has truncated or concatenated
    wrongly, and unpacking that silently yields a record that is entirely
    plausible and entirely wrong.
    """
    out = bytearray()
    acc = bits = 0
    for byte in data:
        if not 0 <= byte <= 0x7F:
            raise ProtocolError(
                f"{byte:#04x} has bit 7 set; packed data must not")
        acc |= byte << bits
        bits += 7
        while bits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            bits -= 8
    return bytes(out)


#: A name is ten characters.
NAME_CHARS = 10

#: ...seven bits each, starting eight bits into the record. Not a byte
#: offset: the eleventh character would start at bit 78. Two spare bits
#: precede it, which is why the offset is 8 and not 0.
NAME_BIT_OFFSET = 8

#: Alesis stores 0-95; adding this gives ASCII, so 0 is a space.
NAME_BASE = 32


def bit_field(data: Sequence[int], bit_offset: int, width: int) -> int:
    """``width`` bits starting at ``bit_offset``, low bit first."""
    value = 0
    for index in range(width):
        at = bit_offset + index
        byte = at >> 3
        if byte >= len(data):
            raise ProtocolError(
                f"bit {at} is past the end of a {len(data)}-byte record")
        value |= ((data[byte] >> (at & 7)) & 1) << index
    return value


def set_bit_field(data: bytearray, bit_offset: int, width: int,
                  value: int) -> None:
    """Write ``width`` bits at ``bit_offset``, low bit first."""
    if not 0 <= value < (1 << width):
        raise ProtocolError(f"{value} does not fit in {width} bits")
    for index in range(width):
        at = bit_offset + index
        byte = at >> 3
        if byte >= len(data):
            raise ProtocolError(
                f"bit {at} is past the end of a {len(data)}-byte record")
        mask = 1 << (at & 7)
        if (value >> index) & 1:
            data[byte] |= mask
        else:
            data[byte] &= ~mask & 0xFF


def decode_name(record: Sequence[int],
                bit_offset: int = NAME_BIT_OFFSET) -> str:
    """The ten-character name at the start of a record.

    Trailing spaces are kept rather than stripped: the caller decides how
    to present a name, and a name that is genuinely blank is worth being
    able to tell from one that is missing.
    """
    chars = []
    for index in range(NAME_CHARS):
        value = bit_field(record, bit_offset + 7 * index, 7)
        chars.append(chr(value + NAME_BASE) if value <= 95 else "?")
    return "".join(chars)


def encode_name(record: bytearray, name: str,
                bit_offset: int = NAME_BIT_OFFSET) -> None:
    """Write a ten-character name into a record, in place."""
    padded = f"{name:<{NAME_CHARS}}"[:NAME_CHARS]
    for index, char in enumerate(padded):
        value = ord(char) - NAME_BASE
        if not 0 <= value <= 95:
            raise ProtocolError(
                f"{char!r} is not in this instrument's character set, which "
                f"runs from space to {chr(95 + NAME_BASE)!r}")
        set_bit_field(record, bit_offset + 7 * index, 7, value)


# --- requests ---------------------------------------------------------------

def identity_request() -> bytes:
    """The universal Identity Request. Not an Alesis message."""
    return bytes([SYSEX_START, 0x7E, 0x7F, 0x06, 0x01, SYSEX_END])


def identity_reply_fields(message: Sequence[int]) -> Optional[dict]:
    """Fields of an Identity Reply, or ``None``.

    Matching the reply sub-ID (``02``) and never the request (``01``) is
    what stops a thru loop being taken for a device -- and this chain does
    loop: the request comes back.

    Alesis's ID is the three-byte extended form, so the family and member
    fields sit three bytes further along than they would for a one-byte
    manufacturer. Reading them at the usual offsets gives a plausible
    wrong answer rather than an error.
    """
    data = bytes(message)
    if len(data) < 13 or data[0] != SYSEX_START or data[-1] != SYSEX_END:
        return None
    if data[1] != 0x7E or data[3] != 0x06 or data[4] != 0x02:
        return None
    if tuple(data[5:8]) != ALESIS_ID:
        return {"channel": data[2], "is_alesis": False,
                "is_nanosynth": False}
    family = (data[8], data[9])
    member = (data[10], data[11])
    version = bytes(data[12:-1]).decode("ascii", "replace")
    return {
        "channel": data[2],
        "manufacturer": ALESIS_ID,
        "family": family,
        "member": member,
        "version": version,
        "is_alesis": True,
        "is_qs_family": family[0] == QS_FAMILY,
        "is_nanosynth": (family[0] == QS_FAMILY
                         and member[0] == NANOSYNTH_MEMBER),
    }


def program_dump_request(number: int) -> bytes:
    """Ask for one of the 128 **user** programs.

    Only the user bank can be read this way. The General MIDI bank and the
    three preset banks are ROM and the protocol has no request for them --
    see :mod:`nano.banks`.
    """
    if not 0 <= number <= 127:
        raise ProtocolError(f"user program {number} is outside 0-127")
    return frame(Function.USER_PROGRAM_REQUEST, [number])


def edit_program_dump_request() -> bytes:
    """Ask for the edit buffer -- whatever the unit is playing now."""
    return frame(Function.EDIT_PROGRAM_REQUEST, [0x00])


def effects_dump_request(number: int) -> bytes:
    if not 0 <= number <= 127:
        raise ProtocolError(f"effects {number} is outside 0-127")
    return frame(Function.USER_EFFECTS_REQUEST, [number])


def edit_effects_dump_request() -> bytes:
    return frame(Function.EDIT_EFFECTS_REQUEST, [0x00])


def mix_dump_request(number: int) -> bytes:
    """Ask for one of the 100 user mixes.

    The NanoSynth's manual does not mention mixes at all. The unit answers
    for them anyway, which is how this came to be here.
    """
    if not 0 <= number <= 99:
        raise ProtocolError(f"mix {number} is outside 0-99")
    return frame(Function.MIX_REQUEST, [number])


def global_dump_request() -> bytes:
    return frame(Function.GLOBAL_REQUEST, [0x00])


def all_dump_request() -> bytes:
    """Ask for everything: 128 programs, 128 effects, 100 mixes, global.

    Roughly 79 kB in 357 messages. Nothing in this program sends it
    implicitly.
    """
    return frame(Function.ALL_REQUEST)


def mode_select(mix_mode: bool) -> bytes:
    """Put the unit in Program or Mix mode. **This changes what plays.**"""
    return frame(Function.MODE_SELECT, [0x01 if mix_mode else 0x00])


def bank_select(bank: int, channel: int = 0) -> List[bytes]:
    """Bank Select, as **Controller 0 only**.

    The manual is explicit that this unit ignores Controller 32, which
    many sequencers send instead. Sending both would be harmless here and
    is still not done: a program that sends a message the instrument
    documents as ignored invites the reader to believe it matters.
    """
    if not 0 <= bank <= 127:
        raise ProtocolError(f"bank {bank} is outside 0-127")
    if not 0 <= channel <= 15:
        raise ProtocolError(f"channel {channel} is outside 0-15")
    return [bytes([0xB0 | channel, 0x00, bank])]


def program_change(program: int, channel: int = 0) -> bytes:
    if not 0 <= program <= 127:
        raise ProtocolError(f"program {program} is outside 0-127")
    if not 0 <= channel <= 15:
        raise ProtocolError(f"channel {channel} is outside 0-15")
    return bytes([0xC0 | channel, program])
