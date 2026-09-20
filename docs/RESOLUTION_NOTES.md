<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Resolution notes

How each thing was established, and where every transcribed number came
from. `TODO.md` says *what* is open; this says *how* what is closed was
closed.

## 1. Sources, and what each one is worth

**The NanoSynth Reference Manual** (48 pages, 1998). Authoritative for the
banks, the panel, and the one thing it says about System Exclusive. Its
body text cannot be extracted: the fonts are subsetted with no ToUnicode
map, so `pdftotext` returns mojibake and the pages have to be read as
images. Only the headings and the implementation chart survive extraction.

**Alesis's QS6/7/8/R System Exclusive specification.** Authoritative for
the message set. The NanoSynth is not mentioned in it.

**The instrument.** Authoritative over both, and the reason anything here
is stated as fact.

## 2. The manual says nothing about System Exclusive, and its chart is
   printed backwards

The manual's only mention is one line of the MIDI Implementation Chart:

```
SYSTEM EXCLUSIVE               X          X
```

and at the foot of the chart:

```
X= YES
O= NO
```

which is inverted from the MMA convention every other such chart uses.
The inversion is not a typo: read the ordinary way the chart says this
sound module *transmits* notes, velocity, aftertouch and pitch bend and
*receives* none of them, which is backwards for a box with no keyboard.
Read its own way it is consistent throughout. So the line means the unit
both sends and receives System Exclusive — and the manual then says
nothing whatever about what.

## 3. It speaks the QS protocol, and calls itself member 7

The NanoSynth is a QS engine without a display, so the QS message set was
the obvious thing to try. It answers all of it.

Its Identity Reply, byte for byte:

```
F0 7E 7F 06 02 | 00 00 0E | 0E 00 | 07 00 | 30 31 30 30 | F7
                  Alesis     QS      ???     "0100"
```

Alesis's published family-member list is QS6 `03`, QS8 `04`, QS7 `05`,
QSR `06`. **`07` is this box.** It appears to be recorded nowhere else.

Note the manufacturer ID is the three-byte extended form, so family and
member sit three bytes further along than they would for a one-byte ID.
Reading them at the usual offsets gives a plausible wrong answer.

## 4. It will not answer an Identity Request

This cost an hour and is the most useful thing on this page.

Send an Identity Request and wait ten seconds: nothing. Send three and
wait: nothing. Then send a Global Dump Request, and **three Identity
Replies arrive ahead of the dump**, at 12, 17 and 23 ms.

Measured:

| Identity Requests sent | Replies flushed by the next Global Dump Request |
|---|---|
| 1 | 1 |
| 2 | 2 |
| 3 | 3 |

So it builds the reply when asked and holds it, transmitting only when it
next answers some other System Exclusive message. That is consistent with
its implementation chart, which says it transmits essentially nothing: the
output seems only to run when there is a dump to send.

Two consequences, both in the code:

* `identify()` sends the Identity Request **and then a Global Dump
  Request** to prompt the flush. There is no other way to get an answer.
* `autodetect()` probes with a **Global Dump Request**, not an Identity
  Request. That is a better probe anyway: it is Alesis-and-QS specific,
  so nothing else on the chain can answer it by accident — whereas an
  Identity Request is answered by everything, and on this bench the
  interface synth always answered first.

## 5. Everything that came back, and one thing that did not

Against the unit, each request sent and the reply measured:

| request | reply | size |
|---|---|---|
| User Program Dump Request `01` | `00` | 408 bytes |
| Edit Program Dump Request `03` | `02` | 408 bytes |
| User Effects Dump Request `07` | `06` | 83 bytes |
| Edit Effects Dump Request `09` | `08` | 83 bytes |
| Mix Dump Request `0F` | `0E` | 166 bytes |
| Global Dump Request `0B` | `0A` | 31 bytes |
| **Old Mix Dump Request `05`** | — | **silence** |

The old mix format is superseded and this unit does not serve it, which
is what the specification implies and what silence here confirms.

**The unit has 100 mixes and the manual never mentions mixes at all.**
Its front panel has no way to reach them.

## 6. Names: ten characters of seven bits, not on a byte boundary

Alesis's specification says a name is ten characters of seven bits with
values 0–95 and gives no character table or offset. Both were found by
brute force over a real dump: try every bit offset, score the result for
printability, and see which offset yields English.

