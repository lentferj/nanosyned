<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Export favourites, init bank, append import — implementation plan

**Repository:** `/home/lentferj/git-repos/nanosyned`
**Status:** plan only; nothing below is implemented yet
**Base:** the current uncommitted tree (favourites view on `F`, UI state in
`ui-state.toml`, import flow and write fence already present)
**Sibling references:** `../kwsed` (init bank), `../ensqsqed` and
`../kwsed` (import screens and batch undo)

## 0. Goal

Add three related operations to the browser and the CLI:

1. **Export favourites** — write the User-bank programs that carry an
   active favourite mark to one `.syx` file, leaving every non-favourited
   program out.
2. **Init User bank** — replace User programs `000`–`126` with the unit's
   own empty/Init program. User `127` (`Off`) is hardwired and is never
   written.
3. **Append import** — add an `Append` choice to the import flow. It writes
   the source programs into free User slots without replacing existing
   programs. If the file needs more slots than are free, the screen names
   what would be cut and offers either “load what fits” or “choose
   single/multiple programs”.

The three are designed to work together:

```
E  export favourites  ->  favourites.syx
N  init User bank     ->  slots 000-126 are Init
I  append favourites.syx  ->  slots 000... receive the exported programs
```

The syx file carries program bytes only. Ratings, tags and notes live in
the local favourites database and are **not** exported; this plan does not
pretend otherwise.

> **Priority: feature 2 is the critical path.** Init is the operation that
> creates the free slots append needs, and it is the only one that replaces
> every writable User program in one action. It therefore gets the detailed
> treatment below: a hardware gate, an explicit template decision, a
> per-slot failure matrix, and its own acceptance criteria. Export and
> append are designed around it, not the other way round. If only one
> feature is implemented first, it is **init bank**.

## 1. Decisions at a glance

| Question | Decision | Why |
|---|---|---|
| What is exported? | Active favourites in `USER`, slots `000`–`126`, ascending | The request names favourite-marked User presets; `127` is hardwired and cannot be restored |
| Where do export bytes come from? | Read each selected slot from the unit, not the catalog | The catalog holds names, not program records |
| Export file format | Concatenated `USER_PROGRAM_DUMP` messages, original slot numbers | It is exactly what `nano.dumps.read_syx_file` already reads, and it remains a faithful snapshot |
| Export write safety | Read every record first; write atomically only if all reads succeeded; refuse an existing path unless explicitly replaced | A partial backup is worse than no backup |
| What is “Init”? | Candidate: the unit's hardwired `Off` record from program `127`, with its name changed to `Init`; **not enabled until the hardware check in §4.2 passes** | It is the only empty record the unit itself provides; no parameter bytes are invented |
| Init range | `000`–`126`; never `127` | `127` is hardwired silent |
| Init execution | 127 ordinary program stores, each read/backup/store/verify through the existing fence | No bulk erase and no invented bytes; every slot is independently undoable |
| Init failure | Stop that slot, keep going only if the destination read succeeded; report every failure; never claim a failed slot was initialised | The family's write fence already works this way |
| Init undo | One batch `z` restores every slot that agreed; a partial init leaves a reduced batch | Same undo log as import |
| Init favourites | Keep the marks; refresh their names to `Init` | Init replaces programs, not the user's annotations; clearing marks is a separate destructive choice |
| Free slot | A User program byte-identical to the Init template | Names can be stale or duplicated; record equality is checkable |
| Append placement | After the highest non-Init slot, through `126` | “Append” means after existing programs; gaps before the last program are left for the single picker |
| Append overflow | Keep the first N source programs in file order; name the rest as cut; or open the single/multiple picker | Deterministic, and the user can choose differently in the picker |
| CLI parity | Add `dump favourites`, `init-bank`, and `import --append` | The project already treats CLI and browser as two drivers of the same plans |
| Sector erase | **Not used** | `SECTOR_ERASE` is flash-level and undocumented for this purpose; a wrong use can destroy more than the User bank |

## 2. Existing machinery to reuse

- `nano/importing.py` reads `.syx`/`.sqs` into `ImportSource` /
  `SourceBank` / `SourceProgram`.
- `nano/importplan.py` validates targets, skips source `127`, and produces
  immutable `Step` / `ImportPlan` objects. The plan is pure.
- `nano/writing.py` reads a destination, backs it up, stores it and reads
  it back. `writing.run` is the CLI driver; the browser's
  `_import_one_step` is the same fence with progress callbacks.
- `nanosyned/importflow.py` is the picker → source bank → mode state
  machine. `IMPORT_MODES` is the one place the import choices live.
- `nanosyned/importbank.py` is the whole-bank preview; it already shows
  plans, the gate, two confirmations and a progress screen.
