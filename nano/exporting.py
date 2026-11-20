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

"""Export the User bank's favourites to one ``.syx`` file.

Feature E1 of the export-favourites plan, ``docs/EXPORT_INIT_APPEND_PLAN.md``
§3.1. The unit is the source of truth for the programs themselves: the
export reads them, and only then is the file written, so a short or failed
read aborts the whole thing before any file exists -- the plan's rule that
"a partial backup is worse than no backup".

The file is built from the original slot numbers with
:func:`nano.messages.program_dump`, so it is exactly what
:func:`nano.dumps.read_syx_file` reads back, and a whole-bank import is a
restore rather than an approximation.

The file carries program bytes only. Ratings, tags and notes live in the
local favourites database and are not exported: the plan says so twice,
because the temptation to slip them in is real.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from nano import messages, writing
from nano import records as rec
from nano.favorites import Favorites

__all__ = [
    "USER_BANK",
    "ExportCancelled",
    "ExportResult",
    "export_favourites",
    "export_selected",
    "favourite_numbers",
    "read_programs",
    "write_syx",
]

#: The bank this export speaks about: the only one the unit will dump.
USER_BANK = "USER"

#: The last User slot worth exporting. 127 is hardwired silent, so a file
#: that carried it could not be fully restored; it is excluded rather than
#: skipped over quietly.
_LAST_SLOT = 126


class ExportCancelled(Exception):
    """A read was refused because the export was cancelled.

    The rule the caller relies on is the one the export's shape
    guarantees: the file is not written.
    """


@dataclass(frozen=True)
class ExportResult:
    """The finished export, as one checkable line.

    ``path`` is the file the caller asked for, ``count`` the programs in
    it, and ``byte_count`` what :func:`write_syx` wrote.
    """

    path: str
    count: int
    byte_count: int


def favourite_numbers(favorites: Favorites) -> tuple[int, ...]:
    """Active USER favourites, ascending, 000-126, 127 excluded.

    ``keys_for_bank("USER")`` already means "the active ones"; the range
    filter is the "127 excluded" half of the rule, with the docstring
    saying it rather than the caller having to discover it. A store with
    nothing active refuses instead of exporting an empty file: the caller
    has nothing to name the file after yet, and a zero-byte syx is not a
    backup anyone can open later.
    """
    numbers = sorted(
        number
        for number in favorites.keys_for_bank(USER_BANK)
        if 0 <= number <= _LAST_SLOT
    )
    if not numbers:
        raise ValueError("no favourited User programs to export; nothing written")
    return tuple(numbers)


def read_programs(
    device: Any,
    numbers: Sequence[int],
    *,
    on_read: Callable[[int, str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[tuple[int, bytes]]:
    """Read every slot first; return ``((number, record), ...)``.

    Reads happen in the order given, one slot at a time, through the same
    read the write fence uses. ``on_read(number, name, done, total)`` fires
    after each read: ``name`` is the record's name, ``done`` the 1-based
    count of reads completed including this one and ``total`` the number
    of reads in the list -- the shape a progress screen reports as ``n/N``.

    ``cancelled()`` is consulted before each read; a true answer raises
    :class:`ExportCancelled` rather than reading on, so the caller can
    stop between slots. A read failure propagates as it happened. Both
    rules matter for the same reason: nothing is written until every read
    has succeeded.
    """
    programs: list[tuple[int, bytes]] = []
    total = len(numbers)
    for index, number in enumerate(numbers):
        if cancelled is not None and cancelled():
            raise ExportCancelled(
                f"export cancelled before reading user program {number:03d}"
            )
        record = writing.truncate(
            "program",
            writing.read_record(device, "program", number),
            writing.label("program", number),
        )
        if on_read is not None:
            on_read(number, rec.program_name(record).rstrip(), index + 1, total)
        programs.append((number, record))
    return programs


def write_syx(
    path: str,
    programs: Sequence[tuple[int, bytes]],
    *,
    overwrite: bool = False,
) -> int:
    """Concatenate the dumps, write them atomically, return the byte count.

    The messages are :func:`nano.messages.program_dump` of each
    ``(number, record)`` in the order given, so the file's slot numbers
    are the originals: a whole-bank import restores the same numbers, and
    an append import can ignore them.

    An existing ``path`` is refused with :class:`FileExistsError` unless
    ``overwrite`` is set. The file is built as ``path + ".tmp"`` in the
    same directory, flushed, fsynced, then moved into place with
    :func:`os.replace`. Any failure removes the temporary file and
    re-raises, so what is at ``path`` afterwards is either the old file or
    the new one -- never a partial one.
    """
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"{path} already exists; pass overwrite to replace it")
    data = b"".join(
        messages.program_dump(number, record) for number, record in programs
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


def export_selected(  # noqa: PLR0913 -- the device, the slots, the path and three options
    device: Any,
    numbers: Sequence[int],
    path: str,
    *,
    overwrite: bool = False,
    on_read: Callable[[int, str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExportResult:
    """Read the selected slots, then write one file.

    The caller may have chosen the numbers on the main thread (the app does
    this so no worker touches the favourites store); this function only
    reads the device and writes the file.
    """
    programs = read_programs(device, numbers, on_read=on_read, cancelled=cancelled)
    byte_count = write_syx(path, programs, overwrite=overwrite)
    return ExportResult(path=path, count=len(programs), byte_count=byte_count)


def export_favourites(  # noqa: PLR0913 -- the device, the store, the path and three options
    device: Any,
    favorites: Favorites,
    path: str,
    *,
    overwrite: bool = False,
    on_read: Callable[[int, str, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExportResult:
    """The whole operation: numbers -> reads -> one file.

    The order is the plan's: every record is read first and only then is
    the file written, so a read that fails or one that was cancelled
    leaves no file behind.
    """
    return export_selected(
        device,
        favourite_numbers(favorites),
        path,
        overwrite=overwrite,
        on_read=on_read,
        cancelled=cancelled,
    )
