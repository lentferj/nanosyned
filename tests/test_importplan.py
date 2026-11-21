# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.

"""Import planning: selection, refusal, and the order of the steps.

Every bank here is fabricated in memory. The planner is pure, so these tests
open no file, no port and no catalog.
"""

from __future__ import annotations

import pytest

from nano import importing, importplan
from nano import records as rec


def _program_record(fill: int, size: int = rec.PROGRAM_BYTES) -> bytes:
    return bytes([fill & 0x7F]) * size


def _program(
    index: int, slot: int, size: int = rec.PROGRAM_BYTES
) -> importing.SourceProgram:
    return importing.SourceProgram(
        index=index,
        slot=slot,
        name=f"Program{slot}",
        record=_program_record(slot, size),
    )


def _bank(*slots: int, label: str = "bank 0") -> importing.SourceBank:
    bank = importing.SourceBank(index=0, label=label)
    for index, slot in enumerate(slots):
        bank.programs[slot] = _program(index, slot)
    return bank


def _effects(*numbers: int, label: str = "bank 0") -> importing.SourceBank:
    bank = importing.SourceBank(index=0, label=label)
    for number in numbers:
        bank.effects[number] = bytes(rec.EFFECTS_BYTES)
    return bank


def _mixes(*numbers: int, label: str = "bank 0") -> importing.SourceBank:
    bank = importing.SourceBank(index=0, label=label)
    for number in numbers:
        bank.mixes[number] = bytes(rec.MIX_BYTES)
    return bank


class TestPlanRestore:
    def test_every_kind_goes_in_backup_order(self):
        bank = _bank(0, 126, 127)
        bank.effects[0] = bytes(rec.EFFECTS_BYTES)
        bank.effects[127] = bytes(rec.EFFECTS_BYTES)
        bank.mixes[0] = bytes(rec.MIX_BYTES)
        bank.mixes[99] = bytes(rec.MIX_BYTES)
        bank.mixes[100] = bytes(rec.MIX_BYTES)
        bank.globals_ = bytes(rec.GLOBAL_BYTES)

        plan = importplan.plan_restore(bank)

        assert [step.kind for step in plan.steps] == [
            "program",
            "program",
            "effects",
            "effects",
            "mix",
            "mix",
            "global",
        ]
        assert [step.target for step in plan.steps] == [
            0,
            126,
            0,
            127,
            0,
            99,
            None,
        ]
        assert plan.skipped == (
            "source 127 is hardwired silent",
            "source mix 100 is the edit buffer; skipped",
        )
        assert len(plan.overwrites) == len(plan.steps)

    def test_a_program_only_bank_still_plans(self):
        plan = importplan.plan_restore(_bank(0))

        assert [step.kind for step in plan.steps] == ["program"]
        assert plan.skipped == ()


class TestPlanBank:
    def test_every_program_goes_to_its_own_slot(self):
        plan = importplan.plan_bank(_bank(0, 5, 126))
        assert [step.kind for step in plan.steps] == ["program"] * 3
        assert [step.target for step in plan.steps] == [0, 5, 126]
        assert all(step.old_name is None for step in plan.steps)
        assert plan.skipped == ()
        assert plan.overwrites == (
            "user program 000 will be overwritten",
            "user program 005 will be overwritten",
            "user program 126 will be overwritten",
        )

    def test_steps_follow_source_order_not_slot_or_dict_order(self):
        bank = importing.SourceBank(index=0, label="bank 0")
        # The reader saw 2 first, then 9, then 7; the plan follows index.
        bank.programs[2] = _program(1, 2)
        bank.programs[9] = _program(0, 9)
        bank.programs[7] = _program(2, 7)
        plan = importplan.plan_bank(bank)
        assert [step.target for step in plan.steps] == [9, 2, 7]

    def test_hardwired_source_is_skipped_with_a_sentence(self):
        plan = importplan.plan_bank(_bank(3, 127, 4))
        assert [step.target for step in plan.steps] == [3, 4]
        assert plan.skipped == ("source 127 is hardwired silent",)

    def test_bank_with_only_127_yields_no_steps(self):
        plan = importplan.plan_bank(_bank(127))
        assert plan.steps == ()
        assert plan.skipped == ("source 127 is hardwired silent",)
        assert plan.overwrites == ()

    def test_padded_record_is_cut_to_the_documented_size(self):
        bank = importing.SourceBank(index=0, label="bank 0")
        bank.programs[1] = _program(0, 1, rec.PROGRAM_BYTES + 9)
        plan = importplan.plan_bank(bank)
        assert len(plan.steps[0].record) == rec.PROGRAM_BYTES
        assert plan.steps[0].record == _program_record(1)

    def test_label_names_the_bank_and_the_source_slot(self):
        plan = importplan.plan_bank(_bank(12, label="bank 2"))
        assert plan.steps[0].source_label == "bank 2 program 012"