- `nanosyned/importsingle.py` is the manual mapping screen; append reuses it
  for the “choose single/multiple” escape hatch.
- `nano/favorites.py` is a binding of `vinsynlib.favorites`;
  `keys_for_bank("USER")` returns the active favourite numbers.
- `nano/banks.py` already names `SILENT_PROGRAM = ("USER", 127)`.

## 3. Feature 1 — export favourited User programs

### 3.1 Core: `nano/exporting.py`

New pure-ish module (it may read a device through a caller-supplied
function, like `nano.writing`):

```python
USER_BANK = "USER"


def favourite_numbers(favorites) -> tuple[int, ...]:
    """Active USER favourites, 000-126, ascending, 127 excluded."""


def read_programs(device, numbers, *, on_read=None, cancelled=None):
    """Read every slot first; return ((number, record), ...)."""


def write_syx(path, programs, *, overwrite=False) -> int:
    """Concatenate program dumps and write atomically; return byte count."""


def export_favourites(
    device, favorites, path, *, overwrite=False, on_read=None, cancelled=None
) -> ExportResult:
    """The whole operation: numbers -> reads -> one file."""
```

Rules:

- `favourite_numbers` raises `ValueError("no favourited User programs to
  export; nothing written")` when the set is empty.
- Slot `127` is excluded with a note, not silently. It is readable but
  cannot be written back; exporting it would make a file that cannot be
  fully restored.
- Every record is read with `writing.read_record(device, "program", n)` and
  truncated to `records.PROGRAM_BYTES`; a short or failed read aborts the
  whole export **before** any file is created.
- The file is built with `messages.program_dump(number, record)` in
  ascending slot order. Original slot numbers are preserved, so a
  whole-bank import is a restore and an append import can ignore them.
- `write_syx` writes to `path + ".tmp"` in the same directory, flushes,
  then `os.replace`s it. `overwrite=False` refuses an existing path with
  `FileExistsError`; the caller decides whether to ask.
- A cancelled read leaves no file. A write error removes the temporary
  file and reports the OS error.
- No write gate is needed: export only reads the unit.

### 3.2 CLI: `nanocli dump favourites --file PATH`

- Add `favourites` to the `dump` group. It needs `--favorites` (the store
  path), `--file`, and `--force` to replace an existing file.
- It opens the unit and the store, calls `export_favourites`, and prints
  `exported N program(s) to PATH`.
- No `--allow-write` / `--yes`: nothing is stored on the unit.
- Exit codes: `0` written; `1` read/write failure; `2` no favourites or a
  refused existing file.
- It is not an offline command: it must read the programs from the unit.

### 3.3 Browser: `E` export favourites

- Add `Binding("E", "export_favourites", "Export favourites")` and the
  legend hint `E export favourites` to `WRITE_HINTS` (or the extras tuple;
  see §6).
- `action_export_favourites`:
  1. Refuse if no favourites store is open.
  2. Ask the store for the active USER favourites and show the count.
  3. Prompt for a path with the family's `ui.prompt`, defaulting to
     `~/nanosyned-favourites.syx` (or the remembered import folder plus
     that filename). Expand `~`.
  4. If the path exists, ask before replacing it. A `no` returns without
     opening the port.
  5. Acquire the exchange/busy gate, push a progress screen and start a
     worker.
- The worker reads each favourite in turn and reports `n/N`, slot and
  name. It never touches widgets; every update uses
  `self.call_from_thread`. On cancel it stops before the next read and
  writes nothing.
- On success, the main thread reports the path, count and byte size. On
  failure, it names the slot that could not be read; no file exists.
- The progress screen can be the existing `ImportProgressScreen` with a
  small `title`/verb parameter, or a sibling `ReadProgressScreen`; do not
  put a second progress implementation in the app.

### 3.4 Tests

- `favourite_numbers` returns only active `USER` favourites, sorted, with
  `127` dropped; non-User favourites are ignored.
- Empty favourites refuses and creates no file.
- A read failure at the third slot creates no file.
- The file round-trips through `dumps.read_syx_file`: only the selected
  programs, original numbers, exact 350-byte records.
- Existing path is refused without `--force`; with `--force` it is
  replaced; the temporary file does not remain.
- Cancel writes nothing.
- TUI: `E` with no store, no favourites, a path with `~`, an existing
  path, a read failure and a successful export. Locked write gate does not
  block export.
- CLI: gate flags are not required; exit codes and `--force`.

## 4. Feature 2 — init the User bank (primary work)

### 4.0 Why init is the critical path

Init is not just “write 127 records”. It is the only operation that:

