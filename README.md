<!-- SPDX-License-Identifier: GPL-2.0-or-later -->
<!-- SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors -->

# nanosyned

A terminal browser for the **Alesis NanoSynth** — the 640 programs, the
ones the front panel cannot reach, and the names the unit will tell you.

Sibling to [rxved](../rxved) (Roland XV-2020), [kwsed](../kwsed) (Korg
Wavestation SR), [p2ked](../p2ked) (E-MU Proteus 2000) and
[x5ded](../x5ded) (Korg X5D/X5DR), and it follows their conventions.

## Support this project

nanosyned is free software and always will be. Nothing is behind a paywall, no
feature is withheld, and none of what follows changes that.

But if it has been useful — if it saved you an evening of mapping zones
by hand, or got a library onto a machine that had no way of reading it, or
**best of all, if it has your vintage instrument switched on and in use more often
than it was, and you are having more fun with it** — then please consider
supporting the work.

**Because here is what it has actually cost:**

- **Real machines on a real bench.** Much of what these tools know about these
  formats was measured on hardware rather than read anywhere, because for most
  of it there is nowhere to read it. That needs the machines — the instruments
  themselves — and it puts hours of wear on hardware that has been locked up and
  recovered more than once in the course of it. Some of these instruments were
  bought specifically to add and verify a format; the others were already here,
  because the person doing this is a vintage instrument enthusiast first and the
  projects exist because the instruments were in the room.
- **Dozens — realistically hundreds — of hours of human time.** Format
  reverse-engineering is slow: measure, be wrong, measure again. A single
  parameter law in this README can represent an evening at the bench.
- **AI assistance, which is a paid service**, used heavily throughout and not
  cheap at this volume.

**This is support, not a donation — and the distinction is a legal one, not a
turn of phrase.** The maintainer is based in Germany, where payments like these
are *not* `Spenden` in the tax sense: they count as **taxable income** for the
recipient and are **not tax-deductible** for the giver. So this section is
titled *Support*, deliberately, and no receipt for tax purposes can be issued.
(That is a statement of how it is handled here, not tax advice.)

If the project saved you the work, you can support it through
**[GitHub Sponsors](https://github.com/sponsors/lentferj)** — the *Sponsor*
button at the top of the repository. Payment is handled entirely by GitHub and
Stripe, so bank and tax details are never handed to the person paying.

**Support is not expected, and it is not the only currency.**

- **Bug reports** — ideally with the bank, preset or disk image that produced
  them. A tool's failures are usually specific to one file rather than
  general, and without that file they are very hard to reproduce.
- **Confirmations from hardware that is not on this bench**, which matters more
  here than for a single-machine tool. These tools write for whole *families*
  of instruments, and the bench holds only a subset. Whether a variant accepts
  what we write is genuinely unknown, and several notes say "on this unit" for
  that reason. A "loads fine here too", or a "no, mine refuses it", is worth a
  great deal.
- **Corrections to the reverse-engineering notes.** The wrong turns are
  recorded next to the findings in `docs/RESOLUTION_NOTES.md` — retractions
  included, because a finding that was withdrawn is as useful as one that
  stood. If any of it is wrong in a way that is still costing someone time,
  saying so improves the record.

---

---



## AI assistance & human authorship

nanosyned was built by its human author together with AI assistance. The
**ideas, the project vision, and every feature** came from the human author;
AI assisted with **writing the code and analyzing the binary formats**.
Crucially, the **reverse engineering rests on hands-on human work** — all testing
and verification on real hardware, creating the reference images/banks on those
instruments (disk saves, SysEx probes), and aural A/B comparison of presets —
which is what makes the results correct.
Full account in [DISCLAIMER.md](DISCLAIMER.md).

---
## ⚠️ Use at your own risk — back up first

 is provided **as is, with absolutely no warranty and no liability**
for data loss or **hardware damage**. You assume all risk. Full terms:
[DISCLAIMER.md](DISCLAIMER.md).

Before you use this software, **make good, current backups of all your files** —
and of any existing banks on your instrument and storage media. These tools can
write to hardware and storage media; a mistake, a bug, or untested output could
overwrite or corrupt data, or be rejected by hardware. Always test on a spare
unit or emulator **before** connecting irreplaceable equipment.

---

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

## Install

Two checkouts, side by side — this project and the shared library it uses:

```sh
git clone https://github.com/lentferj/vinsynlib.git ../vinsynlib
python3 -m venv .venv
.venv/bin/pip install --no-deps -e ../vinsynlib
.venv/bin/pip install -e .
```

Needs Python 3.11+, `python-rtmidi` and `textual`, plus **vinsynlib** — the
shared base of this family of terminal instrument tools: the settings cache,
the keymap and legend, the command line and the port listing. It is **not on
PyPI**, so it is installed from the sibling checkout above, and installed
*first* so that the second command finds the requirement already satisfied.

`--no-deps` on the first install because vinsynlib's dependencies are this
project's too, and a second copy of `textual` in the same venv is a version
skew to diagnose somewhere else. With `uv`, `uv sync` takes the path from
`[tool.uv.sources]` in `pyproject.toml`, so the checkout only has to exist
and neither `pip` line is needed.

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
