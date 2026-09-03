"""D18 Wave 3b - S7 (semantic claim leg, shipped OFF) + S8 (calibration Stage
1a/1b harness + artifact, `mem save --dedup-check`) proof rows from
research/d18-dedup-detection-design-2026-09-02.md S4.7/S4.9.

S6 (rewiring `mem extract` onto `dedup.detect()`) is DEFERRED as a follow-up
decision (Brent, 2026-09-03, after its cap-round gate): extract.py is
byte-identical to the pre-D18 code and is NOT exercised here. The detector's
shipped surfaces are `mem dedup` and `mem save --dedup-check`.
"""

import json
import re
from pathlib import Path

import pytest

from fakes import FakeOllamaServer

from agent_memory import dedup


DIMS = 32
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:d18w3"

SYNONYM_CLASSES = [
    {"spaced", "spacing", "interval", "intervals"},
    {"repetition", "review", "reviews", "rehearsal"},
    {"transformer", "attention", "quadratic"},
    {"context", "window", "tokens"},
    {"docker", "container", "image"},
    {"cache", "caching", "layer", "layers"},
]


def words_of(text: str) -> set:
    return set(re.findall(r"[a-z]+", text.lower()))


def semantic_vec(text: str, dims: int) -> list:
    vec = [0.0] * dims
    for i, cls in enumerate(SYNONYM_CLASSES):
        if words_of(text) & cls:
            vec[i] = 1.0
    if not any(vec):
        vec[len(SYNONYM_CLASSES)] = 1.0
    return vec


@pytest.fixture
def semantic_ollama():
    server = FakeOllamaServer(dims=DIMS, model=MODEL, embed_fn=semantic_vec, digest=DIGEST)
    yield server
    server.stop()


SEED = {
    "title": "Spaced repetition scheduling",
    "body": "Reviews at increasing intervals beat cramming for retention.",
}
NEAR_DUP = {
    "title": "Spacing effect for review",
    "body": "Rehearsal spread across growing intervals outperforms massed study.",
}
NOVEL_ATTENTION = {
    "title": "Attention is quadratic",
    "body": "Transformer attention cost grows with the square of the context window tokens.",
    "topics": ["ml", "transformers"],
}
NOVEL_DOCKER = {
    "title": "Docker layer caching",
    "body": "Docker reuses image layers; ordering commands preserves the cache.",
    "topics": "devops, docker",
}
INVALID_NO_BODY = {"title": "No body here"}


def seed_kb(mem, env) -> str:
    result = mem("save", "--title", SEED["title"], "--body", SEED["body"], env_extra=env)
    assert result.returncode == 0, result.stderr
    return "spaced-repetition-scheduling"














def test_semantic_claim_or_flag_fires_on_zero_lexical_overlap_paraphrase():
    """Two claims sharing NO tokens (verified: disjoint word stems) but the
    same embedding (cosine 1.0) - lexical coverage is 0.000 with the leg off,
    1.000 with it on, and `matched()`'s OR only fires once semantic_cosine
    AND sem_threshold are both supplied (S4.2)."""
    idf = lambda _t: 1.0  # noqa: E731 - matched()/coverage recompute containment fresh per pair

    candidate_tokens = frozenset(dedup.claims.tokenize(
        "Cooling fresh vegetables under a chilly forty mark reduces microbial expansion a lot."
    ))
    card_tokens = frozenset(dedup.claims.tokenize(
        "Storing perishable produce below four degrees slows bacterial growth significantly."
    ))
    assert candidate_tokens & card_tokens == frozenset()  # zero shared tokens, by construction

    cand = dedup.Claim(text="candidate claim", tokens=candidate_tokens, weight=5.0, vec=(1.0, 0.0, 0.0))
    card = dedup.Claim(text="card claim", tokens=card_tokens, weight=5.0, vec=(1.0, 0.0, 0.0))

    assert dedup.lexical_containment(cand.tokens, card.tokens, idf) == 0.0
    assert dedup._claim_cosine(cand, card) == pytest.approx(1.0)

    # Leg off (no sem_threshold, S1/S2's exact pre-S7 behavior): no match.
    assert not dedup.matched(cand.tokens, card.tokens, idf, 0.5)
    assert dedup.coverage_of_candidate([cand], [card], idf, 0.5) == pytest.approx(0.0)

    # Leg on: the OR fires purely on the semantic side.
    assert dedup.matched(
        cand.tokens, card.tokens, idf, 0.5,
        semantic_cosine=dedup._claim_cosine(cand, card), sem_threshold=0.8,
    )
    assert dedup.coverage_of_candidate(
        [cand], [card], idf, 0.5, sem_threshold=0.8,
    ) == pytest.approx(1.0)

    # build_claims wires Claim.vec from an index-aligned vecs list, exactly
    # what dedup.detect() passes it for the candidate/card claim lists.
    built = dedup.build_claims(["one claim here"], idf, vecs=[[1.0, 0.0, 0.0]])
    assert built[0].vec == (1.0, 0.0, 0.0)
    assert dedup.build_claims(["one claim here"], idf)[0].vec is None  # back-compat: vecs omitted