- replaces **every writable User program** in one action;
- defines what “free” means for append;
- makes the export → init → append workflow useful;
- needs a template whose bytes are not yet established for this unit.

For those reasons it gets its own hardware gate and a larger test surface
than the other two features. Export is a read; append is a placement
policy; init is the destructive primitive they depend on.

The invariant is simple:

> **Init writes only User `000`–`126`, only the verified Init record, and
> only through the same read → backup → store → read-back fence as every
> other write in this project. `127` is never written. No template byte is
> invented.**

### 4.1 What “empty” means, and the template options

The NanoSynth manual says User `127` is hardwired silent and cannot be
deleted, edited, overwritten or changed. Its name is `Off`. It is the only
record the unit itself presents as empty.

What is not established: **is the record silent because of its bytes, or
because slot `127` is special?** If the latter, copying the `127` record
into `000` could produce a normal-sounding program, which is not an empty
slot.

Options considered:

| Option | Verdict |
|---|---|
| Copy the `127 Off` record, rename it `Init` | **Candidate.** Smallest, uses the unit's own bytes, no invention. Must pass §4.2. |
| Write an all-zero 350-byte record named `Init` | **Rejected.** The parameter bytes are unknown; all-zero may not be a neutral or silent program. |
| Use `SECTOR_ERASE` / `SECTOR_WRITE` | **Rejected.** Flash-level opcodes; the QS specification does not define this as “clear the User bank”, and a wrong sector can destroy more than the bank. |
| Embed a captured Init record from a factory-initialised unit | **Fallback.** Good if the user can supply a verified dump; do not guess the bytes. |
| Require a user-supplied `--template FILE` | **Fallback / escape hatch.** Useful for development and for a unit whose `127` record is not copyable. |
| Leave empty slots untouched and only write selected slots | Not “init the whole bank”; that is the single-import path. |

The plan therefore proceeds with the `127 Off` candidate **behind a
hardware gate**. Until that gate passes, the implementation may land behind
a `--template`/injected-template seam, but the browser must not offer a
one-key “init everything” that uses an unverified record.

### 4.2 Blocking hardware check: is the candidate actually silent?

Run this on the bench before enabling the feature. It is a gate on tasks
I2–I4, not a detail to discover during coding.

The User bank is a scratch area: full permission is granted to write,
overwrite, init/clear and restore `000`–`126` for this check. No per-write
permission prompt is needed. User `127` is still never written, and the
normal gate, backup and read-back fence still applies.

**Preparation**

1. Choose a scratch slot, preferably `000`; back it up with
   `nanocli dump program 0 --file /tmp/user-000.syx`.
2. Read User `127`: `nanocli dump program 127 --file /tmp/user-127.syx`.
3. Build the candidate: the 350-byte `127` record with its name changed to
   `Init` (the `init_record()` helper from §4.3, or a one-off script).
4. Confirm the candidate differs from the `127` dump only in the name
   bytes and is exactly `records.PROGRAM_BYTES` long.

**Write and listen**

5. Store the candidate into the scratch slot through the existing editor
   or `nanocli send` (gate armed; backup taken).
6. Select the scratch slot on the unit and listen. It must be silent.
7. Read the scratch slot back; it must equal the candidate byte for byte.
8. Repeat once after a power cycle, if the unit's RAM behaviour is not
   already known.

**Restore**

9. Restore `/tmp/user-000.syx` to the scratch slot and verify it.

**Decision**

- If the copy is silent, accepted and read-back identical: the candidate
  is verified. Record the result, the unit firmware/identity, and the
  exact template digest in `docs/RESOLUTION_NOTES.md`.
- If it makes sound, is refused, or reads back differently: **stop.** Do
  not enable init with the `127` candidate. Use a user-supplied verified
  Init dump, or keep init behind `--template` until one exists.

A useful extra check: write the candidate to two different scratch slots
and read both back, to rule out a slot-specific effect. Do not use `127`
as a scratch slot.

### 4.3 Core: `nano/initbank.py`

```python
INIT_NAME = "Init"


def init_record(off_record: bytes) -> bytes:
    """The 127 Off record with its name changed to Init."""


def is_init(record: bytes, template: bytes) -> bool:
    """True only for a byte-identical Init record."""


def append_start(read, template) -> int:
    """Read backwards from 126; return the first free trailing slot.

    `read(number)` is supplied by the caller. It raises on a failed read,
    and append must abort rather than guess.
    """
```

- `init_record` truncates to `PROGRAM_BYTES`, copies the bytes, and calls
  `messages.encode_name(..., INIT_NAME, NAME_BIT_OFFSET)`. It changes no
  other byte.
- `is_init` compares the whole record, not just the name. A user program
  that happens to be called `Init` but has different parameters is not
  free.
