<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Parameter verification run — plan for nanosyned

**Repository:** `/home/lentferj/git-repos/nanosyned`
**Base branch:** `master` (the merged `parity` work)
**New branch:** `param-verify` (from `master`; leave `master` untouched)
**Hardware:** Alesis NanoSynth attached, reachable through the bench chain
(`Roland XV-2020:Roland XV-2020 MIDI 1 52:0` at the last run); Identify reports
QS family member 7. Data is not vital, and every probe is confined to the
**edit buffer**, which is volatile and restored after each probe.
**Run log:** `~/temp/nanosyned-param-run-log.md`
**Backups:** `~/temp/nanosyned-backups/<YYYYMMDD-HHMMSS>/` (persistent)

This plan is the nanosyned counterpart of the x5ded set
(`x5ded-delta-closure-plan.md`, `x5ded-write-path-plan.md`,
`x5ded-param-verification-plan.md`). It carries over their method — small,
atomic subagent tasks on free models, orchestrator-only hardware — and adapts
it to this instrument.

---

## 0. Goal

Close the two gaps the x5ded runs exposed as the remaining family-wide ones,
in this order:

1. **Delta closure (small):** adopt `vinsynlib.config.config_dir` /
   `default_config_path` / `migrate_legacy_config`; make the ledgers tell the
   truth about what is transcribed versus verified.
2. **Parameter verification (the real work):** promote `nano/params.py`'s
   **transcribed** rows to **verified** rows by controlled before/after
   changes on the unit, then ship the parameter/per-channel editors that are
   deliberately absent today.

**Non-negotiable, inherited from x5ded:** a field is writable only after a
controlled before/after change on the unit confirms its offset **and** its
value law. The QS specification and the existing transcription are leads, not
proof. A row that cannot be verified stays read-only and says so.

Today `nano/params.py` has 178 rows transcribed from Alesis's published QS6/7/8/R
specification, and nothing in the code records whether this firmware honours
them. `nanocli set` can send any of them blind. That is the gap.

---

## 1. What we know

- **The `10` MIDI Edit message** addresses one parameter and changes the
  **edit buffer**, not stored memory:
  `F0 00 00 0E 0E 10 <0mmfffff><0ssppppp><0ccccddv><0vvvvvvv> F7`
  — `mm` mode (0 global, 1 mix, 2 program, 3 effects), `fffff` function,
  `ss` sound/effect bus, `ppppp` page, `cccc` channel, `dd` pot, and an 8-bit
  two's-complement value.
- **`03` Edit Program Dump Request** returns **`02` Edit Program Dump**
  (`00` = program mode edit buffer; `1-16` = mix program slots). The `02`
  body is the same 350-byte program record as a `00` user program dump.
- **`02` Edit Program Dump sent to the unit LOADS the edit buffer.** It does
  not store anything. This is the restore message.
