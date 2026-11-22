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
from typing import Final

from nano import messages as m
from nano import params as p
from nano import records as rec
from nano.favorites import Favorite

__all__ = [
    "EditGate",
    "EditRecord",
    "EffectsEditRecord",
    "EffectsEditor",
    "GlobalEditRecord",
    "GlobalEditor",
    "GlobalRow",
    "ImportRecord",
    "MixEditRecord",
    "ProgramEditor",
    "RestoreRecord",
    "choice_text",
]

#: The refusal a locked gate gives. One sentence, and it names the gate and
#: the key that opens it -- the family's rule: a refusal that does not say
#: what to do next is a dead end.
GATE_REFUSAL = "the write gate is locked; press w to arm it"

#: The refusal for a row the specification keeps as a spare for older
#: software. The editor offers none of those rows, and nothing may write
#: the bytes they would have moved.
DELETED_PARAMETER_REFUSAL = (
    "that is a deleted parameter the specification keeps for compatibility"
)


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

    ``favourite`` is the slot's mark and annotations immediately before the
    write. ``favourite_known`` says whether that snapshot was taken, so an
    older or hand-built record cannot clear a mark it never recorded.
    """

    number: int
    previous: bytes
    name: str = ""
    favourite: Favorite | None = None
    favourite_known: bool = False

    @property
    def label(self) -> str:
        """What the undo history calls this edit."""
        return f"user program {self.number:03d}"


@dataclass(frozen=True, slots=True)
class MixEditRecord:
    """One completed mix store, carrying enough to put the mix back.

    The mix counterpart of :class:`EditRecord`: the mix number, the 138
    bytes that were there immediately before the write, and the name those
    bytes spell. ``z`` re-sends them with ``write_mix``; nothing here
    reaches the wire itself.
    """

    number: int
    previous: bytes
    name: str = ""

    @property
    def label(self) -> str:
        """What the undo history calls this edit."""
        return f"mix {self.number:03d}"


@dataclass(frozen=True, slots=True)
class EffectsEditRecord:
    """One completed effects store, carrying enough to put the effects back.

    The effects counterpart of :class:`EditRecord`: the slot, the 65 bytes
    that were there immediately before the write, and the name those bytes
    spell. ``z`` re-sends them with ``write_effects``; nothing here reaches
    the wire itself. ``number`` defaults to slot 0, the effects editor's
    historic single slot; a full restore names every user effects patch.
    """

    previous: bytes
    name: str = ""
    number: int = 0

    @property
    def label(self) -> str:
        """What the undo history calls this edit."""
        if self.number == 0:
            return "the effects settings"
        return f"effects patch {self.number:03d}"


@dataclass(frozen=True, slots=True)
class GlobalEditRecord:
    """One completed global store: the whole set, as it was.

    There is one global set and no number to name it by, so this carries
    the previous record and nothing else. ``z`` re-sends it with
    ``write_global``.
    """

    previous: bytes

    @property
    def label(self) -> str:
        """What the undo history calls this edit."""
        return "the global settings"


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """One import session's undo entry, carrying every edited slot.

    ``z`` restores every record newest-first; a partial failure keeps a
    reduced batch entry with only the edits that succeeded, so ``Z`` still
    undoes the whole session but individual ``z`` may stop early.
    """

    edits: tuple[EditRecord, ...]

    @property
    def label(self) -> str:
        """What the undo history calls this batch."""
        return f"import ({len(self.edits)} edit(s))"


@dataclass(frozen=True, slots=True)
class RestoreRecord:
    """One full-restore session's undo entry, across every record kind.

    Unlike :class:`ImportRecord`, which carries User-program edits only, a
    full restore can replace programs, effects, mixes and the global set in
    one batch. ``z`` sends each previous record back newest-first through
    the kind-specific writer, and a partial failure keeps the reduced entry
    so the next undo can try again.
    """

    edits: tuple[EditRecord | MixEditRecord | EffectsEditRecord | GlobalEditRecord, ...]

    @property
    def label(self) -> str:
        """What the undo history calls this batch."""
        return f"restore ({len(self.edits)} edit(s))"


#: The global rows a store must not present as editable, and the model the
#: spec names beside each one. The NanoSynth is a QS-family member (7) and
#: is not named in the specification at all, so "documented for the QS6/7/8
#: only" means this unit is not among the models it was written for. Writing
#: one of these and reporting success would be a claim nothing supports.
_MODEL_ONLY: Final[tuple[tuple[str, str], ...]] = (
    ("(QS6,7,8 only)", "QS6/7/8"),
    ("(QS7,8,R only)", "QS7/8/R"),
    ("(QSR only)", "QSR"),
)

_GLOBAL_BY_LABEL: Final[dict[str, p.Param]] = {
    param.label: param for param in p.GLOBAL_PARAMS
}


@dataclass(frozen=True, slots=True)
class GlobalRow:
    """One global parameter as the editor shows it.

    ``refusal`` is why a store must leave the row alone, or ``None`` when it
    is writable; ``value`` is ``None`` when this dump does not carry the
    row (dumps from software before 2.00 hold seventeen of the twenty
    bytes). A row that is not written is still *shown*, with its value and
    the reason -- hiding it would teach that the instrument does not have
    it.
    """

    param: p.Param
    value: int | None
    refusal: str | None

    @property
    def writable(self) -> bool:
        """Whether a store may change this row."""
        return self.refusal is None

    @property
    def choice(self) -> str:
        """The row's named value, for the screen's choice column."""
        return choice_text(self.param, self.value)


class GlobalEditor:
    """The one global record, and which of its rows a store may change.

    **Table-driven and small**: the rows are :data:`nano.params.GLOBAL_PARAMS`,
    the widths and ranges are theirs, and the only policy here is which
    rows a whole-record store must not pretend to change. The values are
    two's complement (the spec's own convention for Global), so a signed
    row is sign-extended on the way out of the record and complemented on
    the way back in -- :func:`nano.records.global_record_bytes` does the
    first, :func:`nano.records.encode_bit_field` the second.

    The instrument is silent about whether it kept a global store, exactly
    as it is about a program, so the app reads the record back and compares
    it; this class holds no device and sends nothing.
    """

    def __init__(self, record: bytes) -> None:
        """Wrap the global dump as it was read."""
        rec.check_size(record, 1, "the global settings")
        self._original = bytes(record)
        self._working = bytearray(self._original)

    @property
    def original(self) -> bytes:
        """The record as it was read, untouched -- what a backup preserves."""
        return self._original

    @property
    def size(self) -> int:
        """How many bytes the dump carries (17 on a pre-2.00 unit)."""
        return len(self._original)

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

    def value(self, param: p.Param) -> int | None:
        """One row's current value, sign-extended, or ``None`` if absent."""
        return rec.global_record_bytes(self._working).get(param.label)

    def refusal(self, param: p.Param) -> str | None:
        """Why a store must leave ``param`` alone, or ``None``."""
        for marker, model in _MODEL_ONLY:
            if marker in param.label:
                return f"the spec documents this row for the {model} only"
        if "deleted parameter" in param.label:
            return "a deleted parameter the spec keeps only as a spare"
        if param.function < 0:
            return "the spec gives this row no direct-edit address"
        last_bit = param.bit_address + param.bits - 1
        if last_bit >> 3 >= len(self._original):
            return "not in this dump: it predates the row"
        return None

    def rows(self) -> list[GlobalRow]:
        """Every documented global parameter, in the spec's order."""
        values = rec.global_record_bytes(self._working)
        return [
            GlobalRow(
                param=param,
                value=values.get(param.label),
                refusal=self.refusal(param),
            )
            for param in p.GLOBAL_PARAMS
        ]

    def set_value(self, label: str, value: int) -> str | None:
        """Set one row on the working copy; return the refusal, or ``None``.

        The value is clamped to the row's documented range first (the
        spec's own rule for the ``10`` message, reused here) and then
        stored two's-complement, which is how a Global record carries a
        negative number. A refused row is refused here too, so a caller
        that reaches past the screen's own check still cannot write one.
        """
        param = _GLOBAL_BY_LABEL.get(label)
        if param is None:
            return f"{label!r} is not a global parameter"
        refusal = self.refusal(param)
        if refusal is not None:
            return f"{param.label} was not written: {refusal}"
        clamped = param.clamp(value)
        stored = clamped if clamped >= 0 else clamped + (1 << param.bits)
        rec.encode_bit_field(self._working, param, stored)
        return None


