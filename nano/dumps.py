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

"""Reading ``.syx`` files, and what an All Dump is made of.

An All Dump is not one message. It is 357 of them -- 128 user programs,
128 effects, 100 mixes and one global -- sent back to back, and a ``.syx``
file holding one is simply those messages concatenated. Reading it means
splitting on the message boundaries and sorting by opcode, not seeking to
offsets.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nano import banks
from nano import messages as m
from nano import records as rec

__all__ = ["ALL_DUMP_MESSAGES", "Library", "read_syx_file", "split_messages"]

#: What a complete All Dump contains, by opcode. Counted from a file the
#: owner had and confirmed against the specification's own totals.
ALL_DUMP_MESSAGES = {
    m.Function.USER_PROGRAM_DUMP: banks.PROGRAMS_PER_BANK,  # 128
    m.Function.USER_EFFECTS_DUMP: 128,
    m.Function.MIX_DUMP: banks.MIXES,  # 100
    m.Function.GLOBAL_DUMP: 1,
}


@dataclass
class Library:
    """Whatever a ``.syx`` file turned out to hold.

    Every field may be empty. A file holding only programs is perfectly
    normal, and the point of keeping each optional is that a caller can
    then say *which* part is missing rather than failing to load.
    """

    programs: dict[int, bytes] = field(default_factory=dict)
    effects: dict[int, bytes] = field(default_factory=dict)
    mixes: dict[int, bytes] = field(default_factory=dict)
    globals_: bytes | None = None
    #: Messages that parsed as Alesis QS but were not dumps, and foreign
    #: messages, counted rather than discarded silently.
    skipped: int = 0
    foreign: int = 0

    @property
    def is_all_dump(self) -> bool:
        return (
            len(self.programs) == ALL_DUMP_MESSAGES[m.Function.USER_PROGRAM_DUMP]
            and len(self.mixes) == ALL_DUMP_MESSAGES[m.Function.MIX_DUMP]
            and self.globals_ is not None
        )

    def program_names(self) -> dict[int, str]:
        """Every program name this file carries, by number."""
        out = {}
        for number, record in sorted(self.programs.items()):
            try:
                out[number] = rec.program_name(record)
            except m.ProtocolError:
                continue
        return out

    def mix_names(self) -> dict[int, str]:
        out = {}
        for number, record in sorted(self.mixes.items()):
            try:
                out[number] = rec.mix_name(record)
            except m.ProtocolError:
                continue
        return out

    def summary(self) -> str:
        parts = [f"{len(self.programs)} program(s)"]
        if self.effects:
            parts.append(f"{len(self.effects)} effects")
        if self.mixes:
            parts.append(f"{len(self.mixes)} mix(es)")
        if self.globals_ is not None:
            parts.append("global")
        if self.foreign:
            parts.append(f"{self.foreign} foreign message(s) skipped")
        return ", ".join(parts)


def split_messages(raw: bytes) -> list[bytes]:
    """Every complete SysEx message in a blob, in order.

    A trailing ``F0`` with no ``F7`` is dropped rather than raising: that
    is what a transfer cut short looks like, and the messages before it are
    still good.
    """
    out = []
    cursor = 0
    while True:
        start = raw.find(b"\xf0", cursor)
        if start < 0:
            break
        end = raw.find(b"\xf7", start)
        if end < 0:
            break
        out.append(raw[start : end + 1])
        cursor = end + 1
    return out


def read_syx_file(path: str) -> Library:
    """Load one ``.syx`` file.

    Foreign messages are counted and skipped rather than raising: a file
    somebody assembled may carry other devices' data, and that is their
    business.
    """
    with open(path, "rb") as handle:
        raw = handle.read()
    return read_bytes(raw)


def read_bytes(raw: bytes) -> Library:
    library = Library()
    for message in split_messages(raw):
        packet = m.parse(message)
        if packet is None:
            library.foreign += 1
            continue
        number = packet.number
        try:
            if number is None:
                # Not one of the numbered dumps this library holds. Counted
                # as skipped, which is where it fell before too.
                library.skipped += 1
            elif packet.function == m.Function.USER_PROGRAM_DUMP:
                library.programs[number] = packet.data()
            elif packet.function == m.Function.USER_EFFECTS_DUMP:
                library.effects[number] = packet.data()
            elif packet.function == m.Function.MIX_DUMP:
                library.mixes[number] = packet.data()
            elif packet.function == m.Function.GLOBAL_DUMP:
                library.globals_ = packet.data()
            else:
                library.skipped += 1
        except m.ProtocolError:
            # A dump whose packed data is malformed. Counted with the
            # foreign ones: it is not usable and it is not a reason to
            # abandon the rest of the file.
            library.foreign += 1
    return library
