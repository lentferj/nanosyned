<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Effects verification — plan

**Repository:** `/home/lentferj/git-repos/nanosyned`
**Base branch:** `param-verify`
**Hardware:** the NanoSynth behind the XV-2020 chain (port renamed between
sessions; use `NANOSYNED_PORT`)
**Run log to write:** `~/temp/nanosyned-fx-run-log.md`
**Backups:** `~/temp/nanosyned-backups/<timestamp>/`

## 0. The problem

The bench established that the unit **ignores the `10` MIDI Edit message
in Effects mode**: the config row -- present in every configuration --
refused 0, 1 and 2 in both Program and Mix mode. So the method that
verified 75 Global/Mix/Program rows cannot be used here.

But Effects has something the other modes do not need: a **loadable
edit buffer**. `09` requests it and `08` loads it. The bench already
proved the `08` load lands and restores (the effects edit buffer was
changed and put back during the diagnostics). That is enough to verify
a field's offset **without `10`**.

## 1. Method: the record-write differential

For one candidate field:

1. Read the edit effects buffer: send `09 00`, receive `08 00`, 65 bytes.
   Keep it as the restore reference.
2. Copy the record, set the candidate field to a known raw value with
   `nano.records.encode_bit_field` (sibling bits preserved).
3. Load the copy with `08 00 <packed record>` (`write_edit_effects`).
4. Wait `RECORD_GAP` (0.4 s; a 75-byte record is smaller than a program,
   but the bench's rule is "wait for the wire", and the margin is free).
5. Read the buffer again (`09` → `08`).
6. **Verdict:** every changed bit must lie inside the candidate field,
   and the field must decode to the value written. A bit outside is a
   `mismatch`; a field that reads something else is `partial`/
   `no-change`.
7. Restore the reference with `08`, read back, require byte-identical.
8. Repeat at two more values (low and high, or a value with a different
   bit pattern) to confirm the **value law**, not just the offset.

This is the same verdict shape as the `10` probe, with the `08` load in
place of the edit. The positive control is the same idea: flip one bit,
load, prove it moved, load the reference back, prove it returned.

**Safety:** the only messages are `09` (request), `08` (load the edit
buffer) and `0D` (mode). `06` (user effects store), `00`, `0A` and `0E`
below 100 are never sent. The edit buffer is scratch; the user's stored
effects patches are untouched.

## 2. The configuration problem

The effects record's meaning depends on its **Effect configuration**
(4 bits, bit 70). The unit currently reports configuration **3**
("2-sends, with EQ"); the transcribed table is configuration **0**
("4-sends, 1 reverb"). A config-0 row is not a parameter at all while
the unit is in configuration 3 -- the spec says a `10` for a function
that does not exist selects the nearest legal one and *no edit occurs*,
which is one reason the effects `10` looked dead.

So the work is per configuration:

| config | spec name | transcribed? |
|---|---|---|
| 0 | 4-sends, 1 reverb | `EFFECT_CONFIG_0_PARAMS` (64 rows) |
| 1 | 4-sends, 2 reverb | no |
| 2 | 4-sends, 1 lezlie | no |
| 3 | 2-sends, with EQ | no (the unit's current) |
| 4 | overdrive/chorus/delay/reverb/lezlie | no |

The configuration itself can be changed **by loading a record** with a
different value in the config field -- `08` again, not `10`. That makes
the whole plan self-contained: no `10` anywhere.

## 3. Tasks (atomic, one subagent each where marked)

### F0 -- transcribe configurations 1-4 (subagent, no hardware)

Files: `nano/params.py`, `tests/test_params.py`, `tools/gen_parameter_docs.py`
(if the table shape changes).

- Read the spec's Effects tables for configurations 1, 2, 3 and 4.
- Add `EFFECT_CONFIG_1_PARAMS` ... `EFFECT_CONFIG_4_PARAMS` with the
  same `Param` shape, `verified=False`, `value_law=""`.
- Add a lookup `effect_params(configuration: int) -> tuple[Param, ...]`.
- Do **not** call the config-0 table "the" table anywhere.
- Tests: sizes, no duplicate addresses within a config, the config row
  itself is in the common table, every row unverified.

### F1 -- extend the probe tool with a record strategy (subagent, no hardware)

Files: `tools/probe_params.py`, `tests/test_probe_params.py`.

- Add `class RecordBuffer` with `read(device)` = `request(09→08)` and
  `load(device, record)` = `device.write_edit_effects(record)`.
- Add `record_probe(device, buffer, param, value, ...)` that writes the
  field into a copy, loads, reads, classifies with the same
  `classify()`/`changed_bits()` helpers, and restores in `finally`.
- Add `--strategy {edit,record}`; effects rows select `record`
  automatically (or the CLI requires it).
- The safety scan must allow `08`/`09` and still forbid `06`, `00`,
  `0A`, `0E`<100. Add tests for a firmware that normalizes the field
  (partial) and one that ignores the load (no-change).
- Positive control for the record strategy: flip one bit, load, read,
  restore.

### F2 -- verify the common rows and configuration 3 (hardware, orchestrator)

- Read the current effects record; confirm the config field.
- Verify the common rows that exist in every configuration (the config
  row itself; the ten deleted spares are skipped).
- Verify the configuration-3 rows, two or three values each.
- Restore after every row; a failed restore stops the run.
- Record the results in the run log and the JSON.

### F3 -- switch configurations and verify the rest (hardware)

- For each configuration 0, 1, 2, 4: build a record with the config
  field set, load it, read back and confirm the field changed (the
  config row is itself a verified field), then verify that
  configuration's rows. Restore the original record at the end.
- Expect some rows to be **normalized** (a reverb time that only takes a
  few steps, a type that reorders the table). Those are findings; a row
  that does not read back what was written stays unverified.
- The type-dependent branches are exactly what this pass is for.

### F4 -- promote, per configuration (subagent)

- `verified=True` only for rows that confirmed, with the law the pass
  showed.
- The editors and `nanocli params` must show the configuration: a row is
  editable only when the unit's current configuration matches its table.
  Until that selector exists, a promoted config-N row is shown with
  "configuration N" and is read-only unless the current config is N.
- Regenerate `docs/PARAMETER_NUMBERS.md`.

### F5 -- hardware test and docs

- `tests/test_hardware_effects.py`, behind `NANOSYNED_HW_EFFECTS=1`:
  one confirmed row per configuration, record strategy, restore.
- Update README/TODO/the run log; state the count and the configurations
  covered.

## 4. Stop conditions

- A record load that does not come back byte-identical on restore.
- A load that moves bits outside the candidate field; record it, do not
  promote.
- A field that normalizes a legal value: record it, leave the row
  unverified, do not narrow the range without a second value.
- Any temptation to use `10` for effects: it does not work, and the
  record strategy is the answer.

## 5. Why this is safe

The edit effects buffer is the scratch the current program plays through;
`08` loads it, `06` stores a user patch. This plan sends `08` and `09`
only, restores the reference in a `finally`, and never touches a user
effects slot. The same rule as the rest of the branch: **no store**, and
a restore that is read back and compared.

## 6. What "verified" will mean

For an effects row: a modified 65-byte record loaded with `08` came back
with **only that field's bits changed** and the field decoding to the
value written, at **two or more values**, and the original record
restored byte for byte. A row that normalizes or lands somewhere else
stays read-only, and says why.
