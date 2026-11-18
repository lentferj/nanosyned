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

"""``nanocli`` -- the same operations as the browser, one at a time.

Reading is silent and needs no gate. ``select`` changes what plays. The
write commands -- ``send``, ``set`` and ``backup restore`` -- replace
something the unit keeps or move a parameter in its working copy, so they
are behind the family's ``--allow-write`` and ``--yes`` together.
``send`` and ``backup restore`` read the destination, back it up, write and
read it back. ``set`` prints the frame it sends and reads the working copy
where the unit can answer a dump; it stores nothing, so it has nothing to
back up. ``dump`` writes only to this computer.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, cast

from nano import backup as bk
from nano import banks, config, dumps, importing, importplan, params, verify
from nano import catalog as cat
from nano import config as cfg
from nano import favorites as favmod
from nano import messages as m
from nano import records as rec
from nano.writing import (
    RECORD_BYTES,
    RECORD_NAMES,
    frame,
    label,
    read_record,
    record_name,
    run,
    save_backup,
    truncate,
    write_record,
)
from nano.writing import Step as WStep
from vinsynlib.cli import (
    add_common_arguments,
    channel_of,
    make_parser,
    validate_common,
)
from vinsynlib.midi import list_ports, render_ports
from vinsynlib.render import progress, table

__all__ = ["build_parser", "main"]


def _catalog(args) -> cat.Catalog:
    return cat.load(getattr(args, "catalog", None))


# --- commands ---------------------------------------------------------------


def _cmd_ports(_device, _args) -> None:
    """List MIDI ports. Opens nothing."""
    # The listing itself is the family's (vinsynlib.midi.render_ports), so
    # that `ports` looks the same in all nine tools: inputs, then outputs,
    # two spaces of indent, and a bracketed mark on any port that can
    # answer. This unit is never named by rtmidi, so no hint is passed and
    # the mark simply does not appear -- the listing never claims a
    # judgement it cannot make.
    ins, outs = list_ports()
    print(
        render_ports(
            ins,
            outs,
            note=(
                "This unit may not be named on any of them: it has no USB of "
                "its own\nand answers through whatever interface it is cabled "
                "behind."
            ),
        )
    )


def _cmd_banks(_device, _args) -> None:
    """The five banks and what can be done with each."""
    rows = []
    for entry in banks.banks():
        rows.append(
            [
                entry.id,
                entry.label,
                str(entry.select),
                "yes" if entry.readable else "no",
                "yes" if entry.front_panel else "no",
                str(entry.count),
            ]
        )
    print(table(["id", "name", "CC0", "readable", "panel", "count"], rows))
    print(
        f"\n{banks.TOTAL_PROGRAMS} programs. Only the User bank can be "
        f"read back:\nthe rest are ROM and the protocol has no request "
        f"for them."
    )
    print("Bank Select is Controller 0. This unit ignores Controller 32.")


def _cmd_list(_device, args) -> None:
    """Every slot in a bank, with whatever names are known. Silent."""
    entry = banks.bank(args.bank)
    catalog = _catalog(args)
    rows = []
    for item in banks.slots(entry.id):
        rows.append(
            [
                f"{item.number:03d}",
                catalog.display_name(entry.id, item.program_change),
                item.category,
                str(item.program_change),
                str(item.lsb),
                str(item.msb),
            ]
        )
    print(f"{entry.label} — {entry.count} programs\n")
    print(table(["#", "name", "category", "PC", "LSB", "MSB"], rows))


def _cmd_status(device, _args) -> None:
    """Ask the unit who it is. Silent."""
    fields = device.identify()
    if fields is None:
        raise SystemExit(
            "error: nothing identified itself. Note that this unit never "
            "answers an Identity Request on its own -- nanosyned prompts "
            "it with a Global Dump Request -- so silence here means the "
            "chain does not carry its replies back, or it is not there."
        )
    print(f"port            {device.description}")
    if not fields.get("is_alesis"):
        print("manufacturer    not Alesis")
        return
    member = fields.get("member")
    print(f"manufacturer    {'.'.join(f'{b:02X}' for b in m.ALESIS_ID)}  (Alesis)")
    print(f"family          {fields['family'][0]:#04x}  (QS)")
    if member is not None:
        print(
            f"member          {member[0]:#04x}"
            f"{'  (NanoSynth)' if member[0] == m.NANOSYNTH_MEMBER else ''}"
        )
    if fields.get("version"):
        print(f"software        {fields['version']}")
    if fields.get("inferred"):
        print(
            "\n(inferred: it answered a QS dump request but no Identity\n"
            " Reply was waiting to be flushed)"
        )


def _cmd_current(device, _args) -> None:
    """What the unit is playing, from its edit buffer. Silent."""
    record = device.read_edit_program()
    print(f"edit buffer: {rec.program_name(record)!r} ({len(record)} bytes)")


def _cmd_read(device, args) -> None:
    """Read the User bank's names off the unit. Silent, makes no sound."""

    def _progress(done, total):
        if done % 16 == 0 or done == total:
            print(
                progress("reading the User bank", done, total),
                end="",
                file=sys.stderr,
            )

    names = device.read_program_names(on_progress=_progress)
    catalog = _catalog(args)
    rows = []
    for number, name in sorted(names.items()):
        printed = catalog.name("USER", number) or ""
        mark = "*" if printed and printed.strip() != name.strip() else ""
        rows.append([f"{number:03d}", name.rstrip(), printed, mark])
    print(f"\nUser bank — {len(names)} of {banks.PROGRAMS_PER_BANK} answered\n")
    print(table(["#", "on the unit", "in the catalog", ""], rows, empty="(nothing)"))
    if any(r[3] for r in rows):
        print("\n* the unit and the catalog disagree about this slot")
    print(file=sys.stderr)


def _cmd_mixes(device, _args) -> None:
    """Read the mix names. Silent.

    The manual does not mention mixes at all. The unit has 100 of them.
    """

    def _progress(done, total):
        if done % 20 == 0 or done == total:
            print(
                progress("reading the mixes", done, total),
                end="",
                file=sys.stderr,
            )

    names = device.read_mix_names(on_progress=_progress)
    rows = [[f"{n:02d}", name.rstrip()] for n, name in sorted(names.items())]
    print(f"\n{len(names)} mix(es)\n")
    print(table(["#", "name"], rows, empty="(nothing)"))


# --- records, on both sides of the wire -------------------------------------
#
# One table of sizes and one set of readers/writers, so a dump, a send and a
# restore cannot disagree about what a mix is or how many bytes it has. They
# live in nano.writing, together with the loop that uses them -- so the CLI
# and the browser's import write and read a record the same way, and a dump
# cannot describe a record differently from the store that follows it. The
# sizes there are the unpacked ones: what a dump carries and what the store
# encoders pack again.

