# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The parameter tables are transcribed as data from Alesis's published
# QS6/7/8/R System Exclusive specification (published 1997-02-03). The
# specification's own conventions -- two's complement for Global, offset
# binary for the packed Mix, Program and Effects records -- are preserved
# here verbatim rather than normalised into one domain.
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

"""The instrument's parameters, and where each one lives in a record.

Alesis's specification publishes one table per mode, and every row of every
table is the same handful of things: a ``(mode, function, page, pot)``
address, a label, a value range, a bit width, and a bit address into the
*unpacked* record. The ``10`` MIDI Edit message addresses a parameter by the
first four; a program, mix or effects dump carries the value at the last.
This module is that table, as data.

**Data, not logic.** The tuples below are the single source both readers
use. :func:`midi_edit_for` turns a :class:`Param` back into the message that
addresses it, and :mod:`nano.records` turns one plus a value into the bits of
a record. Nothing else should keep a copy of these numbers: a copy is a
second truth, and a second truth drifts.

**Transcription is a hypothesis; verification is the result.** Every row
here was read off the published specification, and a specification is a
lead, not proof about this firmware. ``verified=True`` on a row means a
controlled before/after probe on *this unit* confirmed both its ``offset``
and its value law, and ``value_law`` names the law that probe showed
(``"offset"``, ``"twos"`` or ``"raw"``). A row without the flag is still
*shown* by the editors, and is read-only there.

**This is a subset, deliberately.** The program's sound table alone is
eighty-five bytes of bitfields per sound, and the specification prints one
keyboard-sound table and one drum-sound table that each of the four sounds
may use. Here the Global table, the Mix common block, the Mix per-channel
template, the program common area and Effects configuration 0's primary
branch are complete; the effects rows that a pitch/delay type swaps for a
different interpretation share the same addresses and are noted below.
Of the sound block only the first thirty-one well-defined rows are
transcribed; the rest travels unaltered and is listed as ``# TODO(parity)``.
Adding a row is a transcription, not a design decision.

**The spec's own conventions are kept, not normalised away.** A Global
record stores its signed values in two's complement and needs no offset. A
Mix, Program or Effects record stores bipolar values in offset binary, and
the specification's Offset column is what converts one to the other. So for
a :class:`Param`, ``low``/``high`` are the parameter's two's-complement
limits and ``offset`` is the spec's Offset column:

* Mix/Program/Effects: ``low == offset`` and ``high - low`` is the spec's
  Limit; the stored (offset-binary) field runs ``0`` through ``high - low``,
  and adding ``offset`` to a stored value gives the two's-complement one.
* Global: ``offset`` is ``0`` and ``low``/``high`` are the spec's LoLim and
  HiLim; the stored byte is already two's complement.

Mixing the two domains up produces values that look plausible and are wrong,
which is the failure this module exists to prevent.

Two more conventions matter and are documented where they bite:

* bit order -- see :func:`nano.records.encode_bit_field`, which is MSB-first
  while the existing name helpers are low-bit-first;
* a bit address is into the byte record *after* unpacking, not into the
  packed bytes on the wire.

The ``10`` message takes the two's-complement value, so a parameter read out
of a packed record must have ``offset`` added before it is sent.

**The value law is a hypothesis until the probe confirms it.** :func:`law_of`
resolves the law a row's bits are stored under -- ``"twos"``, ``"offset"`` or
``"raw"`` -- from the probe's confirmation when there is one, and from the
row's own shape when there is not; :func:`stored_for` and
:func:`value_from_stored` are the two ends of that arithmetic, the helpers
the probe and the editors will both use.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from nano import records

__all__ = [  # noqa: RUF022 -- the tables-before-methods order is sorted plain
    "EFFECT_COMMON_PARAMS",
    "EFFECT_CONFIG_0_PARAMS",
    "EFFECT_MOD_PARAMS",
    "EFFECT_PARAMS",
    "GLOBAL_PARAMS",
    "KEYBOARD_SOUND_PARAMS",
    "MIX_CHANNEL_PARAMS",
    "MIX_COMMON_PARAMS",
    "MODE_NUMBERS",
    "PARAMS",
    "PROGRAM_COMMON_PARAMS",
    "Param",
    "VALUE_LAWS",
    "at",
    "by_label",
    "law_of",
    "midi_edit_for",
    "stored_for",
    "value_from_stored",
    "verified_params",
    "with_channel",
    "with_sound",
]

#: Which ``mm`` field of the ``10`` message selects each mode.
MODE_NUMBERS: Final[dict[str, int]] = {
    "global": 0,
    "mix": 1,
    "program": 2,
    "effects": 3,
}


#: The value laws a stored field can be written under, the unknown slot
#: leading the named ones. The probe sets one with a confirming before/after;
#: until it does, :func:`law_of` infers one from the row's own shape.
VALUE_LAWS: tuple[str, ...] = ("", "offset", "twos", "raw")


@dataclass(frozen=True)
class Param:
    """One row of one of the specification's parameter tables.

    The fields are the specification's columns, in its order, with the
    spec's prose kept as prose:

    ``mode``
        ``"global"``, ``"mix"``, ``"program"`` or ``"effects"``.
    ``function``, ``page``, ``pot``
        The direct-edit address, or ``-1`` in all three where the spec
        prints no address (a spare, the Clock, the ROM identifier).
    ``label``
        The spec's Parameter name, verbatim. Two rows in the Global table
        have the same name; those carry the spec's own bit address as a
        suffix so that a label-keyed mapping can hold both.
    ``low``, ``high``
        The parameter's two's-complement limits. See the module docstring
        for how these relate to the spec's Limit and Offset columns.
    ``bits``, ``bit_address``
        The width, and the index of the field's **least** significant bit
        in the unpacked record. The spec prints a range with the most
        significant bit first (``1:6-1:0``); its last address -- the low
        end -- is what is stored here, and the most significant bit sits at
        ``bit_address + bits - 1``, which is the spec's first address.
    ``offset``
        The spec's Offset column. Add it to a stored value to view it as
        two's complement.
    ``choices``, ``sound``, ``channel``
        Optional extras: named values where the spec lists them, and the
        sound/effect-bus or MIDI-channel index where a table repeats.
        ``sound`` is the spec's Send column in the Effects tables.
    ``verified``
        Whether a controlled before/after probe on this unit confirmed the
        row's ``offset`` **and** its value law. Every row starts False:
        the table is a transcription, and a transcription is a hypothesis.
        The editors show an unverified row and refuse to write it.
    ``value_law``
        The law the probe confirmed, when it confirmed one: ``"offset"``
        for a packed record (stored = value - ``offset``), ``"twos"`` for
        a two's-complement field as the Global record stores it, ``"raw"``
        for a plain unsigned field whose ``low`` is 0. ``""`` means
        unknown, which is every row until it is verified.
    """

    mode: str
    function: int
    page: int
    pot: int
    label: str
    low: int
    high: int
    bits: int
    bit_address: int
    offset: int = 0
    choices: tuple[str, ...] = ()
    sound: int | None = None
    channel: int | None = None
    verified: bool = False
    value_law: str = ""

    @property
    def span(self) -> int:
        """The spec's Limit: the width of the value range."""
        return self.high - self.low

    def clamp(self, value: int) -> int:
        """``value``, moved to the nearest legal value.

        The specification's own rule for the ``10`` message: "If the value
        received is out of range for the parameter selected, the range will
        be limited to the nearest legal value."
        """
        return max(self.low, min(self.high, value))


