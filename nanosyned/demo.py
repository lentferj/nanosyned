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

"""A NanoSynth that is not there.

**Every name here is invented**, from a word pool chosen to be obviously
not Alesis's, so that a screenshot taken in demo mode cannot be mistaken
for a real machine's contents. That is the same rule the sibling projects
apply to their instruments' ROM names, and it applies here for the same
reason: those names are Alesis's work, not this project's, and this
project does not redistribute them.

The demo opens no MIDI port and constructs no bridge, so it is safe to run
beside a session that is driving the hardware.
"""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from nano import banks
from nano import messages as m
from nano import records as rec

__all__ = ["DemoDevice", "demo_name", "demo_mix_name"]

#: Deliberately silly, and deliberately not anybody's product names.
_HEADS = ("Tin", "Glass", "Paper", "Rubber", "Copper", "Velvet", "Chalk",
          "Iron", "Wool", "Amber", "Slate", "Cork", "Linen", "Pewter",
          "Willow", "Basalt")
_TAILS = ("Bell", "Drone", "Pluck", "Wash", "Stab", "Sweep", "Hum", "Bow",
          "Choir", "Reed", "Thud", "Shine", "Comb", "Gust", "Coil", "Loom")


def demo_name(bank_id: str, number: int) -> str:
    """An invented name, stable for a given slot."""
    seed = (sum(ord(c) for c in bank_id) * 7 + number * 13)
    head = _HEADS[seed % len(_HEADS)]
    tail = _TAILS[(seed // len(_HEADS)) % len(_TAILS)]
    return f"{head} {tail}"[:m.NAME_CHARS]


def demo_mix_name(number: int) -> str:
    seed = number * 11 + 3
    return f"{_HEADS[seed % len(_HEADS)]} Set"[:m.NAME_CHARS]


def _record(size: int, name: str, offset: int, number: int) -> bytes:
    record = bytearray(size)
    m.encode_name(record, name, offset)
    # A byte with bit 7 set, past the name, so that the packing is
    # actually exercised. A fake whose data were all 7-bit would let a
    # broken pack/unpack pass every test.
    record[-1] = 0x80 | (number & 0x7F)
    return bytes(record)


class DemoDevice:
    """Answers the subset of the protocol nanosyned speaks."""

    def __init__(self, *, latency: float = 0.0, channel: int = 0) -> None:
        self.description = "demo (no MIDI ports opened)"
        self.channel = channel
        self.timeout = 1.0
        self.latency = latency
        self.port: Optional[str] = None
        self.recv_port: Optional[str] = None
        self.selected: Optional[banks.Slot] = None
        self.selected_channel: int = channel
        #: ``(slot, channel)`` for every selection, in order. The channel
        #: is recorded because a demo that dropped it would let a test
        #: named for the channel pass while asserting only that something
        #: was sent -- which is what happened in the sibling p2ked.
        self.selected_log: List[Tuple[banks.Slot, int]] = []
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _tick(self) -> None:
        if self.latency:
            time.sleep(self.latency)

    # --- reading ------------------------------------------------------------

    def identify(self, *, timeout: Optional[float] = None) -> Optional[dict]:
        """The shape `messages.identity_reply_fields` returns.

        Present so that `status` and the TUI's device screen take the same
        path under --demo as against hardware. The sibling x5ded's demo
        had neither this nor its current-program counterpart, and both CLI
        paths raised AttributeError past the handler that was supposed to
        catch device trouble.
        """
        self._tick()
        return {
            "channel": self.channel,
            "manufacturer": m.ALESIS_ID,
            "family": (m.QS_FAMILY, 0),
            "member": (m.NANOSYNTH_MEMBER, 0),
            "version": "0100",
            "is_alesis": True,
            "is_qs_family": True,
            "is_nanosynth": True,
        }

    def read_program(self, number: int, *,
                     timeout: Optional[float] = None) -> bytes:
        self._tick()
        if not 0 <= number <= 127:
            raise m.ProtocolError(f"user program {number} is outside 0-127")
        name = ("Off" if number == banks.SILENT_PROGRAM[1]
                else demo_name("USER", number))
        return _record(rec.PROGRAM_BYTES, name, m.NAME_BIT_OFFSET, number)

    def read_program_names(
            self, *, timeout: Optional[float] = None,
            on_progress: Optional[Callable[[int, int], None]] = None
    ) -> Dict[int, str]:
        out = {}
        for number in range(banks.PROGRAMS_PER_BANK):
            out[number] = rec.program_name(self.read_program(number))
            if on_progress is not None:
                on_progress(number + 1, banks.PROGRAMS_PER_BANK)
        return out

    def read_edit_program(self, *,
                          timeout: Optional[float] = None) -> bytes:
        self._tick()
        slot = self.selected
        if slot is None:
            return _record(rec.PROGRAM_BYTES, demo_name("GM", 0),
                           m.NAME_BIT_OFFSET, 0)
        return _record(rec.PROGRAM_BYTES,
                       demo_name(slot.bank_id, slot.number),
                       m.NAME_BIT_OFFSET, slot.number)

    def read_mix(self, number: int, *,
                 timeout: Optional[float] = None) -> bytes:
        self._tick()
        if not 0 <= number < banks.MIXES:
            raise m.ProtocolError(f"mix {number} is outside 0-{banks.MIXES-1}")
        return _record(rec.MIX_BYTES, demo_mix_name(number),
                       rec.MIX_NAME_BIT_OFFSET, number)

    def read_mix_names(
            self, *, timeout: Optional[float] = None,
            on_progress: Optional[Callable[[int, int], None]] = None
    ) -> Dict[int, str]:
        out = {}
        for number in range(banks.MIXES):
            out[number] = rec.mix_name(self.read_mix(number))
            if on_progress is not None:
                on_progress(number + 1, banks.MIXES)
        return out

    def read_global(self, *, timeout: Optional[float] = None) -> bytes:
        self._tick()
        return bytes(rec.GLOBAL_BYTES)

    # --- the one thing that makes a sound ----------------------------------

    def select(self, target: banks.Slot) -> None:
        """Select a program. **This changes what the unit is playing.**"""
        self._tick()
        self.selected = target
        self.selected_channel = self.channel
        self.selected_log.append((target, self.channel))
