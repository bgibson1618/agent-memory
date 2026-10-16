"""The version the CLI reports (`mem --version`, agent_memory.__version__) must equal the packaged
version in pyproject.toml — found drifting at the 0.2.1 release (2026-10-16: the tool said 0.2.0)."""

import re
from pathlib import Path

import agent_memory


def test_dunder_version_matches_pyproject():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    packaged = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert agent_memory.__version__ == packaged
