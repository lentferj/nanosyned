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

"""The write loop, once, for the CLI and the browser alike.

**A store is never the first thing that happens to a slot.** The order is the
family's and every step of it is load-bearing:

1. read every destination in full -- a slot that cannot be read is not
   written, because a write that cannot be undone is not performed;
2. back every destination up, once per slot per session, before the first
   store;
3. store, and store only the records whose read succeeded;
4. read each record back and compare it byte for byte.

Two callers drive this module, and they want different shapes of the same
loop. ``nanocli send`` and ``nanocli import`` want the batched order above,
because the plan -- "old name -> new name" for every slot -- has to be printed
between step 1 and step 2. The browser's import screen wants one record at a
time, so a cooperative cancel can stop between records rather than in the
middle of a store. :func:`run` is both: ``read_first=True`` (the default)
batches, ``read_first=False`` streams.

**Device trouble does not raise out of :func:`run`.** Every failure becomes a
:class:`Result` carrying the message and the stage that failed, so a caller
can print it and carry on. What the caller does with that is its own policy:
``send`` stops at the first failed stage, which is what it did before this
module existed, and a progress screen counts the failures and finishes the
rest.

This module imports :mod:`nano.backup`, :mod:`nano.messages`,
:mod:`nano.records` and :mod:`nano.verify`. It must not import Textual,
argparse or the CLI: the TUI and the command line are two callers of one
loop, not two loops.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nano import backup as bk
from nano import messages as m
from nano import records as rec
from nano import verify

__all__ = [
    "RECORD_BYTES",
    "RECORD_NAMES",
    "Result",
    "Step",
    "frame",
    "label",
    "read_record",
    "record_name",
    "run",
    "save_backup",
    "truncate",
    "write_record",
]

#: The four record kinds the write commands speak, and the byte size of each.
#: These are the unpacked sizes: what a dump carries and what the store
#: encoders pack again.
RECORD_BYTES = {
    "program": rec.PROGRAM_BYTES,
    "mix": rec.MIX_BYTES,
    "effects": rec.EFFECTS_BYTES,
    "global": rec.GLOBAL_BYTES,
}

#: What a person calls each kind, for a line that has to name one.
RECORD_NAMES = {
    "program": "user program",
    "mix": "mix",
    "effects": "effects patch",
    "global": "global settings",
}


class Step(Protocol):
    """What :func:`run` needs from one planned record.

    Two planners feed this loop: :class:`nano.importplan.Step` spells the
    destination ``target`` and the CLI's own plan spells it ``number``. Both
    are accepted -- :func:`_slot` reads either -- so a plan travels here
    unchanged and the executor does not get to pick a favourite caller.
    """

    kind: str
    record: bytes


@dataclass
class Result:
    """One step, from the read that found it to the bytes that came back.

    ``stage`` names the last thing that happened: ``"read"``, ``"backup"``,
    ``"store"``, ``"read-back"``, ``"verify"`` or ``"verified"``. A stage that
    failed leaves ``failure`` set to the message the device or the comparison
    gave, so ``failure is None`` is the whole test for "this one is fine".
    ``previous``, ``backup`` and ``read_back`` are the evidence from each
    stage: what the slot held, where that was saved, and what the unit said
    afterwards.

    ``sentence`` is :func:`nano.verify.describe`'s one line about the
    read-back, kept here so the CLI and the browser say the same thing about
    the same bytes. ``sent`` is true once a store was actually sent, which is
    what an undo log must not guess at.
    """

    kind: str
    number: int | None
    record: bytes
    previous: bytes = b""
    read_back: bytes | None = None
    backup: str | None = None
    failure: str | None = None
    stage: str = "planned"
    sentence: str = ""
    sent: bool = False


def truncate(kind: str, data: bytes, what: str) -> bytes:
    """A record at its documented size, or ``ProtocolError``.

    A dump is padded to a whole packing group, so the tail is dropped. A
    *short* record is refused: writing one would put whatever follows it in
    the buffer into the slot.
    """
    size = RECORD_BYTES[kind]
    rec.check_size(data, size, what)
    return bytes(data[:size])


def record_name(kind: str, record: bytes) -> str:
    """The name inside a record, or ``""`` for a kind that has none."""
    if kind == "program":
        return rec.program_name(record).rstrip()
    if kind == "mix":
        return rec.mix_name(record).rstrip()
    return ""


def label(kind: str, number: int | None, name: str = "") -> str:
    """One destination, by the name the unit itself uses for it."""
    if kind == "global":
        return "the global settings"
    where = f"{RECORD_NAMES[kind]} {number:03d}"
    return f"{where} {name!r}" if name else where


def _read_effects(device: Any, number: int) -> bytes:
    """One effects patch, through whichever read the device offers.

    ``nano.bridge`` has no ``read_effects``: the request/reply pair is the
    same one ``read_program`` uses, so the bridge's own ``request`` serves
    it without a second copy of the policy here. A device that cannot answer
    -- the demo is one -- says so rather than inventing bytes.
    """
    reader = getattr(device, "read_effects", None)
    if reader is not None:
        return bytes(reader(number))
    request = getattr(device, "request", None)
    if request is None:
        raise LookupError(
            "this device cannot read an effects patch; only the MIDI bridge "
            "answers that request"
        )
    packet = request(
        m.effects_dump_request(number),
        m.Function.USER_EFFECTS_DUMP,
        number=number,
    )
    data = packet.data()
    rec.check_size(data, rec.EFFECTS_BYTES, "an effects patch")
    return bytes(data[: rec.EFFECTS_BYTES])


def read_record(device: Any, kind: str, number: int | None) -> bytes:
    """Read one record off the unit, by kind. Silent."""
    if kind == "program":
        return bytes(device.read_program(number))
    if kind == "mix":
        return bytes(device.read_mix(number))
    if kind == "effects":
        return _read_effects(device, number)  # type: ignore[arg-type]
    return bytes(device.read_global())


def frame(kind: str, number: int | None, record: bytes) -> bytes:
    """The Alesis message that carries ``record`` back to the unit."""
    if kind == "program":
        return m.program_dump(number, record)  # type: ignore[arg-type]
    if kind == "mix":
        return m.mix_dump(number, record)  # type: ignore[arg-type]
    if kind == "effects":
        return m.effects_dump(number, record)  # type: ignore[arg-type]
    return m.global_dump(record)


def write_record(device: Any, kind: str, number: int | None, record: bytes) -> None:
    """Store one record. **The unit keeps this.**"""
    if kind == "program":
        device.write_program(number, record)
    elif kind == "mix":
        device.write_mix(number, record)
    elif kind == "effects":
        device.write_effects(number, record)
    else:
        device.write_global(record)


def save_backup(kind: str, number: int | None, record: bytes) -> str:
    """Save the destination's current bytes before anything replaces them."""
    name = record_name(kind, record) or label(kind, number)
    slot = "GLOBAL" if number is None else f"{kind.upper()}:{number:03d}"
    return bk.save(
        slot,
        kind=kind,
        name=name,
        blocks={kind: record},
        source="nanocli (before write)",
    )