# The prose above the table says "The Global parameters are comprised of 19
# bytes of data", but the table itself numbers rows 0 through 19 -- twenty
# rows -- and the 0A dump description says its data "corresponds to 20 bytes
# of global data" (and that versions before 2.00 omit the last three). The
# table wins: all twenty rows are transcribed, rows 0 and 14 being the two
# spares. records.GLOBAL_BYTES is 20 to match.
GLOBAL_PARAMS: tuple[Param, ...] = (
    Param("global", -1, -1, -1, "Global spare (deleted parameter) 0:6-0:0", 0, 0, 7, 0),
    Param(
        "global",
        0,
        0,
        2,
        "Pitch transpose*",
        -12,
        12,
        8,
        8,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        0,
        3,
        "Pitch fine tune*",
        -99,
        99,
        8,
        16,
        verified=True,
        value_law="twos",
    ),
    Param("global", 0, 1, 0, "Keyboard scaling", 0, 99, 7, 24),
    Param("global", 0, 1, 1, "Keyboard curve *(QS6,7,8 only)", 0, 2, 2, 32),
    Param("global", 0, 1, 2, "Keyboard Transpose", -12, 12, 8, 40),
    Param("global", 0, 1, 3, "Keyboard mode *(QS6,7,8 only)", 0, 17, 5, 48),
    Param(
        "global",
        0,
        2,
        0,
        "Controller A number",
        0,
        120,
        7,
        56,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        2,
        1,
        "Controller B number",
        0,
        120,
        7,
        64,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        2,
        2,
        "Controller C number",
        0,
        120,
        7,
        72,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        2,
        3,
        "Controller D number",
        0,
        120,
        7,
        80,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        4,
        0,
        "Pedal 1 controller number",
        0,
        120,
        7,
        88,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        4,
        2,
        "Pedal 2 controller number",
        0,
        120,
        7,
        96,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global",
        0,
        5,
        0,
        "MIDI program select",
        0,
        17,
        5,
        104,
        verified=True,
        value_law="twos",
    ),
    Param(
        "global", -1, -1, -1, "Global spare (deleted parameter) 14:6-14:0", 0, 0, 7, 112
    ),
    Param("global", -1, -1, -1, "Clock *(QS7,8,R only)", 0, 1, 1, 120),
    Param("global", 0, 6, 0, "Mix Group Channel *(QSR only)", 0, 16, 5, 128),
    Param("global", 0, 0, 1, "General MIDI", 0, 1, 1, 136),
    Param(
        "global",
        0,
        3,
        1,
        "A-D controller reset",
        0,
        1,
        1,
        144,
        verified=True,
        value_law="twos",
    ),
    Param("global", 0, 3, 3, "A-D controller mode", 0, 2, 2, 152),
)

