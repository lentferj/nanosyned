<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# nanosyned

A terminal browser for the **Alesis NanoSynth** — the 640 programs, the
ones the front panel cannot reach, and the names the unit will tell you.

Sibling to [rxved](../rxved) (Roland XV-2020), [kwsed](../kwsed) (Korg
Wavestation SR), [p2ked](../p2ked) (E-MU Proteus 2000) and
[x5ded](../x5ded) (Korg X5D/X5DR), and it follows their conventions.

## Why

The NanoSynth has 640 programs and a front panel with three knobs and no
display. **384 of those programs cannot be reached from the panel at
all** — the manual says so plainly — and the unit has no way to tell you
what any of them are called. nanosyned selects them by Bank Select and
Program Change, reads back the names of the one bank that can be read,
and keeps your favourites.

## What it knows, and how it knows it

The NanoSynth's Reference Manual has one line about System Exclusive, in
its implementation chart, and no specification. What the unit actually
speaks is the **Alesis QS protocol** — it is a QS engine in a small box —
and that is published. Everything in `nano/messages.py` is transcribed
from Alesis's QS6/7/8/R specification and was then confirmed against the
instrument. Where the two disagreed, the instrument won and
`docs/RESOLUTION_NOTES.md` says so.

The unit reports itself as QS family member **7**. Alesis's published list
covers QS6, QS7, QS8 and QSR and stops; 7 appears to be recorded nowhere
else.

## The five banks

| bank | CC 0 | front panel | can be read back |
|------|------|-------------|------------------|
| General MIDI | 0 | yes | no |
| User | 1 | yes | **yes** |
| Preset 1 | 2 | no | no |
| Preset 2 | 3 | no | no |
| Preset 3 | 4 | no | no |

Only the User bank has a dump request. The other four are ROM, so their
names come from a catalog you generate locally; the User bank's come from
the instrument, and the browser marks which is which.

**Bank Select is Controller 0.** The unit ignores Controller 32, which
many sequencers send instead.

## Running it

```
python -m nanosyned.app --demo      # a NanoSynth that is not there
python -m nanosyned.app             # find the real one
python -m nanosyned.cli banks       # the five banks
python -m nanosyned.cli read        # the User bank's names (silent)
python -m nanosyned.cli syx FILE    # read a .syx dump, no hardware
```

`--demo` opens no MIDI port and constructs no bridge, so it is safe to run
beside a session that is driving the hardware.

Keys: `↑↓` move (never sends anything), `⏎` select on the unit, `r` read
names, `/` search, `[` `]` channel, `c` set channel, `f` favourite, `F`
favourites view, `t` tags, `n` note, `i` device, `?` help, `q` quit.

## The name catalog

`nano/data/catalog.json` is **gitignored**. Alesis's program names are
Alesis's work and this project does not redistribute them. Generate it
from your own material:

```
python3 tools/extract_catalog.py --syx my-own-dump.syx
python3 tools/extract_catalog.py --manual my-transcription.txt
```

nanosyned runs without it.

## Development checks

No AI is involved in these. Every tool runs locally, offline except for
`pip-audit`, and each one either passes or fails the build.

```sh
make check        # everything below, in order; stops at the first failure
```

| target | what it runs |
|---|---|
| `make lint` | `ruff check` and `ruff format --check` |
| `make format` | `ruff check --fix` and `ruff format` — **the only target that edits your code** |
| `make typecheck` | `mypy` |
| `make test` | `pytest`, with coverage and a `term-missing` report |
| `make audit` | `pip-audit`, `vulture`, `deptry`, `detect-secrets` |

All configuration lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`,
`[tool.pytest.ini_options]`, `[tool.coverage]`, `[tool.vulture]`,
`[tool.deptry]`), except `.pre-commit-config.yaml` and `.secrets.baseline`.
The dev toolchain is pinned in `requirements-dev.txt`; `make venv` creates
`.venv` and installs it.

`git commit` runs ruff (lint and format), mypy and detect-secrets through
pre-commit, so the same rules apply whether you use `make` or not. If your
venv lives elsewhere, `make check PY=/usr/bin/python3 BIN=/usr/local/bin`.

**shellcheck and shfmt are not wired up.** The repository contains no shell
scripts — no `*.sh` and no file with a bash/sh shebang — so those hooks would
never fire. Add them to `.pre-commit-config.yaml` alongside a script.

### What is enabled, and what is not

**ruff** — rules `E, F, I, B, S, SIM, UP, C4, PL, RUF, C901`, so it replaces
flake8, isort, black and pyupgrade. Asserts are allowed in `tests/` and
nowhere else. The handful of rules that are off are listed in the next
section.

**mypy** — non-strict, because nothing here was written for it. `nano/banks.py`
and `nano/catalog.py` are fully annotated and are held to the individual checks
`strict` would apply; add a module to that list in `pyproject.toml` once it
qualifies.

**pip-audit** — audits what the project declares: `pyproject.toml`'s runtime
dependencies (rendered to a temp file at run time, so it cannot drift) and
`requirements-dev.txt`. It deliberately does *not* audit the whole
environment: the venv inherits the host's site-packages, which reports
vulnerabilities in unrelated system packages.

**No coverage threshold.** There is one, of zero percent enforced — the point
is the `term-missing` table, so you can see what is untested. A floor should be
a number someone agreed to, not one a tool invented.

### What is switched off, and why

Nothing is baselined: `make check` is clean on the whole tree. The few rules
that are off are off because they disagree with how this codebase is written,
not because the code failed them:

- **`PLR2004`** (magic value in comparison) — this is a MIDI/SysEx codebase
  full of wire bytes; comparing against `0x7F`, `100` or `15` is how the
  format is written down, and naming every one would obscure it.
- **`PLC0415`** (import outside the top level) — the CLI and the TUI defer
  Textual and rtmidi so the offline subcommands and the unit tests do not pay
  for importing a TUI framework.
- **`S110`/`S112`** (try/except/pass and /continue) — best-effort teardown on
  the MIDI path: a `close_port` that raises during cleanup must not mask the
  error that got us there.
- **`SIM105`** — `contextlib.suppress` is not this codebase's idiom; the
  explicit `try`/`except` carries a comment saying why in each case.
- **`S101`** — allowed in `tests/`, where `assert` is what a test is for, and
  nowhere else.
- **`PLR0913`** and **`S608`** in `nano/favorites.py` — `Favorites.add` spells
  out every field because it is the schema; the one SQL string interpolates an
  `ORDER BY` clause a placeholder cannot carry, chosen from a fixed set, never
  from input.
- **`C901`/`PLR0912`** in `nanosyned/cli.py` — `main` is the command dispatch
  table; its branches are the commands.

`vulture` reports nothing, `detect-secrets`'s `.secrets.baseline` is empty (no
secrets, no false positives), `deptry` finds no dependency problems and
`pip-audit` finds no known vulnerabilities in the runtime or dev pins.

### One trap worth knowing about

`detect-secrets scan --baseline <file>` **does not check anything.** In v1.5.0
it merges what it just found into the baseline and rewrites it, printing
nothing and always exiting 0. Used as a check it silently accepts new secrets
*and* records them as accepted. The check is `detect-secrets-hook --baseline`,
which compares and exits 1. That is what `make audit-secrets` and the
pre-commit hook run.

## Licence

GPL-2.0-or-later. See `LICENSE`, and `DISCLAIMER.md` for what is verified,
what is inferred, and what is a guess.

AI assistance was used in writing this project; see `DISCLAIMER.md`.