#: The mix edit buffer: loadable, never storable. A bank that carries it
#: (an All Dump or a MidiQuest file may) skips it rather than refusing the
#: whole file. The skip is the planner's or this file's, not the writer's.
EDIT_MIX = 100

#: The numbered kinds, and the slots each has. Mix 100 is the edit buffer,
#: not a slot, so it is outside the range a write may name.
NUMBER_RANGES = {
    "program": (0, 127),
    "mix": (0, 99),
    "effects": (0, 127),
}


@dataclass
class _Write:
    """One record to store, in the order the plan will print it.

    What the destination held before it is not kept here: the reader that
    talks to the unit owns that, and it comes back in a
    :class:`nano.writing.Result`.
    """

    kind: str
    number: int | None
    record: bytes


def _check_number(kind: str, number: int) -> None:
    """Refuse a slot number the kind does not have, before anything opens."""
    low, high = NUMBER_RANGES[kind]
    if not low <= number <= high:
        raise SystemExit(
            f"error: {RECORD_NAMES[kind]} {number} is outside {low}-{high}"
        )


def _cmd_dump(device, args) -> None:
    """Write one record off the unit as a valid Alesis ``.syx`` file. Silent.

    One message, in the same frame the unit itself sends: the store
    encoders share the dump's shape, and a file holding one is exactly what
    a dump of that record would have been. Nothing is selected and nothing
    plays.
    """
    kind = args.dump_command
    number = getattr(args, "number", None)
    if kind != "global":
        if number is None:
            raise SystemExit(f"error: `dump {kind}` needs a slot number")
        _check_number(kind, number)
    record = truncate(
        kind, read_record(device, kind, number), f"the {RECORD_NAMES[kind]} dump"
    )
    message = frame(kind, number, record)
    try:
        with open(args.file, "wb") as handle:
            handle.write(message)
    except OSError as exc:
        raise SystemExit(f"error: cannot write {args.file}: {exc}") from None
    name = record_name(kind, record)
    print(
        f"wrote {len(message)} bytes ({len(record)}-byte {RECORD_NAMES[kind]}): "
        f"{label(kind, number, name)} -> {args.file}"
    )


def _send_plan(library: dumps.Library, args) -> list[_Write]:
    """Every record in ``library``, with the slot it will replace.

    The numbers come from the file. ``--program``, ``--mix`` and
    ``--effects`` override one of them, and only mean anything for a file
    holding exactly one record of that kind: one destination cannot stand
    for two records, and picking one silently is how the wrong slot is
    overwritten.
    """
    plan: list[_Write] = []
    for kind, source in (
        ("program", "programs"),
        ("mix", "mixes"),
        ("effects", "effects"),
    ):
        records = getattr(library, source)
        override = getattr(args, kind)
        what = f"the {RECORD_NAMES[kind]}"
        if override is not None:
            _check_number(kind, override)
            if len(records) != 1:
                raise SystemExit(
                    f"error: --{kind} {override} names one destination, so "
                    f"{args.file} must hold exactly one {RECORD_NAMES[kind]}; "
                    f"it holds {len(records)}"
                )
            record = truncate(kind, next(iter(records.values())), what)
            plan.append(_Write(kind, override, record))
            continue
        for number, data in sorted(records.items()):
            if kind == "mix" and number == EDIT_MIX:
                continue
            if kind == "program" and number == banks.SILENT_PROGRAM[1]:
                continue
            _check_number(kind, number)
            plan.append(_Write(kind, number, truncate(kind, data, what)))
    if library.globals_ is not None:
        plan.append(
            _Write(
                "global",
                None,
                truncate("global", library.globals_, "the global dump"),
            )
        )
    if not plan:
        raise SystemExit(
            f"error: {args.file} holds no program, mix, effects or global "
            f"records; nothing sent"
        )
    return plan


def _cmd_send(device, args) -> int:
    """**Write** a ``.syx`` file into the unit. The destructive command.

    The order is the app's and the family's, and every step is load-bearing:

    1. read every destination in full -- a slot that cannot be read is not
       written, because a write that cannot be undone is not performed;
    2. say exactly what will be replaced, by the name the unit holds;
    3. back every destination up;
    4. send the stores;
    5. read each back and compare, naming the bytes that differ.

    Those five steps are :func:`nano.writing.run` with ``read_first`` on --
    the batched order is the point, because the plan is printed between the
    reads and the first store. What is left here is this command's wording
    and exit code: a failed read, backup, store or read-back still stops it
    where it stopped before the loop moved out, and a MISMATCH is counted
    while the remaining records are still written.

    The gate (``--allow-write`` and ``--yes``) is checked in :func:`main`
    before a port is opened, so a refusal costs nothing.
    """
    try:
        library = dumps.read_syx_file(args.file)
    except OSError as exc:
        raise SystemExit(f"error: cannot read {args.file}: {exc}") from None
    plan = _send_plan(library, args)
    if EDIT_MIX in library.mixes:
        print(
            "note: mix 100 is the edit buffer, not a stored mix; skipped",
            file=sys.stderr,
        )
    if banks.SILENT_PROGRAM[1] in library.programs:
        print(
            f"note: user program {banks.SILENT_PROGRAM[1]} is hardwired "
            f"silent; skipped",
            file=sys.stderr,
        )
    for write in plan:
        if write.kind == "program" and write.number == banks.SILENT_PROGRAM[1]:
            raise SystemExit(
                f"error: {label(write.kind, write.number)} is hardwired "
                f"silent and cannot be changed; nothing sent"
            )
    if library.foreign or library.skipped:
        print(
            f"note: {library.foreign + library.skipped} message(s) in "
            f"{args.file} are not records this command writes; ignored",
            file=sys.stderr,
        )
    failed = 0

    def stop(result) -> None:
        """A stage that failed stops the command, as it always has."""
        raise SystemExit(f"error: {result.failure}")

    def on_phase(name, results) -> None:
        """The batch lines: the plan before any backup, then the paths."""
        if name == "read":
            for result in results:
                if result.failure is not None:
                    stop(result)
            print(f"{args.file}: {len(results)} record(s) to write")
            for result in results:
                old = record_name(result.kind, result.previous)
                new = record_name(result.kind, result.record)
                print(
                    f"  {label(result.kind, result.number, old)}"
                    f" -> {label(result.kind, result.number, new)}"
                )
        elif name == "backup":
            for result in results:
                if result.failure is not None:
                    stop(result)
                print(f"  backup {result.backup}")

    def on_result(result) -> None:
        """One record's outcome: the write, the read-back and the mismatch."""
        nonlocal failed
        if result.stage in ("read", "backup"):
            return  # the phase above has already said it, or stopped
        if result.failure is not None and result.stage != "verify":
            stop(result)
        if result.failure is not None:
            failed += 1
            print(f"verify   MISMATCH: {result.failure}; the backup is {result.backup}")
            return
        message = frame(result.kind, result.number, result.record)
        print(f"wrote    {len(message)} bytes to {label(result.kind, result.number)}")
        print(f"verify   {result.sentence}; the backup is {result.backup}")

    run(device, plan, on_phase=on_phase, on_result=on_result)
    return 1 if failed else 0


