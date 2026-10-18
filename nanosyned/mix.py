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
needs :attr:`nano.params.Param.offset` added to become the value the
instrument displays, and a value being written needs it subtracted again.
The eight fields this module names all have ``offset == 0``; the arithmetic
is done anyway because the table is the authority, not this file's memory
of it.

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

from nano import params
from nano import records as rec
from nano.params import Param

__all__ = [
    "FIELDS",
    "FIELD_ADDRESSES",
    "MixChannel",
    "channels",
    "get_channel_field",
    "mix_name",
    "param_for",
    "set_channel_field",
]

#: Which direct-edit address each field this module names lives at, as the
#: spec's ``(function, page, pot)``. The label is this module's short name;
#: the table's own label ("Channel 1 program number") is rewritten per
#: channel by :func:`nano.params.with_channel`.
FIELD_ADDRESSES: dict[str, tuple[int, int, int]] = {
    "program": (0, 0, 0),
    "program_type": (0, 0, 2),
    "enable": (0, 0, 3),
    "volume": (1, 0, 0),
    "pan": (1, 0, 1),
    "output": (1, 0, 2),
    "effect_level": (2, 0, 0),
    "effect_bus": (2, 0, 1),
}

#: The three fields the browser's mix pane offers to edit, in the order the
#: choice dialog lists them. The other five are decoded and shown; editing
#: them is not offered yet, which is a smaller promise than a screen that
#: writes a field nobody has tested.
FIELDS: tuple[str, ...] = ("program", "volume", "pan")


@dataclass(frozen=True, slots=True)
class MixChannel:
    """One of a mix's sixteen channels, in the values the unit displays.

    ``program`` is 0-127 and is the **program change** the channel plays;
    the four banks are chosen elsewhere, and a mix does not carry a bank
    select. ``enable`` is a switch and is a ``bool`` here, not a 0/1 the
    reader has to interpret; every other field is the number the panel
    would show. A field the parameter table has no row for is ``None``.
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
    """``param``'s value out of ``record``, offset included, or ``None``."""
    if param is None:
        return None
    return rec.decode_bit_field(record, param) + param.offset


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
        enable = _field(record, channel, "enable")
        out.append(
            MixChannel(
                channel=channel,
                program=_field(record, channel, "program"),
                program_type=_field(record, channel, "program_type"),
                enable=None if enable is None else bool(enable),
                volume=_field(record, channel, "volume"),
                pan=_field(record, channel, "pan"),
                output=_field(record, channel, "output"),
                effect_level=_field(record, channel, "effect_level"),
                effect_bus=_field(record, channel, "effect_bus"),
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
    number.

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
    stored = param.clamp(value) - param.offset
    changed = bytearray(record)
    rec.encode_bit_field(changed, param, stored)
    return bytes(changed)
