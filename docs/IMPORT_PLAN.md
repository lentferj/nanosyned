<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Program import — implementation plan

**Repository:** `/home/lentferj/git-repos/nanosyned`
**Suggested base:** `param-verify` (current, 612 passed / 8 skipped)
**Suggested branch:** `import-parity`
**Sibling references:** `../ensqsqed`, `../kwsed`
**Companion prompt:** `docs/IMPORT_PROMPT.md`

## 0. Goal

Make `nanocli import` and the browser's `I` key import **User programs**
from SysEx (`.syx`) and MidiQuest (`.sqs`) files at the same feature level
as `ensqsqed` and `kwsed`:

- whole-bank import and single/multiple-program import to chosen slots;
- a file picker that remembers the last folder, source-bank selection for
  multi-bank `.sqs` files, and a preview that lists source names before a
  byte is written;
- the family's write safety: gate, explicit confirmations, destination
  read first, backup, read-back verification, one-step undo;
- progress with a cooperative cancel;
- an offline `--list` and a `--dry-run` that says exactly what would be
  replaced, by name.

No hardware is required to develop or test any of it; the demo device is
the fixture, and one opt-in hardware check closes the loop.

## 1. Scope

### In scope

| Area | Scope |
|---|---|
| Formats | `.syx` (one record, several records, a complete All Dump) and `.sqs` (MidiQuest container) |
| `.sqs` | every `FORM`/`BANK` section kept as a distinct **source bank**; native SoundQuest records ignored |
| Whole bank | every program in the selected source bank, written to its own User slot; slot 127 skipped |
| Single / multiple | any source program mapped to any User slot `000`–`126`; unassigned slots untouched |
| Bank parts | effects / mixes / global are **opt-in** on a bank import (default: programs only) |
| CLI | `nanocli import FILE …` with `--list`, `--bank`, `--program SRC=DST`, `--all`, `--dry-run`, `--effects`, `--mixes`, `--global`, the usual gate |
| Browser | `I` → picker → source bank → whole bank or single/multiple → confirm → progress; `l` preview into the edit buffer |
| Safety | gate inside the import screens, two confirmations, backup, verify, batch undo, cancel |
| Docs | README section, help key list, this plan, checks note |

### Out of scope (deliberate)

- **`.mid`, `.lib`, `.zip`, FAT12 images, `.bnk`** — the request names
  SysEx/SQS. The `read_import` dispatch is written so a reader can be
  added later without changing the UI or the plan.
- **Target bank choice** — only the User bank is writable on this unit.
- **Single effects / mix / global import** — those travel only as
  whole-bank opt-ins in this iteration.
- **Dependency planner** — a NanoSynth program is self-contained; it does
  not reference a stored effects patch. There is nothing to preserve or
  deduplicate.
- **Mid-screen source-bank switching** — the bank is chosen immediately
  before the import screen; leaving and pressing `I` again switches. The
  whole-bank and single screens do not rebind `s`.
- **Autoplay after preview** — `ensqsqed` sends a phrase; this plan only
  loads the edit buffer.
- **A local bank cache** — `kwsed` has one; this plan reads the file each
  time and writes the unit.

## 2. Where nanosyned stands

Already present and working:

- `nano/dumps.py` reads `.syx` and unwraps a `.sqs` into one flat
  `Library` (programs / effects / mixes / global keyed by number).
- `nano/sqs.py` scans for `F0 00 00 0E 0E … F7`; it does not preserve
  the container's bank boundaries.
- `nanocli syx FILE` prints the summary and names, offline.
- `nanocli send FILE --allow-write --yes` writes every record in a file,
  reads each destination first, backs it up, stores, reads back and
  compares; it skips mix 100 and program 127 with a note.
- The browser has `w` (gate), `z`/`Z` (undo), editors, and no import path.
- Baseline: **612 passed, 8 skipped**; ruff/format/mypy clean.

Missing, relative to the siblings:

- bank boundaries in `.sqs` (two banks with the same slot number currently
  collide and the last one silently wins);
- any per-slot selection (send is all-or-nothing);
- a preview / list of what a file holds before writing;
- a picker, an import chooser, mapping and progress screens;
- a `--dry-run`;
- one-step undo for a batch.

## 3. Parity matrix

Legend: **Y** yes, **—** no, **n/a** not applicable to that unit.