# --- backups ----------------------------------------------------------------


def _when(saved: float) -> str:
    """A backup's saved time, as a person reads it."""
    if not saved:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(saved))


def _backup_list() -> None:
    """Backups on disk. Needs no unit, so it opens no port."""
    directory = bk.backup_dir()
    rows = []
    for entry in bk.list_backups():
        rows.append(
            [
                entry.kind,
                entry.slot,
                entry.name,
                _when(entry.saved),
                f"unreadable: {entry.error}" if entry.error else "",
            ]
        )
    print(f"{directory}\n")
    print(table(["kind", "slot", "name", "saved", ""], rows, empty="(no backups)"))


def _restore_number(kind: str, backup: bk.Backup, override: int | None) -> int | None:
    """The destination slot a backup names, or ``SystemExit``.

    ``--number`` wins when given. Otherwise the envelope's ``slot`` is read:
    this CLI writes ``PROGRAM:005`` and the app writes ``USER:005``, and
    both are understood. A slot that is not a number is refused rather than
    guessed at, because guessing writes to the wrong program.
    """
    if kind == "global":
        return None
    if override is not None:
        _check_number(kind, override)
        return override
    text = backup.slot.strip()
    if text:
        text = text.rsplit(":", 1)[-1].strip()
        try:
            number = int(text)
        except ValueError:
            number = None
        if number is not None:
            _check_number(kind, number)
            return number
    raise SystemExit(
        f"error: this {kind} backup does not name a slot number "
        f"(slot {backup.slot!r}); give --number N"
    )


def _cmd_backup_restore(device, args) -> int:
    """**Write** a backup back into the unit. Destructive, so guarded."""
    try:
        backup = bk.load(args.file)
    except OSError as exc:
        raise SystemExit(f"error: cannot read {args.file}: {exc}") from None
    kind = backup.kind
    if kind not in RECORD_BYTES:
        raise SystemExit(
            f"error: {args.file} holds a {kind!r} backup; this unit backs up "
            f"{', '.join(sorted(RECORD_BYTES))}"
        )
    if kind not in backup.blocks:
        raise SystemExit(
            f"error: {args.file} is a {kind} backup with no {kind!r} block; "
            f"nothing to restore"
        )
    record = truncate(kind, backup.blocks[kind], f"the {RECORD_NAMES[kind]} backup")
    number = _restore_number(kind, backup, getattr(args, "number", None))
    if kind == "program" and number == banks.SILENT_PROGRAM[1]:
        raise SystemExit(
            f"error: user program {number} is hardwired silent and cannot be "
            f"changed; nothing sent"
        )
    current = truncate(
        kind,
        read_record(device, kind, number),
        f"the {RECORD_NAMES[kind]} at {label(kind, number)}",
    )
    old = record_name(kind, current)
    new = record_name(kind, record) or backup.name
    print(f"{args.file}: {label(kind, number, old)} -> {label(kind, number, new)}")
    path = save_backup(kind, number, current)
    print(f"  backup {path}")
    write_record(device, kind, number, record)
    read_back = truncate(
        kind,
        read_record(device, kind, number),
        f"the {RECORD_NAMES[kind]} at {label(kind, number)}",
    )
    sentence = verify.describe(record, read_back, what=label(kind, number, new))
    if verify.mismatches(record, read_back):
        print(f"verify   MISMATCH: {sentence}; the backup is {path}")
        return 1
    print(f"verify   {sentence}; the backup is {path}")
    return 0


def _cmd_backup(device, args) -> int | None:
    """The ``backup`` group: list on disk, or restore one."""
    if args.backup_command == "list":
        _backup_list()
        return None
    return _cmd_backup_restore(device, args)


# --- one parameter, through the direct edit ---------------------------------


def _parameter_record(device, mode: str, channel: int) -> tuple[bytes, str] | None:
    """Return (record, buffer_name) for the mode's read-back buffer."""
    if mode == "global":
        return device.read_global(), "the global dump"
    if mode == "mix":
        return device.read_mix(100), "the mix edit buffer (100)"
    if mode == "program":
        edit = channel + 1
        return (
            device.read_edit_program(edit=edit),
            f"the channel {edit} program edit buffer",
        )
    if mode == "effects":
        return None
    return None


def _set_read_back(
    device, mode: str, param: params.Param | None, value: int, channel: int
) -> int:
    """Read the working copy back where this mode has a request for it."""
    if mode == "effects":
        print(
            "read-back  the bench found the unit ignores an effects 10, so "
            "nothing was verified"
        )
        return 0
    record_info = _parameter_record(device, mode, channel)
    if record_info is None:
        print(
            "read-back  this mode has no dump request this command can make; "
            "the edit was not verified (a MIDI Edit stores nothing)"
        )
        return 0
    record, where = record_info
    if param is None:
        print(
            f"read-back  {where} answered ({len(record)} bytes); the address "
            f"is not in the transcribed table, so the value was not compared"
        )
        return 0
    stored = rec.decode_bit_field(record, param)
    seen = params.value_from_stored(param, stored)
    expected = param.clamp(value)
    if seen != expected:
        print(
            f"read-back  {param.label} reads {seen}, not {expected} -- the "
            f"edit did not land in {where}"
        )
        return 1
    print(f"read-back  {param.label} = {seen}")
    return 0


