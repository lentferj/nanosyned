# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# The view-model split -- a record decoded into rows the screen draws, with
# the screen holding no byte offsets of its own -- is the shape of the
# sibling p2ked's multi screen and its ChannelField table:
#   Copyright (C) 2026  p2ked contributors            - GPL-2.0-or-later
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""One mix, decoded into sixteen channel rows -- **pure data, no UI**.

A mix is 138 bytes: ten common bytes (a one-bit flag, a four-bit effect
channel and the ten-character name, which starts five bits in -- see
:data:`nano.records.MIX_NAME_BIT_OFFSET`) and sixteen eight-byte channel
blocks. The bit addresses and the value ranges are not restated here: they
come from :data:`nano.params.MIX_CHANNEL_PARAMS` through
:func:`nano.params.at`, which is the one table both the direct-edit message
and this reader use. A second copy of those numbers would be a second truth.

**The two domains meet here, and the conversion is in one place.** A mix
stores bipolar values in offset binary, so a field read out of the record
is decoded with :func:`nano.params.value_from_stored` and a value being
written is encoded with :func:`nano.params.stored_for` -- never with
arithmetic of this file's own. The table is the authority on which law a
row follows, and a second copy of that rule would be a second truth.

**A field the table does not have is ``None``, never a guess.** The
specification's mix-channel table is the template for all sixteen blocks;
if a future table drops a row, the view model says so rather than reading
neighbouring bits and presenting a plausible wrong number.

This module imports nothing from :mod:`nanosyned.app` and nothing from
Textual, so it can be tested without a terminal -- the same rule
:mod:`nanosyned.editor` follows.
"""

from __future__ import annotations

from dataclasses import dataclass

from nano import banks, params
from nano import records as rec
from nano.params import Param

__all__ = [
    "BANK_NAMES",
    "FIELDS",
    "FIELD_ADDRESSES",
    "SWITCHES",
    "MixChannel",
    "bank_id",
    "bank_label",
    "channels",
    "get_channel_field",
    "mix_name",
    "param_for",
    "set_channel_field",
]

#: The QS program-bank codes carried by the mix channel's ``program type``
#: field, keyed by Bank Select value. Cards occupy 5-15.
BANK_NAMES: dict[int, str] = {bank.select: bank.label for bank in banks.BANKS}


def bank_label(code: int | None) -> str:
    """A mix channel bank code as a person reads it.

    Codes 0-4 are the five internal banks. Codes 5-15 are card banks on a
    full QS; this unit has no card slots and resolves them to General MIDI,
    so calling them "Card bank 8" would be a lie about what is playing.
    """
    if code is None:
        return "?"
    if code in BANK_NAMES:
        return BANK_NAMES[code]
    return "GM (fallback)"


def bank_id(code: int | None) -> str | None:
    """The catalog bank id for a mix bank code, or ``None`` without a catalog.

    A card-bank code falls back to General MIDI, which is what this unit
    actually plays when no card is fitted.
    """
    if code is None:
        return None
    for bank in banks.BANKS:
        if bank.select == code:
            return bank.id
    return "GM"


#: Every field of the mix-channel template this module names, with the
#: spec's ``(function, page, pot)``. The label is this module's short name;
#: the table's own label ("Channel 1 program number") is rewritten per
#: channel by :func:`nano.params.with_channel`. The table's spare and its
#: per-channel padding are deliberately absent: neither is a control.
FIELD_ADDRESSES: dict[str, tuple[int, int, int]] = {
    "program": (0, 0, 0),
    "program_type": (0, 0, 2),
    "enable": (0, 0, 3),
    "volume": (1, 0, 0),
    "pan": (1, 0, 1),
    "output": (1, 0, 2),
    "effect_level": (2, 0, 0),
    "effect_bus": (2, 0, 1),
    "pitch_octave": (3, 0, 0),
    "pitch_semitone": (3, 0, 2),
    "keyboard_low": (4, 0, 0),
    "keyboard_high": (4, 0, 1),
    "midi_in": (4, 1, 0),
    "midi_out": (4, 1, 2),
    "keyboard_on": (4, 1, 3),
    "wheels_on": (4, 2, 0),
    "aftertouch_on": (4, 2, 1),
    "sustain_on": (4, 2, 2),
    "pedals_on": (4, 2, 3),
}

#: Every channel field, in the spec's order (the old choice dialog's three
#: leading fields are still here, now among the rest).
FIELDS: tuple[str, ...] = (
    "program",
    "enable",
    "volume",
    "pan",
    "output",
    "effect_level",
    "effect_bus",
    "pitch_octave",
    "pitch_semitone",
    "keyboard_low",
    "keyboard_high",
    "midi_in",
    "midi_out",
    "keyboard_on",
    "wheels_on",
    "aftertouch_on",
    "sustain_on",
    "pedals_on",
)

#: The fields that are one-bit switches: they decode to ``bool`` in
#: :class:`MixChannel` rather than to a 0/1 the reader has to interpret.
SWITCHES: frozenset[str] = frozenset(
    {
        "enable",
        "midi_in",
        "midi_out",
        "keyboard_on",
        "wheels_on",
        "aftertouch_on",
        "sustain_on",
        "pedals_on",
    }
)


@dataclass(frozen=True, slots=True)
class MixChannel:
    """One of a mix's sixteen channels, in the values the unit displays.

    ``program`` is 0-127 and is the **program change** the channel plays;
    ``program_type`` is the QS **program bank** code (0=GM, 1=User,
    2-4=Preset 1-3, 5-15=cards). The eight one-bit switches -- ``enable``,
    the MIDI and keyboard
    gates, and the controllers -- are ``bool`` here, not a 0/1 the reader
    has to interpret; every other field is the number the panel would show,
    with the table's offset already applied for a bipolar row. A field the
    parameter table has no row for is ``None``.
    """

    channel: int
    program: int | None
    program_type: int | None
    enable: bool | None
    volume: int | None
    pan: int | None
    output: int | None
    effect_level: int | None
    effect_bus: int | None
    pitch_octave: int | None
    pitch_semitone: int | None
    keyboard_low: int | None
    keyboard_high: int | None
    midi_in: bool | None
    midi_out: bool | None
    keyboard_on: bool | None
    wheels_on: bool | None
    aftertouch_on: bool | None
    sustain_on: bool | None
    pedals_on: bool | None


def param_for(channel: int, label: str) -> Param | None:
    """The table row for one field of one channel, or ``None``.

    ``channel`` is zero-based (0-15); the returned row's label already says
    "Channel 3", so a value read back is never attributed to channel 1.
    A label this module does not name raises ``ValueError`` -- unlike an
    absent *row*, which is a fact about the table and returns ``None``.
    """
    if not 0 <= channel < rec.MIX_CHANNELS:
        raise ValueError(f"channel {channel} is outside 0-{rec.MIX_CHANNELS - 1}")
    try:
        function, page, pot = FIELD_ADDRESSES[label]
    except KeyError:
        known = ", ".join(sorted(FIELD_ADDRESSES))
        raise ValueError(
            f"{label!r} is not a mix channel field this module names ({known})"
        ) from None
    return params.at("mix", function, page, pot, channel=channel)


def mix_name(record: bytes) -> str:
    """The ten-character name of a mix, via :func:`nano.records.mix_name`.

    A one-line delegation rather than a second decoder: the name starts at
    bit 5 of the common area, not at bit 8 like a program's, and reading it
    at the program offset produces ten plausible characters of nonsense.
    """
    return rec.mix_name(record)


def _decoded(record: bytes, param: Param | None) -> int | None:
    """``param``'s displayed value out of ``record``, or ``None``.

    The stored field is decoded by :func:`nano.records.decode_bit_field` and
    then moved into the display domain by :func:`nano.params.value_from_stored`,
    which is the table's own law: offset binary for a bipolar row, raw for
    the rest. Doing the arithmetic here instead would guess at that law.
    """
    if param is None:
        return None
    stored = rec.decode_bit_field(record, param)
    return params.value_from_stored(param, stored)


def _field(record: bytes, channel: int, label: str) -> int | None:
    """One field's displayed value, or ``None`` when the table lacks it."""
    return _decoded(record, param_for(channel, label))


