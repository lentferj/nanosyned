# Comparative Audit: rxved (reference) → nanosyned (target)

Read-only audit. Every gap cites file:line evidence on **both** sides plus why it matters.
Reference: `/home/lentferj/git-repos/rxved` (XV-2020 tool, 3031-line app, 1418-line CLI, 631 tests).
Target: `/home/lentferj/git-repos/nanosyned` (NanoSynth tool, 896-line app, 396-line CLI, 129 tests).

---

## 1. vinsynlib adoption gaps

rxved tracks vinsynlib 0.4.2 (`rxved/rxved/entry.py` requires `(0, 4, 2)`; commits 6fa0a14, 51d207d). nanosyned froze at 0.3.1 (`nanosyned/nanosyned/entry.py` — MINIMUM `(0, 2, 0)`, pyproject `>=0.3.1`).

### 1.1 `vinsynlib.ui.report.ReportScreen` — not adopted
- rxved: `rxved/screens.py:240-247` —
  ```python
  class ReportScreen(_Frame):
      """rxved's shape: ``enter`` closes as well. Three lines, no rewrite."""

      BINDINGS: ClassVar[list[Any]] = [
          ("escape", "close", "Close"),
          ("q", "close", "Close"),
          ("enter", "close", "Close"),
      ]
  ```
  (commit 51d207d "screens: adopt the library's ReportScreen frame").
- nanosyned: `nanosyned/nanosyned/app.py:113-143` — a hand-written `class ReportScreen(ModalScreen[None])` with its own CSS block (lines 117-124), `compose`, `action_close`; plus a local `wrap_blocks` at `app.py:103-111`.
- Why it matters: nanosyned re-implements library code that already received the family's fixes (frame, quiet-error handling at `vinsynlib/ui/report.py`); every library fix must be re-done locally.

### 1.2 `vinsynlib.ui.prompt` / confirm / modals — not adopted
- rxved: `rxved/screens.py:85-165` — `ConfirmScreen` and `TextPromptScreen` are thin adopters; family modals carry the shared look and key rules (`--use _confirm` rule: three answers, escape says "later" never "never").
- nanosyned: `nanosyned/nanosyned/app.py:145-175` — local `PromptScreen(ModalScreen[str | None])`, and **no ConfirmScreen at all**; destructive actions have no confirm dialog.
- Why it matters: inconsistent modal behaviour vs the family, and irreversible deletions without a confirm step.

### 1.3 `vinsynlib.undo` — no undo log
- rxved: `rxved/app.py:176` `class _Change`, `app.py:1368` `def _undo(self, count: int)`; help legend carries `z undo` / `Z undo all` (`rxved/screens.py:292-293`).
- nanosyned: `grep undo nanosyned/nanosyned/app.py` → zero matches. Favourite writes / tag edits are final.
- Why it matters: any slip in `f` / tag / note editing is unrecoverable; the whole editor tier can adopt this straight from `vinsynlib.undo`.

### 1.4 `vinsynlib.ui.hints.keys.legend` — key hints are hand-rolled
- rxved: `rxved/screens.py:260-296` —	KEY_HINTS built from `keys.legend(...)` with a documented `_view_key` override explaining why `v` replaces `F favourites view`.
- nanosyned: no keys/legend use in `nanosyned/nanosyned/app.py`; help screen is a plain text constant (`app.py:750` `ReportScreen("nanosyned", _HELP)`).
- Why it matters: the family's shared legend order and coverage tests (`tests/test_legend.py` in rxved, 13 tests) cannot apply; drags between programs get lost.