- `append_start` returns `0` when every slot `000`–`126` is Init, `127`
  when the highest slot is not Init, and `highest_non_init + 1` otherwise.
  It reads from `126` downwards, so a full bank costs one read.
- A failed read propagates; the caller reports it and writes nothing.

### 4.4 Planner: `nano/importplan.py`

Add:

```python
def plan_init(template: bytes) -> ImportPlan:
    """One Init step for every User slot 000-126."""


def plan_append(bank, targets: Iterable[int]) -> ImportPlan:
    """Source programs in file order into the supplied free targets."""
```

- `plan_init` builds 127 steps, `source_label="Init program"`, and no
  skipped records. It must reuse the existing `_step` / `_assemble`
  validation so a bad template is refused before a port opens.
- `plan_append` validates that targets are unique, ascending, and inside
  `000`–`126`. It walks `bank.programs` in `SourceProgram.index` order
  (file order), skips source `127` with the existing sentence, and pairs
  each remaining program with the next target. Programs beyond the target
  list go into `skipped` as e.g.
  `source 005 "Ballad Pno" is cut; no free slot`.
- `plan_append` does **not** raise merely because the file overflows; the
  screen needs the cut list. It raises only for an invalid target list.
  The caller refuses an empty step list.
- Add both names to `__all__`.

### 4.5 CLI: `nanocli init-bank`

- Add `init-bank` to the parser with the usual write flags
  (`--allow-write`, `--yes`) and `--dry-run` if cheap.
- The command reads User `127`, builds `init_record`, plans `000`–`126`,
  prints the range and count, then calls `writing.run(..., read_first=True)`.
  It prints the same read/backup/store/verify lines as `send`/`import`.
- It never plans `127`.
- Exit `1` if any slot fails to read, back up, store or verify; `0` when
  all 127 agree. A failed destination read leaves that slot untouched and
  is named in the summary.
- `--dry-run` reads the destinations and prints the range, but stores
  nothing and does not need the gate.

### 4.6 Browser: `N` init bank