def _cmd_params(_device, args) -> None:
    """List the parameter table, and which rows this unit verified."""
    mode = getattr(args, "mode", None)
    modes = ["global", "mix", "effects", "program"]
    if mode is not None:
        modes = [mode]
    rows = []
    for mode_name in modes:
        for param in params.PARAMS:
            if param.mode != mode_name:
                continue
            verified = "yes" if param.verified else "no"
            law = param.value_law or "-"
            range_str = f"{param.low}..{param.high}"
            if mode is None:
                rows.append(
                    [
                        mode_name,
                        verified,
                        law,
                        str(param.function),
                        str(param.page),
                        str(param.pot),
                        str(param.bits),
                        range_str,
                        param.label,
                    ]
                )
            else:
                rows.append(
                    [
                        verified,
                        law,
                        str(param.function),
                        str(param.page),
                        str(param.pot),
                        str(param.bits),
                        range_str,
                        param.label,
                    ]
                )
    if mode is None:
        print(
            _plain_table(
                ["mode", "verified", "law", "f", "p", "pot", "bits", "range", "label"],
                rows,
            )
        )
    else:
        print(
            _plain_table(
                ["verified", "law", "f", "p", "pot", "bits", "range", "label"],
                rows,
            )
        )
    verified_count = len(params.verified_params())
    total_count = len(params.PARAMS)
    if mode is not None:
        mode_verified = len(params.verified_params(mode))
        mode_total = len([p for p in params.PARAMS if p.mode == mode])
        head = (
            f"\n{mode_verified} of {mode_total} {mode} rows verified; "
            f"{verified_count} of {total_count} overall"
        )
    else:
        head = (
            f"\n{verified_count} of {total_count} rows verified on the bench "
            f"unit (2026-11-01)"
        )
    print(f"{head}; the rest are transcriptions and are read-only.")


def _plain_table(headers: list[str], rows: list[list[str]]) -> str:
    """A listing table that does **not** truncate.

    :func:`vinsynlib.render.table` caps every column to fit the terminal,
    which is right for a browser's summary line and wrong for a table
    meant to be read, grepped and copied: it turned ``verified`` into
    ``veri...`` and the value law into ``tw...``. Here the widest cell
    wins and the terminal wraps if it must.
    """
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[i]) for i, header in enumerate(headers))]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def _cmd_set(device, args) -> int:
    """**Write** one parameter through the ``10`` MIDI Edit message.

    Nothing is stored: the unit moves the parameter in its working copy,
    and only a store keeps it. It does change what plays, so it is behind
    the same gate as ``send``. There is no backup to take because there is
    no stored record to replace; what proves the edit landed is the buffer
    read back afterwards, in the two modes that can answer a dump.
    """
    mode = args.mode
    channel = getattr(device, "channel", 0) or 0
    number = params.MODE_NUMBERS[mode]
    param = params.at(
        mode,
        args.function,
        args.page,
        args.pot,
        sound=args.sound,
        channel=channel if mode == "mix" else None,
    )
    if param is None:
        raise SystemExit(
            f"error: no parameter at mode {mode}, function {args.function}, "
            f"page {args.page}, pot {args.pot}"
        )
    if not param.verified:
        if not getattr(args, "force_unverified", False):
            raise SystemExit(
                f'error: "{param.label}" is a transcription, not verified on '
                "this unit; add --force-unverified to send it anyway"
            )
        print(
            f"warning: {param.label} is a transcription, not verified on this "
            "unit; the user asked for it (unverified)",
            file=sys.stderr,
        )
    # Put the unit in the mode the row lives in: opcode 0D, a mode change only,
    # no memory written. Program rows only land in Mix mode.
    if mode in {"mix", "program"}:
        device.mode_select(True)
    elif mode == "global":
        device.mode_select(False)
    message = m.midi_edit(
        number,
        args.function,
        args.page,
        args.pot,
        args.value,
        sound=args.sound,
        channel=channel,
    )
    line = " ".join(f"{byte:02X}" for byte in message)
    print(f"frame    {line}  ({len(message)} bytes)")
    print(
        f"address  {param.label} (mode {mode}, function "
        f"{args.function}, page {args.page}, pot {args.pot})"
    )
    print(f"channel  {channel + 1}, sound {args.sound}, value {args.value}")
    device.midi_edit(
        number,
        args.function,
        args.page,
        args.pot,
        args.value,
        sound=args.sound,
        channel=channel,
    )
    print("sent     the working copy, not stored; the unit's memory is unchanged")
    return _set_read_back(device, mode, param, args.value, channel)


