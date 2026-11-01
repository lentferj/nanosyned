<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Parameter verification run log

- **Started:** 2026-10-31
- **Branch:** `param-verify` (from `master` @ `42c8e19`)
- **Plan:** `docs/PARAMETER_VERIFICATION_PLAN.md`
- **Hardware:** Alesis NanoSynth behind the XV-2020 chain,
  `Roland XV-2020:Roland XV-2020 MIDI 1 52:0`; Identify reports
  Alesis / QS / member 7 / version `0100`.
- **Backups:** `~/temp/nanosyned-backups/20261031-220708/edit-buffer.syx`
- **Manual:** `NanoSynth_Manual.pdf` (48 pp., 1998). Its text layer is
  partly mojibake; the MIDI chapter and chart were OCR'd.

## Baseline

`master` before the branch: 436 passed, 7 skipped. Wave 1 + V0 on the
branch: 502 passed, 7 skipped.

## What was already done before the bench

D01 per-tool config, D02 honest ledgers, D03 the `02` load encoder,
V01 `Param.verified`, V02 value laws, V04 the generated map, V03 the
probe harness. See the four commits on `param-verify`.

## Bench findings

### The manual documents no sysex, but says sysex is recognised

`NanoSynth_Manual.pdf` has no System Exclusive chapter. Its MIDI
Implementation Chart (printed p. 80; legend inverted, `X = YES`) marks
System Exclusive as transmitted **and recognised**. The QS6/7/8
implementation specification therefore remains the only message
reference, and it describes a full QS6, not the reduced firmware.

### `02` is a load, not a store — confirmed

A record with one name bit flipped was sent as `02 00`. The edit buffer
read back with the new name, and **no stored user slot carried it**
(all 128 `00` dumps were searched). The restore then put the original
back. So the probe's restore message is the right one.

### A 408-byte load needs ~0.4 s before the next request

Measured by loading a modified record and then reading it back with
gaps of 0.00, 0.05, 0.15, 0.40 and 0.80 s:

| gap | restore landed |
|---|---|
| 0.00 s | no |
| 0.05 s | no |
| 0.15 s | no |
| 0.40 s | yes |
| 0.80 s | yes |

`SEND_GAP = 0.000` is right for small messages and wrong for a
record-sized one: a 408-byte frame is ~130 ms on the wire before the
unit has even parsed it. This is almost certainly the pre-existing
`tests/test_hardware.py` restore failure, and it is why the first
one-row probe reported `no-change restored` — with nothing changed,
the restore "verified" trivially and proved nothing.

**Confirmed after the fix.** With `RECORD_GAP` in the write methods,
`tests/test_hardware.py::TestHardwareProgramWrite` now passes: user
program 0 renamed to `WRITETEST`, stored, read back identical across
all 350 bytes, then restored and verified. That test had been failing
on `master` before this branch. The unit's program 0 is back as found.

### `10` is honoured for Global, Mix and Program — but differently

Each mode was tested with a value that differs from the current one,
read from **its own record**, with a 0.4 s settle:

| mode | `10` lands? | record to read | restore |
|---|---|---|---|
| Global | **yes** | `0A` global dump | send the old value back with `10` (`0A` is a store) |
| Mix | **yes** | `0F 64` → `0E 64`, 138 bytes (edit buffer 100) | `0E 64` (`write_mix(100, ...)`) |
| Program in Program mode | **no** | `03 00` → `02 00` unchanged | — |
| Program in **Mix mode**, channel N | **yes** | `03 <N+1>` → `02 <N+1>` | `02 <N+1>` |
| Effects | **no** | `09` → `08`, 65 bytes, unchanged | — |

Evidence:

- Global "Pitch transpose" byte 1: `7 -> 3` after `10 00 00 02 03`, and
  `3 -> 7` after sending the old value back.
- Mix name digit 0 changed bits `[5, 11]`; a channel row changed
  `[87, 88]`. `write_mix(100, ...)` restored the buffer.
- Program name digit 0 in Mix mode changed edit buffer **1** at bits
  `[8, 10, 12, 13, 14]`; edit buffer 0 did not move. "Sound pitch
  semitone" changed `[115, 117]` — exactly the both-sounds address the
  table gives — and "Sound filter frequency" changed `[169, 170, 175]`.
  `02 01` restored it.
