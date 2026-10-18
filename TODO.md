<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# TODO

What is open. *How* anything was resolved goes in
`docs/RESOLUTION_NOTES.md`, not here.

## Status, 2026-09-20 (first session)

Built against the instrument in one sitting. The protocol is confirmed:
identity, all 128 user programs, the edit buffer, effects, mixes and
global all answer, and the names decode. 82 tests, all synthetic.

The `parity` branch has since landed the family shape on top of that:
vinsynlib 0.4.2, ratings, scan, live names, the write path and its fence,
the tooling tier and the hardware suite. What is left is the bench work
and the owner's transcription.

## 1. `SEND_GAP` and `SELECT_GAP` are guesses

**Status:** open, blocked on the bench run.

Neither has been measured. Alesis documents no inter-message timing for
this unit because Alesis documents no System Exclusive for it at all. The
values are the sibling projects' conservative defaults.

The tool now exists — `tools/measure_send_gap.py` reads the unit at a
conservative reference gap, then re-reads at candidate gaps and compares
the names, which is the only way to see a gap that is too short. What
remains is running it.

**Blocked on:** one bench session.

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

**Status:** closed by the `parity` branch — mixes are browsable and
editable now, behind the write fence.

The unit has 100 mixes and answers dump requests for all of them. Its
manual never mentions mixes; its front panel cannot reach them. `nanocli
mixes` lists their names, and `m` in the browser edits one — its sixteen
channels — reading it first and storing it behind the same gate, backup
and read-back as every other write.

A mix assigns a program to each of the 16 MIDI channels, which is
genuinely useful on a box that receives on all 16 at once. The question
this item was really asking — should the program grow a second pane — was
answered with a modal screen instead, which keeps the browser's one-pane
shape.

**Blocked on:** nothing.

## 5. The global record is not decoded

**Status:** closed by transcription, and the question behind it is closed
by the same rule.

The record is 20 bytes, and the QS specification publishes the table of
its rows. `nano/params.py` now carries that table, addresses included, and
`g` edits it row by row. Rows the spec documents for another model — the
`(QS6,7,8 only)` and `(QSR only)` rows, the deleted parameters — are
shown and are not editable: a store writes the whole record, and writing
a value the unit is documented to ignore while reporting success would be
a lie about what happened.

Which rows this firmware honours was never going to be settled by writing
to the unit to see what moves; that was this item's original objection and
it stands. What is transcribed is labelled as transcribed.

**Blocked on:** nothing.

## 6. Writing is implemented, behind the arm-then-fire fence

**Status:** closed by the `parity` branch.

nanosyned reads, selects, and now writes: a User program's name in the
browser (`e`), a mix's channels (`m`), the global record (`g`), whole
records through `nanocli send`, one parameter through `nanocli set`, and
a backup restore. The shape is the family's: the `w` gate checked before
a worker exists, an unconditional backup before a byte goes out, a
read-back verify that names what did not match, User 127 refused, and an
undo log that records only an agreed read-back.

**Blocked on:** nothing. *How* each part was established — the opcodes,
the store semantics, the parameter tables — is in
`docs/RESOLUTION_NOTES.md`.

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
