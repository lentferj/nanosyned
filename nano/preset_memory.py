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

"""Content-addressed memory of seen User programs.

The favourites database answers "which slots show a heart". This sidecar
answers a different question: "have I seen these bytes before, and did I
favourite them?". It is keyed by the SHA-256 of the canonical 350-byte
program, not by a slot. That is what lets an import put the same preset in a
different slot and have the heart come back.

The database is deliberately separate from ``favorites.db``. The shared
favourites schema belongs to every tool in the family; this is a
nanosyned-only memory and must not make older siblings refuse the shared
file. It lives beside the favourites database in the application's data
directory, is versioned from the first release, and is safe to call from the
app's main thread and its import worker.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

from nano import favorites as favs
from nano import identity

__all__ = ["MEMORY_NAME", "MemoryEntry", "PresetMemory", "default_path"]

#: The sidecar's filename, beside ``favorites.db``.
MEMORY_NAME = "preset-memory.db"

#: Bumped whenever the schema changes. A newer file is refused, not guessed
#: at, because a memory is user work.
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MemoryEntry:
    """One content identity and the user's annotations for it."""

    digest: str
    name: str
    favourite: bool
    rating: int
    tags: str
    note: str
    first_seen: float
    last_seen: float
    seen_count: int


class _LockedConnection:
    """A SQLite connection that one process may use from several threads."""

    def __init__(self, path: str) -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row

    def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, parameters).fetchone()

    def rows(self, sql: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._db.execute(sql, parameters).fetchall())

    def script(self, sql: str) -> None:
        with self._lock:
            self._db.executescript(sql)

    def commit(self) -> None:
        with self._lock:
            self._db.commit()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Run a block under the connection lock and commit it once."""
        with self._lock:
            try:
                yield
            except BaseException:
                self._db.rollback()
                raise
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()


class PresetMemory:
    """A content-addressed memory of seen programs, in its own SQLite file.

    ``path`` is injectable so tests never touch the user's real data. A
    missing parent directory is created; a newer schema is refused.
    """

    MEMORY_NAME: ClassVar[str] = MEMORY_NAME

    def __init__(self, path: str | None = None) -> None:
        self.path = path or default_path()
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._db = _LockedConnection(self.path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def _migrate(self) -> None:
        row = self._db.execute("PRAGMA user_version")
        current = int(row[0]) if row is not None else 0
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} was written by a newer preset memory "
                f"(schema {current}, this build understands {SCHEMA_VERSION}). "
                f"Refusing to touch it rather than risk dropping data."
            )
        if current < 1:
            self._db.script(
                """
                CREATE TABLE IF NOT EXISTS preset_memory (
                    digest      TEXT PRIMARY KEY,
                    name        TEXT NOT NULL DEFAULT '',
                    favourite   INTEGER NOT NULL DEFAULT 0,
                    rating      INTEGER NOT NULL DEFAULT 0,
                    tags        TEXT NOT NULL DEFAULT '',
                    note        TEXT NOT NULL DEFAULT '',
                    first_seen  REAL NOT NULL DEFAULT 0,
                    last_seen   REAL NOT NULL DEFAULT 0,
                    seen_count  INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS slot_content (
                    bank_id     TEXT NOT NULL,
                    number      INTEGER NOT NULL,
                    digest      TEXT NOT NULL,
                    updated_at  REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (bank_id, number)
                );
                CREATE INDEX IF NOT EXISTS slot_content_digest
                    ON slot_content (digest);
                """
            )
        self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

    def close(self) -> None:
        try:
            self._db.commit()
        finally:
            self._db.close()

    def __enter__(self) -> PresetMemory:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def remember(self, record: bytes, *, name: str | None = None) -> MemoryEntry:
        """Record that these program bytes have been seen.

        A new digest starts as seen but not favourite. An existing row keeps
        its favourite flag and annotations; a non-empty ``name`` refreshes
        the label, and the seen count and last-seen time advance.
        """
        digest = identity.digest(record)
        label = name if name is not None else identity.program_name(record)
        fresh_name = label.strip()
        now = time.time()
        with self._db.transaction():
            row = self._db.execute(
                "SELECT name, favourite, rating, tags, note, first_seen, "
                "last_seen, seen_count FROM preset_memory WHERE digest = ?",
                (digest,),
            )
            if row is None:
                self._db.execute(
                    "INSERT INTO preset_memory "
                    "(digest, name, favourite, rating, tags, note, "
                    " first_seen, last_seen, seen_count) "
                    "VALUES (?, ?, 0, 0, '', '', ?, ?, 1)",
                    (digest, fresh_name, now, now),
                )
            else:
                self._db.execute(
                    "UPDATE preset_memory SET name = ?, last_seen = ?, "
                    "seen_count = seen_count + 1 WHERE digest = ?",
                    (fresh_name if fresh_name else row["name"], now, digest),
                )
        entry = self.get(digest)
        if entry is None:  # pragma: no cover -- the insert/update just ran
            raise RuntimeError("preset memory lost a row it just wrote")
        return entry

    def get(self, digest: str) -> MemoryEntry | None:
        row = self._db.execute(
            "SELECT digest, name, favourite, rating, tags, note, first_seen, "
            "last_seen, seen_count FROM preset_memory WHERE digest = ?",
            (digest,),
        )
        return None if row is None else self._entry(row)

    def set_favourite(
        self,
        digest: str,
        favourite: bool,
        *,
        rating: int | None = None,
        tags: str | None = None,
        note: str | None = None,
    ) -> MemoryEntry:
        """Set the content-level favourite flag, preserving what is omitted."""
        if rating is not None and not 0 <= int(rating) <= 5:
            raise ValueError(f"rating {rating} is outside 0-5")
        row = self._db.execute(
            "SELECT digest FROM preset_memory WHERE digest = ?", (digest,)
        )
        if row is None:
            raise KeyError(f"no preset memory for {digest}")
        self._db.execute(
            "UPDATE preset_memory SET favourite = ?, "
            "rating = COALESCE(?, rating), tags = COALESCE(?, tags), "
            "note = COALESCE(?, note) WHERE digest = ?",
            (
                1 if favourite else 0,
                None if rating is None else int(rating),
                tags,
                note,
                digest,
            ),
        )
        self._db.commit()
        entry = self.get(digest)
        if entry is None:  # pragma: no cover -- the row existed above
            raise RuntimeError("preset memory lost a row it just updated")
        return entry

    def favourites(self) -> list[MemoryEntry]:
        """Every content identity currently marked favourite."""
        rows = self._db.rows(
            "SELECT digest, name, favourite, rating, tags, note, first_seen, "
            "last_seen, seen_count FROM preset_memory "
            "WHERE favourite = 1 ORDER BY last_seen DESC, digest"
        )
        return [self._entry(row) for row in rows]

    def seen(self) -> list[MemoryEntry]:
        """Every content identity ever seen, newest first."""
        rows = self._db.rows(
            "SELECT digest, name, favourite, rating, tags, note, first_seen, "
            "last_seen, seen_count FROM preset_memory "
            "ORDER BY last_seen DESC, digest"
        )
        return [self._entry(row) for row in rows]

    def bind_slot(self, bank_id: str, number: int, digest: str) -> None:
        """Remember which content currently sits in a User slot."""
        if bank_id != "USER":
            raise ValueError(f"{bank_id} is not the writable User bank")
        if not 0 <= number <= 126:
            raise ValueError(f"user program {number} is outside 000-126")
        row = self._db.execute(
            "SELECT 1 FROM preset_memory WHERE digest = ?", (digest,)
        )
        if row is None:
            raise KeyError(f"no preset memory for {digest}")
        self._db.execute(
            "INSERT INTO slot_content (bank_id, number, digest, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT (bank_id, number) DO UPDATE SET "
            "digest = excluded.digest, updated_at = excluded.updated_at",
            (bank_id, number, digest, time.time()),
        )
        self._db.commit()

    def slot_digest(self, bank_id: str, number: int) -> str | None:
        row = self._db.execute(
            "SELECT digest FROM slot_content WHERE bank_id = ? AND number = ?",
            (bank_id, number),
        )
        return None if row is None else str(row["digest"])

    def slots_for(self, digest: str) -> list[tuple[str, int]]:
        rows = self._db.rows(
            "SELECT bank_id, number FROM slot_content WHERE digest = ? "
            "ORDER BY bank_id, number",
            (digest,),
        )
        return [(str(row["bank_id"]), int(row["number"])) for row in rows]

    def forget_slot(self, bank_id: str, number: int) -> None:
        self._db.execute(
            "DELETE FROM slot_content WHERE bank_id = ? AND number = ?",
            (bank_id, number),
        )
        self._db.commit()

    @staticmethod
    def _entry(row: sqlite3.Row) -> MemoryEntry:
        return MemoryEntry(
            digest=str(row["digest"]),
            name=str(row["name"]),
            favourite=bool(row["favourite"]),
            rating=int(row["rating"]),
            tags=str(row["tags"]),
            note=str(row["note"]),
            first_seen=float(row["first_seen"]),
            last_seen=float(row["last_seen"]),
            seen_count=int(row["seen_count"]),
        )


def default_path() -> str:
    """Where the sidecar lives unless ``--preset-memory`` says otherwise."""
    return os.path.join(favs.data_dir(), MEMORY_NAME)
