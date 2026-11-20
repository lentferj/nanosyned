<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Import-parity review findings — fix prompt

**Read `docs/PROMPT-PARITY.md` section 9 first.** This file carries the
review of branch `import-parity` (`master..HEAD`, 51 commits, 752 tests
green) verbatim, and turns every finding into one atomic fix task in the
plan's `id — title — files — dep — model — done when` shape, as section 9
asks. The findings were verified against the code; two were reproduced by
executing throwaway tests against the working tree (R1, R3). No file was
modified by the review.

Model ids: `opencode/glm-5.3-flash-free` (G),
`opencode/deepseek-v4.1-flash-free` (D),
`opencode/nemotron-3.5-lightning-free` (N, fast/mechanical),
`opencode/longcat-2.5-preview-free` (L, docs).

---

## 1. Findings, in priority order

### Correctness bugs

**R1 — a failed `g` read locks the browser busy forever.**
`nanosyned/app.py:1899-1913` (`_global_read_worker`). Evidence:

```python
exchange_acquired = False
try:
    with self._busy_gate, self._lock:
        record = self.device.read_global()
    exchange_acquired = True
except _BRIDGE_ERRORS as exc:
    failure = exc
finally:
    if exchange_acquired:
        self._exchange.release()
```

`exchange_acquired` is set only *after* the `with` block completes, so on
any failure — a timeout is the ordinary case — `self._exchange` is never
released. The lock was claimed on the main thread in `action_edit_global`
(`app.py:1894-1896`), and `_busy` (`app.py:416-420`) reads
`self._exchange.locked()`, so every later MIDI action (select, read, edit,
import, undo, scan) refuses with "busy" for the rest of the session.
Reproduced by executing the pattern against the app fixture. The family
shape releases unconditionally (rxved `app.py:962-982`, `_set_mode_worker`:
`finally: self._busy = False`), as this file's own other twelve workers do.

**R2 — the same leak in the effects read.** `nanosyned/app.py:2043-2060`
(`_effects_read_worker`), same inverted flag; additionally the release is
wrapped in `try: ... except RuntimeError: pass  # Lock already released,
ignore` (`app.py:2056-2060`) — `threading.Lock.release()` does not raise
`RuntimeError`, so the guard is dead code that documents the confusion
that produced R1.

**R3 — the demo's effects store never lands, so every effects verify is a
MISMATCH.** `nanosyned/demo.py:329-337`:

```python
def write_effects(self, number, record, *, timeout=None) -> None:
    ...
    stored = bytes(record)
    self.effect_writes.append((number, stored))
```

`write_program` assigns `self._programs[number]` (`demo.py:307-309`),
`write_mix` `self._mixes[number]`, `write_global` `self._global` —
`write_effects` appends to the log only. A read-back after an effects
store returns the *old* bytes, so the browser's `x` editor (`a`/`s` →
`_effects_store_worker`, `app.py:2093-2130`) and `nanocli send --demo` for
an effects record always report "the unit did not take the effects
settings: 65 byte(s) differ". Reproduced by executing it. The demo's own
contract is that read-back equals written (`demo.py:144-148`). No test
round-trips effects (test_bridge.py has mix and global round-trips at
lines 306-322 and none for effects), which is why this survived.

**R4 — `p` opens with an ungated Mode Select.**
`nanosyned/paramsui.py:87-91`:

```python
def on_mount(self) -> None:
    try:
        self._device.mode_select(True)
    except Exception:
        pass
```