### 1.5 `vinsynlib.catalog` semantics — local catalog diverges
- rxved: `xv/catalog.py` (adopted family shape) with `knows()`, `clear()`, `search(kind=)`, `categories_in()`, `printed_list_void()`, `voices` field (commits a5edf6c, 2693716).
- nanosyned: `nanosyned/nano/catalog.py:224 lines` — own store; keys are `"BANK:NNN"`-style 3-digit slot format, not the family's `make_key`; no `knows()` / `clear()`.
- Why it matters: no rebuild path (can't tell "empty because never scanned" from "deleted"), and key format mismatches the family's favourites/keys helpers.

### 1.6 `vinsynlib.backup` — no performance/patch backup envelope
- rxved: `xv/backup.py` — JSON envelope with `FORMAT`, `save/load/verify/describe/list_backups`; `rxved/app.py` stores a backup before each StoreScreen write; tests `tests/test_backup.py` (15 tests).
- nanosyned: no backup module (`nano/` has no backup.py; no store-then-backup flow in `app.py`).
- Why it matters: a failed store overwrites the slot with nothing to fall back on.

### 1.7 version gate lags
- rxved: `rxved/rxved/entry.py` MINIMUM `(0, 4, 2)`; pyproject `vinsynlib>=0.4.2`.
- nanosyned: `nanosyned/nanosyned/tests/test_version_gate_copy.py` exists (the check was copied, 1 test) but MINIMUM is `(0, 2, 0)`.
- Why it matters: features 1.1–1.4 above are un-adoptable until the gate and pin move; the gate itself advertises a floor it doesn't enforce in pyproject.

---

## 2. Feature / UX gaps

### 2.1 Ratings (column, filter, CLI)
- rxved: `rxved/screens.py:326-340` `RatingFilter` dataclass (`stars`, `at_least`, `matches`, `label` → `rating ≥3` / `rating =0`); help carries `* rating` and `V rating filter` (`screens.py:288-289`); CLI `rxved/rxved/cli.py` `fav` with `--rate / --rating-at-least / --rating-exactly`; persistence via `xv/config.py:158` `("rating_stars", rating_stars)`.
- nanosyned: no rating in favourites (`nanosyned/nano/favorites.py` — tags/notes only); no filter; no CLI flags.
- Why it matters: "which of these do I actually like" is missing end-to-end.

### 2.2 UI-state persistence (session restore)
- rxved: `xv/config.py:133-194` — `save_ui_state` / `load_ui_state` restoring `bank_index`, `slot_cursor`, `view_mode`, `categories`, `rating_stars`, `scan_offer_dismissed` (lines 136-160).
- nanosyned: `nano/config.py` has nothing of the sort; app starts flat at bank 0 cursor 0 every launch (also channel is remembered only in-memory, `app.py:341` `_remember_channel` — confirm no disk write).
- Why it matters: every restart loses position, view and filter.

### 2.3 Scan offer + rebuild
- rxved: `rxved/scan.py` — `ScanOfferScreen` (three answers: scan now / later / never) and `ScanScreen` with cancellable progress; `app.py` offers a scan when there is no catalog, and a rebuild (commits 2693716, 5af22dd); catalog gained `clear()`/`knows()` for it.
- nanosyned: scan is a silent CLI/app walk (`nanosyned/nano/scan` absent; sweep was removed at commit 69a3829 "Stop sweeping every port on every launch" without replacing the offer UX).
- Why it matters: fresh installs see an empty catalog with no guidance.

### 2.4 Multi/part editing screens
- rxved: `rxved/screens.py:1588-1880+` `MultiScreen` (performance-part table, `_columns`, `_row_cells`, editable offsets, `_report_text`), `CommonScreen` (`751-949`, offsets table with edit & digit typing), `EffectsScreen` (`1283-1587`, `_wire`, `_choices`, per-row apply) — all with `on_write` plumbing and `update_*` refresh from MIDI replies.
- nanosyned: `nanosyned/nanosyned/app.py` is a single bank browser with name/tags/notes detail; no Common/Effects/Multi screens at all (grep finds no such classes).
- Why it matters: the NanoSynth's mix/global/effects parameters are only reachable through ad-hoc CLI reads, not editability.

### 2.5 Patch picker with remembered position/view
- rxved: `rxved/screens.py:950-1213` `PickerPosition` + `PatchPickerScreen` with `_restore_position`, `_cursor_key`, `action_cycle_view` (commits 0fb2194, 1f18666 keep cursors and the `v` view across the dialog).
- nanosyned: no picker dialog; selection is the main table only.
- Why it matters: dialogs keep cursor+view in rxved so a multi-step session never loses context.

### 2.6 Sound mode / readback writing
- rxved: `xv/bridge.py:440-481` `SoundMode.name`, `SetupState.is_patch_mode`; app `M sound mode` (`screens.py:287`); demo bridge implements `write_sound_mode` with `verify=True` (`rxved/demo.py:266-279`), `store_temporary_to_slot` (`demo.py:417`), `write_performance_*` with verify (`demo.py:400-570`).
- nanosyned: `nanosyned/nanosyned/demo.py` has `read_*` methods only (lines 130-215: read_program, read_edit_program, read_mix, read_global, select) — no write path, no verify-on-write, no store-to-slot in the app either.
- Why it matters: nanosyned is effectively read-only + select; the write-verify loop the family standardised on is missing.

### 2.7 Search richness
- rxved: `rxved/screens.py:167-231` `SearchScreen` returning `(needle, per-column flags dict)` — column-scoped search.
- nanosyned: `nanosyned/nanosyned/app.py:670-680` — search over names only.
- Why it matters: can't restrict search to tags/notes.

### 2.8 CLI command surface
- rxved: `rxved/cli.py` (1418 lines) ~21 commands incl. `fav ... --rate/--rating-*`, `mode`, `multi`, `channels`, `perf-*`, `read`, `probe-srx`, `scan-catalog`.
- nanosyned: `nanosyned/nanosyned/cli.py` (396 lines) 10 commands; no favorites management in CLI nor ratings nor `mode`/`multi`/`read` reads.
- Why it matters: headless/scripted workflows can't rate, back up or read state.

---

## 3. Structural / pattern gaps

### 3.1 Screen/architecture
- rxved: app state machine in `app.py` + all modals in `screens.py` (2539 lines, 12+ screens), with a `_Frame` adopter block (`screens.py:234-240`) documented against library tests.
- nanosyned: `app.py` mixes report+prompt modals into the app file (`app.py:113-175`) and has one screen total.
- Why it matters: the modal surface can't grow without bloating app.py; library conformance tests per-screen can't exist.

### 3.2 Data model: categories, kind labels, voices
- rxved: `xv/catalog.py` carries `categories_in()`, `voices`; `screens.py:343-350` `_KIND_LABEL` maps patch/rhythm/perf deliberately ("Spelled out rather than truncated").
- nanosyned: `nano/catalog.py` flat name records; no categories.
- Why it matters: cursored filtering is a core browsing affordance rxved's UI persists and restores.

### 3.3 Bridge state objects
- rxved: `xv/bridge.py:472-975` — `PartState`, `SetupState`, `ChannelMidi`, `PerformanceFx`, `PerformanceCommon`, `DeviceState.silence_report()` (`bridge.py:875-978` `_selection_findings`/`_part_findings` explain why nothing is audible).
- nanosyned: `nano/bridge.py` (614 lines) returns raw reads; no state objects, no silence/why-diagnosis.
- Why it matters: users get "played nothing" without a reason.

### 3.4 Demo richness
- rxved: `rxved/demo.py` 699 lines implementing ~40 bridge methods incl. `scan_bank_with_categories` (`demo.py:636`), `store_temporary_to_slot` (`417`), `write_sound_mode` (`266`), `read_state(with_parts=...)` (`596`).
- nanosyned: `nanosyned/demo.py` 215 lines, `read_*` + `select` only (`demo.py:130-215`).
- Why it matters: portable demo can't exercise writes; CI hardware-free coverage is shallower.

### 3.5 Editor map / marked-list tooling pattern
- rxved: `tools/check_editor_map.py` ( agrees-with-test pattern, `tests/test_editor_map.py` 8 tests), `tools/read_marked_list.py` (marked-up printout → favourites; `tests/test_marked_list.py`), documented in README §"Reading a marked-up printout" (`README.md:667`).
- nanosyned: `tools/` contains only `extract_catalog.py`.
- Why it matters: bulk name/annotation entry workflows absent.

---

## 4. Tooling / packaging / docs / testing gaps

### 4.1 CI
- rxved: `.github/workflows/checks.yml` — 3-OS × py3.11/3.12 matrix, least-privilege permissions, concurrency-cancel, Windows make+Git-Bash handling, separate pre-commit job, `make check` as single entry point (`checks.yml` lines shown above).
- nanosyned: no `.github/` directory at all (`ls` shows no .github).
- Why it matters: nothing validates commits on the README's supported platforms.

### 4.2 Makefile targets
- rxved: `Makefile:84` `typecheck-strict` (+ `:93` `strict-modules` helper, `:106` `test-hardware`, `:178` `baseline`).
- nanosyned: `nanosyned/Makefile:44` has `typecheck` only; no `typecheck-strict`, no `test-hardware`, no `baseline` diffing, no `format-check` named target in help (`:34` lint, `:40` format).
- Why it matters: the "strict count can only shrink" loop (docs/CHECKS.md:31-33) can't run; hardware suite is uninvokeable.

### 4.3 pyproject strictness + extras
- rxved: `pyproject.toml` 440 lines; `pyproject.toml:63-84` optional deps `[dev]` **and** a `tools` extra (numpy/Pillow) so CI installs `.[dev,tools]` (`checks.yml` step).
- nanosyned: `pyproject.toml` 151 lines; dev deps via `requirements-dev.txt` (outside pyproject); no `tools` extra.
- Why it matters: deptry/audit and strict-mypy plumbing already wired upstream shoehorn fit; the README dev-check story (README §"Development checks" `nanosyned/README.md:185-277`) documents what the pyproject doesn't enforce.

### 4.4 Docs
- rxved: `docs/CHECKS.md` (347 lines: the "no existing finding mass-fixed" rule, per-tool table, `typecheck-strict` usage), `docs/RESOLUTION_NOTES.md`, `docs/screenshots/` 10+ PNGs referenced from README.
- nanosyned: `docs/` has only `RESOLUTION_NOTES.md`; no screenshots (`ls docs/` shows one file).
- Why it matters: CHECKS.md is the onboarding agreement for check history; screenshots are README navigation.

### 4.5 README defects not yet fixed (rxved already fixed in 5e82bf8)
- `nanosyned/README.md:69-71` — a doubled `---` rule (same defect rxved commit 5e82bf8 "drop the doubled rule" fixed).
- `nanosyned/README.md:89` — " is provided **as is…" heading/line missing its subject (rxved fixed the missing subject too).
- rxved README also documents non-d挚istribution rules and catalog sources (`README.md:545-700` "Patch names are not included / From the fitted synth / The editor binary / The PDFs"); nanosyned's "The name catalog" section (`README.md:172`) is thinner.
- Why it matters: identical wordings should track the family's corrected text.

### 4.6 Test suite depth
- rxved: `tests/` 22 files, 631 tests: `test_backup.py` (15), `test_banks.py` (40), `test_catalog.py` (24), `test_cli_favorites.py` (12), `test_editor_map.py` (8), `test_extract.py` (7), `test_hardware.py` (14), `test_legend.py` (13), `test_livenames.py` (15), `test_marked_list.py` (4), `test_scan_catalog.py` (10), `test_scan.py` (10), `test_scan_stuck.py` (8), `test_state.py` (54), plus 207 `test_app.py`.
- nanosyned: `tests/` 11 files, 129 tests: `test_app.py` 16 actions coverage only, `test_bridge.py` 2, `test_conformance.py` 4, `test_version_gate_copy.py` 1.
- Why it matters: app/bridge coverage ratios (207:16, conformance 6:4) mean regressions in family features can't be detected when adopting.

### 4.7 Liveness / hardware entry points
- rxved: `Makefile:106` `test-hardware`, `tests/test_hardware.py` gated by `--hardware` + `RXVED_HARDWARE` env (commits 5b44ec3/e555d1f/e549db4/6fbb582).
- nanosyned: no hardware test file.
- Why it matters: the one path that proves protocol behaviour on-device is missing.

---

## 5. Recent rxved git work nanosyned lacks

From `rxved` git log (top 15) vs `nanosyned` (stops at 16e3a95 "Adopt vinsynlib's version-gate check … 0.3.1"):

| rxved commit | What it does | nanosyned status |
|---|---|---|
| 2693716 + 5af22dd + a5edf6c | scan offer + rebuild screens, `catalog.clear()/knows()` | absent (§2.3, §1.5) |
| 51d207d | adopt `vinsynlib.ui.report` ReportScreen frame | reimplemented locally (§1.1) |
| 6fa0a14 / e229aae / bf53e0c | vinsynlib 0.4.2: rating glyph, UNSET/bind | version gate stuck at 0.2/0.3.1 (§1.7) |
| 70e6687 / e3eefaf / e549db4 / 6fbb582 | rating column + filter + CLI rating flags | absent (§2.1) |
| 07d07d0 / 8e033e0 | sound-mode write path with verify | read-only bridge (§2.6) |
| 8b864df | help names both builds via `__file__` | single-build help string (`app.py:750`) |
| 0fb2194 / 1f18666 | picker remembers cursors + `v` view | no picker dialog (§2.5) |
| 82d57a3 / 74ec133 | 15 README screenshots | no screenshots (§4.4) |
| 5e82bf8 | README "restore missing subject, drop doubled rule" | same defects live (§4.5) |
| cfb9714 | tools default paths home-relative (`config.toml` under `$HOME`) | `tools/extract_catalog.py` hardcodes repo-relative? → confirm, but note `nanosyned/config.toml`-equivalent path handling diverges in `nano/config.py:load_port_pair` |
| 675789d | tests assert the build rule not this venv | test_style of local suite not aligned |

### 5.1 Also worth tracking: rxved README/config extras
- `rxved/README.md.backup` and `rxved/coverage.xml` and `rxved/.secrets.baseline`/`tools/diff_secrets_baseline.py` exist in rxved but nanosyned has only `.secrets.baseline` with no diff tool/M target wiring (it does have `audit-secrets`, `Makefile:86`).
- Why it matters: secrets-baseline drift is only detectable with the diff tool + `baseline` target (rxved `Makefile:178`).

---

## Priority order (recommendation for porting)

1. **vinsynlib 0.4.2 adoption sweep** — ReportScreen/PromptScreen/Confirm + undo + keys.legend (§1.1–1.4, 1.7) — smallest diff, unlocks everything else.
2. **UI-state persistence + ratings** (§2.2, §2.1) — config plumbing already exists in `xv/config.py` shape to copy.
3. **Scan offer + rebuild** (§2.3) — depends on (1) and `catalog.clear()/knows()` (§1.5).
4. **Write paths with verify + backup-on-store** (§2.6, §1.6) — biggest behavioural gap: currently read-only.
5. **Multi/Common/Effects screens** (§2.4, §2.5) — biggest UI gap.
6. **CI + typecheck-strict + hardware suite + screenshots + CHECKS.md** (§4.1–4.4, 4.7) — all mechanical, high confidence.
7. **README fixes (5e82bf8 sync)** (§4.5) — trivial.
8. Test deepening proportional to each port (§4.6).