class TestPlanSingle:
    def test_pairs_map_sources_to_chosen_targets(self):
        bank = _bank(0, 1, 2)
        plan = importplan.plan_single(bank, [(2, 10), (0, 11)])
        assert [step.target for step in plan.steps] == [11, 10]
        assert [step.source_label for step in plan.steps] == [
            "bank 0 program 000",
            "bank 0 program 002",
        ]
        assert plan.skipped == ()

    def test_steps_follow_source_order_when_pairs_do_not(self):
        bank = _bank(0, 1, 2)
        plan = importplan.plan_single(bank, [(2, 20), (0, 21), (1, 22)])
        assert [step.target for step in plan.steps] == [21, 22, 20]

    def test_duplicate_target_is_refused(self):
        bank = _bank(0, 1)
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(bank, [(0, 10), (1, 10)])
        assert str(caught.value) == "user program 010 is assigned twice; nothing sent"

    def test_target_127_is_refused(self):
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(_bank(0), [(0, 127)])
        assert str(caught.value) == (
            "user program 127 is hardwired silent and cannot be changed; nothing sent"
        )

    @pytest.mark.parametrize("target", [128, -1, 999])
    def test_target_outside_the_user_bank_is_refused(self, target):
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(_bank(0), [(0, target)])
        assert str(caught.value) == (
            f"user program {target} is outside 0-126; nothing sent"
        )

    def test_missing_source_is_refused(self):
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(_bank(0), [(9, 10)])
        assert str(caught.value) == "source slot 9 is not in bank 0; nothing sent"

    def test_empty_selection_is_refused(self):
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(_bank(0), [])
        assert str(caught.value) == "nothing selected; nothing sent"

    def test_short_record_is_refused(self):
        bank = importing.SourceBank(index=0, label="bank 0")
        bank.programs[3] = _program(0, 3, 4)
        with pytest.raises(ValueError) as caught:
            importplan.plan_single(bank, [(3, 5)])
        assert str(caught.value) == (
            "source program 3 unpacked to 4 bytes, fewer than the 350 one "
            "occupies; nothing sent"
        )

    def test_padded_record_is_cut_to_the_documented_size(self):
        bank = importing.SourceBank(index=0, label="bank 0")
        bank.programs[3] = _program(0, 3, rec.PROGRAM_BYTES + 4)
        plan = importplan.plan_single(bank, [(3, 5)])
        assert len(plan.steps[0].record) == rec.PROGRAM_BYTES


class TestPlanEffects:
    def test_every_effects_patch_keeps_its_number(self):
        plan = importplan.plan_all_effects(_effects(0, 7, 127))
        assert [step.kind for step in plan.steps] == ["effects"] * 3
        assert [step.target for step in plan.steps] == [0, 7, 127]
        assert plan.steps[1].source_label == "bank 0 effects 007"
        assert plan.overwrites[0] == "effects patch 000 will be overwritten"
        assert plan.skipped == ()

    def test_effects_record_size_is_checked(self):
        bank = importing.SourceBank(index=0, label="bank 0")
        bank.effects[2] = bytes(1)
        with pytest.raises(ValueError, match="fewer than the 65"):
            importplan.plan_all_effects(bank)


class TestPlanMixes:
    def test_mix_100_is_skipped_with_a_sentence(self):
        plan = importplan.plan_all_mixes(_mixes(0, 100, 99))
        assert [step.target for step in plan.steps] == [0, 99]
        assert plan.skipped == ("source mix 100 is the edit buffer; skipped",)
        assert plan.overwrites == (
            "mix 000 will be overwritten",
            "mix 099 will be overwritten",
        )

    def test_mix_outside_the_stored_range_is_refused(self):
        with pytest.raises(ValueError) as caught:
            importplan.plan_all_mixes(_mixes(101))
        assert str(caught.value) == "mix 101 is outside 0-99; nothing sent"