`action_edit_parameter` (`app.py:2037-2041`) checks neither the gate, nor
`_busy`, nor the exchange before pushing this screen. So pressing `p`
sends Mode Select — **a message the app treats as a write everywhere
else**: `M` asks the gate, a dialog and a confirmation first
(`app.py:1822-1857`). This breaks CLAUDE.md:91-93 ("Opening an editor
sends nothing, arming sends nothing"), README.md:194-196 ("every write key
is inert until `w` has armed the gate"), and it is swallowed silently on
failure (`except Exception: pass`). The bench reason is real (program
`10` edits land only in Mix mode; PARAMETER_VERIFICATION_RUN_LOG.md:89),
but the decision is recorded nowhere — RESOLUTION_NOTES.md has no entry —
and the test that pins it (`test_paramsui.py:40-49`) pins the violation,
not the discipline. `test_enter_locked_refuses_and_sends_nothing`
(`test_paramsui.py:240-256`) counts only `midi_edits`, so it passes while
the open has already sent a Mode Select with the gate locked.

**R5 — `l` preview sends from the main thread with no busy guard.**
`nanosyned/app.py:2673-2680`:

```python
def _preview_import(self, record) -> None:
    try:
        self.device.write_edit_program(record, edit=0)
    except Exception as exc:
        ...
```

Reached from `SingleMappingScreen.action_preview`
(`importsingle.py:469-479`) with no `_busy` check, no `_exchange` claim
and no gate. A load (opcode `02`) is not a store — the plan designs it
(IMPORT_PLAN.md:115) — but it is a MIDI send, and it happens on the main
thread while a worker may be mid-exchange: press `r` (128 requests
running), then `I` → picker → single → `l`. `write_edit_program` calls
`self._drain()` first (`bridge.py:649-650`), which consumes *every*
queued message — stealing the reader's replies and failing the read —
and interleaves a load into the request/response traffic the unit is
documented to choke on (item 1, `app.py:1107-1117`). Every other send in
the app is claimed on the main thread before the worker exists
(`app.py:1110-1121`).

**R6 — the parameter screen's thread discipline.**
`nanosyned/paramsui.py`:
- `_fill` (152-194) and `action_cycle_mode` (249-257) read the buffer
  synchronously on the main thread (`read_global`, `read_mix(100)`,
  `read_edit_program`) — MIDI from the main thread, racing any worker;
- `_edit_worker` (332-386) sends `midi_edit` plus a read-back with no
  `_busy_gate` and no `_exchange` claim — two rapid `e` edits run two
  concurrent workers on one port;
- the `try: self.app.call_from_thread(...) except Exception: <direct
  call>` fallbacks (357-363, 368-376, 378-381) call
  `_edit_done_mismatch`/`_edit_done_ok` **directly from the worker
  thread** when `call_from_thread` raises — widget mutation off the main
  thread, exactly what the fallback exists to avoid;
- `except Exception` (382) dresses a programming error up as a device
  fault, against `_BRIDGE_ERRORS`' stated design (`app.py:112-123`).

### Missing or weak tests

**R7 — no test pins the exchange release on a failed read.** The R1/R2
leak is invisible to the suite: `tests/test_app.py` has no failure-path
test for `_global_read_worker`/`_effects_read_worker`, and no test asserts
`not app._exchange.locked()` after a refused or timed-out read. The
behaviour most worth pinning in this file — "a failed action leaves the
app usable" — is unpinned.

**R8 — no demo effects round-trip.** `tests/test_bridge.py:306-322`
round-trips a mix and the global; there is no
`write_effects` → `read_effects` test, which is exactly the one that is
broken (R3). `test_edits_and_mode_changes_are_logged` (line 324) checks
only the log.

**R9 — the ungated/unguarded sends are unpinned, and one test pins the
violation.** No test asserts that `p` with the gate locked sends nothing
(it sends a Mode Select), that `l` is refused or deferred while
`self._busy`, or that the parameter screen's open send honours the
exchange. `test_opening_sends_mode_select_and_shows_warning` pins the
ungated send as intended behaviour (R4) — if R4's fix keeps the auto
Mode Select, that test must be rewritten to assert gate-then-send;
otherwise it asserts the opposite of the fix.

**R10 — `--all` and `--program` together silently ignores `--program`.**
`nanosyned/cli.py:916-932` (`_import_plan`): `args.all` wins and the
`--program` pairs are dropped without a word. Untested, unspecified.

### Docs and ledger contradictions

**R11 — TODO item 7 contradicts the branch.** `TODO.md:127-145` still
says the `.sqs` format is unread, "Nothing here depends on it", and the
note added by *this branch's own commits* ("Deliberately out of scope for
the `param-verify` branch") — while the branch lands `nano/sqs.py`,
`.sqs` support in `nanocli import` and the browser `I`, and
`tests/test_sqs.py`. Per CLAUDE.md:133-139, *what* is open belongs in
TODO.md; item 7 must be closed (or narrowed to what is genuinely left,
e.g. `.mid`/`.lib`).

**R12 — README contradicts itself about `.sqs`.** README.md:371-372
("`.sqs` import remains a shared family gap and is out of scope for this
branch") against README.md:378 ("`nanocli import` reads a `.syx` ... or
`.sqs`"). The first sentence is a stale leftover from the param-verify
branch.

**R13 — README overclaims the browser import.** README.md:189: "`I` |
import programs (and effects, mixes, global)". The browser flow builds
program-only plans (`importflow.py:79-85`; `importplan.plan_bank` and
`plan_single` yield only programs); parts are CLI-only by design
(IMPORT_PLAN.md:14, 41, 53).

**R14 — README's write-key claim is false for `p` and `l`.**
README.md:194-196 ("every write key is inert until `w` has armed the
gate") — see R4 and R5. Fix the sentence or the keys; both cannot stand.

**R15 — README misdescribes `ctrl+s` on the mapping screen.**
README.md:394-397: "or press `ctrl+s` to import the whole bank with no
mapping" — `ctrl+s` on `SingleMappingScreen` imports the *mapping you
built* (`importsingle.py:488-506`); the whole-bank path is the dialog's
first choice (`importflow.py:57-60, 142-165`).

### Minor style

**R16 — speculative compat surface in `importsingle.py`.** The alias
table and id rewriting (`importsingle.py:46-61, 563-584`) plus four class
aliases (602-606) exist for "a caller or a test might use" any of several
names. The family's shape is one name; the tests that use the aliases
should use the real one.

**R17 — workers mutate `self._backed_up`.** `_store_worker`
(`app.py:1531-1540`), `_mix_store_worker` (1740-1749), `_global_store_worker`
(1964-1972) and `_effects_store_worker` (2111-2119) add to the app's set
from the worker thread. Benign under the GIL, but it is shared state
touched off the main thread, and the AST guard (`test_app.py:359-375`)
does not see method calls. Hand the fact back with
`call_from_thread`, or document the exception.

**R18 — small wording/derailments.**
`_undo_done`'s refusal joins `sentences` including the empty strings of
successful entries, producing `"; ; "` gaps (`app.py:1395`); the import
progress line shows slot `000` for the global step
(`app.py:2554-2564`, `number or 0`); `ImportProgressScreen.set_progress`'s
docstring says "Update the display from the worker thread"
(`importprogress.py:78-81`) while every caller goes through
`call_from_thread`; the parameter screen captures `channel` at
construction and never sees a `[`/`]` change while it is open
(`paramsui.py:60-67`).

---

## 2. Fix tasks

Format: `id — title — files — dep — model — done when`.

| id | title | files | dep | model | done when |
|---|---|---|---|---|---|
| F1 | Release the exchange unconditionally in `_global_read_worker` and `_effects_read_worker`; delete the `except RuntimeError` guard | `nanosyned/app.py` | — | N | a failed `g`/`x` read leaves `not app._exchange.locked()`; a new test in `tests/test_app.py` pins it (R1, R2, R7) |
| F2 | `DemoDevice.write_effects` stores into `self._effects[number]` like its three siblings | `nanosyned/demo.py` | — | N | a `write_effects` → `read_effects` round-trip test passes beside the mix and global ones (R3, R8) |
| F3 | Decide and record the `p` open policy: either gate+confirm the automatic Mode Select (dialog like `M`, or gate check at minimum) or keep it and record why in `docs/RESOLUTION_NOTES.md`; either way it must claim the busy gate/exchange like every other send | `nanosyned/app.py`, `nanosyned/paramsui.py`, `tests/test_paramsui.py`, `docs/RESOLUTION_NOTES.md` | F1 | G | opening `p` while an exchange is in flight is refused or deferred; the gate state decides; RESOLUTION_NOTES records the decision; `test_opening_sends_mode_select...` asserts the new discipline (R4, R9) |
| F4 | Route the `l` preview through the app's exchange: busy check + claim on the main thread before the send, or a worker with the claim — the screen must not send while `_busy` | `nanosyned/app.py`, `nanosyned/importsingle.py`, `tests/test_importui.py` | — | G | `l` during a running `r` is refused with "busy" and sends nothing; a test pins it (R5, R9) |
| F5 | Give `ParameterScreen` the app's thread discipline: reads on a worker (or documented main-thread reads with the exchange claimed), one `_busy_gate`/`_exchange` claim around `_edit_worker`, no direct widget calls off-thread, `_BRIDGE_ERRORS` instead of bare `except Exception` | `nanosyned/paramsui.py`, `tests/test_paramsui.py` | F3 | D | two rapid `e` edits cannot overlap; the `call_from_thread` fallbacks are gone or provably main-thread-only; no bare `except Exception` on the send path |
| F6 | `nanocli import` refuses `--all` and `--program` together (or documents that `--all` wins), with a test | `nanosyned/cli.py`, `tests/test_cli_import.py` | — | N | `import --all --program 0=5` says which one it obeys, or refuses; test pins it (R10) |
| F7 | Close TODO item 7 (`.sqs` is read on this branch) or narrow it to what remains (`.mid`/`.lib`); per CLAUDE.md the *how* goes to RESOLUTION_NOTES | `TODO.md`, `docs/RESOLUTION_NOTES.md` | — | L | TODO no longer claims nothing depends on `.sqs`; RESOLUTION_NOTES records the container's quirks (R11) |
| F8 | README truth pass on the import and write keys: drop the stale "`.sqs` out of scope" sentence, scope `I` to programs, fix the `ctrl+s` sentence, and make "every write key is inert until `w`" true or name the two exceptions | `README.md` | F3, F4 | L | the five sentences R12-R15 name read correctly against the code |
| F9 | Style sweep: one name for the mapping screen (drop the alias table or keep it with a written reason), `_backed_up` handed back via `call_from_thread`, `_undo_done` sentence join, progress slot for global, `ImportProgressScreen` docstring | `nanosyned/importsingle.py`, `nanosyned/app.py`, `nanosyned/importprogress.py`, `tests/test_importui.py` | — | N | ruff clean; the alias surface is either one name or documented; no empty-sentence joins in a refusal |

Dependency order: F1, F2, F4, F6 first (independent, small); F3 next
(owns `paramsui`/`app`); F5 after F3; F7, F8, F9 last (docs and sweep).
Files that touch `nanosyned/app.py` are serialised; F1/F4 both touch it —
run F1 before F4.

## 3. Verification

1. `make lint` then `$(PY) -m pytest -q` — green before a task is called
   done.
2. The two reproduced findings (F1, F2) get regression tests in their own
   task, in the shape of the throwaway tests used to confirm them:
   failed `g` read → `not app._exchange.locked()`;
   `write_effects` → `read_effects` equality.
3. No hardware run is needed for any fix here; all of them are pinned
   synthetically. The hardware import check (CHECKS.md:148-151) stays
   opt-in and human-run.
