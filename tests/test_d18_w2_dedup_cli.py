"""D18 Wave 2 (S3 chunk index + S4 `mem dedup` CLI + S5 durable log) -
research/d18-dedup-detection-design-2026-09-02.md S4.1/S4.3/S4.5, S4.9's
proof rows for S3/S4/S5.

Patterns reused: `tests/conftest.py`'s `kb`/`mem` fixtures + `fake_ollama_factory`;
`tests/fakes.py`'s meaning-shaped `embed_fn` (the capstone D020 pattern also
used by test_f9_extract.py/f12_netns_driver.py) so dispositions/verdicts are
insensitive to the calibrated threshold's exact value; D8's
`test_reindex_preserves_usage_log` pattern, copied for the dedup log.
"""

import json
import re
import subprocess
import sys

import pytest

from fakes import FakeOllamaServer

from agent_memory import chunks, claims, config, dedup, deduplog, okf, vector

DIMS = 32
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:d18w2"

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


def semantic_env(server) -> dict:
    return {"MEM_OLLAMA_URL": server.url, "MEM_EMBED_DIMS": str(DIMS)}


def save(mem, env, title, body, **extra):
    args = ["save", "--title", title, "--body", body]
    for k, v in extra.items():
        args += [f"--{k.replace('_', '-')}", v]
    r = mem(*args, env_extra=env)
    assert r.returncode == 0, r.stderr
    return okf.slugify(title)


def db_rows(kb, sql, params=()):
    import sqlite3

    db = kb.kb / ".index" / "mem.db"
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def dedup_json(mem, env, file_arg, *flags):
    r = mem("dedup", file_arg, "--json", *flags, env_extra=env)
    return r, (json.loads(r.stdout) if r.returncode == 0 or r.stdout.strip() else None)


# ==========================================================================
# S3 - chunk index
# ==========================================================================


def test_chunk_spans_no_heading_short_body_is_exactly_one_chunk():
    text = "A short body with no headings at all here."
    spans = chunks.chunk_spans(text)
    assert spans == [(0, len(text))]


def test_build_chunks_one_chunk_text_equals_document_text_exactly():
    """The literal S4.3 claim: a <=1,000-char, heading-less card's ONE chunk
    is byte-identical to `vector.document_text` - no special case, just the
    general chunker naturally producing a single full-span chunk."""
    concept = okf.Concept(
        slug="short-card", title="Short card", description="d", type="concept",
        topics=["x"], sensitivity="normal", created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z", body="A short body with no headings.",
    )
    built = chunks.build_chunks(concept)
    assert len(built) == 1
    (ordinal, start, end, text) = built[0]
    assert (ordinal, start, end) == (0, 0, len(vector.document_text(concept)))
    assert text == vector.document_text(concept)


def test_long_heading_less_section_windows_never_exceed_hard_cap():
    text = "word " * 2000  # 10,000 chars, no headings
    spans = chunks.chunk_spans(text)
    assert len(spans) > 1
    for s, e in spans:
        assert e - s <= chunks.HARD_CAP_CHARS
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    # 50% stride overlap: consecutive windows share half their span
    stride = spans[1][0] - spans[0][0]
    assert stride == pytest.approx(chunks.TARGET_CHARS * (1 - chunks.STRIDE_OVERLAP), abs=1)


def test_gate8_two_block_boundary_golden_no_interior_cut_no_zero_overlap():
    """Gate finding 8 + re-gate finding 2: two ~900-char paragraphs used to be
    sliced at raw character offsets (round 1), then split cleanly but with
    ZERO overlap (round 2). The ratified rule: a single-block chunk with
    blocks remaining FORCE-INCLUDES the next block when the pair fits the
    hard cap - here that yields ONE span covering both blocks whole, so a
    unit at the boundary appears complete in a window and no interior is
    ever cut."""
    text = ("A" * 900) + "\n\n" + ("B" * 900)
    spans = chunks.chunk_spans(text)
    assert spans == [(0, len(text))]


def test_regate2_multi_block_runs_never_advance_with_zero_overlap():
    """Re-gate finding 2, general form: across a run of near-target blocks,
    every adjacent pair of block-grain spans overlaps (the trailing block is
    re-included whole) - a zero-overlap advance is the defect class."""
    n_blocks = 4
    text = "\n\n".join("R%d %s" % (k, "z" * 896) for k in range(n_blocks))
    spans = chunks.chunk_spans(text, target=1000, hard_cap=4000)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    for (s1, e1), (s2, e2) in zip(spans, spans[1:]):
        assert s2 < e1, f"zero-overlap advance between {(s1, e1)} and {(s2, e2)}"


def test_regate2_over_cap_block_pair_takes_the_character_window_fallback():
    """When even a PAIR of adjacent blocks exceeds the hard cap there is no
    block-aligned representation satisfying overlap - the ratified fallback
    is `_windows` character slides over the pair (same fallback class as an
    oversize single block). Coverage must be complete and overlapping."""
    text = ("Q0 " + "y" * 2500) + "\n\n" + ("Q1 " + "y" * 2500)
    spans = chunks.chunk_spans(text, target=1000, hard_cap=4000)
    assert spans[0][0] == 0
    assert max(e for _, e in spans) == len(text)
    covered = set()
    for s1, e1 in spans:
        covered.update(range(s1, e1))
    assert covered == set(range(len(text)))


