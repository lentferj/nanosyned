# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The comparison is the shape the sibling rxved's store verification uses:
# send, read back, compare the two records, and say which bytes disagree.
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

"""Did the write land?

**A write is not known to have landed until the record is read back and
compared.** The unit answers a store with silence whether it accepted it or
not -- there is no acknowledgement on the wire and no error to catch -- so
the only evidence that a store happened is the record the instrument sends
when asked for it afterwards. Sending and believing is how a program
disappears from a user slot while the caller reports success.

This module is that comparison and nothing else. It is **pure**: it takes
two buffers and returns offsets, so it needs no hardware, runs in tests, and
is the same comparison the demo checks itself against and the bench harness
uses against the unit. The recording and the reporting around a write -- the
gate that decides to send it, the backup taken first, the log that says it
was done -- belong to the caller, as they do in the sibling projects.
"""

from __future__ import annotations

__all__ = ["describe", "mismatches"]

#: How many offsets :func:`describe` names before it stops listing them.
#: Enough to see a pattern -- a shifted field, a size that came up short --
#: without turning one wrong store into a wall of numbers.
_SHOWN = 3


def mismatches(sent: bytes, read_back: bytes) -> list[int]:
    """Byte offsets at which ``sent`` and ``read_back`` disagree.

    An offset is reported when the bytes differ **or** when it sits past
    the shorter of the two: a record that came back truncated is not
    agreement, and counting only the bytes both buffers hold would call a
    short read a clean write.

    ``[]`` means agreement, byte for byte, including the lengths.
    """
    shared = min(len(sent), len(read_back))
    offsets = [at for at in range(shared) if sent[at] != read_back[at]]
    offsets.extend(range(shared, max(len(sent), len(read_back))))
    return offsets


def describe(sent: bytes, read_back: bytes, *, what: str = "record") -> str:
    """One sentence saying whether the unit took ``what``, and where not.

    The offsets are the first few from :func:`mismatches`, so the sentence
    and the list a caller logs cannot disagree about what went wrong.
    """
    offsets = mismatches(sent, read_back)
    if not offsets:
        return f"{what} read back byte-for-byte"
    listed = ", ".join(str(at) for at in offsets[:_SHOWN])
    if len(offsets) > _SHOWN:
        listed += ", ..."
    return f"the unit did not take the {what}: {len(offsets)} byte(s) differ ({listed})"
