"""D17 - two-band dedup thresholds: `dedup_low` (below: added; unchanged
default 0.79) and `dedup_high` (at/above, when configured: "skipped-duplicate-
confident", accepted without a full-body D3 read). Between the two -
"skipped-duplicate" - is byte-identical to pre-D17 behavior.

The fake embedder here is cosine-controlled, not synonym-shaped (unlike F9's):
each candidate encodes an "AXISn=x,y" marker placing its vector on a private
2D plane, so a single extract call can pin an exact similarity against a seed
without guessing what a real model would produce. Distinct axes never share a
component, so unrelated seeds/candidates in the same test can't collide;
margins around each boundary (>= 0.01) stay well clear of float32 rounding.
"""

import json
import math
import re

import pytest

from fakes import FakeOllamaServer

from agent_memory import config

DIMS = 8
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:d17d17d17"

_AXIS_RE = re.compile(r"AXIS(\d)=(-?[0-9.]+),(-?[0-9.]+)")


def band_vec(text: str, dims: int) -> list:
    vec = [0.0] * dims
    m = _AXIS_RE.search(text)
    if not m:
        vec[-1] = 1.0  # fallback: orthogonal to every axis plane
        return vec
    axis, x, y = int(m.group(1)), float(m.group(2)), float(m.group(3))
    vec[axis * 2] = x
    vec[axis * 2 + 1] = y
    return vec


def BandOllama(dims: int = DIMS, model: str = MODEL) -> FakeOllamaServer:
    return FakeOllamaServer(dims=dims, model=model, embed_fn=band_vec, digest=DIGEST)


@pytest.fixture
def band_ollama():
    server = BandOllama()
    yield server
    server.stop()


def seed(axis: int) -> dict:
    return {
        "title": f"Axis {axis} seed concept",
        "body": f"Seed body for band-boundary testing, axis {axis}. AXIS{axis}=1.0,0.0",
    }


def candidate(title: str, axis: int, similarity: float) -> dict:
    """A candidate whose embedding has ~exactly `similarity` cosine against
    that axis's seed vector [1, 0]."""
    y = math.sqrt(max(0.0, 1.0 - similarity ** 2))
    return {
        "title": title,
        "body": (
            f"Band-boundary test body for {title}."
            f" AXIS{axis}={similarity:.6f},{y:.6f}"
        ),
    }


def run_extract(mem, payload, *flags, env_extra=None):
    return mem("extract", "--candidates", json.dumps(payload), *flags, env_extra=env_extra)


def seed_kb(mem, env, axis: int) -> str:
    s = seed(axis)
    result = mem("save", "--title", s["title"], "--body", s["body"], env_extra=env)
    assert result.returncode == 0, result.stderr
    return f"axis-{axis}-seed-concept"


