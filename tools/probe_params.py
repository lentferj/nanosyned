#!/usr/bin/env python3
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

"""Probe one parameter row, and put the edit buffer back afterwards.

**What this tool writes: nothing that is kept.** It sends three opcodes
and no others: ``10`` (MIDI Edit), which moves one parameter in the
unit's volatile edit buffer; ``02`` (Edit Program Dump), a *load* that
puts that buffer back to the reference read at the start of the run; and
``0D`` (Mode Select), which chooses the mode the rows live in and writes
nothing to memory. The store -- opcode ``00``, the message that
overwrites a user program -- is never built, never sent and never named
here. The user's bank is not written, not once, by anything on this
path.

The method is ``docs/PARAMETER_VERIFICATION_PLAN.md``'s section 5: put
the unit in the right mode, read the edit buffer, prove the restore path
with *no probe at all*, then per row -- ``10`` with a value that flips
every bit of the field, a short settle (the unit is silent under a
``10``), read again, diff, restore, read back, compare. The diff is the
verdict:

``confirmed``
    exactly the row's own bits moved, so the table's address and the
    unit's field agree.
``partial``
    only some of the row's bits moved -- a field wider than its value
    range lets the flip reach, or a row that is wrong.
``mismatch``
    a bit *outside* the row's field moved. A wrong table address looks
    like this. It is a finding to record, not a reason to edit the
    table.
``no-change``
    nothing moved at all.

A verdict here is one before/after observation: it confirms an address,
and promotion to ``verified`` in ``nano/params.py`` is a separate,
deliberate act (plan V11). This tool does not edit the tables, and it
does not store anything.

**What it needs from a device** is four methods -- ``read_edit_program``,
``write_edit_program``, ``midi_edit`` and ``mode_select``.
``nano.bridge.NanoBridge`` has them; so does ``--demo``'s
:class:`EditingDemo`, which applies each field to an in-process buffer
so the walk-through can be read, printed and tested without hardware.

Usage::

    .venv/bin/python tools/probe_params.py --demo --mode global --limit 3
    .venv/bin/python tools/probe_params.py --port "X:1" --mode global --yes
    .venv/bin/python tools/probe_params.py --port "X:1" --all --yes \
        --backup-dir /tmp/probe --json probes.json

Exit status is 0 only when at least one row was probed, every verdict is
``confirmed`` and every restore verified; 1 for any other completed run;
2 when the *pre-flight* restore could not be verified, which means
nothing was probed at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import bridge as b
from nano import messages as m
from nano import params
from nano import records as rec
from nanosyned.demo import demo_name

#: The pause between the ``10`` and the read-back, in seconds. The unit
#: answers a MIDI Edit with silence, so this is a settle, not a timeout.
DEFAULT_SETTLE = 0.05

#: Which ``mm`` field of the ``10`` message selects Mix mode. Everything
#: else -- global, program, effects -- plays in Program mode, which is
#: what ``mode_select(False)`` asks for.
MIX_MODE = "mix"

#: The backup's filename, inside ``--backup-dir``.
BACKUP_NAME = "edit-buffer.syx"


class ProbeAborted(RuntimeError):
    """The edit buffer could not be trusted, so the run stopped.

    ``preflight`` marks the abort that happened *before anything was
    probed*: the pre-flight restore did not verify, and the plan's rule
    for that case is to refuse to probe at all. The CLI exits 2 for it
    rather than 1, so "nothing was attempted" is distinguishable from
    "something was attempted and did not confirm".
    """

    def __init__(self, message: str, *, preflight: bool = False) -> None:
        super().__init__(message)
        self.preflight = preflight


@dataclass(frozen=True)
class Probe:
    """One row, one value, one before/after and what it came to.

    ``before`` and ``after`` are the edit buffer's 350 bytes on each
    read, ``value`` the displayed value sent, ``target`` the stored field
    that value should become, ``changed`` the absolute bit indices that
    differ between them (ascending, :func:`changed_bits`), ``verdict``
    what :func:`classify` made of that, and ``restored`` whether the
    buffer read back byte for byte as ``reference`` after the probe --
    the one flag that decides whether the run may continue at all.
    """

    param: params.Param
    value: int
    target: int
    before: bytes
    after: bytes
    changed: tuple[int, ...]
    verdict: str
    restored: bool


# --- pure helpers: no device, no sleeping, testable on their own -----------


def changed_bits(before: bytes, after: bytes) -> tuple[int, ...]:
    """Absolute indices of every bit that differs, ascending.

    Bit ``i`` lives in byte ``i >> 3`` at bit ``i & 7`` -- the addressing
    :mod:`nano.records` uses -- so these indices line up with
    ``Param.bit_address`` with no conversion, and a range the
    specification prints as ``1:6-1:0`` can be checked against them as
    written.

    Two reads of the edit buffer are always the same length (the bridge
    truncates every dump to the record size), so this walks the bytes
    both records have; a length difference is a caller's problem, not a
    changed bit, and is not reported here.
    """
    bits: list[int] = []
    for index, (was, now) in enumerate(zip(before, after, strict=False)):
        difference = was ^ now
        if not difference:
            continue
        base = index * 8
        for bit in range(8):
            if (difference >> bit) & 1:
                bits.append(base + bit)
    return tuple(bits)


def expected_bits(param: params.Param) -> tuple[int, ...]:
    """Every absolute bit index the row's field occupies.

    ``bit_address`` is the field's *least* significant bit -- the low end
    of the range the specification prints -- and the field runs ``bits``
    wide from there.
    """
    return tuple(range(param.bit_address, param.bit_address + param.bits))


def classify(param: params.Param, before: bytes, after: bytes, *, target: int) -> str:
    """What one before/after says about the row's address and its field.

    The changed set is compared against the row's own bits as a set, and
    the field is read back on the other side:

    * nothing changed -> ``no-change``;
    * any bit outside the row's field changed -> ``mismatch``, which is
      what a table address that disagrees with the firmware looks like;
    * nothing outside changed and the field now reads as ``target`` ->
      ``confirmed``. A subset is enough here: a field wider than its
      legal range cannot always flip every bit, and requiring that would
      report a correct address as a fault. What proves the address is
      that only the field moved **and** it holds the value that was
      sent;
    * nothing outside changed but the field reads something else ->
      ``partial``: the unit clamped or ignored bits, and the value law
      is not what the table says.

    ``target`` is the stored field value for the value sent, from
    :func:`nano.params.stored_for`.
    """
    changed = set(changed_bits(before, after))
    if not changed:
        return "no-change"
    expected = set(expected_bits(param))
    if not changed <= expected:
        return "mismatch"
    if rec.decode_bit_field(after, param) == target:
        return "confirmed"
    return "partial"


def probeable(param: params.Param) -> bool:
    """Whether the row may be probed at all. **False is a skip, not a probe.**

    Two rows are out of the question. ``function < 0`` is the
    specification's own mark for a row with no direct-edit address -- the
    spares, the Clock, the ROM identifier -- and sending one would invent
    an address the unit does not have. And a field whose bits fall
    outside the 350-byte record cannot be read back, so the diff could
    not mean anything; skipping it is honest where probing it would
    produce a ``mismatch`` that is the layout's fault, not the
    firmware's.
    """
    if param.function < 0:
        return False
    last = param.bit_address + param.bits - 1
    return param.bit_address >= 0 and last >> 3 < rec.PROGRAM_BYTES


def addressed(param: params.Param) -> params.Param:
    """The row the unit actually edits when this row's ``10`` is sent.

    The Mix channel block and the program sound block are *templates*:
    their bit addresses are relative to their own block, and the ``10``
    message carries a channel or sound index beside them. The row behind
    that message is the one :func:`nano.params.at` resolves, with
    ``with_channel``/``with_sound`` already applied -- probing the
    template's relative address would compare against bits the unit does
    not move. ``at`` returning nothing (no table row at this address)
    leaves the row alone, and the probe then reports what the unit
    actually did rather than what a lookup failed to find.
    """
    sound = 0 if param.sound is None else param.sound
    channel = 0 if param.channel is None else param.channel
    found = params.at(
        param.mode,
        param.function,
        param.page,
        param.pot,
        sound=sound,
        channel=channel,
    )
    return param if found is None else found


def flip_value(param: params.Param, current_stored: int) -> int:
    """The value that flips **every** bit of the row's field.

    The complement of what the field holds, read back under the row's
    value law: a controlled probe should move every bit it claims, and a
    field that moves all of them cannot be confused with a neighbouring
    one that moved some.

    The complement can leave the row's documented range -- a field wider
    than its own value span has such values -- and the ``10`` message
    would then be clamped by the unit to something that did not flip the
    whole field. So the fallback is the other end of the range,
    ``param.high``; except when the row already sits at ``high``, where
    re-sending the current value would prove nothing at all, so ``low``
    goes instead. The verdict for such a row is ``partial``, and that is
    the arithmetic's doing, not a bad address.
    """
    mask = (1 << param.bits) - 1
    target = current_stored ^ mask
    value = params.value_from_stored(param, target)
    if param.low <= value <= param.high:
        return value
    if params.value_from_stored(param, current_stored) >= param.high:
        return param.low
    return param.high


# --- the device side --------------------------------------------------------


def select_mode(device, mode: str) -> None:
    """Put the unit in the mode the rows live in, before any read.

    Program mode for ``global``, ``program`` and ``effects``, Mix mode
    for ``mix``. This is opcode ``0D`` -- **not a store**: it changes
    which buffer the unit plays from and writes nothing to memory, which
    is what makes it allowed before the edit buffer is read.
    """
    if mode not in params.MODE_NUMBERS:
        raise ValueError(
            f"unknown mode {mode!r}; expected one of "
            f"{', '.join(sorted(params.MODE_NUMBERS))}"
        )
    device.mode_select(mode == MIX_MODE)


def check_restore(device, reference: bytes, *, preflight: bool) -> None:
    """Send the reference back, read it, and insist it came back whole.

    Before any probe (``preflight``) this is the plan's "confirm the
    restore path once with no probe: send ``02`` with the original
    record, read it back, compare. If that fails, stop before probing" --
    so the refusal raises :class:`ProbeAborted` with ``preflight=True``
    and nothing has been moved. After the last probe it is the run's
    closing check, and its failure stops the run for the same reason: a
    buffer this tool cannot put back is not a buffer to keep
    disturbing.
    """
    device.write_edit_program(reference)
    read_back = bytes(device.read_edit_program())
    if read_back == reference:
        return
    where = "pre-flight" if preflight else "final"
    detail = (
        "so nothing was probed and nothing further will be sent"
        if preflight
        else "so the run stops here"
    )
    raise ProbeAborted(
        f"the {where} restore did not verify: the edit buffer did not "
        f"come back byte for byte, {detail}",
        preflight=preflight,
    )


def probe(
    device,
    param: params.Param,
    value: int,
    *,
    settle: float = DEFAULT_SETTLE,
    reference: bytes | None = None,
) -> Probe:
    """Move one parameter, read what moved, and put the buffer back.

    ``reference`` is the restore reference the caller already holds --
    ``run`` reads it once for the whole run; with no reference given,
    the edit buffer is read here and doubles as both. Then the ``10``,
    the settle (the unit answers it with silence, so nothing is waited
    for), the read-back, and the diff.

    The restore is in ``finally``, and that is the point of the whole
    function: whether the edit, the settle or the read-back raises, and
    however the caller leaves -- an exception, a Ctrl-C -- the reference
    goes back into the edit buffer and is read again, and ``restored``
    is true only when that read-back is byte for byte the reference. A
    probe whose restore raises propagates that instead of returning: an
    unrestored probe is not a result.
    """
    if reference is None:
        reference = device.read_edit_program()
    reference = bytes(reference)
    before = reference
    after = before
    changed: tuple[int, ...] = ()
    verdict = "no-change"
    restored = False
    target = params.stored_for(param, value)
    try:
        device.midi_edit(
            params.MODE_NUMBERS[param.mode],
            param.function,
            param.page,
            param.pot,
            value,
            sound=param.sound or 0,
            channel=param.channel or 0,
        )
        time.sleep(settle)  # the unit is silent under a 10; nothing to await
        after = device.read_edit_program()
        changed = changed_bits(before, after)
        verdict = classify(param, before, after, target=target)
    finally:
        device.write_edit_program(reference)
        restored = bytes(device.read_edit_program()) == reference
    return Probe(
        param=param,
        value=value,
        target=target,
        before=before,
        after=bytes(after),
        changed=changed,
        verdict=verdict,
        restored=restored,
    )


def run(
    device,
    rows: list[params.Param],
    *,
    settle: float = DEFAULT_SETTLE,
) -> list[Probe]:
    """Probe every probeable row once, restoring around each one.

    The sequence is ``docs/PARAMETER_VERIFICATION_PLAN.md`` section 5:

    1. put the unit in the mode the first row lives in;
    2. read the edit buffer -- the restore reference;
    3. **pre-flight restore with no probe**: send the reference back,
       read, compare (:func:`check_restore`). A failure raises
       :class:`ProbeAborted` with ``preflight=True`` *before anything
       moved*;
    4. one :func:`probe` per row, each with its own ``finally``
       restore; ``restored is False`` on any of them stops the run
       immediately;
    5. a final restore check, for the same reason as step 3.

    Rows :func:`probeable` refuses are skipped, not probed, so a spare
    never reaches a ``midi_edit``.
    """
    targets: list[params.Param] = []
    for row in rows:
        if not probeable(row):
            continue  # the spec's addressless rows are skipped, never probed
        target = addressed(row)
        if probeable(target):
            targets.append(target)

    probes: list[Probe] = []
    current_mode: str | None = None
    if targets:
        # Rule: the mode is chosen before the edit buffer is read.
        select_mode(device, targets[0].mode)
        current_mode = targets[0].mode
    reference = bytes(device.read_edit_program())
    check_restore(device, reference, preflight=True)

    for target in targets:
        if target.mode != current_mode:
            select_mode(device, target.mode)
            current_mode = target.mode
        stored = rec.decode_bit_field(reference, target)
        result = probe(
            device,
            target,
            flip_value(target, stored),
            settle=settle,
            reference=reference,
        )
        if not result.restored:
            raise ProbeAborted(
                f"{target.label}: the edit buffer did not come back byte "
                f"for byte after the probe, so the run stops here"
            )
        probes.append(result)

    check_restore(device, reference, preflight=False)
    return probes


def succeeded(probes: list[Probe]) -> bool:
    """Whether the run may be called a success.

    Every probed row ``confirmed`` **and** every restore verified, and
    at least one row probed: a run that probed nothing has confirmed
    nothing, and calling that a success is how a filter typo looks like
    a clean result.
    """
    if not probes:
        return False
    return all(p.verdict == "confirmed" and p.restored for p in probes)


# --- the demo device that takes the edit seriously --------------------------


def _flips_in_range(param: params.Param, stored: int) -> bool:
    """Whether ``stored``'s complement also reads back inside the range."""
    mask = (1 << param.bits) - 1
    flipped = params.value_from_stored(param, stored ^ mask)
    return param.low <= flipped <= param.high


