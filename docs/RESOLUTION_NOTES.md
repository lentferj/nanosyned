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

## 12. The write opcodes and what a store does

Transcribed from the QS specification, confirmed against the unit on the
read side:

| opcode | store | record size |
|---|---|---|
| `00` | User Program Dump | 350 bytes |
| `06` | User Effects Dump | 65 bytes |
| `0E` | Mix Dump | 138 bytes |
| `0A` | Global Dump | 20 bytes |
| `10` | MIDI Edit — one parameter, the working copy | not stored |
| `0D` | Mode Select — Program/Mix, one byte | changes what plays |

The store semantics are the specification's: a dump sent *to* the unit
stores it in the slot it names, and a store to a *user* slot is permanent.
The unit answers a store with **silence either way** — it took it or it
did not — which is why a store without a read-back verify is not
considered landed, and why the verify is byte-for-byte rather than
name-only.

What is bench-verified: one write, in `tests/test_hardware.py` — a User
program renamed, read back across all 350 bytes, and restored in a
`finally` with a second read-back assertion. What is spec-transcribed:
the opcode set above and every parameter table in `nano/params.py`. The
record *sizes* the hardware suite pins on the read side (program 350,
mix 138, global 20) are the one place transcription and bench agree
without either being quoted for the other.

## 13. The parameter tables

`nano/params.py` is transcribed from the QS specification's parameter
tables — program common and sound, mix common and channel, effects,
global — keyed by (mode, function, page, pot) with the spec's ranges,
named choices and bit addresses. The global table is the spec's twenty
rows verbatim, including the two deleted parameters and the rows the spec
marks `(QS6,7,8 only)` or `(QSR only)`; `records.GLOBAL_BYTES` is 20 to
match the spec's own figure, whose dump description says the data
"corresponds to 20 bytes" and that versions before 2.00 omit the last
three.

**Transcribed, not bench-verified.** Which rows this firmware honours is
not established, and the editors treat that honestly: the global editor
shows a row the spec documents for another model and will not write it,
because a store writes the whole record and reporting success over a
value the unit is documented to ignore would be a lie about what happened.

## 14. Why `v` is the favourites view and not `F`

The family's shift-pair is `f` set / `F` view. Here `f` writes the
favourites database and `F` does not, so the pair left a write one slip
away from a read — and in a tool whose whole discipline is "the cursor
sends nothing", a shift-pair that puts a write next to a read is the
wrong shape. `v` has no such twin. rxved and p2ked made the same swap,
and `tests/test_conformance.py` pins the whole divergence in two
sentences, as the family asks.

## 15. The catalog's key grammar: `offset=0`, and reading a legacy file

vinsynlib keys the catalog on the *display* number (`BANK:NNN`). On this
instrument the display number and the program change are the same number
— both 0-based, equal on every slot — so the offset is 0. Its own
`catalog.load` cannot be used for this file: it converts a `"pc"` row with
`wire_to_display(pc, offset=1)`, i.e. `+1`, which is right for a tool whose
first patch is number 1 and on this unit would shift every catalog written
before the grammar changed by one slot. `nano.catalog.load` therefore reads
the JSON itself and accepts **both** grammars at offset 0 — `"n"` (the
display number the extractor now writes) and the older `"pc"` (the wire
number) — taking each as the same integer. `tests/test_catalog.py` pins
that a `"pc": 0` row lands on slot 0, not slot 1, which is the whole trap.

The extractor writes only `"n"` rows now: `{"n": 0, "name": …}`, never
`"pc"`. `tests/test_extract.py` pins the grammar, the dump-beats-page
precedence in the User bank, and that a manual line whose name is only
whitespace is counted as malformed rather than stored as a name of one
space.

## 16. Where the live-names sidecar lives

`live-names.json`, beside the catalog file — `nano/data/live-names.json`
by default, and beside whatever `--catalog` points at, because the names
were read against that catalog's bank layout and the two travel together.
Loaded at startup, so the browser shows the right names *before* anything
has talked to the unit; re-saved after every read, so the next start is
right again without one. A missing file means nothing has been read yet;
a corrupt one earns a warning rather than a refusal to open.