def _slot(step: Step) -> int | None:
    """The destination number, under either plan's spelling of it."""
    number = getattr(step, "number", None)
    if number is None:
        number = getattr(step, "target", None)
    return number


class _Session:
    """One run: the results so far, and the backups this session took.

    ``backups`` is what makes "once per slot per session" true: a second step
    for a slot reuses the first step's path instead of writing a second file
    beside it, so one undo point covers the slot however many records land in
    it.
    """

    def __init__(  # noqa: PLR0913 -- the device, its results and four hooks
        self,
        device: Any,
        results: list[Result],
        *,
        on_step: Callable[[Result], None] | None,
        on_result: Callable[[Result], None] | None,
        on_phase: Callable[[str, list[Result]], None] | None,
        cancel: Any,
    ) -> None:
        self.device = device
        self.results = results
        self.on_step = on_step
        self.on_result = on_result
        self.on_phase = on_phase
        self.cancel = cancel
        self.backups: dict[tuple[str, int | None], str] = {}

    def cancelled(self) -> bool:
        """Whether the caller asked to stop. Never consulted mid-store."""
        return self.cancel is not None and bool(self.cancel.is_set())

    def _told(self, result: Result) -> None:
        """Tell the caller one stage of ``result`` just finished."""
        if self.on_step is not None:
            self.on_step(result)

    def _finished(self, result: Result) -> None:
        """Tell the caller this step's outcome is final."""
        if self.on_result is not None:
            self.on_result(result)

    def _phase(self, name: str) -> None:
        """Tell a batched caller that one whole phase is behind it."""
        if self.on_phase is not None:
            started = [item for item in self.results if item.stage != "planned"]
            self.on_phase(name, started)

    def _what(self, result: Result) -> str:
        """How this step's destination is named in a refusal."""
        return f"the {RECORD_NAMES[result.kind]} at {label(result.kind, result.number)}"

    def _fail(self, result: Result, stage: str, exc: Exception) -> None:
        """Record the stage that failed, and let the caller hear it once."""
        result.failure = str(exc)
        result.stage = stage
        self._told(result)
        self._finished(result)

    def read(self, result: Result) -> bytes | None:
        """Read the destination in full. ``None`` means do not write it."""
        try:
            result.previous = truncate(
                result.kind,
                read_record(self.device, result.kind, result.number),
                self._what(result),
            )
        except Exception as exc:  # the port, the unit or a short record
            self._fail(result, "read", exc)
            return None
        result.stage = "read"
        self._told(result)
        return result.previous

    def back_up(self, result: Result, previous: bytes) -> bool:
        """Save the destination, once per slot per session."""
        key = (result.kind, result.number)
        if key not in self.backups:
            try:
                self.backups[key] = save_backup(result.kind, result.number, previous)
            except Exception as exc:  # the disk, not the unit
                self._fail(result, "backup", exc)
                return False
        result.backup = self.backups[key]
        result.stage = "backup"
        self._told(result)
        return True

    def store(self, result: Result) -> None:
        """Store, read back and compare. **The only stage the unit keeps.**"""
        try:
            write_record(self.device, result.kind, result.number, result.record)
        except Exception as exc:  # the port, the unit or a refused slot
            self._fail(result, "store", exc)
            return
        result.sent = True
        result.stage = "store"
        self._told(result)
        try:
            result.read_back = truncate(
                result.kind,
                read_record(self.device, result.kind, result.number),
                self._what(result),
            )
        except Exception as exc:  # the store landed; the answer did not
            self._fail(result, "read-back", exc)
            return
        result.sentence = verify.describe(
            result.record,
            result.read_back,
            what=label(
                result.kind,
                result.number,
                record_name(result.kind, result.record),
            ),
        )
        if verify.mismatches(result.record, result.read_back):
            result.failure = result.sentence
            result.stage = "verify"
        else:
            result.stage = "verified"
        self._told(result)
        self._finished(result)

    def read_everything(self) -> None:
        """Every destination, then every backup, then the stores.

        This is the CLI's order and the reason for it is the module
        docstring: a slot that cannot be read is not written, and the plan is
        printed from what was read, before the first store.
        """
        readable: list[tuple[Result, bytes]] = []
        for result in self.results:
            if self.cancelled():
                return
            previous = self.read(result)
            if previous is not None:
                readable.append((result, previous))
        self._phase("read")
        backed: list[Result] = []
        for result, previous in readable:
            if self.cancelled():
                return
            if self.back_up(result, previous):
                backed.append(result)
        self._phase("backup")
        for result in backed:
            if self.cancelled():
                return
            self.store(result)
        self._phase("store")

    def stream(self) -> None:
        """One step at a time, so a cancel stops before the next one.

        The per-step order is the batched order folded into one turn, and the
        cancel flag is read between steps only -- a record half-stored is
        worse than a record not started.
        """
        for result in self.results:
            if self.cancelled():
                return
            previous = self.read(result)
            if previous is None:
                continue
            if not self.back_up(result, previous):
                continue
            self.store(result)