def choice_text(param: p.Param, value: int | None) -> str:
    """The row's named value for ``value``, or a dash.

    Rows without names leave the cell blank -- there is nothing to choose
    from -- and a named row whose value is outside its own list shows ``-``
    rather than a guess. This is the shape the ``p`` editor's choice column
    uses, so both editors read a value the same way.
    """
    if not param.choices:
        return ""
    if value is None or not 0 <= value < len(param.choices):
        return "-"
    return param.choices[value]


#: The mapping from parameter label to Param for the Effects section,
#: used by :class:`EffectsEditor.set_value` for O(1) lookups.
_EFFECT_BY_LABEL: dict[str, p.Param] = {param.label: param for param in p.EFFECT_PARAMS}


class EffectsEditor:
    """The one effects record, and which of its rows a store may change.

    **Table-driven and small**: the rows are :data:`nano.params.EFFECT_PARAMS`,
    the widths and ranges are theirs, and the only policy here is which
    rows a whole-record store must not pretend to change. The values are
    offset-binary (the spec's convention for packed records), so a signed
    row is stored with the offset applied -- :func:`nano.records.effects_record_bytes`
    does the inverse, and :func:`nano.records.encode_bit_field` handles the
    encoding.

    The instrument is silent about whether it kept an effects store, exactly
    as it is about a program, so the app reads the record back and compares
    it; this class holds no device and sends nothing.

    The deleted spares the specification keeps for older software are not
    offered at all: they are not controls, so the editor's rows never touch
    those bytes, and :func:`set_value` refuses a hidden row by name while
    the record keeps carrying the bytes untouched.
    """

    def __init__(self, record: bytes) -> None:
        """Wrap the effects dump as it was read."""
        rec.check_size(record, rec.EFFECTS_BYTES, "the effects settings")
        self._original = bytes(record)
        self._working = bytearray(self._original)

    @property
    def original(self) -> bytes:
        """The record as it was read, untouched -- what a backup preserves."""
        return self._original

    @property
    def size(self) -> int:
        """How many bytes the dump carries."""
        return len(self._original)

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

    def value(self, param: p.Param) -> int | None:
        """One row's current value, with offset applied, or ``None`` if absent."""
        return rec.effects_record_bytes(self._working).get(param.label)

    def refusal(self, param: p.Param) -> str | None:
        """Why a store must leave ``param`` alone, or ``None``."""
        if "deleted parameter" in param.label:
            return DELETED_PARAMETER_REFUSAL
        if param.function < 0:
            return "the spec gives this row no direct-edit address"
        last_bit = param.bit_address + param.bits - 1
        if last_bit >> 3 >= len(self._original):
            return "not in this dump: it predates the row"
        return None

    def rows(self) -> list:
        """The rows the editor offers, in the spec's order.

        The deleted spares the specification keeps for older software are
        not offered: they are not controls, so the view hides them rather
        than list a row it cannot write. The record still carries their
        bytes either way; only this list does not offer them.
        """
        values = rec.effects_record_bytes(self._working)
        return [
            type(
                "EffectsRow",
                (),
                {
                    "param": param,
                    "value": values.get(param.label),
                    "choice": choice_text(param, values.get(param.label)),
                    "refusal": self.refusal(param),
                    "writable": self.refusal(param) is None,
                },
            )
            for param in p.EFFECT_PARAMS
            if "deleted parameter" not in param.label
        ]

    def set_value(self, label: str, value: int) -> str | None:
        """Set one row on the working copy; return the refusal, or ``None``.

        The value is clamped to the row's documented range first (the
        spec's own rule for the ``10`` message, reused here) and then
        stored with the offset applied, which is how an Effects record
        carries a signed value. A refused row is refused here too, so a
        caller that reaches past the screen's own check still cannot
        write one.

        A hidden row is a deleted parameter, and a deleted parameter is
        not a control, so it is refused by name here rather than offered or
        written: the specification keeps the bytes for older software, and
        the store must leave them alone.
        """
        param = _EFFECT_BY_LABEL.get(label)
        if param is None:
            return f"{label!r} is not an effects parameter"
        if "deleted parameter" in param.label:
            return DELETED_PARAMETER_REFUSAL
        refusal = self.refusal(param)
        if refusal is not None:
            return f"{param.label} was not written: {refusal}"
        clamped = param.clamp(value)
        stored = clamped if clamped >= 0 else clamped + (1 << param.bits)
        rec.encode_bit_field(self._working, param, stored)
        return None