MIX_COMMON_PARAMS: tuple[Param, ...] = (
    Param("mix", 5, 0, 2, "Mix effect MIDI program change", 0, 1, 1, 0),
    Param(
        "mix", 5, 0, 3, "Mix effect chan", 0, 15, 4, 1, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 0, 0, "Mix name digit 0", 0, 95, 7, 5, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 1, 0, "Mix name digit 1", 0, 95, 7, 12, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 2, 0, "Mix name digit 2", 0, 95, 7, 19, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 3, 0, "Mix name digit 3", 0, 95, 7, 26, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 4, 0, "Mix name digit 4", 0, 95, 7, 33, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 5, 0, "Mix name digit 5", 0, 95, 7, 40, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 6, 0, "Mix name digit 6", 0, 95, 7, 47, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 7, 0, "Mix name digit 7", 0, 95, 7, 54, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 8, 0, "Mix name digit 8", 0, 95, 7, 61, verified=True, value_law="raw"
    ),
    Param(
        "mix", 6, 9, 0, "Mix name digit 9", 0, 95, 7, 68, verified=True, value_law="raw"
    ),
    Param("mix", -1, -1, -1, "Mix spare", 0, 0, 5, 75),
)

MIX_CHANNEL_PARAMS: tuple[Param, ...] = (
    Param("mix", 0, 0, 0, "Channel 1 program number", 0, 127, 7, 80),
    Param("mix", 0, 0, 2, "Channel 1 program type", 0, 1, 4, 87),
    Param(
        "mix", 0, 0, 3, "Channel 1 enable", 0, 1, 1, 91, verified=True, value_law="raw"
    ),
    Param(
        "mix", 1, 0, 0, "Channel 1 volume", 0, 99, 7, 92, verified=True, value_law="raw"
    ),
    Param("mix", 1, 0, 1, "Channel 1 pan", 0, 7, 3, 99, verified=True, value_law="raw"),
    Param(
        "mix", 1, 0, 2, "Channel 1 output", 0, 3, 2, 102, verified=True, value_law="raw"
    ),
    Param(
        "mix",
        2,
        0,
        0,
        "Channel 1 effect level",
        0,
        100,
        7,
        104,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        2,
        0,
        1,
        "Channel 1 effect bus",
        0,
        4,
        3,
        111,
        verified=True,
        value_law="raw",
    ),
    Param("mix", 3, 0, 0, "Channel 1 pitch octave", -2, 3, 3, 114, offset=-2),
    Param(
        "mix",
        3,
        0,
        2,
        "Channel 1 pitch semitone",
        -12,
        12,
        5,
        117,
        offset=-12,
        verified=True,
        value_law="offset",
    ),
    Param(
        "mix",
        4,
        0,
        0,
        "Channel 1 keyboard low note",
        0,
        127,
        7,
        122,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        0,
        1,
        "Channel 1 keyboard high note",
        0,
        127,
        7,
        129,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        1,
        0,
        "Channel 1 midi in on/off",
        0,
        1,
        1,
        136,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        1,
        2,
        "Channel 1 midi out on/off",
        0,
        1,
        1,
        137,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        1,
        3,
        "Channel 1 keyboard on/off **",
        0,
        1,
        1,
        138,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        2,
        0,
        "Channel 1 wheels on/off",
        0,
        1,
        1,
        139,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        2,
        1,
        "Channel 1 Aftertouch on/off",
        0,
        1,
        1,
        140,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        2,
        2,
        "Channel 1 Sustain pedal on/off",
        0,
        1,
        1,
        141,
        verified=True,
        value_law="raw",
    ),
    Param(
        "mix",
        4,
        2,
        3,
        "Channel 1 Pedals/controllers on/off",
        0,
        1,
        1,
        142,
        verified=True,
        value_law="raw",
    ),
    Param("mix", -1, -1, -1, "Channel 1 Spare", 0, 0, 1, 143),
)