| Feature | `ensqsqed` | `kwsed` | nanosyned now | target |
|---|---|---|---|---|
| Read `.syx` offline | Y | Y | Y | keep |
| Read `.sqs` offline | Y (flat) | Y (banked) | Y (flat) | **banked** |
| `.mid` / `.lib` | Y | Y | — | out of scope |
| `.zip` / images / `.bnk` | — | Y | — | out of scope |
| CLI list of a file | `read` | `import --list` | `syx` | `import --list` |
| CLI whole bank | `backup restore` (`.syx`/`.mid`; `.sqs` sends you to the app) | `import` (cache) | `send` | `import --all` |
| CLI single / multiple | — | cache + TUI | — | `--program SRC=DST` |
| CLI dry run | — | `--list` only | — | **`--dry-run`** |
| TUI `I` chooser | Y | Y | — | **Y** |
| File picker, remembered folder | Y | Y | — | **Y** |
| Source-bank selection | Y (multi-bank) | Y (`s`) | — | **Y** |
| Whole-bank preview table | Y | Y | — | **Y** |
| Single/multiple slot map | Y (00–79) | Y (00–49) | — | **Y (000–126)** |
| Unique / range validation | Y | Y | n/a | **Y** |
| Gate inside import | Y | Y | n/a | **Y** |
| Two confirmations | Y | Y (one, plus counts) | `send` plan, no prompt | **Y** |
| Progress / cancel | Y | Y | scan only | **Y** |
| One-step batch undo | snapshot | Y (`z`) | per store | **Y** |
| Non-storing preview | Y (`l`) | Y (`t`) | — | **`l` edit buffer** |
| Overwrite named before write | Y | Y | Y (`send`) | **Y** |
| Dependency planner | n/a | Y | n/a | n/a |
| Writable target | Internal | RAM/Card | User | User |
| Skip hardwired slot | n/a | n/a | 127 / mix 100 | **same** |

## 4. Target UX

### 4.1 CLI

```
nanocli import FILE --list
nanocli import FILE --list --bank 2
nanocli import FILE --all --bank 2 --dry-run
nanocli import FILE --program 0=10 --program 3=11 --dry-run
nanocli import FILE --program 0=10 --program 3=11 --allow-write --yes
nanocli import FILE --all --bank 2 --effects --allow-write --yes
```

Rules:

- `--list` is offline. It prints each source bank, what it holds, and each
  program as `slot  name`. A `.syx` is one synthetic bank.
- `--bank N` selects a source bank. With more than one program bank,
  `--all` and `--program` require it; the error lists the bank numbers.
- `--program SRC=DST` is repeatable. `SRC` is the source **slot** in the
  selected bank (or the only bank). `DST` is the User destination.
- `--all` writes every program in the selected bank to its own slot,
  skipping source slot 127 (and destination 127 is always refused).
- `--dry-run` reads the destinations and prints the same
  `old name -> new name` lines the write would print, then stops. It opens
  the port but does **not** need the write gate.
- `--effects`, `--mixes`, `--global` extend a bank import to those parts
  when the file carries them. They are off by default. Mix 100 is the edit
  buffer and is skipped with a note; effects are 0–127.
- A real write needs `--allow-write` and `--yes`, like `send`; the plan is
  printed first and there is no interactive prompt. `--dry-run` is the
  read-only preview.
- Exit codes: `0` every record read back; `1` at least one mismatch or
  failed record; `2` usage / nothing selected.
- Empty selection is an error: "nothing selected; nothing sent".

### 4.2 Browser

`I` in the browser opens the flow. It works while the gate is locked: the
picker and mapping screens open, assignments are kept, and only the final
write is refused, on the screen's own line (`w` arms the gate in place).

```
I                  pick a .syx / .sqs file
  → source bank?   only when the file holds more than one program bank
  → whole bank | single / multiple programs
```

**Pick a file** — a modal file browser:

| key | action |
|---|---|
| `↑ ↓` | move |
| `enter` | enter a directory, or choose the highlighted file |
| `backspace` | parent directory |
| `~` | home |
| `/` | filter by substring |
| `esc` / `q` | cancel |

It lists directories and `.syx` / `.sqs` files; the last folder is
remembered in ui-state (`import.folder`), never the file. A path that no
longer exists falls back to home with a note.

