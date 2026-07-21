"""Paths and environment seams.

Everything user-visible hangs off $HOME so tests can isolate a KB with a scratch
HOME; MEM_OLLAMA_URL is the sanctioned seam for daemon up/down/hung states.
"""

import os
from pathlib import Path

KB_DIRNAME = ".agent-memory"

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text:v1.5"
DEFAULT_EMBED_DIMS = 768

# Dedup threshold: the cosine line between "near-duplicate, skip" and
# "distinct, save" for `mem extract`. Calibrated, not guessed (capstone D024):
# the value must equal the measured choice recorded in
# research/dedup-calibration.md (regenerate: uv run python
# research/dedup_calibration.py) - the test suite asserts they match.
DEFAULT_DEDUP_THRESHOLD = 0.79  # measured: research/dedup-calibration.md (band 0.77-0.81, fp 0, fn 0)


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def kb_root() -> Path:
    return _home() / KB_DIRNAME


def ollama_base_url() -> str:
    url = os.environ.get("MEM_OLLAMA_URL", DEFAULT_OLLAMA_URL).strip()
    if "://" not in url:
        url = "http://" + url
    return url.rstrip("/")


def embed_model() -> str:
    return os.environ.get("MEM_EMBED_MODEL", DEFAULT_EMBED_MODEL)


def embed_dims() -> int:
    return int(os.environ.get("MEM_EMBED_DIMS", str(DEFAULT_EMBED_DIMS)))


def dedup_threshold() -> float:
    return float(os.environ.get("MEM_DEDUP_THRESHOLD", str(DEFAULT_DEDUP_THRESHOLD)))


def claude_md_path() -> Path:
    override = os.environ.get("MEM_CLAUDE_MD")
    if override:
        return Path(override).expanduser()
    return _home() / ".claude" / "CLAUDE.md"


def agents_md_path() -> Path:
    override = os.environ.get("MEM_AGENTS_MD")
    if override:
        return Path(override).expanduser()
    return _home() / ".agent-docs" / "AGENTS.md"
