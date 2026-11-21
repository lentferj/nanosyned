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

"""One ordinary Alesis ``.syx`` file holding a full backup.

A full backup is one file that carries every setting the unit can restore
by a SysEx load: the user programs that are not the hardwired silent one,
every user effects patch, every user mix, and the one global settings
record. It is one file rather than a store of per-slot backups because the
restore path this project already has -- ``nanocli send FILE
--allow-write --yes`` -- takes exactly such a file, and a full backup in
another format would need a second writer.

The file is the concatenation of one Alesis dump message per destination,
built with :func:`nano.writing.frame`, so it is exactly what
:func:`nano.dumps.read_syx_file` reads back and what a whole-bank restore
sends.

**Reads first, file second.** Every destination is read before any byte is
written, so a read that fails or a cancel that lands leaves no file behind:
a partial backup is worse than no backup.

The file is built as ``path + ".tmp"`` in the same directory, flushed,
fsynced, then moved into place with :func:`os.replace`; any failure removes
the temporary file, so what is at ``path`` afterwards is either the old file
or the new one, never a partial one.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from nano import banks, writing

__all__ = [
    "TOTAL_RECORDS",
    "BackupCancelled",
    "BackupResult",
    "backup_device",
    "read_all",
    "slots",
    "write_syx",
]

#: How many destinations a full backup holds, and how many reads it takes.
#: User programs 000-126 (127 is hardwired silent), the user effects patches
#: 000-127, the user mixes 000-099, and the one global settings record. The
#: mix edit buffer (100) and the hardwired silent program (127) are not stored
#: user data, so neither belongs in a backup.
TOTAL_RECORDS = 356


class BackupCancelled(Exception):
    """A full backup was cancelled before some destination could be read.

    The rule the caller relies on is the one the backup's shape
    guarantees: the file is not written.
    """


@dataclass(frozen=True)
class BackupResult:
    """The finished full backup, as one checkable line.

    ``path`` is the file the caller asked for, ``byte_count`` what
    :func:`write_syx` wrote, and the four counts the backup read back: how
    many programs, effects patches, mixes and global settings it carried.
    ``count`` is the sum of the four, which is :data:`TOTAL_RECORDS` for a
    backup that read every destination cleanly.
    """

    path: str
    byte_count: int
    programs: int
    effects: int
    mixes: int
    globals_: int

    @property
    def count(self) -> int:
        """The destinations the backup held: the sum of the four counts."""
        return self.programs + self.effects + self.mixes + self.globals_


def slots() -> tuple[tuple[str, int | None], ...]:
    """The 356 destinations of a full backup, in the order it reads them.

    User programs 000-126 -- 127 is hardwired silent and is not user data --
    then the user effects patches 000-127, the user mixes 000-099, and the
    single global settings record, which carries no number.
    """
    destinations: list[tuple[str, int | None]] = [
        ("program", number) for number in range(banks.SILENT_PROGRAM[1])
    ]
    destinations.extend(
        ("effects", number) for number in range(banks.PROGRAMS_PER_BANK)
    )
    destinations.extend(("mix", number) for number in range(banks.MIXES))
    destinations.append(("global", None))
    return tuple(destinations)


def read_all(
    device: Any,
    *,
    on_read: Callable[[str, int | None, str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[tuple[str, int | None, bytes], ...]:
    """Read every destination in full; return what it held.

    The reads happen in :func:`slots` order, one destination at a time, through
    the same read the write fence uses, so a record is truncated exactly the
    way a store expects it. ``on_read(kind, number, name, done, total)`` fires
    after each successful read: ``name`` is the record's name, ``done`` the
    1-based count of reads completed including this one and ``total`` the
    number of reads in a full backup -- the shape a progress screen reports
    as ``n/356``.

    ``cancelled()`` is consulted before each read; a true answer raises
    :class:`BackupCancelled` rather than reading on, so the caller can stop
    between destinations. A read failure propagates as it happened.

    Nothing here writes, so a cancelled or failed read leaves no file behind
    for the caller to clean up.
    """
    records: list[tuple[str, int | None, bytes]] = []
    for kind, number in slots():
        if cancelled is not None and cancelled():
            raise BackupCancelled(
                f"full backup cancelled before reading {writing.label(kind, number)}"
            )
        record = writing.truncate(
            kind, writing.read_record(device, kind, number), writing.label(kind, number)
        )
        done = len(records) + 1
        if on_read is not None:
            on_read(
                kind, number, writing.record_name(kind, record), done, TOTAL_RECORDS
            )
        records.append((kind, number, record))
    return tuple(records)


def write_syx(
    path: str,
    records: tuple[tuple[str, int | None, bytes], ...],
    *,
    overwrite: bool = False,
) -> int:
    """Concatenate the dumps, write them atomically, return the byte count.

    The messages are :func:`nano.writing.frame` of each ``(kind, number,
    record)`` in the order given, so the file's slot numbers are the
    originals and a restore lands the same destinations a backup read.

    An existing ``path`` is refused with :class:`FileExistsError` unless
    ``overwrite`` is set. The file is built as ``path + ".tmp"`` in the same
    directory, flushed, fsynced, then moved into place with :func:`os.replace`.
    Any failure removes the temporary file and re-raises, so what is at
    ``path`` afterwards is either the old file or the new one -- never a
    partial one.
    """
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"{path} already exists; pass overwrite to replace it")
    data = b"".join(
        writing.frame(kind, number, record) for kind, number, record in records
    )
    temporary = path + ".tmp"
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.remove(temporary)
        except FileNotFoundError:
            pass
        raise
    return len(data)


def backup_device(
    device: Any,
    path: str,
    *,
    overwrite: bool = False,
    on_read: Callable[[str, int | None, str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> BackupResult:
    """Read the whole unit, then write one file, and say how it went.

    The order is the plan's: every destination is read first and only then is
    the file written, so a read that fails or one that was cancelled leaves no
    file behind. An existing destination is refused before the first read:
    the user asked not to replace it, and making 356 requests to discover that
    would waste the unit's time and say the wrong thing when it is offline.
    """
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"{path} already exists; pass overwrite to replace it")
    records = read_all(device, on_read=on_read, cancelled=cancelled)
    byte_count = write_syx(path, records, overwrite=overwrite)
    counts = {"program": 0, "effects": 0, "mix": 0, "global": 0}
    for kind, _number, _record in records:
        counts[kind] += 1
    return BackupResult(
        path=path,
        byte_count=byte_count,
        programs=counts["program"],
        effects=counts["effects"],
        mixes=counts["mix"],
        globals_=counts["global"],
    )