EFFECT_COMMON_PARAMS: tuple[Param, ...] = (
    Param("effects", 2, 0, 0, "Effect spare (deleted parameter)", 0, 95, 7, 0),
    Param("effects", 2, 1, 0, "Effect spare (deleted parameter)", 0, 95, 7, 7),
    Param("effects", 2, 2, 0, "Effect spare (deleted parameter)", 0, 95, 7, 14),
    Param("effects", 2, 3, 0, "Effect spare (deleted parameter)", 0, 95, 7, 21),
    Param("effects", 2, 4, 0, "Effect spare (deleted parameter)", 0, 95, 7, 28),
    Param("effects", 2, 5, 0, "Effect spare (deleted parameter)", 0, 95, 7, 35),
    Param("effects", 2, 6, 0, "Effect spare (deleted parameter)", 0, 95, 7, 42),
    Param("effects", 2, 7, 0, "Effect spare (deleted parameter)", 0, 95, 7, 49),
    Param("effects", 2, 8, 0, "Effect spare (deleted parameter)", 0, 95, 7, 56),
    Param("effects", 2, 9, 0, "Effect spare (deleted parameter)", 0, 95, 7, 63),
    Param("effects", 2, 0, 0, "Effect configuration", 0, 4, 4, 70),
)

# Configuration 0 is conditional: when a pitch type selects chorus/flange
# the spec prints one set of rows, and pitch detune/resonator print another
# set at the same addresses with different labels and ranges; the delay rows
# likewise branch on mono/stereo/ping-pong. Only the first branch of each
# (chorus/flange, mono delay) is transcribed below, because the variants
# share the addresses and differ only in interpretation. The spec's unnamed
# filler spares are omitted for the same reason.
EFFECT_CONFIG_0_PARAMS: tuple[Param, ...] = (
    Param("effects", 0, 0, 0, "Send 1 pitch type", 0, 5, 3, 74, sound=0),
    Param("effects", 0, 1, 1, "Send 1 pitch speed", 0, 99, 7, 77, sound=0),
    Param("effects", 0, 1, 0, "Send 1 pitch shape", 0, 1, 1, 84, sound=0),
    Param("effects", 0, 1, 2, "Send 1 pitch depth", 0, 99, 7, 85, sound=0),
    Param("effects", 0, 1, 3, "Send 1 pitch feedback", 0, 99, 7, 92, sound=0),
    Param("effects", 5, 0, 0, "Send 1 pitch mix", 0, 99, 7, 99, sound=0),
    Param("effects", 4, 0, 0, "Send 1 delay type", 0, 2, 2, 106, sound=0),
    Param(
        "effects", 4, 1, 0, "Send 1 delay input", -99, 99, 8, 108, offset=-99, sound=0
    ),
    Param("effects", 4, 1, 1, "Send 1 delay 10ms", 0, 79, 7, 116, sound=0),
    Param("effects", 4, 1, 2, "Send 1 delay 1ms", 0, 9, 4, 123, sound=0),
    Param("effects", 4, 1, 3, "Send 1 delay feedback", 0, 99, 7, 137, sound=0),
    Param("effects", 5, 0, 1, "Send 1 delay mix", 0, 99, 7, 151, sound=0),
    Param("effects", 3, 1, 0, "Reverb type", 0, 6, 4, 158, sound=0),
    Param("effects", 3, 0, 0, "Send 1 reverb input 1", 0, 1, 1, 162, sound=0),
    Param("effects", 3, 0, 1, "Send 1 reverb input 2", 0, 2, 2, 163, sound=0),
    Param(
        "effects",
        3,
        0,
        2,
        "Send 1 reverb balance",
        -99,
        99,
        8,
        165,
        offset=-99,
        sound=0,
    ),
    Param("effects", 3, 0, 3, "Send 1 reverb input level", 0, 99, 7, 173, sound=0),
    Param("effects", 3, 1, 1, "Send 1 reverb prdly 10ms", 0, 29, 5, 180, sound=0),
    Param("effects", 3, 1, 2, "Send 1 reverb prdly 1ms", 0, 9, 4, 185, sound=0),
    Param(
        "effects",
        3,
        1,
        3,
        "Send 1 reverb inut premix",
        -99,
        99,
        8,
        189,
        offset=-99,
        sound=0,
    ),
    Param("effects", 3, 2, 0, "Send 1 reverb input filter", 0, 99, 7, 197, sound=0),
    Param("effects", 3, 2, 1, "Send 1 reverb decay", 0, 99, 7, 204, sound=0),
    Param("effects", 3, 3, 2, "Send 1 reverb diffusion", 0, 99, 7, 211, sound=0),
    Param("effects", 3, 3, 0, "Send 1 reverb density", 0, 99, 7, 218, sound=0),
    Param("effects", 3, 2, 2, "Send 1 reverb low decay", 0, 99, 7, 225, sound=0),
    Param("effects", 3, 2, 3, "Send 1 reverb high decay", 0, 99, 7, 232, sound=0),
    Param("effects", 5, 0, 2, "Send 1 reverb mix", 0, 99, 7, 239, sound=0),
    Param("effects", 0, 0, 0, "Send 2 pitch type", 0, 5, 3, 246, sound=1),
    Param("effects", 0, 1, 1, "Send 2 pitch speed", 0, 99, 7, 249, sound=1),
    Param("effects", 0, 1, 0, "Send 2 pitch shape", 0, 1, 1, 256, sound=1),
    Param("effects", 0, 1, 2, "Send 2 pitch depth", 0, 99, 7, 257, sound=1),
    Param("effects", 0, 1, 3, "Send 2 pitch feedback", 0, 99, 7, 264, sound=1),
    Param("effects", 5, 0, 0, "Send 2 pitch mix", 0, 99, 7, 271, sound=1),
    Param("effects", 4, 0, 0, "Send 2 delay type", 0, 2, 2, 278, sound=1),
    Param(
        "effects", 4, 1, 0, "Send 2 delay input", -99, 99, 8, 280, offset=-99, sound=1
    ),
    Param("effects", 4, 1, 1, "Send 2 delay 10ms", 0, 79, 7, 288, sound=1),
    Param("effects", 4, 1, 2, "Send 2 delay 1ms", 0, 9, 4, 295, sound=1),
    Param("effects", 4, 1, 3, "Send 2 delay feedback", 0, 99, 7, 309, sound=1),
    Param("effects", 5, 0, 1, "Send 2 delay mix", 0, 99, 7, 323, sound=1),
    Param("effects", 3, 0, 0, "Send 2 reverb input 1", 0, 1, 1, 330, sound=1),
    Param("effects", 3, 0, 1, "Send 2 reverb input 2", 0, 2, 2, 331, sound=1),
    Param(
        "effects",
        3,
        0,
        2,
        "Send 2 reverb balance",
        -99,
        99,
        8,
        333,
        offset=-99,
        sound=1,
    ),
    Param("effects", 3, 0, 3, "Send 2 reverb input level", 0, 99, 7, 341, sound=1),
    Param("effects", 0, 0, 0, "Send 3 pitch type", 0, 2, 2, 348, sound=2),
    Param("effects", 0, 1, 1, "Send 3 pitch speed", 0, 99, 7, 350, sound=2),
    Param("effects", 0, 1, 0, "Send 3 pitch shape", 0, 1, 1, 357, sound=2),
    Param("effects", 0, 1, 2, "Send 3 pitch depth", 0, 99, 7, 358, sound=2),
    Param("effects", 0, 1, 3, "Send 3 pitch feedback", 0, 99, 7, 365, sound=2),
    Param("effects", 5, 0, 0, "Send 3 pitch mix", 0, 99, 7, 372, sound=2),
    Param(
        "effects", 4, 0, 0, "Send 3 delay input", -99, 99, 8, 379, offset=-99, sound=2
    ),
    Param("effects", 4, 0, 1, "Send 3 delay 10ms", 0, 79, 7, 387, sound=2),
    Param("effects", 4, 0, 2, "Send 3 delay 1ms", 0, 9, 4, 394, sound=2),
    Param("effects", 4, 0, 3, "Send 3 delay feedback", 0, 99, 7, 398, sound=2),
    Param("effects", 5, 0, 1, "Send 3 delay mix", 0, 99, 7, 405, sound=2),
    Param("effects", 3, 0, 0, "Send 3 reverb input 1", 0, 1, 1, 412, sound=2),
    Param("effects", 3, 0, 1, "Send 3 reverb input 2", 0, 2, 2, 413, sound=2),
    Param(
        "effects",
        3,
        0,
        2,
        "Send 3 reverb balance",
        -99,
        99,
        8,
        415,
        offset=-99,
        sound=2,
    ),
    Param("effects", 3, 0, 3, "Send 3 reverb input level", 0, 99, 7, 423, sound=2),
    Param("effects", 4, 0, 1, "Send 4 delay 10ms", 0, 79, 7, 430, sound=3),
    Param("effects", 4, 0, 2, "Send 4 delay 1ms", 0, 9, 4, 437, sound=3),
    Param("effects", 4, 0, 3, "Send 4 delay feedback", 0, 99, 7, 441, sound=3),
    Param("effects", 5, 0, 0, "Send 4 delay mix", 0, 99, 7, 448, sound=3),
    Param(
        "effects",
        3,
        0,
        0,
        "Send 4 reverb balance",
        -99,
        99,
        8,
        455,
        offset=-99,
        sound=3,
    ),
    Param("effects", 3, 0, 2, "Send 4 reverb input level", 0, 99, 7, 463, sound=3),
)