**Whole bank** — a table of every source program (`slot`, `name`,
`target`, `note`), the count, the destination (`User`, always), the gate
state, and:

| key | action |
|---|---|
| `w` | arm / lock the gate |
| `ctrl+s` | import |
| `esc` / `q` | cancel |

Source slot 127 is shown as `skipped: hardwired silent`. `ctrl+s` asks
twice: first "import N programs into the User bank?", then the overwrite
list by name. The gate is checked again between the second answer and the
worker.

**Single / multiple programs** — one table:

| column | meaning |
|---|---|
| `#` | source index in file order |
| `name` | source name |
| `target` | `---` or the assigned slot, in bold |
| `state` | `free`, `used: Old Name`, or the slot the row will overwrite |

| key | action |
|---|---|
| `space` | assign to the next free slot (and advance); press again to unassign |
| `enter` / digits | type a target (3 digits; `enter` commits) |
| `u` / `backspace` | unassign the focused row |
| `A` | assign every unassigned row to the next free slots |
| `U` | clear every assignment |
| `l` | preview the focused row in the program edit buffer |
| `w` | arm / lock the gate |
| `ctrl+s` | import the assigned rows |
| `esc` | cancel a typed target first, then leave |
| `q` | leave |

Validation is immediate, on the screen's own line: duplicate target, target
127, target out of `000`–`126`, or an empty selection refuses with a
sentence and writes nothing. `ctrl+s` asks twice exactly as the whole-bank
screen does; only assigned rows are written; unassigned slots are left
alone.

**Preview `l`** sends the source record to the **program edit buffer**
(`02 00`, a load, never a store), so the unit plays it. It stores nothing,
takes no backup, and does not need the gate. The status line says so:
"loaded into the edit buffer; nothing stored". In Mix mode this loads the
program buffer, not the mix channel's, and the screen says that too.

**Progress** — after the second confirmation: `n/N`, the current slot and
name, failures so far, and `esc` to stop. Cancel is cooperative: the
current record finishes, the next is not started, and the summary names
how many were written. Written records are still backed up, verified and
undoable; the unwritten ones are not claimed.

**Done** — for every agreed read-back: update the live name
(`catalog.set_live_name`), refresh the favourites' names, refill the User
bank keeping the cursor, and push **one** undo entry. The status line
names the count and the first failure, if any.

**Undo** — one `z` restores every record of the import, newest first; a
partial undo keeps a reduced batch entry for the slots that did not come
back. `Z` still undoes the whole session.

### 4.3 Safety invariants (every task)

1. No store without the gate and a second answer. The browser asks twice;
   the CLI needs `--allow-write` and `--yes`.
2. The destination is read in full before it is written. If the read
   fails, that record is not written and the summary says so.
3. The destination is backed up once per slot per session before the
   first store; the path is named in the result.
4. The store is read back and compared byte for byte. Only an agreed
   read-back updates the catalog and the undo log.
5. Destination 127 is never written. Whole-bank import skips source 127
   with a sentence; naming 127 as a target is an error.
6. Mix 100 (edit buffer) is never stored; whole-file mix import skips it.
7. An empty assignment list writes nothing.
8. Cancel stops before the next record; completed records are reported
   and undoable, incomplete ones are not.
9. Every unit string goes through `literal()` before markup.
10. No hardware in `make check`; hardware checks stay opt-in.

## 5. Formats and data model

### 5.1 `.syx`

One synthetic bank. Programs, effects and mixes are keyed by the slot in
the message; a duplicate slot in one `.syx` is malformed and the **last**
one wins, with a `duplicates` note the list shows. The source `index` is
the position in file order and `slot` is the number the message carries;
the CLI maps `--program` by slot. A file with only one program is a
one-row bank and imports like any other.

### 5.2 `.sqs`

Each `FORM`/`BANK` section is a **source bank**, in file order. The bank
boundary is found in the container, not in the drift-prone chunk sizes:

1. extract the Alesis messages with their absolute byte spans;
2. find every `FORM` signature **outside** those spans (the signature is
   ASCII and *can* occur inside 7-bit packed data, so a naive scan would
   split a message);
3. sort the boundaries and assign each message to the last boundary
   before it;
4. a bank with no Alesis messages is kept as an empty bank (it may be a
   mix-only or native-only bank) and `--list` says so.

