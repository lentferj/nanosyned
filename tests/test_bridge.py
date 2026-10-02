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

"""The MIDI bridge's process-level bits. No port is opened, no hardware."""

import signal

import pytest

from nano import bridge

_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@pytest.fixture
def _restored_signals():
    """Put the process's handlers back however the test ends.

    Underscored so vulture, which does not know a pytest fixture is used by
    being named, does not report it as a dead function.
    """
    before = {sig: signal.getsignal(sig) for sig in _SIGNALS}
    try:
        yield
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


class TestCleanExit:
    """main() calls install_clean_exit() on the real-hardware path. It has
    to exist -- it did not, and the AttributeError was invisible because
    every test runs the demo path -- and it has to turn a termination
    signal into an unwinding SystemExit, or the port stays open."""

    def test_it_replaces_the_termination_handlers(self, _restored_signals):
        before = {sig: signal.getsignal(sig) for sig in _SIGNALS}
        bridge.install_clean_exit()
        for sig in _SIGNALS:
            assert callable(signal.getsignal(sig))
            assert signal.getsignal(sig) is not before[sig]

    def test_the_handler_raises_system_exit(self, _restored_signals):
        bridge.install_clean_exit()
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)
