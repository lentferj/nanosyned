<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# PROMPT-PARITY — bringing nanosyned en-par with the family

This is the working prompt for the parity effort. It is written to be handed
to a fresh agent (or a human) as the complete brief: it records what was
inspected, what the gap is, the design decisions that are already settled, and
a breakdown of the implementation into small, atomic, independently
verifiable tasks, each with the free model best suited to it.

The four deep audits it is built on were produced for this effort and are
reproduced here in condensed form; the raw evidence lives beside this file:

- `docs/audit/findings-rxved.md`
- `docs/audit/findings-p2ked.md`
- `docs/audit/findings-emorphed.md`
- `docs/audit/findings-vinsynlib.md`
- `docs/audit/writepath-p2ked.md`
- `docs/audit/writepath-emorphed-rxved.md`

---

## 1. Scope, as decided

**Full parity, including the write path.** nanosyned must reach the family's
current shape — vinsynlib 0.4.2 adoption, the shared UI/worker/undo/backup
seams, the UX features (ratings, UI-state, scan/rebuild, livenames, markup
escaping, refused styling), the tooling/CI/test tier, **and** an
arm-then-fire write path for the instrument's records (User programs, mixes,
effects, global). Read-only hardware verification is also permitted; writes
are permitted with backup-first and read-back verify.

Where the sibling's hardware differs, the *shape* ports and the *protocol*
does not: nanosyned keeps its own `nano/messages.py`, `nano/records.py`,
`nano/banks.py`, `nano/dumps.py`, and adds its own parameter tables from the
Alesis QS6/7/8/R specification.

### The three sources of truth, in order

1. **The instrument.** It is on the bench and free to use. Anything the
   siblings "prove" on E-MU/Roland hardware is only a pattern until this unit
   confirms it; `docs/RESOLUTION_NOTES.md` records which is which.
2. **The Alesis QS6/7/8/R System Exclusive specification** (published 1997-02-03).
   Authoritative for the message set and every parameter table. The
   NanoSynth is not named in it; it speaks the QS set and identifies as QS
   family member 7.
3. **The sibling projects** (`../rxved`, `../p2ked`, `../emorphed`) and
   **vinsynlib 0.4.2** — authoritative for *shape*, never for wire bytes.

---

## 2. What was inspected

| artifact | lines / count | note |
|---|---|---|
| nanosyned `nano/` + `nanosyned/` | ~4 000 | 11 modules, 10 CLI commands, 1 screen |
| nanosyned tests | 129 | read path only |
| rxved | ~15 900 | 3031-line app, 1418-line CLI, 2539-line screens, 631 tests |
| p2ked | ~13 200 | multi/master/FX editors, scan, backup, ~700 tests |
| emorphed | ~9 400 | midimap editor, 438 tests, CI, screenshots |
| vinsynlib | ~6 900 | 0.4.2; 20 modules incl. `ui/*`, `undo`, `backup`, `build`, `livenames`, `render` |

The installed vinsynlib in `nanosyned/.venv` was **0.4.1** and lacked
`vinsynlib.build`; the branch installs the sibling working copy (0.4.2)
editable, which is the documented development path.

---

## 3. The gap, in seven groups

### 3.1 vinsynlib floor and reimplemented widgets

nanosyned pins `vinsynlib>=0.3.1` (`pyproject.toml:11`) but gates at
`MINIMUM = (0, 2, 0)` / `SOURCE = "vinsynlib>=0.2.0"`
(`nanosyned/entry.py:41,44`) — the two disagree, and both lag the siblings'
coherent `>= 0.4.2`. It reimplements the library's `ReportScreen`
(`app.py:113`), `PromptScreen` (`app.py:145`), `render.table` (`cli.py:44`)
and a whole `catalog` fork (`nano/catalog.py`), and uses none of `undo`,
`backup`, `build`, `livenames`, `ui.confirm`, `ui.modals`, `ui.work`.

### 3.2 Structural drift

All modals live in `app.py`; there is no `screens.py`, no `text.py`, no
`Device` Protocol; worker errors use bare `except Exception`; the busy
discipline is a boolean + `RLock` rather than `BusyGate`/`close_when_idle`;
refusals are a text prefix, not the family's red `.refused` bar; the key
hints are hand-written and the KeyHints footer-height fix is absent.

### 3.3 Read-tier UX gaps

No ratings (though the schema has the column); no UI-state restore; no
scan/rebuild or startup scan offer; names read off the unit are never
persisted (`livenames`) and never refresh favourite rows; no column-scoped
search; the `f`/`F` shift-pair the family moved off; no build/about line;
`i` is not busy-guarded; no sweep announcement and `--port` runs never save
the pair.

