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
# nanosyned is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.

"""Content identity for one User program record.

The identity is the SHA-256 of the canonical 350-byte unpacked program. The
name is part of the record, so a rename creates a new identity; that is
deliberate for version 1. A name-insensitive hash would collapse two presets
that differ only by their label, and the memory is meant to answer "the same
bytes", not "the same approximate sound".

Nothing here reads a device, opens a file, or knows about the favourites
database. The digest is an ordinary value the memory store keys on.
"""

from __future__ import annotations

import hashlib

from nano import records as rec

__all__ = ["canonical", "digest", "program_name"]


def canonical(record: bytes) -> bytes:
    """The 350 bytes a program identity is computed from.

    A dump may carry packing padding past the record; that tail is not part
    of the identity. A short record is refused rather than padded, because
    every byte past the end would otherwise read as whatever followed it.
    """
    rec.check_size(record, rec.PROGRAM_BYTES, "a program")
    return bytes(record[: rec.PROGRAM_BYTES])


def digest(record: bytes) -> str:
    """The lower-case SHA-256 of the canonical program record."""
    return hashlib.sha256(canonical(record)).hexdigest()


def program_name(record: bytes) -> str:
    """The record's ten-character name, with its padding removed."""
    return rec.program_name(record).rstrip()