CLAIM_SEM_SEED = {
    "title": "Spaced repetition scheduling",
    "body": "Reviews at increasing intervals beat cramming for retention.",
}
CLAIM_SEM_CANDIDATE = {
    "title": "Spacing effect for review",
    "body": "Rehearsal spread across growing intervals outperforms massed study.",
}


def test_semantic_claim_leg_absent_from_legs_run_when_unconfigured(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", CLAIM_SEM_SEED["title"], "--body", CLAIM_SEM_SEED["body"], env_extra=env,
    ).returncode == 0

    result = mem("dedup", json.dumps([CLAIM_SEM_CANDIDATE]), "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert "claim_semantic" not in report["config"]["legs_run"]


def test_semantic_claim_leg_present_when_configured_and_caches_on_second_run(mem, kb, semantic_ollama):
    env = {
        "MEM_OLLAMA_URL": semantic_ollama.url,
        "MEM_DEDUP_CLAIM_SEM": "0.5",
    }
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", CLAIM_SEM_SEED["title"], "--body", CLAIM_SEM_SEED["body"], env_extra=env,
    ).returncode == 0

    before_run1 = semantic_ollama.embed_requests
    result1 = mem("dedup", json.dumps([CLAIM_SEM_CANDIDATE]), "--json", env_extra=env)
    assert result1.returncode == 0, result1.stdout + result1.stderr
    report1 = json.loads(result1.stdout)
    assert "claim_semantic" in report1["config"]["legs_run"]
    after_run1 = semantic_ollama.embed_requests

    result2 = mem("dedup", json.dumps([CLAIM_SEM_CANDIDATE]), "--json", env_extra=env)
    assert result2.returncode == 0, result2.stdout + result2.stderr
    after_run2 = semantic_ollama.embed_requests

    run1_posts = after_run1 - before_run1  # batch doc-embed + candidate's own claims + seed's claims (cold)
    run2_posts = after_run2 - after_run1  # seed's claims are now cached - zero new embeds for them
    assert run1_posts == 3, run1_posts
    assert run2_posts == 2, run2_posts
    assert run2_posts < run1_posts


def _db_rows(kb, sql, params=()):
    import sqlite3

    db = kb.kb / ".index" / "mem.db"
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_reindex_claims_flag_populates_and_mem_search_is_byte_unchanged(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url, "MEM_DEDUP_CLAIM_SEM": "0.5"}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", CLAIM_SEM_SEED["title"], "--body", CLAIM_SEM_SEED["body"], env_extra=env,
    ).returncode == 0

    before = mem("search", "spaced repetition intervals", "--json", env_extra=env)
    assert before.returncode == 0

    r = mem("reindex", "--claims", env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "claims:" in r.stdout

    rows = {row[0] for row in _db_rows(kb, "SELECT DISTINCT slug FROM claim_vectors")}
    assert rows == {"spaced-repetition-scheduling"}
    # vectors untouched: still exactly the one whole-card row, same shape.
    vec_rows = {row[0] for row in _db_rows(kb, "SELECT slug FROM vectors")}
    assert vec_rows == {"spaced-repetition-scheduling"}

    after = mem("search", "spaced repetition intervals", "--json", env_extra=env)
    assert after.returncode == 0
    assert after.stdout == before.stdout
    assert after.stderr == before.stderr


def test_plain_reindex_drops_stale_claim_vectors_without_repopulating(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url, "MEM_DEDUP_CLAIM_SEM": "0.5"}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", CLAIM_SEM_SEED["title"], "--body", CLAIM_SEM_SEED["body"], env_extra=env,
    ).returncode == 0
    assert mem("reindex", "--claims", env_extra=env).returncode == 0
    assert _db_rows(kb, "SELECT COUNT(*) FROM claim_vectors")[0][0] > 0

    r = mem("reindex", env_extra=env)  # no --claims: drop stale rows, don't repopulate
    assert r.returncode == 0, r.stdout + r.stderr
    assert _db_rows(kb, "SELECT COUNT(*) FROM claim_vectors")[0][0] == 0




# S8 - calibration artifact + `mem save --dedup-check`
# ==========================================================================


