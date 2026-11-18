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

"""Reading MidiQuest's ``.sqs`` bank container.

A ``.sqs`` file is an IFF-like container: four bytes of chunk type, a
four-byte big-endian size, then the chunk's data. A ``LIST`` wraps five
``FORM``s, one per bank, and each ``FORM`` ends in a ``BODY`` chunk whose
payload is **plain concatenated Alesis SysEx** -- exactly the bytes an All
Dump would have, or a slice of one: ``F0 00 00 0E 0E`` and on to ``F7``,
messages back to back with no framing of the container's own.

**The chunk sizes are not walked.** They drift: the first ``FORM`` claims a
size that ends 44 bytes before the next ``FORM`` begins, and a walker that
trusts them steps into the middle of the next bank's header. What is
reliable is the SysEx itself, so this module scans for the Alesis header
and its terminating ``F7``. Packed data is 7-bit by construction, so an
``F7`` cannot occur inside a message and the first one after a header is
the end of that message.

**Only Alesis messages are taken.** A container may hold another
manufacturer's dump -- one of the files this was written against carries a
Roland XV-2020 patch -- and those are not the nano's business. A stray
``F0`` that is not followed by the Alesis header is skipped, as is a
header with no ``F7`` after it: the extractor never invents a message to
fill a gap.

**Bank boundaries.** A ``.sqs`` keeps several banks in one container, one
per ``FORM``. The ``FORM`` signature is ASCII and can occur inside 7-bit
packed data, so boundaries are only taken where they fall *outside* an
extracted Alesis message's byte span. Each message is assigned to the last
boundary before it; a bank that receives none stays an empty ``b""``.
"""

from __future__ import annotations

import bisect

__all__ = ["HEADER", "MAGIC", "extract_sysex", "is_sqs", "read_banks"]

#: The container's first chunk. A plain ``.syx`` starts with ``F0``, so the
#: two cannot be confused.
MAGIC = b"LIST"

#: The Alesis QS header the scan anchors on: ``F0``, Alesis's extended
#: manufacturer ID and the QS family byte.
HEADER = b"\xf0\x00\x00\x0e\x0e"


def is_sqs(raw: bytes) -> bool:
    """Whether ``raw`` is a MidiQuest container rather than a ``.syx``."""
    return raw.startswith(MAGIC)


def _message_spans(raw: bytes) -> list[tuple[int, int]]:
    """Return ``(start, end)`` byte spans of every Alesis message.

    ``start`` points at the ``HEADER`` and ``end`` is one past the
    terminating ``F7``. A header with no ``F7`` before the next header (or
    at all) is dropped without swallowing the messages that follow it.
    """
    spans: list[tuple[int, int]] = []
    cursor = 0
    header_len = len(HEADER)
    while True:
        start = raw.find(HEADER, cursor)
        if start < 0:
            break
        next_header = raw.find(HEADER, start + header_len)
        end = raw.find(b"\xf7", start)
        if end < 0:
            break
        # A second header before the terminator means the first one never
        # terminated: drop it and try again from the next header.
        if next_header != -1 and next_header < end:
            cursor = next_header
            continue
        spans.append((start, end + 1))
        cursor = end + 1
    return spans


def _form_boundaries(raw: bytes, spans: list[tuple[int, int]]) -> list[int]:
    """Positions of every ``FORM`` signature outside the message spans."""
    boundaries: list[int] = []
    cursor = 0
    while True:
        pos = raw.find(b"FORM", cursor)
        if pos < 0:
            break
        if not any(start <= pos < end for start, end in spans):
            boundaries.append(pos)
        cursor = pos + 1
    return boundaries


def read_banks(raw: bytes) -> list[bytes]:
    """Split a container into one payload per ``FORM`` bank.

    Alesis messages are extracted with their absolute byte spans first, so a
    ``FORM`` signature that happens to occur inside 7-bit packed data does
    not create a spurious bank boundary. Every ``FORM`` found outside those
    spans becomes a bank (in file order); each message is assigned to the
    bank whose boundary is the last one before it. A bank that receives no
    Alesis message is kept as ``b""``. Messages that precede every boundary
    are dropped, matching the container's bank model.
    """
    spans = _message_spans(raw)
    boundaries = _form_boundaries(raw, spans)
    banks: list[bytearray] = [bytearray() for _ in boundaries]
    for start, end in spans:
        index = bisect.bisect_right(boundaries, start) - 1
        if 0 <= index < len(banks):
            banks[index].extend(raw[start:end])
    return [bytes(bank) for bank in banks]


def extract_sysex(raw: bytes) -> bytes:
    """Every Alesis message in a container, concatenated, in order.

    The result is what a ``.syx`` file holding the same messages would
    contain, so :func:`nano.dumps.read_bytes` can read it unchanged.
    Anything that is not an Alesis message is left out, and a message with
    no ``F7`` is dropped rather than repaired. Returns ``b""`` when the
    container holds none.
    """
    return b"".join(read_banks(raw))