Within a bank, slot numbers are unique for programs; a duplicate is
last-wins with a note. Across banks, the same slot number is **not**
merged: `--bank` chooses, and the UI asks which bank when there is more
than one with programs. This is the fix for the current silent collision.

Native SoundQuest records are ignored, as today. Foreign manufacturers'
SysEx is ignored and counted, not treated as an error.

### 5.3 Source model

```python
@dataclass(frozen=True)
class SourceProgram:
    index: int  # flat position in the bank, file order
    slot: int  # the number in the dump
    name: str  # stripped; "?" when unreadable
    record: bytes  # 350 bytes


@dataclass
class SourceBank:
    index: int  # 0-based bank number in the file
    label: str  # "bank 2" / "qesence1.syx"
    programs: dict[int, SourceProgram]
    effects: dict[int, bytes]
    mixes: dict[int, bytes]
    globals_: bytes | None
    duplicates: list[int]


@dataclass
class ImportSource:
    path: str
    kind: str  # "syx" | "sqs"
    banks: list[SourceBank]
```

`read_import(path)` dispatches on the magic (`LIST` vs `F0`). It never
opens a port.

### 5.4 Selection and plan

```python
@dataclass(frozen=True)
class Assignment:
    source: SourceProgram
    target: int


@dataclass(frozen=True)
class Step:
    kind: str  # "program" (effects/mixes/global added by bank opt-ins)
    target: int | None
    record: bytes
    old_name: str | None  # filled by the reader, not the planner
    source_label: str


@dataclass(frozen=True)
class ImportPlan:
    steps: tuple[Step, ...]
    skipped: tuple[str, ...]  # "source 127 is hardwired silent"
    overwrites: tuple[str, ...]  # sentences for the confirmation
```

The planner is pure: no device, no catalog, no printing. It refuses
duplicate targets, target 127, out-of-range targets, a missing source, a
record of the wrong size, and an empty selection. `ImportPlan` is what the
CLI and the TUI both hand to the writer.

## 6. Architecture and file map

| File | Change |
|---|---|
| `nano/sqs.py` | add `read_banks(raw) -> list[bytes]`; keep `extract_sysex` as the concatenation |
| `nano/importing.py` | **new** — source model and `read_import` |
| `nano/importplan.py` | **new** — assignments, validation, bank/single planners |
| `nano/writing.py` | **new** — the read/backup/write/verify loop, extracted from `cli._cmd_send` |
| `nanosyned/cli.py` | `import` parser + `_cmd_import`; `send` delegates to `nano.writing`; `_writes` learns `import --list`/`--dry-run` |
| `nanosyned/picker.py` | **new** — `FilePickerScreen` |
| `nanosyned/importflow.py` | **new** — chooser, source-bank choice, parse helper |
| `nanosyned/importbank.py` | **new** — whole-bank screen |
| `nanosyned/importsingle.py` | **new** — single/multiple mapping screen |
| `nanosyned/importprogress.py` | **new** — progress + cancel screen |
| `nanosyned/app.py` | `I` binding, `action_import`, import worker/done, catalog refresh, `ImportRecord` logging |
| `nanosyned/editor.py` | `ImportRecord` payload |
| `tests/test_sqs.py` | bank tests |
| `tests/test_importing.py` | **new** |
| `tests/test_importplan.py` | **new** |
| `tests/test_writing.py` | **new** |
| `tests/test_cli_import.py` | **new** |
| `tests/test_importui.py` | **new** — Textual pilot flows |
| `README.md`, `_HELP` | import section and keys |
| `docs/CHECKS.md` | the opt-in hardware import check |

`nano.writing` imports `nano.backup`, `nano.verify`, `nano.records` and the
device protocol; it must not import Textual or argparse.

## 7. Task graph

```
T1 sqs banks ──► T2 import model ──► T3 planner ──┬──► T5 CLI list ──► T6 CLI write ──► T7 CLI parts
                                                   │
T4 shared writer (independent) ───────────────────┘
T8 file picker (independent) ──► T9 flow ──► T10 whole bank ──► T11 single map ──► T12 worker/progress ──► T13 batch undo ──► T14 preview
T15 docs ──► T16 QA
```

Parallel-safe pairs: `T4` with `T1`–`T3`; `T8` with `T5`–`T7`;
`T10` and `T11` **must not** run together (both wire `app.py`), so they
are serial. `T14` touches `app.py` as well, so it runs after `T13`; it may
run alongside no other UI task.