def _legal_pair(param: params.Param) -> int | None:
    """A stored value whose complement is inside the range too, or ``None``.

    ``None`` means the row has no such value: a field wider than its own
    value span cannot flip all of it and stay legal. The demo leaves
    such a row alone rather than inventing a value, because inventing
    one would hide the arithmetic the probe is supposed to report.
    """
    for value in range(param.low, param.high + 1):
        try:
            stored = params.stored_for(param, value)
        except ValueError:
            return None  # a row whose range does not fit its width
        if _flips_in_range(param, stored):
            return stored
    return None


class EditingDemo:
    """A unit that takes the edit seriously -- ``--demo``'s device.

    **Not** :class:`nanosyned.demo.DemoDevice`, whose ``midi_edit``
    only logs: this one *applies* the field with
    :func:`nano.records.encode_bit_field`, so a demo verdict of
    ``confirmed`` means the bit arithmetic held, not just that a log
    grew. It opens no MIDI port, and it keeps nothing either: the only
    write it accepts is a *load* of the edit buffer, and the frames it
    records in :attr:`sent` are the ones the tool asked it to send --
    ``10``, ``02``, ``0D`` -- for the same safety check the tests make.

    ``modes`` names the modes this run will probe. The four tables
    overlap in this one 350-byte buffer, so only the selected modes are
    seeded: each of their fields gets a current value whose flip is also
    in range (a field left at zero whose complement would leave the
    range reports ``partial`` for a reason that is neither the tool nor
    the table), and a field that already flips legally is left exactly
    as it is -- which is what keeps the seeded demo name's characters
    intact where they can stay.
    """

    def __init__(self, *, modes: tuple[str, ...] = ()) -> None:
        record = bytearray(rec.PROGRAM_BYTES)
        m.encode_name(record, demo_name("USER", 0), m.NAME_BIT_OFFSET)
        # A byte with its top bit set, past the name, so the packing sees
        # real 8-bit data; a record of only seven-bit bytes would let a
        # broken pack7 pass.
        record[-1] = 0x80
        self._seed(record, modes)
        self.description = "demo (no MIDI ports opened)"
        self._buffer = bytes(record)
        #: Every frame the tool asked to send, in order.
        self.sent: list[bytes] = []
        self.edits: list[tuple[int, int, int, int, int, int, int]] = []
        self.mix_mode = False
        self._closed = False

    @staticmethod
    def _seed(record: bytearray, modes: tuple[str, ...]) -> None:
        """Give every probeable field of ``modes`` a legal flip pair."""
        for row in params.PARAMS:
            if row.mode not in modes or not probeable(row):
                continue
            target = addressed(row)
            current = rec.decode_bit_field(record, target)
            if _flips_in_range(target, current):
                continue  # already flips in range; leave it where it is
            stored = _legal_pair(target)
            if stored is not None:
                rec.encode_bit_field(record, target, stored)

    def _tick(self) -> None:
        """Refuse after ``close``, the way a closed port would."""
        if self._closed:
            raise RuntimeError(
                "this demo device is closed; a real bridge would be a closed port"
            )

    def close(self) -> None:
        self._closed = True

    def read_edit_program(self, *, timeout: float | None = None) -> bytes:
        self._tick()
        return self._buffer

    def write_edit_program(
        self, record: bytes, *, edit: int = 0, timeout: float | None = None
    ) -> None:
        """Load the edit buffer. **A load; this demo has no store at all.**"""
        self._tick()
        rec.check_size(record, rec.PROGRAM_BYTES, "a program")
        # Built (and range-checked) rather than sent: the frame is kept
        # so that the safety scan can see exactly what the tool asked for.
        self.sent.append(m.edit_program_dump(record, edit=edit))
        self._buffer = bytes(record)[: rec.PROGRAM_BYTES]

    def midi_edit(  # noqa: PLR0913 -- the body is the spec's seven fields
        self,
        mode: int,
        function: int,
        page: int,
        pot: int,
        value: int,
        *,
        sound: int = 0,
        channel: int = 0,
        timeout: float | None = None,
    ) -> None:
        """Move one parameter in the demo's buffer, as the unit would.

        The encoder is called for its range checks, the row is resolved
        through ``params.at`` exactly as the message addresses it, and
        the value lands through :func:`nano.records.encode_bit_field` --
        MSB first, sibling bits kept. An address no table row answers
        changes nothing, which is what the unit does with one.
        """
        self._tick()
        self.sent.append(
            m.midi_edit(mode, function, page, pot, value, sound=sound, channel=channel)
        )
        self.edits.append((mode, function, page, pot, value, sound, channel))
        found = params.at(
            _MODE_BY_NUMBER.get(mode, ""),
            function,
            page,
            pot,
            sound=sound,
            channel=channel,
        )
        if found is None:
            return
        record = bytearray(self._buffer)
        # The unit limits an out-of-range value to the nearest legal one
        # (the specification's own rule); this does the same, so a value
        # the demo clamps reports partial instead of passing.
        stored = params.stored_for(found, found.clamp(value))
        rec.encode_bit_field(record, found, stored)
        self._buffer = bytes(record)

    def mode_select(self, mix_mode: bool) -> None:
        """Put the demo in Program or Mix mode. **A mode change, no store.**"""
        self._tick()
        self.sent.append(m.mode_select(mix_mode))
        self.mix_mode = mix_mode


