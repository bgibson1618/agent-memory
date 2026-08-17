"""Paths and environment seams.

Everything user-visible hangs off $HOME so tests can isolate a KB with a scratch
HOME; MEM_OLLAMA_URL is the sanctioned seam for daemon up/down/hung states.
MEM_KB_ROOT (D15) points the whole CLI at an alternate KB instance — every rule
(local-only, no remote, OKF, sensitivity) applies per-instance.
"""

import os
from pathlib import Path

KB_DIRNAME = ".agent-memory"

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_EMBED_MODEL = "nomic-embed-text:v1.5"
DEFAULT_EMBED_DIMS = 768

# Dedup bands (D17, extends D3): the cosine lines `mem extract` uses to
# classify a candidate against its best KB match. Below dedup_low: novel,
# save. [dedup_low, dedup_high): "skipped-duplicate" - the D3-reviewable
# band. At/above dedup_high: "skipped-duplicate-confident" - accepted
# without a full-body D3 read. dedup_low defaults to the D3 measured value
# (must equal research/dedup-calibration.md's chosen-threshold - the test
# suite asserts they match); dedup_high defaults to disabled (None) - a
# confident band is a per-instance calibration choice
# (research/dedup-calibration-personal-2026-08-17.md), never a global one.
DEFAULT_DEDUP_LOW = 0.79  # measured: research/dedup-calibration.md (band 0.77-0.81, fp 0, fn 0)
DEFAULT_DEDUP_HIGH = None  # disabled by default; per-instance seam: MEM_DEDUP_HIGH

# Pre-D17 name. Must stay equal to DEFAULT_DEDUP_LOW: dedup_threshold() and
# MEM_DEDUP_THRESHOLD are the back-compat surface dedup_low() falls back to.
DEFAULT_DEDUP_THRESHOLD = DEFAULT_DEDUP_LOW


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def kb_root() -> Path:
    override = os.environ.get("MEM_KB_ROOT", "").strip()
    if override:
        return Path(os.path.expanduser(override))
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


def dedup_low() -> float:
    """Auto-add / reviewable-band boundary. MEM_DEDUP_LOW takes precedence;
    MEM_DEDUP_THRESHOLD (the pre-D17 single-threshold name) is the back-compat
    fallback, so existing per-instance env config keeps working untouched."""
    raw = os.environ.get("MEM_DEDUP_LOW", "").strip()
    if not raw:
        raw = os.environ.get("MEM_DEDUP_THRESHOLD", "").strip()
    return float(raw) if raw else DEFAULT_DEDUP_LOW


def dedup_high() -> float | None:
    """Reviewable / confident-skip boundary. Disabled (None) unless an
    instance opts in - a confident band is a calibrated, per-instance choice
    (research/dedup-calibration-personal-2026-08-17.md), not a global default."""
    raw = os.environ.get("MEM_DEDUP_HIGH", "").strip()
    return float(raw) if raw else DEFAULT_DEDUP_HIGH


def dedup_threshold() -> float:
    """Pre-D17 name, kept as an alias so existing callers need no change."""
    return dedup_low()


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
