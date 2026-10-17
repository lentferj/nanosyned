# Comparative code audit: `emorphed` (reference) vs `nanosyned` (target)

Date: 2026-10-17.
Reference: `/home/lentferj/git-repos/emorphed` (git `c1f1847`).
Target: `/home/lentferj/git-repos/nanosyned` (git `16e3a95`).
No files were modified; no hardware tests run.

Everything below is a concrete, actionable gap: emorphed has it (or fixed it),
nanosyned does not (or did it an older way). Line numbers are verified.

---

## 1. vinsynlib adoption inventory

nanosyned depends on `vinsynlib>=0.3.1` (nanosyned/pyproject.toml:11) and
gates at `MINIMUM = (0, 2, 0)` (nanosyned/nanosyned/entry.py:41). emorphed
asks `vinsynlib>=0.4.2` (emorphed/pyproject.toml:11) and gates at
`MINIMUM = (0, 4, 2)` (emorphed/emorphed/entry.py:41-44). nanosyned's two
numbers disagree with each other (0.3.1 vs 0.2.0), and both lag the library
API emorphed is written against. Installed vinsynlib is 0.4.2
(vinsynlib/src/vinsynlib/__init__.py:59 `__version__ = "0.4.2"`).

### 1.1 Modules emorphed binds that nanosyned does not use at all

| vinsynlib module | emorphed usage | nanosyned status |
|---|---|---|
| `undo` (`UndoLog`, `Record` + plan/settle seam) | emorphed/emorphed/app.py:90, 296-421, 1175-1277 | absent — no undo of any kind |
| `ui.confirm.ConfirmScreen` | app.py:87, 1078-1083, 1945-1948 | absent — no confirmation screens exist |
| `ui.modals.RatingFilter(SCREEN)`, `ChoiceScreen` | app.py:88, 1444-1457; midimapui.py:35 | absent — no rating UI at all |
| `ui.work` (`BusyGate`, `QUIET_BRIDGE_ERRORS`, `close_when_idle`) | app.py:89, 120-126, 341-349, workers, 2533 | absent |
| `ui.report.ReportScreen` (frame) | emorphed/emorphed/screens.py:61-68 (thin subclass) | reimplemented locally, app.py:113-143 |
| `ui.prompt.PromptScreen` | screens.py:37 re-export | reimplemented locally, app.py:145-175 |
| `build.build_of` (about line) | app.py:84, 2377-2389; screens in `?` help | absent — `?` and CLI --help never name the vinsynlib build |
| `keys.legend` (legend built from extras) | screens.py:97-130 | legend hardcoded, app.py:85-100 |
| `livenames` (sidecar cache) | emu/livenames.py; app.py:78, 2060-2078, 2501-2506 | absent — names read from the unit die with the process |
| `backup` (envelope) | emu/backup.py (whole module) | absent |
| `render` (`table`, `progress`) | cli.py:30, 41-42, 427 | reimplemented, cli.py:44-62 (local `_table`) |
| `catalog` (make_key/split_key/UNNAMED/manager) | emu/catalog.py:42-54, 73-129 | reimplemented wholesale, nano/catalog.py:57-176 |
| `config` UI-state API (`UNSET`, `load_ui_state/int/bool`, `save_ui_state`) | emu/config.py:40, 76-80 | absent — nano/config.py:40-54 exports only the 0.2.0 port/device pair |
| `cli` `device_id`/`allow_write` argument blocks | app.py:2407-2415; cli.py:466-478 | only the 0.2-era flags, app.py:799-808, cli.py:291-301 |

Evidence for why the missing `undo`/`ui.work` adoption matters:

- emorphed/emorphed/app.py:88-90:
  ```python
  from vinsynlib.build import build_of
  from vinsynlib.cli import add_common_arguments, make_parser, validate_common
  from vinsynlib.keys import wrap_blocks as _wrap_blocks
  from vinsynlib.ui.confirm import ConfirmScreen
  from vinsynlib.ui.modals import RatingFilter, RatingFilterScreen
  from vinsynlib.ui.work import QUIET_BRIDGE_ERRORS, BusyGate, close_when_idle
  from vinsynlib.undo import Record, UndoLog
  ```
  nanosyned/nanosyned/app.py:65-68 imports only `cli`, `keys`, `ui.hints`.