def _cmd_select(device, args) -> int:
    """Select a program. **This makes the unit play.**"""
    try:
        target = banks.slot(args.bank, args.number)
    except LookupError as exc:
        raise SystemExit(f"error: {exc}") from None
    if not args.yes:
        print(f"about to select {target.display} on MIDI channel {device.channel + 1}.")
        print("This changes what the instrument is playing.")
        if input("proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            print("nothing sent")
            return 1
    device.select(target)
    print(
        f"selected {target.display} "
        f"(Bank Select {target.bank.select}, Program Change "
        f"{target.program_change}) on channel {device.channel + 1}"
    )
    return 0


def _cmd_syx(_device, args) -> None:
    """Read a .syx file. Touches no hardware."""
    library = dumps.read_syx_file(args.file)
    print(f"{args.file}: {library.summary()}")
    if library.is_all_dump:
        print("this is a complete All Dump")
    names = library.program_names()
    if names:
        rows = [[f"{n:03d}", v.rstrip()] for n, v in sorted(names.items())]
        print()
        print(table(["#", "program"], rows, empty="(nothing)"))
    mixes = library.mix_names()
    if mixes and args.mixes:
        rows = [[f"{n:02d}", v.rstrip()] for n, v in sorted(mixes.items())]
        print()
        print(table(["#", "mix"], rows, empty="(nothing)"))


def _usage(msg: str) -> NoReturn:
    """Refuse a command line before anything is stored, with exit code 2."""
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


def _select_bank(source: importing.ImportSource, args) -> importing.SourceBank:
    """The one source bank this command works on, or a refusal.

    ``--bank N`` picks a bank by its index. Without it, a file with a
    single program bank needs no choice; a file with more does, and the
    error lists the banks so the retry can name one.
    """
    banks = source.banks
    if args.bank is None:
        if len(banks) > 1:
            available = ", ".join(str(bank.index) for bank in banks)
            _usage(
                f"{args.file} holds {len(banks)} banks ({available}); "
                f"choose one with --bank"
            )
        return banks[0]
    for bank in banks:
        if bank.index == args.bank:
            return bank
    available = ", ".join(str(bank.index) for bank in banks)
    _usage(f"bank {args.bank} is not in {args.file}; available bank(s): {available}")


def _program_pairs(program_list: list[str]) -> list[tuple[int, int]]:
    """``--program SRC=DST`` tokens as ``(source_slot, target_slot)`` pairs."""
    pairs: list[tuple[int, int]] = []
    for item in program_list:
        src_text, sep, dst_text = item.partition("=")
        if not sep:
            _usage(f"--program wants SRC=DST, not {item!r}")
        try:
            pairs.append((int(src_text), int(dst_text)))
        except ValueError:
            _usage(f"--program wants SRC=DST, not {item!r}")
    return pairs


def _cmd_import(device, args) -> int:
    """Import programs from a file, or list one offline.

    ``--list`` prints each source bank, what it holds, and every program as
    ``slot  name``. A ``.syx`` is one synthetic bank; a ``.sqs`` keeps its
    banks distinct. ``--program SRC=DST`` maps source slots to User
    destinations 000-126. ``--all`` writes the whole bank. ``--dry-run``
    reads the destinations and prints what would be replaced, then stops;
    it opens the port but does not need the write gate.
    """
    try:
        source = importing.read_import(args.file)
    except OSError as exc:
        raise SystemExit(f"error: cannot read {args.file}: {exc}") from None

    if args.list:
        return _import_list(source, args)

    if not args.program and not args.all:
        _usage("nothing selected; nothing sent (use --program or --all)")

    plan = _import_plan(source, args)
    if not plan.steps:
        _usage("nothing selected; nothing sent")

    # Notes: a part flag given for a part the file does not carry, and
    # the records the plan skipped (source 127, mix 100 the edit buffer).
    if args.all:
        bank = _select_bank(source, args)
        if args.effects and not bank.effects:
            print(
                "note: the file carries no effects patches; --effects skipped",
                file=sys.stderr,
            )
        if args.mixes and not bank.mixes:
            print(
                "note: the file carries no mixes; --mixes skipped",
                file=sys.stderr,
            )
        if args.global_ and bank.globals_ is None:
            print(
                "note: the file carries no global settings; --global skipped",
                file=sys.stderr,
            )
    for note in plan.skipped:
        print(f"note: {note}", file=sys.stderr)

    if args.dry_run:
        _import_dry_run(device, args, plan)
        return 0

    return _import_write(device, args, plan)


def _import_plan(source: importing.ImportSource, args) -> importplan.ImportPlan:
    """Build the program plan, or a refusal."""
    bank = _select_bank(source, args)
    try:
        if args.all:
            plan = importplan.plan_bank(bank)
            # Add bank parts if requested
            if args.effects:
                plan = _combine_plans(plan, importplan.plan_all_effects(bank))
            if args.mixes:
                plan = _combine_plans(plan, importplan.plan_all_mixes(bank))
            if args.global_:
                plan = _combine_plans(plan, importplan.plan_all_global(bank))
            return plan
        return importplan.plan_single(bank, _program_pairs(args.program))
    except ValueError as exc:
        _usage(str(exc))


def _combine_plans(
    base: importplan.ImportPlan, part: importplan.ImportPlan
) -> importplan.ImportPlan:
    """Combine a base plan with a part plan (effects/mixes/global)."""
    return importplan.ImportPlan(
        steps=base.steps + part.steps,
        skipped=base.skipped + part.skipped,
        overwrites=base.overwrites + part.overwrites,
    )


def _import_list(source: importing.ImportSource, args) -> int:
    """Print what the import file holds, offline. Returns exit code."""
    banks = source.banks
    if args.bank is not None:
        matches = [bank for bank in banks if bank.index == args.bank]
        if not matches:
            available = ", ".join(str(bank.index) for bank in banks)
            raise SystemExit(
                f"error: bank {args.bank} is not in {args.file}; "
                f"available bank(s): {available}"
            )
        banks = matches
    print(f"{args.file}: {source.summary()}")
    for bank in banks:
        print()
        print(f"{bank.label} — {len(bank.programs)} program(s)")
        for number in sorted(bank.programs):
            program = bank.programs[number]
            print(f"  {program.slot:3d}  {program.name}")
        for number in sorted(bank.effects):
            print(f"  effects {number:03d}")
        for number in sorted(bank.mixes):
            print(f"  mix {number:03d}")
        if bank.globals_ is not None:
            print("  global")
        if bank.duplicates:
            print(
                "  duplicate slot(s): "
                + ", ".join(str(number) for number in bank.duplicates)
            )
        if (
            not bank.programs
            and not bank.effects
            and not bank.mixes
            and bank.globals_ is None
        ):
            print("  (empty bank)")
    return 0


def _import_dry_run(device, args, plan: importplan.ImportPlan) -> None:
    """Read the destinations and print the plan; store nothing.

    The lines are the write's own: each destination's current name, then the
    source program's name. Nothing is backed up or stored, and the write
    gate is not needed because nothing changes.
    """
    print(f"{args.file}: {len(plan.steps)} record(s) to write")
    catalog = _catalog(args)
    for step in plan.steps:
        target = step.target
        kind = step.kind
        try:
            previous = read_record(device, kind, target)
        except Exception as exc:
            raise SystemExit(
                f"error: cannot read destination {target}: {exc}"
            ) from None
        if kind == "program":
            old = record_name(kind, previous) or catalog.display_name(
                "USER", cast(int, target)
            )
        else:
            old = record_name(kind, previous)
        new = record_name(kind, step.record) or step.source_label
        print(f"  {label(kind, target, old)} -> {label(kind, target, new)}")


def _import_write(device, args, plan: importplan.ImportPlan) -> int:
    """Read, back up, store and verify every planned program.

    The plan is executed by :func:`nano.writing.run` with ``read_first=True``
    (the default). Every destination is read first; a slot that cannot be read
    is not written. The on_phase and on_result hooks print the plan lines and
    record outcomes, matching the family's ``send`` output style.
    """
    failed = 0

    def stop(result) -> None:
        raise SystemExit(f"error: {result.failure}")

    def on_phase(name: str, results: list) -> None:
        if name == "read":
            for result in results:
                if result.failure is not None:
                    stop(result)
            print(f"{args.file}: {len(results)} record(s) to write")
            for result in results:
                old = record_name(result.kind, result.previous)
                new = record_name(result.kind, result.record)
                print(
                    f"  {label(result.kind, result.number, old)}"
                    f" -> {label(result.kind, result.number, new)}"
                )
        elif name == "backup":
            for result in results:
                if result.failure is not None:
                    stop(result)
                print(f"  backup {result.backup}")

    def on_result(result) -> None:
        nonlocal failed
        if result.stage in ("read", "backup"):
            return
        if result.failure is not None and result.stage != "verify":
            stop(result)
        if result.failure is not None:
            failed += 1
            print(f"verify   MISMATCH: {result.failure}; the backup is {result.backup}")
            return
        message = frame(result.kind, result.number, result.record)
        print(f"wrote    {len(message)} bytes to {label(result.kind, result.number)}")
        print(f"verify   {result.sentence}; the backup is {result.backup}")

    run(
        device,
        cast("Sequence[WStep]", plan.steps),
        on_phase=on_phase,
        on_result=on_result,
    )
    return 1 if failed else 0


def _cmd_find(_device, args) -> None:
    """Search the names this program knows. Touches no hardware."""
    catalog = _catalog(args)
    hits = catalog.search(args.name)
    if not hits:
        print(f"nothing matching {args.name!r}", file=sys.stderr)
        return
    rows = []
    for bank_id, _kind, number, name in hits:
        try:
            entry = banks.bank(bank_id)
        except LookupError:
            continue
        rows.append(
            [
                entry.label,
                f"{number:03d}",
                name.rstrip() + (" *" if catalog.differs(bank_id, number) else ""),
                str(number),
                str(0),
                str(entry.select),
            ]
        )
    print(table(["bank", "#", "name", "PC", "LSB", "MSB"], rows))
    if any(catalog.differs(bank_id, number) for bank_id, _kind, number, _name in hits):
        print(
            "\n* the unit and the catalog disagree about this slot; the "
            "unit's name is shown"
        )


# --- favourites -------------------------------------------------------------


def _favorites(args) -> favmod.Favorites:
    """The user's store, at ``--favorites`` or in the data directory."""
    return favmod.Favorites(getattr(args, "favorites", None))


def _favorite_slot(args) -> tuple[str, int]:
    """The bank and number the action flags apply to, or ``SystemExit``.

    The slot is positional (``fav USER 12 --add``) rather than part of each
    flag's value, so that the same two words serve ``--add``, ``--remove``
    and ``--rate`` -- the family's later command lines do it this way, and
    an action on the wrong slot is not a thing to spell three times.
    """
    if args.bank is None or args.number is None:
        raise SystemExit("error: give a bank and a number, e.g. `fav USER 12 --add`")
    try:
        banks.slot(args.bank, args.number)
    except LookupError as exc:
        raise SystemExit(f"error: {exc}") from None
    return args.bank, args.number


def _rating_stars(value: object, flag: str) -> int:
    """A rating from the command line, 0-5, or one line of ``SystemExit``.

    Checked here rather than left to :meth:`Favorites.add`: the column has
    no CHECK constraint, so an out-of-range rating is stored happily and
    then breaks the rating column's value-and-scale invariant -- seven
    stars with no scale, or a negative one that renders as dots and that
    ``--rating-at-least 0`` cannot find.
    """
    try:
        stars = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        raise SystemExit(f"error: {flag} wants 0-5, not {value!r}") from None
    if not 0 <= stars <= 5:
        raise SystemExit(f"error: {flag} wants 0-5, not {stars}")
    return stars


def _list_favorites(args, favorites: favmod.Favorites) -> None:
    """One table of whichever favourites the filters select."""
    if getattr(args, "tag", None):
        rows = favorites.with_tag(args.tag)
    elif getattr(args, "search", None):
        rows = favorites.search(args.search)
    else:
        rows = favorites.all(order=args.order)
    # A rating filter is a post-filter over whichever of the three ran, not
    # a fourth branch: `--tag lead --rating-at-least 4` has to mean what it
    # says, and the browser stacks its filter the same way.
    if getattr(args, "rating_at_least", None) is not None:
        stars = _rating_stars(args.rating_at_least, "--rating-at-least")
        rows = [row for row in rows if row.rating >= stars]
    if not rows:
        print("no favourites", file=sys.stderr)
        return
    catalog = _catalog(args)
    table_rows = []
    for fav in rows:
        try:
            slot = banks.slot(fav.bank_id, fav.number)
            wire = [str(slot.bank.select), str(slot.program_change)]
        except LookupError:
            # A bank this build no longer defines. Shown, not dropped.
            wire = ["?", "?"]
        table_rows.append(
            [
                fav.bank_id,
                f"{fav.number:03d}",
                fav.name or catalog.display_name(fav.bank_id, fav.number),
                *wire,
                favmod.rating_cell(fav.rating),
                fav.tags,
                fav.note,
            ]
        )
    print(
        table(
            ["bank", "#", "name", "CC0", "PC", "rating", "tags", "note"],
            table_rows,
        )
    )


def _cmd_fav(_device, args) -> None:
    """The favourites database. Offline; opens no instrument."""
    favorites = _favorites(args)
    try:
        if args.add:
            bank_id, number = _favorite_slot(args)
            # `add` is an upsert that replaces every field, so anything not
            # passed would silently wipe it. Carry through what is already
            # there: "favourite this and rate it 4" must not drop the note.
            existing = favorites.get(bank_id, number)
            rating = existing.rating if existing is not None else 0
            tags = existing.tags if existing is not None else ""
            note = existing.note if existing is not None else ""
            if args.rate is not None:
                rating = _rating_stars(args.rate, "--rate")
            if args.tags is not None:
                tags = args.tags
            if args.note is not None:
                note = args.note
            favorites.add(
                bank_id,
                number,
                name=_catalog(args).display_name(bank_id, number),
                rating=rating,
                tags=tags,
                note=note,
            )
            print(f"added {bank_id} {number:03d}")
            return
        if args.remove:
            bank_id, number = _favorite_slot(args)
            if favorites.remove(bank_id, number):
                print(f"removed {bank_id} {number:03d}")
            else:
                print(
                    f"{bank_id} {number:03d} was not a favourite",
                    file=sys.stderr,
                )
            return
        if args.rate is not None:
            # Rating an existing favourite without touching anything else.
            # Unlike the library's set_rating, this refuses a slot nobody
            # favourited: a rating is an annotation *on* a favourite, and
            # `fav --rate` on a typo should say so rather than invent a row.
            bank_id, number = _favorite_slot(args)
            if favorites.get(bank_id, number) is None:
                raise SystemExit(
                    f"error: {bank_id} {number:03d} is not a favourite; add it first"
                )
            stars = _rating_stars(args.rate, "--rate")
            favorites.set_rating(bank_id, number, stars)
            print(f"rated {bank_id} {number:03d} {stars}")
            return
        if args.tags is not None or args.note is not None:
            # The library's set_tags/set_note *create* a favourite when
            # there is none; that is its documented contract, and the help
            # says so rather than pretending otherwise.
            bank_id, number = _favorite_slot(args)
            if args.tags is not None:
                favorites.set_tags(bank_id, number, args.tags)
                print(f"tagged {bank_id} {number:03d}")
            if args.note is not None:
                favorites.set_note(bank_id, number, args.note)
                print(f"noted {bank_id} {number:03d}")
            return
        _list_favorites(args, favorites)
    finally:
        favorites.close()


def _cmd_tags(_device, args) -> None:
    """Every tag in use, with its count. Offline; opens no instrument."""
    favorites = _favorites(args)
    try:
        counts = favorites.tags()
    finally:
        favorites.close()
    if not counts:
        print("no tags", file=sys.stderr)
        return
    print(table(["tag", "count"], [[tag, str(n)] for tag, n in counts.items()]))


# --- wiring -----------------------------------------------------------------

#: Commands that need no instrument at all.
OFFLINE = {
    "ports",
    "banks",
    "import",
    "list",
    "syx",
    "find",
    "fav",
    "favorites",
    "tags",
    "params",
}


def _needs_device(args) -> bool:
    """Whether this invocation must open the unit.

    ``backup list`` is the one command inside a group that needs nothing:
    judging by the group's name alone would open a port to list files on
    disk. ``import`` is offline for ``--list``, the read-only preview; every
    other import path reads or stores, so it opens the unit.
    """
    listing = (
        args.command == "backup" and getattr(args, "backup_command", None) == "list"
    )
    if args.command == "backup" and listing:
        # The list half of a group is the one thing inside it that reads no
        # port; judging by the group's name alone would open one to list files.
        return False
    if args.command == "import" and getattr(args, "list", False):
        # --list only reads a file on disk; the write and dry-run paths below
        # read or store, so they open the unit.
        return False
    if args.command == "import":
        return True
    return args.command not in OFFLINE and not listing


def _writes(args) -> bool:
    """True for the commands that change the unit or what it plays."""
    if args.command in ("send", "set"):
        return True
    if args.command == "import":
        # --list and --dry-run read; only a real import writes. The write
        # path is a stub until T6, but the gate is checked before it runs.
        return not (args.list or args.dry_run)
    return (
        args.command == "backup" and getattr(args, "backup_command", None) == "restore"
    )


def _require_write(args) -> None:
    """The gate, before a port is opened. Both halves are required."""
    if not _writes(args):
        return
    missing = [
        flag
        for flag, given in (
            ("--allow-write", args.allow_write),
            ("--yes", args.yes),
        )
        if not given
    ]
    if not missing:
        return
    what = "backup restore" if args.command == "backup" else args.command
    raise SystemExit(
        f"error: `{what}` writes to the unit; add {' and '.join(missing)} "
        f"if that is what you want"
    )


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 -- one per command
    parser = make_parser(
        "nanocli",
        "Browse an Alesis NanoSynth. Reading is silent; `send`, `set` and "
        "`backup restore` write, and need --allow-write and --yes.",
        distribution="nanosyned",
    )
    # Every flag's help text is the family's, from vinsynlib.spec. This tool
    # used to word four of them its own way, which is how the same option
    # came to read one way in one program and another in the other eight.
    add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        catalog=True,
        config=True,
        demo=True,
        favorites=True,
        yes=True,
        allow_write=True,
    )
    cfg.apply_config_help(parser, tool="nanosyned")
    sub = parser.add_subparsers(dest="command", required=True)

    def _inherit(sp: argparse.ArgumentParser, dest: str) -> None:
        """Let a family option follow the subcommand as well as precede it.

        argparse only accepts a parent parser's option *before* the
        subcommand, and ``nanocli send x.syx --yes`` is the shape people
        actually type. Re-declaring the option keeps the family's own help
        text, taken from the action just added. ``SUPPRESS`` is the load-
        bearing part: without it the subparser's default would overwrite a
        value given before the subcommand.
        """
        for action in parser._actions:
            if action.dest != dest:
                continue
            extra: dict[str, Any] = {
                "dest": action.dest,
                "default": argparse.SUPPRESS,
                "help": action.help,
            }
            # A switch must stay a switch: re-declaring --yes as a value
            # option is how ``send x.syx --yes`` came to want an argument.
            if action.nargs == 0:
                extra["action"] = "store_true" if action.const else "store_false"
            else:
                extra["type"] = action.type
                extra["metavar"] = action.metavar
            sp.add_argument(*action.option_strings, **extra)
            return

    def _store_flag(sp: argparse.ArgumentParser) -> None:
        _inherit(sp, "favorites")

    def _write_flags(sp: argparse.ArgumentParser) -> None:
        """The two halves of the write gate, either side of the command."""
        _inherit(sp, "allow_write")
        _inherit(sp, "yes")

    sub.add_parser("ports", help="list MIDI ports (opens nothing)")
    sub.add_parser("banks", help="the five banks, and what each allows")
    sp = sub.add_parser("list", help="every slot in a bank (silent)")
    sp.add_argument("bank", choices=banks.bank_ids())
    sub.add_parser("status", help="ask the unit who it is (silent)")
    sub.add_parser("current", help="what the unit is playing (silent)")
    sub.add_parser("read", help="read the User bank's names (silent)")
    sub.add_parser("mixes", help="read the mix names (silent)")
    sp = sub.add_parser(
        "dump", help="write one record off the unit to a .syx file (silent)"
    )
    dsub = sp.add_subparsers(dest="dump_command", required=True)
    for kind in ("program", "mix", "effects"):
        dp = dsub.add_parser(
            kind, help=f"read one {RECORD_NAMES[kind]} and write it as .syx"
        )
        dp.add_argument("number", type=int)
        dp.add_argument("--file", required=True, metavar="PATH")
    dp = dsub.add_parser("global", help="read the global settings as .syx")
    dp.add_argument("--file", required=True, metavar="PATH")
    sp = sub.add_parser(
        "send",
        help="WRITE a .syx file into the unit (backs up, then verifies)",
    )
    sp.add_argument("file", metavar="FILE")
    sp.add_argument(
        "--program",
        type=int,
        default=None,
        metavar="N",
        help="store the file's one program in this slot, not its own number",
    )
    sp.add_argument(
        "--mix",
        type=int,
        default=None,
        metavar="N",
        help="store the file's one mix in this slot, not its own number",
    )
    sp.add_argument(
        "--effects",
        type=int,
        default=None,
        metavar="N",
        help="store the file's one effects patch in this slot, not its own",
    )
    _write_flags(sp)
    sp = sub.add_parser(
        "backup", help="backups on disk, and restoring one (restore WRITES)"
    )
    bsub = sp.add_subparsers(dest="backup_command", required=True)
    bsub.add_parser("list", help="backups found on disk (no unit needed)")
    bp = bsub.add_parser(
        "restore", help="write a backup back into the unit (DESTRUCTIVE)"
    )
    bp.add_argument("file", metavar="PATH")
    bp.add_argument(
        "--number",
        type=int,
        default=None,
        metavar="N",
        help="destination slot, when the backup itself does not name one",
    )
    _write_flags(bp)
    sp = sub.add_parser(
        "set",
        help="WRITE one parameter through the MIDI Edit message (not stored)",
    )
    sp.add_argument("mode", choices=["global", "mix", "program", "effects"])
    sp.add_argument("function", type=int, help="0-16")
    sp.add_argument("page", type=int, help="0-23")
    sp.add_argument("pot", type=int, help="0-3")
    sp.add_argument("value", type=int, help="-128 to 127")
    sp.add_argument(
        "--sound",
        type=int,
        default=0,
        metavar="N",
        help="program sound or effects bus, 0-3",
    )
    sp.add_argument("--force-unverified", action="store_true")
    # --channel is both the send channel and the message's `cccc` field;
    # re-declaring it here lets it follow the command, which is the shape
    # people type. main() subtracts one and the device carries the 0-15 form.
    _inherit(sp, "channel")
    _write_flags(sp)
    sp = sub.add_parser(
        "params",
        help="list the parameter table, and which rows this unit verified",
    )
    sp.add_argument(
        "mode",
        nargs="?",
        choices=["global", "mix", "program", "effects"],
        default=None,
    )
    sp = sub.add_parser("select", help="select a program ON THE UNIT")
    sp.add_argument("bank", choices=banks.bank_ids())
    sp.add_argument("number", type=int)
    sp = sub.add_parser("syx", help="read a .syx file (no hardware)")
    sp.add_argument("file")
    sp.add_argument("--mixes", action="store_true", help="list mixes too")
    sp = sub.add_parser(
        "import",
        help="preview an import file --list, or write it with --program/--all",
    )
    sp.add_argument("file", metavar="FILE")
    sp.add_argument(
        "--list",
        action="store_true",
        default=False,
        help="print each source bank, its counts, and every program as "
        "`slot  name` (offline)",
    )
    sp.add_argument(
        "--bank",
        type=int,
        default=None,
        metavar="N",
        help="source bank number, when the file holds more than one program bank",
    )
    sp.add_argument(
        "--program",
        action="append",
        default=None,
        metavar="SRC=DST",
        help="repeatable: map source slot SRC to User destination DST (000-126)",
    )
    sp.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="write every program in the selected bank to its own slot "
        "(not yet implemented)",
    )
    sp.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="read the destinations and print what would be replaced, then stop",
    )
    sp.add_argument(
        "--effects",
        action="store_true",
        default=False,
        help="also import effects patches (bank import only)",
    )
    sp.add_argument(
        "--mixes",
        action="store_true",
        default=False,
        help="also import mixes (bank import only)",
    )
    sp.add_argument(
        "--global",
        action="store_true",
        default=False,
        dest="global_",
        help="also import the global settings (bank import only)",
    )
    _write_flags(sp)
    sp = sub.add_parser("find", help="search known names (no hardware)")
    sp.add_argument("name")
    sp = sub.add_parser(
        "fav",
        aliases=["favorites"],
        help="the favourites database (no hardware)",
    )
    sp.add_argument("bank", nargs="?", choices=banks.bank_ids())
    sp.add_argument("number", nargs="?", type=int)
    # --add and --remove are two directions of one operation; argparse can
    # refuse the pair before the store is even opened. --rate is
    # deliberately *not* in this group: with --add it supplies the rating
    # to store, and alone it rates a favourite that already exists.
    actions = sp.add_mutually_exclusive_group()
    actions.add_argument("--add", action="store_true", help="favourite the slot")
    actions.add_argument("--remove", action="store_true", help="un-favourite the slot")
    sp.add_argument(
        "--rate",
        type=int,
        default=None,
        metavar="0-5",
        help=(
            "with --add, the rating to store; alone, rate a favourite you "
            "already have (0-5)"
        ),
    )
    sp.add_argument(
        "--tags",
        default=None,
        help="set the tags (creates the favourite if it is not one)",
    )
    sp.add_argument(
        "--note",
        default=None,
        help="set the note (creates the favourite if it is not one)",
    )
    sp.add_argument("--tag", default=None, help="favourites with this tag")
    sp.add_argument("--search", default=None, help="search names, tags and notes")
    sp.add_argument("--rating-at-least", type=int, default=None, metavar="0-5")
    sp.add_argument(
        "--order",
        default="added",
        choices=["added", "bank", "name", "rating"],
    )
    _store_flag(sp)
    sp = sub.add_parser("tags", help="tags in use, with counts (no hardware)")
    _store_flag(sp)
    return parser


