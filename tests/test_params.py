# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
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

"""The parameter tables' verification status, with no unit and no MIDI.

The tables in :mod:`nano.params` are a transcription of a published
specification, and a transcription is a hypothesis about this firmware.
What the rows gain here is the *slot* for the answer -- ``verified`` and
``value_law`` -- and nothing else: this file pins that every row starts
unverified, that the promotion helper says so honestly, and that adding
the fields changed neither the addresses the readers look up nor the
shape every existing construction depends on.

No row is verified here, and none may be: the flag is set by
``docs/PARAMETER_VERIFICATION_PLAN.md``'s probe on the unit, never by a
test. A test that marked a row verified would be exactly the "a second
truth drifts" failure the module docstring warns about, wearing the
authority of a green suite.
"""

import dataclasses

import pytest

from nano import params
from nano import records as rec

#: Every transcribed table and the row count the specification prints for
#: it. The eight sizes sum to the 178 rows ``PARAMS`` carries.
_TABLE_SIZES = {
    "GLOBAL_PARAMS": 20,
    "MIX_COMMON_PARAMS": 13,
    "MIX_CHANNEL_PARAMS": 20,
    "EFFECT_COMMON_PARAMS": 11,
    "EFFECT_CONFIG_0_PARAMS": 64,
    "EFFECT_MOD_PARAMS": 6,
    "PROGRAM_COMMON_PARAMS": 13,
    "KEYBOARD_SOUND_PARAMS": 31,
}


class TestTheVerifiedSet:
    """What the bench confirmed, and what it did not.

    The 2026-11-01 run promoted the confirmed rows only; the mismatches,
    partials and no-change rows stay unverified. A row with no law is a
    transcription, and the editors must treat it as read-only.
    """

    def test_a_verified_row_names_a_law_and_the_rest_name_none(self):
        for row in params.PARAMS:
            if row.verified:
                assert row.value_law in params.VALUE_LAWS[1:], row.label
            else:
                assert row.value_law == "", row.label

    def test_the_helper_returns_exactly_the_verified_rows(self):
        promoted = params.verified_params()
        assert promoted, "the bench confirmed rows; none are marked"
        assert all(row.verified for row in promoted)
        for mode in ("global", "mix", "program", "effects"):
            expected = tuple(
                row for row in params.PARAMS if row.verified and row.mode == mode
            )
            assert params.verified_params(mode) == expected, mode
        # The unit ignored every effects 10, so no effects row may be here.
        assert params.verified_params("effects") == ()

    def test_every_verified_row_has_an_address_and_a_law(self):
        """Completeness: a promoted row is editable, so it needs both."""
        for row in params.verified_params():
            assert row.function >= 0 and row.page >= 0 and row.pot >= 0, row.label
            assert params.law_of(row) == row.value_law, row.label

    def test_the_helper_is_exported(self):
        """A reader outside the module must find it where ``__all__`` says."""
        assert "verified_params" in params.__all__
        assert params.__all__ == sorted(params.__all__)

    def test_the_helper_reads_the_table_at_call_time(self, monkeypatch):
        """A promoted row shows up, and only in its own mode.

        The row is patched into a local copy of ``PARAMS`` rather than
        edited into the real one: no test may leave a verification
        behind, and this proves the filter both ways -- everything
        verified is returned, everything else is not.
        """
        row = dataclasses.replace(
            params.GLOBAL_PARAMS[1], verified=True, value_law="twos"
        )
        monkeypatch.setattr(params, "PARAMS", (row,))

        assert params.verified_params() == (row,)
        assert params.verified_params("global") == (row,)
        assert params.verified_params("mix") == ()


