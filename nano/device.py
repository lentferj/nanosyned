# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The shape of the Device interface is ported from the sibling emorphed
# project, which fixes the same need, and which carries the same licence:
#   Copyright (C) 2026  emorphed contributors
#                                     - GPL-2.0-or-later
# The library beneath the real device is vinsynlib, shared by the whole
# family of these tools.
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

"""The interface both devices answer to.

The app talks to *a* device. The real one is :class:`nano.bridge.NanoBridge`,
which opens MIDI ports and carries the Alesis protocol; the demo is
:class:`nanosyned.demo.DemoDevice`, which answers the same calls from memory.
The demo is a structural clone, not a subclass, on purpose: it must open no
MIDI port at all, and it must be usable in tests and beside a live session
without anything about a real unit being reachable from it.

This Protocol is the seam the two meet at, and it is deliberately the
*smallest* set of methods the app and the CLI use -- nothing more, so
neither implementation is asked to fake anything it does not honestly do.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from nano import banks

__all__ = ["Device"]


@runtime_checkable
class Device(Protocol):
    """What nanosyned asks of a device, real or invented."""

    description: str
    channel: int
    # The port names as opened, "out -> in" split; both are None for the
    # demo, which never opened anything.
    port: str | None
    recv_port: str | None
    timeout: float

    def close(self) -> None:
        """Shut the connection down; safe twice, and after a failure."""
        ...

    def identify(self, *, timeout: float | None = None) -> dict | None:
        """Ask who is there. **Makes no sound.** ``None`` when no one answers."""
        ...

    def read_program(self, number: int, *, timeout: float | None = None) -> bytes:
        """One user program's record. **Silent.**"""
        ...

    def read_program_names(
        self,
        *,
        timeout: float | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[int, str]:
        """Every user program name. **Silent.** Many round trips; see on_progress."""
        ...

    def read_edit_program(
        self, *, edit: int = 0, timeout: float | None = None
    ) -> bytes:
        """The edit buffer: whatever the unit is playing. **Silent.**"""
        ...

    def read_mix(self, number: int, *, timeout: float | None = None) -> bytes:
        """One of the 100 mixes. **Silent.**"""
        ...

    def read_mix_names(
        self,
        *,
        timeout: float | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[int, str]:
        """Every mix name. **Silent.** Many round trips; see on_progress."""
        ...

    def read_global(self, *, timeout: float | None = None) -> bytes:
        """Every global parameter, in one dump. **Silent.**"""
        ...

    def select(self, target: banks.Slot) -> None:
        """Select a program. **This changes what the unit is playing.**"""
        ...

    def select_mix(self, number: int) -> None:
        """Select a mix. **This changes what the unit is playing.**"""
        ...