EFFECT_MOD_PARAMS: tuple[Param, ...] = (
    Param("effects", 1, 0, 0, "MIDImod source 1", 0, 10, 4, 470),
    Param("effects", 1, 0, 1, "MIDImod destination 1", 0, 36, 6, 474),
    Param("effects", 1, 0, 2, "MIDImod level 1", -99, 99, 8, 480, offset=-99),
    Param("effects", 1, 1, 0, "MIDImod source 2", 0, 10, 4, 488),
    Param("effects", 1, 1, 1, "MIDImod destination 2", 0, 36, 6, 492),
    Param("effects", 1, 1, 2, "MIDImod level 2", -99, 99, 8, 498, offset=-99),
)

PROGRAM_COMMON_PARAMS: tuple[Param, ...] = (
    Param("program", -1, -1, -1, "Program spare (deleted parameter)", 0, 0, 7, 0),
    Param("program", -1, -1, -1, "Program spare (deleted parameter)", 0, 0, 1, 7),
    Param(
        "program",
        8,
        0,
        0,
        "Program name digit 0",
        0,
        95,
        7,
        8,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        1,
        0,
        "Program name digit 1",
        0,
        95,
        7,
        15,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        2,
        0,
        "Program name digit 2",
        0,
        95,
        7,
        22,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        3,
        0,
        "Program name digit 3",
        0,
        95,
        7,
        29,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        4,
        0,
        "Program name digit 4",
        0,
        95,
        7,
        36,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        5,
        0,
        "Program name digit 5",
        0,
        95,
        7,
        43,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        6,
        0,
        "Program name digit 6",
        0,
        95,
        7,
        50,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        7,
        0,
        "Program name digit 7",
        0,
        95,
        7,
        57,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        8,
        0,
        "Program name digit 8",
        0,
        95,
        7,
        64,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        8,
        9,
        0,
        "Program name digit 9",
        0,
        95,
        7,
        71,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        -1,
        -1,
        -1,
        "ROM Identifier",
        0,
        3,
        2,
        78,
        choices=(
            "Quadrasynth Plus / S4 Plus",
            "QS",
            "Reserved for future use",
            "Reserved for future use",
        ),
    ),
)