#: The ``mm`` field of a ``10`` message, read back as a mode name.
_MODE_BY_NUMBER = {number: name for name, number in params.MODE_NUMBERS.items()}


# --- the command line -------------------------------------------------------


def select_rows(args: argparse.Namespace) -> tuple[list[params.Param], int]:
    """The rows this run will probe, and how many rows it skipped.

    The skip count is taken *before* the addressless rows are dropped so
    the plan can say how many there were, and ``--limit`` applies to
    what is left: ``--limit 3`` means three **probed** rows rather than
    three rows of which one could not be.
    """
    modes = tuple(params.MODE_NUMBERS) if args.all else (args.mode,)
    label = None if args.label is None else args.label.casefold()
    wanted = [
        row
        for row in params.PARAMS
        if row.mode in modes and (label is None or label in row.label.casefold())
    ]
    skipped = sum(1 for row in wanted if not probeable(row))
    rows = [addressed(row) for row in wanted if probeable(row)]
    if args.limit is not None:
        rows = rows[: args.limit]
    return rows, skipped


def describe_plan(
    args: argparse.Namespace, rows: list[params.Param], skipped: int
) -> None:
    """Print what will happen, before a single frame is built."""
    print("PROBE PARAMETERS -- A DIFFERENTIAL PROBE OF THE EDIT BUFFER")
    print("=" * 60)
    print("This tool moves parameters in the unit's volatile edit buffer and")
    print("puts the buffer back. It sends only MIDI Edit (10), Edit Program")
    print("Dump (02, a load) and Mode Select (0D, no memory written); the")
    print("store (00) is never built or sent, so the user's bank is not")
    print("written. Every restore is read back and compared, and a restore")
    print("that does not verify stops the run.")
    print("")
    target = (
        "the in-process demo (no MIDI port opened)"
        if args.demo
        else f"output port {args.port!r}"
    )
    limit = "none" if args.limit is None else str(args.limit)
    backup = args.backup_dir or "none (--backup-dir writes it)"
    json_path = args.json_path or "none (--json writes it)"
    print(f"  target      : {target}")
    print(f"  mode        : {'every mode' if args.all else args.mode}")
    print(
        f"  rows        : {len(rows)} selected, {skipped} skipped with no "
        f"direct-edit address; limit {limit}"
    )
    print(f"  settle      : {args.settle:.3f} s between the edit and the read")
    print(f"  backup      : {backup}")
    print(f"  json        : {json_path}")
    print("  mode select : Program mode for global/program/effects, Mix mode")
    print("                for mix, before the buffer is read; not a store")
    print("  restore     : pre-flight with no probe first, then after every")
    print("                probe, then a final check")


