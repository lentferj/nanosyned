# nanosyned vs p2ked — comparative code audit

Reference: `/home/lentferj/git-repos/p2ked` (E-MU Proteus 2000 terminal tool)
Target:    `/home/lentferj/git-repos/nanosyned` (Alesis NanoSynth terminal tool)
Method:    read both trees in full, quote `file:line` on both sides. No files
           modified. No hardware tests run.

The two projects are siblings in one family and share `vinsynlib`. p2ked is the
more advanced tree by roughly a full generation of features, and nanosyned is
where p2ked was several milestones ago. Every gap below is a place where a
concrete, already-solved problem in p2ked has no counterpart in nanosyned.

---

## Executive summary

nanosyned is a correct, well-documented **read-and-select browser**. p2ked is a
**read / scan / edit / undo / back-up** workbench. The delta is not one feature:
it is five whole subsystems and the shared-library adoption that comes with them.

1. **vinsynlib floor is two minor versions behind** (`>=0.3.1` / MINIMUM `0.2.0`
   vs `>=0.4.2` / MINIMUM `0.4.2`), and nanosyned still reimplements three
   widgets the library now owns (report, prompt, hints are split).
2. **No scan / rebuild / catalog persistence** — names read off the unit are
   lost on exit; p2ked keeps them and scans the whole device.
3. **No ratings**, no rating filter, no `rating_cell`.
4. **No multi/channel pane, no master edit, no FX edit, no write gate, no undo,
   no backup** — the entire write path.