- Add `Binding("N", "init_bank", "Init bank")` and the legend hint
  `N init bank` (matching kwsed's `N`).
- New `nanosyned/initbank.py` with `InitBankScreen`, modelled on
  `WholeBankScreen`:
  - title: “Initialise the User bank”
  - text: programs `000`–`126` will be replaced with the unit's `Init`
    program; `127 Off` is untouched; every replaced slot is backed up
    first; one `z` can restore the batch.
  - gate line and `w` arm/lock.
  - `ctrl+s` asks twice. The second answer names the range and says that
    all 127 destinations will be read and backed up first.
  - `esc` cancels.
- The app's `action_init_bank` pushes the screen. On confirmation it
  checks the gate, busy state and exchange exactly like `_import_plan`.
- `_init_worker` is a thread worker:
  1. acquire `_busy_gate`/`_lock` and the exchange;
  2. read `127` (this is the only way to build the template safely);
  3. build `init_record` and `plan_init`;
  4. run the same per-step loop as `_import_worker`;
  5. release and hand the results to the main thread.
- Refactor `_import_worker`'s loop into `_run_plan_locked(plan, progress,
  cancel)` so init and import share one store/verify/undo path. Do not
  duplicate `_import_one_step`.
- On success/partial success, reuse `_import_done` (with an “init” label):
  set live names for every agreed slot to `Init`, refresh favourite names,
  refill the User bank, and push one undo entry. `z` restores the batch
  newest first.
- Favourites are **not deleted** by init. Their names refresh to `Init`;
  the marks remain. Clearing marks is a separate destructive action and is
  not part of this request. The screen says this explicitly.
- A cancel stops before the next store; the summary reports how many were
  initialised and the undo entry covers only those.

### 4.7 Tests

- `init_record` changes only the name; size is 350; name decodes as `Init`.
- `plan_init` has 127 steps, targets `000`–`126`, no `127`.
- `is_init` accepts the exact template and rejects a same-name/different-
  bytes record.
- `append_start`: all Init -> 0; top non-Init -> 127; mixed bank -> after
  the highest non-Init; failed read propagates.
- CLI gate refusal; all 127 written; `127` untouched; read failure skips
  one slot; verify mismatch returns 1; dry-run writes nothing.
- TUI: locked gate refuses; two confirmations; cancel partial; undo
  restores; catalog live names become `Init`; favourites remain and their
  names refresh.
- Hardware check recorded in `docs/RESOLUTION_NOTES.md` once done.

### 4.8 Failure and cancellation matrix

| Event | Required behaviour |
|---|---|
| Template read (`127`) fails | Abort before any write; report the read failure; no progress screen is left claiming work started |
| Gate locked | Refuse on the main thread; no worker, no port, no backup |
| Busy / exchange unavailable | Refuse with the existing “busy” status; nothing sent |
| Destination read fails | Do not write that slot; continue with the others; name the slot and phase in the summary |
| Backup fails | Do not store that slot; continue; name the failed backup in the summary |
| Store raises | No read-back claim; report the failure; the backup remains the restore path |
| Read-back differs | Report `verify MISMATCH`; do not update the live name for that slot; keep the backup path |
| Cancel requested | Finish the current slot, start no next slot, report how many agreed, push an undo entry for the agreed slots only |
| Partial init | Untouched slots keep their bytes; `z` restores the agreed slots newest first; `Z` still undoes the session |
| Power loss / process death | No automatic resume; each completed slot has its backup file; the next launch does not assert an init happened |
| Template wrong size or invalid | Refuse in `init_record`/`plan_init` before the port; no write |
| User asks for `127` | Refuse; `127` is never a destination, including via a hand-built plan |

Cancellation is cooperative for the same reason as import: the current
MIDI exchange is allowed to finish, and the next one is not started. A
cancelled init is a partial init, not a rollback; the backup and undo log
are what make it recoverable.

### 4.9 Task cards (feature 2)

| id | task | files | depends | done when |
|---|---|---|---|---|
| I0 | Bench-verify the `127 Off` candidate: silent, accepted, read-back identical; record digest and firmware | docs only | none | §4.2 decision recorded; candidate approved or rejected |
| I1 | `nano/initbank.py`: `INIT_NAME`, `init_record`, `is_init`, `append_start` | new core module, tests | I0 for enabling; pure code can start earlier | template changes only the name; equality is whole-record; scan reads backwards |
| I2 | `importplan.plan_init`: 127 steps `000`–`126` | `nano/importplan.py`, tests | I1 | no `127`; bad template refused; plan is pure |
| I3 | CLI `nanocli init-bank`: gate, read template, plan, `writing.run`, summary | `nanosyned/cli.py`, tests | I1, I2 | all 127 verified; one failure returns 1; dry-run writes nothing |
| I4 | Extract `_run_plan_locked` from `_import_worker`; add `_init_worker` | `nanosyned/app.py`, tests | I2 | init and import share one store/verify loop; no duplication |
| I5 | `InitBankScreen` with two confirmations, gate and range copy | `nanosyned/initbank.py`, tests | I4 | locked gate refuses; cancel writes nothing; second answer names `000`–`126` |
| I6 | Catalog, favourites and undo integration | `nanosyned/app.py`, tests | I4 | agreed slots become `Init`; favourite names refresh; one batch `z` restores |
| I7 | Key `N`, legend, help, README, resolution note | `nanosyned/app.py`, docs, tests | I5 | `N init bank` appears everywhere; conformance/legend pass |
| I8 | Optional `--template FILE` / injected template seam | CLI/app tests | I1 | a verified dump can be used without the `127` candidate; default remains gated |

I0 is deliberately first. I1–I2 can be written and unit-tested offline
before the bench result, but the browser action must stay unavailable until
I0 passes. If I0 fails, I8 becomes the only supported path and I5/I6 are
not enabled for the built-in template.

### 4.10 Acceptance criteria (feature 2)

- `N` is refused while the gate is locked; arming the gate is explicit.
- The screen says exactly: `000`–`126` replaced, `127 Off` untouched,
  backups first, one `z` restores the batch.
- The second confirmation cannot be reached without the first.
- Exactly 127 targets are planned; `127` appears in no plan step.
- The template is the verified one; an unverified candidate is not wired to
  the default action.
- Every slot is read, backed up, stored and read back through the existing
  fence; a failure is named, not hidden.
- A successful init updates live names to `Init`, refreshes favourite
  names, keeps the marks, and pushes one undo entry.
- A cancelled init reports a partial result and leaves an undo entry for
  the slots that agreed.
- No sector/flash opcode is sent.
- `nanocli init-bank` obeys the same gate and reports the same phases.
- The hardware result and template digest are in the resolution notes.

### 4.11 What init does to favourites

A favourite is **not part of the bank**. It is a local SQLite row holding
`bank_id`, `number`, `name`, `rating`, `tags`, `note`, `added` and an
`active` flag. Init replaces program bytes; it does not touch that row.
The decision is what the app should do to the row after a slot becomes
`Init`.

There are three states, not two:

| Choice | What happens | Pros | Cons |
|---|---|---|---|
| **Keep active** | The row stays `active = 1`; the slot still shows a heart and appears in `F` views | Nothing is hidden; undo needs no favourites handling | A bank that was just “emptied” still looks full of favourites; every mark points at `Init`, not at a program; the user must clean them by hand |
| **Deactivate / dormant** | `Favorites.remove("USER", n)` for every verified slot; the row stays, `active = 0` | The bank looks empty; ratings, tags, notes and the added date survive; `f` on the slot later restores them through the existing `toggle()` path | Re-favouriting a new program in that slot inherits the old annotations; `z` restoring the programs does not automatically reactivate the marks |
| **Erase** | `Favorites.forget("USER", n)` deletes the row | Truly “clear everything”; no dormant data | Irreversible loss of ratings, tags and notes; no keystroke should reach this by accident |

**Recommendation: deactivate the marks for the slots init actually
verified.**

Why:

- It matches the meaning of “empty the User bank”: the favourite views and
  the bank counts drop to zero instead of showing 127 `Init` slots.
- It preserves the only data that cannot be reconstructed from the unit:
  ratings, tags, notes and when the favourite was made.
- It uses the library's existing safety split: `remove()` is the ordinary
  “unfavourite” and keeps the row; `forget()` is the deliberate deletion.
  The browser's `f` already uses `toggle()`, which restores a dormant row's
  annotations when the slot is favourited again.
- It is reversible at the row level even after init: the user can
  re-favourite a slot and get the annotations back.

Rules for the deactivation:

1. Run it **after** the write results are known, never before the plan is
   confirmed.
2. Deactivate only slots whose result is `stage == "verified"`. A failed
   or cancelled slot keeps its active mark.
3. Apply it only to `USER` numbers `000`–`126`. Leave `127` alone if init
   did not write it, and leave every other bank alone.
4. If there is no favourites store, skip the step silently.
5. Refresh names after the deactivation, as the normal import path does;
   a dormant row's name may become `Init`, but its rating/tags/note remain.
6. The init summary says: “Favourite marks on the initialised slots are
   hidden; ratings, tags and notes are kept and return if you re-favourite.”
7. Do **not** call `forget()` from the init path. If a separate “erase the
   User favourites completely” action is ever wanted, it needs its own
   explicit confirmation and a database backup first.

**Undo caveat.** `z` restores program bytes from the per-slot backups; it
does not automatically reactivate the dormant favourite rows. That is
acceptable because the annotations are still there and re-favouriting
restores them, but the init summary should say so. If automatic
reactivation is wanted, the init batch would need to record the affected
keys and `z` would need a favourites hook; that is a separate enhancement,
not a prerequisite.

**Do not choose “erase” just because the word is “clear”.** “Clear the
User bank” normally means the programs, not the user's annotations. The
safe reading is: hide the marks, keep the work behind them.

## 5. Feature 3 — append import

### 5.1 Import mode

Add a third mode in `nanosyned/importflow.py`:

```python
APPEND = "append"
IMPORT_MODES = (
    (WHOLE_BANK, "Whole bank"),
    (APPEND, "Append to free slots"),
    (SINGLE, "Single / multiple programs"),
)
```

`run_import_flow` gains an `open_append` seam, passed through
`_ask_after_read` and `_ask_mode`. `action_import` passes
`open_append=self._open_append`. The picker and source-bank question are
unchanged.

Append is **programs only**. Effects, mixes and global records in the file
are ignored with a note; the file produced by feature 1 contains only
programs.

### 5.2 Destination scan

The free-slot question depends on the unit, so it is read in a worker, not
in a screen:

1. Read User `127` and build the Init template.
2. `start = initbank.append_start(lambda n: writing.read_record(device,
   "program", n), template)`.
3. The free targets are `range(start, 127)`. `start == 127` means no free
   slots.
4. Build `plan = importplan.plan_append(bank, targets)`.
5. Push `AppendBankScreen(bank, plan, start, gate, catalog)` on the main
   thread.

The scan reuses the exchange/busy gate and a progress screen. A failed
read aborts before the append screen and writes nothing.

### 5.3 `nanosyned/appendbank.py`

The screen is modelled on `WholeBankScreen`, with these differences:

- Columns: source `#`, source name, target (`---` when cut), state.
  Targets are free slots, so state reads `free (Init)`; cut rows read
  `cut`.
