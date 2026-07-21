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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

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


class FusionOllama:
    """Localhost Ollama double: /api/version, /api/tags, /api/embed with the
    zero-fallback semantic embedding above."""

    def __init__(self, dims: int = DIMS, model: str = MODEL):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send(200, {"version": "0.0.0-fake"})
                elif self.path == "/api/tags":
                    self._send(
                        200,
                        {"models": [{"name": srv.model, "model": srv.model, "digest": DIGEST}]},
                    )
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if self.path != "/api/embed":
                    self._send(404, {"error": "not found"})
                    return
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                if body.get("model") != srv.model:
                    self._send(404, {"error": f"model '{body.get('model')}' not found"})
                    return
                texts = body.get("input")
                if isinstance(texts, str):
                    texts = [texts]
                self._send(
                    200,
                    {
                        "model": srv.model,
                        "embeddings": [semantic_vec(t, srv.dims) for t in texts or []],
                    },
                )

        self.dims = dims
        self.model = model
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


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
        assert set(hit) == {"slug", "title", "score", "snippet"}
        assert isinstance(hit["score"], float) and hit["score"] > 0
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)

    text = mem("search", "gadget")
    assert text.returncode == 0
    assert len(text.stdout.splitlines()) <= 24  # one screen by default