### 1.2 Modules both bind, nanosyned older / thinner

- **config**: `nano/config.py:40` uses `Settings` but does not re-export
  `UNSET` or the 0.4.0 UI-state wrappers. emorphed needs them for
  rating-filter persistence and window-state restore
  (emorphed/emorphed/app.py:81 `from emu.config import UNSET`; 1459-1517).
- **favorites**: `nano/favorites.py:35-38` imports `SCHEMA_VERSION`,
  `Favorite` only; emorphed also re-exports `rating_cell`
  (emu/favorites.py:35-39) used by the CLI's favourites table (cli.py:201,
  284). In nanosyned there is no rating display anywhere — see §2.6.
- **version gate**: same `_release_parts` copy (kept honest by the same
  `devchecks.release_parts_drift` test on both sides,
  tests/test_version_gate_copy.py), but nanosyned's floor is two library
  generations behind while the pyproject claims 0.3.1 — a user installing
  0.2.x passes the gate and hits `AttributeError`s at runtime.

---

## 2. Feature / UX gaps

### 2.1 Undo (`z`/`Z`) — missing entirely

- emorphed: every mutating action pushes a `Record` into `UndoLog`
  (app.py:204-224 `_ChangesView.append`, `_change_label`); `z`/`Z` replans
  through `self._undo_log.plan(...)` (app.py:1175-1277
  `_undo_master_edits`), refusing under a locked gate first (1177-1190).
- nanosyned: `f`, tag and note edits (app.py:377-451) are irreversible;
  there is no `z` binding at all (BINDINGS list app.py:197-213).
- Why: undo is the one safety net for the favourites store the user's own
  work accumulates in; vinsynlib.undo already implements the seam, so the
  port is entirely mechanical.

### 2.2 Window/screen state restore and persistence — missing

- emorphed restores bank row, slot cursor, `view_mode` and `kind_view`
  from the config's ui-state at `__init__` (app.py:351-406:
  `_cfg.load_ui_int("bank_index", ...)`, `"slot_cursor"`, ...), clamps the
  saved cursor to the fill (app.py:1357-1368), and saves on every move
  (`_save_ui_state`, app.py:1481-1517; `_remember_channel` 1545-1554,
  `_remember_device_id` 1591-1599).
- nanosyned: `on_mount` always fills the first bank and focuses the bank
  table (app.py:272-273); `on_data_table_row_highlighted` refills without
  any save or even an unchanged-bank guard:
  ```python
  # nanosyned/app.py:553-556
  row = event.cursor_row
  if 0 <= row < len(self._bank_ids):
      self._fill(self._bank_ids[row])
  ```
  emorphed guards the same handler with `if bank_id != self._current_bank:`
  (app.py:1860-1862) and explains why (idempotency, app.py:1854-1859).
- Why: every restart lands the user on bank 1 row 0 and re-fires refills
  for the bank already shown; the state has nowhere to live because the
  ui-state wrappers were never adopted.

### 2.3 Refusals are a text prefix, not the family's red bold bar

- emorphed: committed `eb98ff4 errors: a refusal is a red bold bar, the
  family's refused class`; CSS app.py:246-254
  (`#status.refused { background: $error; ... text-style: bold; }`) and
  `notify_status` (app.py:1832-1841) does `status.set_class(refused,
  "refused")`.
- nanosyned: informatics still the old prefix shape, app.py:544-546:
  ```python
  def notify_status(self, message: str, *, refused: bool = False) -> None:
      prefix = "[b]refused[/b] · " if refused else ""
      self.query_one("#status", Static).update(prefix + message)
  ```
- Why: a refusal must read as red at a glance, not as another grey
  sentence; this is exactly what emorphed's own commit says was wrong
  with the prefix shape.