class TestTheStatusIsACopyNotAMutation:
    def test_replace_produces_a_verified_row_and_leaves_the_original(self):
        original = params.EFFECT_COMMON_PARAMS[0]
        assert original.verified is False
        promoted = dataclasses.replace(original, verified=True, value_law="twos")

        assert promoted.verified is True
        assert promoted.value_law == "twos"
        # Nothing but the two new fields moved.
        assert (
            promoted.mode,
            promoted.function,
            promoted.page,
            promoted.pot,
            promoted.label,
            promoted.low,
            promoted.high,
            promoted.bits,
            promoted.bit_address,
            promoted.offset,
        ) == (
            original.mode,
            original.function,
            original.page,
            original.pot,
            original.label,
            original.low,
            original.high,
            original.bits,
            original.bit_address,
            original.offset,
        )

        assert original.verified is False
        assert original.value_law == ""
        # ``Param`` is frozen and the tables are tuples, so the table row
        # is the very object the promotion copied from.
        assert params.EFFECT_COMMON_PARAMS[0] is original
        assert params.EFFECT_COMMON_PARAMS[0].verified is False

    def test_the_copy_is_a_param_and_equal_where_it_was_not_asked_to_change(self):
        # A row the bench did not confirm (the program type did not
        # move), so the copy really changes.
        original = params.MIX_CHANNEL_PARAMS[1]
        assert original.verified is False
        promoted = dataclasses.replace(original, verified=True, value_law="offset")
        assert isinstance(promoted, params.Param)
        assert promoted != original  # the status is part of equality
        assert promoted.label == original.label
        assert promoted.bit_address == original.bit_address


class TestTheLookupsStillFindTheirRows:
    """``verified`` sits after every real column, so nothing moved."""

    def test_by_label_finds_a_global_row(self):
        rows = params.by_label("Pitch transpose")
        assert [row.label for row in rows] == ["Pitch transpose*"]
        assert (rows[0].mode, rows[0].low, rows[0].high) == ("global", -12, 12)
        assert rows[0].bit_address == 8
        assert rows[0].verified is True
        assert rows[0].value_law == "twos"

    def test_at_finds_a_mix_channel_row(self):
        row = params.at("mix", 1, 0, 0)
        assert row is not None
        assert row.label == "Channel 1 volume"
        assert (row.low, row.high, row.bits, row.bit_address) == (0, 99, 7, 92)

    def test_at_finds_a_program_sound_row(self):
        row = params.at("program", 3, 0, 0)
        assert row is not None
        assert row.label == "Sound pitch semitone"
        assert (row.low, row.high, row.offset) == (-24, 25, -24)

    def test_at_still_selects_an_effect_send_by_sound(self):
        row = params.at("effects", 0, 0, 0, sound=1)
        assert row is not None
        assert row.label == "Send 2 pitch type"
        assert (row.sound, row.bit_address) == (1, 246)

    def test_by_label_still_sees_every_mode(self):
        assert {row.mode for row in params.by_label("Spare")} == {
            "global",
            "mix",
            "program",
            "effects",
        }