- **`00` User Program Dump sent to the unit STORES the user program.** It is
  the write that must never be sent during verification. (This is the exact
  analogue of x5ded's `0x11`.)
- **Everything sent comes back** on the bench chain (soft thru). Replies are
  matched by opcode *and* object number, as `nano.bridge.request` already
  does.
- **The unit is silent after a `10`.** MIDI Edit is unacknowledged; the probe
  must read the edit buffer afterwards, not wait for a reply.
- **The published QS table** gives each row's `(mode, function, page, pot)`,
  bit width, bit address, range and Offset column. `nano/params.py` carries
  them. The published table is the *hypothesis*; the differential probe is
  the *proof*.
- **No front-panel parameter editing exists on this unit.** It has three
  knobs and no display; it cannot edit a parameter to cross-check the probe.
  x5ded's **method B is unavailable here** (see §2).

---

## 2. Verification methods — and the one difference from x5ded

### A. Edit-buffer differential (automated, the only method here)

For a candidate parameter:

1. Read the edit buffer: send `03 00`, receive `02 00 <350-byte record>`.
2. Send `10` with a value different from the current one; wait for the unit
   to settle (no reply is sent).
3. Read the edit buffer again; diff it against the original.
4. The changed bit(s) identify the field. For a whole-byte row, exactly one
   byte changes. For a bitfield, only the field's bits change and its sibling
   bits must not.
5. **Value-law check:** repeat with at least two more values (the row's low
   and high, and a negative one where `low < 0`). Assert the stored field is
   `value - offset` (offset binary) or the two's-complement bit pattern
   (Global), matching `Param`.
6. **Restore:** send `02 00 <original 350-byte record>`, then `03 00` and
   assert the edit buffer equals the original byte for byte.
7. **Never send `00`.** The stored user program is untouched for the whole
   run.

This is the same shape as x5ded's `0x41` probe, with `02` restoring instead
of `40`, and `00` forbidden instead of `11`.

### B. Front-panel differential — **not available on this instrument**

The NanoSynth's front panel selects a bank and a program and has no parameter
editing and no display. There is no way for a person to change one parameter
from the panel and let the agent diff it. The plan therefore uses **A only**,
and compensates by probing *multiple values per field* and by checking the
bit-level result, which together confirm both offset and value law. This is a
real limitation and is recorded as such, not glossed over.

---

## 3. Safety invariants

1. **Never send `00` (User Program Dump) during a probe.** Only `10` (edit
   buffer) and `02` (load edit buffer). The stored bank is not written.
2. **Restore after every probe**, and verify the restore. A probe that cannot
   restore is a stop condition.
3. **Back up before any later store.** Store tests use the existing fence:
   gate, unconditional backup, read-back verify, undo. The probe phase has no
   store.
4. **One session, one unit.** No other MIDI application while probing.
5. **Scratch slot for the later store tests:** User 127 is refused outright
   (hardwired silent). Use a normal User slot chosen by the test and restore
   it in `finally`.
6. **A row is `verified=True` only when the offset and the value law are both
   confirmed.** A one-byte diff without the value law is not enough for a
   signed or offset-binary field, and not enough for a bitfield.
7. **No guessed bytes in a shipped editor.** The probe tool may probe; the
   editors only edit `verified=True` rows. Unverified rows are shown with
   their verification status and are not editable.
8. **The editors preserve sibling bits.** Whole-record writes go through
   `nano.records.encode_bit_field`, which is MSB-first and leaves the other
   bits of a shared byte alone. The `10` message edits one field natively.
   A field whose bit layout is ambiguous stays read-only.
9. **Alesis's content is never committed.** Names, fixtures and screenshots
   stay invented. The probe's records are the user's unit contents and are
   never committed.

---

## 4. Phases and atomic tasks

Model names are the current free ladder; the review uses
`opencode-go/glm-5.3-flash` as the x5ded runs did.

Ladder:
- **Iceman** = `opencode-go/iceman-contributor-free` (mechanical code/tests)
- **Beam** = `opencode-go/beam-free` (docs/prose)
- **Flint** = `opencode/flint-40b-free` (code)
- **Mimo** = `opencode/mimo-v2.6-flash-free` (code/reasoning)
- **Nemotron** = `opencode/nemotron-3.5-lightning-free` (small mechanical)
- **DS** = `opencode/deepseek-v4.1-flash-free` (fallback)
- **VL** = `opencode/nemotron-3.5-super-vl-free` (vision, only if a page must be read)
- **Review** = `opencode-go/glm-5.3-flash`

### Phase D — delta closure (no unit writes)

| ID | Task | Files | Tests | Model | Depends |
|---|---|---|---|---|---|
| D01 | Bind config to `config_dir("nanosyned")` / `default_config_path`, migrate legacy `./config.toml`, keep `--config` override | `nano/config.py`, `nanosyned/app.py`, `nanosyned/cli.py` | `tests/test_config_paths.py`, `tests/test_connect.py` | Iceman | — |
| D02 | Truth pass: README/TODO/RESOLUTION_NOTES say the parameter tables are **transcribed, not verified**; link this plan; state `.sqs` is a shared out-of-scope gap | `README.md`, `TODO.md`, `docs/RESOLUTION_NOTES.md` | docs only | Beam | — |
| D03 | Add the missing `02` encoder and bridge method: `messages.edit_program_dump(record)` and `NanoBridge.write_edit_program(record)` (send only), with exact-frame tests | `nano/messages.py`, `nano/bridge.py`, `tests/test_messages.py`, `tests/test_bridge.py` | frame parses back as `02`, 350→400 packed, no store | Iceman | — |

### Phase V0 — pure code and harness (no unit writes)

| ID | Task | Files | Tests | Model | Depends |
|---|---|---|---|---|---|
| V01 | Add verification status to `Param`: `verified: bool = False` and `value_law: str = ""` (`"offset"`/`"twos"`/`"raw"`), plus `verified_params(mode=...)`; keep every existing row unverified by default | `nano/params.py`, `tests/test_params.py` (new) | defaults False, filter, frozen/replace round-trip | Iceman | — |
| V02 | Pure value-law helpers: `stored_for(param, value)` and `value_from_stored(param, stored)` used by both the probe and the editors; explicit for two's-complement Global and offset-binary packed modes | `nano/params.py`, `tests/test_params.py` | round-trip across low/high/negative, offset fields | Flint | V01 |
| V03 | Safe probe harness `tools/probe_params.py`: read edit buffer, send `10`, settle, read, diff bits/bytes, restore with `02`, verify restore, never send `00`; fake-device tests | `tools/probe_params.py` (new), `tests/test_probe_params.py` (new) | fake device, no `00`, restore verified, one-byte/bitfield/multi-byte classification | Mimo | D03, V02 |
| V04 | Generate `docs/PARAMETER_NUMBERS.md` from `nano/params.py` (mode, address, label, bits, range, offset, verified, verdict); a test that the doc and the table agree | `docs/PARAMETER_NUMBERS.md` (new), `tools/gen_parameter_docs.py` (new), `tests/test_parameter_docs.py` (new) | generated doc matches table; no hand-edit drift | Beam | V01 |

### Phase V1 — automated differential (hardware; orchestrator only)

| ID | Task | Output | Gate | Depends |
|---|---|---|---|---|
| V05 | Probe the **Global** rows (20): offsets and two's-complement law; skip spares/model-only rows | run log + `docs/PARAMETER_NUMBERS.md` | restore verified after each | V03 |
| V06 | Probe the **Mix common + channel-1 template** (13 + 20); then channel 2 and channel 16 to confirm the 8-byte stride | same | same | V05 |
| V07 | Probe the **Effects** primary branch (64) and the MOD rows (6); record which type-dependent rows share addresses | same | same | V06 |
| V08 | Probe **program common/name** (13) and the 31 transcribed keyboard-sound rows; record the rest of the sound table as unprobed | same | same | V07 |
| V09 | Multi-value law pass for every signed/offset field: send low, high and a negative; assert `stored == value - offset` (or two's complement) | same | a mismatch is a finding, not a reason to edit the table | V08 |
| V10 | Bitfield sibling pass: for each packed field, assert only its bits change and sibling bits are untouched | same | any sibling change stops that field | V09 |

**Stop condition:** a probe that changes a field other than the expected one,
or a restore that does not return the original edit buffer byte for byte,
stops the run. Record it; do not add the row.

### Phase V2 — promote verified rows

| ID | Task | Files | Tests | Model | Depends |
|---|---|---|---|---|---|
| V11 | Set `verified=True` and `value_law` only on rows V05–V10 confirmed; leave the rest unverified with the reason | `nano/params.py` | every promoted row has offset+law; unverified rows are still present | Iceman | V10 |
| V12 | Regenerate `docs/PARAMETER_NUMBERS.md`; add a completeness test (every verified row has a record offset and a law; no verified row lacks a probe entry) | doc + tests | doc/table agreement | Beam | V11 |
| V13 | Record the unprobed remainder plainly: the program sound table beyond the transcribed 31 rows, the type-dependent effect branches, the multi-byte rows | `docs/PARAMETER_NUMBERS.md`, `TODO.md` | docs only | Beam | V12 |

### Phase V3 — editors over verified rows

| ID | Task | Files | Tests | Model | Depends |
|---|---|---|---|---|---|
| V14 | CLI: `nanocli params MODE` lists rows with verified/unverified status; `nanocli param-get` reads one field from the edit buffer; keep `set` but refuse unverified rows unless `--force-unverified` (labelled raw) | `nanosyned/cli.py`, `tests/test_cli_params.py` (new) | list/status, get, set refusal, gate/`--yes` | Iceman | V12 |
| V15 | TUI parameter editor (`p`): list only verified rows, edit a value through `10`, read back and show the result; no single-key write; the working copy is not stored | `nanosyned/paramsui.py` (new), `nanosyned/app.py`, `tests/test_paramsui.py` (new) | arm-then-fire, cancel, read-back, unverified rows not editable | Mimo | V14 |
| V16 | Extend the mix modal to every **verified** mix channel field (program, enable, volume, pan, output, effect level/bus, octave/semitone, note windows, MIDI in/out) | `nanosyned/mix.py`, `nanosyned/screens.py`, `tests/test_mix.py` | round-trip for each verified field, unverified not offered | Iceman | V12 |
| V17 | Program sound-field editor for the verified subset; store requires the existing fence (gate, backup, whole-record write, read-back, undo) | `nanosyned/paramsui.py`, `nanosyned/app.py`, `tests/test_paramsui.py` | edit → store → read back; User 127 refused | Mimo | V15 |
| V18 | Effects/global editors show verification status: verified rows editable, transcribed rows shown read-only with the reason | `nanosyned/screens.py`, `nanosyned/editor.py`, `tests/test_mix.py` | unverified refused, verified round-trip | Iceman | V12 |

### Phase V4 — hardware tests, docs, review, final

| ID | Task | Files | Tests | Model | Depends |
|---|---|---|---|---|---|
| V19 | `tests/test_hardware_params.py`: probe one field per mode, verify, restore; opt-in `NANOSYNED_HW_PARAMS=1`; never send `00` | `tests/test_hardware_params.py` (new), `Makefile` | unit run, restore in `finally` | Orchestrator | V11, V15 |
| V20 | README/`DISCLAIMER.md`/`docs/CHECKS.md`/`TODO.md`: parameter editor, verified row counts, the no-front-panel limitation, and the unprobed remainder | docs | docs only | Beam | V19 |
| V21 | Review the branch with `opencode-go/glm-5.3-flash`; fix findings atomically | branch diff | review | Review | V20 |
| V22 | Final: `make check`, `make test-hardware`, the parameter hardware test with restore, and the run log | branch | all | Orchestrator | V21 |

---

## 5. Hardware protocol for the probe

**Pre-flight (once):**

1. `nanocli --scan status` — confirm Alesis, QS family, member 7.
2. Choose a program whose edit buffer is safe to disturb; record its name.
3. Read the edit buffer (`03 00` → `02 00`) and save it to
   `~/temp/nanosyned-backups/<timestamp>/edit-buffer.syx`. This is the
   restore reference.
4. Confirm the restore path once with no probe: send `02` with the original
   record, read it back, compare. If that fails, stop before probing.

**Per probe:**

```
03 00                                   -> 02 00 <before>   (350 bytes)
10 <mm><f><page><pot><value>            -> (silence)
03 00                                   -> 02 00 <after>
diff(before, after)                     -> byte(s) and bit(s)
02 00 <before>                          -> (silence; loads edit buffer)
03 00                                   -> 02 00 <must equal before>
```

- Match the reply by opcode `02` **and** number `00`.
- After the `10`, allow a short settle (the unit is silent); do not wait for
  a reply.
- If more than the expected bits change, record the diff and stop that field.
- If the restore read-back differs, stop the whole run.

**Later store tests (only after a row is verified):**

- Use the existing fence: `w` gate, unconditional backup, write, read-back,
  undo.
- Refuse User 127 outright.
- Restore in `finally` and verify the restore.

---

## 6. Model routing

- Research/prose: `opencode-go/beam-free`; fallback `opencode/deepseek-v4.1-flash-free`.
- Mechanical code/tests: `opencode-go/iceman-contributor-free`.
- Complex code: `opencode/flint-40b-free` and `opencode/mimo-v2.6-flash-free`.
- Small mechanical edits: `opencode/nemotron-3.5-lightning-free`.
- Vision (only if a spec page must be read): `opencode/nemotron-3.5-super-vl-free`.
- Review: `opencode-go/glm-5.3-flash`.
- Hardware probes/stores: **orchestrator only**, never a subagent, so only one
  process drives the unit.

Rules: one task per brief, exact files, required tests, no commit; the
orchestrator reviews and commits. Free model fails twice → escalate one rung
and record it.

---

## 7. Stop conditions

- A probe cannot restore the edit buffer.
- A `10` changes bits outside the expected field.
- The value law does not match the transcribed `Param` at more than one
  value.
- A restore read-back mismatches.
- `00` would be sent (never).
- A backup fails.
- The address is ambiguous for a field.
- A subagent edits outside its brief.

---

## 8. Confirmation gates

Before starting:

1. **Scope:** approve D + V0–V4 (parameter verification and editors). `.sqs`
   import stays out of scope, as a shared family gap.
2. **Branch:** `param-verify` from `master`.
3. **Hardware:** the NanoSynth is available; probing writes only the volatile
   edit buffer and restores it. Confirm that is acceptable (it was, for the
   `parity` hardware runs).
4. **Backups:** `~/temp/nanosyned-backups/<timestamp>/`.
5. **Field priority:** Global → Mix → Effects → Program common/sound. Add or
   remove.

Do not start V05 until these are answered.

---

## 9. Final deliverable

- `docs/PARAMETER_NUMBERS.md` with the verified map and the unprobed
  remainder stated plainly.
- `nano/params.py` with `verified`/`value_law` on every row; unknown rows
  preserved and read-only.
- `tools/probe_params.py` and its tests; `messages.edit_program_dump` and
  `NanoBridge.write_edit_program`.
- CLI `params`/`param-get` and a TUI parameter editor, plus the extended mix
  editor, all behind the existing fence and using verified rows only.
- Opt-in hardware parameter test with restore.
- `make check` green; `make test-hardware` green; run log written.
- Review findings fixed; no push, tag or release unless asked.