KEYBOARD_SOUND_PARAMS: tuple[Param, ...] = (
    Param("program", 16, 0, 0, "Keyboard / drum mode (=0)", 0, 1, 1, 0),
    Param("program", 0, 0, 0, "Sample group", 0, 47, 6, 1),
    Param("program", 0, 0, 2, "Sample number", 0, 127, 7, 7),
    Param(
        "program", 1, 0, 0, "Sound volume", 0, 99, 7, 14, verified=True, value_law="raw"
    ),
    Param("program", 1, 0, 1, "Sound pan", 0, 6, 3, 21, verified=True, value_law="raw"),
    Param(
        "program", 1, 0, 2, "Sound output", 0, 2, 2, 24, verified=True, value_law="raw"
    ),
    Param(
        "program",
        2,
        0,
        0,
        "Sound effect level",
        0,
        99,
        7,
        26,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        2,
        0,
        1,
        "Sound effect bus",
        0,
        3,
        2,
        33,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        3,
        0,
        0,
        "Sound pitch semitone",
        -24,
        24,
        6,
        35,
        offset=-24,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        3,
        0,
        2,
        "Sound pitch detune",
        -99,
        99,
        8,
        41,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        3,
        0,
        3,
        "Sound pitch detune type",
        0,
        1,
        1,
        49,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        3,
        1,
        0,
        "Sound pitch wheel mod",
        0,
        12,
        4,
        50,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        3,
        1,
        1,
        "Sound pitch aftertouch mod",
        -99,
        99,
        8,
        54,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        3,
        1,
        2,
        "Sound pitch lfo mod",
        -99,
        99,
        8,
        62,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        3,
        1,
        3,
        "Sound pitch env mod",
        -99,
        99,
        8,
        70,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        3,
        2,
        0,
        "Sound portamento mode",
        0,
        2,
        2,
        78,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        3,
        2,
        2,
        "Sound portamento rate",
        0,
        99,
        7,
        80,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        3,
        2,
        3,
        "Sound key mode",
        0,
        2,
        2,
        87,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        4,
        0,
        0,
        "Sound filter frequency",
        0,
        99,
        7,
        89,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        4,
        0,
        1,
        "Sound filter keyboard track",
        0,
        1,
        1,
        96,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        4,
        0,
        3,
        "Sound filter velocity mod",
        -99,
        99,
        8,
        97,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        4,
        1,
        0,
        "Sound filter pitch wheel mod",
        -99,
        99,
        8,
        105,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        4,
        1,
        1,
        "Sound filter aftertouch mod",
        -99,
        99,
        8,
        113,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        4,
        1,
        2,
        "Sound filter lfo mod",
        -99,
        99,
        8,
        121,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        4,
        1,
        3,
        "Sound filter env mod",
        -99,
        99,
        8,
        129,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        5,
        0,
        0,
        "Sound amp velocity curve",
        0,
        12,
        4,
        137,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        5,
        0,
        1,
        "Sound amp aftertouch mod",
        -99,
        99,
        8,
        141,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        5,
        0,
        2,
        "Sound amp alfo mod",
        -99,
        99,
        8,
        149,
        offset=-99,
        verified=True,
        value_law="offset",
    ),
    Param(
        "program",
        6,
        0,
        0,
        "Sound low note limit",
        0,
        127,
        7,
        157,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        6,
        0,
        1,
        "Sound high note limit",
        0,
        127,
        7,
        164,
        verified=True,
        value_law="raw",
    ),
    Param(
        "program",
        6,
        0,
        2,
        "Sound overlap",
        0,
        99,
        7,
        171,
        verified=True,
        value_law="raw",
    ),
)