COMMANDS = {
    "ports": _cmd_ports,
    "banks": _cmd_banks,
    "list": _cmd_list,
    "status": _cmd_status,
    "current": _cmd_current,
    "read": _cmd_read,
    "mixes": _cmd_mixes,
    "dump": _cmd_dump,
    "send": _cmd_send,
    "backup": _cmd_backup,
    "set": _cmd_set,
    "params": _cmd_params,
    "select": _cmd_select,
    "syx": _cmd_syx,
    "import": _cmd_import,
    "find": _cmd_find,
    "fav": _cmd_fav,
    "favorites": _cmd_fav,
    "tags": _cmd_tags,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = getattr(args, "config", None) or config.DEFAULT_PATH

    if args.config is None:
        cfg.migrate_legacy_config("nanosyned")
        import os

        os.makedirs(cfg.config_dir("nanosyned"), exist_ok=True)

    # The family's range checks, before anything is opened.
    validate_common(args)
    # ...and the write gate, also before a port is opened: a store that was
    # not asked for twice must not even cost a probe.
    _require_write(args)
    # channel_of subtracts one: --channel is 1-16 on every command line in
    # this family and 0-15 on the wire.
    channel = channel_of(args, default=config.load_channel(config_path)) or 0

    #: DemoDevice and NanoBridge are structurally interchangeable; the
    #: local is untyped for the same reason as in nanosyned.app.main.
    device: Any = None
    if _needs_device(args):
        if args.demo:
            from nanosyned.demo import DemoDevice

            device = DemoDevice(channel=channel)
        else:
            from nano import bridge as b

            try:
                if args.port:
                    device = b.NanoBridge.open(
                        args.port, recv_port=args.recv_port, channel=channel
                    )
                else:
                    # One Global Dump Request to the remembered port; the
                    # sweep only when there is nothing remembered, when the
                    # remembered port no longer answers, or on --scan. The
                    # inline remembered-port try/except this replaces fell
                    # back to the sweep silently, which is how a launch that
                    # had lost its port looked exactly like a fast one.
                    device = b.NanoBridge.connect(
                        config_path=config_path,
                        channel=channel,
                        scan=args.scan,
                        on_try=lambda n: print(f"  probing {n}...", file=sys.stderr),
                    )
                if getattr(device, "swept", False):
                    print(
                        f"swept for {device.probe_seconds:.1f} s; found {device.port}",
                        file=sys.stderr,
                    )
                try:
                    port = getattr(device, "port", None)
                    if port:
                        config.save_last_port(port, config_path)
                except OSError:
                    pass
            except Exception as exc:
                raise SystemExit(f"error: {exc}") from None

    try:
        result = COMMANDS[args.command](device, args)
    except (LookupError, TimeoutError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"error: {exc}") from None
    finally:
        if device is not None:
            device.close()
    return result or 0


if __name__ == "__main__":
    raise SystemExit(main())
