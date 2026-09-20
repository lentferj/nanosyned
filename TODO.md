<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# TODO

What is open. *How* anything was resolved goes in
`docs/RESOLUTION_NOTES.md`, not here.

## Status, 2026-09-20 (first session)

Built against the instrument in one sitting. The protocol is confirmed:
identity, all 128 user programs, the edit buffer, effects, mixes and
global all answer, and the names decode. 82 tests, all synthetic.

## 1. `SEND_GAP` and `SELECT_GAP` are guesses

**Status:** open, blocked on wanting to measure them.

Neither has been measured. Alesis documents no inter-message timing for
this unit because Alesis documents no System Exclusive for it at all. The
values are the sibling projects' conservative defaults.

Worth measuring together with the question below, in one bench session.

**Blocked on:** a measurement.

## 2. Reading the User bank is 128 round trips

**Status:** open, works, slow.

There is no bulk request that returns only the user bank. The All Dump
(`0C`) returns everything the instrument holds — 79 kB in 357 messages,
nearly all of it data this program does not use — so `read_program_names`
asks 128 times instead.

Whether the All Dump is in fact faster has not been timed. If it is, it
would be worth taking the whole thing and discarding the parts not
needed; if it is not, this note should say so and stop inviting the
question.

**Blocked on:** timing both against the unit.

## 3. The ROM banks have no names until somebody types them

**Status:** open by design, and the main thing a user has to do.

Only the User bank can be read back. General MIDI and the three preset
banks are ROM and the protocol has no request for them, so their names
can only come from a transcription of the manual's program list, made by
the owner, with `tools/extract_catalog.py --manual`.

General MIDI is the easy half: the bank is in GM order, so a standard GM
name list fits it exactly. The three preset banks are not.

**Blocked on:** nothing but the typing, and it is the owner's to do --
those names are Alesis's and are not committed here.

## 4. Mix mode is read-only here, and unmentioned by the manual

**Status:** open, deliberate for now.

The unit has 100 mixes and answers dump requests for all of them. Its
manual never mentions mixes; its front panel cannot reach them. `nanocli
mixes` lists their names and nothing else uses them.

A mix assigns a program to each of the 16 MIDI channels, which is
genuinely useful on a box that receives on all 16 at once. Browsing them
properly means decoding the 8-byte channel blocks, and *selecting* one
means `Mode Select` (`0D`) — which changes what the instrument plays, so
it belongs behind the same care as any other sounding action.

**Blocked on:** deciding whether this program should grow a second pane.

## 5. The global record is not decoded

**Status:** open, low value.

20 bytes whose contents Alesis lists but whose offsets were not pinned
down. Pinning them means writing to the instrument to see what moves,
which is not a thing to do to find out what a byte means.

`nanocli status` reports the identity instead, which answers the question
people actually ask.

## 6. Writing is not implemented, and should not be added casually

**Status:** open, and the fence is the point.

nanosyned reads and selects. The protocol can write: a User Program Dump
sent *to* the unit stores it, and there are FLASH sector commands as
well.

If that is ever added it takes the siblings' shape, which is not a
suggestion:

1. A modal arm-then-fire screen. Opening it sends nothing; arming sends
   nothing; firing is a different key and works only while armed, and
   moving the cursor disarms.
2. Never one keystroke from the browser.
3. Back up first, unconditionally: read the destination in full and write
   it to a file before a byte goes out. If that read fails, nothing is
   written.
4. Say what is about to be destroyed, **by name**. "Program 12" means
   nothing; the name it is about to replace means everything.
5. Verify by reading back and comparing, and report what did not match
   rather than claiming success.

Note that User program 127 is hardwired silent and cannot be changed, so
it is the one slot where a write must be refused outright.

## 7. The MidiQuest `.sqs` format is unread — across all the projects

**Status:** open, and not specific to this instrument.

`~/Dokumente/SYNTHS/Nanosynth` holds two `.sqs` files alongside the
`.syx` dumps. They are MidiQuest's own bank format: an IFF-style chunked
file with `LIST`, `FORM`, `BANK`, `CHNL`, `SHDR`, `FILE`, `TRAN`, `RECV`,
`XTRA`, `MPIN`, `MPOT`, `BODY`, `AUDI`, `BDEF` and `TDEF` chunks, sizes
big-endian, contents not obviously the raw SysEx.

The same format turns up in the other instruments' folders, so decoding
it once would serve **all** the sibling projects — rxved, kwsed, p2ked,
x5ded and this one. Worth doing as shared work rather than five times.

**Blocked on:** nothing but the decoding. Nothing here depends on it.

## 8. Measure whether the browser can sit open beside a sequencer

**Status:** open.

The design says it can: the cursor sends nothing and every read is
silent. That is enforced by tests against a fake. It has not been checked
against the real unit with a sequencer running into it at the same time,
which is the claim that actually matters.

**Blocked on:** a bench session.
