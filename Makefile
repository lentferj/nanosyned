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
.PHONY: help check lint format typecheck test audit audit-vulns \
        audit-deadcode audit-deps audit-secrets venv

help:
	@echo "make check        everything below, in order; stops on first failure"
	@echo "make lint         ruff check + ruff format --check"
	@echo "make format       ruff check --fix + ruff format (the fixer)"
	@echo "make typecheck    mypy"
	@echo "make test         pytest with coverage, term-missing"
	@echo "make audit        pip-audit, vulture, deptry, detect-secrets"
	@echo "make venv         create .venv and install runtime + dev deps"

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
