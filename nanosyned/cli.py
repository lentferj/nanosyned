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
from typing import Any

from nano import banks, config, dumps
from nano import catalog as cat
from nano import favorites as favmod
from nano import messages as m
from nano import records as rec
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
            ]
        )
    print(f"{entry.label} — {entry.count} programs\n")
    print(table(["#", "name", "category"], rows))


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
                str(entry.select),
                str(number),
            ]
        )
    print(table(["bank", "#", "name", "CC0", "PC"], rows))
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
OFFLINE = {"ports", "banks", "list", "syx", "find", "fav", "favorites", "tags"}


def build_parser() -> argparse.ArgumentParser:
    parser = make_parser(
        "nanocli",
        "Browse an Alesis NanoSynth. Everything is read-only except `select`.",
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
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _store_flag(sp: argparse.ArgumentParser) -> None:
        """Let ``--favorites`` follow the subcommand as well as precede it.

        argparse only accepts a parent parser's option *before* the
        subcommand, and ``nanocli tags --favorites x`` is the shape people
        actually type. Re-declaring the option keeps the family's own help
        text, taken from the action just added. ``SUPPRESS`` is the load-
        bearing part: without it the subparser's default (``None``) would
        overwrite a path given before the subcommand.
        """
        for action in parser._actions:
            if action.dest == "favorites":
                sp.add_argument(
                    *action.option_strings,
                    dest=action.dest,
                    metavar=action.metavar,
                    default=argparse.SUPPRESS,
                    help=action.help,
                )
                return

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
    "select": _cmd_select,
    "syx": _cmd_syx,
    "find": _cmd_find,
    "fav": _cmd_fav,
    "favorites": _cmd_fav,
    "tags": _cmd_tags,
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
