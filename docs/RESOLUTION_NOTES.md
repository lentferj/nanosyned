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

* Moving the cursor sends nothing by default, enforced by a test. The
  explicit `a` auto-load mode is the only exception; it is remembered.
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

## 14. The favourites view is `F`

The family's shift-pair is `f` set / `F` view, and this tool follows it.
`F` is the family's canonical key, so the binding and the legend need no
per-tool rename. Some siblings — rxved, p2ked, emorphed and ensqsqed —
move the view to `v` because `f` writes the favourites database and `F`
only reads; that is their safety argument, not part of this tool's
contract. `tests/test_conformance.py` checks the binding and the legend
against the family with no divergence.

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
(User 000), so the tool could not distinguish a short gap from a working
one. It stays `0.005`. Whether the edit buffer not updating is a fact about
the unit's Program Change handling, a fact about the edit buffer until a
note is played, or a flaw in the probe is not established here — it is
recorded as an open question rather than a finding.

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

## 19. The parameter tables are transcribed as data

`nano/params.py` carries the QS specification's parameter tables as data:
Global 20 rows, Mix common 13 plus a 20-row channel template, Effects
11 + 64 + 6, Program common 13 plus 31 sound rows -- 178 rows in all.
They are keyed by (mode, function, page, pot) with the spec's ranges,
named choices and bit addresses. Nothing here establishes that this
firmware honours any of them; the specification is a lead, and the
firmware's behaviour is not established by transcription. The next step
is the differential verification plan in
`docs/PARAMETER_VERIFICATION_PLAN.md`, which promotes a row to verified
only after a controlled before/after change on the unit confirms its
offset and its value law. Until then the editors write only what the
specification documents, and rows the specification marks for another
model are shown and are not editable.

## 20. Opening `p` sends one Mode Select, and the gate decides

The parameter editor opens in **Mix mode on purpose**, and the open itself
is where that Mode Select is sent. The bench reason is the one in
`docs/PARAMETER_VERIFICATION_RUN_LOG.md`: a Program ``10`` edit lands only
in the per-channel Mix buffer. In Program mode the same message changes
nothing at all, so an editor that opened without asking for Mix mode would
offer rows whose edits silently do not happen.

That send is a send, and the app treats a Mode Select as a write
everywhere else (`M` asks the gate and a confirmation first). So `p` is now
gated like the other write keys:

- `w` decides. A locked gate means no Mode Select **and no editor** -- the
  status line carries the gate sentence and nothing goes on the wire.
- The exchange is claimed on the main thread, before the worker exists,
  and a port that is already busy refuses with "busy". This is the same
  shape as `M`, `g`, `x` and the stores: a worker that failed still
  releases the exchange in a ``finally``.
- The worker sends one Mode Select and nothing else. It stores nothing and
  reads nothing back; this protocol does not answer a Mode Select, so no
  state is claimed about the unit's mode.
- `ParameterScreen.on_mount` sends nothing at all. It builds its table,
  shows the Mix-mode warning and fills from the buffer. A screen
  constructed directly -- by a test, or by a later caller -- is silent.

This closes the review's R4/R9 finding without giving up the bench reason.
The previous shape sent an ungated Mode Select from the screen's mount,
swallowed every failure with a bare ``except Exception: pass``, and pinned
that violation in a test. The test now asserts the discipline instead:
gate first, one claimed send, the warning on screen, and no send when the
gate is locked or the port is busy.

## 21. The MidiQuest `.sqs` container is scanned, not walked

`nano/sqs.py` is the `.sqs` reader used by `nanocli import` and the
browser. A `.sqs` is an IFF-like container: four-byte chunk type, four-byte
big-endian size, then data. A `LIST` wraps one `FORM` per bank, and each
`FORM` ends in a `BODY` whose payload is plain concatenated Alesis SysEx --
the bytes an All Dump would have, or a slice of one.