## 8. Task cards

Each card is one subagent session. The model named is the primary; the
fallback ladder is in `docs/IMPORT_PROMPT.md`.

### T1 — Bank-aware `.sqs` reading

- **Model:** `opencode/beam-free` (parser edge cases, drift tolerance).
- **Depends:** none.
- **Files:** `nano/sqs.py`, `tests/test_sqs.py`.
- **Do:** add `read_banks(raw) -> list[bytes]` using the span-aware
  boundary rule in §5.2. `extract_sysex(raw)` becomes
  `b"".join(read_banks(raw))` so existing callers do not change. Keep
  `is_sqs`, `MAGIC`, `HEADER`. A bank's payload is the concatenated
  Alesis messages that belong to it; an empty bank is `b""`. Keep the
  order of messages inside a bank.
- **Tests:** two banks carrying the same program slot stay distinct;
  `FORM` bytes inside a packed message do not split it; junk and foreign
  Sysex are ignored; a missing `F7` drops that message only; a bank with
  no Alesis message is empty; a `LIST` with one `FORM` is one bank.
- **Accept:** `extract_sysex` output is byte-identical to today for every
  existing fixture; bank count matches the real factory file's five
  `FORM`s; ruff/mypy clean.

### T2 — Import source model

- **Model:** `opencode/beam-free` (format semantics and naming).
- **Depends:** T1.
- **Files:** `nano/importing.py` (new), `nano/dumps.py` (only if a shared
  helper is genuinely needed), `tests/test_importing.py` (new).
- **Do:** implement §5.3. `.syx` → one synthetic bank; `.sqs` → one bank
  per `read_banks` entry. Names via `rec.program_name`, stripped, `?` on
  failure. Record the duplicate-slot note. `ImportSource.summary()`
  returns one sentence (banks, programs, effects, mixes, global,
  duplicates). `read_import` refuses a file with no usable records with a
  sentence naming the file.
- **Tests:** single program `.syx`; All Dump `.syx`; multi-bank `.sqs`
  with identical slot numbers; a mix-only bank; a foreign-only container;
  a truncated message; unreadable name → `?`; summary punctuation.
- **Accept:** no hardware, no Textual, no CLI; the real factory `.sqs`
  reads as five banks with programs only in bank 2; `qesence1.syx` reads
  as one bank of 128.

### T3 — Selection and plan

- **Model:** `opencode/deepseek-v4.1-flash-free` (pure logic, edge cases).
- **Depends:** T2.
- **Files:** `nano/importplan.py` (new), `tests/test_importplan.py` (new).
- **Do:** implement §5.4. `plan_bank(bank)`: every program to its own
  slot, skip 127, collect a sentence. `plan_single(bank, pairs)`:
  `pairs` is `(source_slot, target_slot)`. `plan_all_effects/mixes/global`
  helpers for T7. Validation raises `ValueError` with the exact sentence
  the CLI/TUI will show. `ImportPlan` carries `steps`, `skipped`,
  `overwrites`; `overwrites` is human sentences, not name lookups (the
  destination read fills names).
- **Tests:** duplicate target; target 127; target 128/−1; missing
  source; empty selection; all-bank skip; order is source order;
  effect/mix/global plans; mix 100 skipped; step record size checked.
- **Accept:** no I/O at all; a plan can be built from a fabricated bank.

### T4 — Shared write executor

- **Model:** `opencode/deepseek-v4.1-flash-free` (careful refactor; the
  existing suite is the guard).
- **Depends:** none (touches `cli.py`, so run before T5).
- **Files:** `nano/writing.py` (new), `nanosyned/cli.py`,
  `tests/test_writing.py` (new), existing `tests/test_cli_write.py`.
- **Do:** move the read/backup/store/read-back loop out of
  `_cmd_send` into `nano.writing.run(device, steps, *, on_step, on_result,
  cancel) -> list[Result]`. A `Result` carries kind, number, previous,
  read_back, backup path, failure and stage. `run` reads every destination
  first (for the plan display) only if the caller asks; it must be able to
  stream step by step for the TUI. `send` calls it and prints exactly the
  lines it prints today. Do **not** change `send`'s wording, exit codes or
  skip rules.