- Effects: the config row (function 2, page 0, pot 0) refused values
  0, 1 and 2 in both Program and Mix mode; the record never moved.
  A config-0 row also refused, which the spec's no-edit rule could
  explain, but the config row exists in **every** configuration.

### The Generated map's first run was a false positive

`tools/probe_params.py --mode global --limit 1` on the unit reported
`no-change restored`. Both halves were misleading: Global `10` was
being applied to the global record, which the harness never read, and
"restored" was trivially true because nothing had changed. The harness
needs a positive control: modify one bit, load it, prove it moved, then
restore.

## What this means for the plan

1. **The harness must read and restore the right buffer per mode**, not
   always the program edit buffer:
   - Global: `read_global`; restore each edited row by `10` with its
     old value. Never send `0A` (it stores).
   - Mix: `read_mix(100)` / `write_mix(100, ...)`.
   - Program: put the unit in **Mix mode**, use channel 0, read
     `03 01` / restore `02 01`.
   - Effects: **cannot be verified** on this firmware as it stands;
     leave the table untouched and say so.
2. `mix_dump_request` and `read_mix` reject 100 even though the unit
   answers it and the spec names it as the edit buffer. Fix both.
3. Record loads need a post-write gap; `SEND_GAP = 0` is only for
   small messages.
4. **Program rows can only be verified in Mix mode**, which changes what
   "program mode" means in the editors: the same `10` works there, but
   the buffer is per-channel. The editor design must say which buffer it
   is editing.

## Unit state after the run