- Summary: `N source program(s); M free slot(s) (START-126); K cut`.
- If `K > 0`, a red warning lists the cut programs by source slot and name
  (first few plus “and N more”). The user is told the two choices:
  - `ctrl+s` — “load M and cut K”
  - `s` — “choose single/multiple programs”
- If `M == 0`, `ctrl+s` refuses with “no free slots; run N init bank or
  choose single/multiple”; `s` still opens the picker.
- `w` arms/locks the gate; `esc` cancels.
- `ctrl+s` asks twice. The first answer repeats the count and the cut
  count. The second answer lists each `target <- source name` and says
  that the current Init placeholders are backed up first. It must not call
  the free slots “existing presets”.
- `s` dismisses with a `MANUAL` sentinel; the app's `done` callback opens
  the existing `SingleMappingScreen` for the same source bank. The picker
  can overwrite, but that is now an explicit manual choice.
- The screen holds no device and starts no worker; it only renders a plan
  built by the app.

### 5.4 Worker and undo

Append uses `_import_plan` unchanged: the gate is checked on the main
thread, the progress screen is pushed, and `_import_worker` reads each
destination, backs it up, stores and verifies. Because every target is an
Init slot, the backups are the Init records; `z` restores them as one
batch. The existing `_import_done` updates live names and refreshes
favourites.

