from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from perspectiv import __version__


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "check_release_version.py"


def load_release_checker():
    spec = importlib.util.spec_from_file_location("check_release_version", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_exposes_canonical_version() -> None:
    assert __version__ == "0.3.8"


def test_release_checker_accepts_current_tag() -> None:
    checker = load_release_checker()
    assert checker.validate_release_version("v0.3.8", ROOT) == "0.3.8"


def test_release_checker_rejects_mismatched_tag() -> None:
    checker = load_release_checker()
    with pytest.raises(ValueError, match="Publication incoherente"):
        checker.validate_release_version("v0.3.7", ROOT)


def test_release_workflow_checks_version_before_building_archive() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    check_position = workflow.index("tools/check_release_version.py")
    archive_position = workflow.index("git archive")
    assert check_position < archive_position
