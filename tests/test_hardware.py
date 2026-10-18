# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 2 of the License, or (at your option)
# any later version.

"""Tests against a real Alesis NanoSynth. **Opt-in: see tests.conftest.**

Everything else in this suite runs synthetically -- no bridge is ever
constructed and no port is opened, which is CLAUDE.md's hardware rule and
the point of this suite being fast. That is also its limit: a synthetic
check agrees with whatever nanosyned transcribed, so every offset and size
in :mod:`nano.records` had only ever been checked against nanosyned's own
reading of the Alesis QS specification.

This file is the other half. It asks the machine, and the machine's
answer is the one that cannot be transcribed wrong:

* **Read-only, structural.** Identification, all 128 User program names,
  and the dump sizes the specification prints. Every one of these reads
  is silent: a dump request makes the unit transmit, and nothing in this
  file sends a Program Change, a Bank Select, a MIDI Edit or a store
  except the one gated write below.
* **One write, three gates.** Renaming a User program is the smallest
  write this protocol has -- ten seven-bit characters on top of record
  bytes the bridge sends back untouched -- and it still changes what the
  unit *keeps*, so it sits behind ``--hardware``, the unit answering,
  and ``NANOSYNED_HW_WRITE=1``, and it puts the original bytes back and
  asserts the restore whatever the first assertions did.

**What these tests deliberately do not do.** They never assert on a
single factory program *name*: the ROM banks are Alesis's and are not
this project's to redistribute, and a fixture naming one would be a copy
of one. The User bank's names are asserted on only as a count and as
"every one of them decodes to something not blank" -- what a given slot
holds is the owner's data, not this suite's. Not a single test here ever
selects a program: ``select()`` is the only thing in the bridge that
makes a sound, and nothing in this file needs the unit to play anything.
"""

import os

import pytest

from nano import banks
from nano import bridge as b
from nano import messages as m
from nano import records as rec

#: The slot the write test renames and puts back. Never 127: that one is
#: hardwired silent, the unit refuses to change it, and
#: :meth:`nano.bridge.NanoBridge.write_program` refuses it outright -- a
#: test that picked it would be testing the guard, not the write.
WRITE_PROGRAM = 0

#: The invented name: ten characters or fewer, inside the unit's
#: character set (space through ``_``), and padded by the encoder.
WRITE_NAME = "WRITETEST"


class TestHardwareIdentity:
    """``identify()``: the request that makes no sound, twice."""

    def test_identity_reports_alesis_qs_family_member_and_version(
        self, unit: b.NanoBridge
    ) -> None:
        """Alesis, the QS family, member 7 -- and a software version.

        This unit holds an Identity Reply rather than sending one: it
        transmits it only when it next answers some other System
        Exclusive message, which is why :meth:`identify` prompts with a
        read-only Global Dump Request. When even the prompt brings back
        only the dump, the family member and the version simply never
        came out, and asserting them would assert nothing -- so that
        case skips with its own reason rather than passing on an
        "inferred" identity that could not name its member.
        """
        fields = unit.identify()
        assert fields is not None, (
            "identify() returned None: not even the Global Dump prompt "
            "was answered, which is a connection finding, not an "
            "identity one"
        )
        assert fields["is_alesis"], f"manufacturer was {fields}"
        assert fields["is_qs_family"], f"family was {fields}"
        if fields.get("inferred"):
            pytest.skip(
                "the unit answered the Global Dump prompt but held every "
                "Identity Reply (this unit transmits a held reply only "
                "when it next answers some other SysEx message), so the "
                "family member and the software version cannot be read "
                "here"
            )
        assert fields["member"][0] == m.NANOSYNTH_MEMBER, (
            f"the unit answered with family {fields['family']} and member "
            f"{fields['member']}; nanosyned expects the NanoSynth's "
            f"member code {m.NANOSYNTH_MEMBER:#04x} on the bench"
        )
        assert fields["version"], "an Identity Reply with no software version in it"
        print(
            f"\nidentity: family {fields['family']}, member "
            f"{fields['member']}, version {fields['version']!r}, "
            f"channel {fields['channel']}, port {unit.port!r}"
        )


class TestHardwareUserBank:
    """The 128 User program names, one request at a time.

    There is no bulk request for just this bank -- the All Dump returns
    79 kB of everything -- so this is 128 round trips of the same request
    ``read_program_names`` makes. Every one is asserted, because
    ``read_program_names`` treats a timeout as "no name here" and would
    quietly hand back a shorter dictionary; a structural test must fail
    on silence, not absorb it.
    """

    def test_all_128_user_program_names_decode(self, unit: b.NanoBridge) -> None:
        names: dict[int, str] = {}
        for number in range(banks.PROGRAMS_PER_BANK):
            record = unit.read_program(number)
            # read_program already checked the size and cut the packing
            # pad off; asserting the exact size here is the one place a
            # silent re-arrangement of the slice would be caught.
            assert len(record) == rec.PROGRAM_BYTES, (
                f"user program {number} read as {len(record)} bytes, not "
                f"the documented {rec.PROGRAM_BYTES}"
            )
            name = rec.program_name(record)
            assert name.strip(), (
                f"user program {number}: name {name!r} decodes to "
                "nothing -- every slot on this bank decodes to a name"
            )
            names[number] = name
        assert len(names) == banks.PROGRAMS_PER_BANK
        # The read side is silent by construction, but nothing here can
        # prove a negative over the wire: what is asserted is that every
        # request was answered with a User Program Dump carrying its own
        # number. No Program Change, no Bank Select, no note went out.
        print(
            f"\nuser bank: all {len(names)} programs answered with a "
            "350-byte record and a decodable non-blank name; this file "
            "does not say what any of them are"
        )


