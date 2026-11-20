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

"""Init bank core: the template, the equality test, the append scan.

Feature I1 of ``docs/EXPORT_INIT_APPEND_PLAN.md``, §4.3. The template is
the unit's own hardwired ``Off`` record from User slot 127 with its name
changed to ``Init``. Nothing about its parameters is invented: §4.1's
rule is that an unverified record is worse than none, and silence is
§4.2's hardware decision, not a guess.

``init_record`` changes only the name bits. That is the whole of the
write's risk: the record staged for every slot is the unit's own program
under a new label, and a change to a parameter byte here would be a
program somebody made wearing somebody else's name -- exactly what
``is_init`` refuses to call free.

``is_init`` is whole-record equality, not a name comparison: a program
that is called ``Init`` but has different parameters is not free (§4.3).

``append_start`` scans from the top so append can write after the
highest occupied slot (§4.4); a read failure propagates because guessing
past a hole could store over a real program (§4.8).
"""

from __future__ import annotations

from collections.abc import Callable

from nano import messages
from nano import records as rec

__all__ = ["INIT_NAME", "append_start", "init_record", "is_init"]

#: The name init writes into every slot it creates.
INIT_NAME = "Init"

#: The last writable User slot. 127 is hardwired silent
#: (:data:`nano.banks.SILENT_PROGRAM`), so the User range is 000-126,
#: per §4.0 and §4.3.
_LAST_USER_SLOT = 126


def init_record(off_record: bytes) -> bytes:
    """The 127 ``Off`` record with its name changed to ``Init``.

    The record is checked to :data:`nano.records.PROGRAM_BYTES` and
    copied, then only the ten-character name is rewritten through
    :func:`nano.messages.encode_name`. Every other byte is untouched, so
    the staged record is the unit's own empty program under a new label.
    """
    rec.check_size(off_record, rec.PROGRAM_BYTES, "a program")
    record = bytearray(off_record[: rec.PROGRAM_BYTES])
    messages.encode_name(record, INIT_NAME, messages.NAME_BIT_OFFSET)
    return bytes(record)


def is_init(record: bytes, template: bytes) -> bool:
    """True only for a byte-identical Init record.

    The record is checked to :data:`nano.records.PROGRAM_BYTES` and
    truncated to it, as a real read does. Equality is whole-record: a
    user program that merely happens to be named ``Init`` with different
    parameters is not free (§4.3).
    """
    if len(record) < rec.PROGRAM_BYTES:
        return False
    return record[: rec.PROGRAM_BYTES] == template[: rec.PROGRAM_BYTES]


def append_start(read: Callable[[int], bytes], template: bytes) -> int:
    """The first free trailing slot: the slot after the highest non-Init.

    ``read(number)`` returns the record of that User slot and raises on a
    failed read. Slots are read backwards from the top (126 to 0); the
    first non-Init slot found is the highest non-Init one, and the
    return is its number plus one. If every slot 000-126 reads as Init,
    the return is ``0``: append goes to the bank's first slot. A failed
    read propagates -- guessing past a hole could store over a real
    program (§4.8).
    """
    for number in range(_LAST_USER_SLOT, -1, -1):
        if not is_init(read(number), template):
            return number + 1
    return 0