def get_channel_field(record: bytes, channel: int, label: str) -> int | None:
    """One field's displayed value, or ``None`` when the table lacks it."""
    rec.check_size(record, rec.MIX_BYTES, "a mix")
    return _field(record, channel, label)


def channels(record: bytes) -> list[MixChannel]:
    """All sixteen channels of ``record``, in channel order.

    The record may be longer than a mix -- a dump is padded to a whole
    packing group -- so only the first :data:`nano.records.MIX_BYTES` are
    read. A short one raises :class:`nano.messages.ProtocolError` rather
    than reading past its end.
    """
    rec.check_size(record, rec.MIX_BYTES, "a mix")
    out: list[MixChannel] = []
    for channel in range(rec.MIX_CHANNELS):
        values = {label: _field(record, channel, label) for label in FIELD_ADDRESSES}
        switches = {
            label: None if values[label] is None else bool(values[label])
            for label in SWITCHES
        }
        out.append(
            MixChannel(
                channel=channel,
                program=values["program"],
                program_type=values["program_type"],
                enable=switches["enable"],
                volume=values["volume"],
                pan=values["pan"],
                output=values["output"],
                effect_level=values["effect_level"],
                effect_bus=values["effect_bus"],
                pitch_octave=values["pitch_octave"],
                pitch_semitone=values["pitch_semitone"],
                keyboard_low=values["keyboard_low"],
                keyboard_high=values["keyboard_high"],
                midi_in=switches["midi_in"],
                midi_out=switches["midi_out"],
                keyboard_on=switches["keyboard_on"],
                wheels_on=switches["wheels_on"],
                aftertouch_on=switches["aftertouch_on"],
                sustain_on=switches["sustain_on"],
                pedals_on=switches["pedals_on"],
            )
        )
    return out


def set_channel_field(record: bytes, channel: int, label: str, value: int) -> bytes:
    """``record`` with one channel field set to ``value``, as a new record.

    **Pure**: the argument is not touched and the change is encoded into a
    copy. ``value`` is clamped with :meth:`nano.params.Param.clamp` first,
    which is the specification's own rule for a value out of range -- "the
    range will be limited to the nearest legal value" -- so a mistyped 500
    for a 0-99 volume becomes 99 rather than an exception or a wrapped
    number. The clamped display value is then encoded by
    :func:`nano.params.stored_for`, the table's own inverse law, so a
    bipolar field such as pitch semitone round-trips through the record.

    A label this module does not name raises ``ValueError``; a label it
    names but the table has no row for raises ``LookupError``. Both are
    caller errors and neither sends anything.
    """
    rec.check_size(record, rec.MIX_BYTES, "a mix")
    param = param_for(channel, label)
    if param is None:
        raise LookupError(
            f"the parameter table has no {label} row for mix channel "
            f"{channel + 1}; nothing was written"
        )
    stored = params.stored_for(param, param.clamp(value))
    changed = bytearray(record)
    rec.encode_bit_field(changed, param, stored)
    return bytes(changed)