def test_calibration_artifact_recall_reproduces_the_design_baseline():
    """`research/dedup_detection_calibration.py`'s Stage 1b replay must
    reproduce research/d18-dedup-detection-design-2026-09-02.md's §3.1/§3.2
    headline numbers exactly (S4.9's S8 proof row + this brief's verification
    section) - the archive is a fixed, already-scored fence-free artifact,
    so a correct join reproduces the same numbers byte-for-byte, not just
    approximately."""
    artifact = Path(__file__).resolve().parents[1] / "research" / "dedup-detection-calibration-2026-09-02.md"
    assert artifact.is_file(), (
        "research/dedup-detection-calibration-2026-09-02.md is missing - generate it with:"
        " uv run python research/dedup_detection_calibration.py"
    )
    text = artifact.read_text(encoding="utf-8")
    if "Stage 1b - SKIPPED" in text:
        pytest.skip("Stage 1b was skipped when the artifact was generated (archive out of reach)")

    assert "| 1 | 0.810 |" in text
    assert "| 2 | 0.889 |" in text
    assert "| 3 | 0.937 |" in text
    assert "| 5 | 0.968 |" in text
    assert "| 10 | 0.968 |" in text
    assert "MRR: 0.872" in text
    assert "Absent from the archived top-10: 2/63" in text
    assert "| 0.79 | 0.410 |" in text
    assert "| 0.83 | 0.197 |" in text
    assert "| 0.85 | 0.082 |" in text
    assert "| 0.88 | 0.016 |" in text


def test_calibration_artifact_recommended_defaults_match_config_comments():
    """D3/D17's pattern: the artifact's recommended values are pinned - but
    unlike dedup_low (D3) or dedup_high (D17), none of the three D18
    coverage/union seams ships enabled globally (S4.4's ratified per-
    instance posture), so there is no `DEFAULT_DEDUP_COVERAGE_LOW` etc to
    equal. What's pinned: (a) the three defaults really do stay disabled
    (None) for extract's own byte-identical-by-default path; (b) the
    RECOMMENDED values documented in both config.py's comments and the
    artifact agree with each other; AND (c, gate finding 6) the artifact's
    recommended values equal the SHIPPED standalone `mem dedup` overlay
    (`dedupcmd._DEDUP_CMD_*_DEFAULT`, applied by
    `_apply_command_coverage_defaults`) - the actual defaults that activate
    standalone `mem dedup` coverage, not just config.py's globally-disabled
    comments, which a drifted overlay could leave stale forever."""
    from dataclasses import replace

    from agent_memory import config, dedupcmd

    assert config.DEFAULT_DEDUP_COVERAGE_LOW is None
    assert config.DEFAULT_DEDUP_COVERAGE_HIGH is None
    assert config.DEFAULT_DEDUP_UNION_LOW is None

    artifact = Path(__file__).resolve().parents[1] / "research" / "dedup-detection-calibration-2026-09-02.md"
    assert artifact.is_file()
    text = artifact.read_text(encoding="utf-8")
    assert "MEM_DEDUP_COVERAGE_LOW` recommended: 0.35" in text
    assert "MEM_DEDUP_COVERAGE_HIGH` recommended: 0.85" in text
    assert "MEM_DEDUP_UNION_LOW` recommended: 0.55" in text

    config_src = Path(config.__file__).read_text(encoding="utf-8")
    assert "recommended calibrated value: 0.35" in config_src
    assert "recommended: 0.85" in config_src
    assert "recommended: 0.55" in config_src

    # Gate finding 6: pin the SHIPPED overlay constants directly - a
    # mutation of any of these three values must fail this assertion.
    assert dedupcmd._DEDUP_CMD_COVERAGE_LOW_DEFAULT == 0.35
    assert dedupcmd._DEDUP_CMD_COVERAGE_HIGH_DEFAULT == 0.85
    assert dedupcmd._DEDUP_CMD_UNION_LOW_DEFAULT == 0.55

    # And round-trip through the actual applying function, independent of
    # ambient env - a config that hasn't opted into its own coverage values
    # must land on exactly the shipped overlay once `mem dedup` applies it.
    unconfigured = replace(dedup.load_config(), coverage_low=None, coverage_high=None, union_low=None)
    applied = dedupcmd._apply_command_coverage_defaults(unconfigured)
    assert applied.coverage_low == 0.35
    assert applied.coverage_high == 0.85
    assert applied.union_low == 0.55


