"""F6 - fused search: single-leg fixtures surface in fused results;
sensitivity marking honored.

One `mem search` fuses lexical (FTS5 BM25), semantic (local embeddings), and
graph (1-hop expansion from the lexical∪vector seeds) evidence via RRF. All KB
writes go through `mem` subprocesses against an isolated HOME; daemon states
ride the MEM_OLLAMA_URL seam. The fake embedder is deterministic and semantic
(synonym-class dimensions, the capstone D020 pattern) with one sharpening for
F6: text containing no known class words embeds to the ZERO vector, so a
purely literal term carries no semantic evidence at all - which is exactly
what makes a lexical-only fixture constructible.

Single-leg fixtures:
- lexical-only: `zorbofrob-protocol` - query terms literal-match it, but both
  query and concept embed to zero (no semantic evidence, no links/topics).
- semantic-only: `sedan-upkeep` - shares zero literal terms with the query
  "vehicle repairs" (machine-asserted) yet lands in the same synonym classes.
- graph-only: `brake-fluid-swap-steps` - shares no query terms, embeds to
  zero, but wikilinks to `family-wagon-logbook`, which the query hits
  lexically (the seed-neighbor construction from FEATURES).
"""

import json
import re

import pytest

from fakes import FakeOllamaServer

from agent_memory import config, lexical, vector

DIMS = 64
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:f6f6f6f6"

SYNONYM_CLASSES = [
    {"car", "automobile", "sedan", "vehicle", "motor"},
    {"maintenance", "upkeep", "servicing", "repairs"},
    {"dog", "canine", "puppy", "hound"},
    {"training", "obedience", "commands", "heel"},
    {"bread", "sourdough", "loaf", "crumb"},
    {"fermentation", "levain", "proofing", "starter"},
]


def words_of(text: str) -> set:
    return set(re.findall(r"[a-z]+", text.lower()))


def semantic_vec(text: str, dims: int) -> list:
    """Bag-of-synonym-classes; unknown-words-only text is the zero vector."""
    vec = [0.0] * dims
    for i, cls in enumerate(SYNONYM_CLASSES):
        if words_of(text) & cls:
            vec[i] = 1.0
    return vec


def FusionOllama(dims: int = DIMS, model: str = MODEL) -> FakeOllamaServer:
    """Zero-fallback semantic double (unknown words embed to the zero
    vector - what makes a lexical-only fixture constructible)."""
    return FakeOllamaServer(dims=dims, model=model, embed_fn=semantic_vec, digest=DIGEST)


@pytest.fixture
def fusion_ollama():
    server = FusionOllama()
    yield server
    server.stop()


SEDAN = "sedan-upkeep"
ZORBO = "zorbofrob-protocol"
WAGON = "family-wagon-logbook"       # graph seed: the query hits it lexically
BRAKE = "brake-fluid-swap-steps"     # graph-only: surfaces via its link to WAGON

CORPUS = [
    ("Sedan upkeep", "Regular servicing keeps an automobile dependable for years.", []),
    ("Puppy obedience", "A young canine learns commands like heel through routine.", []),
    ("Sourdough starter", "Levain proofing determines the crumb of the loaf.", []),
    ("Zorbofrob protocol", "The zorbofrob widget flarps during calibration.", []),
    ("Family wagon logbook", "Regular servicing schedule for the family wagon.", []),
    ("Brake fluid swap steps", "Bleed lines every spring. See [[family-wagon-logbook]].", []),
    ("Acme pipeline secrets", "The acme pipeline rotates signing keys quarterly.",
     ["--sensitivity", "work"]),
    ("Pipeline hygiene notes", "General pipeline hygiene: version everything.", []),
]


def seed(mem, env) -> None:
    assert mem("init", env_extra=env).returncode == 0
    for title, body, extra in CORPUS:
        result = mem("save", "--title", title, "--body", body, *extra, env_extra=env)
        assert result.returncode == 0, result.stderr


def search_json(mem, *args, env_extra=None):
    result = mem("search", *args, "--json", env_extra=env_extra)
    assert result.returncode == 0, result.stderr
    return result, json.loads(result.stdout)


def use_kb_env(monkeypatch, kb, url):
    monkeypatch.setenv("HOME", str(kb.home))
    monkeypatch.setenv("MEM_OLLAMA_URL", url)