**The chunk sizes are not trusted.** The files this was written against
have a first `FORM` whose declared size ends 44 bytes before the next
`FORM` begins; a walker that trusts the size steps into the next bank's
header. The reader therefore scans for the Alesis header
`F0 00 00 0E 0E` and its terminating `F7`. Packed data is 7-bit by
construction, so an `F7` cannot occur inside a message and the first one
after a header ends that message. A header with no `F7`, or a second header
before the terminator, is dropped rather than repaired.

**Only Alesis messages are taken.** One test file carries a Roland XV-2020
patch; a foreign `F0` is skipped. Bank boundaries are the `FORM`
signatures that fall *outside* an extracted message's byte span -- a
`FORM` can occur inside 7-bit packed data, so a naive search would invent a
bank. Each message belongs to the last boundary before it; a `FORM` that
receives no Alesis message stays an empty bank. The result is byte-for-byte
what a plain `.syx` holding the same messages would be, so
`nano.dumps.read_bytes` handles both formats through one path.

`.mid` and `.lib` are still unread. Nothing in the current import path
needs them; the scanner is written so another container reader can be
added without changing the planner or the screens.

## 22. Preset memory is content-addressed, not slot-addressed

The favourites database is deliberately keyed on the slot: a row survives
a rename because the slot is the identity. The preset memory is the other
kind of identity. It is keyed on `sha256(record[:350])`, the full unpacked
program including its ten-character name. It answers "have I seen these
exact bytes before, and did I favourite them?", not "which slot is this?".

`preset-memory.db` is a separate SQLite file beside `favorites.db`. The
shared favourites schema is family property and was not changed; this is a
nanosyned memory. The memory stores a content row (name, favourite, rating,
tags, note, first/last seen, seen count) and a `slot_content` cache binding
a User slot to the digest currently in it. The sidecar path is injectable
through `--preset-memory`.

On a verified import or send, the app remembers the record, binds the
destination, and if the content was a favourite reactivates the slot row
with the memory's annotations. A non-favourite import over an old favourite
clears that slot's mark; the old content remains in the memory, so loading
it again restores its heart. Toggling `f` with a known digest is
content-level: turning it off deactivates every bound occurrence of those
bytes. If the digest is unknown, the old slot-only behaviour remains.

Existing slot favourites migrate lazily, the first time their bytes are
seen. The memory's annotations win over a different slot row; with two
active old rows that hash to the same content, the earliest-added row's
annotations win. There is no full-bank read at startup.

**Limits, recorded rather than hidden.** The hash is the program record,
not the complete sound: effects, mixes and global settings are outside it.
Renaming changes the digest; a name-insensitive "same sound" hash is not
implemented. The memory is local; the annotations do not travel in a
`.syx`. Tests use synthetic records and a temporary sidecar, and no
hardware check was needed for this branch.

The catalog is not the home for this data. `catalog.json` is generated
name data and may be regenerated; losing the user's ratings, tags and notes
with it would be the wrong trade. The sidecar is the authority for content
and annotations, while `favorites.db` remains the authority for which
slots currently display a heart.

## 23. Exporting favourites: read all, then write atomically

Export writes the active favourite programs of the User bank to one `.syx`
file. The decision, and the reasons for it:

- **Read all first, write once.** Every selected slot is read from the unit
  with `writing.read_record` and truncated to `records.PROGRAM_BYTES` before
  any file is created. A short or failed read, or a cancelled read, aborts
  the whole export and leaves no file. A partial backup is worse than no
  backup.