# TODO(parity): rows 31 (Sound mod 1 source) through 121 (Drum number) of the
# keyboard-sound table are not transcribed yet, nor is the spec's separate
# Drum Sound table (rows 0-165, ``Keyboard / drum mode (=1)``). Until they
# are, those bits travel unaltered; nothing here writes them.


#: The Effects tables, in the order the spec prints them. Configuration 0's
#: rows and the modulation block are addressed by (function, page, pot,
#: sound); the common block's Send column is "x", so its ``sound`` is None.
EFFECT_PARAMS: tuple[Param, ...] = (
    EFFECT_COMMON_PARAMS + EFFECT_CONFIG_0_PARAMS + EFFECT_MOD_PARAMS
)

#: Every transcribed row, once. Templates (the mix channel block and the
#: keyboard sound block) appear once, with ``channel``/``sound`` unset.
PARAMS: tuple[Param, ...] = (
    GLOBAL_PARAMS
    + MIX_COMMON_PARAMS
    + MIX_CHANNEL_PARAMS
    + EFFECT_PARAMS
    + PROGRAM_COMMON_PARAMS
    + KEYBOARD_SOUND_PARAMS
)

_BY_MODE: Final[dict[str, tuple[Param, ...]]] = {
    "global": GLOBAL_PARAMS,
    "mix": MIX_COMMON_PARAMS,
    "effects": EFFECT_PARAMS,
    "program": PROGRAM_COMMON_PARAMS,
}


def with_channel(param: Param, channel: int) -> Param:
    """One mix-channel parameter, moved to ``channel`` (0-15, channel 1-16).

    The spec prints channel 1's block and says the next fifteen repeat every
    eight bytes. Only the bit address and the channel index change; the
    template's "Channel 1" in the label is rewritten so a value read back is
    not attributed to the wrong channel.
    """
    if not 0 <= channel < records.MIX_CHANNELS:
        raise ValueError(f"channel {channel} is outside 0-15")
    return replace(
        param,
        channel=channel,
        bit_address=param.bit_address + channel * records.MIX_CHANNEL_BYTES * 8,
        label=param.label.replace("Channel 1", f"Channel {channel + 1}", 1),
    )


def with_sound(param: Param, sound: int) -> Param:
    """One keyboard-sound parameter, moved to ``sound`` (0-3, sound 1-4).

    The spec's sound table is addressed relative to the start of its own
    eighty-five-byte block; sound 1 begins at byte 10 of the program, sound
    2 at 95, sound 3 at 180 and sound 4 at 265.
    """
    if not 0 <= sound < records.SOUNDS_PER_PROGRAM:
        raise ValueError(f"sound {sound} is outside 0-3")
    return replace(
        param,
        sound=sound,
        bit_address=param.bit_address
        + (records.PROGRAM_COMMON + sound * records.SOUND_BYTES) * 8,
    )


def _find(
    table: tuple[Param, ...],
    function: int,
    page: int,
    pot: int,
    sound: int | None,
) -> Param | None:
    for param in table:
        if (param.function, param.page, param.pot) != (function, page, pot):
            continue
        # ``sound`` disambiguates the four effect sends, which share an
        # address; a table row whose Send is "x" (None) is not tied to one.
        if sound is not None and param.sound is not None and param.sound != sound:
            continue
        return param
    return None


_EMPTY: Final[tuple[Param, ...]] = ()


