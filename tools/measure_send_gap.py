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

"""Measure the inter-message gaps ``nano/bridge.py`` guesses at.

``nano.bridge.SEND_GAP`` (0.010 s) and ``nano.bridge.SELECT_GAP`` (0.005 s)
have been guesses since the first commit. Alesis documents no inter-message
timing for this instrument because it documents no System Exclusive for it
at all, so the values are the siblings' conservative defaults. This tool
measures both against the unit.

**A bench tool: it drives the unit and must be run alone.** Quit every other
MIDI program first, and leave the front panel alone while it runs. It opens
a real port and sends the messages described below; it will not open one
without ``--yes``.

**It does not change the unit's memory.** No store message is sent -- not
one. The SEND_GAP half only sends User Program Dump Requests, which are
reads. The SELECT_GAP half sends Bank Select and Program Change, which
change what the unit is *playing* and **may make a sound**; nothing is
stored, and ``--no-select`` skips that half. Put the unit in Program mode
first: the protocol has no request that reads the mode back, and in Mix mode
a Program Change addresses a mix channel rather than a program, which would
make the observation meaningless.

What is measured
----------------

``SEND_GAP``
    For each candidate gap, read the first ``--count`` User programs one at
    a time, sleeping that gap between consecutive requests, and compare the
    resulting ``{number: name}`` map against a reference read taken at
    ``--reference-gap`` (0.100 s), twice. The interesting failure is not a
    timeout: it is a reply belonging to the *previous* request, which this
    protocol cannot distinguish from the current one except by the number
    the reply carries (:meth:`nano.bridge.NanoBridge.request` checks it).
    Too small a gap shows up as names shifted by one slot. Those are
    reported separately from timeouts and from names that match no slot.

``SELECT_GAP``
    The gap between Bank Select and Program Change in
    :meth:`nano.bridge.NanoBridge.select`. For each gap, the tool first
    selects a General MIDI program at the conservative reference gap -- a
    *different* bank, so the next Bank Select has work to do -- then selects
    the same-numbered User program with the candidate gap, and asks the edit
    buffer which program the unit actually loaded. This is a bench
    observation of what the unit did, not a claim about its firmware: what
    is printed is the bytes sent and the names the edit buffer reported.

Neither constant is edited here. The final block prints the values to paste
into ``nano/bridge.py`` deliberately, and a measured value supersedes the
guess. Record the run in ``docs/RESOLUTION_NOTES.md``.

Usage::

    python3 tools/measure_send_gap.py                  # dry listing
    python3 tools/measure_send_gap.py --yes --port "X:1"
    python3 tools/measure_send_gap.py --yes --scan --count 8
    python3 tools/measure_send_gap.py --yes --gaps 0.000,0.005,0.010 --no-select

Exit status is 0 when the measurement completed, 1 when it could not be
taken at all -- no port, nothing answering, or a reference read that was
not reproducible. A candidate gap failing is the *result*, not an error.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nano import banks
from nano import bridge as b
from nano import config as cfg
from nano import messages as m
from nano import records as rec
from vinsynlib.cli import (
    add_common_arguments,
    channel_of,
    make_parser,
    validate_common,
)

#: Candidate gaps between two User Program Dump Requests, in seconds.
#: ``0.000`` is in the list on purpose: "the unit needs no gap at all" is a
#: result worth being able to state, and the table says which gaps were
#: actually tried if it is.
DEFAULT_GAPS: tuple[float, ...] = (0.000, 0.002, 0.005, 0.010, 0.020, 0.050)

#: The gap the reference read is taken at. Long enough that a failure there
#: is the unit's problem rather than the timing's.
DEFAULT_REFERENCE_GAP = 0.100

#: How many reference passes. One clean sweep is an absence of evidence on
#: a cable: a marginal link fails intermittently, and a one-shot read of a
#: reference is exactly what an intermittent failure hides behind.
REFERENCE_PASSES = 2

#: How long to wait for the edit buffer to show a selection before calling
#: the Program Change lost, and how often to look while waiting.
SETTLE = 0.500
POLL = 0.020

#: Selection trials per candidate gap.
DEFAULT_TRIALS = 3

#: Failure lines printed per gap. The rest are counted, not listed: a gap
#: that is far too short fails every slot and the table already says so.
SHOWN = 6

#: The bank the unit is put into before each selection trial, and the bank
#: the program selected during the trial belongs to.
PREVIOUS_BANK = "GM"
TARGET_BANK = "USER"


@dataclass
class Comparison:
    """What one bank read did against the reference."""

    matched: int = 0
    timeouts: int = 0
    misfiled: int = 0
    wrong: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (self.timeouts or self.misfiled or self.wrong)


@dataclass
class GapResult:
    """One candidate gap, after all its repeats."""

    gap: float
    clean: int
    repeats: int
    matched: int
    timeouts: int
    misfiled: int
    wrong: int
    mean_seconds: float
    notes: list[str]


@dataclass
class SelectResult:
    """One candidate SELECT_GAP, after all its trials."""

    gap: float
    clean: int
    conclusive: int
    trials: int
    notes: list[str]


@dataclass(frozen=True)
class Bench:
    """What every selection trial shares, so the arguments stay legible."""

    reference: dict[int, str]
    reference_gap: float
    channel: int


def read_names(
    device: b.NanoBridge, count: int, gap: float
) -> tuple[dict[int, str], float]:
    """Read the first ``count`` User programs, ``gap`` seconds apart.

    The same request sequence as :meth:`NanoBridge.read_program_names`, with
    the sleep between requests supplied here instead of by
    :data:`nano.bridge.SEND_GAP`. That method swallows each ``TimeoutError``
    and returns whatever arrived; this one has to know *which* slots did not
    answer in order to classify the failure, so it reads one program at a
    time and remembers the holes.

    The gap is between consecutive requests, not after the last one. A slot
    that times out is left out of the result, which is how the caller sees
    it: the next request's :meth:`_drain` discards a late reply, exactly as
    the production bridge does.
    """
    names: dict[int, str] = {}
    started = time.perf_counter()
    for number in range(count):
        if number:
            time.sleep(gap)
        try:
            record = device.read_program(number)
        except TimeoutError:
            continue
        names[number] = rec.program_name(record)
    return names, time.perf_counter() - started


def compare(reference: dict[int, str], names: dict[int, str], count: int) -> Comparison:
    """Classify what a read did against the reference.

    Three kinds of failure, and the difference matters:

    ``timeout``
        the slot did not answer at all.
    ``misfiled``
        the slot answered with a name that belongs to **another slot** --
        usually the one before it, which is the previous request's reply
        arriving during this one. This is the failure a bare success count
        cannot see, and the one that would put a name on the wrong row.
    ``wrong``
        a name that matches no slot in the reference. Not a shift; treat it
        as a bad record rather than a timing result.
    """
    result = Comparison()
    for number in range(count):
        expected = reference.get(number)
        got = names.get(number)
        if got is None:
            result.timeouts += 1
            result.notes.append(f"slot {number:03d}: no reply")
            continue
        if expected is None:
            result.wrong += 1
            result.notes.append(
                f"slot {number:03d}: read {got!r}, with no reference to compare it to"
            )
            continue
        if got == expected:
            result.matched += 1
            continue
        previous = reference.get(number - 1)
        if number and previous is not None and got == previous:
            result.misfiled += 1
            result.notes.append(
                f"slot {number:03d}: carried slot {number - 1:03d}'s name "
                f"{got!r} -- the previous request's reply, filed late"
            )
            continue
        sources = [
            other
            for other, name in reference.items()
            if name == got and other != number
        ]
        if sources:
            result.misfiled += 1
            result.notes.append(
                f"slot {number:03d}: carried slot {sources[0]:03d}'s name "
                f"{got!r} -- a reply filed under the wrong number"
            )
            continue
        result.wrong += 1
        result.notes.append(f"slot {number:03d}: read {got!r}, which matches no slot")
    return result


def take_reference(
    device: b.NanoBridge, count: int, gap: float
) -> dict[int, str] | None:
    """Read the bank twice at a conservative gap, or give up.

    A reference that is not reproducible makes every later comparison
    meaningless, so this stops rather than sweeping on top of it.
    """
    reference: dict[int, str] | None = None
    for index in range(REFERENCE_PASSES):
        print(
            f"reference pass {index + 1}/{REFERENCE_PASSES} at {gap * 1000:.0f} ms...",
            file=sys.stderr,
        )
        names, seconds = read_names(device, count, gap)
        missing = count - len(names)
        if missing:
            print(
                f"  {missing} slot(s) did not answer at {gap * 1000:.0f} ms; "
                f"the reference is not trustworthy. Is the unit connected, "
                f"in Program mode, and is System Exclusive reception on?",
                file=sys.stderr,
            )
            return None
        if reference is not None and names != reference:
            for number in range(count):
                if reference.get(number) != names.get(number):
                    print(
                        f"  slot {number:03d} read {reference.get(number)!r} "
                        f"on pass 1 but {names.get(number)!r} on pass "
                        f"{index + 1} at the *reference* gap. That is a fault "
                        f"to look at before changing any timing.",
                        file=sys.stderr,
                    )
                    break
            return None
        reference = names
        print(f"  {len(names)} names in {seconds:.2f} s", file=sys.stderr)
    return reference


def measure_send(
    device: b.NanoBridge,
    reference: dict[int, str],
    gaps: list[float],
    count: int,
    repeats: int,
) -> list[GapResult]:
    """Sweep the candidate SEND_GAPs. Returns one result per gap."""
    results: list[GapResult] = []
    print("")
    print(
        f"{'gap':>9}  {'clean':>5}  {'match':>5}  {'timeout':>7}  "
        f"{'mis-filed':>9}  {'wrong':>5}  {'mean s':>7}"
    )
    for gap in gaps:
        clean = 0
        matched = timeouts = misfiled = wrong = 0
        total = 0.0
        notes: list[str] = []
        for _ in range(repeats):
            names, seconds = read_names(device, count, gap)
            total += seconds
            found = compare(reference, names, count)
            matched += found.matched
            timeouts += found.timeouts
            misfiled += found.misfiled
            wrong += found.wrong
            notes.extend(found.notes)
            if found.clean:
                clean += 1
        print(
            f"{gap * 1000:8.1f}ms  {clean:>2}/{repeats:<2}  {matched:>5}  "
            f"{timeouts:>7}  {misfiled:>9}  {wrong:>5}  {total / repeats:7.2f}"
        )
        for note in notes[:SHOWN]:
            print(f"      {note}")
        if len(notes) > SHOWN:
            print(f"      ... and {len(notes) - SHOWN} more")
        results.append(
            GapResult(
                gap=gap,
                clean=clean,
                repeats=repeats,
                matched=matched,
                timeouts=timeouts,
                misfiled=misfiled,
                wrong=wrong,
                mean_seconds=total / repeats,
                notes=notes,
            )
        )
    return results


def edit_name(device: b.NanoBridge) -> str | None:
    """The name in the edit buffer, or ``None`` if it did not answer."""
    try:
        return rec.program_name(device.read_edit_program())
    except TimeoutError:
        return None


def poll_edit(
    device: b.NanoBridge, name: str, settle: float, *, until_equal: bool
) -> str | None:
    """Poll the edit buffer until it equals or leaves ``name``.

    ``until_equal`` selects the predicate: ``True`` waits for the buffer to
    say ``name`` (did the Program Change land?), ``False`` for it to stop
    saying it (did the previous Bank Select work?). Returns the last name
    seen, whether or not the wait succeeded, so the caller can report what
    the unit actually showed.
    """
    deadline = time.monotonic() + settle
    last: str | None = None
    while True:
        last = edit_name(device)
        # (last == name) == until_equal is the predicate in one expression:
        # equal-and-wanted, or different-and-wanted.
        done = last is not None and (last == name) == until_equal
        if done or time.monotonic() >= deadline:
            return last
        time.sleep(POLL)


def witness_slots(reference: dict[int, str]) -> list[int]:
    """User slots whose name can prove which program the unit loaded.

    A blank name, or one another slot also has, cannot tell "the selection
    worked" from "the edit buffer did not move", so those make poor
    witnesses. The hardwired silent program is left out as well. If nothing
    is unique, any named slot will do, and failing that, any slot.
    """
    seen: dict[str, int] = {}
    for name in reference.values():
        seen[name] = seen.get(name, 0) + 1
    silent = banks.SILENT_PROGRAM[1]
    usable = [number for number, name in reference.items() if number != silent]
    odd = [number for number in usable if reference[number].strip()]
    unique = [number for number in odd if seen[reference[number]] == 1]
    return unique or odd or usable


def measure_select(
    device: b.NanoBridge,
    bench: Bench,
    gaps: list[float],
    trials: int,
) -> list[SelectResult]:
    """Sweep the candidate SELECT_GAPs against what the edit buffer says.

    Not a read-only observation: a Bank Select and a Program Change are
    sent, which changes what the unit plays. Nothing is stored.
    """
    reference = bench.reference
    reference_gap = bench.reference_gap
    channel = bench.channel
    targets = witness_slots(reference)
    if not targets:
        print(
            "no User program can witness a selection; skipping SELECT_GAP",
            file=sys.stderr,
        )
        return []

    previous = banks.bank(PREVIOUS_BANK)
    target_bank = banks.bank(TARGET_BANK)
    print("")
    print(
        "SELECT_GAP is a bench observation: the unit is put into another "
        "bank, then\nthe same-numbered User program is selected with the "
        "candidate gap, and the edit\nbuffer is asked which program it "
        "actually loaded. Nothing is stored."
    )
    print(
        f"  setup:  {_hex(m.bank_select(previous.select, channel)[0])} then "
        f"{_hex(m.program_change(0, channel), last='nn')}"
        f"   ({previous.label}, reference gap {reference_gap * 1000:.0f} ms)"
    )
    print(
        f"  test:   {_hex(m.bank_select(target_bank.select, channel)[0])} "
        f"then {_hex(m.program_change(0, channel), last='nn')}"
        f"   ({target_bank.label}, the candidate gap)"
    )
    print("  nn is the same User program number in both pairs.")
    print("  Assumes the unit is in Program mode; the mode cannot be read back.")
    print("")

    original = b.SELECT_GAP
    results: list[SelectResult] = []
    try:
        for gap in gaps:
            clean = conclusive = 0
            notes: list[str] = []
            for trial in range(trials):
                target = targets[trial % len(targets)]
                expected = reference[target]

                # A different bank first, at the conservative gap, so the
                # Bank Select under test has something to change.
                b.SELECT_GAP = reference_gap
                device.select(banks.slot(previous.id, target))
                before = poll_edit(device, expected, SETTLE, until_equal=False)
                if before is None or before == expected:
                    notes.append(
                        f"trial {trial + 1} (User {target:03d}): inconclusive "
                        f"-- the edit buffer did not leave {expected!r}; is "
                        f"the unit in Program mode?"
                    )
                    continue
                conclusive += 1

                # The production path, with only the gap changed.
                b.SELECT_GAP = gap
                device.select(banks.slot(target_bank.id, target))
                after = poll_edit(device, expected, SETTLE, until_equal=True)
                if after == expected:
                    clean += 1
                elif after is None:
                    notes.append(
                        f"trial {trial + 1} (User {target:03d}): the edit "
                        f"buffer did not answer after the Program Change"
                    )
                elif after == before:
                    notes.append(
                        f"trial {trial + 1} (User {target:03d}): still "
                        f"{after!r} -- unchanged, so the Program Change was "
                        f"ignored or landed in the previous bank's slot "
                        f"{target:03d}"
                    )
                else:
                    notes.append(
                        f"trial {trial + 1} (User {target:03d}): the edit "
                        f"buffer carried {after!r}, not {expected!r}"
                    )

            print(
                f"{gap * 1000:8.1f}ms  {clean}/{conclusive} clean, "
                f"{trials - conclusive} inconclusive"
            )
            for note in notes[:SHOWN]:
                print(f"      {note}")
            if len(notes) > SHOWN:
                print(f"      ... and {len(notes) - SHOWN} more")
            results.append(
                SelectResult(
                    gap=gap,
                    clean=clean,
                    conclusive=conclusive,
                    trials=trials,
                    notes=notes,
                )
            )
    finally:
        b.SELECT_GAP = original
    return results


def smallest_clean_send(results: list[GapResult]) -> float | None:
    """The smallest gap whose every repeat matched the reference."""
    clean = [r.gap for r in results if r.clean == r.repeats]
    return min(clean) if clean else None


def smallest_clean_select(results: list[SelectResult]) -> float | None:
    """The smallest gap whose every conclusive trial landed."""
    clean = [r.gap for r in results if r.conclusive == r.trials and r.clean == r.trials]
    return min(clean) if clean else None


def _hex(message: bytes, *, last: str | None = None) -> str:
    """A message as spaced hex bytes; ``last`` replaces the final byte."""
    parts = [f"{byte:02X}" for byte in message]
    if last is not None and parts:
        parts[-1] = last
    return " ".join(parts)


def _constant(name: str, measured: float | None, why: str) -> str:
    """One paste-ready line: the measured value, or the current one."""
    current = getattr(b, name)
    if measured is None:
        return f"{name} = {current:.3f}   # unchanged: {why}"
    return f"{name} = {measured:.3f}"


def print_constants(
    send_gap: float | None,
    select_gap: float | None,
    send_why: str = "no candidate gap read the bank cleanly",
    select_why: str = "no candidate gap selected cleanly",
) -> None:
    """The final block, ready to paste into ``nano/bridge.py``."""
    print("")
    print("recommended constants, from what this run measured")
    print("-" * 60)
    print(_constant("SEND_GAP", send_gap, send_why))
    print(_constant("SELECT_GAP", select_gap, select_why))
    print("")
    print("A measured value supersedes the guess. This tool does not edit")
    print("nano/bridge.py: make the change deliberately, and record the run")
    print("in docs/RESOLUTION_NOTES.md.")


def describe_plan(
    args: argparse.Namespace,
    gaps: list[float],
    channel: int,
    config_path: str,
) -> None:
    """Print what will happen, before anything is opened."""
    print("MEASURE SEND_GAP / SELECT_GAP -- A BENCH TOOL")
    print("=" * 60)
    print("This tool drives the unit and must be run alone. Quit every other")
    print("MIDI program, and do not touch the front panel while it measures.")
    print("")
    print("It changes no memory: it sends no store message, only dump")
    print("requests. The SELECT_GAP half also sends Bank Select and Program")
    print("Change -- that changes what is playing and may make a sound --")
    print("and is skipped by --no-select. Put the unit in Program mode.")
    print("")
    if args.port:
        target = f"output {args.port!r}, input {args.recv_port or args.port!r}"
    elif args.scan:
        target = "sweep every MIDI port (--scan)"
    else:
        target = (
            f"the port remembered in {config_path} "
            f"(sweeping only if it does not answer)"
        )
    if args.recv_port and not args.port:
        print("note: --recv-port is used only with --port; the remembered")
        print("      path carries its own pair.")
        print("")
    print(f"  port        : {target}")
    print(f"  channel     : {channel + 1} (MIDI channel)")
    print(f"  programs    : {args.count} of the User bank")
    print(
        f"  reference   : {args.reference_gap * 1000:.0f} ms "
        f"x {REFERENCE_PASSES} passes"
    )
    print(f"  gaps        : {', '.join(f'{gap:.3f}' for gap in gaps)} s")
    print(f"  repeats     : {args.repeats} bank read(s) per gap")
    if args.no_select:
        print("  SELECT_GAP  : skipped (--no-select)")
    else:
        print(
            f"  SELECT_GAP  : {args.trials} trial(s) per gap, "
            f"{PREVIOUS_BANK} -> {TARGET_BANK}"
        )


def build_parser() -> argparse.ArgumentParser:
    """The family's options, then this tool's own."""
    parser = make_parser(
        "measure_send_gap",
        "Measure SEND_GAP and SELECT_GAP against the unit. Bench tool; "
        "opens a real MIDI port.",
        epilog=(
            "examples:\n"
            "  python3 tools/measure_send_gap.py                  # dry listing\n"
            '  python3 tools/measure_send_gap.py --yes --port "X:1"\n'
            "  python3 tools/measure_send_gap.py --yes --scan --count 8\n"
            "  python3 tools/measure_send_gap.py --yes "
            "--gaps 0.000,0.005,0.010 --no-select"
        ),
        distribution="nanosyned",
    )
    add_common_arguments(
        parser,
        port=True,
        scan=True,
        recv_port=True,
        channel=True,
        config=True,
        demo=False,
        yes=True,
    )
    parser.add_argument(
        "--gaps",
        metavar="SECONDS,...",
        default=None,
        help="comma-separated candidate gaps, shortest first "
        f"(default: {','.join(f'{gap:.3f}' for gap in DEFAULT_GAPS)})",
    )
    parser.add_argument(
        "--reference-gap",
        metavar="SECONDS",
        type=float,
        default=DEFAULT_REFERENCE_GAP,
        help="gap for the reference read; must exceed every --gaps value "
        f"(default: {DEFAULT_REFERENCE_GAP:.3f})",
    )
    parser.add_argument(
        "--count",
        metavar="N",
        type=int,
        default=banks.PROGRAMS_PER_BANK,
        help="how many User programs to read, 1-128 "
        f"(default: {banks.PROGRAMS_PER_BANK})",
    )
    parser.add_argument(
        "--repeats",
        metavar="N",
        type=int,
        default=1,
        help="bank reads per SEND_GAP candidate; a marginal gap fails "
        "intermittently, so 3 is better evidence (default: 1)",
    )
    parser.add_argument(
        "--trials",
        metavar="N",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"selection trials per SELECT_GAP candidate (default: {DEFAULT_TRIALS})",
    )
    parser.add_argument(
        "--no-select",
        action="store_true",
        help="skip the SELECT_GAP half, which changes what plays and may make a sound",
    )
    return parser


def gaps_of(parser: argparse.ArgumentParser, text: str | None) -> list[float]:
    """Parse ``--gaps``, or return the defaults."""
    if text is None:
        return list(DEFAULT_GAPS)
    try:
        gaps = [float(part) for part in text.split(",") if part.strip()]
    except ValueError:
        parser.error(f"--gaps: {text!r} is not a comma-separated list of numbers")
    if not gaps:
        parser.error("--gaps needs at least one number")
    return gaps


def open_device(
    args: argparse.Namespace, channel: int, config_path: str
) -> b.NanoBridge | None:
    """Open the port ``--port`` names, or the remembered/swept one."""
    try:
        if args.port:
            return b.NanoBridge.open(
                args.port, recv_port=args.recv_port, channel=channel
            )
        return b.NanoBridge.connect(
            config_path=config_path,
            channel=channel,
            scan=args.scan,
            on_try=lambda name: print(f"  probing {name}...", file=sys.stderr),
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def settings(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[list[float], int, str]:
    """Validate the options, before anything is opened."""
    gaps = gaps_of(parser, args.gaps)
    if any(gap < 0 for gap in gaps):
        parser.error("every --gaps value must be zero or more")
    if args.reference_gap <= max(gaps):
        parser.error("--reference-gap must be longer than every --gaps value")
    if not 1 <= args.count <= banks.PROGRAMS_PER_BANK:
        parser.error(f"--count is 1-{banks.PROGRAMS_PER_BANK}")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    if args.trials < 1:
        parser.error("--trials must be at least 1")
    validate_common(args)

    config_path = args.config or cfg.DEFAULT_PATH
    channel = channel_of(args, default=cfg.load_channel(config_path)) or 0
    return gaps, channel, config_path


def unit_answers(device: b.NanoBridge) -> bool:
    """One Global Dump Request, so a wrong port fails in half a second."""
    try:
        device.read_global(timeout=b.PROBE_TIMEOUT)
    except TimeoutError:
        print(
            "nothing answered a Global Dump Request on that port. The unit "
            "may be off, on another port, or not carrying the reply back to "
            "this computer.",
            file=sys.stderr,
        )
        return False
    return True


def report(
    send_results: list[GapResult],
    select_results: list[SelectResult],
    gaps: list[float],
    skipped: bool,
) -> None:
    """Turn the tables into the paste-ready block and its caveats."""
    send_gap = smallest_clean_send(send_results)
    select_gap = smallest_clean_select(select_results)
    exact = [r.gap for r in send_results if r.clean == r.repeats]
    print("")
    if exact:
        print(
            "gaps that reproduced the reference exactly: "
            + ", ".join(f"{gap:.3f}" for gap in exact)
            + " s"
        )
    else:
        print("no candidate gap reproduced the reference exactly.")
    select_why = (
        "skipped with --no-select" if skipped else "no candidate gap selected cleanly"
    )
    print_constants(send_gap, select_gap, select_why=select_why)
    if send_gap is None:
        print(
            "No candidate SEND_GAP was clean; extend --gaps upwards "
            "before trusting any value."
        )
    elif send_gap == min(gaps):
        print(
            f"Even the shortest gap tried ({send_gap:.3f} s) was clean, so "
            f"the edge is not in this list. Extend --gaps downwards to look "
            f"further (0.000 is as low as it goes)."
        )
    if select_gap is not None and select_gap == min(gaps):
        print(
            f"Even the shortest SELECT_GAP tried ({select_gap:.3f} s) selected cleanly."
        )


def measure(
    args: argparse.Namespace, gaps: list[float], channel: int, config_path: str
) -> int:
    """Open the unit, take the reference, sweep, and report."""
    device = open_device(args, channel, config_path)
    if device is None:
        return 1
    try:
        if not unit_answers(device):
            return 1

        print(
            f"reading {args.count} User program(s) for the reference...",
            file=sys.stderr,
        )
        reference = take_reference(device, args.count, args.reference_gap)
        if reference is None:
            print_constants(
                None,
                None,
                send_why="the reference read failed",
                select_why="the reference read failed, so it was not measured",
            )
            print("No measurement was taken, so keep the current guesses.")
            return 1

        send_results = measure_send(device, reference, gaps, args.count, args.repeats)
        select_results = (
            []
            if args.no_select
            else measure_select(
                device,
                Bench(reference, args.reference_gap, channel),
                gaps,
                args.trials,
            )
        )
        report(send_results, select_results, gaps, args.no_select)
        return 0
    except (LookupError, TimeoutError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        device.close()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    gaps, channel, config_path = settings(parser, args)

    describe_plan(args, gaps, channel, config_path)
    if not args.yes:
        print("")
        print("dry run: nothing was opened and nothing was sent.")
        print("Re-run with --yes to drive the unit.")
        return 0

    b.install_clean_exit()
    print("", file=sys.stderr)
    return measure(args, gaps, channel, config_path)


if __name__ == "__main__":
    raise SystemExit(main())