class TestTheTablesAreTheOnesDocumented:
    def test_every_table_has_the_size_the_specification_prints(self):
        for name, size in _TABLE_SIZES.items():
            assert len(getattr(params, name)) == size, name
        assert sum(_TABLE_SIZES.values()) == len(params.PARAMS)

    def test_params_is_the_union_of_the_tables(self):
        """``PARAMS`` is the concatenation the module documents, once each."""
        assert params.EFFECT_PARAMS == (
            params.EFFECT_COMMON_PARAMS
            + params.EFFECT_CONFIG_0_PARAMS
            + params.EFFECT_MOD_PARAMS
        )
        assert params.PARAMS == (
            params.GLOBAL_PARAMS
            + params.MIX_COMMON_PARAMS
            + params.MIX_CHANNEL_PARAMS
            + params.EFFECT_PARAMS
            + params.PROGRAM_COMMON_PARAMS
            + params.KEYBOARD_SOUND_PARAMS
        )
        assert len(set(params.PARAMS)) == len(params.PARAMS), "a row is listed twice"

    def test_the_status_fields_default_in_a_positional_construction(self):
        """Every existing row is built from nine positionals plus keywords."""
        row = params.Param("global", 0, 0, 2, "Pitch transpose*", -12, 12, 8, 8)
        assert row.offset == 0
        assert row.choices == ()
        assert row.sound is None
        assert row.channel is None
        # A fresh row is unverified; the promoted table row is not.
        assert row.verified is False
        assert row.value_law == ""
        assert params.GLOBAL_PARAMS[1].verified is True
        assert params.GLOBAL_PARAMS[1].value_law == "twos"
        # ``span`` and ``clamp`` are the two accessors the editors use.
        assert row.span == 24
        assert row.clamp(99) == 12

    def test_moving_a_row_to_a_channel_or_sound_carries_its_status(self):
        """``with_channel``/``with_sound`` copy, so the status travels."""
        template = dataclasses.replace(
            params.MIX_CHANNEL_PARAMS[3], verified=True, value_law="offset"
        )
        channelled = params.with_channel(template, 7)
        assert (channelled.verified, channelled.value_law) == (True, "offset")
        assert channelled.channel == 7
        assert channelled.label == "Channel 8 volume"
        assert channelled.bit_address == template.bit_address + 7 * (
            rec.MIX_CHANNEL_BYTES * 8
        )
        assert template.channel is None

        sound_row = dataclasses.replace(
            params.KEYBOARD_SOUND_PARAMS[8], verified=True, value_law="offset"
        )
        sounded = params.with_sound(sound_row, 2)
        assert (sounded.verified, sounded.value_law) == (True, "offset")
        assert sounded.sound == 2
        assert (
            sounded.bit_address
            == sound_row.bit_address + (rec.PROGRAM_COMMON + 2 * rec.SOUND_BYTES) * 8
        )
        assert sound_row.sound is None


class TestTheValueLaws:
    """The displayed value and the stored bits are two ends of one law."""

    def test_the_law_is_inferred_then_overridden(self):
        transpose = params.GLOBAL_PARAMS[1]
        semitone = params.at("program", 3, 0, 0)
        assert semitone is not None
        octave = params.at("mix", 3, 0, 0)
        assert octave is not None

        assert params.law_of(transpose) == "twos"
        assert params.law_of(semitone) == "offset"
        assert params.law_of(params.at("mix", 1, 0, 0)) == "raw"
        # A law the probe confirmed overrides the inference.
        assert params.law_of(dataclasses.replace(transpose, value_law="raw")) == "raw"

    def test_the_stored_and_displayed_ends_agree(self):
        transpose = params.GLOBAL_PARAMS[1]
        semitone = params.at("program", 3, 0, 0)
        assert semitone is not None
        octave = params.at("mix", 3, 0, 0)
        assert octave is not None

        assert params.stored_for(transpose, -12) == 244
        assert params.stored_for(transpose, 12) == 12
        assert params.value_from_stored(transpose, 244) == -12
        assert params.value_from_stored(transpose, 12) == 12

        assert params.stored_for(semitone, -24) == 0
        assert params.stored_for(semitone, 25) == 49
        assert params.value_from_stored(semitone, 0) == -24
        assert params.value_from_stored(semitone, 49) == 25

        assert params.stored_for(octave, -2) == 0
        assert params.value_from_stored(octave, 0) == -2

    def test_every_row_round_trips_through_stored_and_displayed(self):
        for row in params.PARAMS:
            values = [row.low, row.high]
            if row.low <= 0 <= row.high:
                values.append(0)
            for value in values:
                stored = params.stored_for(row, value)
                assert params.value_from_stored(row, stored) == value

    def test_stored_for_refuses_out_of_range_and_overwide_results(self):
        transpose = params.GLOBAL_PARAMS[1]
        with pytest.raises(ValueError):
            params.stored_for(transpose, transpose.low - 1)
        with pytest.raises(ValueError):
            params.stored_for(transpose, transpose.high + 1)

        # A pathological width: 99 does not fit in six bits.
        narrow = dataclasses.replace(params.MIX_CHANNEL_PARAMS[3], bits=6)
        with pytest.raises(ValueError):
            params.stored_for(narrow, 99)

    def test_value_from_stored_refuses_an_overwide_stored_value(self):
        transpose = params.GLOBAL_PARAMS[1]
        with pytest.raises(ValueError):
            params.value_from_stored(dataclasses.replace(transpose, bits=4), 244)