The plan's `skipped` entries are shown on the append screen before the
write; the import summary does not need to repeat every cut name.

### 5.5 CLI: `nanocli import FILE --append`

- `--append` is an alternative to `--all` and `--program`; make them
  mutually exclusive. It is programs only, so `--effects`, `--mixes` and
  `--global` are refused with it.
- After selecting the source bank, read User `127`, scan for the append
  start, and build `plan_append` with `range(start, 127)`.
- If `plan` has no steps because there are no free slots, exit `2` with
  “no free slots; run `nanocli init-bank` or use `--program`”.
- If the file overflows and `--cut` is absent, print the cut list and exit
  `2`; do not write. `--cut` means “write the first N and drop the rest”,
  exactly the screen's “load anyway”.
- `--dry-run` prints the assignments and cut list without storing.
- A real write needs `--allow-write` and `--yes`.
- Refactor `_cmd_import` so the append plan can be built after the device
  is open. The existing whole-bank/single path stays where it is; only the
  append branch needs the destination scan.

### 5.6 Tests

- `plan_append`: file order, target order, cut list, skip source `127`,
  duplicate/out-of-range target refusal, empty targets, more targets than
  sources.
- `append_start` as in §4.7.
- Append screen: fits; overflow with cut names; `ctrl+s` truncates;
  `s` returns `MANUAL`; `M == 0`; locked gate; cancel.
- End-to-end on the demo: init the bank, export a handful of favourites,
  append the file, assert targets `000...`, old names `Init`, read-back
  names, and one undo entry.
- CLI: `--append` gate; overflow without `--cut` exits 2; `--cut` writes
  only the first N; `--dry-run`; no free slots; incompatible flags.
- Flow: `APPEND` appears in `IMPORT_MODES`; `open_append` receives the
  selected bank; cancel at the mode question builds no plan.

## 6. Keys, legend, help and docs

- `E export favourites` and `N init bank` go into `WRITE_HINTS` (or a new
  `TOOL_HINTS` passed to `keys.legend`), because they are this tool's own
  keys, not the family's.
- Update `KEY_HINTS`, the `?` help text, and `README.md`'s browser table.
- `tests/test_legend.py` derives extras from `KEY_HINTS`; its position and
  vocabulary checks must still pass.
- `tests/test_favorites.py` checks that every binding appears in the
  legend; `tests/test_conformance.py` checks the family's keys and the
  extras. Both need the two new hints.
- Document the append/free-slot rule in `README.md` and in
  `docs/RESOLUTION_NOTES.md`; the latter should also record the hardware
  check from §4.2.
- Do not use `SECTOR_ERASE`, `SECTOR_WRITE` or a flash path for any of
  this. Init is 127 ordinary program stores through the existing fence.

## 7. File map

| File | Change |
|---|---|
| `nano/exporting.py` | new: favourite selection, reads, syx writing |
| `nano/initbank.py` | new: Init template, equality, append-start scan |
| `nano/importplan.py` | add `plan_init`, `plan_append`, exports |
| `nano/dumps.py` | unchanged unless `write_syx` belongs here; prefer `exporting.py` |
| `nanosyned/cli.py` | `dump favourites`, `init-bank`, `import --append` |
| `nanosyned/app.py` | `E`, `N`, append seam, workers, shared `_run_plan_locked`, help/legend |
| `nanosyned/importflow.py` | `APPEND` mode and `open_append` |
| `nanosyned/initbank.py` | new: `InitBankScreen` |
| `nanosyned/appendbank.py` | new: `AppendBankScreen` and `MANUAL` |
| `nanosyned/importprogress.py` | optional title/verb parameter, or a shared progress base |
| `tests/test_exporting.py` | new |
| `tests/test_initbank.py` | new |
| `tests/test_append.py` | new |
| `tests/test_importflow.py` | append mode/seam |
| `tests/test_importui.py` | append screen, init screen, export screen |
| `tests/test_cli_import.py` | append CLI |
| `tests/test_cli_write.py` | init CLI |
| `tests/test_cli_favorites.py` | export CLI |
| `tests/test_legend.py`, `tests/test_conformance.py`, `tests/test_favorites.py` | new hints |
| `README.md`, `docs/RESOLUTION_NOTES.md` | keys, commands, Init semantics, hardware result |