It is deliberately not inside the catalog file. The catalog is a
transcription of the manual; the sidecar is one instrument's current
contents; the printed-versus-live disagreement is the whole point of
having two sources, and overwriting one with the other would destroy it.

## 17. `SEND_GAP`, measured on the bench

`tools/measure_send_gap.py` reads the first N User programs at a
conservative reference gap (100 ms, twice, and refuses to proceed unless
the two passes agree), then re-reads at a series of candidate gaps and
compares every name against the reference. A gap that is too short shows
up not as a timeout but as a reply belonging to the *previous* request,
filed late — the hazard `bridge.request(number=…)` exists to prevent.

The run, on 2026-10-18, against the unit behind the XV-2020 on the bench:

| gap | programs clean | timeouts | mis-filed | mean read |
|---|---|---|---|---|
| 0 ms | 32/32 | 0 | 0 | 5.22 s |
| 2 ms | 32/32 | 0 | 0 | 5.29 s |
| 5 ms | 32/32 | 0 | 0 | 5.37 s |
| 10 ms | 32/32 | 0 | 0 | 5.53 s |
| 20 ms | 32/32 | 0 | 0 | 5.84 s |
| 50 ms | 32/32 | 0 | 0 | 6.77 s |

Every candidate gap reproduced the reference exactly, including no delay
at all. The mean read of 32 programs rises only by the gap itself — about
5.2 s at 0 ms against 6.8 s at 50 ms, i.e. 32 × 50 ms of deliberate delay
— so the unit's own reply latency (roughly 160 ms a program on this chain)
dominates and the inter-message gap is not the limiting factor. `SEND_GAP`
is therefore `0.000`: the smallest candidate measured clean. The DIN hop
to the unit is included in what was measured, so the baud-limited leg is
covered.

`SELECT_GAP` (Bank Select, then Program Change) could not be measured this
way. The tool's method selects a General MIDI program as a reference, then
selects a User program and polls the edit buffer for the change; at every
candidate gap the edit buffer still reported the program it started on
(`WailinWall`, User 000), so the tool could not distinguish a short gap
from a working one. It stays `0.005`. Whether the edit buffer not updating
is a fact about the unit's Program Change handling, a fact about the edit
buffer until a note is played, or a flaw in the probe is not established
here — it is recorded as an open question rather than a finding.

## 18. The preset names come from the manual, read by OCR

The Reference Manual carries the whole program list — all 640 names for
all five banks — under "NanoSynth Program List", **pages 30-33**. Only the
User bank can be read from the unit; the General MIDI bank and the three
preset banks are ROM and the protocol has no request for them, so their
names exist nowhere but that table.

The table cannot be read as text. Its fonts are subsetted Type 1C with a
**Custom encoding and no ToUnicode map** (`pdffonts` shows `uni no` on
every embedded face), so `pdftotext` returns mojibake — the same property
that has always meant the manual's pages are read as images here. So
`tools/extract_catalog.py --pdf` renders pages 30-33 with `pdftoppm` at
300 dpi and reads them with `tesseract` in TSV mode, which gives each
word's bounding box.

The columns are then recovered by x: the five bank columns sit at fixed
x-windows, and the boundaries are placed in the **blank gaps between one
column's last name and the next column's index number** — not on the
header labels, which sit a pixel or two from the next column's index and
let it bleed into the previous cell (P1 004 read "Suitcase 4" until the
boundary moved). The table lists the banks by their controller-0 value
(GM 0, User 1, then 2, 3, 4); this project calls 2/3/4 `P1`/`P2`/`P3`, and
the columns are mapped left to right. Each cell carries the page's own
index number before the name, which is trimmed once — once, because a real
name may begin with a number ("61 Tines") and a name may begin with a digit
that is not one ("8va Piano" must not become "va Piano").

**The names are OCR and contain errors** — a footnote number glued to a
name, an em dash read for an en dash. `--draft FILE` writes them as a
`BANK NNN Name` transcription to proofread and rebuild with `--manual`. A
`.syx` dump wins over the page for the User bank, so `--pdf --syx dump.syx`
gives the unit's own names for that bank and the page's for the rest.

`tests/test_extract_pdf.py` pins the parser — the column geometry, the
one-time index trim, and the two traps above ("61 Tines", "8va Piano") —
over an invented TSV, so it needs neither the PDF nor OCR.
