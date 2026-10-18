# nanosyned -- development checks.
#
# Everything here is also wired into .pre-commit-config.yaml, so `make check`
# and `git commit` are held to the same standard.
#
# Override the interpreter/venv if yours lives elsewhere:
#     make check PY=.venv/bin/python BIN=.venv/bin

PY  ?= .venv/bin/python
BIN ?= .venv/bin

# Tracked files PLUS untracked-but-not-ignored ones. A brand new module is
# untracked until it is committed, and it is exactly that file the pipeline
# must hold to the full rule set -- so `git ls-files` alone would leave the
# one gap that matters. --exclude-standard keeps .venv and the caches out.
PYFILES := $(shell git ls-files --cached --others --exclude-standard '*.py')

.DEFAULT_GOAL := help
# Get strict module names from pyproject.toml's [[tool.mypy.overrides]] entries.
STRICT_MODULES := $(shell $(PY) tools/get_strict_modules.py)

.PHONY: help check lint format typecheck test audit audit-vulns \
        audit-deadcode audit-deps audit-secrets venv install install-hooks \
        format-check coverage test-hardware ci pre-commit-run clean \
        typecheck-strict

help:
	@echo "make check        everything below, in order; stops on first failure"
	@echo "make lint         ruff check + ruff format --check"
	@echo "make format       ruff check --fix + ruff format (the fixer)"
	@echo "make typecheck    mypy"
	@echo "make test         pytest with coverage, term-missing"
	@echo "make audit        pip-audit, vulture, deptry, detect-secrets"
	@echo "make venv         create .venv and install runtime + dev deps"
	@echo "make install      install project in development mode"
	@echo "make install-hooks install pre-commit hooks"
	@echo "make format-check ruff format --check"
	@echo "make coverage     pytest with explicit coverage"
	@echo "make test-hardware tests that need a real synth (opens MIDI ports)"
	@echo "make ci           single entry point CI calls"
	@echo "make pre-commit-run run every pre-commit hook against all files"
	@echo "make clean        remove caches and coverage output"
	@echo "make secrets-update regenerate .secrets.baseline"
	@echo ""
	@echo "make typecheck-strict  mypy with per-module strict overrides"

check: lint typecheck test audit
	@echo "all checks passed"

lint:
	@echo "== ruff check =="
	$(PY) -m ruff check .
	@echo "== ruff format --check =="
	$(PY) -m ruff format --check $(PYFILES)

format:
	$(PY) -m ruff check --fix $(PYFILES)
	$(PY) -m ruff format $(PYFILES)

typecheck:
	@echo "== mypy =="
	$(PY) -m mypy

typecheck-strict:
	@echo "== mypy strict =="
	@if [ -n "$(STRICT_MODULES)" ]; then \
		$(PY) -m mypy --strict $(STRICT_MODULES); \
	else \
		echo "No strict modules configured."; \
	fi
	@echo "Strict modules checked: $(words $(STRICT_MODULES))"

test:
	@echo "== pytest =="
	$(PY) -m pytest

audit: audit-vulns audit-deadcode audit-deps audit-secrets

# Audits what this project declares, not whatever happens to be installed in
# the ambient environment. Auditing the venv would report CVEs in unrelated
# system packages and drown the project's own dependencies in noise.
#
# vinsynlib is an index dependency now (it is on PyPI), so it is audited with
# the rest. It used to be filtered out, because as a sibling checkout pip
# could not resolve it and pip-audit would fail resolving rather than
# auditing anything.
audit-vulns:
	@echo "== pip-audit: runtime dependencies (from pyproject.toml) =="
	@$(PY) -c "import pathlib, tomllib; \
	    data = tomllib.load(open('pyproject.toml', 'rb')); \
	    pathlib.Path('.audit-runtime-req.txt').write_text(\
	        ''.join(r + chr(10) for r in data['project']['dependencies']))"
	$(PY) -m pip_audit --progress-spinner=off -r .audit-runtime-req.txt
	@rm -f .audit-runtime-req.txt
	@echo "== pip-audit: development tooling (requirements-dev.txt) =="
	$(PY) -m pip_audit --progress-spinner=off --no-deps -r requirements-dev.txt

audit-deadcode:
	@echo "== vulture =="
	$(PY) -m vulture

audit-deps:
	@echo "== deptry =="
	$(PY) -m deptry .

# NOTE: the check is detect-secrets-HOOK, not `scan --baseline`.
# `detect-secrets scan --baseline <file>` does not check anything: in v1.5.0 it
# merges what it just found into the baseline and rewrites it, printing
# nothing and exiting 0. Used in a Makefile that silently accepts new secrets
# and poisons the baseline with them. The hook does the comparison and exits 1.
audit-secrets:
	@echo "== detect-secrets =="
	$(BIN)/detect-secrets-hook --baseline .secrets.baseline $(PYFILES) \
		Makefile README.md pyproject.toml requirements-dev.txt  # pragma: allowlist secret

venv:
	python3 -m venv --system-site-packages .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e . -r requirements-dev.txt
	$(BIN)/pre-commit install

## ---------------------------------------------------------------- install ---

install: ## Install the project in development mode (plus dev deps)
	$(PY) -m pip install -e . -r requirements-dev.txt

## ---------------------------------------------------------------- install-hooks ---

install-hooks: ## Install pre-commit hooks into .git/hooks
	$(BIN)/pre-commit install

## ---------------------------------------------------------------- format-check ---

format-check: ## ruff format --check
	$(PY) -m ruff format --check $(PYFILES)

## ---------------------------------------------------------------- coverage ---

coverage: ## pytest with explicit coverage (addopts already enables it)
	$(PY) -m pytest

## ---------------------------------------------------------------- test-hardware ---

# The hardware suite is a separate target, not part of `check`: CLAUDE.md's
# rule is that only one session drives a unit at a time, and CI -- which
# runs `make check` -- must not be it. `--hardware` opens MIDI ports and
# must be run alone; this target will error if tests/test_hardware.py is
# absent (a later task adds it).
test-hardware: ## tests that need a real synth (opens MIDI ports)
	@# Must be run alone: opening MIDI ports precludes concurrent access
	$(PY) -m pytest tests/test_hardware.py --hardware -o addopts="" -p no:cacheprovider -rs -s

## ---------------------------------------------------------------- ci ---

ci: ## Single entry point CI calls; wraps `make check`
	$(MAKE) check

## ---------------------------------------------------------------- pre-commit-run ---

pre-commit-run: ## Run every pre-commit hook against all files
	$(BIN)/pre-commit run --all-files

## ---------------------------------------------------------------- clean ---

clean: ## Remove caches and coverage output; safe cleanup, do NOT delete .venv
	rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache .coverage
	@echo "Note: .venv is NOT deleted"

## ---------------------------------------------------------------- secrets-update ---

# `detect-secrets scan --baseline <file>` does not check anything: in v1.5.0 it
# merges what it just found into the baseline and rewrites it, printing
# nothing and exiting 0. Used in a Makefile that silently accepts new secrets
# and poisons the baseline with them. The hook does the comparison and exits 1.
secrets-update: ## Regenerate .secrets.baseline with detect-secrets scan
	@# Mirrors p2ked's exact command but `scan --baseline` merges findings
	@# into the baseline rather than checking, undermining the purpose.
	$(BIN)/detect-secrets scan --baseline .secrets.baseline