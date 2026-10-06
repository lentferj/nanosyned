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

Everything here is read-only except ``select``, which is marked, and which
is the only command that makes the instrument play.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from nano import banks, config, dumps
from nano import catalog as cat
from nano import messages as m
from nano import records as rec
from vinsynlib.cli import (
    add_common_arguments,
    channel_of,
    make_parser,
    validate_common,
)
from vinsynlib.midi import list_ports, render_ports

__all__ = ["build_parser", "main"]


def _table(rows: Sequence[Sequence[str]], headers: Sequence[str]) -> str:
    if not rows:
        return "(nothing)"
    widths = [
        max(len(str(r[i])) for r in (*rows, headers)) for i in range(len(headers))
    ]
    out = [
        "  ".join(
            str(h).ljust(w) for h, w in zip(headers, widths, strict=True)
        ).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    for row in rows:
        out.append(
            "  ".join(
                str(c).ljust(w) for c, w in zip(row, widths, strict=True)
            ).rstrip()
        )
    return "\n".join(out)


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
    print(_table(rows, ["id", "name", "CC0", "readable", "panel", "count"]))
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
            ]
        )
    print(f"{entry.label} — {entry.count} programs\n")
    print(_table(rows, ["#", "name", "category"]))


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

    def progress(done, total):
        if done % 16 == 0 or done == total:
            print(f"  {done}/{total}", file=sys.stderr)

    names = device.read_program_names(on_progress=progress)
    catalog = _catalog(args)
    rows = []
    for number, name in sorted(names.items()):
        printed = catalog.name("USER", number) or ""
        mark = "*" if printed and printed.strip() != name.strip() else ""
        rows.append([f"{number:03d}", name.rstrip(), printed, mark])
    print(f"\nUser bank — {len(names)} of {banks.PROGRAMS_PER_BANK} answered\n")
    print(_table(rows, ["#", "on the unit", "in the catalog", ""]))
    if any(r[3] for r in rows):
        print("\n* the unit and the catalog disagree about this slot")


def _cmd_mixes(device, _args) -> None:
    """Read the mix names. Silent.

    The manual does not mention mixes at all. The unit has 100 of them.
    """

    def progress(done, total):
        if done % 20 == 0 or done == total:
            print(f"  {done}/{total}", file=sys.stderr)

    names = device.read_mix_names(on_progress=progress)
    rows = [[f"{n:02d}", name.rstrip()] for n, name in sorted(names.items())]
    print(f"\n{len(names)} mix(es)\n")
    print(_table(rows, ["#", "name"]))


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
        print(_table(rows, ["#", "program"]))
    mixes = library.mix_names()
    if mixes and args.mixes:
        rows = [[f"{n:02d}", v.rstrip()] for n, v in sorted(mixes.items())]
        print()
        print(_table(rows, ["#", "mix"]))


def _cmd_find(_device, args) -> None:
    """Search the names this program knows. Touches no hardware."""
    catalog = _catalog(args)
    hits = catalog.search(args.name)
    if not hits:
        print(f"nothing matching {args.name!r}", file=sys.stderr)
        return
    rows = []
    for bank_id, number, name, differs in hits:
        try:
            entry = banks.bank(bank_id)
        except LookupError:
            continue
        rows.append(
            [
                entry.label,
                f"{number:03d}",
                name.rstrip() + (" *" if differs else ""),
                str(entry.select),
                str(number),
            ]
        )
    print(_table(rows, ["bank", "#", "name", "CC0", "PC"]))
    if any(hit[3] for hit in hits):
        print(
            "\n* the unit and the catalog disagree about this slot; the "
            "unit's name is shown"
        )


# --- wiring -----------------------------------------------------------------

#: Commands that need no instrument at all.
OFFLINE = {"ports", "banks", "list", "syx", "find"}


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser(
        "nanocli",
        "Browse an Alesis NanoSynth. Everything is read-only except `select`.",
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
        yes=True,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ports", help="list MIDI ports (opens nothing)")
    sub.add_parser("banks", help="the five banks, and what each allows")
    sp = sub.add_parser("list", help="every slot in a bank (silent)")
    sp.add_argument("bank", choices=banks.bank_ids())
    sub.add_parser("status", help="ask the unit who it is (silent)")
    sub.add_parser("current", help="what the unit is playing (silent)")
    sub.add_parser("read", help="read the User bank's names (silent)")
    sub.add_parser("mixes", help="read the mix names (silent)")
    sp = sub.add_parser("select", help="select a program ON THE UNIT")
    sp.add_argument("bank", choices=banks.bank_ids())
    sp.add_argument("number", type=int)
    sp = sub.add_parser("syx", help="read a .syx file (no hardware)")
    sp.add_argument("file")
    sp.add_argument("--mixes", action="store_true", help="list mixes too")
    sp = sub.add_parser("find", help="search known names (no hardware)")
    sp.add_argument("name")
    return parser


COMMANDS = {
    "ports": _cmd_ports,
    "banks": _cmd_banks,
    "list": _cmd_list,
    "status": _cmd_status,
    "current": _cmd_current,
    "read": _cmd_read,
    "mixes": _cmd_mixes,
    "select": _cmd_select,
    "syx": _cmd_syx,
    "find": _cmd_find,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = getattr(args, "config", None) or config.DEFAULT_PATH

    # The family's range checks, before anything is opened.
    validate_common(args)
    # channel_of subtracts one: --channel is 1-16 on every command line in
    # this family and 0-15 on the wire.
    channel = channel_of(args, default=config.load_channel(config_path)) or 0

    #: DemoDevice and NanoBridge are structurally interchangeable; the
    #: local is untyped for the same reason as in nanosyned.app.main.
    device: Any = None
    if args.command not in OFFLINE:
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