def test_lexical_only_concept_surfaces_in_fused_topk(mem, kb, monkeypatch, fusion_ollama):
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)

    # No semantic evidence exists for this query: it embeds to zero, so the
    # vector leg returns nothing at all - only the lexical leg can know.
    use_kb_env(monkeypatch, kb, fusion_ollama.url)
    assert vector.top_k(config.kb_root(), "zorbofrob calibration", k=10) == []

    result, hits = search_json(mem, "zorbofrob calibration", env_extra=env)
    assert hits and hits[0]["slug"] == ZORBO, hits
    assert result.stderr.strip() == ""


def test_semantic_only_concept_surfaces_in_fused_topk(mem, kb, fusion_ollama):
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)
    query = "vehicle repairs"

    # The fixture's defining property: zero shared terms with the stored file.
    stored = (kb.kb / "concepts" / f"{SEDAN}.md").read_text(encoding="utf-8")
    assert words_of(query).isdisjoint(words_of(stored))

    # Without the vector leg (daemon down) the concept is unreachable...
    result = mem("search", query, "--json")  # kb default env: closed port
    assert result.returncode == 0
    assert SEDAN not in [hit["slug"] for hit in json.loads(result.stdout)]

    # ...with it, fused search puts it on top.
    _, hits = search_json(mem, query, env_extra=env)
    assert hits and hits[0]["slug"] == SEDAN, hits


def test_graph_only_neighbor_surfaces_via_one_hop(mem, kb, monkeypatch, fusion_ollama):
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)
    query = "servicing schedule"

    # BRAKE shares no terms with the query and carries no semantic evidence:
    # neither the lexical nor the vector leg can reach it on its own.
    use_kb_env(monkeypatch, kb, fusion_ollama.url)
    conn = lexical.connect(config.kb_root())
    try:
        lexical.sync(conn, config.kb_root())
        lex_slugs = [hit["slug"] for hit in lexical.search(conn, query, 10)]
    finally:
        conn.close()
    assert WAGON in lex_slugs and BRAKE not in lex_slugs
    assert not any(
        slug == BRAKE and score > 0.0
        for slug, score in vector.top_k(config.kb_root(), query, k=10)
    )

    _, hits = search_json(mem, query, env_extra=env)
    slugs = [hit["slug"] for hit in hits]
    assert slugs[0] == WAGON
    assert BRAKE in slugs[:3], slugs  # 1-hop expansion from the lexical seed


def test_work_items_marked_and_no_work_excludes(mem, kb, fusion_ollama):
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)

    _, hits = search_json(mem, "pipeline", env_extra=env)
    by_slug = {hit["slug"]: hit for hit in hits}
    assert by_slug["acme-pipeline-secrets"]["sensitivity"] == "work"
    assert "sensitivity" not in by_slug["pipeline-hygiene-notes"]

    text = mem("search", "pipeline", env_extra=env)
    assert text.returncode == 0
    lines = text.stdout.splitlines()
    assert any(line.startswith("acme-pipeline-secrets") and "[work]" in line for line in lines)
    assert not any("pipeline-hygiene-notes" in line and "[work]" in line for line in lines)

    _, filtered = search_json(mem, "pipeline", "--no-work", env_extra=env)
    slugs = [hit["slug"] for hit in filtered]
    assert "acme-pipeline-secrets" not in slugs
    assert "pipeline-hygiene-notes" in slugs


def test_semantic_similarity_carried_per_hit(mem, kb, fusion_ollama):
    """Raw cosine rides --json on hits the vector leg scored (RRF encodes rank
    agreement, not magnitude - downstream connect/new thresholding needs the
    leg's own score). Absent on graph-only hits, on zero-evidence queries, and
    on degraded searches - absence is itself signal."""
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)

    _, hits = search_json(mem, "servicing schedule", env_extra=env)
    by_slug = {hit["slug"]: hit for hit in hits}
    # WAGON: lexical + semantic ("servicing" shares a synonym class) - exact
    # class match, cosine 1.0. SEDAN: semantic evidence only, partial overlap.
    assert by_slug[WAGON]["semantic_similarity"] == pytest.approx(1.0, abs=1e-3)
    assert 0.0 < by_slug[SEDAN]["semantic_similarity"] < 1.0
    # BRAKE surfaced by the graph leg alone: no cosine to report.
    assert "semantic_similarity" not in by_slug[BRAKE]

    # Zero-evidence query: embeds to zero, vector leg empty, field nowhere.
    _, zero_hits = search_json(mem, "zorbofrob calibration", env_extra=env)
    assert all("semantic_similarity" not in hit for hit in zero_hits)

    # Degraded search (daemon down): field nowhere, list still valid.
    result = mem("search", "servicing schedule", "--json")  # closed port
    assert result.returncode == 0
    assert all(
        "semantic_similarity" not in hit for hit in json.loads(result.stdout)
    )