5. **No category / all-ROMs filters, no remembered UI state** beyond the channel.
6. **Testing and tooling are a generation behind**: no `test_no_sound`, no
   `test_legend`, no `test_remembered_state`, no hardware suite, no coverage
   gate, no `measure_send_gap.py` (the exact tool for nanosyned's own TODO #1).

Rough size comparison:

| metric | p2ked | nanosyned |
|---|---|---|
| test files | 21 | 11 |
| `def test_` count | ~700 | ~129 |
| tools/ | 4 | 1 |
| Makefile targets | 17 | 9 |
| vinsynlib pin | `>=0.4.2` | `>=0.3.1` |
| coverage gate | `fail_under = 68` | none |

---

## Category 1 — vinsynlib adoption

p2ked binds to `vinsynlib>=0.4.2` and imports shared modules for the things the
family has already unified. nanosyned pins `vinsynlib>=0.3.1`, gates on
`MINIMUM = (0, 2, 0)`, and still defines or omits several of those modules
locally. This is the root cause of most Category 2 gaps.

### 1.1 Version floor

p2ked `pyproject.toml:19`:
```toml
    "vinsynlib>=0.4.2",
```
p2ked `p2ked/entry.py:57`:
```python
MINIMUM = (0, 4, 2)
```
p2ked `p2ked/entry.py:61`:
```python
SOURCE = "vinsynlib>=0.4.2"
```

nanosyned `pyproject.toml:11`:
```toml
dependencies = ["textual>=0.40", "python-rtmidi>=1.4", "vinsynlib>=0.3.1"]
```
nanosyned `nanosyned/entry.py:41`:
```python
MINIMUM = (0, 2, 0)
```
nanosyned `nanosyned/entry.py:44`:
```python
SOURCE = "vinsynlib>=0.2.0"
```

**Why it matters:** the library grew `ui.report`, `ui.confirm`, `undo`,
`backup`, `build`, `favorites.rating_cell`, the ui-state half of `config`, and
the settings-cache upgrades *after* nanosyned's floor, so nanosyned cannot adopt
them without raising the floor and re-running its entry gate.

### 1.2 `ReportScreen` reimplemented locally

p2ked imports the library's (`p2ked/app.py:91`):
```python
from vinsynlib.ui.report import ReportScreen
```
nanosyned defines its own (`nanosyned/app.py:113`):
```python
class ReportScreen(ModalScreen[None]):
    """A scrollable block of text."""
```
**Why it matters:** the library's frame is the one p2ked fixed to carry and
scroll its help text (p2ked commit `e88e382`); the local copy will drift from
every other tool's report behaviour and misses those fixes.

### 1.3 No `ConfirmScreen`

p2ked imports it (`p2ked/app.py:89`):
```python
from vinsynlib.ui.confirm import ConfirmScreen
```
nanosyned: **no occurrence of `ConfirmScreen` anywhere in the tree.**
**Why it matters:** every destructive or ambiguous action in p2ked is guarded by
the family's confirm modal (scan offer, rebuild, restore, select); nanosyned has
no such widget, so any future guarded action must invent its own.

### 1.4 `PromptScreen` split away from the shared widget

p2ked keeps its own in a module so two screens can share it
(`p2ked/prompts.py:35`, re-exported by `p2ked/app.py:104`), and uses the
library's report/confirm for the rest.
nanosyned folds `PromptScreen` into `app.py` (`nanosyned/app.py:145`):
```python
class PromptScreen(ModalScreen[str | None]):
    """One line of text."""
```
**Why it matters:** p2ked's comment — "a shared widget that lives inside one of
its callers is a cycle waiting to happen" — is exactly the trap nanosyned is in;
the moment a second module needs a prompt there is no place to import it from.

### 1.5 No `vinsynlib.undo`

p2ked imports the timeline (`p2ked/app.py:92`):
```python
from vinsynlib.undo import Record, UndoLog
```
nanosyned: **no occurrence of `UndoLog` / `Record` / `undo`** in application
code (only the word "rating" in a docstring at `nanosyned/app.py:395`).
**Why it matters:** the family's undo log is the mechanism behind `z`/`Z`; without
it nanosyned cannot offer any reversible change, even a local favourites toggle.

### 1.6 No `vinsynlib.build`

p2ked imports the build fingerprint (`p2ked/app.py:87`):
```python
from vinsynlib.build import build_of
```
nanosyned: **no occurrence.**
**Why it matters:** the build string is what a bug report can quote; the family
made it one implementation so two tools cannot report different formats.

### 1.7 `Settings` bound, but not its ui-state half

p2ked binds the whole store (`p2ked/p2k/config.py:93-98`):
```python
load_ui_bool = _settings.load_ui_bool
load_ui_int = _settings.load_ui_int
load_ui_str = _settings.load_ui_str
load_ui_state = _settings.load_ui_state
read_ui_state = _settings.read_ui_state
save_ui_state = _settings.save_ui_state
```
nanosyned binds only the older scalars (`nanosyned/nano/config.py:42-54`):
```python
__all__ = [
    "DEFAULT_PATH",
    "load_channel",
    "load_device_id",
    "load_last_port",
    "load_last_recv_port",
    "load_port_pair",
    "save_channel",
    "save_device_id",
    "save_last_port",
    "save_last_recv_port",
    "save_ports",
]
```
**Why it matters:** the ui-state store is how p2ked remembers where you were
(see 2.13); nanosyned has no ui-state API at all, so it can only ever remember
the channel.

### 1.8 No `vinsynlib.backup`

p2ked has a binding module (`p2k/backup.py`, 9.7 kB) and `p2ked/app.py:60`:
```python
from p2k import backup as bk
```
nanosyned: **no backup module, no occurrence of `backup`.**
**Why it matters:** the family's JSON-envelope backup format ("a version byte,
and never an overwrite") is already solved; nanosyned cannot offer a restore
point for any future write without it.

### 1.9 `rating_cell` not re-exported

p2ked re-exports the library's glyph function (`p2k/favorites.py:50`):
```python
from vinsynlib.favorites import SCHEMA_VERSION, Favorite, rating_cell
```
nanosyned imports only the schema and row (`nano/favorites.py:35-38`):
```python
from vinsynlib.favorites import (
    SCHEMA_VERSION,
    Favorite,
)
```
**Why it matters:** `rating_cell` is the one implementation of what a rating
*looks like*; nanosyned has the `rating` column in its database (schema is the
library's) but no way to render it — a direct symptom of the missing ratings
feature (2.5).

### 1.10 `conformance` / `devchecks` — partial parity

Both use `vinsynlib.conformance` (nanosyned `tests/test_conformance.py:26`,
p2ked `tests/test_conformance.py:29`) and `vinsynlib.devchecks`
(nanosyned `tests/test_config_paths.py:39`, `tests/test_version_gate_copy.py:19`).
But p2ked also runs the **CLI parser** conformance check
(`p2ked/tests/test_conformance.py:137-157`, `conformance.check_flags(cli.build_parser(), ...)`),
and nanosyned checks only the browser parser (`nanosyned/tests/test_conformance.py:32`).
**Why it matters:** p2ked's comment records that the CLI "had drifted: it did
not offer `--config` while it read and wrote the settings cache" — exactly the
class of bug nanosyned's two front ends can still develop unchecked.

---

## Category 2 — feature / UX gaps

### 2.1 Whole-device scan and catalog rebuild

p2ked `p2ked/app.py:3037,3113,3117`:
```python
    def scan_bank_ids(self) -> List[str]:
    def action_scan_device(self) -> None:
    def action_rebuild_catalog(self) -> None:
```
p2ked modal screens `p2ked/scan.py:47` `ScanOfferScreen`, `p2ked/scan.py:107`
`ScanScreen` (with a `threading.Event` cancel, `scan.py:146,172,183`), and a CLI
front end `p2ked/cli.py:384` `_cmd_scan`. Keys `S` / `R` are in the legend
(`p2ked/app.py`, KEY_HINTS "S scan device" / "R rebuild catalog") and bound at
`p2ked/app.py:597-598`.

nanosyned reads only the bank the cursor is on (`nanosyned/app.py:607`):
```python
    def action_read_names(self) -> None:
        ...
        entry = banks.bank(self._current_bank)
        if not entry.readable:
            self.notify_status(
                f"{entry.label} is ROM and the protocol has no request for "
                f"it; only the User bank can be read back",
                refused=True,
            )
```
**Why it matters:** p2ked's `S`/`R` turn "build the catalog" from a manual
per-bank chore into one action (and one scriptable CLI command); nanosyned has
no bulk operation at all.

### 2.2 Names read off the unit are not persisted

p2ked stores read names and can write them back (`p2k/catalog.py:195`):
```python
    def set_live_name(self, bank_id: str, program_change: int, name: str) -> None:
```
and `p2k/catalog.py:212`:
```python
    def save(self, path: Optional[str] = None) -> bool:
```
nanosyned's adopt step only touches memory (`nanosyned/app.py:647-649`):
```python
    def _adopt(self, bank_id: str, names: dict[int, str]) -> None:
        for program_change, name in names.items():
            self.catalog.set_live_name(bank_id, program_change, name)
```
and `nano/catalog.py` has **no `save` method** — `__all__` (`nano/catalog.py:50`)
is `["DEFAULT_PATH", "Catalog", "Entry", "empty", "load"]`.
**Why it matters:** in p2ked a name read once survives a restart (the `*`
disagreement marker too); in nanosyned every launch starts from the printed
catalog again and re-reads the User bank on `r`, losing the distinction the
whole catalog module is built around.

### 2.3 ROM/preset names you are not currently playing are not kept

p2ked `p2k/catalog.py:252`:
```python
    def live_name(self, bank_id: str, program_change: int) -> Optional[str]:
```
with the README rule that a ROM you take out of the machine "can still be
browsed, searched and favourited" because its names were kept.
nanosyned `nano/catalog.py:105` has `live_name` but nothing writes a *read* name
to disk (2.2), and there is no scan to read a whole device.
**Why it matters:** the "names are permanent for a ROM" property — the reason
p2ked can browse a ROM after it leaves the machine — does not exist here.

### 2.4 No startup scan offer

p2ked `ScanOfferScreen` (`p2ked/scan.py:47`) is offered when the catalog is empty
and remembers "never" (`p2ked/tests/test_scan.py:122-232`, config key
`scan.offer_dismissed` in `p2k/config.py:93`).
nanosyned announces emptiness and stops (`nanosyned/app.py:274-279`):
```python
        self.notify_status(
            f"{len(self.catalog)} names from the catalog"
            if self.catalog
            else "no catalog -- numbers only. Build one with "
            "tools/extract_catalog.py, or press r to read from the unit."
        )
```
**Why it matters:** a first-run user of p2ked is offered the one action that
fixes the empty screen; a nanosyned first-run user is told to go read the manual
or press one key that only covers one fifth of the banks.

### 2.5 No ratings

p2ked `p2ked/app.py:2485` `action_edit_rating`, `p2ked/app.py:2594`
`action_rating_filter`, bound at `p2ked/app.py:586-587`:
```python
(Binding("asterisk", "edit_rating", "Rating"),)
(Binding("V", "rating_filter", "Rating filter"),)
```
nanosyned has an empty rating slot: `KEY_HINTS` (`nanosyned/app.py:85-100`) has
no `*`/`V`, `BINDINGS` (`nanosyned/app.py:197-213`) has neither key, and the
only mention of rating is a comment at `nanosyned/app.py:395` about toggling a
favourite preserving "a rating, tags, a note".
**Why it matters:** the library schema already stores ratings; nanosyned stores
a rating it can never set, filter or display.

### 2.6 No multi / channel pane

p2ked has a whole module, `p2ked/multi.py` (103 kB: `MultiScreen`,
`ChannelDetailScreen`, `SoundPickerScreen`, `ValuePickerScreen`, `MasterEditScreen`,
`FXEditScreen`), a `m` binding (`p2ked/app.py:580`), and `p2kcli channels`
(`p2ked/cli.py:207`).
nanosyned `KEY_HINTS` and `BINDINGS` have no `m` and there is no multi module.
**Why it matters:** the NanoSynth receives on all 16 channels at once, so "what
is every channel playing, and why not" is a real question this tool cannot answer.

### 2.7 No master edit

p2ked has `p2ked/masteredit.py` (45 kB: `MasterParameter`, `EditGate`,
`EditLog`, `MasterEditor`, `ChannelLog`, `CHANNEL_FIELDS`, `mutate_channel`) and
an `e` door from the multi screen.
nanosyned: no editor, and `TODO.md:85-109` explicitly fences writing as a
5-step armed/back-up/name-the-destination/verify protocol not yet built.
**Why it matters:** this is the largest single subsystem missing, and nanosyned's
own TODO already specifies the exact p2ked shape it should take.

### 2.8 No FX edit

p2ked `FXEditScreen` (in `p2ked/multi.py`), `x` binding at `p2ked/app.py:615`:
```python
(Binding("x", "edit_fx", "Master FX"),)
```
nanosyned has no `x` and no FX block.
**Why it matters:** the QS effects block is dumpable (`nano/dumps.py:39`
`USER_EFFECTS_DUMP`), so the data is reachable; only the editor is missing.

### 2.9 No write gate

p2ked `p2ked/app.py:606`:
```python
(Binding("w", "toggle_write_gate", "Write gate"),)
```
with `action_toggle_write_gate` at `p2ked/app.py:691` and `EditGate` in
`masteredit.py:829`.
nanosyned: no `w`, no gate.
**Why it matters:** the family's rule is that nothing is sent while the gate is
locked and a refusal says which of gate/range it was; nanosyned has no such
safety primitive to build on.

### 2.10 No undo

p2ked `p2ked/app.py:607-608`:
```python
(Binding("z", "undo", "Undo edit"),)
(Binding("Z", "undo_all", "Undo all edits"),)
```
with `action_undo`/`action_undo_all` at `p2ked/app.py:695-713` and
`_undo_master_edits` at `p2ked/app.py:1472`.
nanosyned: no `z`/`Z`.
**Why it matters:** in p2ked even a local favourite toggle is on the same undo
timeline, so `z` is a general "put that back", not an edit-only key.

### 2.11 No backup / restore

p2ked `p2kcli backup` (`p2ked/cli.py:604` `_cmd_backup`, subcommands at
`p2ked/cli.py:781-792`), automatic pre-write save at `p2ked/app.py:1132`
`_backup_before_write`.
nanosyned: no backup command or module.
**Why it matters:** the whole-setup write p2ked's per-channel edit performs is
only safe because a restore point is written first; nanosyned has neither the
write nor the restore point.

### 2.12 No category / all-ROMs filters

p2ked `p2ked/app.py:591-592`:
```python
(Binding("C", "pick_categories", "Categories"),)
(Binding("a", "toggle_all_roms", "All ROMs"),)
```
nanosyned `KEY_HINTS`/`BINDINGS`: neither key.
**Why it matters:** the NanoSynth's own 16 front-panel categories are modelled in
`nano/banks.py:134-151` (`CATEGORIES`, `Slot.category`), so the filter p2ked
offers is buildable here from data nanosyned already has.

### 2.13 Remembered UI state is channel-only

p2ked remembers bank row, preset cursor, favourites view, rating filter,
category filter and scan dismissal (`p2k/config.py:89-98`, README "ui-state.toml").
nanosyned remembers only the channel (`nanosyned/app.py:341-351`):
```python
    def _remember_channel(self, channel: int) -> None:
        """Save it for next time. Only OSError is swallowed."""
        path = self._config_path
        if path is None:
            return
        from nano import config

        try:
            config.save_channel(channel, path)
        except OSError:
            pass
```
**Why it matters:** p2ked's "where you left the screen" also fixes a real bug
class (a filter you cleared must not come back), which nanosyned has no store to
implement against.

### 2.14 Device info does not report installed ROMs

p2ked's `i` shows the hardware configuration, including SIMMs
(`p2ked/app.py:558` `hardware_config`, README "device.png" marker `SIMM`).
nanosyned's `i` shows only identity (`nanosyned/app.py:696-747`), and there is
no configuration request — correctly, since the NanoSynth's ROM banks are fixed
(`nano/banks.py:166-208`).
**Why it matters:** parity here is a *deliberate* gap, not a defect; it is only
listed so the inventory is complete and so a reader does not "fix" nanosyned
into asking a question this unit has no answer for.

### 2.15 Favourites view key diverges from the family deliberately

p2ked moved the view to `v` (`p2ked/app.py:588`) and documents why
(`p2ked/tests/test_conformance.py:113-130`: "`f` writes the favourites database
and cycling the view only reads it, so the shift-pair left a write one slip away
from a read").
nanosyned still uses `F` (`nanosyned/app.py:94` KEY_HINTS "F favourites view",
`nanosyned/app.py:205` `Binding("F", "cycle_favorites", ...)`).
**Why it matters:** nanosyned kept the exact `f`/`F` shift-pair that p2ked and
rxved both moved off for safety; this is a correctness/adjacency issue, not taste.

### 2.16 Key hints are a subset

p2ked `KEY_HINTS` (`p2ked/app.py:191-250`) includes ratings, `m`, `v`, `C`, `a`,
`S`, `R`, `x`, `w`, `z`, `Z`, `+ -`, `space`, `s`.
nanosyned `KEY_HINTS` (`nanosyned/app.py:85-100`) has none of those.
**Why it matters:** the legend is the family's promise of which keys work;
every missing line above corresponds to a missing capability.

### 2.17 Refused styling — parity (no gap)

Both implement it: nanosyned `nanosyned/app.py:544-546`
(`notify_status(..., refused=True)` → `"[b]refused[/b] · "`); p2ked the same
shape via its own status helper. Recorded so the audit is not one-sided.

### 2.18 No-sound guarantee is untested

p2ked has a dedicated module (`p2ked/tests/test_no_sound.py`) that (a) runs every
read against a recording port and asserts only SysEx went out
(`tests/test_no_sound.py:112-173`) and (b) does a structural AST check that
`select()` is the only non-SysEx send site (`tests/test_no_sound.py:213-254`).
nanosyned has no equivalent; `select` is only wired to Enter
(`nanosyned/app.py:560-563`) but nothing enforces that.
**Why it matters:** nanosyned's own `README.md:168` promises "moving the cursor
never sends anything" and `TODO.md:127-136` says this is "enforced by tests
against a fake" — the guarantee p2ked formalises is the one nanosyned most needs.

---

## Category 3 — testing gaps

nanosyned's suite is real and well-written, but it covers only the read path.

| missing test | p2ked equivalent | what it protects |
|---|---|---|
| `test_no_sound.py` | 12 tests | reads emit only SysEx; `select` is the sole audible site |
| `test_legend.py` | 13 tests | `wrap_blocks` never truncates; workers only do MIDI; no pathless config |
| `test_scan.py` | 15 tests | scan scope, ROM-vs-user keeping, offer lifecycle, cancel |
| `test_remembered_state.py` | 33 tests | ui-state round-trips and clears |
| `test_modal_ux.py` | 69 tests | modal dismiss/exit behaviour |
| `test_masteredit.py` | 79 tests | gate, read-back, undo, channel fields |
| `test_channel_edits.py` | 63 tests | per-channel write round trip |
| `test_multi_edits.py` | 58 tests | multi screen editing |
| `test_backup.py` | 24 tests | backup envelope, list, restore |
| `test_catalog.py` | 8 tests | printed vs read names, persistence |
| `test_roms.py` | 38 tests | bank arithmetic |
| `test_hardware.py` | 10 tests | reads on a real unit (`make test-hardware`) |
| `test_audit_fixes.py` | 30 tests | regressions from review |

Also:
- **CLI conformance** — p2ked `tests/test_conformance.py:137` checks
  `cli.build_parser()`; nanosyned `tests/test_conformance.py` checks only the
  browser parser.
- **Coverage gate** — p2ked `pyproject.toml:328` `fail_under = 68`; nanosyned
  `pyproject.toml:35-36` deliberately has none ("Add fail_under once the number
  is understood"). p2ked's rationale for gating is on record
  (`README.md:682-689`), and its two low modules are named.
- **No hardware suite** — p2ked `Makefile:120` `test-hardware`; nanosyned has
  none, though `TODO.md` item 8 ("can the browser sit open beside a sequencer")
  is exactly a hardware-suite question.

**Why it matters:** p2ked's coverage is *behavioural* — it pins the negative
properties (cursor sends nothing, modal can be left, config is not written into
the checkout) that are the easiest to regress silently and the most expensive
when they fail against real hardware.

---

## Category 4 — tooling gaps

### 4.1 Makefile

p2ked `Makefile` targets (`grep -n '^[a-z-]*:'`): `help, install, install-hooks,
lint, format, format-check, typecheck, test, coverage, test-hardware, audit,
audit-vulns, audit-deadcode, audit-deps, audit-secrets, secrets-update, check,
ci, pre-commit-run, clean`.

nanosyned `Makefile` targets: `help, check, lint, format, typecheck, test,
audit, audit-vulns, audit-deadcode, audit-deps, audit-secrets, venv`.

Missing: `install`, `install-hooks`, `format-check`, `coverage`, `test-hardware`,
`ci`, `pre-commit-run`, `clean`, `secrets-update`.

Notable:
- p2ked `Makefile:99` `coverage:` runs pytest with the `fail_under` gate; p2ked
  `Makefile:102-104` explains it is in `make check` on purpose.
- p2ked `Makefile:120-121`:
  ```make
  test-hardware: ## tests that need a real Proteus 2000 (opens MIDI ports)
  	$(PYTEST) tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s
  ```
- p2ked `Makefile:157` `secrets-update` regenerates `.secrets.baseline`.

**Why it matters:** `format-check`, the coverage gate and `test-hardware` are
the three targets that turn "passes on my machine" into "passes reproducibly",
and `pre-commit-run`/`ci` make the Makefile the single source of truth (p2ked
`README.md:631-636`).

### 4.2 Dev tools

p2ked `tools/`: `capture_screenshots.py` (13.4 kB), `extract_catalog.py`
(16.5 kB), `import_favourites.py` (6.0 kB), `measure_send_gap.py` (12.4 kB).
nanosyned `tools/`: `extract_catalog.py` only.

- **`measure_send_gap.py`** is directly relevant to nanosyned `TODO.md:15-25`:
  > "`SEND_GAP` and `SELECT_GAP` are guesses … Neither has been measured."
  It reads a bank at a series of gaps, compares each read against a reference
  (`p2ked/tools/measure_send_gap.py:121-146`), and reports "the interesting
  failure is not a timeout: it is a reply belonging to the *previous* request".
  nanosyned's `SEND_GAP`/`SELECT_GAP` (`nano/bridge.py:84,87`) are the same
  guesses p2ked measured away.
  **Why it matters:** this is the single highest-value tool to port — it closes
  an open TODO item and validates the exact mis-filing hazard nanosyned's
  `request(number=...)` check exists to prevent.
- **`capture_screenshots.py`** drives the app headlessly, exports SVG, converts
  to PNG, and asserts text markers per shot (`p2ked/tools/capture_screenshots.py:66-82,132-137`).
  nanosyned's `README.md` has no screenshots at all.
  **Why it matters:** screenshots are how the family's READMEs stay honest about
  the UI; without the script they are hand-made and rot.
- **`import_favourites.py`** imports a `[BANK]`/`PC nnn name` listing into the
  favourites DB, with `--dry-run`/`--replace`/`--skip-uncertain` and a
  "faint mark → `check-scan` tag" rule (`p2ked/tools/import_favourites.py:17-34,81-162`).
  nanosyned has no importer.
  **Why it matters:** it is the only route from a paper/scan favourite list into
  the database, and it reuses the same `Favorites` binding nanosyned already has.

### 4.3 Pre-commit

p2ked `.pre-commit-config.yaml` pins `ruff` `--exit-non-zero-on-fix`, runs
`mirrors-mypy` pinned to `v2.4.0` with `additional_dependencies`, and pins
`detect-secrets` `v1.5.0`.
nanosyned `.pre-commit-config.yaml:13-39` runs `ruff --fix`, a **local** mypy
(`.venv/bin/python -m mypy`), and `detect-secrets`.
**Why it matters:** the local-mypy hook is defensible (nanosyned documents why:
textual/rtmidi are not in the hook env), but nanosyned lacks
`--exit-non-zero-on-fix` and the secrets-regeneration target, so `git commit`
and `make check` are held to slightly different standards than p2ked's identical
pair.

---

## Category 5 — recent p2ked git fixes nanosyned lacks

`git log --oneline -45` in p2ked, newest first, mapped to the gap it closes.
None of these commits has a counterpart in nanosyned (`git log --oneline -25`,
whose latest work is the `vinsynlib 0.3.1` adoption and version-gate copy).

| p2ked commit | what it did | nanosyned gap |
|---|---|---|
| `2f0bb14` | raise vinsynlib floor 0.4.1 → 0.4.2 | still at 0.3.1 (1.1) |
| `ed70c1d` | `p2kcli scan` pipe front end | no scan CLI (2.1, 4.2) |
| `026aa5f` | whole-device scan + rebuild catalog | no scan (2.1) |
| `54edae8` | keep names read off a unit; show ROMs not playing | no persistence (2.2, 2.3) |
| `96b03d4`,`ccd9889`,`4717685` | screenshot pipeline + 15 shots | no screenshots (4.2) |
| `e88e382` | library report frame carries + scrolls help | local ReportScreen (1.2) |
| `10bb7de`,`a389951` | undo timeline is the library's `UndoLog` | no undo, no binding (1.5, 2.10) |
| `854e659` | backup the setup before the first write | no backup (1.8, 2.11) |
| `9f88c99` | `rating_cell` is the library's, re-exported | not re-exported (1.9, 2.5) |
| `6a77ad3` | run on 0.4.0: pin, entry gate, drift check | older floor (1.1) |
| `bd224a8` | ratings: column, picker, filter, local undo | no ratings (2.5) |
| `dd504e6` | coalesce a burst of nudges, one write in flight | no writer (2.7) |
| `8e51eb1` | `_has_floor_at` — the not-at-nothing rule in one place | n/a |
| `5219cfd` | the channels are editable | no multi screen (2.6) |
| `5d96165`,`3429768` | dump writes back byte-exact; setup dump encoder | no writer (2.7) |
| `ba3e435` | per-channel edit writes the dump back | no writer (2.7) |
| `e16f14f` | undo from the multi screen + FX block on master editor | no multi/master/FX (2.6-2.8) |
| `73b2331`,`fb0ac77` | master FX editor | no FX (2.8) |
| `5117967` | edit path tested, `--allow-write`, undo from browser | no gate (2.9) |
| `f78cef5` | leave the modal, see the edit, undo either kind | no modals/undo (1.3, 2.10) |
| `22c2fb1` | family devchecks: `iter_test_sources`, foreign imports | partially adopted (1.10) |
| `cd97901` | retry `m` until the screen is up (test race) | no multi tests (3) |
| `85acd06`,`5219cfd` | multi screen editable, documented | — |

**Why it matters:** these are not stylistic fixes; each is a solved correctness
or reproducibility problem, and nanosyned is the tree that still has the
problem. `e88e382` (report scrolling) and `cd97901` (test race) are the two that
will bite nanosyned first once it grows modals.

---

## Suggested priority order

1. **Raise the vinsynlib floor to 0.4.2** and adopt `ui.report`, `ui.confirm`,
   `undo`, `backup`, `build`, `favorites.rating_cell`, and the `config` ui-state
   half. Everything else is cheaper after this. (Category 1.)
2. **Port `tools/measure_send_gap.py`** and close `TODO.md` item 1 (measured
   `SEND_GAP`/`SELECT_GAP`). (4.2.)
3. **Catalog persistence + whole-device scan + startup offer**, then `nanocli
   scan`. (2.1-2.4, 3.)
4. **Ratings** (`*`, `V`) using the already-stored column. (2.5.)
5. **Testing/tooling parity**: `test_no_sound`, `test_legend`,
   `test_remembered_state`, CLI conformance, `make coverage` with a gate,
   `make test-hardware`. (3, 4.1.)
6. **The write path** (gate → master edit → multi → FX → backup → undo), in
   p2ked's order and shape, once `TODO.md:85-109` is satisfied. (2.6-2.11.)
