# SPDX-License-Identifier: GPL-2.0-or-later
# SPDX-FileCopyrightText: Copyright (C) 2026  nanosyned contributors
#
# This file is part of nanosyned.
#
# nanosyned is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 2 of the License, or (at your option) any later
# version.
#
# nanosyned is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more
# details.

"""The suite must not write the application's config into the checkout.

``config.DEFAULT_PATH`` is now the per-platform path for the tool, outside
the checkout. The checks below ensure config saves go through explicit paths
and the per-tool config contract is followed.
"""

import ast
import os
from pathlib import Path

from vinsynlib import devchecks


def _here() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _config_saves():
    for name, tree in devchecks.iter_test_sources(_here()):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("save_")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "config"
            ):
                yield name, node


def test_every_config_save_in_the_suite_names_its_file() -> None:
    offenders = devchecks.config_saves_without_path(_here())
    assert not offenders, (
        f"{offenders} save to config.DEFAULT_PATH, which is relative to the "
        f"working directory. Pass a tmp_path."
    )


def test_the_check_has_something_to_check() -> None:
    """Guard against the search passing because it matched nothing."""
    assert list(_config_saves()), "no config.save_* calls found; the check is vacuous"


def test_this_project_imports_no_sibling() -> None:
    """A sibling project's package is not installed beside this one."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    offenders = []
    for pkg in ("nanosyned", "nano"):
        d = os.path.join(root, pkg)
        for name in os.listdir(d):
            if name.endswith(".py"):
                offenders += devchecks.foreign_imports(
                    os.path.join(d, name),
                    own=("nanosyned", "nano", "vinsynlib"),
                )
    assert not offenders, offenders


def test_default_path_is_under_the_platform_config_dir(monkeypatch, tmp_path):
    """The default path is under the platform config dir (config_dir("nanosyned"))."""
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    import sys

    for mod in list(sys.modules.keys()):
        if (
            mod.startswith("vinsynlib")
            or mod.startswith("nano")
            or mod.startswith("nanosyned")
        ):
            sys.modules.pop(mod)

    from nano import config as cfg
    from vinsynlib import config as vcfg

    expected_dir = vcfg.config_dir("nanosyned")
    assert os.path.isabs(cfg.DEFAULT_PATH)
    assert cfg.DEFAULT_PATH.startswith(expected_dir)
    assert cfg.DEFAULT_PATH.endswith(os.path.join("nanosyned", "config.toml"))


def test_explicit_config_still_wins(monkeypatch, tmp_path):
    """An explicit --config still wins."""
    from nanosyned.app import build_parser as app_build_parser

    parser = app_build_parser()
    args = parser.parse_args(["--config", "/custom/path/config.toml"])
    assert args.config == "/custom/path/config.toml"

    from nanosyned.cli import build_parser as cli_build_parser

    parser = cli_build_parser()
    args = parser.parse_args(["--config", "/custom/path/config.toml", "ports"])
    assert args.config == "/custom/path/config.toml"


def test_legacy_config_migrated_once(monkeypatch, tmp_path):
    """A legacy ./config.toml is migrated once."""
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.chdir(tmp_path)

    legacy_path = tmp_path / "config.toml"
    legacy_path.write_text('# nanosyned\nport = "test"\n')

    from nano import config as cfg

    result = cfg.migrate_legacy_config("nanosyned")
    assert result is not None, "migrate_legacy_config should have returned a path"
    assert legacy_path.exists(), "Legacy file should still exist"
    target = Path(result)
    assert target.exists()
    assert target.read_text() == '# nanosyned\nport = "test"\n'

    result2 = cfg.migrate_legacy_config("nanosyned")
    assert result2 is None, "migrate_legacy_config returns None if target exists"


def test_config_help_is_the_familys(monkeypatch, tmp_path):
    """The --config help text is the family's (config_help("nanosyned"))."""
    home = tmp_path / "home"
    home.mkdir()
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)

    import sys

    for mod in list(sys.modules.keys()):
        if (
            mod.startswith("vinsynlib")
            or mod.startswith("nano")
            or mod.startswith("nanosyned")
        ):
            sys.modules.pop(mod)

    from nano import config as cfg
    from nanosyned import app as nanosyned_app
    from nanosyned import cli as nanosyned_cli

    expected = cfg.config_help("nanosyned")
    assert os.path.join("nanosyned", "config.toml") in expected
    assert "./config.toml" not in expected

    parser = nanosyned_app.build_parser()
    help_text = parser.format_help()
    assert "nanosyned" in help_text and "config.toml" in help_text
    assert "./config.toml" not in help_text

    parser = nanosyned_cli.build_parser()
    help_text = parser.format_help()
    assert "nanosyned" in help_text and "config.toml" in help_text
    assert "./config.toml" not in help_text