def build_parser() -> argparse.ArgumentParser:
    """This tool's options; no port is opened here."""
    parser = argparse.ArgumentParser(
        prog="probe_params",
        description=__doc__.split("\n")[0],
        epilog=(
            "examples:\n"
            "  tools/probe_params.py --demo --mode global --limit 3\n"
            '  tools/probe_params.py --port "X:1" --mode global --yes\n'
            "  tools/probe_params.py --demo --all --json probes.json\n"
            "\n"
            "exit status:\n"
            "  0  at least one row probed, every verdict confirmed, every\n"
            "     restore verified\n"
            "  1  any other completed run\n"
            "  2  the pre-flight restore did not verify, so nothing was\n"
            "     probed at all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--port",
        metavar="PORT",
        help="the unit's MIDI output port; a real port needs --yes",
    )
    target.add_argument(
        "--demo",
        action="store_true",
        help="run against the in-process editing demo; opens no port",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(params.MODE_NUMBERS),
        default="global",
        help="which table's rows to probe (default: global)",
    )
    parser.add_argument(
        "--label",
        metavar="TEXT",
        help="keep only rows whose label contains TEXT (case-insensitive)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="probe every mode, not just --mode",
    )
    parser.add_argument(
        "--limit",
        metavar="N",
        type=int,
        default=None,
        help="probe at most N rows (default: every selected row)",
    )
    parser.add_argument(
        "--settle",
        metavar="SECONDS",
        type=float,
        default=DEFAULT_SETTLE,
        help=f"pause between the edit and the read-back (default: {DEFAULT_SETTLE})",
    )
    parser.add_argument(
        "--backup-dir",
        metavar="DIR",
        default=None,
        help=f"write the restore reference to DIR/{BACKUP_NAME} before probing",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        dest="json_path",
        default=None,
        help="write the probes as a JSON list to PATH",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirm that this tool may drive a real port (demo needs none)",
    )
    return parser


def write_backup(device, rows: list[params.Param], directory: Path) -> Path:
    """Save the restore reference **before** anything is probed.

    The file holds one Edit Program Dump message -- opcode ``02``, a
    load -- with the reference record packed inside it. It is a backup of
    the edit buffer, not of a store: nothing here writes it to the unit,
    and reading it back is what the unit is asked to do if a later run
    needs the same reference.
    """
    if rows:
        select_mode(device, rows[0].mode)
    reference = bytes(device.read_edit_program())
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / BACKUP_NAME
    path.write_bytes(m.edit_program_dump(reference))
    return path


def report_line(result: Probe) -> str:
    """One probe as one line: address, label, values, verdict, restore."""
    param = result.param
    address = f"{param.function}/{param.page}/{param.pot}"
    if param.sound is not None:
        address += f" s{param.sound}"
    if param.channel is not None:
        address += f" c{param.channel + 1}"
    current = params.value_from_stored(
        param, rec.decode_bit_field(result.before, param)
    )
    state = "restored" if result.restored else "NOT RESTORED"
    return (
        f"  {param.mode:<8} {address:<12} {param.label:<34} "
        f"{current:>5} -> {result.value:<5} {result.verdict:<9} {state}"
    )


def write_json(path: Path, probes: list[Probe]) -> None:
    """Write the probes as the JSON list the plan's log step reads back."""
    payload = [
        {
            "mode": probe_result.param.mode,
            "function": probe_result.param.function,
            "page": probe_result.param.page,
            "pot": probe_result.param.pot,
            "sound": probe_result.param.sound,
            "channel": probe_result.param.channel,
            "label": probe_result.param.label,
            "value": probe_result.value,
            "target_stored": probe_result.target,
            "verdict": probe_result.verdict,
            "restored": probe_result.restored,
        }
        for probe_result in probes
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def settings(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Validate the numbers, before anything is opened or printed."""
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.settle < 0:
        parser.error("--settle must be zero or more")


def report(probes: list[Probe], json_path: str | None) -> int:
    """Print every probe, write ``--json`` if asked, and say how it went."""
    for result in probes:
        print(report_line(result))
    if json_path:
        write_json(Path(json_path), probes)
        print(f"wrote {len(probes)} probe(s) to {json_path}")
    if not probes:
        print("no row was probed, so nothing was confirmed", file=sys.stderr)
        return 1
    failed = sum(1 for result in probes if result.verdict != "confirmed")
    if failed:
        print(
            f"{len(probes) - failed} of {len(probes)} row(s) confirmed; "
            f"{failed} did not. A partial or a mismatch is a finding to "
            f"record, not a table to edit.",
            file=sys.stderr,
        )
        return 1
    print(f"{len(probes)} of {len(probes)} row(s) confirmed; every restore verified.")
    return 0


def open_device(args: argparse.Namespace, modes: tuple[str, ...]):
    """The demo, or the port ``--port`` names. ``None`` after an error."""
    if args.demo:
        return EditingDemo(modes=modes)
    try:
        return b.NanoBridge.open(args.port)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings(parser, args)

    rows, skipped = select_rows(args)
    describe_plan(args, rows, skipped)
    if args.port and not args.yes:
        print("")
        print("dry run: no port was opened and nothing was sent.")
        print("Re-run with --yes to drive the unit.")
        return 0

    modes = tuple(dict.fromkeys(row.mode for row in rows))
    device = open_device(args, modes)
    if device is None:
        return 1
    try:
        if args.backup_dir:
            backup = write_backup(device, rows, Path(args.backup_dir))
            print(f"restore reference written to {backup}", file=sys.stderr)
        probes = run(device, rows, settle=args.settle)
    except ProbeAborted as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return 2 if exc.preflight else 1
    except (LookupError, TimeoutError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        device.close()
    return report(probes, args.json_path)


if __name__ == "__main__":
    raise SystemExit(main())
