# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The backup envelope is vinsynlib's: this file binds it rather than
# copying it (vinsynlib/src/vinsynlib/backup.py, GPL-2.0-or-later).
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""Backups: the family's envelope, this unit's kinds and directory.

The on-disk shape is :mod:`vinsynlib.backup`'s and lives in one place: a
JSON object carrying a version byte (:data:`FORMAT`) that a future reader
checks before trusting it, the record's blocks base64-encoded inside it,
and a filename that never overwrites one already there. None of that is
restated here -- an envelope copied into a second module is an envelope
that drifts.

What this module adds is what the library cannot know:

* the directory, ``nanosyned``'s per-platform settings directory with
  ``backups`` beneath it -- not the checkout, which ``git clean`` empties;
* the kinds of record this instrument can back up (:data:`KINDS`):
  ``program``, ``mix``, ``effects`` and ``global``, each carried in a block
  of the same name. The library is device-agnostic and has no opinion on
  what those blocks hold; this unit's SysEx records do.

**Nothing here talks to MIDI.** It serialises the blocks it is handed and
reads them back; the bridge and the CLI do the round trips. That keeps a
backup testable with no hardware.
"""

from __future__ import annotations

import os

from vinsynlib import backup as _backup
from vinsynlib import config as _config
from vinsynlib.backup import FORMAT, Backup

__all__ = [
    "FORMAT",
    "KINDS",
    "Backup",
    "backup_dir",
    "list_backups",
    "load",
    "save",
]

#: The record kinds this unit can back up. Each names both the record and
#: the block that carries it inside the envelope, so a program backup writes
#: one ``program`` block, a mix backup one ``mix`` block, and so on.
KINDS: tuple[str, ...] = ("program", "mix", "effects", "global")


def backup_dir() -> str:
    """Where this project writes backups.

    ``nanosyned``'s per-platform settings directory, with ``backups``
    beneath it -- so the restore points sit beside ``config.toml`` and
    **not** in the checkout, which ``git clean`` empties. The directory is
    not created here: deciding where a file goes must not decide that it
    exists. :func:`save` creates it, through the library's
    ``os.makedirs(..., exist_ok=True)``.
    """
    return os.path.join(_config.config_dir("nanosyned"), "backups")


def save(  # noqa: PLR0913
    slot: str,
    *,
    kind: str,
    name: str,
    blocks: dict[str, bytes],
    device_id: str = "",
    source: str = "",
) -> str:
    """Write one record's blocks into :func:`backup_dir`, return its path.

    ``kind`` is one of :data:`KINDS` and is written into the envelope, where
    :func:`load` and :func:`list_backups` report it; ``slot`` and ``name``
    label the file. The envelope, the version byte and the never-overwrite
    rule are the library's (:func:`vinsynlib.backup.save`); this chooses
    only the directory.
    """
    return _backup.save(
        backup_dir(),
        kind=kind,
        slot=slot,
        name=name,
        device_id=device_id,
        source=source,
        blocks=blocks,
    )


def load(path: str) -> Backup:
    """Read one backup back.

    ``path`` is what :func:`save` returned or what :func:`list_backups`
    reports. The version check, the base64 decoding and the refusal of a
    malformed file are the library's (:func:`vinsynlib.backup.load`).
    """
    return _backup.load(path)


def list_backups() -> list[Backup]:
    """Every backup in :func:`backup_dir`, newest first.

    A file that cannot be read is listed with its ``error`` rather than
    dropped: a restore point you cannot read is exactly the thing to be
    told about. That is the library's rule
    (:func:`vinsynlib.backup.list_backups`), kept here while the caller is
    spared the directory argument.
    """
    return _backup.list_backups(backup_dir())