### 3.4 The write path is absent

nanosyned reads and selects. The family shape is: a locked-by-default
`EditGate`, an `UndoLog` on one timeline, a pre-write backup taken
unconditionally, read-back verification that names what did not match, and
arm-then-fire modals (never one keystroke). The Alesis protocol supports it:
opcode `00` User Program Dump stores a user program, `06` effects, `0E` mix,
`0A` global, `10` direct parameter edit (function/page/pot), `0D` mode select.

### 3.5 Tooling gaps

No CI; Makefile lacks `install`, `format-check`, `coverage`, `test-hardware`,
`ci`, `pre-commit-run`, `clean`, `secrets-update`; no `tools/measure_send_gap.py`
(the exact tool for `TODO.md` item 1), no `import_favourites.py`, no
`capture_screenshots.py`; `extract_catalog.py` is untested; pre-commit lacks
`--exit-non-zero-on-fix`.

### 3.6 Test gaps

129 tests, read path only. Missing: `test_no_sound`, `test_legend`,
`test_remembered_state`, `test_catalog`, `test_livenames`, `test_backup`,
`test_scan`, `test_modal_ux`, `test_markup_crash`, a hardware suite, CLI
conformance, and any write/edit tests — against the siblings' 400–700 each.

### 3.7 Docs gaps

README misses the command-line table, backups, bench/hardware, honest-limits
and screenshots sections, and still carries the doubled `---` and the
missing-subject " is provided **as is**" defects the siblings fixed; no
`docs/CHECKS.md`; no `.opencode/commands/review.md`.

---

## 4. Invariants that must survive (from CLAUDE.md and the audits)

These are not style. A task that breaks one is wrong even if `make check` is green.

1. **Cursor movement sends nothing.** `select()` is bound to Enter and nothing
   else; enforced by `tests/test_app.py::TestCursorIsSilent` and the new
   `test_no_sound.py`.
2. **Only the User bank can be read.** The other four are ROM and have no
   request. Five banks, one dump request.
3. **Everything sent comes back** (soft thru) — match replies by opcode *and*
   object number, never by "an Alesis message arrived".
4. **The unit will not answer an Identity Request on its own** — `identify()`
   prompts with a Global Dump Request; `autodetect()` probes with one.
5. **Bank Select is Controller 0 only.** Controller 32 is ignored; no helper
   sends both.
6. **`number` and `program_change` stay separate attributes.** No conversion
   helper.
7. **Workers do MIDI and nothing else**; the favourites store is SQLite and
   refuses cross-thread use; `_busy`/gate is set on the thread that checks it.
8. **User program 127 is hardwired silent** and a write must refuse it.
9. **Alesis's names are never committed**; the catalog is generated and
   gitignored; fixtures and demo names are invented.
10. **Only one session drives the synth.** Develop and test the cursor
    synthetically; hardware tests are opt-in and never run concurrently.

The siblings' write-path rules also apply verbatim: **never write without a
backup read first** (a store that cannot be undone is not performed); **say
what is about to be destroyed, by name**; **verify by reading back and report
what did not match**; **arm-then-fire, never one keystroke, and moving the
cursor disarms**.

---

## 5. Design decisions, settled

- **Adopt the library wherever it owns the behaviour.** Delete
  `nano/catalog.py`'s fork, `app.ReportScreen`, `app.PromptScreen`,
  `cli._table`; bind `backup`, `livenames`, `undo`, `build`, `render`, the
  `ui/*` widgets and the full `config` API.
- **Keep project-side:** bank table, wire messages, record sizes, the
  parameter tables, the catalog's *disagreement* semantics, the demo device,
  and the NanoSynth-specific `identify`/`autodetect` policy.
- **Catalog key grammar.** vinsynlib keys on the **display** number
  (`BANK:NNN`). On this instrument `number == program_change`, so the offset
  is `0`; the binding passes `offset=0` to `wire_to_display` and the
  generated JSON keeps writing `"pc"` rows (converted at the edge). The
  project-only `disagreement()` moves to a small `nano/names.py` helper or
  stays as a function beside the catalog binding.
- **Write path scope.** Whole-record writes plus the full parameter tables
  the spec publishes (program common/name, global 19 bytes, mix 138 bytes,
  effects 65 bytes) and the `10` direct-edit message. The editor is
  table-driven: one `nano/params.py` of frozen parameter descriptors keyed by
  (mode, function, page, pot) with ranges and choices, exactly the p2ked
  `MasterParameter`/`MASTER_BY_ID` shape.