class TestPlanGlobal:
    def test_global_is_one_step_with_no_number(self):
        bank = _bank(0)
        bank.globals_ = bytes(rec.GLOBAL_BYTES)
        plan = importplan.plan_all_global(bank)
        assert len(plan.steps) == 1
        assert plan.steps[0].kind == "global"
        assert plan.steps[0].target is None
        assert plan.steps[0].source_label == "bank 0 global"
        assert plan.overwrites == ("the global settings will be overwritten",)

    def test_a_bank_without_global_yields_no_steps(self):
        plan = importplan.plan_all_global(_bank(0))
        assert plan.steps == ()
        assert plan.skipped == ()
        assert plan.overwrites == ()

    def test_short_global_record_is_refused(self):
        bank = _bank(0)
        bank.globals_ = bytes(2)
        with pytest.raises(ValueError, match="fewer than the 20"):
            importplan.plan_all_global(bank)


class TestPlanInit:
    def test_plans_one_step_for_every_writable_slot(self):
        plan = importplan.plan_init(_program_record(0))
        assert len(plan.steps) == 127
        assert [step.target for step in plan.steps] == list(range(127))
        assert all(step.kind == "program" for step in plan.steps)
        assert all(step.source_label == "Init program" for step in plan.steps)
        assert all(step.old_name is None for step in plan.steps)
        assert all(len(step.record) == rec.PROGRAM_BYTES for step in plan.steps)
        assert all(step.record == _program_record(0) for step in plan.steps)
        assert plan.skipped == ()

    def test_no_step_targets_the_hardwired_slot(self):
        plan = importplan.plan_init(_program_record(0))
        assert all(step.target != 127 for step in plan.steps)
        assert plan.steps[-1].target == 126

    def test_every_writable_slot_is_planned_for_replacement(self):
        plan = importplan.plan_init(_program_record(0))
        assert plan.overwrites == tuple(
            f"user program {slot:03d} will be overwritten" for slot in range(127)
        )

    def test_short_template_is_refused_before_a_port_opens(self):
        with pytest.raises(ValueError) as caught:
            importplan.plan_init(b"\x00" * 4)
        assert "fewer than the 350 one" in str(caught.value)


class TestPlanAppend:
    def test_fits_sources_into_the_next_free_targets(self):
        bank = _bank(0, 1)
        plan = importplan.plan_append(bank, [7, 8])
        assert [step.target for step in plan.steps] == [7, 8]
        assert [step.source_label for step in plan.steps] == [
            "bank 0 program 000",
            "bank 0 program 001",
        ]

    def test_steps_follow_source_file_order_and_ascending_targets(self):
        bank = _bank(3, 127, 5, 1)
        plan = importplan.plan_append(bank, [0, 4, 126])
        assert [(step.target, step.source_label) for step in plan.steps] == [
            (0, "bank 0 program 003"),
            (4, "bank 0 program 005"),
            (126, "bank 0 program 001"),
        ]

    def test_overflow_cuts_the_excess_sources(self):
        bank = _bank(0, 1, 2)
        plan = importplan.plan_append(bank, [10])
        assert [(step.target, step.source_label) for step in plan.steps] == [
            (10, "bank 0 program 000")
        ]
        assert plan.skipped == (
            'source 001 "Program1" is cut; no free slot',
            'source 002 "Program2" is cut; no free slot',
        )

    def test_source_127_is_skipped_with_the_bank_sentence(self):
        bank = _bank(3, 127, 4)
        plan = importplan.plan_append(bank, [0, 1])
        assert [step.target for step in plan.steps] == [0, 1]
        assert plan.skipped == ("source 127 is hardwired silent",)

    def test_empty_targets_cut_every_source(self):
        plan = importplan.plan_append(_bank(0, 1), [])
        assert plan.steps == ()
        assert plan.skipped == (
            'source 000 "Program0" is cut; no free slot',
            'source 001 "Program1" is cut; no free slot',
        )

    @pytest.mark.parametrize(
        "targets",
        [
            [1, 1],  # duplicate
            [5, 3],  # not ascending
            [127],  # hardwired silent
            [128],  # outside the user bank
        ],
    )
    def test_invalid_targets_are_refused(self, targets):
        with pytest.raises(ValueError):
            importplan.plan_append(_bank(0), targets)
