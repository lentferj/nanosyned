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

## Licence

GPL-2.0-or-later. See `LICENSE`, and `DISCLAIMER.md` for what is verified,
what is inferred, and what is a guess.

AI assistance was used in writing this project; see `DISCLAIMER.md`.