def at(  # noqa: PLR0913 -- the address is four fields plus two selectors
    mode: str,
    function: int,
    page: int,
    pot: int,
    *,
    sound: int | None = None,
    channel: int | None = None,
) -> Param | None:
    """The parameter at a direct-edit address, or ``None``.

    This is the lookup the ``10`` message's four address fields perform.
    ``sound`` selects the effect bus in ``"effects"`` mode and the program
    sound in ``"program"`` mode; ``channel`` moves a ``"mix"`` channel
    parameter to the requested channel. With no ``sound``/``channel`` the
    template row is returned unchanged.
    """
    if mode == "mix":
        found = _find(MIX_CHANNEL_PARAMS, function, page, pot, sound)
        if found is not None:
            return found if channel is None else with_channel(found, channel)
        return _find(MIX_COMMON_PARAMS, function, page, pot, sound)

    if mode == "program":
        found = _find(PROGRAM_COMMON_PARAMS, function, page, pot, sound)
        if found is None:
            found = _find(KEYBOARD_SOUND_PARAMS, function, page, pot, sound)
            if found is not None and sound is not None:
                found = with_sound(found, sound)
        return found

    return _find(_BY_MODE.get(mode, _EMPTY), function, page, pot, sound)


def by_label(text: str) -> list[Param]:
    """Every parameter whose label contains ``text``, case-insensitively."""
    needle = text.casefold()
    return [param for param in PARAMS if needle in param.label.casefold()]


def verified_params(mode: str | None = None) -> tuple[Param, ...]:
    """The rows verified on this unit, optionally limited to one ``mode``.

    A row is here only when a controlled before/after probe on this unit
    confirmed its ``offset`` **and** its value law -- ``param.verified``
    being true, with ``param.value_law`` naming the law that probe showed.
    ``mode`` is one of ``"global"``, ``"mix"``, ``"program"`` or
    ``"effects"``; with ``None`` every verified row of every mode is
    returned.

    This is the editing set, not the display set: a row that is *not*
    verified is still shown in the editors, with its status, and is
    read-only there -- the transcription is a hypothesis until this
    function returns it.
    """
    if mode is None:
        return tuple(param for param in PARAMS if param.verified)
    return tuple(param for param in PARAMS if param.verified and param.mode == mode)


def law_of(param: Param) -> str:
    """The value law the parameter's stored field is written under.

    The probe's explicit ``param.value_law`` wins when it named one; until
    it did, the law is inferred from the parameter's own shape: a Global row
    stores two's complement, a packed row with a negative limit or a nonzero
    offset stores offset binary, and any other row stores its value raw.
    """
    if param.value_law and param.value_law in VALUE_LAWS:
        return param.value_law
    if param.mode == "global":
        return "twos"
    if param.offset != 0 or param.low < 0:
        return "offset"
    return "raw"


def stored_for(param: Param, value: int) -> int:
    """The stored field value for ``param``'s displayed ``value``.

    The value is first checked against the row's documented range, then
    moved into the field's own domain -- two's complement, offset binary or
    raw -- and the result is checked to fit the field's width. This is the
    arithmetic both the probe and the editors share: the ``10`` message takes
    the displayed value, the record stores the field.
    """
    if not param.low <= value <= param.high:
        raise ValueError(f"{param.label}: {value} is outside {param.low}..{param.high}")
    law = law_of(param)
    if law == "offset":
        stored = value - param.offset
    elif law == "twos":
        stored = value & ((1 << param.bits) - 1)
    else:
        stored = value
    if not 0 <= stored < (1 << param.bits):
        raise ValueError(f"{param.label}: {value} does not fit in {param.bits} bits")
    return stored


def value_from_stored(param: Param, stored: int) -> int:
    """The displayed value for ``param``'s stored field ``stored``.

    The exact inverse of :func:`stored_for`: the stored pattern is checked
    against the field's width, then read back under the row's value law.
    """
    if not 0 <= stored < (1 << param.bits):
        raise ValueError(f"{param.label}: {stored} does not fit in {param.bits} bits")
    law = law_of(param)
    if law == "offset":
        return stored + param.offset
    if law == "twos":
        # A two's-complement field stores its value biased into unsigned;
        # the rows whose low limit is negative are signed fields, the rest
        # keep their stored pattern as the value.
        if param.low < 0 and stored >= 1 << (param.bits - 1):
            return stored - (1 << param.bits)
        return stored
    return stored


def midi_edit_for(param: Param, value: int) -> bytes:
    """The ``10`` MIDI Edit message for ``param`` at ``value``.

    ``value`` is the parameter's two's-complement value, as the
    specification requires for the message; for a value read out of a
    packed record that means adding ``param.offset`` first. This does not
    store anything -- it is the ``10`` message, which only moves the
    parameter -- and the import is deferred so that importing the tables
    does not pull in the wire module.
    """
    from nano import messages as m

    if param.function < 0:
        raise ValueError(f"{param.label!r} has no direct-edit address")
    return m.midi_edit(
        MODE_NUMBERS[param.mode],
        param.function,
        param.page,
        param.pot,
        value,
        sound=param.sound if param.sound is not None else 0,
        channel=param.channel if param.channel is not None else 0,
    )
