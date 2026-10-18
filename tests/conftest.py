# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""The ``--hardware`` option, a ``--scan`` override, and the unit fixture
for the file that uses them.

**Nothing here runs unless you ask for it.** CLAUDE.md's hardware rule is
that only one session drives the unit at a time, so the suite that talks
to a real Alesis NanoSynth is opt-in twice over: the ``--hardware`` flag,
and the machine actually answering. Everything else in the repo is
synthetic -- no bridge is ever constructed, no port opened -- and CI never
passes the flag, so ``tests/test_hardware.py`` skips there by design
rather than by accident. The environment variable covers the case of a
unit plugged into a runner nobody meant to address.

A skip is a skip, not a pass. ``-rs`` names the reason, so "the unit was
off" and "the offsets are wrong" never look like the same green.
"""

import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from nano.bridge import NanoBridge

#: Why the option is spelled out rather than folded into ``-m hardware``.
HARDWARE_HELP = (
    "run the tests that need a real Alesis NanoSynth on a MIDI port. "
    "They open the ports, so only one session may use them at a time. "
    "Without this flag they skip."
)

#: The ``--scan`` spelling: sweep every port instead of using the one the
#: config remembers. Needed after USB re-enumeration renumbers clients.
SCAN_HELP = (
    "sweep every MIDI port for the unit instead of using the remembered "
    "port, the way --scan does in the app."
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("hardware", "tests against a real Alesis NanoSynth")
    group.addoption(
        "--hardware",
        action="store_true",
        default=False,
        help=HARDWARE_HELP,
    )
    group.addoption(
        "--scan",
        action="store_true",
        default=False,
        help=SCAN_HELP,
    )


def _asked_for_hardware(config: pytest.Config) -> bool:
    """The flag, or the environment variable that says the same thing."""
    return bool(config.getoption("--hardware")) or bool(
        os.environ.get("NANOSYNED_HARDWARE")
    )


@pytest.fixture(scope="session")
def unit(request: pytest.FixtureRequest) -> Iterator["NanoBridge"]:
    """A live :class:`nano.bridge.NanoBridge`, or a skip saying why not.

    Session-scoped on purpose: one connection, one pair of ports, held for
    the whole run rather than opened and closed per test. The bridge
    learns the ports once, and the 128-request reads below are slow
    enough already.

    The ports come from the remembered pair, or from
    ``NANOSYNED_PORT`` / ``NANOSYNED_RECV_PORT`` when either is set --
    the one-connection-at-a-time rule means a test run must be able to
    name its port without editing the config both sessions read. The
    override is passed as ``remembered``, so sweep-on-silence still
    applies and connect's habit of filing the answer back into the
    config is connect's, not this fixture's invention. ``--scan`` forces
    the sweep instead.

    A failure to connect is a skip, never a failure, and the reason
    lists every cause rather than picking one: the unit answers a request
    it cannot serve with silence, so a timeout does not say whether it
    was off, on another port (USB renumbers them), refusing System
    Exclusive, or cabled behind a chain that only carries requests out.
    """
    if not _asked_for_hardware(request.config):
        pytest.skip(
            "hardware tests need --hardware (or NANOSYNED_HARDWARE=1); the "
            "suite that talks to a real Alesis NanoSynth is opt-in because "
            "only one session may drive the unit, and CLAUDE.md's rule is "
            "that every other path here is synthetic and opens no ports"
        )

    from nano import bridge as b

    scan = bool(request.config.getoption("--scan"))
    env_port = os.environ.get("NANOSYNED_PORT")
    env_recv = os.environ.get("NANOSYNED_RECV_PORT") or env_port
    remembered = (env_port, env_recv) if env_port else None

    try:
        connection = b.NanoBridge.connect(scan=scan, remembered=remembered)
    except Exception as exc:
        # One retry, sweeping. The remembered port may have been
        # renumbered since it was saved -- or the config may name a port
        # for a different instrument entirely, since these programs share
        # a bench.
        try:
            connection = b.NanoBridge.connect(scan=True, remembered=remembered)
        except Exception as exc2:
            pytest.skip(
                f"no NanoSynth answered (remembered or overridden port: "
                f"{exc}; the sweep that followed: {exc2}). The unit may be "
                "powered off, on the wrong port (USB renumbers them), have "
                "System Exclusive reception disabled, or sit behind a MIDI "
                "chain whose thru carries the requests out but not the "
                "replies back -- easy to get wrong when the unit hangs off "
                "another device. This unit builds a dump it does not send, "
                "so the silence does not say which."
            )
    try:
        yield connection
    finally:
        # The ports are this run's to close, whatever happened inside:
        # leaving them open is how the next session's "the unit answered
        # nobody" becomes a mystery instead of a diagnosis.
        connection.close()
