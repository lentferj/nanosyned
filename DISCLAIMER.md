<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# What this project knows, and how well

nanosyned is not affiliated with Alesis. "Alesis", "NanoSynth" and
"QuadraSynth" are their names, used here to say which instrument this
talks to.

## Verified against the instrument

Confirmed by sending the message and reading what came back, on an
Alesis NanoSynth reporting software version 1.00:

- The Alesis manufacturer ID `00 00 0E` and QS family `0E`.
- **Family member `07`.** Alesis's published list gives QS6 `03`,
  QS8 `04`, QS7 `05`, QSR `06` and stops. This unit answers `07`.
- User Program Dump Request → a 408-byte dump, 400 packed bytes, 350
  unpacked. All 128 programs answer.
- Edit Program Dump, User Effects, Edit Effects, Global Dump and **Mix
  Dump** all answer. Old Mix Dump Request is met with silence.
- **100 mixes**, which the Reference Manual never mentions.
- Program and mix names: ten characters, seven bits each, `value + 32`
  is the ASCII character. A program's name starts at bit 8 of the
  record; a mix's at bit 5.
- Program 127 of the User bank is named `Off`. The manual describes a
  hardwired silent program at that number without giving its name.
- **This unit never answers an Identity Request when it receives one.**
  It holds the reply and transmits it the next time it answers some other
  System Exclusive message; send three and all three arrive at once
  behind the next dump.

## Transcribed from documents

- The five banks, their Bank Select values, and that Controller 32 is
  ignored: NanoSynth Reference Manual, pages 22–23 and 43–45.
- The sixteen front-panel categories: page 43.
- The silent program at User 127: page 45.
- Opcodes, record sizes and the 8-into-7 packing: Alesis's published
  QS6/7/8/R System Exclusive specification.

**The manual contradicts itself once.** Page 22's heading says the
MIDI-only banks are "1, 2, AND 3"; page 23's body and page 43 both say
2, 3 and 4. Two against one, and the arithmetic agrees with the two —
640 programs less the 256 on the panel is 384, which is three banks. The
heading is treated as the error, and `nano/banks.py` says so.

**The implementation chart's legend is inverted** from the usual
convention: it reads `X = YES, O = NO`. Read the ordinary way, the chart
says this sound module transmits notes and receives none, which is
backwards. Read its own way it is consistent — including the line that
says it both sends and receives System Exclusive.

## Inferred, and labelled as such

- That the unit's MIDI output only runs when it has a dump to send is the
  most economical explanation of the held Identity Replies. It matches
  the implementation chart, which says the unit transmits essentially
  nothing. It has not been confirmed any other way.

## Guesses

- `SEND_GAP` and `SELECT_GAP` in `nano/bridge.py`. Neither has been
  measured. They are labelled at the point of use and measuring them is a
  TODO item. Do not quote them as measurements.

## Not decoded

The interior of a program's four 85-byte sound blocks, and most of the
20-byte global record. nanosyned browses and selects; it does not edit,
and a half-decoded parameter map invites writing to it.

## Alesis's content is not redistributed here

No program, mix or preset name from the instrument appears in this
repository. The generated catalog is gitignored, fixtures are invented,
and the demo device's names come from a word pool chosen to be obviously
not Alesis's.

## AI assistance

This project was written with AI assistance (Claude). The protocol work
was done against the published specification and a real instrument, and
every claim above is marked with which of those it rests on. Findings
that came from the instrument are recorded in `docs/RESOLUTION_NOTES.md`
with what was sent and what came back.