* `value + 32` is the ASCII character, so 0 is a space.
* A **program** name starts at **bit 8** of the unpacked record.
* A **mix** name starts at **bit 5**.

The mix offset is different because a mix's common area opens with a
one-bit flag and a four-bit channel where a program's has two spare bits.
Reading a mix name at the program's offset does not fail — it returns ten
plausible characters of nonsense, and that is how the difference was
noticed:

```
a mix read at bit 8: 'uji:izIHj)'   <- punctuation soup, obviously wrong
a mix read at bit 5: 'Invented01'   <- English
```

The program offset was found the same way, by scoring every offset from 0
to 160 over 24 records for printability. Two offsets scored: 8, and 1 --
which is 8 shifted by one character and produces every name with a
leading space. Only one of them can be right and the names say which.

## 7. The packing is a bitstream, and the direction is not obvious

Seven 8-bit bytes travel as eight 7-bit ones. Alesis documents it as a bit
table:

```
0: 0 A6-A0        4: 0 E2-E0 D7-D4
1: 0 B5-B0 A7     5: 0 F1-F0 E7-E3
2: 0 C4-C0 B7-B6  6: 0 G0 F7-F2
3: 0 D3-D0 C7-C5  7: 0 G7-G1
```

which is a **low-bits-first** bitstream. Implemented the other way round
— concatenating each byte's seven bits most-significant-first, which is
the more natural reading of "eight 7-bit words beginning with the most
significant bit" — it still produces a record of exactly 350 bytes, and
that record is entirely wrong. The first attempt here did precisely that
and the names came out as `'\x01\x80Â´àg$\x06tH1\x1e'`. A shorter or
longer result would have been a better failure.

## 8. The edit-buffer dumps carry a number byte too

An edit buffer is a single thing, so its dump looks like one that would
carry no object number. It carries one, always zero.

Leaving it in the payload does not raise. Every field shifts by eight
bits and the record is still exactly the right length, so the name comes
out one character over:

```
number byte left in : ' Invented1'
number byte stripped: 'Invented12'
```

A person would accept the first at a glance. `messages.NUMBERED` is the
table that prevents it and `tests/test_messages.py` pins it, including a
test that the wrong reading is silent rather than fatal — which is the
property that makes it worth a test at all.

## 9. Everything this bridge sends comes back

The bench chain is the computer to a Roland XV-2020 over USB, and the
NanoSynth behind it on DIN. That chain has a soft thru in it: send a
Program Dump Request and the first thing that arrives is the Program Dump
Request, a perfectly well-formed Alesis message that cannot be rejected
as malformed.

So a reply is never identified by "an Alesis message arrived". It is
identified by opcode, and `Function.REPLY_TO` is the table that says which
opcode answers which. Replies also arrive late — a request that already
timed out can be answered during the next one — so every read checks the
object number as well. Both are the same lessons the sibling kwsed
learned the hard way, arriving here before they could cost anything.

## 10. What a `.syx` All Dump is made of

The owner's file, 79,479 bytes, split into 357 messages:

| opcode | what | count | bytes each |
|---|---|---|---|
| `00` | User Program Dump | 128 | 408 |
| `06` | User Effects Dump | 128 | 83 |
| `0E` | Mix Dump | 100 | 166 |
| `0A` | Global Dump | 1 | 31 |

Each is the specification's data size plus eight bytes of header and
footer, which is how the specification's figures were confirmed. An All
Dump is not one message and is not read by seeking to offsets.

## 11. Rules carried in from the sibling projects

Arrived with the code and did not have to be rediscovered:

* Moving the cursor sends nothing, enforced by a test.
* Workers do MIDI and nothing else; the favourites store is SQLite and
  refuses cross-thread use.
* `_busy` is set on the thread that checks it, not inside the worker.
* Favourites act on the row's own bank, never on the bank pane's.
* TOML values are escaped, so a port name with a quote cannot poison the
  config permanently.
* `config.toml` lives in the working directory, is disposable, and is
  gitignored; the favourites store is the user's own work and lives in
  the platform data directory.
* The manufacturer's names are not committed: the catalog is generated
  and gitignored, and every fixture is invented.