def test_daemon_down_degrades_to_lexical_plus_graph_one_warning(mem, kb, fusion_ollama):
    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)  # vectors + metadata stamped while the daemon is up

    result = mem("search", "servicing schedule", "--json")  # closed port now
    assert result.returncode == 0, result.stderr
    warnings = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(warnings) == 1, result.stderr
    assert warnings[0].startswith("warning:")

    slugs = [hit["slug"] for hit in json.loads(result.stdout)]
    assert WAGON in slugs   # lexical still answers
    assert BRAKE in slugs   # graph still answers


def test_hits_keep_contract_one_screen_by_default(mem, kb):
    assert mem("init").returncode == 0  # daemon down throughout: also proves
    for i in range(12):                 # fusion never needs Ollama to exist
        result = mem(
            "save", "--title", f"Gadget note {i}",
            "--body", f"Gadget usage pattern number {i}.",
        )
        assert result.returncode == 0, result.stderr

    _, hits = search_json(mem, "gadget")
    assert len(hits) == 10  # default --limit caps the list at one screen
    for hit in hits:
        assert set(hit) == {"slug", "title", "type", "score", "snippet"}  # type added D10
        assert isinstance(hit["score"], float) and hit["score"] > 0
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)

    text = mem("search", "gadget")
    assert text.returncode == 0
    assert len(text.stdout.splitlines()) <= 24  # one screen by default


def test_filters_widen_leg_pool_instead_of_starving_results(mem, kb):
    """The 2026-08-05 quality-review recall cliff: with a filter active, the
    top of every leg can be entirely filtered types while a real match sits
    below the default pool depth. The pool must widen so filtering selects
    from a deeper field."""
    assert mem("init").returncode == 0  # daemon down: lexical leg only
    for i in range(12):  # strong, work-tagged matches fill the default pool
        result = mem(
            "save", "--title", f"Gadget internals {i}",
            "--body", f"Gadget gadget gadget deep dive number {i}.",
            "--sensitivity", "work",
        )
        assert result.returncode == 0, result.stderr
    result = mem(
        "save", "--title", "Public teardown notes",
        "--body", "One public gadget reference among many internal ones.",
    )
    assert result.returncode == 0, result.stderr

    result = mem("search", "gadget", "--no-work", "--json")
    assert result.returncode == 0, result.stderr
    slugs = [hit["slug"] for hit in json.loads(result.stdout)]
    assert "public-teardown-notes" in slugs, slugs


def test_corrupt_vector_store_degrades_search_not_breaks(mem, kb, monkeypatch, fusion_ollama):
    """A corrupt derived index is recoverable state (mem reindex) and must
    degrade the semantic leg with the standard marker, never traceback."""
    import io
    import sqlite3 as _sqlite3
    from contextlib import redirect_stderr, redirect_stdout
    from types import SimpleNamespace

    from agent_memory import search as search_mod
    from agent_memory import vector

    env = {"MEM_OLLAMA_URL": fusion_ollama.url}
    seed(mem, env)
    use_kb_env(monkeypatch, kb, fusion_ollama.url)

    def corrupt_top_k(*a, **kw):
        raise _sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(vector, "top_k", corrupt_top_k)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = search_mod.cmd_search(SimpleNamespace(
            query="servicing schedule", limit=10, json=True, no_work=False, type=None,
        ))
    assert rc == 0
    warnings = [l for l in err.getvalue().splitlines() if l.startswith("warning:")]
    assert len(warnings) == 1, err.getvalue()
    assert warnings[0].startswith("warning: semantic leg skipped")
    assert "mem reindex" in warnings[0]
    assert json.loads(out.getvalue()), "lexical+graph still answer"