- **One write as a service.** `NanoBridge.write_*` sends and does **not**
  verify (p2ked's rule); the app owns gate + log + read-back verify; a write
  that does not read back is not logged and so not undoable.
- **Backup once per session per kind**, taken on the worker before the first
  write, announced by filename; a failed backup aborts the write.

---

## 6. Atomic tasks

Format: `id — title — files owned — depends — model — done when`.
Model ids are the free tier, except the review which uses the requested
`opencode-go/glm-5.3-flash`.

Free models used below: `opencode/glm-5.3-flash-free` (G),
`opencode/deepseek-v4.1-flash-free` (D),
`opencode/nemotron-3.5-lightning-free` (N, fast/mechanical),
`opencode/longcat-2.5-preview-free` (L, docs/mechanical),
`opencode/beam-free` (B, docs).

### P0 — environment and gate

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T0.1 | branch + vinsynlib 0.4.2 editable + green baseline | — | — | *(done by orchestrator)* | `parity` branch, 129 pass |
| T0.2 | align version gate to 0.4.2 (entry/pyproject/tests) | `nanosyned/entry.py`, `pyproject.toml`, `tests/test_entry.py` | T0.1 | N | gate and pin both say 0.4.2; `test_version_gate_copy` passes |

### P1 — library adoption (no UI change yet)

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T1.1 | `nano/config.py`: export `UNSET` + ui-state + `config_dir` API | `nano/config.py` | T0.2 | N | names importable; tests pass |
| T1.2 | `nano/favorites.py`: re-export `rating_cell` | `nano/favorites.py` | — | N | import passes |
| T1.3 | replace `nano/catalog.py` fork with a vinsynlib binding (`offset=0`, keep `disagreement`) | `nano/catalog.py`, `tools/extract_catalog.py`, `tests/test_banks_dumps.py` | T0.2 | G | all catalog call-sites work; tests pass |
| T1.4 | `nano/backup.py` binding (kinds: program/mix/effects/global) | `nano/backup.py` (new) | T0.2 | D | round-trips a block |
| T1.5 | `nano/livenames.py` binding (per-app path) | `nano/livenames.py` (new) | T1.3 | D | load/save/apply work |
| T1.6 | `nanosyned/text.py`: `literal()` + `test_markup_crash.py` | `nanosyned/text.py` (new), `tests/test_markup_crash.py` | — | D | markup in a name cannot crash a pane |
| T1.7 | `cli._table` → `vinsynlib.render.table`; progress → `render.progress` | `nanosyned/cli.py` | — | N | CLI output matches family |

### P2 — structure and shared UI seams

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T2.1 | split `screens.py` out of `app.py`; adopt `ui.report`/`ui.prompt`/`ui.confirm`/`ui.modals`; `text.literal` everywhere | `nanosyned/screens.py` (new), `nanosyned/app.py` | T1.6 | G | no local modal classes; markup-proof |
| T2.2 | `nano/device.py` `Device` Protocol; demo + bridge conform | `nano/device.py` (new), `nanosyned/demo.py`, `nano/bridge.py` | T2.1 | G | demo no longer lies about closed port |
| T2.3 | refused red `.refused` class bar (CSS + `notify_status`) | `nanosyned/app.py` | T2.1 | N | refusals render red |
| T2.4 | `keys.legend` built from bindings; `F`→`v` swap; conformance update | `nanosyned/app.py`, `tests/test_conformance.py` | T2.1 | D | legend + keymap match family |
| T2.5 | `BusyGate` + `close_when_idle` + `_BRIDGE_ERRORS`; busy-guard `i` | `nanosyned/app.py` | T2.1 | G | no overlapping exchanges; shutdown safe |
| T2.6 | KeyHints footer-height subclass | `nanosyned/screens.py` | T2.1 | N | footer re-lays out on rewrap |
| T2.7 | `build.build_of` about/help line; `--version` names vinsynlib | `nanosyned/app.py`, `nanosyned/cli.py` | T2.1 | N | help shows both builds |

### P3 — read-tier UX

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T3.1 | UI-state persistence (bank/cursor/view/filters/scan-dismissal) + unchanged-bank guard | `nanosyned/app.py`, `nano/config.py` | T1.1,T2.1 | G | restart restores position |
| T3.2 | ratings: `*` set, `V` filter, column, persistence | `nanosyned/app.py`, `nanosyned/screens.py`, `nanosyned/cli.py` | T3.1 | G | rate + filter round-trip |
| T3.3 | livenames: load on boot, save on read, `favorites.refresh_names`, 3-state startup line | `nanosyned/app.py`, `nano/livenames.py` | T1.5,T2.1 | G | live names survive restart |
| T3.4 | scan/rebuild: `S`/`R`, ScanOffer + Scan screens, `catalog` knows/clear, `nanocli scan` | `nanosyned/scan.py` (new), `nanosyned/app.py`, `nanosyned/cli.py` | T3.3 | G | one action fills the catalog |
| T3.5 | column-scoped `SearchScreen` (names/tags/notes) | `nanosyned/app.py`, `nanosyned/screens.py` | T2.1 | D | search flags work |
| T3.6 | sweep announcement (`swept`/`probe_seconds`); save pair on `--port` path | `nano/bridge.py`, `nanosyned/app.py`, `nanosyned/cli.py` | — | D | slow launch says so |
| T3.7 | `nanocli fav`/`tags` (add/remove/rate/tags/note/search/order) | `nanosyned/cli.py` | T1.2,T1.7 | D | offline favourites management |

### P4 — write protocol and bridge

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T4.1 | message encoders: `program_dump`,`effects_dump`,`mix_dump`,`global_dump`,`midi_edit`,`mode_select`; `frame` body + tests | `nano/messages.py`, `tests/test_messages.py` | — | G | each frame round-trips through `parse` |
| T4.2 | `nano/params.py`: frozen parameter descriptors from the QS spec (global, mix, effects, program common); `nano/records.py` encode/decode | `nano/params.py` (new), `nano/records.py` | T4.1 | D | table lookups + byte-exact round-trip |
| T4.3 | bridge write methods `write_program/effects/mix/global/midi_edit` (send only) + demo mirrors | `nano/bridge.py`, `nanosyned/demo.py` | T4.1,T2.2 | G | demo models stores/scratch |
| T4.4 | read-back verify: unchanged-and-recompare; report mismatches | `nano/bridge.py` | T4.3 | D | a wrong write is named |
| T4.5 | `EditGate` + `UndoLog` + pre-write backup wiring; `w` gate key; `--allow-write` | `nanosyned/app.py`, `nano/backup.py`, `nanosyned/cli.py` | T1.4,T2.5,T4.4 | G | locked writes refused; undo works |

### P5 — write UI

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T5.1 | program editor: name + common/sound params, arm-then-fire store, verify | `nanosyned/editor.py` (new), `nanosyned/app.py` | T4.5 | G | edit → store → read back |
| T5.2 | mix pane (`m`): 16 channels, program/volume/pan, edit + `0D` mode select | `nanosyned/mix.py` (new), `nanosyned/app.py` | T4.5 | G | channel edit round-trips |
| T5.3 | effects editor (`x`) | `nanosyned/editor.py`, `nanosyned/app.py` | T5.1 | D | effects edit round-trips |
| T5.4 | global editor | `nanosyned/editor.py`, `nanosyned/app.py` | T5.1 | D | global edit round-trips |
| T5.5 | CLI `send`/`dump`/`set`/`backup` (+ `--yes`, `--allow-write`) | `nanosyned/cli.py` | T4.5 | D | scripted write with confirmation |

### P6 — tooling, CI, hardware

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T6.1 | `tools/measure_send_gap.py`; measure `SEND_GAP`/`SELECT_GAP` on the unit; update `bridge.py` + `RESOLUTION_NOTES.md` | `tools/measure_send_gap.py` (new), `nano/bridge.py`, `docs/RESOLUTION_NOTES.md` | T0.1 | D | measured values recorded |
| T6.2 | `tools/import_favourites.py` (marked-up listing → DB) | `tools/import_favourites.py` (new) | T1.2 | D | imports a sample listing |
| T6.3 | `tools/capture_screenshots.py` + README screenshots | `tools/capture_screenshots.py` (new), `docs/screenshots/` | T3.* | D | shots reproduce |
| T6.4 | tests for `tools/extract_catalog.py` + invented fixture | `tests/test_extract.py`, `tests/fixtures/` | T1.3 | D | extractor covered |
| T6.5 | `tests/conftest.py` + `tests/test_hardware.py` + `make test-hardware` | `tests/conftest.py`, `tests/test_hardware.py`, `Makefile` | T4.* | G | opt-in suite runs on the unit |
| T6.6 | Makefile targets: `install`,`format-check`,`coverage`,`test-hardware`,`ci`,`pre-commit-run`,`clean`,`secrets-update` | `Makefile` | — | N | targets work |
| T6.7 | `.github/workflows/ci.yml` + `.opencode/commands/review.md` | `.github/`, `.opencode/commands/review.md` | T6.6 | L | CI mirrors `make check` |
| T6.8 | `docs/CHECKS.md` | `docs/CHECKS.md` (new) | — | B | the check ledger exists |
| T6.9 | strict-mypy expansion + `typecheck-strict` | `pyproject.toml`, `Makefile` | T2.* | D | strict count recorded |

### P7 — tests

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T7.1 | `test_no_sound.py`: reads emit only SysEx; `select` sole audible site | `tests/test_no_sound.py` | T2.5 | D | enforced structurally + on a recording port |
| T7.2 | `test_legend.py`: wrap never truncates; workers only MIDI; pathless config | `tests/test_legend.py` | T2.4 | D | family properties pinned |
| T7.3 | `test_remembered_state.py` | `tests/test_remembered_state.py` | T3.1 | D | ui-state round-trips |
| T7.4 | `test_catalog.py`, `test_livenames.py` | `tests/test_catalog.py`, `tests/test_livenames.py` | T1.3,T1.5 | D | both layers covered |
| T7.5 | `test_backup.py` (envelope, never-overwrite, corrupt-listed, offline list) | `tests/test_backup.py` | T1.4 | D | covered |
| T7.6 | `test_scan.py` (scope, ROM-vs-user keeping, offer lifecycle, cancel) | `tests/test_scan.py` | T3.4 | D | covered |
| T7.7 | `test_modal_ux.py` (dismiss/exit on every modal) | `tests/test_modal_ux.py` | T2.1 | D | covered |
| T7.8 | CLI conformance + `test_cli_favorites.py` | `tests/test_conformance.py`, `tests/test_cli_favorites.py` | T3.7 | D | both parsers checked |
| T7.9 | deepen `test_app`/`test_bridge`/`test_messages`/`test_connect` | `tests/*` | P4 | G | write paths covered |

### P8 — docs

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| T8.1 | README: command-line table, backups, bench, honest limits, screenshots, README defects | `README.md` | P5,P6 | L | README complete |
| T8.2 | CLAUDE.md/TODO.md/RESOLUTION_NOTES.md sync | `CLAUDE.md`, `TODO.md`, `docs/RESOLUTION_NOTES.md` | P5 | B | ledger consistent |
| T8.3 | DISCLAIMER.md + LICENSE third-party references | `DISCLAIMER.md`, `LICENSE` | P5 | B | attribution complete |

---

## 7. Verification protocol (every task)

1. `make lint` then `$(PY) -m pytest -q` — must be green before a task is
   called done. A task that leaves the tree red is not merged.
2. New behaviour gets a test in the same task or the immediately following
   test task; a feature without a test is unfinished.
3. Hardware checks (`make test-hardware`, `tools/measure_send_gap.py`) run
   **serially**, never two at once, and never while another session drives
   the unit. The demo path (`--demo`) is the synthetic stand-in everywhere.
4. `make check` is the gate for the whole branch before review.

## 8. Execution waves (parallelism)

- **Wave 1:** T0.2, T1.2 (independent, tiny).
- **Wave 2:** T1.1, T1.4, T1.6, T1.7 (distinct files).
- **Wave 3:** T1.3 (catalog; cross-cutting — serialise).
- **Wave 4:** T2.1 (app/screens refactor; serialise).
- **Wave 5:** T2.2, T2.3, T2.4, T2.6, T2.7, T1.5 (mostly distinct).
- **Wave 6:** T2.5, T3.1, T3.5, T3.6 (app/bridge — serialise app-touching).
- **Wave 7:** T3.2, T3.3, T3.4, T3.7 (app-touching serialised; T3.7 parallel).
- **Wave 8:** T4.1, T4.2 (protocol + params; parallel).
- **Wave 9:** T4.3 (bridge), then T4.4.
- **Wave 10:** T4.5, then T5.1–T5.5 app-touching serialised; T5.5 CLI parallel.
- **Wave 11:** T6.x, T7.x, T8.x (largely independent).

Where two tasks touch `nanosyned/app.py` they are serialised; tasks that own
disjoint files run concurrently as background subagents.

## 9. Review-and-fix loop

1. When `make check` is green on `parity`, run `/review branch` from
   `.opencode/commands/review.md` with **`opencode-go/glm-5.3-flash`**.
2. Take the review's findings verbatim; for each, write one atomic fix task
   in the same `id — title — files — dep — model — done when` shape, with the
   free model best suited to the fix.
3. Execute the fixes in dependency order, parallelising disjoint files, until
   the tree is green again; record anything the review found that could not
   be reproduced or fixed.
