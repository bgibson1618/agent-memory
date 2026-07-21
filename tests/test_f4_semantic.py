"""F4 - semantic recall: a paraphrase fixture recovered via the vector leg;
bounded-drain, full-drain, and strict-timeout semantics machine-asserted.

All KB writes go through `mem` subprocesses against an isolated HOME; daemon
states (up / down / hung / wrong-dims) are simulated on localhost through the
MEM_OLLAMA_URL seam. The fake embedder is deterministic and *semantic*: words
map onto synonym-class dimensions, so paraphrases land near each other while
sharing zero literal terms - the capstone D020 pattern. The vector-leg query
is asserted through the library API (vector.top_k) under the same isolated
environment; `mem search` fusion is F6's surface.
"""

import json
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_memory import config, vector

DIMS = 768
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:f4f4f4f4"

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
    vec = [0.0] * dims
    for i, cls in enumerate(SYNONYM_CLASSES):
        if words_of(text) & cls:
            vec[i] = 1.0
    if not any(vec):
        vec[len(SYNONYM_CLASSES)] = 1.0  # orthogonal "no known meaning" direction
    return vec


class SemanticOllama:
    """Localhost Ollama double whose embeddings are deterministic and
    meaning-shaped; optionally hung (accepts connections, never answers)."""

    def __init__(self, dims: int = DIMS, model: str = MODEL, stall: bool = False):
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
                if srv.stall:
                    time.sleep(5)
                    return
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
                if srv.stall:
                    time.sleep(5)
                    return
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
        self.stall = stall
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.block_on_close = False  # stalled handler threads must not hang teardown
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def semantic_ollama_factory():
    servers = []

    def make(**kwargs) -> SemanticOllama:
        server = SemanticOllama(**kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


def db_file(kb):
    return kb.kb / ".index" / "mem.db"


def _rows(kb, sql):
    if not db_file(kb).exists():
        return []
    con = sqlite3.connect(db_file(kb))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def queue_slugs(kb) -> set:
    return {row[0] for row in _rows(kb, "SELECT slug FROM embed_queue")}


def vector_slugs(kb) -> set:
    return {row[0] for row in _rows(kb, "SELECT slug FROM vectors")}


def index_meta(kb) -> dict:
    return dict(_rows(kb, "SELECT key, value FROM vector_meta"))


def use_kb_env(monkeypatch, kb, url):
    """Point in-process library calls at the isolated KB + fake daemon."""
    monkeypatch.setenv("HOME", str(kb.home))
    monkeypatch.setenv("MEM_OLLAMA_URL", url)


def save_target(mem, env):
    """The paraphrase fixture: stored text shares no literal terms with the
    query 'vehicle repairs' but lands in the same synonym classes."""
    result = mem(
        "save", "--title", "Sedan upkeep", "--body",
        "Regular servicing keeps an automobile dependable for years.",
        env_extra=env,
    )
    assert result.returncode == 0, result.stderr
    return "sedan-upkeep"


DISTRACTORS = [
    ("Puppy obedience", "A young canine learns commands like heel through routine."),
    ("Sourdough starter", "Levain proofing determines the crumb of the loaf."),
]

QUERY = "vehicle repairs"


def test_paraphrase_query_recovers_concept(mem, kb, monkeypatch, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    slug = save_target(mem, env)
    for title, body in DISTRACTORS:
        assert mem("save", "--title", title, "--body", body, env_extra=env).returncode == 0

    # Saves embedded inline (daemon up): nothing queued, all vectors present.
    assert queue_slugs(kb) == set()
    assert vector_slugs(kb) == {slug, "puppy-obedience", "sourdough-starter"}

    # The fixture's defining property, machine-asserted: zero shared terms
    # between the query and the stored concept file (frontmatter included).
    stored = (kb.kb / "concepts" / f"{slug}.md").read_text(encoding="utf-8")
    assert words_of(QUERY).isdisjoint(words_of(stored))

    use_kb_env(monkeypatch, kb, daemon.url)
    hits = vector.top_k(config.kb_root(), QUERY, k=2)
    assert hits and hits[0][0] == slug, hits
    assert hits[0][1] > 0.5  # cosine, same two synonym classes


def test_save_with_daemon_down_is_fast_and_queues(mem, kb):
    assert mem("init").returncode == 0  # default env: closed port = daemon down

    start = time.monotonic()
    result = mem("save", "--title", "Sedan upkeep", "--body", "Regular servicing matters.")
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    assert elapsed < 1.0, f"save took {elapsed:.2f}s with the daemon down"
    assert queue_slugs(kb) == {"sedan-upkeep"}
    assert vector_slugs(kb) == set()


def test_hung_daemon_never_stalls_save(mem, kb, semantic_ollama_factory):
    hung = semantic_ollama_factory(stall=True)
    assert mem("init").returncode == 0  # init offline; only the save meets the hang

    start = time.monotonic()
    result = mem(
        "save", "--title", "Sedan upkeep", "--body", "Regular servicing matters.",
        env_extra={"MEM_OLLAMA_URL": hung.url},
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    assert elapsed < 2.0, f"save took {elapsed:.2f}s against a hung daemon"
    assert queue_slugs(kb) == {"sedan-upkeep"}
    assert vector_slugs(kb) == set()


def test_bounded_then_full_drain_no_manual_reindex(
    mem, kb, monkeypatch, semantic_ollama_factory
):
    assert mem("init").returncode == 0
    slug = save_target(mem, kb.env)  # daemon down: queued
    extra = [f"filler-note-{i}" for i in range(4)]
    for name in extra:
        assert mem("save", "--title", name, "--body", f"plain text {name}").returncode == 0
    assert queue_slugs(kb) == {slug, *extra}

    # Daemon still down: an ordinary invocation must not drain or error.
    assert mem("list").returncode == 0
    assert queue_slugs(kb) == {slug, *extra}

    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}

    # Bounded drain: ~3 items per ordinary invocation, no manual reindex.
    assert mem("list", env_extra=env).returncode == 0
    assert len(queue_slugs(kb)) == 2
    assert mem("list", env_extra=env).returncode == 0
    assert queue_slugs(kb) == set()
    assert vector_slugs(kb) == {slug, *extra}

    # And the drained concept is now semantically findable.
    use_kb_env(monkeypatch, kb, daemon.url)
    hits = vector.top_k(config.kb_root(), QUERY, k=3)
    assert hits and hits[0][0] == slug, hits


def test_doctor_drains_queue_fully(mem, kb, semantic_ollama_factory):
    assert mem("init").returncode == 0
    for i in range(5):
        assert mem("save", "--title", f"note {i}", "--body", f"text {i}").returncode == 0
    assert len(queue_slugs(kb)) == 5

    daemon = semantic_ollama_factory()
    result = mem("doctor", env_extra={"MEM_OLLAMA_URL": daemon.url})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "embed-queue" in result.stdout
    assert "drained 5" in result.stdout
    assert queue_slugs(kb) == set()
    assert len(vector_slugs(kb)) == 5


def test_reindex_rebuilds_and_drains_fully(mem, kb, monkeypatch, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    slug = save_target(mem, env)
    for title, body in DISTRACTORS:
        assert mem("save", "--title", title, "--body", body, env_extra=env).returncode == 0

    db_file(kb).unlink()  # the whole derived index is disposable

    result = mem("reindex", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3" in result.stdout
    assert queue_slugs(kb) == set()
    assert len(vector_slugs(kb)) == 3

    use_kb_env(monkeypatch, kb, daemon.url)
    assert vector.top_k(config.kb_root(), QUERY, k=1)[0][0] == slug


def test_reindex_with_daemon_down_queues_and_exits_zero(mem, kb):
    assert mem("init").returncode == 0
    for i in range(3):
        assert mem("save", "--title", f"note {i}", "--body", f"text {i}").returncode == 0

    result = mem("reindex")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 queued" in result.stderr
    assert len(queue_slugs(kb)) == 3


def test_meta_stamped_and_mismatched_dims_refused(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem("save", "--title", "first note", "--body", "plain text one", env_extra=env).returncode == 0

    meta = index_meta(kb)
    assert meta == {"model": MODEL, "digest": DIGEST, "dims": "768"}

    # Same model tag suddenly embedding at 512 dims: the write is refused with
    # one line, the save still lands, and the item stays queued - not lost.
    shrunk = semantic_ollama_factory(dims=512)
    result = mem(
        "save", "--title", "second note", "--body", "plain text two",
        env_extra={"MEM_OLLAMA_URL": shrunk.url},
    )
    assert result.returncode == 0, result.stderr
    err_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(err_lines) == 1, result.stderr
    assert err_lines[0].startswith("error:") and "512" in err_lines[0] and "768" in err_lines[0]
    assert "second-note" in queue_slugs(kb)
    assert "second-note" not in vector_slugs(kb)
    assert index_meta(kb) == meta  # stamp unchanged by the refused write


def test_changed_model_tag_refused_until_reindex(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem("save", "--title", "first note", "--body", "plain text one", env_extra=env).returncode == 0

    other = semantic_ollama_factory(model="other-embedder:v9")
    other_env = {"MEM_OLLAMA_URL": other.url, "MEM_EMBED_MODEL": "other-embedder:v9"}
    result = mem("save", "--title", "second note", "--body", "plain text two", env_extra=other_env)
    assert result.returncode == 0, result.stderr
    assert "mem reindex" in result.stderr
    assert "second-note" in queue_slugs(kb)

    # reindex re-stamps to the current model and rebuilds everything.
    assert mem("reindex", env_extra=other_env).returncode == 0
    assert index_meta(kb)["model"] == "other-embedder:v9"
    assert queue_slugs(kb) == set()
    assert len(vector_slugs(kb)) == 2