### 2.4 Markup escaping (`text.py`) — absent; scroll-crash bug is live

- emorphed fixed this in `1c5d2e2 text from the unit is escaped before it
  meets markup -- the scroll crash` and keeps a regression test
  (tests/test_markup_crash.py, 5 tests, plus emorphed/text.py:27-42
  `literal()`).
- nanosyned: instrument names, search hits, tags and notes go into
  markup-parsed widgets unescaped:
  - `app.py:495` `name = self.catalog.display_name(...)` → `table.add_row(...)`
    (DataTable cells are markup; a User-program name containing `[`
    kills the pane);
  - `app.py:666-674` search hits → `ReportScreen` (a `Static`, markup);
  - `app.py:394-399` favourite status line `f"...{name}"` includes the
    name raw.
  There is no `literal()` equivalent anywhere in the repo (no `escape`
  symbol in nanosyned/nano, verified by grep).
- Why: the NanoSynth's User bank is user-editable, so `[...]` in a live
  name is exactly as reachable here as on the Morpheus.

### 2.5 Honest "no catalog yet" startup line + scan offer

- emorphed distinguishes three startup states (app.py:1369-1388:
  `"{printed} names from the catalog · {live} read from the unit"`,
  `"...read from the unit (no printed catalog)"`, `"no names yet -- press
  r ..."`), and offers a scan when truly empty (`_maybe_offer_scan`
  app.py:2089-2118 + ScanOfferScreen with remembered dismissal in
  emorphed/scan.py:22-118 and `scan_offer_dismissed` persistence
  app.py:2100-2135).
- nanosyned: two states only (app.py:274-279), no scan offer; and since
  livenames are missing (§1.1) the second state ("read from the unit only")
  cannot even exist — a restart with a full set of live names reports
  "no catalog -- numbers only" until `r` is pressed again, which emorphed's
  `66e83d1 browser: names read off the unit count as names` explicitly
  fixed as lying to the user.
- Why: the offer-on-empty and "the unit supplied them" wording are user
  trust beats; nanosyned currently under-reports what it knows.

### 2.6 Ratings and rating filter — missing although the store supports them

- The database layer already has ratings (vinsynlib favorites; `toggle`
  keeps them: nanosyned/app.py:394-397 comment). But nanosyned has no key
  to set a rating and no `RatingFilterScreen`: `grep set_rating` in
  nanosyned hits only a comment. BINDINGS (app.py:197-213) has neither
  `*` nor `V`.
- emorphed: `Binding("asterisk", "edit_rating")` + `Binding("V",
  "rating_filter")` (app.py:274-275), filter persistence
  (`rating_stars`/`rating_at_least`, app.py:1459-1476).

### 2.7 Favourites view key: family `F` → deliberate `v` swap not adopted

- emorphed (and rxved/p2ked) moved the favourites view off `F` because `f`
  writes the DB and `F` is one shift-slip away from it (app.py:267-271
  comment; screens.py:97-112 `_view_key`; conformance records the
  divergence, tests/test_conformance.py:63-74).
- nanosyned still binds `f` favourite and `F` cycle (app.py:204-205).
- Why: the shared keymap change post-dates nanosyned; the swap is a
  safety change about a write sitting one keypress from a read.

### 2.8 KeyHints footer height fix — absent

- emorphed/emorphed/screens.py:71-91 subclasses the library `KeyHints` and
  forces `call_after_refresh(self.refresh, layout=True)` after each
  re-wrap, because the library's first render happens before the widget
  has a width and "the footer stays that tall ... until the terminal is
  resized" (screens.py:73-82). Nanosyned uses the raw widget
  (app.py:67, `yield KeyHints(KEY_HINTS)` at app.py:246), so the footer
  keeps the fixed bug shape.

### 2.9 `i` device info is not busy-guarded — concurrent MIDI traffic

