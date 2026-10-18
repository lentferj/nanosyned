# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The gate/editor split is the shape of the sibling p2ked master editor and
# emorphed's edit module, which keep the rules out of the TUI:
#   Copyright (C) 2026  p2ked / emorphed contributors
#                                      - GPL-2.0-or-later
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

"""The write rules for one program: a gate, an editor, a record to undo.

**PURE data and policy.** Nothing here opens a MIDI port, imports Textual, or
touches a file. It is importable and testable without a terminal, which is the
whole point: the rules that decide whether a byte goes to the instrument are
the ones a test must be able to pin, and a rule buried in a key handler is a
rule that is only exercised by pressing the key.

The family shape is p2ked's master editor and emorphed's edit module: the app
owns the worker, the exchange and the status bar; this module owns *what* may
be changed and *whether* it may be sent. The wire stays in
:mod:`nano.bridge`, the comparison stays in :mod:`nano.verify`, and the backup
stays in :mod:`nano.backup`.

Writing to this instrument is destructive and unacknowledged: the unit answers
a store with silence whether it took it or not, so every rule here exists to
make the caller's next move deliberate.
"""

from __future__ import annotations

from dataclasses import dataclass

from nano import messages as m
from nano import records as rec

__all__ = ["EditGate", "EditRecord", "ProgramEditor"]

#: The refusal a locked gate gives. One sentence, and it names the gate and
#: the key that opens it -- the family's rule: a refusal that does not say
#: what to do next is a dead end.
GATE_REFUSAL = "the write gate is locked; press w to arm it"


class EditGate:
    """The fence in front of every write. Locked unless somebody arms it.

    **Nothing is sent while the gate is locked.** The check happens on the
    main thread before a worker is spawned, so a refused action sends no
    message at all -- not a store, not a read, nothing.

    The default is locked, and :func:`check` is the one question a caller
    asks. It returns a sentence rather than ``False`` because a refusal is
    shown to somebody: "the write gate is locked; press w to arm it" tells
    them what happened and what to do about it.
    """

    def __init__(self, *, armed: bool = False) -> None:
        self._armed = armed

    @property
    def armed(self) -> bool:
        """Whether a write may be sent right now."""
        return self._armed

    def toggle(self) -> bool:
        """Flip the gate; return its new state."""
        self._armed = not self._armed
        return self._armed

    def describe(self) -> str:
        """The gate's state, as one short line for the status bar."""
        return "write gate armed" if self._armed else "write gate locked"

    def check(self) -> str | None:
        """``None`` when armed, else the refusal sentence. Never sends."""
        if self._armed:
            return None
        return GATE_REFUSAL


class ProgramEditor:
    """One 350-byte User program, with its unedited copy kept beside it.

    ``original`` is the record exactly as the unit sent it; ``record()`` is
    the working copy. Only the ten-character name is editable here, so
    ``record()`` differs from ``original`` in the name bits and nowhere else
    -- the sound blocks travel through untouched, which is the same decision
    :mod:`nano.records` makes when it refuses to decode them.

    A failed rename leaves the working copy as it was. :func:`set_name`
    encodes into a copy first: :func:`nano.messages.encode_name` writes
    character by character and raises part-way through a bad name, so
    encoding in place would leave the first few characters already changed
    when the refusal came back.
    """

    def __init__(self, number: int, record: bytes) -> None:
        """Wrap the record read from user program ``number``."""
        rec.check_size(record, rec.PROGRAM_BYTES, "a program")
        #: Which of the 128 User programs this is.
        self.number = number
        self._original = bytes(record[: rec.PROGRAM_BYTES])
        self._working = bytearray(self._original)

    @property
    def original(self) -> bytes:
        """The record as it was read, untouched -- what a backup preserves."""
        return self._original

    @property
    def name(self) -> str:
        """The current name, padded to the instrument's ten characters."""
        return rec.program_name(self._working)

    def set_name(self, text: str) -> str | None:
        """Rename the working copy; return the refusal, or ``None``.

        The instrument's charset runs from space to ``DEL`` and a name is
        :data:`nano.messages.NAME_CHARS` characters, so
        :func:`nano.messages.encode_name` pads a short name and truncates a
        long one. A character outside the set raises
        :class:`nano.messages.ProtocolError`; that message is returned
        verbatim for the caller to show (escaped at the widget, since the
        character quoted in it came from the user).
        """
        proposed = bytearray(self._working)
        try:
            m.encode_name(proposed, text)
        except m.ProtocolError as exc:
            return str(exc)
        self._working[:] = proposed
        return None

    def record(self) -> bytes:
        """The working copy, ready to send."""
        return bytes(self._working)

    @property
    def dirty(self) -> bool:
        """Whether anything has been changed since the record was read."""
        return self._working != self._original

    def reset(self) -> None:
        """Discard the edits; the working copy becomes the record again."""
        self._working[:] = self._original


@dataclass(frozen=True, slots=True)
class EditRecord:
    """One completed store, carrying enough to put the slot back.

    This is what an :class:`vinsynlib.undo.Record` carries as its payload: the
    slot number, the bytes that were there immediately before the write, and
    the name those bytes spell. ``z`` re-sends :attr:`previous`; nothing here
    reaches the wire itself.
    """

    number: int
    previous: bytes
    name: str = ""

    @property
    def label(self) -> str:
        """What the undo history calls this edit."""
        return f"user program {self.number:03d}"