def test_gate8_long_single_block_fallback_matches_the_pre_fix_character_windows():
    """The "long-single-block fallback" the brief pins: a section with NO
    internal blank line has no finer boundary than characters, so it must
    fall back to exactly the same sliding-window algorithm the whole
    chunker used before this fix - `_windows`, unchanged - preserving the
    cap/overlap guarantees `test_long_heading_less_section_windows_never_
    exceed_hard_cap` already pins for that function directly."""
    text = "word" * 1300  # 5,200 chars, no blank line anywhere
    assert chunks.chunk_spans(text) == chunks._windows(0, len(text), chunks.TARGET_CHARS)


def test_gate8_three_block_grouping_overlaps_the_shared_middle_block():
    """A run of several small blocks (none alone over target) groups whole
    blocks up to ~target per chunk, with the 50%-overlap guarantee expressed
    as a whole re-included trailing block (never a sub-block cut). Pinned
    to the exact BLOCK-aligned boundaries (402, 804) - not just "some
    overlap exists", which the pre-fix raw-character `_windows(0, 1204,
    1000)` (stride 500: [(0,1000),(500,1204)]) would also satisfy."""
    text = "\n\n".join(["X" * 400] * 3)
    spans = chunks.chunk_spans(text)
    assert spans == [(0, 804), (402, 1204)]
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)