- nanosyned/app.py:682-683:
  ```python
  def action_device_info(self) -> None:
      self._info_worker()
  ```
  No `_busy` check and no claim: pressing `i` during the 128-request
  `r` read interleaves two exchanges on one MIDI port (the `self._lock`
  serialises frame-wise but not exchange-wise — the report can swallow the
  read's replies). Compare emorphed app.py:2233-2240
  (`if self._busy: ...; if not self._exchange.acquire(blocking=False): ...
  ; self._info_worker()`).
- Why: `r` on this unit sends 128 requests; overlapping traffic is the
  exact failure the codebase's own comment about "data format error"
  (app.py:583-585) warns of.

### 2.10 Names read from the unit do not refresh favourites

- emorphed `r`/scan adoption calls `self.favorites.refresh_names(...)`
  (app.py:2056-2059) so favourite rows show the unit's names.
- nanosyned `_adopt` (app.py:647-656) writes the catalog and refills, but
  never touches the favourites store; a favourited program keeps its
  old name until the row is toggled.
- Why: stale names in the favourites table are a wrong answer the store
  already has an API to fix.

### 2.11 Sweep announcements, `swept`/`probe_seconds`, and `--port` pair saving

- emorphed sets `bridge.swept`/`probe_seconds` (emu/bridge.py:148-152,
  679-680) and both front ends print one line when the launch swept:
  app.py:2362-2374 `_say_sweep`, cli.py:614-619.
- nanosyned's `NanoBridge` has neither attribute nor any report
  (nano/bridge.py:153-232); the TUI probe prints only
  `"probing {n}..."` (app.py:860). Additionally, the `--port` path never
  records the port pair: nanosyned app.py:869-872 saves only the channel
  (`cfg.save_channel(...)`), while emorphed saves port, recv port and
  device id on the same path (app.py:2490-2499). In nanosyned every
  explicit `--port` run is followed by a full sweep on the next bare
  launch.
- Why: a slow swept launch silently looks like the fast path — the exact
  `69a3829 Stop sweeping every port on every launch` regression nanosyned
  fixed once and is reintroducing at the margins.

### 2.12 Exit that closes the port under a live worker

- nanosyned app.py:887-891: `finally: store.close(); device.close()` —
  straight close, which can close a port while `_read_worker` still holds
  `self._lock`. emorphed closes through the library's idle-aware helper:
  app.py:2533 `with close_when_idle(device, gate=app._busy_gate): pass`.
- Why: the whole `ui.work` seam exists to make "quit after quitting mid
  read" safe; nanosyned adopted the 0.2-shape hand-close.
  (nanosyned does have `install_clean_exit` for SIGTERM,
  nano/bridge.py:127-151 — a nicety emorphed lacks; noted as reverse-direction, §7.)

### 2.13 CLI: no favourites, tags or ratings commands at all

- emorphed cli.py:504-531 has `fav` (`--add/--remove/--rate/--tags/
  --note/--tag/--search/--rating-at-least/--order`, mutually exclusive
  rating flags at 518-527) and `tags`; tested by tests/test_cli_favorites.py
  (12 tests).
- nanosyned cli.py:302-320 has `ports/banks/list/status/current/read/
  mixes/select/syx/find` — nothing to add, remove, rate, tag or search
  favourites offline. The browser is the only surface.
- Why: the store is SQLite in the data dir, already attached by the CLI
  path; the commands are the vinsynlib.favorites API plus a table.

### 2.14 CLI table/progress rendering is a local copy, and can lie about width

- nanosyned cli.py:44-62 reimplements `_table` (no width cap, no `…`
  truncation); progress is ad-hoc `f"  {done}/{total}"` (cli.py:174-176,
  197-199). emorphed uses `vinsynlib.render.table/progress`
  (cli.py:41-42, 427), which caps to 79 columns and renders `label
  n/total` properly (vinsynlib/src/vinsynlib/render.py:10-13, 78).
- Why: family outputs should be identical; nanosyned's can overflow the
  terminal and format differently from its siblings.

### 2.15 Read-back-verified writes / midimap editor / scan screen — n/a with an analogue

The midimap editor (emorphed/edit.py + midimapui.py) is Morpheus-specific;
nanosyned has no write path by design (nanosyned/TODO.md item 6 spells out
the required shape: arm-then-fire, backup first, name what is destroyed,
read-back verify). Not a gap today — but §1.1's undo/confirm/work seams
are the dependencies of that shape, and they are all absent, so TODO 6
currently cannot be implemented the family way without first landing
vinsynlib 0.4 adoption.

### 2.16 Help text is missing the build/about line

- emorphed `?` shows `_build_line()` (app.py:2306-2309,
  2377-2389): "built from emorphed X (sha, tag) and vinsynlib Y".
- nanosyned app.py:749-750 shows `_HELP` only; the CLI's `--version`
  comes from `make_parser(distribution=...)` but never names the shared
  library. Support triage can't tell which vinsynlib the user has.

---

## 3. Structural / pattern gaps

### 3.1 Module layout does not match the family shape

- emorphed splits on the rxved shape: `emorphed/screens.py` ("This module
  holds every widget the application opens ... It imports nothing from
  emorphed.app", screens.py:12-18) and `emorphed/text.py` (cycle-free,
  text.py:17-19).
- nanosyned keeps `ReportScreen`/`PromptScreen` inside `nanosyned/app.py`
  (app.py:113-176), imports `textual.widgets.{Input,Label}`,
  `ModalScreen`, ... at top level just for them (app.py:59-61), and has no
  text module. The screen stubs local to app.py are also untyped
  (`class NanosynedApp(App):` app.py:178, `events` untyped at 550).
- Why: the split is what keeps screens importable by tests and
  midimapui-like overlays without an app cycle; nanosyned has already
  begun drifting from it (its own docstring at screens.py:14-17 is the
  stated reason for the layout).

### 3.2 Worker error handling: broad `except Exception` — the family moved to a curated quiet set

- nanosyned app.py:595, 640, 691 all do `except Exception as exc:` and
  print `f"select: {exc}"`. That swallows programming errors
  (`TypeError`, `KeyError`, `AttributeError`) into a status line that
  looks like a device fault.
- emorphed defines `_BRIDGE_ERRORS` (app.py:120-126) as the family's
  `QUIET_BRIDGE_ERRORS` (`ConnectionError, TimeoutError, OSError`,
  vinsynlib/src/vinsynlib/ui/work.py:26-32) plus its own
  `ValueError, LookupError, RuntimeError, SystemError`, and each worker
  catches exactly that (e.g. app.py:474, 800).
- Why: on nanosyned a bug in `_show_info` looks like "device: ..." and
  costs a debugging evening.

### 3.3 No `Device` protocol; CLI/TUI accept an untyped `Any`

- emorphed/emu/device.py:37-81 declares a `Protocol` the clone (demo) and
  bridge both satisfy structurally, with per-method docstrings (e.g.
  `read_parameter` "live scratch-map value ... NOT the stored midimap
  dump", device.py:73-76).
- nanosyned: app.py:822-825 comment declares the device "deliberately
  untyped rather than forced into a Protocol"; the demo (nanosyned/demo.py)
  and `NanoBridge` drift independently — e.g. `DemoDevice._tick`
  (nanosyned/demo.py:124-126) no longer raises a closed-port error, while
  emorphed's `_tick` does (emorphed/demo.py:212-222: "this demo device is
  closed; a real bridge would be a closed port and would fail less
  clearly").
- Why: without the Protocol, a demo that lies about being open lets
  post-close use pass tests that hardware would fail.

### 3.4 Threading seam: no exchange claim, no BusyGate

- emorphed pairs three signals: `BusyGate` + `_exchange`
  `threading.Lock` claim on the main thread (`_busy` reads all three,
  app.py:338-349; e.g. `action_select` claims at 1934-1937, each worker
  releases in `finally`).
- nanosyned uses a `threading.RLock` (app.py:229) plus a boolean `_busy`
  set on the main thread (app.py:586, 619). The `_busy` flag is not
  checked or set on all entry points (`action_device_info`, §2.9), and
  there is no refusal/clear semantics like the gate's `check()/is_busy()`.
- Why: the nanosyned comment for `action_select` (app.py:580-586) shows
  the project already understands the double-worker race; the gate is the
  library's general fix and nanosyned stopped at the old flag.

### 3.5 Catalog: subclass of the library vs a fork

- emorphed `Catalog(_BaseCatalog)` (emu/catalog.py:73-124) inherits the
  shared key grammar (`make_key`, `split_key`, `UNNAMED`), and `load`
  warns on an unparseable file (emu/catalog.py:142-147).
- nanosyned's `Catalog` (nano/catalog.py:68-176) is a second grammar with
  quiet failures: a corrupt JSON file returns `empty()` with no warning
  (nano/catalog.py:192-196 `except (OSError, json.JSONDecodeError):
  return empty()`) — only *skipped rows* warn (214-219). emorphed prints
  `f"warning: {target} could not be read as a catalog"` for the same
  case. It also lacks `live_count`, which its own startup line needs
  (emu/catalog.py:99-108).
- Why: a user who generated a half-broken catalog.json gets "numbers
  only" with no sentence about why.

### 3.6 Catalog load ignores `--catalog` warning parity

Related to §3.5: emorphed's `load` warns via stderr on any read failure
(emu/catalog.py:140-147); nanosyned silently loses the file only on
JSON/OS errors. Behaviour visible to a user typing `--catalog` twice.

---

## 4. Tooling / testing / packaging / docs gaps

### 4.1 Files present in emorphed, absent in nanosyned (git-tracked)

Verified with `git ls-files` diff:

- `.github/workflows/ci.yml` — emorphed runs `uv run --no-sync make check`
  on ubuntu/windows/macos (emorphed/.github/workflows/ci.yml:1-33).
  nanosyned has no `.github` directory at all. Why: the pre-commit and
  Makefile gate exists but nothing enforces it off-home.
- `.opencode/commands/review.md` — emorphed has the review harness
  (priority-ordered findings with file:line evidence; hardware rule at
  review.md:19-21). nanosyned has no `.opencode/` tree. Why: the same
  review loop that produced emorphed's last 40 commits has no entry point
  here.
- `docs/screenshots/*` (15 png/svg), `docs/PROMPT-*.md` (5 prompt ledgers),
  `docs/SQS_NOTES.md` — nanosyned has only `docs/RESOLUTION_NOTES.md`.
  Its README references no screenshots and never shows the browser.
- `tools/bench_bank_numbers.py`, `tools/bench_midimap_write.py`,
  `tools/capture_screenshots.py` — nanosyned has only `extract_catalog.py`.
  The parallel bench files are the write-bench harness; the NanoSynth
  analogue (Aside: TODO item 1 timing, TODO 8 sequencer coexistence) has no
  tool to run with.
- `uv.lock` — emorphed locks the dev set; nanosyned uses
  `requirements-dev.txt` (present, fine) but has no lock for `uv sync`/
  CI parity. Cosmetic given no CI, but the two should match once CI lands.
- `tests/fixtures/invented.ins` + `tests/test_extract.py` (9 tests) —
  nanosyned's `tools/extract_catalog.py` (159 lines) is **completely
  untested**.
- `tests/conftest.py` + `tests/test_hardware.py` (7 tests) — the opt-in
  hardware mechanics: `--hardware` flag,
  `EMORPHED_*`-style env override, session-scoped `unit` fixture whose
  skip message lists the concrete causes (conftest.py:88-94), and the
  `test-hardware` Makefile target (emorphed/Makefile:40-42). nanosyned has
  no hardware suite despite its TODO items 1 and 8 being pure bench
  questions ("Blocked on: a bench session", TODO.md:126-136).
- tests absent by name (both repos otherwise share the same test style):
  `test_catalog.py` (17), `test_store.py` (21), `test_cli_favorites.py`
  (12), `test_report.py` (11), `test_livenames.py` (18),
  `test_markup_crash.py` (5), plus emorphed's large `test_app.py` (69 vs
  nanosyned's 16). Totals: **438 tests in emorphed vs ~134 in nanosyned**
  (counted from `def test_` occurrences).
- nanosyned's `test_bridge.py` has just 2 tests versus emorphed
  `test_protocol.py` (61) + `test_connect.py` (23) + `test_bank_bench.py`
  (7): the wire-format layers (pack/unpack, parsing of foreign and thru
  traffic, machinery of `read_program_names`) are lightly covered even for
  what nanosyned does have.

### 4.2 Makefile

- emorphed has `test-hardware` (Makefile:40-42) with an explicit
  `-o addopts=""` reasoning comment. nanosyned: no hardware target, though
  it already has the `PY`/`BIN` overrides and granular audit targets that
  are *equal or better* (Makefile:52-89).
- nanosyned Makefile lacks nothing else material.

### 4.3 pre-commit

- Both have `.pre-commit-config.yaml` and `.secrets.baseline`.
- nanosyned does not pin down the hook revision comment issue (it pins
  revs too). One difference: emorphed's mypy hook runs
  `.venv/bin/mypy` with `args: [emorphed, emu, tests]`
  (`.pre-commit-config.yaml:21-27`); nanosyned runs
  `.venv/bin/python -m mypy` with no args — equivalent given pyproject
  `files` (nanosyned/pyproject.toml:113). **Not a gap.**

### 4.4 pyproject

- `vinsynlib>=0.3.1` (nanosyned pyproject:11) contradicts the runtime gate
  `MINIMUM = (0, 2, 0)` (nanosyned entry.py:41) — and both are behind
  emorphed's coherent `>=0.4.2` pair (pyproject:11 + entry.py:41).
- mypy: emorphed `strict = true` for the whole tree
  (pyproject:82-89); nanosyned non-strict with two opt-in modules
  (pyproject:107-130). Directional: as modules get typed, the strict floor
  rises; nanosyned's speed is also held back by reimplemented untyped
  local stubs (§2.x).
- nanosyned *ahead* on: `branch = true` coverage (pyproject:30),
  exclusion_lines, testpaths. Keep those when porting.
- Line-length 79 vs 88 and per-file ignores differ (cosmetic, skip).

### 4.5 README

- emorphed sections nanosyned's README lacks: **Command line** (full
  subcommand table with every flag, emorphed/README.md:319-337),
  **Backups** (339-348), **The bench, real hardware** (350-368),
  **Honest limits** (369-401: e.g. "`PRESET_GAP` is a guess ... labelled
  as one; the bench measures it"), **Memory** (143-? "names read off the
  unit go into live-names.json ... Override the path with --live-names",
  README:286-289), **What the browser does** with screenshots (200-318).
- nanosyned documents only four `cli` invocations in "Running it"
  (README:155-166) — `mixes`, `current`, `find` and the subcommand list
  never appear.
- Why: the misleading-absent docs are the same findings as §2 (undo,
  livenames, backups absent *and* undocumented — consistent, but the user
  cannot see what the browser does beyond the key list).

### 4.6 CLAUDE.md / TODO parity

- emorphed CLAUDE.md (192 lines) vs nanosyned CLAUDE.md (127 lines):
  emorphed's carries the write-fencing ledger that matches its implemented
  gate; nanosyned's is fine for scope. TODOs differ by instrument
  (n/a beyond §6 cross-reference).

---

## 5. Git-history fixes in emorphed that nanosyned has not applied

Verified `git -C emorphed log --oneline -40`. Items already covered above
are listed with their commits so the port is greppable:

| emorphed commit | what it is | nanosyned status |
|---|---|---|
| `eb98ff4` refused class bar | §2.3 | absent, app.py:544-546 |
| `efb34f1` window opens where you left it | §2.2 | absent |
| `1c5d2e2` escape unit text before markup | §2.4 | absent |
| `66e83d1` names read off the unit count as names | §2.5 | absent |
| `73272b4` undo pushes back what it did not apply | §2.1 (deeper) | absent |
| `59ca80d` KeyHints footer height | §2.8 | absent |
| `9b21962` scan offer frames itself | §2.5 | absent (partial n/a: single bank) |
| `5dffb16` store read back and checked | n/a (no writes) — TODO 6 fixture | |
| `b48c6e8`/`5774d4c`/`6d34cb7` channel presets + picker | n/a (no midimap) | |
| `security-of-keys` family: the `f`/`F` → `v` swap (log shows it in earlier history; visible at app.py:267-271) | §2.7 | not yet |

The commit `16e3a95` currently at nanosyned's HEAD ("Adopt vinsynlib's
version-gate check, and require 0.3.1") is the last adoption round; every
gap above postdates the round of work that produced it.

---

## 6. Things that look like gaps but are not (verified)

Listed so the eventual fix work does not churn them:

- `--device-id` / `--allow-write` flags absent in nanosyned: the Alesis QS
  wire format has **no SysEx device-ID byte**
  (nano/messages.py:250-252 — the frame is `F0 <ALESIS_ID> <QS_FAMILY>
  <function> <body> F7` with no device id), and nanosyned writes nothing
  yet (TODO 6). emorphed's flags are instrument-shaped, not owed here —
  but `--allow-write` becomes owed the day TODO 6 lands, alongside undo.
- `install_clean_exit` exists only in nanosyned (nano/bridge.py:127-151;
  app.py:833). emorphed has no SIGTERM handler. Reverse-direction
  difference, workable as-is.
- emorphed autodetect sweeps 16 device IDs and orders ports by the
  remembered ID (emu/bridge.py:621-687); nanosyned's single-ID sweep is
  correct for a protocol with no device id.
- Kind views (`k`), regions, hyperpresets — Morpheus-only concepts.
- `Config` device-id persistence absent — ditto.
- `nano/banks.py`/`nano/messages.py`/`nano/records.py` are
  instrument-model modules of the same quality as emorphed's equivalents;
  gaps claimed here are only in what emorphed *adds above* them.

---

## 7. Suggested port order (cheapest → deepest)

1. **text.py + markup escaping** (+ port test_markup_crash.py) —
   30 lines, prevents a live crash (§2.4).
2. **Version-gate/dep alignment**: bump `entry.py` MINIMUM and
   `pyproject` to vinsynlib 0.4.2 (fix the 0.3.1/0.2.0 inconsistency) (§1).
3. **notify_status → refused class** + CSS (§2.3).
4. **config ui-state wrappers** (`nano/config.py` re-exports) →
   **window state restore/save** (§2.2), picked up from
   emorphed app.py:351-406/1481-1517.
5. **KeyHints layout subclass** (§2.8), tiny.
6. **worker error sets** `_BRIDGE_ERRORS` = QUIET_BRIDGE_ERRORS + own
   types; busy-guard `i` (§2.9, §3.2); `close_when_idle` (§2.12).
7. **favorites.refresh_names after reads** (§2.10).
8. **livenames sidecar** (nano/livenames.py binding, `--live-names`,
   apply on boot, save on read) + start-up status trichotomy + scan offer
   (§2.5) + tests (test_livenames.py).
9. **undo seam** (`vinsynlib.undo` + `z`/`Z` for favourite/tags/note) and
   the **`F`→`v` key swap** together with raising the conformance
   divergence line (§2.1, §2.7).
10. **ratings UI** (`*`, `V`, persistence) (§2.6) — needs 8+9.
11. **CLI**: swap local `_table` for `vinsynlib.render`; add
   `fav`/`tags` (+ test_cli_favorites) (§2.13, §2.14).
12. **sweep announcement** (`swept`/`probe_seconds` + one stderr line +
   saving the `--port` pair) (§2.11).
13. **Screens module split + Device Protocol** (§3.1, §3.3).
14. **Harness**: CI workflow, `.opencode/commands/review.md`, docs
   (PROMPT/SQS) — the process tooling emorphed's recent 40 commits ran on
   (§4.1).
15. **conftest.py + make test-hardware + tests/test_hardware.py** when a
   unit is on the bench — TODO items 1 and 8 are its exact subject
   (§4.1).