- **Tests:** all existing `test_cli_write.py` strings unchanged; a fake
  device that fails the read, the backup, the store and the read-back;
  cancellation between steps; a partial result list; backup once per slot.
- **Accept:** `pytest tests/test_cli_write.py` green byte-for-byte; the
  new unit tests cover every stage; no Textual import.

### T5 — `nanocli import --list` and parser

- **Model:** `opencode/hy4-flash-free` (small, mechanical).
- **Depends:** T3, T4.
- **Files:** `nanosyned/cli.py`, `tests/test_cli_import.py` (new).
- **Do:** add the `import` subparser and `_cmd_import`; `--list` prints
  banks, counts and programs (`slot`, `name`) with no port. Add `import`
  to `COMMANDS`. Teach `_writes` that `--list` and `--dry-run` do not
  write; a plain `import` does. Parser flags from §4.1 (write path may be
  a stub that exits "not implemented" until T6, but the offline path must
  work).
- **Tests:** `--list` on a synthetic `.syx` and multi-bank `.sqs`;
  `--list` opens no port (monkeypatch the bridge to explode); unknown
  bank lists the available ones; `--help` mentions the flags.
- **Accept:** `nanocli import FILE --list` works with `--demo` and with
  no device; no write is possible yet.

### T6 — CLI single/multiple program write

- **Model:** `opencode/deepseek-v4.1-flash-free` (safety-critical).
- **Depends:** T5.
- **Files:** `nanosyned/cli.py`, `tests/test_cli_import.py`.
- **Do:** `--program SRC=DST` (repeatable), `--bank`, `--dry-run`, the
  two gate flags, plan display (`old -> new`, by name), executor, failure
  summary, exit codes. `--dry-run` reads the destinations and prints the
  plan but writes nothing and needs no gate. Refuse target 127 and empty
  selection. Refuse ambiguous source banks without `--bank`.
- **Tests:** one and two programs; duplicate target; 127; missing
  `--bank`; dry run leaves the demo untouched; gate refusal; backup and
  read-back; a forced mismatch exits 1; a failed destination read writes
  nothing.
- **Accept:** every write is backed up and verified; the output names the
  slot and both names.

### T7 — CLI bank parts (`--effects`, `--mixes`, `--global`)

- **Model:** `opencode/mimo-v2.6-flash-free` (focused option work).
- **Depends:** T6.
- **Files:** `nanosyned/cli.py`, `nano/importplan.py`,
  `tests/test_cli_import.py`.
- **Do:** `--all` with the three part flags. Effects 0–127; mixes 0–99
  (100 skipped with a note); global once. Only when present in the file.
  The plan lists them with names. No part flags → programs only.
- **Tests:** each flag alone; all three; a file missing a part and the
  flag given → a note, not an error; mix 100 skip; global last; effect
  and mix read-back.
- **Accept:** a `.sqs` All-Dump bank imports programs and, with flags,
  the rest; the confirmation counts each kind.

### T8 — File picker

- **Model:** `opencode/flint-40b-free` (Textual UI).
- **Depends:** none.
- **Files:** `nanosyned/picker.py` (new), `tests/test_importui.py` (new).
- **Do:** `FilePickerScreen(ModalScreen[str | None])` per §4.2: directory
  listing, `.syx`/`.sqs` files, `enter`, `backspace`, `~`, `/` filter,
  `esc`. Remember `import.folder` with `config.load_ui_str` /
  `config.save_ui_state`; fall back to home when the remembered path is
  gone or unreadable, with a status note. Use `literal()` for every name.
- **Tests:** lists files; filters; enters a directory; chooses a file;
  remembers the folder across two mounts; unreadable path falls back;
  cancel returns `None`.
- **Accept:** no hardware, no parse; keyboard-only; long names do not
  crash markup.

### T9 — Import flow and source-bank choice

- **Model:** `opencode/flint-40b-free` (Textual wiring).
- **Depends:** T2, T8.
- **Files:** `nanosyned/importflow.py` (new), `nanosyned/app.py`,
  `tests/test_importui.py`.
- **Do:** bind `I`, `action_import`: picker → `read_import` (on a worker,
  with a readable error) → if more than one bank with programs,
  `ChoiceScreen("Source bank", ["bank 0 — 0 programs", …])` → `ChoiceScreen
  ("Import", ["Whole bank", "Single / multiple programs"])` → push the
  screen (T10/T11 callbacks may be stubs until those land; keep the flow
  testable). Locked gate still opens; the screen shows the gate state.