def test_reindex_chunks_flag_populates_and_mem_search_is_byte_unchanged(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Docker layer caching", "Docker reuses image layers for the cache.")
    save(mem, env, "Spaced repetition", "Reviews at increasing intervals beat cramming.")

    before = mem("search", "docker layers", "--json", env_extra=env)
    assert before.returncode == 0

    r = mem("reindex", "--chunks", env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "chunks:" in r.stdout

    rows = db_rows(kb, "SELECT DISTINCT slug FROM chunks")
    assert {row[0] for row in rows} == {"docker-layer-caching", "spaced-repetition"}
    # vectors untouched: still exactly the two whole-card rows, same shape
    vec_rows = db_rows(kb, "SELECT slug FROM vectors")
    assert {row[0] for row in vec_rows} == {"docker-layer-caching", "spaced-repetition"}

    after = mem("search", "docker layers", "--json", env_extra=env)
    assert after.returncode == 0
    assert after.stdout == before.stdout
    assert after.stderr == before.stderr


def test_reindex_chunks_excludes_and_reports_oversize_card(mem, kb, semantic_ollama):
    env = dict(semantic_env(semantic_ollama))
    env["MEM_DEDUP_CHUNK_SKIP_CHARS"] = "150"  # document_text = title+description+body, not body alone
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Small card", "Docker reuses image layers for the cache today.")
    save(mem, env, "Huge card", "Docker container image cache. " * 20)  # well over 150 chars total

    r = mem("reindex", "--chunks", env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipped-oversize" in r.stdout
    assert "1 skipped-oversize" in r.stdout

    rows = {row[0] for row in db_rows(kb, "SELECT DISTINCT slug FROM chunks")}
    assert rows == {"small-card"}


def test_plain_reindex_drops_stale_chunks_without_repopulating(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Docker layer caching", "Docker reuses image layers for the cache.")
    assert mem("reindex", "--chunks", env_extra=env).returncode == 0
    assert db_rows(kb, "SELECT COUNT(*) FROM chunks")[0][0] > 0

    r = mem("reindex", env_extra=env)  # no --chunks: drop stale rows, don't repopulate
    assert r.returncode == 0, r.stdout + r.stderr
    assert db_rows(kb, "SELECT COUNT(*) FROM chunks")[0][0] == 0


def test_deep_k_and_top_m_cli_overrides_are_honored(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r, payload = dedup_json(
        mem, env, json.dumps([{"title": "X", "body": "Docker reuses image layers."}]),
        "--deep-k", "7", "--top-m", "2",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["config"]["deep_k"] == 7


def test_chunk_leg_finds_spine_card_invisible_to_whole_document_cosine(mem, kb, semantic_ollama):
    """S4.9's headline S3 proof: a spine/reference card spanning several
    unrelated topic sections dilutes its whole-card embedding (multi-hot
    under the fake embedder) below `dedup_low`, while ONE of its sections,
    chunked on its own, embeds as a pure match for a single-topic
    candidate - `cosine_best_chunk` clears the threshold `cosine_document`
    cannot."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0

    spine_body = (
        "## Docker section\n\nDocker reuses image layers for the cache.\n\n"
        "## Transformer section\n\nTransformer attention cost grows quadratically.\n\n"
        "## Context section\n\nThe context window holds many tokens.\n\n"
        "## Repetition section\n\nSpaced repetition intervals aid review.\n"
    )
    save(mem, env, "Reference spine index", spine_body)

    r = mem("reindex", "--chunks", env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr

    candidate = {"title": "Docker caching note", "body": "Docker layer caching reuses images."}
    dedup_env = dict(env)
    dedup_env["MEM_DEDUP_CHUNKS"] = "1"
    r, payload = dedup_json(mem, dedup_env, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    hit = next(h for h in entry["hits"] if h["slug"] == "reference-spine-index")

    assert hit["cosine_document"] < config.DEFAULT_DEDUP_LOW  # diluted, whole-card leg misses it
    assert hit["cosine_best_chunk"] is not None
    assert hit["cosine_best_chunk"] >= config.DEFAULT_DEDUP_LOW  # one section is a pure match
    assert "vector_chunk" in hit["legs"]
    assert entry["decisions"]["cosine_chunk_max"]["crossed"] is True
    assert entry["flagged"] is True


# ==========================================================================
# S4 - `mem dedup` CLI: report shape, un-misreadable contract
# ==========================================================================


def _walk_keys(obj, found: set):
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.add(k)
            _walk_keys(v, found)
    elif isinstance(obj, list):
        for item in obj:
            _walk_keys(item, found)


def test_json_report_never_emits_score_or_semantic_similarity_at_any_depth(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")

    candidates = [
        {"title": "Reviewing at growing intervals",
         "body": "Spacing out review sessions with growing intervals beats cramming."},
        {"title": "Docker layer caching", "body": "Docker reuses image layers for the cache."},
    ]
    r, payload = dedup_json(mem, env, json.dumps(candidates), "--explain")
    assert r.returncode == 0, r.stdout + r.stderr

    found: set = set()
    _walk_keys(payload, found)
    assert "score" not in found
    assert "semantic_similarity" not in found


def test_verdict_flagged_recommended_action_always_present(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")

    candidates = [
        {"title": "Reviewing at growing intervals",
         "body": "Spacing out review sessions with growing intervals beats cramming."},  # review-duplicate
        {"title": "Docker layer caching", "body": "Docker reuses image layers for the cache."},  # novel
        {"body": "no title here"},  # invalid
    ]
    r, payload = dedup_json(mem, env, json.dumps(candidates))
    assert r.returncode == 0, r.stdout + r.stderr
    verdicts = {c["verdict"] for c in payload["candidates"]}
    assert verdicts == {"review-duplicate", "novel", "invalid"}
    for c in payload["candidates"]:
        assert "verdict" in c and "flagged" in c and "recommended_action" in c
    invalid = next(c for c in payload["candidates"] if c["verdict"] == "invalid")
    assert invalid["flagged"] is False and invalid["recommended_action"] is None


def test_decisions_entries_carry_value_threshold_crossed_scope(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r, payload = dedup_json(
        mem, env, json.dumps([{"title": "X", "body": "Docker reuses image layers for the cache."}])
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for decision in payload["candidates"][0]["decisions"].values():
        assert set(decision) == {"value", "threshold", "crossed", "scope"}
        assert isinstance(decision["crossed"], bool)


def test_fusion_rank_is_int_and_no_rrf_float_leaks(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r, payload = dedup_json(
        mem, env,
        json.dumps([{"title": "X", "body": "Reviews at increasing intervals beat cramming today."}]),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    hits = payload["candidates"][0]["hits"]
    assert hits
    for h in hits:
        assert isinstance(h["fusion_rank"], int) and not isinstance(h["fusion_rank"], bool)


def test_exit_0_on_flagged_analysis_and_on_novel(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r, payload = dedup_json(
        mem, env, json.dumps([{"title": "X", "body": "Reviews at increasing intervals beat cramming today."}])
    )
    assert r.returncode == 0
    assert payload["candidates"][0]["flagged"] is True


def test_exit_1_when_no_kb(mem, kb):
    r = mem("dedup", json.dumps([{"title": "X", "body": "some body text here"}]))
    assert r.returncode == 1
    assert r.stderr.strip().startswith("error:")


def test_exit_1_on_invalid_band_config(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    bad_env = dict(env)
    bad_env["MEM_DEDUP_HIGH"] = "0.1"  # <= default dedup_low -> refused
    r = mem("dedup", json.dumps([{"title": "X", "body": "some body text here"}]), env_extra=bad_env)
    assert r.returncode == 1
    assert r.stderr.strip().startswith("error:")


# ==========================================================================
# S4 - input sniffing: candidates JSON (path/-/inline), OKF card, markdown
# ==========================================================================


def test_input_sniffing_candidates_json_via_path(mem, kb, semantic_ollama, tmp_path):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    path = tmp_path / "cands.json"
    path.write_text(json.dumps([{"title": "Docker layer caching", "body": "Docker reuses image layers."}]))
    r, payload = dedup_json(mem, env, str(path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["candidates"][0]["title"] == "Docker layer caching"


def test_input_sniffing_candidates_json_via_stdin(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    payload_in = json.dumps([{"title": "Docker layer caching", "body": "Docker reuses image layers."}])
    r = mem("dedup", "-", "--json", env_extra=env, input=payload_in)
    assert r.returncode == 0, r.stdout + r.stderr
    payload = json.loads(r.stdout)
    assert payload["candidates"][0]["title"] == "Docker layer caching"


def test_input_sniffing_inline_json(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r, payload = dedup_json(
        mem, env, json.dumps([{"title": "Docker layer caching", "body": "Docker reuses image layers."}])
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["candidates"][0]["title"] == "Docker layer caching"


def test_input_sniffing_okf_card_file(mem, kb, semantic_ollama, tmp_path):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Docker layer caching", "Docker reuses image layers for the cache today.")

    card_text = okf.serialize(okf.Concept(
        slug="docker-recheck", title="Docker recheck", description="d", type="concept",
        topics=[], sensitivity="normal", created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z",
        body="Docker reuses image layers for the cache today.",
    ))
    path = tmp_path / "card.md"
    path.write_text(card_text)
    r, payload = dedup_json(mem, env, str(path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["candidates"][0]["title"] == "Docker recheck"
    assert payload["candidates"][0]["flagged"] is True  # identical body to the saved card


def test_input_sniffing_plain_markdown_file_title_from_heading(mem, kb, semantic_ollama, tmp_path):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    path = tmp_path / "note.md"
    path.write_text("# Docker layer caching\n\nDocker reuses image layers for the cache.\n")
    r, payload = dedup_json(mem, env, str(path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["candidates"][0]["title"] == "Docker layer caching"


def test_input_sniffing_plain_markdown_file_title_from_flag(mem, kb, semantic_ollama, tmp_path):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    path = tmp_path / "note.md"
    path.write_text("Docker reuses image layers for the cache with no heading at all.\n")
    r, payload = dedup_json(mem, env, str(path), "--title", "Docker caching note")
    assert r.returncode == 0, r.stdout + r.stderr
    assert payload["candidates"][0]["title"] == "Docker caching note"


def test_input_sniffing_okf_card_recheck_excludes_itself_from_its_own_hits(mem, kb, semantic_ollama, tmp_path):
    """Re-checking an EXISTING card (the input OKF file's slug equals a KB
    slug) must never surface the card as its own duplicate hit at cosine
    1.0 - self-comparison is noise, not signal."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Docker layer caching", "Docker reuses image layers for the cache today.")

    card_text = (kb.kb / "concepts" / "docker-layer-caching.md").read_text(encoding="utf-8")
    path = tmp_path / "recheck.md"
    path.write_text(card_text)
    r, payload = dedup_json(mem, env, str(path))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    assert entry["slug_intended"] == "docker-layer-caching"
    assert all(h["slug"] != "docker-layer-caching" for h in entry["hits"])
    assert entry["verdict"] == "novel"


def test_input_sniffing_plain_markdown_no_title_refused(mem, kb, semantic_ollama, tmp_path):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    path = tmp_path / "note.md"
    path.write_text("No heading and no title flag either, just plain text.\n")
    r = mem("dedup", str(path), env_extra=env)
    assert r.returncode == 1
    assert "error:" in r.stderr


# ==========================================================================
# S4 - degradation: empty lexical leg (all-unseen candidate)
# ==========================================================================


def test_empty_lexical_leg_all_unseen_candidate_still_runs_and_says_so(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")

    # every content word here is unseen by the lexical index -> dedup_match_expr
    # returns "" (W1's all-unseen case) - the leg must be omitted cleanly,
    # not error, and the run must still complete via the other legs.
    candidate = {"title": "Zephyr wombat quokka", "body": "Zephyr wombat quokka platypus armadillo iguana."}
    r, payload = dedup_json(mem, env, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    assert entry["verdict"] == "novel"
    assert any("lexical leg" in note for note in entry["notes"])
    assert "lexical" in payload["config"]["legs_run"]  # the leg is configured/attempted regardless


# ==========================================================================
# S4 - --adjudicate happy path + refusal
# ==========================================================================


def test_adjudicate_happy_path_joins_on_run_id_and_hash(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")

    run_env = dict(env)
    run_env["MEM_RUN_ID"] = "fixed-run-1"
    r, payload = dedup_json(mem, run_env, json.dumps([{"title": "X", "body": "Docker reuses image layers."}]))
    assert r.returncode == 0, r.stdout + r.stderr
    content_hash = payload["candidates"][0]["content_hash"]

    r2 = mem(
        "dedup", "--adjudicate", "fixed-run-1", "--candidate", content_hash,
        "--label", "DISTINCT", "--by", "brent", env_extra=env,
    )
    assert r2.returncode == 0, r2.stdout + r2.stderr

    records = deduplog.read_records(kb.kb)
    adjudications = [r for r in records if r["type"] == "adjudication"]
    assert len(adjudications) == 1
    assert adjudications[0]["run_id"] == "fixed-run-1"
    assert adjudications[0]["candidate_content_hash"] == content_hash
    assert adjudications[0]["label"] == "DISTINCT"
    assert adjudications[0]["by"] == "brent"


def test_adjudicate_refuses_when_no_matching_detection(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r = mem(
        "dedup", "--adjudicate", "nonexistent-run", "--candidate", "sha256:deadbeef",
        "--label", "DUP", env_extra=env,
    )
    assert r.returncode == 1
    assert "error:" in r.stderr
    assert deduplog.read_records(kb.kb) == []


def test_adjudicate_requires_candidate_and_label(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r = mem("dedup", "--adjudicate", "some-run", env_extra=env)
    assert r.returncode == 1
    assert "error:" in r.stderr


# ==========================================================================
# S5 - durable log: .index/dedup-log.jsonl
# ==========================================================================


def read_log_lines(kb):
    path = kb.kb / ".index" / "dedup-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_dedup_run_writes_a_detection_record_by_default(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r = mem("dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]), env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    records = read_log_lines(kb)
    assert len(records) == 1
    assert records[0]["type"] == "detection"
    assert records[0]["command"] == "dedup"
    assert "config" in records[0] and records[0]["config"]["deep_k"] == config.DEFAULT_DEDUP_DEEP_K


def test_no_log_flag_suppresses_the_write(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r = mem(
        "dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]),
        "--no-log", env_extra=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_log_lines(kb) == []


def test_mem_dedup_log_env_var_suppresses_the_write(mem, kb, semantic_ollama):
    env = dict(semantic_env(semantic_ollama))
    env["MEM_DEDUP_LOG"] = "0"
    assert mem("init", env_extra=env).returncode == 0
    r = mem("dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]), env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert read_log_lines(kb) == []


def test_log_titles_off_omits_titles_everywhere_in_the_record(mem, kb, semantic_ollama):
    env = dict(semantic_env(semantic_ollama))
    env["MEM_DEDUP_LOG_TITLES"] = "0"
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r = mem(
        "dedup",
        json.dumps([{"title": "Reviewing at growing intervals",
                     "body": "Spacing out review sessions with growing intervals beats cramming."}]),
        env_extra=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    records = read_log_lines(kb)
    assert len(records) == 1
    assert "title" not in records[0]["candidate"]
    for hit in records[0]["hits"]:
        assert "title" not in hit
    raw = json.dumps(records[0])
    assert "Reviewing at growing intervals" not in raw
    assert "Spaced repetition scheduling" not in raw


def test_no_card_body_ever_appears_in_the_log(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    distinctive_body = "The quokka migration corpus body sentence is distinctive and searchable."
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    r = mem(
        "dedup",
        json.dumps([{"title": "Reviewing at growing intervals", "body": distinctive_body}]),
        env_extra=env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    log_path = kb.kb / ".index" / "dedup-log.jsonl"
    raw_bytes = log_path.read_bytes()
    assert b"quokka migration corpus" not in raw_bytes
    assert b"Reviews at increasing intervals beat cramming" not in raw_bytes


def test_every_log_line_under_4096_bytes_with_hits_truncated_flag(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    # Seed many near-identical cards sharing the same synonym class, so the
    # deep-K hit list for one candidate is long enough to force truncation.
    for i in range(20):
        save(mem, env, f"Docker caching note {i}", f"Docker reuses image layers for the cache variant {i}.")
    dedup_env = dict(env)
    dedup_env["MEM_DEDUP_DEEP_K"] = "20"
    r = mem(
        "dedup", json.dumps([{"title": "Docker caching lookup", "body": "Docker reuses image layers for the cache."}]),
        env_extra=dedup_env,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    records = read_log_lines(kb)
    assert len(records) == 1
    line_bytes = json.dumps(records[0], ensure_ascii=False).encode("utf-8")
    assert len(line_bytes) + 1 < deduplog.LINE_LIMIT  # +1 newline: strictly under
    assert len(records[0]["hits"]) <= deduplog.MAX_INLINE_HITS
    if len(records[0]["hits"]) < 20:
        assert records[0]["hits_truncated"] is True


def test_reindex_preserves_dedup_log(mem, kb, semantic_ollama):
    """Copies D8's `test_reindex_preserves_usage_log` pattern exactly:
    `.index/dedup-log.jsonl` is not derived state, so `mem reindex` must
    leave it alone."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    assert mem("dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]), env_extra=env).returncode == 0
    before = read_log_lines(kb)
    assert len(before) == 1

    r = mem("reindex", env_extra=env)
    assert r.returncode == 0, r.stdout + r.stderr

    after = read_log_lines(kb)
    assert after == before  # untouched, byte for byte


def test_detection_and_later_adjudication_join_on_run_id_and_content_hash(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    run_env = dict(env)
    run_env["MEM_RUN_ID"] = "join-run-1"
    r = mem("dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]), "--json", env_extra=run_env)
    assert r.returncode == 0, r.stdout + r.stderr
    content_hash = json.loads(r.stdout)["candidates"][0]["content_hash"]

    r2 = mem(
        "dedup", "--adjudicate", "join-run-1", "--candidate", content_hash,
        "--label", "FOLD", env_extra=env,
    )
    assert r2.returncode == 0, r2.stdout + r2.stderr

    records = read_log_lines(kb)
    detections = [r for r in records if r["type"] == "detection"]
    adjudications = [r for r in records if r["type"] == "adjudication"]
    assert len(detections) == 1 and len(adjudications) == 1
    assert detections[0]["run_id"] == adjudications[0]["run_id"] == "join-run-1"
    assert detections[0]["candidate"]["content_hash"] == adjudications[0]["candidate_content_hash"]
    assert adjudications[0]["label"] == "FOLD"


# ==========================================================================
# D18 W2 fix cycle (work/agents/d18-w2-gate/verifier/output.md) - pinning
# each Class-1 finding's reproduction so it cannot silently regress.
# ==========================================================================


def test_gate1_coverage_on_default_flags_exact_duplicate_with_semantic_legs_unavailable(mem, kb):
    """Gate finding 1 reproduction: with all three coverage env vars
    unset, an exact lexical duplicate scored coverage_of_candidate_max=1.0
    but its threshold was null/crossed=false/verdict novel - the ratified
    coverage-on default (DECISION_LOG D18 S4.4) never actually applied to
    standalone `mem dedup`. No `semantic_ollama` fixture here on purpose:
    the daemon stays down (the `kb` fixture's default closed-port URL), so
    only the coverage-only legs can possibly flag this."""
    assert mem("init").returncode == 0
    save(mem, {}, "Docker layer caching", "Docker reuses image layers for the cache today.")

    candidate = {"title": "Docker layer caching copy",
                 "body": "Docker reuses image layers for the cache today."}
    r, payload = dedup_json(mem, {}, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    assert "vector_document" not in payload["config"]["legs_run"]  # semantic legs truly absent
    decision = entry["decisions"]["coverage_of_candidate_max"]
    assert decision["threshold"] == pytest.approx(0.35)
    assert decision["crossed"] is True
    assert entry["flagged"] is True
    assert entry["verdict"] != "novel"


def test_gate1_coverage_on_default_flags_union_only_duplicate_with_semantic_legs_unavailable(mem, kb):
    """Gate finding 1's second pin: a composite candidate whose halves each
    sit BELOW the coverage-low floor individually, but whose greedy union
    crosses coverage_union_low - the "union-only" duplicate class the
    detector exists to catch, still with semantic legs unavailable."""
    assert mem("init").returncode == 0
    save(mem, {}, "Docker layer caching", "Docker reuses image layers for caching.")
    save(mem, {}, "Spaced repetition scheduling",
         "Spaced repetition improves long term retention of study material.")

    candidate = {
        "title": "Composite of both cards",
        "body": (
            "Docker reuses image layers for caching. "
            "Spaced repetition improves long term retention of study material. "
            "Zebra kangaroo pineapple lorem ipsum wonderful fantastic."
        ),
    }
    r, payload = dedup_json(mem, {}, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    assert "vector_document" not in payload["config"]["legs_run"]
    assert entry["decisions"]["coverage_of_candidate_max"]["crossed"] is False  # neither half alone
    union_decision = entry["decisions"]["coverage_union"]
    assert union_decision["threshold"] == pytest.approx(0.55)
    assert union_decision["crossed"] is True
    assert entry["flagged"] is True
    assert entry["verdict"] != "novel"
    assert len(entry["union"]["member_slugs"]) == 2


def test_gate2_ruling_a_fallback_relation_never_changes_verdict_when_coverage_unconfigured(
    mem, kb, semantic_ollama, monkeypatch,
):
    """Gate finding 2 / orchestrator Ruling A, reproduced exactly: coverage
    thresholds unset, cosine confident-crossed, the winning hit's cc/cd =
    (0.148, 1.0) - fallback high 0.85 labels it candidate-superset (a
    downgrade-worthy relation under the OLD code), fallback high 0.01
    labels it equivalent. Ruling A: since coverage is unconfigured, this
    label is presentation-only and must never change the verdict either
    way - cosine-only routing stands, `label_basis` says "fallback"."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HOME", str(kb.home))
    monkeypatch.setenv("MEM_DEDUP_HIGH", "0.8")  # > dedup_low (0.79); still cheap for cosine=1.0 to cross
    monkeypatch.delenv("MEM_DEDUP_COVERAGE_LOW", raising=False)
    monkeypatch.delenv("MEM_DEDUP_COVERAGE_HIGH", raising=False)

    candidate = okf.Concept(
        slug="candidate-note", title="Candidate note", description="d", type="concept",
        topics=[], sensitivity="normal", created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z", related=[], source="test",
        body=(
            "Reviews at increasing intervals beat cramming. "
            "Also this note discusses zebra kangaroo pineapple lorem ipsum dolor sit amet"
            " consectetur adipiscing elit today wonderfully."
        ),
    ).validate()
    vec = semantic_vec(vector.embed_text(candidate), DIMS)

    def run_once():
        cfg = dedup.load_config()
        assert cfg.coverage_low is None and cfg.coverage_high is None  # truly unconfigured
        corpus = dedup.build_corpus(kb.kb, cfg)
        corpus.embed_model, corpus.embed_digest = MODEL, DIGEST
        try:
            return dedup.detect(corpus, candidate, vec)
        finally:
            corpus.close()

    report_default_fallback = run_once()
    monkeypatch.setattr(dedup, "_RELATION_LABEL_FALLBACK_HIGH", 0.01)
    report_flipped_fallback = run_once()

    assert report_default_fallback["verdict"] == "confident-duplicate"
    assert report_flipped_fallback["verdict"] == "confident-duplicate"
    for report in (report_default_fallback, report_flipped_fallback):
        assert report["hits"][0]["label_basis"] == "fallback"


def test_ruling_b_semantic_flag_with_unrelated_winning_hit_recommends_generic_review(
    mem, kb, semantic_ollama,
):
    """Orchestrator Ruling B (finding 10), ratified: when a candidate is
    flagged by a semantic signal and the best hit's `relation` is
    `unrelated` (no coverage corroboration), the top-level
    `recommended_action` must be the generic "review", never an inherited
    "add" - `unrelated`'s own per-hit action. "rehearsal"/"repetition" are
    the same fake-embedding synonym class (cosine flags it) but lexically
    distinct tokens (zero real claim overlap), so coverage genuinely sees
    nothing on this hit - not a contrived cc/cd, a real disjoint pair."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Repetition study card", "Repetition of study material strengthens memory over time.")

    candidate = {
        "title": "Rehearsal candidate",
        "body": (
            "Rehearsal cycles are covered here only in passing. "
            "This is an otherwise entirely unrelated discussion about zebra kangaroo pineapple"
            " lorem ipsum wonderful fantastic elephant giraffe topics that share nothing else"
            " with the card's real content whatsoever."
        ),
    }
    r, payload = dedup_json(mem, env, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr
    entry = payload["candidates"][0]
    hit = entry["hits"][0]
    assert hit["relation"] == "unrelated"
    assert entry["decisions"]["cosine_document_max"]["crossed"] is True  # semantic flag fired
    assert entry["flagged"] is True
    assert entry["verdict"] != "novel"
    assert entry["recommended_action"] == "review"  # never the inherited "add"


def test_gate3_top_k_doc_refuses_a_precomputed_vector_from_a_different_model(tmp_path):
    """Gate finding 3 reproduction: an index stamped under one model must
    refuse a document-cosine scan against a vector identified as coming
    from a different model, even at matching dims - the pre-fix dims-only
    check let two incomparable embedding spaces through silently."""
    from array import array

    con = vector.connect(tmp_path)
    try:
        con.execute(
            "INSERT INTO vectors(slug, model, dims, content_hash, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("card-a", "old-model", 2, "sha256:x", array("f", [1.0, 0.0]).tobytes(), "2026-01-01T00:00:00Z"),
        )
        for key, value in (("model", "old-model"), ("dims", "2"), ("digest", "sha256:olddigest")):
            con.execute("INSERT OR REPLACE INTO vector_meta(key, value) VALUES(?, ?)", (key, value))
        con.commit()
    finally:
        con.close()

    with pytest.raises(vector.VectorError):
        vector.top_k_doc(tmp_path, vec=[1.0, 0.0], k=None, model="new-model")

    # same model, same dims: the identity check passes, the scan proceeds
    result = vector.top_k_doc(tmp_path, vec=[1.0, 0.0], k=None, model="old-model")
    assert result == [("card-a", pytest.approx(1.0))]


def test_gate3_chunk_currency_invalidates_on_model_swap_not_just_content_hash(tmp_path):
    """Gate finding 3's chunk-side claim: chunk currency checked only
    `content_hash`, so a model swap left old, numerically-incomparable
    chunk vectors looking "current" because their bytes were unchanged."""
    concept = okf.Concept(
        slug="short-card", title="Short card", description="d", type="concept",
        topics=["x"], sensitivity="normal", created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z", related=[], body="A short body with no headings.",
    )
    con = chunks.connect(tmp_path)
    try:
        built = chunks.build_chunks(concept)
        chunks._store(con, concept.slug, built, [[1.0, 0.0] for _ in built], "old-model", "sha256:olddigest")
        assert chunks.is_current(con, concept, "old-model", "sha256:olddigest") is True
        assert chunks.is_current(con, concept, "new-model", "sha256:olddigest") is False
        assert chunks.is_current(con, concept, "old-model", "sha256:newdigest") is False
    finally:
        con.close()


def test_gate3_chunk_scan_excludes_rows_stamped_under_a_different_model(tmp_path):
    """The read-side half of gate finding 3: a chunk scan filtered only by
    `dims` could return a same-dimension row embedded under a different
    (numerically incomparable) model. `best_per_card`'s model/digest filter
    must exclude it rather than score it."""
    from array import array

    con = chunks.connect(tmp_path)
    try:
        con.execute(
            "INSERT INTO chunks(slug, ordinal, char_start, char_end, content_hash, model, digest, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("stale-card", 0, 0, 10, "sha256:x", "old-model", "sha256:olddigest",
             array("f", [1.0, 0.0]).tobytes(), "2026-01-01T00:00:00Z"),
        )
        con.execute(
            "INSERT INTO chunks(slug, ordinal, char_start, char_end, content_hash, model, digest, vec, updated)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("fresh-card", 0, 0, 10, "sha256:y", "new-model", "sha256:newdigest",
             array("f", [1.0, 0.0]).tobytes(), "2026-01-01T00:00:00Z"),
        )
        con.commit()
        best = chunks.best_per_card(con, [1.0, 0.0], model="new-model", digest="sha256:newdigest")
    finally:
        con.close()
    assert list(best) == ["fresh-card"]


def test_gate4_five_thousand_char_title_line_stays_under_the_atomic_limit(mem, kb, semantic_ollama):
    """Gate finding 4 reproduction, pinned exactly: a 5,000-char title
    produced a 5,000-char slug and a 5,521-byte line that the pre-fix code
    warned about and wrote anyway. Every variable field must now be
    elided/bounded so the final line (with its newline) stays under the
    4,096B atomic-append limit."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0

    long_title = "A" * 5000
    candidate = {"title": long_title, "body": "Docker reuses image layers for the cache today."}
    r, payload = dedup_json(mem, env, json.dumps([candidate]))
    assert r.returncode == 0, r.stdout + r.stderr

    raw_lines = (kb.kb / ".index" / "dedup-log.jsonl").read_bytes().split(b"\n")
    raw_lines = [ln for ln in raw_lines if ln]
    assert len(raw_lines) == 1
    assert len(raw_lines[0]) + 1 < deduplog.LINE_LIMIT  # +1 for the newline written after it

    records = read_log_lines(kb)
    assert len(records[0]["candidate"]["title"]) < 5000
    assert len(records[0]["candidate"]["slug_intended"]) < 5000


def test_gate4_run_id_over_the_bound_is_refused_not_silently_elided(mem, kb, semantic_ollama):
    """`run_id` is a literal (run_id, content_hash) JOIN KEY - eliding it
    would silently break a later `--adjudicate`'s exact-match lookup, so an
    absurdly long forced MEM_RUN_ID must be refused outright instead."""
    env = dict(semantic_env(semantic_ollama))
    assert mem("init", env_extra=env).returncode == 0
    env["MEM_RUN_ID"] = "R" * 1000
    r = mem("dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]), env_extra=env)
    assert r.returncode == 1
    assert r.stderr.strip().startswith("error:")
    assert read_log_lines(kb) == []


def test_gate5_legs_run_drops_chunk_leg_after_mid_run_daemon_failure(mem, kb, semantic_ollama, monkeypatch):
    """Gate finding 5 reproduction: the candidate/document leg succeeded,
    then the chunk leg's embed raised `OllamaError` mid-run - the note said
    the chunk leg was disabled, but `config.legs_run` still listed
    `vector_chunk`, letting a consumer mistake a degraded run for a full
    one."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Docker layer caching", "Docker reuses image layers for the cache.")

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HOME", str(kb.home))
    monkeypatch.setenv("MEM_DEDUP_CHUNKS", "1")

    from agent_memory import chunks as chunks_mod
    from agent_memory import ollama

    def _boom(*_args, **_kwargs):
        raise ollama.OllamaError("simulated daemon failure mid-run")

    monkeypatch.setattr(chunks_mod, "populate_one", _boom)

    cfg = dedup.load_config()
    corpus = dedup.build_corpus(kb.kb, cfg)
    assert "vector_chunk" in corpus.legs_run  # sanity: the leg was configured to run
    corpus.embed_model, corpus.embed_digest = MODEL, DIGEST
    candidate = okf.Concept(
        slug="another-docker-note", title="Another docker note", description="d", type="concept",
        topics=[], sensitivity="normal", created="2026-01-01T00:00:00Z",
        updated="2026-01-01T00:00:00Z", related=[], source="test",
        body="Docker reuses image layers for the cache too.",
    ).validate()
    vec = semantic_vec(vector.embed_text(candidate), DIMS)
    try:
        report = dedup.detect(corpus, candidate, vec)
    finally:
        legs_after_failure = list(corpus.legs_run)
        corpus.close()

    assert "vector_chunk" not in legs_after_failure
    assert any("vector_chunk leg disabled mid-run" in n for n in report["notes"])


def test_gate6_invalid_candidate_carries_empty_flag_reasons_list(mem, kb, semantic_ollama):
    """Gate finding 6 reproduction: `[{"body":"No title supplied here."}]`
    returned an invalid candidate with verdict/flagged/recommended_action
    but no `flag_reasons` - a shape-safe consumer needed a key-existence
    branch just for this case."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r, payload = dedup_json(mem, env, json.dumps([{"body": "No title supplied here."}]))
    assert r.returncode == 0, r.stdout + r.stderr
    invalid = payload["candidates"][0]
    assert invalid["verdict"] == "invalid"
    assert invalid["flag_reasons"] == []


def test_gate6_mixed_valid_and_invalid_batch_both_carry_flag_reasons(mem, kb, semantic_ollama):
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    save(mem, env, "Spaced repetition scheduling", "Reviews at increasing intervals beat cramming.")
    candidates = [
        {"body": "No title supplied here."},
        {"title": "Docker layer caching", "body": "Docker reuses image layers for the cache."},
    ]
    r, payload = dedup_json(mem, env, json.dumps(candidates))
    assert r.returncode == 0, r.stdout + r.stderr
    for c in payload["candidates"]:
        assert "flag_reasons" in c and isinstance(c["flag_reasons"], list)


def test_gate7_deep_k_zero_and_top_m_zero_refused_after_cli_override(mem, kb, semantic_ollama):
    """Gate finding 7 reproduction: `--deep-k 0 --top-m 0` replaced an
    already-validated config and reached corpus construction unvalidated,
    exiting 0. CLI overrides must be validated too."""
    env = semantic_env(semantic_ollama)
    assert mem("init", env_extra=env).returncode == 0
    r = mem(
        "dedup", json.dumps([{"title": "X", "body": "Docker reuses image layers."}]),
        "--deep-k", "0", "--top-m", "0", env_extra=env,
    )
    assert r.returncode == 1
    assert r.stderr.strip().startswith("error:")
    assert "deep-k" in r.stderr


def test_regate1_builder_refuses_at_the_exact_boundary(tmp_path):
    """Round-3 gate finding: the previous pin swept the TITLE, which the
    builder elides, so the encoded line never approached the limit and a
    reverted `<=` passed undetected. This pin drives the line to the exact
    boundary through `config` (embedded verbatim, never elided), with
    log_titles=False so the builder's final title-drop lever is a no-op:
    exactly-at-limit MUST refuse (strict `<`), one byte under MUST be
    accepted. A `<=` regression on either builder comparison returns the
    at-limit record and fails this test."""
    import pytest as _pytest

    def build_with(filler):
        report = {
            "title": "t", "slug_intended": "x",
            "content_hash": "sha256:" + "0" * 8, "claim_count": 1,
            "verdict": "novel", "flagged": False, "recommended_action": "add",
            "flag_reasons": [], "hits": [],
            "union": {"member_slugs": [], "coverage_curve": []},
        }
        return deduplog.build_detection_record(
            run_id="20260902T000000Z-regate", command="dedup",
            detector_version="1.0.0", embed_model="m", embed_digest="d",
            config={"deep_k": 50, "filler": filler},
            report=report, log_titles=False,
        )

    base_len = deduplog._encoded_line_len(build_with(""))
    pad = deduplog.LINE_LIMIT - base_len

    # One byte under the limit: accepted, and encodes to exactly LIMIT-1.
    under = build_with("f" * (pad - 1))
    assert deduplog._encoded_line_len(under) == deduplog.LINE_LIMIT - 1

    # Exactly at the limit: the strict `<` must refuse; nothing returned.
    with _pytest.raises(deduplog.DedupLogError):
        build_with("f" * pad)


def test_regate1_append_guard_refuses_exact_equality(tmp_path):
    """The raw append guard refuses a line that lands exactly on LINE_LIMIT
    (record + newline == limit) and writes nothing."""
    import pytest as _pytest

    root = tmp_path / "kb"
    (root / ".index").mkdir(parents=True)
    overhead = len((json.dumps({"p": ""}, ensure_ascii=False) + "\n").encode())
    exact_record = {"p": "x" * (deduplog.LINE_LIMIT - overhead)}
    assert deduplog._encoded_line_len(exact_record) == deduplog.LINE_LIMIT
    with _pytest.raises(deduplog.DedupLogError):
        deduplog._append_line(root, exact_record)
    assert not (root / ".index" / "dedup-log.jsonl").exists()
