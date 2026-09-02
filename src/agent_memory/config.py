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

# D18 (research/d18-dedup-detection-design-2026-09-02.md S4.4): the detector's
# claim-coverage seams, all disabled (None) or conservative by default - a
# per-instance calibration choice, never a global one, same posture as
# DEFAULT_DEDUP_HIGH above. Every getter below just reads+parses its env var;
# cross-field validation (high > low, ranges, non-finite) is dedup.py's
# load_config(), mirroring extract.py's _band_config().
DEFAULT_DEDUP_COVERAGE_LOW = None  # recommended calibrated value: 0.35
DEFAULT_DEDUP_COVERAGE_HIGH = None  # recommended: 0.85
DEFAULT_DEDUP_UNION_LOW = None  # recommended: 0.55
DEFAULT_DEDUP_UNION_M = 5
DEFAULT_DEDUP_CLAIM_LEX = 0.60
DEFAULT_DEDUP_CLAIM_SEM = None  # the paraphrase lever; off ships the semantic claim leg disabled
DEFAULT_DEDUP_DEEP_K = 50
DEFAULT_DEDUP_CHUNKS = False  # off by default; S3's opt-in seam for chunk-index population
DEFAULT_DEDUP_CHUNK_SKIP_CHARS = 200_000
DEFAULT_DEDUP_LOG = True
DEFAULT_DEDUP_LOG_TITLES = True


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


def _env_float(name: str, default: float | None) -> float | None:
    """For seams whose default is None (disabled-unless-opted-in)."""
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"{name} must be a boolean (1/0, true/false, yes/no, on/off), got {raw!r}")


def dedup_coverage_low() -> float | None:
    """Coverage-flag floor - disabled (None) unless an instance opts in,
    same per-instance posture as dedup_high (D18 S4.4)."""
    return _env_float("MEM_DEDUP_COVERAGE_LOW", DEFAULT_DEDUP_COVERAGE_LOW)


def dedup_coverage_high() -> float | None:
    """Confident-coverage ceiling; disabled (None) by default (D18 S4.4)."""
    return _env_float("MEM_DEDUP_COVERAGE_HIGH", DEFAULT_DEDUP_COVERAGE_HIGH)


def dedup_union_low() -> float | None:
    """Union-coverage flag floor; disabled (None) by default (D18 S4.4)."""
    return _env_float("MEM_DEDUP_UNION_LOW", DEFAULT_DEDUP_UNION_LOW)


def dedup_union_m() -> int:
    """Greedy union set-cover cap (D18 S4.2)."""
    return _env_int("MEM_DEDUP_UNION_M", DEFAULT_DEDUP_UNION_M)


def dedup_claim_lex() -> float:
    """Per-claim lexical containment match threshold (D18 S4.2's tau_lex)."""
    raw = os.environ.get("MEM_DEDUP_CLAIM_LEX", "").strip()
    return float(raw) if raw else DEFAULT_DEDUP_CLAIM_LEX


def dedup_claim_sem() -> float | None:
    """Per-claim semantic cosine match threshold; disabled (None) by default
    - the semantic claim leg ships off (D18 S7 scope, R1 in the design)."""
    return _env_float("MEM_DEDUP_CLAIM_SEM", DEFAULT_DEDUP_CLAIM_SEM)


def dedup_deep_k() -> int:
    """Fused-retrieval pool depth per leg (D18 S4.1)."""
    return _env_int("MEM_DEDUP_DEEP_K", DEFAULT_DEDUP_DEEP_K)


def dedup_chunks() -> bool:
    """Whether the chunk index (S3) is populated at all; off by default -
    strict boolean parsing, same as dedup_log/dedup_log_titles (D18 S4.4's
    ratified seam table; gate finding 5)."""
    return _env_bool("MEM_DEDUP_CHUNKS", DEFAULT_DEDUP_CHUNKS)


def dedup_chunk_skip_chars() -> int:
    """Cards above this size are excluded from chunk population, scored only
    by their lexically-matched window(s) (D18 S4.2)."""
    return _env_int("MEM_DEDUP_CHUNK_SKIP_CHARS", DEFAULT_DEDUP_CHUNK_SKIP_CHARS)


def dedup_log() -> bool:
    """Whether `mem dedup` writes .index/dedup-log.jsonl by default (D18 S4.5)."""
    return _env_bool("MEM_DEDUP_LOG", DEFAULT_DEDUP_LOG)


def dedup_log_titles() -> bool:
    """Whether dedup-log.jsonl records carry candidate/hit titles (D18 S4.5);
    off for a paranoid instance that wants slugs/hashes/numbers only."""
    return _env_bool("MEM_DEDUP_LOG_TITLES", DEFAULT_DEDUP_LOG_TITLES)


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
