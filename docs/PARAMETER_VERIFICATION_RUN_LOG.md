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

- Program edit buffer 0: `WailinWall`, digest `75b9a5bdf195`, restored.
- Program edit buffer 1: `Tubulous`, restored after the sound tests.
- Mix edit buffer 100: restored (`bfceecee977b`).
- Effects edit buffer: config 3, restored (`b44e1d0bc16b`).
- Global: byte 1 back at 7; record restored (`56b9d94fcb91`).
- **No store (`00`) was ever sent.** No user slot changed.

## Remaining

- Redesign the probe harness for the per-mode buffers and the positive
  control.
- Fix `mix_dump_request(100)` / `read_mix(100)`.
- Fix the post-load gap in the write methods (and re-run the hardware
  write test).
- Re-run V05–V08 with the corrected harness; effects stay unverified.
- Then V11–V22 as planned.