def test_below_low_is_added_default(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    seed_kb(mem, env, axis=0)

    result = run_extract(mem, [candidate("Distinct low", 0, 0.50)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["results"][0]["disposition"] == "added"


def test_in_reviewable_band_is_skipped_duplicate_default(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    # Default dedup_low is 0.79; 0.81 clears it with margin, dedup_high is
    # disabled by default so this cannot become "confident".
    result = run_extract(mem, [candidate("Near dup", 0, 0.81)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert "dedup_high" not in report
    entry = report["results"][0]
    assert entry["disposition"] == "skipped-duplicate"
    assert entry["match"] == match_slug


def test_confident_band_disabled_by_default_even_at_very_high_similarity(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    seed_kb(mem, env, axis=0)

    result = run_extract(mem, [candidate("Near twin", 0, 0.99)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert "dedup_high" not in report
    assert report["results"][0]["disposition"] == "skipped-duplicate"
    assert "skipped_duplicate_confident" not in report


def test_confident_band_when_configured_json(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url, "MEM_DEDUP_HIGH": "0.9"}
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    result = run_extract(
        mem,
        [candidate("Mid band", 0, 0.85), candidate("Confident twin", 0, 0.95)],
        "--json", env_extra=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["dedup_high"] == 0.9
    mid, confident = report["results"]
    assert mid["disposition"] == "skipped-duplicate"
    assert confident["disposition"] == "skipped-duplicate-confident"
    assert confident["match"] == match_slug
    assert confident["similarity"] >= 0.9
    assert report["skipped_duplicate"] == 1
    assert report["skipped_duplicate_confident"] == 1


def test_confident_band_text_report_lists_separately(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url, "MEM_DEDUP_HIGH": "0.9"}
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    result = run_extract(
        mem,
        [candidate("Mid band", 0, 0.85), candidate("Confident twin", 0, 0.95)],
        env_extra=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert f"skipped-duplicate: Mid band - matches '{match_slug}'" in out
    assert f"skipped-duplicate-confident: Confident twin - matches '{match_slug}'" in out
    assert "extract: 0 added, 1 skipped-duplicate, 1 skipped-duplicate-confident, 0 invalid" in out


def test_legacy_mem_dedup_threshold_env_still_sets_low(mem, kb, band_ollama):
    env = {"MEM_OLLAMA_URL": band_ollama.url, "MEM_DEDUP_THRESHOLD": "0.6"}
    assert mem("init", env_extra=env).returncode == 0
    seed_kb(mem, env, axis=0)
    match_slug_1 = seed_kb(mem, env, axis=1)

    result = run_extract(
        mem,
        [candidate("Below legacy threshold", 0, 0.50), candidate("Above legacy threshold", 1, 0.70)],
        "--json", env_extra=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["threshold"] == 0.6
    below, above = report["results"]
    assert below["disposition"] == "added"
    assert above["disposition"] == "skipped-duplicate"
    assert above["match"] == match_slug_1


def test_new_dedup_low_takes_precedence_over_legacy_threshold(mem, kb, band_ollama):
    env = {
        "MEM_OLLAMA_URL": band_ollama.url,
        "MEM_DEDUP_LOW": "0.5",
        "MEM_DEDUP_THRESHOLD": "0.9",
    }
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    # 0.6 is between the two candidate values: skipped under MEM_DEDUP_LOW=0.5
    # (correct precedence), but would be "added" if the legacy 0.9 name won.
    result = run_extract(mem, [candidate("Precedence probe", 0, 0.60)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["threshold"] == 0.5
    entry = report["results"][0]
    assert entry["disposition"] == "skipped-duplicate"
    assert entry["match"] == match_slug


# The pre-D17 --json object's exact shape (git history: extract.py before
# this brief). A strict/byte-level consumer must see zero difference from
# this when dedup_high is not configured.
PRE_D17_TOP_LEVEL_KEYS = {
    "threshold", "added", "skipped_duplicate", "invalid", "links_remapped", "results",
}
PRE_D17_ADDED_KEYS = {"index", "title", "disposition", "slug", "path"}
PRE_D17_SKIPPED_KEYS = {"index", "title", "disposition", "match", "similarity"}


def test_defaults_produce_pre_d17_golden_json(mem, kb, band_ollama):
    # No band env set at all: dedup_low falls back to DEFAULT_DEDUP_LOW and
    # dedup_high stays None - this is the back-compat acceptance bar. Unlike
    # asserting individual keys equal their old values, this pins the exact
    # key *set* so a stray additive key would fail it too.
    env = {"MEM_OLLAMA_URL": band_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    added_result = run_extract(mem, [candidate("Distinct low", 0, 0.50)], "--json", env_extra=env)
    assert added_result.returncode == 0, added_result.stdout + added_result.stderr
    added_report = json.loads(added_result.stdout)
    assert set(added_report.keys()) == PRE_D17_TOP_LEVEL_KEYS
    assert added_report["threshold"] == config.DEFAULT_DEDUP_LOW == 0.79
    assert added_report["added"] == 1
    assert added_report["skipped_duplicate"] == 0
    added_entry = added_report["results"][0]
    assert set(added_entry.keys()) == PRE_D17_ADDED_KEYS
    assert added_entry["disposition"] == "added"

    dup_result = run_extract(mem, [candidate("Plain dup", 0, 0.90)], "--json", env_extra=env)
    assert dup_result.returncode == 0, dup_result.stdout + dup_result.stderr
    dup_report = json.loads(dup_result.stdout)
    assert set(dup_report.keys()) == PRE_D17_TOP_LEVEL_KEYS
    dup_entry = dup_report["results"][0]
    assert set(dup_entry.keys()) == PRE_D17_SKIPPED_KEYS
    assert dup_entry["disposition"] == "skipped-duplicate"
    assert dup_entry["match"] == match_slug


def test_dedup_high_configured_adds_new_json_keys(mem, kb, band_ollama):
    # Mirror image of the golden test: with dedup_high configured, the two
    # new top-level keys appear - proving the additions are opt-in, not
    # baked into the default shape.
    env = {"MEM_OLLAMA_URL": band_ollama.url, "MEM_DEDUP_HIGH": "0.9"}
    assert mem("init", env_extra=env).returncode == 0
    seed_kb(mem, env, axis=0)

    result = run_extract(mem, [candidate("Confident twin", 0, 0.95)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert set(report.keys()) == PRE_D17_TOP_LEVEL_KEYS | {
        "dedup_high", "skipped_duplicate_confident",
    }
    assert report["dedup_high"] == 0.9
    assert report["skipped_duplicate_confident"] == 1
    entry = report["results"][0]
    assert set(entry.keys()) == PRE_D17_SKIPPED_KEYS
    assert entry["disposition"] == "skipped-duplicate-confident"


def test_low_boundary_exact_equality_is_skipped_duplicate(mem, kb, band_ollama):
    # s == dedup_low exactly must land in the reviewable band (inclusive
    # lower bound: `>=`, not `>`). Configuring dedup_low = 1.0 and using a
    # candidate identical to the seed gives an exact cosine of 1.0 - float32
    # arithmetic on identical vectors is exact, so this pins the boundary
    # bit-exactly rather than by a margin.
    env = {"MEM_OLLAMA_URL": band_ollama.url, "MEM_DEDUP_LOW": "1.0"}
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    result = run_extract(mem, [candidate("Exact low twin", 0, 1.0)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = json.loads(result.stdout)["results"][0]
    assert entry["similarity"] == 1.0
    assert entry["disposition"] == "skipped-duplicate"
    assert entry["match"] == match_slug


def test_high_boundary_exact_equality_is_skipped_duplicate_confident(mem, kb, band_ollama):
    # Same exact-cosine trick, at the dedup_high boundary this time: s ==
    # dedup_high exactly must land in the confident band (inclusive upper
    # gate's own `>=`, not `>`).
    env = {
        "MEM_OLLAMA_URL": band_ollama.url,
        "MEM_DEDUP_LOW": "0.5",
        "MEM_DEDUP_HIGH": "1.0",
    }
    assert mem("init", env_extra=env).returncode == 0
    match_slug = seed_kb(mem, env, axis=0)

    result = run_extract(mem, [candidate("Exact high twin", 0, 1.0)], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = json.loads(result.stdout)["results"][0]
    assert entry["similarity"] == 1.0
    assert entry["disposition"] == "skipped-duplicate-confident"
    assert entry["match"] == match_slug


def test_dedup_high_not_exceeding_low_refused_cleanly(mem, kb):
    # A confident band configured at or below the reviewable one's floor is
    # a degenerate/reversed pair (D17 gate open question) - refused rather
    # than silently prioritizing the low gate.
    assert mem("init").returncode == 0
    payload = [{"title": "Whatever", "body": "Whatever body."}]
    for low, high in [("0.8", "0.8"), ("0.8", "0.5")]:
        result = run_extract(mem, payload, env_extra={"MEM_DEDUP_LOW": low, "MEM_DEDUP_HIGH": high})
        assert result.returncode == 1, (low, high)
        err_lines = [line for line in result.stderr.splitlines() if line.strip()]
        assert len(err_lines) == 1 and err_lines[0].startswith("error:"), result.stderr


def test_non_finite_or_unparseable_dedup_env_refused_cleanly(mem, kb):
    assert mem("init").returncode == 0
    payload = [{"title": "Whatever", "body": "Whatever body."}]
    for env_extra in (
        {"MEM_DEDUP_LOW": "nan"},
        {"MEM_DEDUP_HIGH": "inf"},
        {"MEM_DEDUP_LOW": "not-a-number"},
    ):
        result = run_extract(mem, payload, env_extra=env_extra)
        assert result.returncode == 1, env_extra
        err_lines = [line for line in result.stderr.splitlines() if line.strip()]
        assert len(err_lines) == 1 and err_lines[0].startswith("error:"), result.stderr


def test_personal_calibration_artifact_defaults_match_config():
    from pathlib import Path

    artifact = (
        Path(__file__).resolve().parents[1]
        / "research" / "dedup-calibration-personal-2026-08-17.md"
    )
    assert artifact.is_file(), "research/dedup-calibration-personal-2026-08-17.md is missing"
    # Collapse line-wrapping so a marker split across a hard-wrapped line
    # (as this prose is) still matches a single-line regex.
    text = " ".join(artifact.read_text(encoding="utf-8").split())
    assert re.search(r"`dedup_low`.*?\*\*default 0\.79\*\*", text), (
        "artifact's documented dedup_low default has drifted from its stated 0.79"
    )
    assert re.search(r"`dedup_high`.*?\*\*default disabled\*\*", text), (
        "artifact's documented dedup_high default has drifted from 'disabled'"
    )
    assert config.DEFAULT_DEDUP_LOW == 0.79
    assert config.DEFAULT_DEDUP_HIGH is None
