<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# Development checks

What `make check` runs, and what was switched off to get it passing on the
existing tree. Recorded on branch `parity` on 2026-10-18: `make check` is
clean on the whole tree (285 tests pass and the 7 hardware tests skip, by
design, without `--hardware`; ruff clean, mypy clean, vulture 0 findings,
deptry 0 findings, pip-audit "No known vulnerabilities found", detect-secrets
clean).

Configuration lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`,
`[tool.pytest.ini_options]`, `[tool.coverage]`, `[tool.vulture]`,
`[tool.deptry]`), with `.pre-commit-config.yaml` and `.secrets.baseline`
beside it. The dev toolchain is pinned in `requirements-dev.txt`; `make venv`
creates `.venv` (with `--system-site-packages`) and installs both.

## The rule this page exists for

**Existing findings are not mass-fixed.** Where a tool reports something, the
fix is either a suppression scoped to a specific rule, module or file with a
reason written next to it, or a real fix to the code — never an edit that
swallows the finding. Two consequences follow:

- **A check that was clean must stay clean.** Nothing here is baselined. A
  module that is exempted stays exempted; a new module that is not exempted is
  held to the full rule set.
- **A new tool is added when its findings are understood, not baselined.** A
  tool that cannot pass on the existing code is not switched on and left
  red — it is switched on once the findings are read and dealt with.

`make check` is clean on the whole tree today, and it is the gate for the
branch before review.

## Running it

```sh
make check            # everything below, in order; stops on first failure
make lint             # ruff check + ruff format --check
make format           # ruff check --fix + ruff format (the fixer; edits files)
make typecheck        # mypy
make test             # pytest with coverage, term-missing
make audit            # pip-audit, vulture, deptry, detect-secrets
make venv             # create .venv and install runtime + dev deps
```

`make check` is `lint typecheck test audit` and stops at the first failure.

The parity plan's further targets — `format-check`, `coverage`,
`test-hardware`, `ci`, `pre-commit-run`, `clean` and `secrets-update` (see
`docs/PROMPT-PARITY.md` T6.6) — now exist in the `Makefile`, alongside
`install` and `install-hooks`. The two that matter for the checks ledger are
called out below.

## What each tool is doing

| Tool | What it runs | What it is set to | Deliberately off |
|---|---|---|---|
| `ruff check` | `make lint`, first half: `.venv/bin/python -m ruff check .` | select `E F I B S SIM UP C4 PL RUF C901`, `mccabe` max-complexity 10, line-length 88, target `py311`, `isort` known-first-party `nano nanosyned vinsynlib` | project-wide: `PLR2004`, `PLC0415`, `S110`, `S112`, `SIM105`; per file below |
| `ruff format --check` | `make lint`, second half, over `$(PYFILES)` (tracked plus untracked-but-not-ignored) | default formatter: 88 columns, double quotes | nothing |
| `mypy` | `make typecheck`: `.venv/bin/python -m mypy` | `files = ["nano", "nanosyned", "tools"]`, non-strict, `python_version = 3.11`, `warn_unused_configs`, `warn_redundant_casts`, `no_implicit_optional`; `rtmidi` `ignore_missing_imports` | opt-in strict modules: `nano.banks`, `nano.catalog` (see below) |
| `pytest` (+ coverage) | `make test` | `asyncio_mode = auto`, `testpaths = ["tests"]`, `addopts = --cov=nano --cov=nanosyned --cov-report=term-missing`; coverage `branch = true`, `source = ["nano", "nanosyned"]`, `show_missing = true` | **no `fail_under`** — no threshold; `exclude_lines` for `pragma: no cover`, `if TYPE_CHECKING:`, `raise NotImplementedError`, `if __name__ == .__main__.:` |
| `pip-audit` | `make audit-vulns` | runtime dependencies rendered from `pyproject.toml` into a temp file, plus `requirements-dev.txt --no-deps` | nothing ignored; scoped to what the project declares |
| `vulture` | `make audit-deadcode` | `min_confidence = 80`, paths `nano nanosyned tools tests`, `exclude = [".venv"]` | 0 findings |
| `deptry` | `make audit-deps` | declared vs imported, `extend_exclude = [".venv"]` | nothing; 0 findings |
| `detect-secrets` | `make audit-secrets` | `detect-secrets-hook --baseline .secrets.baseline` over `$(PYFILES)` plus `Makefile README.md pyproject.toml requirements-dev.txt` | nothing; `.secrets.baseline` has an empty `results` |

`ruff format --check` runs both as the second half of `make lint` and as the
named `format-check` target added by the parity work
(`docs/PROMPT-PARITY.md` T6.6). The two are the same command over the same
`$(PYFILES)`, so they cannot drift.

`pip-audit` deliberately does not audit the whole environment. The venv
inherits the host's site-packages (`make venv` creates it with
`--system-site-packages`), and auditing that would report vulnerabilities in
unrelated system packages and drown the project's own dependencies in noise.
It audits the declared runtime dependencies and the dev pins only. Runtime
dependencies are rendered from `pyproject.toml` at run time, into
`.audit-runtime-req.txt` (gitignored, removed again in the same recipe), so the
list cannot drift from the project's single source of truth.

### What is switched off, and why

Nothing is baselined. The rules below are off because they disagree with how
this codebase is written, not because the code failed them:

- **`PLR2004`** (magic value in comparison) — a MIDI/SysEx codebase full of wire
  bytes; comparing against `0x7F`, `100` or `15` is how the format is written
  down, and naming every one would obscure it.
- **`PLC0415`** (import outside the top level) — the CLI and the TUI defer
  Textual and rtmidi so the offline subcommands and the unit tests do not pay
  for importing a TUI framework.
- **`S110`/`S112`** (try/except/pass and /continue) — best-effort teardown on the
  MIDI path: a `close_port` that raises during cleanup must not mask the error
  that got us there.
- **`SIM105`** — `contextlib.suppress` is not this codebase's idiom; the
  explicit `try`/`except` carries a comment saying why in each case.
- **`S101`** — allowed in `tests/`, where `assert` is what a test is for, and
  nowhere else.
- **`PLR0913`** and **`S608`** in `nano/favorites.py` — `Favorites.add` spells
  out every field because it is the schema; the one SQL string interpolates an
  `ORDER BY` clause a placeholder cannot carry, chosen from a fixed set, never
  from input.
- **`C901`/`PLR0912`** in `nanosyned/cli.py` — `main` is the command dispatch
  table; its branches are the commands, and splitting it would scatter the
  wiring it exists to keep in one place.

## The `typecheck-strict` loop

The intent is that the strict-module list in `pyproject.toml` can **only
grow**. A module is added when it passes the strict checks; a module is never
removed from it; a new module is welcome to opt in once it qualifies. The
`pyproject.toml` comment says so:

> These two modules are fully annotated and already pass `--strict`, so they
> are held to it. A new module should be added here once it qualifies.
> `strict = true` cannot be used per-module: mypy expands it globally, which
> turns the whole project strict and raises pre-existing errors. These are the
> individual checks that `strict` would enable, listed explicitly.

The `typecheck-strict` target is **added by the parity work** (see
`docs/PROMPT-PARITY.md` T6.9, "strict-mypy expansion + `typecheck-strict`") and
lands alongside this ledger; as of this writing the `Makefile` carries
`make typecheck` (plain `mypy`) and the strict loop below is the whole of it.
The two opt-in modules are **`nano.banks`** and **`nano.catalog`**, held to the
individual checks `strict` would enable — `disallow_untyped_defs`,
`disallow_incomplete_defs`, `check_untyped_defs`, `no_implicit_reexport`,
`strict_equality`, `warn_return_any` — rather than to a bare `strict = true`.

## The hardware rule

- **Only one session drives the synth at a time.** Do not open MIDI ports or
  send SysEx if another session may be using the hardware. Develop and test
  synthetically: `nanosyned/demo.py` and `--demo` never construct a bridge and
  open no ports.
- **`make test-hardware` opens MIDI ports, runs one process at a time, and is
  never part of `make check`.** It is an opt-in suite: it runs
  `pytest tests/test_hardware.py tests/test_hardware_params.py --hardware`,
  and without that flag every test in the files skips — a skip with a
  reason, never a pass, so "the unit was off" and "the offsets are wrong"
  cannot look the same green. Its one store (a User program renamed and put
  back) sits behind a third gate, `NANOSYNED_HW_WRITE=1`; the parameter
  probe (`tests/test_hardware_params.py`, one confirmed row per mode) sits
  behind `NANOSYNED_HW_PARAMS=1` and stores nothing. `make check` contains
  no hardware step, so CI never drives the unit. It runs serially — never
  two at once, never while another session drives the unit.
- **Hardware import check (opt-in, human-run).** Behind
  `NANOSYNED_HW_WRITE=1`, never part of `make check`: import one source
  record into a spare User slot over MIDI, read the slot back byte for
  byte, then restore the previous bytes from the backup the import wrote.
  The result (slot, name, read-back verdict) is recorded in
  `docs/CHECKS.md` by hand; a failed read-back or a mismatched backup
  restore is a failed check, not a retry.
- The demo path (`--demo`) is the synthetic stand-in everywhere else.

## The detect-secrets trap

`detect-secrets scan --baseline <file>` **does not check anything.** In v1.5.0
it merges what it just found into the baseline and rewrites it, printing
nothing and always exiting 0. Used as a check it silently accepts new secrets
*and* records them as accepted. The check is `detect-secrets-hook --baseline`,
which compares and exits 1. That is what `make audit-secrets` and the
`detect-secrets` pre-commit hook run.

## Pre-commit and CI

`.pre-commit-config.yaml` runs ruff (`--fix`), ruff-format, a local mypy hook
(`.venv/bin/python -m mypy`, so the check uses the project's own interpreter)
and `detect-secrets --baseline .secrets.baseline`. shellcheck and shfmt are
deliberately absent: this repository contains no shell scripts — no `*.sh` and
no file with a bash/sh shebang — so those hooks would never fire.

There is no CI workflow on this branch yet; `.github/workflows/ci.yml`, which
mirrors `make check`, is added by the parity work (see
`docs/PROMPT-PARITY.md` T6.7).

## See also

The parity plan, of which this ledger is one task (T6.8), is
[`docs/PROMPT-PARITY.md`](PROMPT-PARITY.md).