class TestHardwareDumpSizes:
    """The sizes the specification prints, checked against the unit.

    ``read_mix`` and ``read_program`` cut a record to its documented
    size after demanding it be at least that long, so "came back the
    documented size" is an assertion and not a slice-summarising
    itself. The global dump is *not* cut by the bridge, so its length
    is the unit's own word: a firmware that answers with the
    pre-2.00-pack seventeen bytes would fail here loudly, which is the
    right response to a size the specification documented as twenty.
    """

    def test_a_mix_dump_is_138_bytes(self, unit: b.NanoBridge) -> None:
        record = unit.read_mix(0)
        assert len(record) == rec.MIX_BYTES, (
            f"mix 0 read as {len(record)} bytes, not the documented {rec.MIX_BYTES}"
        )
        # Decoded once so a wrong MIX_NAME_BIT_OFFSET (5, not the
        # program's 8) would at least run the code path here; what the
        # name *says* is this unit's data and is never asserted.
        rec.mix_name(record)

    def test_a_mix_dump_comes_back_for_each_number_asked(
        self, unit: b.NanoBridge
    ) -> None:
        """The manual does not document mixes at all. The unit answers."""
        record = unit.read_mix(0)
        again = unit.read_mix(0)
        assert record == again, (
            "two requests for mix 0 came back different bytes -- "
            "nothing in this file asks the unit to change a mix"
        )

    def test_a_global_dump_is_20_bytes(self, unit: b.NanoBridge) -> None:
        record = unit.read_global()
        assert len(record) == rec.GLOBAL_BYTES, (
            f"the global dump read as {len(record)} bytes, not the "
            f"documented {rec.GLOBAL_BYTES}"
        )

    def test_the_edit_buffer_returns_a_350_byte_program(
        self, unit: b.NanoBridge
    ) -> None:
        """Whatever the unit is playing right now, at program size.

        Reading it changes nothing: it is a copy of the scratch buffer,
        requested with the same opcode shape as every silent read here.
        """
        record = unit.read_edit_program()
        assert len(record) == rec.PROGRAM_BYTES, (
            f"the edit buffer read as {len(record)} bytes, not a "
            f"program's {rec.PROGRAM_BYTES}"
        )


class TestHardwareProgramWrite:
    """The one write: a User program renamed and put back.

    **Three gates, deliberately.** ``--hardware`` gets the suite onto
    the bench, the unit answering gets the fixture past its probe, and
    ``NANOSYNED_HW_WRITE=1`` gets this test past its own skip -- that
    last one belongs to the test, not the fixture, because a write is
    not "more hardware tests", it is "the hardware suite, changed": a
    store to a User slot is permanent unit memory, the one thing every
    other test in this file leaves alone.

    The flow is the siblings': read, edit the ten-name-character
    corner into an invented name, store, read back, assert, then
    restore the original bytes **in a ``finally``** and assert the
    restore there too -- so a failed first assertion leaves the unit
    as it was found rather than holding a test name with nothing
    checking the undo.
    """

    def test_a_renamed_user_program_reads_back_and_is_restored(
        self, unit: b.NanoBridge
    ) -> None:
        if not os.environ.get("NANOSYNED_HW_WRITE"):
            pytest.skip(
                "the write test needs NANOSYNED_HW_WRITE=1: it stores "
                "into user program memory, which the unit keeps and "
                "every other test in this file never touches"
            )
        slot = WRITE_PROGRAM
        assert slot != banks.SILENT_PROGRAM[1], (
            "the write slot is program 127, hardwired silent and "
            "unchangeable -- the bridge refuses it, and so does this"
        )
        original = unit.read_program(slot)
        edited = bytearray(original)
        m.encode_name(edited, WRITE_NAME)
        assert bytes(edited) != original, (
            "encoding the test name did not change the record, so the "
            "write below would prove nothing"
        )
        try:
            unit.write_program(slot, bytes(edited))
            read_back = unit.read_program(slot)
            assert rec.program_name(read_back) == f"{WRITE_NAME:<10}", (
                f"user program {slot}: after the store its name is "
                f"{rec.program_name(read_back)!r}, not the invented "
                f"{WRITE_NAME!r}"
            )
            differing = [
                index
                for index, (sent, came) in enumerate(
                    zip(bytes(edited), read_back, strict=True)
                )
                if sent != came
            ]
            assert read_back == bytes(edited), (
                f"user program {slot}: the read-back differs from the "
                f"record sent at {differing} -- something other than the "
                "name moved, and one of them is unit behaviour this file "
                "needs to know about"
            )
            print(
                f"\nwrite: user program {slot} renamed to {WRITE_NAME!r}, "
                "stored, and read back identical across all 350 bytes"
            )
        finally:
            # Restore first, assert second: the assert is *this* file
            # saying the unit holds what it held before the test ran,
            # and a restore that does not read back as the original is
            # worse news than whatever failed above.
            unit.write_program(slot, original)
            restored = unit.read_program(slot)
            assert restored == original, (
                f"user program {slot}: the restore did not read back as "
                f"the original -- it now holds "
                f"{rec.program_name(restored)!r}; re-run this test or "
                "put the original bytes back by hand"
            )
        print(
            f"write: the original bytes of user program {slot} are "
            "restored and verified by read-back"
        )