def test_save_dedup_check_advisory_reports_but_never_blocks(mem, kb, semantic_ollama):
    """--dedup-check is advisory only (S4.6): the save lands and exits 0
    whether or not the candidate flags, and the full detector report goes
    to stderr, never stdout."""
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", SEED["title"], "--body", SEED["body"], env_extra=env,
    ).returncode == 0

    result = mem(
        "save", "--title", NEAR_DUP["title"], "--body", NEAR_DUP["body"],
        "--dedup-check", env_extra=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "saved: spacing-effect-for-review" in result.stdout
    assert '"verdict"' not in result.stdout  # the report never lands on stdout
    assert "dedup-check: verdict=" in result.stderr
    report = json.loads(result.stderr.split("\n", 1)[1])
    assert report["verdict"] in ("review-duplicate", "confident-duplicate")
    assert report["flagged"] is True

    # A file the KB has never seen at all flags nothing, and still saves.
    result = mem(
        "save", "--title", NOVEL_ATTENTION["title"], "--body", NOVEL_ATTENTION["body"],
        "--dedup-check", env_extra=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stderr.split("\n", 1)[1])
    assert report["verdict"] == "novel"
    assert report["flagged"] is False


def test_save_dedup_check_advisory_survives_a_detector_error_after_save(mem, kb):
    """D18 W3 fix cycle (gate finding 4): the save already landed by the
    time `--dedup-check` runs - ANY detector/index failure after that point
    (reproduced here with the exact model-identity mismatch the gate used:
    `vector.VectorError` from `vector.top_k_doc`'s `check_meta`, when the
    index was built under a different model than the check now runs under)
    must degrade to a one-line stderr note, never propagate and never
    change the save's own exit code or stdout."""
    server_old = FakeOllamaServer(dims=DIMS, model="model-old", embed_fn=semantic_vec)
    server_new = FakeOllamaServer(dims=DIMS, model="model-new", embed_fn=semantic_vec)
    try:
        env_old = {"MEM_OLLAMA_URL": server_old.url, "MEM_EMBED_MODEL": "model-old"}
        assert mem("init", env_extra=env_old).returncode == 0
        assert mem(
            "save", "--title", SEED["title"], "--body", SEED["body"], env_extra=env_old,
        ).returncode == 0

        env_new = {"MEM_OLLAMA_URL": server_new.url, "MEM_EMBED_MODEL": "model-new"}
        result = mem(
            "save", "--title", NOVEL_ATTENTION["title"], "--body", NOVEL_ATTENTION["body"],
            "--dedup-check", env_extra=env_new,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "saved: attention-is-quadratic" in result.stdout
        assert '"verdict"' not in result.stdout  # never landed on stdout, degraded or not
        assert "dedup-check: skipped (" in result.stderr
        assert "index built with model model-old, current model is model-new" in result.stderr
    finally:
        server_old.stop()
        server_new.stop()


def test_save_without_dedup_check_flag_is_unchanged(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    result = mem("save", "--title", SEED["title"], "--body", SEED["body"], env_extra=env)
    assert result.returncode == 0
    assert result.stderr == ""


def test_save_dedup_check_refuses_stale_claim_digest_and_repopulates(mem, kb, semantic_ollama):
    """W3b gate finding 1: `mem save --dedup-check` must resolve the model
    digest exactly like standalone `mem dedup`, so a same-model claim row
    stamped under an OLD digest is refused and repopulated under the current
    one - never silently trusted for the advisory's coverage scoring. The
    save itself still exits 0."""
    from array import array

    from agent_memory import claims as claims_mod

    env = {"MEM_OLLAMA_URL": semantic_ollama.url, "MEM_DEDUP_CLAIM_SEM": "0.5"}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", CLAIM_SEM_SEED["title"], "--body", CLAIM_SEM_SEED["body"], env_extra=env,
    ).returncode == 0

    seed_slug = "spaced-repetition-scheduling"
    seed_claim_texts = claims_mod.segment(CLAIM_SEM_SEED["body"])
    text_hash = claims_mod.content_hash(seed_claim_texts[0])
    con = claims_mod.connect(kb.kb)
    try:
        con.execute(
            "INSERT INTO claim_vectors(slug, ordinal, text_hash, model, digest, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (seed_slug, 0, text_hash, MODEL, "sha256:stale",
             array("f", [9.9] * DIMS).tobytes(), "2020-01-01T00:00:00Z"),
        )
        con.commit()
    finally:
        con.close()
    assert _db_rows(kb, "SELECT digest FROM claim_vectors WHERE slug = ?", (seed_slug,)) == [("sha256:stale",)]

    r = mem(
        "save", "--title", CLAIM_SEM_CANDIDATE["title"], "--body", CLAIM_SEM_CANDIDATE["body"],
        "--dedup-check", env_extra=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dedup-check: verdict=" in r.stderr

    rows = _db_rows(kb, "SELECT DISTINCT digest FROM claim_vectors WHERE slug = ?", (seed_slug,))
    assert rows == [(DIGEST,)], rows  # stale row refused + repopulated under the CURRENT digest