## 8. Order of work (init first)

1. **I0** — bench-verify the `127 Off` candidate. This is the first action;
   everything else in init waits on it. While the bench session is being
   arranged, E1–E2 and A1 can be developed because they do not write.
2. **I1–I2** — init core and planner; offline unit tests.
3. **I3** — `nanocli init-bank`, using the verified template.
4. **I4–I6** — extract `_run_plan_locked`, add `_init_worker`,
   `InitBankScreen`, catalog/favourites/undo integration.
5. **E1–E2** — export core and CLI. Independent, fully offline-testable.
6. **A1** — `plan_append` pure planner and tests. Can start before I0,
   because it only needs a template parameter.
7. **A2–A3** — append scan, screen, flow seam and worker path.
8. **E3** — export browser action and progress.
9. **A4** — append CLI.
10. **Docs, legend, conformance, full suite, hardware opt-in check.**

If only one feature is shipped, ship I0 + I1–I6. Export and append are
useful without init, but append's free-slot rule has no reliable meaning
until init exists.

Suggested commits: `init bank template gate`, `init bank core`, `init bank
cli`, `init bank ui`, `export favourites`, `append planner`, `append ui`,
`append cli`, `docs and keys`. Keep the hardware-check result in its own
note so a failed check does not look like a code regression.

## 9. Test matrix (acceptance)

| Area | Must pass |
|---|---|
| Export selection | active USER favourites only; sorted; `127` excluded; non-User ignored |
| Export bytes | file parses; 350-byte records; original numbers; exact round-trip |
| Export failure | one failed read -> no file; cancel -> no file; existing path refused |
| Export UI | `E`, path prompt, overwrite question, progress, cancel, busy refusal |
| Init hardware | `127 Off` candidate silent, accepted, read-back identical; digest recorded |
| Init template | name `Init`; only the name changed; 350 bytes; exact equality |
| Init plan | 127 steps `000`–`126`; no `127`; gate; two answers |
| Init UI copy | range, `127` untouched, backups, one `z`; second answer names the range |
| Init failure | template read abort; destination read/backup/store/verify failure named; no false success |
| Init cancel | partial result; undo entry for agreed slots only; no automatic resume |
| Init execution | read/backup/store/verify; partial failure; undo; names refresh; favourites kept |
| Init CLI | `init-bank` gate; all 127; `127` untouched; failure exit 1; dry-run writes nothing |
| Append planner | file order; free targets; cut names; skip `127`; invalid targets refused |
| Append scan | all Init -> 0; full -> 127; mixed -> after highest; read failure aborts |
| Append UI | fits; overflow cut list; `ctrl+s` cuts; `s` manual; zero free; gate; cancel |
| Append CLI | `--append`; `--cut`; `--dry-run`; gate; incompatible flags |
| End-to-end | export -> init -> append -> names/undo; no `127` write |
| Static | ruff, format, mypy; no new coverage plugin assumptions |

## 10. Open decisions for the user

**Init decisions — answer these first**

1. **Init template:** approve the `127 Off` record (renamed `Init`) as the
   candidate, subject to the §4.2 hardware check? If the copy is not
   silent, do you have a known Init dump to use as the template?
2. **Init fallback:** if the candidate fails, should init stay behind
   `--template FILE` (recommended), or should the feature be held until a
   verified record can be embedded?
3. **Favourites after init:** deactivate the marks for verified slots,
   keeping ratings/tags/notes dormant (recommended — see §4.11); keep them
   active on `Init` slots; or erase them with `forget()` after an explicit
   backup and confirmation?
4. **Init confirmation shape:** is “all 127 programs `000`–`126`” enough,
   or must the second confirmation list every slot name? The plan
   recommends the range plus count, because 127 names do not fit the
   dialog and the backups are per slot.

**Supporting-feature decisions**

5. **Append placement:** after the highest non-Init slot, leaving earlier
   gaps for the single picker (recommended), or fill the lowest free gaps
   first?
6. **Export path UI:** a one-line path prompt with a sensible default
   (recommended, smallest change), or a new save-file picker screen?
7. **CLI scope:** include all three commands in the first pass
   (recommended), or ship the browser first and add CLI parity later?

Until 1 is answered on hardware, feature 2 must not write an invented
record into 127 slots.