def run(  # noqa: PLR0913 -- the device, the plan and its five hooks
    device: Any,
    steps: Sequence[Step],
    *,
    on_step: Callable[[Result], None] | None = None,
    on_result: Callable[[Result], None] | None = None,
    on_phase: Callable[[str, list[Result]], None] | None = None,
    cancel: Any = None,
    read_first: bool = True,
) -> list[Result]:
    """Read, back up, store and verify ``steps``; return what happened.

    ``device`` is the bridge or the demo -- anything with the four reads and
    the four stores. ``steps`` is a plan: :class:`nano.importplan.Step` or the
    CLI's own, as long as each one names a ``kind``, a ``record`` and a
    destination (``number`` or ``target``).

    ``on_step`` hears about each stage as it finishes, which is what a
    progress line draws from; ``on_result`` hears once per step, when its
    outcome is final; ``on_phase`` hears after the read, backup and store
    phases of a batched run, which is where the CLI prints the plan and the
    backup paths. ``cancel`` is any object with ``is_set()`` and is read
    between steps, never mid-store.

    With ``read_first`` (the default) nothing is stored until every
    destination has been read. A streaming caller passes ``read_first=False``
    and gets each record read, backed up, stored and checked before the next
    one starts; that is the shape a TUI needs, where the whole point is that
    pressing ``esc`` after record three leaves records four onward alone.

    The returned list holds the steps that were attempted, in plan order. A
    cancelled or short run therefore returns a prefix -- the results that
    really happened -- and never places a step that was not started.
    """
    results = [
        Result(kind=step.kind, number=_slot(step), record=bytes(step.record))
        for step in steps
    ]
    session = _Session(
        device,
        results,
        on_step=on_step,
        on_result=on_result,
        on_phase=on_phase,
        cancel=cancel,
    )
    if read_first:
        session.read_everything()
    else:
        session.stream()
    return [result for result in results if result.stage != "planned"]