- Program edit buffer 0 (the unit's own program, not named here), digest
  `75b9a5bdf195`, restored.
- Program edit buffer 1 (the next channel's), digest `8fadd8b045f6`, restored
  after the sound tests.
- Mix edit buffer 100: restored (`bfceecee977b`).
- Effects edit buffer: config 3, restored (`b44e1d0bc16b`).
- Global: byte 1 back at 7; record restored (`56b9d94fcb91`).
- **No store (`00`) was ever sent.** No user slot changed.

## V05–V08 — the verification runs

Run with the corrected harness (per-mode buffers, positive control) on
2026-10-31/11-01:

| mode | rows probed | confirmed | other |
|---|---|---|---|
| Global | 17 | **10** | 7 no-change |
| Mix | 31 | **27** | 1 no-change, 1 mismatch, 1 partial |
| Program | 41 | **38** | 2 mismatch, 1 partial |
| Effects | 0 | 0 | blocked (the mode is inert) |

**75 rows confirmed in total.** The harness's control passed in every
mode after it learned to try several rows: the first mix row ("Mix
effect MIDI program change", a 1-bit switch) is ignored by the unit,
and the second ("Mix effect chan") is not. One silent row is not a dead
mode.

The non-confirmed rows are findings, and none was promoted:

- **Mix:** "Channel 1 program number" changed bits outside its 7-bit
  field (`mismatch`); "Channel 1 pitch octave" moved but read back
  something other than the value sent (`partial`); "Channel 1 program
  type" did not move (`no-change`).
- **Program:** "Keyboard / drum mode" and "Sample group" changed bits
  outside their fields (`mismatch`) -- the mode bit switches the whole
  sound table, which is the expected shape of that one; "Sample number"
  moved but did not read back the value sent (`partial`).
- **Global:** the seven no-change rows are the model-specific ones
  (`QS6,7,8 only`, `QSR only`) and General MIDI / A-D controller mode,
  which this firmware does not expose through `10`.

The stride spot check passed: "Sound pitch semitone" on **sound 2**
changed exactly its field at bit 795, and "Channel 1 volume" on
**channel 2** changed exactly its field at bit 156. The template rows
were probed on sound 1 / channel 1, and the fixed strides are real.

## V09/V10 — the multi-value and sibling-bit pass

Every promoted row was probed again at up to three values (its low, its
high, and a mid or signed one), each value diffed against the record
immediately before it, with every changed bit required to stay inside
the row's field and the field required to read back exactly what was
sent. 201 of 214 value probes matched.

The 13 that did not are all the same shape: on a signed field the unit
stores **one less than the documented top**.

| row | sent | read back |
|---|---|---|
| Channel 1 pitch semitone | 13 | 12 |
| Sound pitch semitone | 25 | 24 |
| Sound pitch detune and the other mod rows (11) | 100 | 99 |

The address and the value law are right -- every other value agrees --
but the documented top is not honoured: the specification's Limit is
one past the unit's top on these signed rows. The 13 were re-checked
at the corrected top and at their low and 0 (all 39 value probes
matched), then the table's `high` was set to the measured value -- 99
for the mod/detune rows, 12 for the mix semitone, 24 for the program
semitone -- and they were re-promoted.

## V11 — promotion

All **75 flip-confirmed rows** carry `verified=True` and the law the
probe showed: 10 Global `twos`, 27 Mix, 38 Program `raw`/`offset`. The
13 corrected tops above are part of that count; every one was re-probed
at its new top before promotion. Effects have none. The remaining 103
rows are still transcriptions and stay read-only in the editors.
`docs/PARAMETER_NUMBERS.md` is regenerated and shows the per-mode
counts.

## Review (`opencode-go/glm-5.3-flash`)

Verdict: **FIX-FIRST**. The findings were fixed on the branch and the
suite re-run:

- **HIGH** — a global row that moved bits *outside* its field could
  leave the record altered, because `run` raised before the final
  restore. It now attempts the mode's own restore before stopping and
  reports the leftover bits.
- **MEDIUM** — the positive control `continue`d past a row that moved
  but did not reach the target, leaving stray bits (persistently, for
  global). It now restores through `check_restore` before trying the
  next row.
- **MEDIUM** — an aborted run discarded the probes it had already
  proved, and never wrote `--json`. `ProbeAborted` now carries them and
  `main` reports them; exit `2` means only "nothing was probed".
- **MEDIUM** — the run log named two programs read off the unit.
  Replaced with the slot and digest.
- **LOW/NIT** — the run-level mismatch test was vacuous and now asserts
  the abort and a direct probe's verdict; the TODO body no longer says
  `set` sends any address; the `params` summary says "bench unit
  (2026-11-01)"; the plan's invariant 1 includes `0E` with number 100
  only; the `--backup-dir` help says `--all` backs up the first mode.

The review also confirmed the store ban (no `00`, `0A`, or `0E` < 100 on
the probe path), the 75 promoted rows against the three JSON files, the
generated map, and the record gap.

## Remaining

- The mismatch and partial rows need their addresses or widths re-read
  from the spec before anything is promoted.
- Effects stay unverified: the unit ignored every effects `10`.
- V14–V22: the CLI `params`/`param-get`, the TUI parameter editor, the
  extended mix editor, verified-only enforcement in the effects/global
  editors, the hardware parameter test, docs, review.

## State at the end of this pass

- **75 of 178 rows verified**: 10 Global, 27 Mix, 38 Program, 0 Effects.
  The other 103 are transcriptions and are read-only. The 13 signed
  rows whose spec Limit sat one past the unit's top now carry the
  measured top (99/12/24) and were re-probed there.
- The probe tool reads and restores each mode's own record, with a
  positive control that proves the `10` moved it and the restore brought
  it back. It never sends `00`, `0A`, or `0E` below 100.
- `nanocli params [MODE]` lists the table offline with the status and
  law; `nanocli set` refuses an unverified or unknown row, and reads its
  confirmation from the right buffer per mode.
- The effects editor no longer offers the ten deleted spares (their bytes
  stay in the record).
- `tests/test_hardware_params.py` probes one verified row per mode on
  the unit, behind `NANOSYNED_HW_PARAMS=1`.
- `make check` is green (547 passed, 8 skipped; ruff, mypy, vulture,
  deptry, detect-secrets, pip-audit clean).

**Open:**

- Re-transcribe the top of the 13 demoted signed fields (the unit stores
  limit - 1), then re-probe them.
- The mismatch and partial rows (mix program number, mix pitch octave,
  program mode switch, sample group/number) need their addresses or
  widths re-read from the spec.
- Effects remain unverified: the unit ignored every effects `10`. The
  plan to verify them at the record level (`09`/`08`, never `06`) is
  `docs/EFFECTS_VERIFICATION_PLAN.md`.
- The TUI parameter editor, the extended mix editor and the program
  sound editor (V15-V17) are not built; the `10` path is available
  through `nanocli set`.
