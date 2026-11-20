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
beside a session that is driving the hardware. It satisfies
:class:`nano.device.Device` structurally -- same calls, same shapes -- which
is what lets the app be written against that Protocol and run against
either device.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from nano import banks
from nano import messages as m
from nano import records as rec

__all__ = ["DemoDevice", "demo_mix_name", "demo_name"]

#: Deliberately silly, and deliberately not anybody's product names.
_HEADS = (
    "Tin",
    "Glass",
    "Paper",
    "Rubber",
    "Copper",
    "Velvet",
    "Chalk",
    "Iron",
    "Wool",
    "Amber",
    "Slate",
    "Cork",
    "Linen",
    "Pewter",
    "Willow",
    "Basalt",
)
_TAILS = (
    "Bell",
    "Drone",
    "Pluck",
    "Wash",
    "Stab",
    "Sweep",
    "Hum",
    "Bow",
    "Choir",
    "Reed",
    "Thud",
    "Shine",
    "Comb",
    "Gust",
    "Coil",
    "Loom",
)


def demo_name(bank_id: str, number: int) -> str:
    """An invented name, stable for a given slot."""
    seed = sum(ord(c) for c in bank_id) * 7 + number * 13
    head = _HEADS[seed % len(_HEADS)]
    tail = _TAILS[(seed // len(_HEADS)) % len(_TAILS)]
    return f"{head} {tail}"[: m.NAME_CHARS]


def demo_mix_name(number: int) -> str:
    seed = number * 11 + 3
    return f"{_HEADS[seed % len(_HEADS)]} Set"[: m.NAME_CHARS]


def _record(size: int, name: str, offset: int, number: int) -> bytes:
    record = bytearray(size)
    m.encode_name(record, name, offset)
    # A byte with bit 7 set, past the name, so that the packing is
    # actually exercised. A fake whose data were all 7-bit would let a
    # broken pack/unpack pass every test.
    record[-1] = 0x80 | (number & 0x7F)
    return bytes(record)


def _default_program(number: int) -> bytes:
    """What the demo's user bank holds before anything is written."""
    name = "Off" if number == banks.SILENT_PROGRAM[1] else demo_name("USER", number)
    return _record(rec.PROGRAM_BYTES, name, m.NAME_BIT_OFFSET, number)


def _default_effect(number: int) -> bytes:
    name = f"Effect {number:03d}"
    return _record(rec.EFFECTS_BYTES, name, m.NAME_BIT_OFFSET, number)


def _default_mix(number: int) -> bytes:
    return _record(
        rec.MIX_BYTES, demo_mix_name(number), rec.MIX_NAME_BIT_OFFSET, number
    )


class DemoDevice:
    """Answers the subset of the protocol nanosyned speaks."""

    def __init__(self, *, latency: float = 0.0, channel: int = 0) -> None:
        self.description = "demo (no MIDI ports opened)"
        self.channel = channel
        self.timeout = 1.0
        self.latency = latency
        self.port: str | None = None
        self.recv_port: str | None = None
        #: Structural parity with :class:`nano.bridge.NanoBridge`: the demo
        #: never sweeps for a port it does not open, so both stay at the
        #: value a remembered-port launch has.
        self.swept: bool = False
        self.probe_seconds: float = 0.0
        self.selected: banks.Slot | None = None
        self.selected_channel: int = channel
        #: ``(slot, channel)`` for every selection, in order. The channel
        #: is recorded because a demo that dropped it would let a test
        #: named for the channel pass while asserting only that something
        #: was sent -- which is what happened in the sibling p2ked.
        self.selected_log: list[tuple[banks.Slot, int]] = []
        #: The user bank as the unit holds it, seeded with the invented
        #: names this demo has always answered with. A write replaces an
        #: entry, and ``read_program`` returns what is in here -- which is
        #: what lets a caller prove "read back == written" against the same
        #: code it runs against the unit.
        self._programs: dict[int, bytes] = {
            number: _default_program(number)
            for number in range(banks.PROGRAMS_PER_BANK)
        }
        self._mixes: dict[int, bytes] = {
            number: _default_mix(number) for number in range(banks.MIXES)
        }
        self._effects: dict[int, bytes] = {
            number: _default_effect(number) for number in range(128)
        }
        self._global: bytes = bytes(rec.GLOBAL_BYTES)
        #: The effects edit buffer. Nothing reads it back over this
        #: protocol's subset, so it is kept for the log's sake.
        self.edit_effects: bytes | None = None
        #: The program edit buffer. Seeded from the current selection and
        #: replaced by a load, which is what a safe parameter probe sends --
        #: and what must never be mistaken for a store.
        self._edit_buffer: bytes | None = None
        #: Every write, in order. Kept apart by kind so a test can say
        #: "nothing was written" (``program_writes == []``) without
        #: inspecting a count of everything that did happen.
        self.program_writes: list[tuple[int, bytes]] = []
        self.edit_program_writes: list[bytes] = []
        self.effect_writes: list[tuple[int, bytes]] = []
        self.edit_effect_writes: list[bytes] = []
        self.mix_writes: list[tuple[int, bytes]] = []
        self.global_writes: list[bytes] = []
        self.midi_edits: list[tuple[int, int, int, int, int, int, int]] = []
        self.mode_selects: list[bool] = []
        self._closed = False

    def close(self) -> None:
        self._closed = True

    def _tick(self) -> None:
        """Every request passes through here, as through a live port.

        Matches the sibling emorphed's demo: after ``close()`` every
        request raises, the way a closed port would, so a caller that kept
        using the device learns it promptly rather than being answered
        politely by a unit that is not there.
        """
        if self._closed:
            raise RuntimeError(
                "this demo device is closed; a real bridge would be a closed port"
            )
        if self.latency:
            time.sleep(self.latency)

    # --- reading ------------------------------------------------------------

    def identify(self, *, timeout: float | None = None) -> dict | None:
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

    def read_program(self, number: int, *, timeout: float | None = None) -> bytes:
        self._tick()
        if not 0 <= number <= 127:
            raise m.ProtocolError(f"user program {number} is outside 0-127")
        return self._programs[number]

    def read_program_names(
        self,
        *,
        timeout: float | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[int, str]:
        out = {}
        for number in range(banks.PROGRAMS_PER_BANK):
            out[number] = rec.program_name(self.read_program(number))
            if on_progress is not None:
                on_progress(number + 1, banks.PROGRAMS_PER_BANK)
        return out

    def read_edit_program(
        self, *, edit: int = 0, timeout: float | None = None
    ) -> bytes:
        # The demo keeps one buffer: it has no mixes to give 16 more.
        self._tick()
        if self._edit_buffer is None:
            slot = self.selected
            if slot is None:
                return _record(
                    rec.PROGRAM_BYTES, demo_name("GM", 0), m.NAME_BIT_OFFSET, 0
                )
            return _record(
                rec.PROGRAM_BYTES,
                demo_name(slot.bank_id, slot.number),
                m.NAME_BIT_OFFSET,
                slot.number,
            )
        return self._edit_buffer

    def read_mix(self, number: int, *, timeout: float | None = None) -> bytes:
        self._tick()
        if not 0 <= number < banks.MIXES:
            raise m.ProtocolError(f"mix {number} is outside 0-{banks.MIXES - 1}")
        return self._mixes[number]

    def read_mix_names(
        self,
        *,
        timeout: float | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> dict[int, str]:
        out = {}
        for number in range(banks.MIXES):
            out[number] = rec.mix_name(self.read_mix(number))
            if on_progress is not None:
                on_progress(number + 1, banks.MIXES)
        return out

    def read_global(self, *, timeout: float | None = None) -> bytes:
        self._tick()
        return self._global

    def read_effects(self, number: int, *, timeout: float | None = None) -> bytes:
        self._tick()
        if not 0 <= number <= 127:
            raise ValueError(f"effects {number} is outside 0-127")
        return self._effects[number]

    # --- writing, which the demo also keeps --------------------------------

    def write_program(
        self, number: int, record: bytes, *, timeout: float | None = None
    ) -> None:
        """Store one of the 128 **user** programs. **The demo keeps this.**

        Refuses program 127 for the same reason the unit does: it is
        hardwired silent and cannot be changed. Refusing it here means a
        caller that would have overwritten it fails identically against
        the demo and against the hardware.
        """
        self._tick()
        if not 0 <= number <= 127:
            raise m.ProtocolError(f"user program {number} is outside 0-127")
        if number == banks.SILENT_PROGRAM[1]:
            raise m.ProtocolError(
                f"user program {number} is hardwired silent and cannot be changed"
            )
        stored = bytes(record)
        self._programs[number] = stored
        self.program_writes.append((number, stored))

    def write_edit_program(
        self, record: bytes, *, edit: int = 0, timeout: float | None = None
    ) -> None:
        """Load the edit buffer. **Kept here too.** Does not store.

        Mirrors :meth:`nano.bridge.NanoBridge.write_edit_program`: refuses
        a short record, and keeps the loaded buffer the way a unit that
        took the load would. The unit is silent under a load, so the caller
        owns the read-back either way.
        """
        self._tick()
        stored = bytes(record)
        rec.check_size(stored, rec.PROGRAM_BYTES, "a program")
        m.edit_program_dump(stored, edit=edit)  # range checks, as the encoder does
        loaded = stored[: rec.PROGRAM_BYTES]
        self._edit_buffer = loaded
        self.edit_program_writes.append(loaded)

    def write_effects(
        self, number: int, record: bytes, *, timeout: float | None = None
    ) -> None:
        """Store one of the 128 **user** effects patches. **Kept here too.**"""
        self._tick()
        if not 0 <= number <= 127:
            raise m.ProtocolError(f"effects {number} is outside 0-127")
        stored = bytes(record)
        self._effects[number] = stored
        self.effect_writes.append((number, stored))

    def write_edit_effects(
        self, record: bytes, *, timeout: float | None = None
    ) -> None:
        """Store the effects edit buffer. **Kept here too.**"""
        self._tick()
        stored = bytes(record)
        self.edit_effects = stored
        self.edit_effect_writes.append(stored)

    def write_mix(
        self, number: int, record: bytes, *, timeout: float | None = None
    ) -> None:
        """Store a mix: ``0``-``99`` for a user slot, ``100`` for the buffer."""
        self._tick()
        if not 0 <= number <= 100:
            raise m.ProtocolError(f"mix {number} is outside 0-100")
        stored = bytes(record)
        self._mixes[number] = stored
        self.mix_writes.append((number, stored))

    def write_global(self, record: bytes, *, timeout: float | None = None) -> None:
        """Store the global settings. **Kept here too.**"""
        self._tick()
        stored = bytes(record)
        self._global = stored
        self.global_writes.append(stored)

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
        """Address one parameter for editing. **This changes what plays.**

        The encoder is called for its range checks only -- nothing is
        built or sent -- so the demo refuses exactly the fields the
        bridge's message builder refuses.
        """
        self._tick()
        m.midi_edit(mode, function, page, pot, value, sound=sound, channel=channel)
        self.midi_edits.append((mode, function, page, pot, value, sound, channel))

    def mode_select(self, mix_mode: bool) -> None:
        """Put the unit in Program or Mix mode. **This changes what plays.**"""
        self._tick()
        self.mode_selects.append(mix_mode)

    # --- the one thing that makes a sound ----------------------------------

    def select(self, target: banks.Slot) -> None:
        """Select a program. **This changes what the unit is playing.**"""
        self._tick()
        self.selected = target
        self.selected_channel = self.channel
        self.selected_log.append((target, self.channel))
