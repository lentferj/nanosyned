<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Program import — implementation prompt

**Read `docs/IMPORT_PLAN.md` first. This file is the orchestration prompt;
the plan is the specification.**

## Kickoff (paste this into the orchestrator session)

> You are implementing the program-import feature specified in
> `docs/IMPORT_PLAN.md` for the repository at
> `/home/lentferj/git-repos/nanosyned`.
>
> Work on a new branch `import-parity` created from the current branch
> (`param-verify`), unless the user names a different base. The venv is
> `.venv`; every command runs as `.venv/bin/python -m …`. The baseline is
> **612 passed / 8 skipped**, ruff/format/mypy clean; it must never go
> down.
>
> Execute the plan one task at a time, in the order in the table below.
> Each task is one subagent session with a fresh context. Use the model in
> the task's row as the subagent's `model`; that model was chosen for the
> shape of the work. Do not batch two tasks into one subagent, and do not
> let a subagent "helpfully" touch a file outside its task card.
>
> You are the reviewer and the only one who commits. A subagent returns a
> summary, the tests it ran, and the exact output. You run the task's
> verification yourself, read the diff, and then commit with the message
> given below. If a task fails twice, stop and report; do not let it
> wander or weaken a test.
>
> Hardware is off-limits to subagents and to `make check`. Only the human
> runs the opt-in hardware check, and only after saying yes to the write.
>
> Stop conditions: a task would need a file outside its allowlist; a
> safety invariant in plan §4.3 would be weakened; the full suite drops
> below the baseline; or the requested UX would silently write something
> the confirmations did not name. In each case, stop and ask.

## Task order, model, and commit message

Run in this order. **Bold** tasks are serialisation points: do not start
the next one until the bold one is committed.

| # | Task | Subagent model | Commit after review |
|---|---|---|---|
| 1 | **T1** bank-aware `.sqs` | `opencode/beam-free` | `feat(sqs): keep the container's banks` |
| 2 | **T2** source model | `opencode/beam-free` | `feat(import): read .syx and .sqs into source banks` |
| 3 | **T3** planner | `opencode/deepseek-v4.1-flash-free` | `feat(import): plan slots and validate assignments` |
| 4 | **T4** shared writer | `opencode/deepseek-v4.1-flash-free` | `refactor(write): one read/backup/store/verify loop` |
| 5 | **T5** CLI `--list` | `opencode/hy4-flash-free` | `feat(cli): add import --list` |
| 6 | **T6** CLI single/multi | `opencode/deepseek-v4.1-flash-free` | `feat(cli): import programs into chosen slots` |
| 7 | T7 CLI bank parts | `opencode/mimo-v2.6-flash-free` | `feat(cli): import effects, mixes and global with a bank` |
| 8 | T8 file picker | `opencode/flint-40b-free` | `feat(ui): add the import file picker` |
| 9 | **T9** import flow | `opencode/flint-40b-free` | `feat(ui): open imports from I` |
| 10 | **T10** whole bank | `opencode/deepseek-v4.1-flash-free` | `feat(ui): whole-bank import screen` |
| 11 | **T11** single map | `opencode/beam-free` | `feat(ui): map source programs to User slots` |
| 12 | **T12** worker/progress | `opencode/mimo-v2.6-flash-free` | `feat(ui): import worker, progress and cancel` |
| 13 | T13 batch undo | `opencode/deepseek-v4.1-flash-free` | `feat(undo): one entry for a whole import` |
| 14 | T14 preview | `opencode/hy4-flash-free` | `feat(ui): preview an import in the edit buffer` |
| 15 | T15 docs | `opencode/inkling-2-small-free` | `docs: describe program import` |
| 16 | **T16** QA | `opencode/beam-free` | `chore: import parity review` |

`T7` may run alongside `T8`; `T10` and `T11` both wire
`nanosyned/app.py` and must not overlap. `T14` also touches `app.py`, so
run it after `T13`, not beside it.

### Model fallback ladder

If a model is unavailable or its free quota is exhausted, fall back in
this order, and say which one was used in the task report:

1. the model named in the row;
2. `opencode/deepseek-v4.1-flash-free`;
3. `opencode/flint-40b-free`;
4. `opencode-go/beam-free`.

**Do not use `iceman`** unless the user explicitly asks for it. The user
prefers `beam-free` and DeepSeek V4.1 Flash.

## Per-task subagent prompt template

Fill the braces and send exactly this. Do not paraphrase the allowed
files or the safety rules.

```
GOAL
Implement task {TASK} from /home/lentferj/git-repos/nanosyned/docs/IMPORT_PLAN.md
(§8, the card titled "{TITLE}").

CONTEXT
- Repository: /home/lentferj/git-repos/nanosyned
- Branch: import-parity (already checked out; do NOT switch or create)
- Python: .venv/bin/python
- Read first: docs/IMPORT_PLAN.md §§{SECTIONS}; the task card §8/{TASK};
  and the existing files named below.
- The family's safety invariants are plan §4.3. They are not negotiable.
- Baseline suite: 612 passed, 8 skipped. Do not weaken a test to pass.

ALLOWED FILES (edit only these)
{FILES}

WHAT TO DO
{STEPS}

CONSTRAINTS
- Standard library only; no new dependency.
- Keep line length 88; match the surrounding tone and docstring style.
- No hardware, no `make test-hardware`, no MIDI port.
- No commit, no push, no branch change, no worktree.
- Do not edit a file outside ALLOWED FILES. If you believe one is needed,
  stop and say why instead.
- Every unit-derived string goes through nanosyned.text.literal() before
  Textual markup.

VERIFY (run all; paste the exact output)
{VERIFY}

ACCEPTANCE
{ACCEPT}

OUTPUT
- What changed and why, one paragraph per file.
- The exact verification commands and their final lines.
- Anything you deliberately did not do.
- Do not commit.
```

## Wave gates

After every task, the orchestrator runs:

```sh
.venv/bin/python -m ruff check <touched files>
.venv/bin/python -m ruff format --check <touched files>
.venv/bin/python -m mypy
```

After every **wave** (the bold rows in the table), additionally:

```sh
.venv/bin/python -m pytest -q -o addopts="" -p no:cacheprovider
```

and one demo smoke test. Do not start the next wave until both are green
and the diff has been read.

A wave is:

- **W0** T1–T4 — parsers, model, planner, writer.
- **W1** T5–T7 — the CLI.
- **W2** T8–T11 — picker, flow, the two import screens.
- **W3** T12–T14 — worker, undo, preview.
- **W4** T15–T16 — docs and QA.

## Commit protocol

- The orchestrator commits, never the subagent.
- One commit per task, message from the table above; add one or two
  sentences about the *why* in the body.
- Re-run the task's tests after any fix you make during review; the
  commit contains only that task's files.
- Never commit a fixture that contains real bank data from
  `~/Dokumente/SYNTHS/Nanosynth/`; synthetic fixtures only.
- Keep the working tree clean between tasks so a bad task can be dropped
  without archaeology.

## Hardware protocol

- No subagent opens a MIDI port.
- The opt-in hardware check is run by the human, once, at the end:
  one single-program import into a spare User slot, read back, then the
  previous bytes restored from the named backup.
- It runs only with `NANOSYNED_HW_WRITE=1`, never as part of `make check`,
  and only after the human confirms the slot and the write.
- If the unit is unavailable, leave the check documented and unrun; do not
  mark it passed.

## Definition of done (orchestrator checklist)

- [ ] Every task card's acceptance is met and its tests are in the suite.
- [ ] `make check` is green: ruff, format, mypy, pytest, audits.
- [ ] Baseline or better: 612+ passed, 8 skipped; no new warning.
- [ ] The demo end-to-end works: list, dry-run, single, multi, bank,
      cancel, undo.
- [ ] No write path exists without the gate and the confirmations.
- [ ] Destination 127 and mix 100 are never stored.
- [ ] Every agreed write is backed up and read back; failures are named.
- [ ] One `z` restores a whole import; a partial undo keeps the failures.
- [ ] README and `_HELP` name every new key and flag.
- [ ] No hardware is required by the test suite; the opt-in check is
      documented.