- **Atomic write.** `write_syx` builds the file in memory, writes it to
  `path + ".tmp"` in the same directory, flushes, and then `os.replace`s
  it into place. A write error removes the temporary file. `overwrite=False`
  refuses an existing path with `FileExistsError`; the caller (CLI
  `--force`, or the browser's confirmation) decides whether to replace.
- **Original slot numbers preserved.** The file is built with
  `messages.program_dump(number, record)` in ascending slot order, so it is
  a faithful snapshot: a whole-bank import restores it, and an append import
  can ignore the numbers.
- **Active USER favourites only, slots 000-126, ascending.** Slot 127
  (`Off`) is excluded: it is readable but cannot
  be written back, so exporting it would make a file that cannot be fully
  restored. Non-User favourites are ignored. An empty set refuses with
  `ValueError("no favourited User programs to export; nothing written")`.
- **Annotations are not exported.** Ratings, tags and notes live in the
  local favourites database and are not part of the program record; the
  `.syx` carries program bytes only. The export does not pretend otherwise.
- **No write gate.** Export only reads the unit, so it needs no
  `--allow-write` / `--yes` and is not blocked by a locked gate. Exit code
  0 is a written file; 1 is a read/write failure, no favourites, or a
  refused existing file.

## 24. Initialising the User bank: the template and the fence

Init replaces User programs `000`-`126` with the unit's own Init program.
User `127` (`Off`) is hardwired silent and is never written. The template is
the unit's hardwired `Off` record from slot `127` with only its name changed
to `Init`; `nano/initbank.init_record` changes only the name bits and nothing
else, and `is_init` is whole-record equality, so a program merely called
`Init` with different parameters is not free.

- **Template candidate:** the `127 Off` record renamed `Init`. It passed a data
  write/read-back check on the bench (the staged record was stored into a
  scratch slot and read back byte for byte) and was confirmed silent. The
  scratch slot was then restored from its backup and verified byte for byte.
- **Range:** `000`-`126` only; `127` is never a destination, including in a
  hand-built plan.
- **Fence:** init uses the normal read/backup/store/read-back/undo fence, one
  ordinary program store per slot. No sector/flash opcode is sent. A failed
  destination read leaves that slot untouched; the browser names it in the
  summary, while the CLI stops with the error.
- **Undo:** one batch entry restores the agreed slots newest first; a partial
  init leaves a reduced entry.
- **Favourites:** init preserves the old favourite content in the preset
  memory. The marks on initialised slots are hidden (deactivated) while the
  old content's ratings, tags and notes are kept; they return if those bytes
  are loaded again or the slot is re-favourited.
- **CLI:** `nanocli init-bank --allow-write --yes` (with `--dry-run`).

## 25. Appending imports: placement and overflow

Append writes source programs into free User slots without replacing existing
programs.

- **Free slots:** trailing slots holding the Init template. `append_start`
  scans backwards from `126` for Init slots and returns the first free trailing
  slot; it appends only after the highest non-Init slot and never fills gaps.
- **Overflow:** if the file needs more slots than are free, the screen names
  the cut programs and offers load-what-fits (`ctrl+s`) or single/multiple
  (`s`). The CLI equivalent is `--cut` (load what fits) versus refusing with
  the cut list and exiting 2; `--dry-run` prints assignments and cuts.
- **No free slots:** points to `N` (init bank) or the single/multiple picker.
- **Programs only:** effects, mixes and global records are not appended.
- **CLI:** `nanocli import FILE --append` (plus `--cut`, `--dry-run`).

## 26. Auto-load and left/right pane focus

Cursor movement is silent by default. `a` explicitly enables **auto-load**:
while the slot pane has focus, moving the cursor sends the focused slot's
Bank Select MSB/LSB and Program Change after a 120 ms debounce. The debounce
coalesces key repeat and fast scrolling; Enter cancels a pending auto-load
and performs its explicit select. The toggle is remembered in
`ui-state.toml` as `auto_load`. Going left, or leaving the slot pane, cancels
a pending send. Auto-load never uses the write gate: a selection is not a
store.

The two panes are focused with `tab` or with `←`/`→`. The pane tables replace
the DataTable's left/right cursor bindings with pane-focus actions; up/down
and Enter remain the DataTable's. The default silence invariant is now
"cursor movement sends nothing unless the user has explicitly enabled
auto-load"; `tests/test_auto_load.py` pins both states and the persistence.

## 27. Mixes are a pseudo-bank, and mode is tracked best-effort

The left pane's sixth row is **Mixes**, not a program bank. It lists the
unit's 100 mixes; the names are read with the existing silent Mix Dump
Request on first use and cached for the session. Mixes have no Bank Select
and no favorites/catalog entries; the right pane shows number and name.

Selecting a mix sends **Mode Select: Mix mode**, reads the stored mix and
loads those bytes into the live mix buffer with a mix dump numbered `100`.
It does not send Program Change: on this family that selects a mix only when
the global MIDI Mix Selection channel matches, and with that setting off (or
on another channel) the message edits the current mix instead. The buffer
load is independent of that setting. Selecting a program while the tracked
mode is Mix sends Program mode first, then the normal Bank Select + Program
Change. The protocol has no mode query and no current-mix query, so
`_unit_mode` is explicitly best-effort: it records what this app last sent,
not what the unit is necessarily doing. A manual `M` Mode Select updates it
on success. The direct mix selection does not use the write gate because it
is a selection, like Enter on a program; `M` remains the gated manual mode
change. `e` on the focused mix opens its editor; the old `m` prompt is gone.
Opening the editor also puts the unit in Mix mode and loads that stored mix
into buffer `100`.

The mix editor edits the live buffer, not a private staging area: changing a
field builds the whole record and loads it back into buffer `100`, then reads
it back. A whole-buffer load is used rather than the per-field Mix MIDI Edit
because the program-number field did not change through the direct edit on
the bench, while the load carries it correctly. Enter and Space toggle the
one-bit fields; the program field opens the User-bank program picker by name;
other fields still ask for a number. `a` then `s` stores the result, and
storing the loaded mix reloads buffer `100` again so the stored and audible
states agree.

The QS `program_type` field is deliberately not exposed. The specification
names it a four-bit field but gives its range as 0-1 and does not say what
the two values mean; every channel of this unit's stored mixes reads 8,
outside that range. It stays in the decoder, where it is reported as data,
but it is not offered as a control.

## 28. A full backup is a normal `.syx`, not another envelope

A full backup captures the whole unit in one file so the entire state can be
restored in a single send. It is deliberately not another JSON envelope: the
file is one ordinary Alesis `.syx`, the same shape `nanocli send` accepts.

- **What it holds:** 356 messages / 79,071 bytes. User programs 000-126
  (127 programs; 127 is hardwired silent and excluded), user effects
  000-127 (128), user mixes 000-099 (100; 100 is the non-stored edit buffer
  and excluded), and the one global settings record.
- **Individual reads, not All Request.** Each record is read with the same
  per-destination read used elsewhere, so a failure names the destination it
  stopped on instead of collapsing into one opaque All Dump error.
- **Read all first, then write atomically.** All 356 destinations are read
  before any file is created; only then is the file written to
  `path + ".tmp"`, fsynced, and `os.replace`d into place. A failed or
  cancelled read leaves no file behind.
- **Read-only toward the unit.** It needs no write gate and no
  `--allow-write` / `--yes`; the browser confirms before replacing an
  existing file, and the CLI uses `--force` for the same purpose.
- **Entry points:** `B` in the browser (a path prompt defaulting to
  `nanosyned-backup-YYYYMMDD-HHMMSS.syx` in the remembered import folder,
  or home) and `nanocli backup save --file PATH`.
- **Restore:** `R` in the browser chooses a `.syx`, refuses a file with more
  than one source bank, shows the record counts, asks the shared gate and
  two confirmations, then runs the normal read/backup/store/read-back
  fence. Program, effects, mix and global edits become one `restore` undo
  entry, so `z` sends every previous record back through its kind-specific
  writer. The CLI path remains `nanocli send FILE --allow-write --yes`.
  `nanocli backup restore` remains for the pre-write JSON envelopes, not full
  `.syx` files, and `nanocli backup list` still lists only those envelopes.