- **Tests:** `I` opens the picker; a parse error is a report screen and
  no write; two program banks ask; one bank skips the question; cancel at
  each step leaves the bank untouched.
- **Accept:** no MIDI writes in this task.

### T10 — Whole-bank screen

- **Model:** `opencode/deepseek-v4.1-flash-free` (destructive screen).
- **Depends:** T9.
- **Files:** `nanosyned/importbank.py` (new), `nanosyned/app.py`,
  `tests/test_importui.py`.
- **Do:** §4.2 whole-bank table, `w`, `ctrl+s`, two `ConfirmScreen`s,
  gate re-check, skip 127 row, return `ImportPlan` to the app. No device
  in the screen.
- **Tests:** locked gate refuses and keeps the screen; 127 shown
  skipped; two confirms; cancel at either confirm writes nothing; gate
  locked between confirms refuses; plan count matches.
- **Accept:** the screen sends nothing itself; the callback receives the
  plan and nothing else.

### T11 — Single/multiple mapping screen

- **Model:** `opencode/beam-free` (assignment logic, validation).
- **Depends:** T10 (serialize `app.py`; separate file).
- **Files:** `nanosyned/importsingle.py` (new), `nanosyned/app.py`,
  `tests/test_importui.py`.
- **Do:** §4.2 map: `space`, `enter`/digits, `A`, `u`/`U`, `l` (delegate
  to the app's preview callback), `w`, `ctrl+s`, `esc` two-step. Live
  validation and state column. Return assignments, not a plan (the app
  plans, so it can name destinations from the catalog).
- **Tests:** assign one; duplicate refusal; 127 refusal; out-of-range;
  auto-assign skips used; unassign; clear; gate kept; cancel typed target
  then screen; non-printing digits.
- **Accept:** unassigned slots never appear in the plan.

### T12 — Import worker, progress, refresh

- **Model:** `opencode/mimo-v2.6-flash-free` (worker + screen).
- **Depends:** T10, T11, T4.
- **Files:** `nanosyned/importprogress.py` (new), `nanosyned/app.py`,
  `tests/test_importui.py`.
- **Do:** `_import_worker(plan)` on a thread: claim the exchange, read
  destination, backup, store, read back per step; report progress; check
  the cancel flag between steps. `ImportProgressScreen` shows `n/total`,
  current, failures, `esc`. On done: update live names, refresh
  favourites, refill keeping place, push undo, status summary.
- **Tests:** a plan of three, the second fails → first and third written,
  status names the failure; cancel after one; no catalog update for a
  mismatch; busy exchange refuses; gate locked at start refuses.
- **Accept:** `make check` needs no unit; a fake device drives every
  branch.

### T13 — One-step batch undo

- **Model:** `opencode/deepseek-v4.1-flash-free` (undo semantics).
- **Depends:** T12.
- **Files:** `nanosyned/editor.py`, `nanosyned/app.py`,
  `tests/test_app.py`, `tests/test_importui.py`.
- **Do:** `ImportRecord(edits: tuple[EditRecord, ...])`; `_undo_worker`
  expands it, rewrites newest-first, verifies each; a partial failure
  pushes a reduced `ImportRecord` with only the failed edits; `label`
  names the count. One `z` consumes one entry.
- **Tests:** all restore; one fails and stays; two imports undo in order;
  `Z` clears both; catalog names revert.
- **Accept:** undo of an import never claims a slot it did not restore.

### T14 — Preview into the edit buffer

- **Model:** `opencode/hy4-flash-free` (small, one path).
- **Depends:** T11; run after T13 because it also edits `app.py`.
- **Files:** `nanosyned/importsingle.py`, `nanosyned/app.py`,
  `tests/test_importui.py`, `tests/test_bridge.py` (only if a helper is
  missing).
- **Do:** `l` calls the app's preview callback with the focused record;
  the app sends `write_edit_program(record, edit=0)` (opcode `02`, a
  load), status "loaded into the edit buffer; nothing stored". No gate,
  no backup, no undo. In Mix mode add "the mix channel is what plays".
- **Tests:** `l` sends exactly one `02 00` message; no store opcodes; no
  backup; status text; locked gate still allows it.
- **Accept:** the unit is left playing the preview, nothing stored; no
  stored slot changed (demo asserts).

### T15 — Docs, help, checks

- **Model:** `opencode/inkling-2-small-free` (prose).
- **Depends:** all feature tasks.
- **Files:** `README.md`, `nanosyned/app.py` (`_HELP`),
  `docs/CHECKS.md`, `docs/IMPORT_PLAN.md` (status only).
- **Do:** a README "Importing programs" section with the CLI examples and
  the browser keys; `_HELP` gains `I`; `docs/CHECKS.md` gains the opt-in
  hardware import check; no code changes.
- **Tests:** none; run the link/text checks the repo has.
- **Accept:** every key in the plan appears in help; every command in the
  plan appears in README.

### T16 — QA and review

- **Model:** `opencode/beam-free` (review).
- **Depends:** T1–T15.
- **Files:** all (read-only; fixes only).
- **Do:** full `make check`; a demo end-to-end (single, multi, bank,
  dry-run, cancel, undo); read every new screen for `literal()` use;
  confirm no hardware in `make check`; confirm no store without gate;
  fix nits; write the final status.
- **Accept:** 0 failures, 0 warnings, clean tree; the plan's definition of
  done is met.

## 9. Verification

- **Per task:** the card's tests, plus `ruff check`, `ruff format --check`
  and `mypy` on the touched files.
- **Per wave:** the full `pytest` suite (baseline 612 passed / 8 skipped
  must never go down), and a demo smoke test.
- **End-to-end demo:** `nanocli --demo import <fixture> --list`;
  `--program 0=5 --dry-run`; `--program 0=5 --allow-write --yes`; then
  `nanocli --demo syx` on a fresh dump to prove the bytes.
- **Hardware (opt-in, human-run):** one single import into a spare User
  slot, read back, then restore the previous bytes from the named backup.
  Behind `NANOSYNED_HW_WRITE=1`; never part of `make check`; one session
  at a time. Record the result in `docs/CHECKS.md`.
- **Real files:** `Nanosynth_Factory_User.sqs`, `qesence1.syx`,
  `qesence2.syx`, `qesence_bestof.sqs` may be read for a manual check but
  their contents never enter the repository.

## 10. Risks and decisions

| Risk | Decision |
|---|---|
| `.sqs` chunk sizes drift | split on `FORM` boundaries that lie outside extracted SysEx spans |
| same slot in two `.sqs` banks | keep banks distinct; require `--bank` / ask in the UI |
| `FORM` ASCII inside packed data | span-aware boundary scan; tested |
| refactoring `send` changes output | existing `test_cli_write.py` strings are the contract |
| two screens both edit `app.py` | T10 then T11, serial |
| batch undo partial failure | reduced `ImportRecord` keeps only the failed slots |
| preview in Mix mode | say the program buffer is loaded, not the mix channel |
| hardwired 127 | skip on bank import, refuse as a destination |
| edit buffer 100 | skip on mix import, never store |
| no `.mid`/`.lib` | out of scope now; `read_import` dispatch is the extension point |

## 11. Definition of done

- [ ] `nanocli import FILE --list` works offline for `.syx` and `.sqs`.
- [ ] `nanocli import FILE --program SRC=DST` writes one or many with
      gate, confirm, backup, read-back and honest failures.
- [ ] `nanocli import FILE --all --bank N` imports a whole bank; `--dry-run`
      names every overwrite.
- [ ] `--effects`, `--mixes`, `--global` extend a bank import, off by
      default; mix 100 skipped.
- [ ] `I` opens the picker, remembers the folder, asks for a source bank
      when needed, and offers whole-bank and single/multiple flows.
- [ ] Mapping validates duplicates, range and 127 before any send.
- [ ] `w` works inside both import screens and keeps assignments.
- [ ] Two confirmations; the gate is re-checked after the second.
- [ ] Progress with a cooperative cancel; written records are verified
      and undoable, unwritten ones are not claimed.
- [ ] One `z` undoes a whole import; a partial undo keeps a reduced entry.
- [ ] `l` previews into the edit buffer and stores nothing.
- [ ] `make check` is green and hardware-free; the opt-in hardware check
      is documented and has been run once.
- [ ] README and `_HELP` name every new key and flag.
