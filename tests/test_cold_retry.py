"""Cold-model embed retry - the first search after an Ollama restart must
return real semantic results, and `mem doctor` must not flap FAIL on a
healthy-but-cold daemon.

The failure class (reported by expert-wrangler, 2026-07-29): the query-embed
timeout is shorter than a cold model load, the aborted request does not leave
the model loaded, so every search degrades until something else warms the
model. The fix is a health-check-gated retry: a timeout plus a fast
/api/version answer means "loading, not hung" - retry once on the cold budget,
holding the connection open so the load completes. A hung daemon fails the
version check and still costs ~one timeout (the original invariant).

ColdStartOllama models the real daemon's queue-behind-the-loading-runner
behavior: the first embed contact starts a load clock, every embed arriving
before it expires blocks until it does, then answers normally.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from test_f4_semantic import (  # noqa: F401  (fixture pulled in by import)
    DIGEST,
    DIMS,
    MODEL,
    semantic_ollama_factory,
    semantic_vec,
)

QUERY = "vehicle repairs"
SLUG = "sedan-upkeep"


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # aborted-client BrokenPipes are the point of these tests


class ColdStartOllama:
    """Ollama double with a cold model: /api/version answers instantly, the
    first /api/embed contact starts `load_delay` seconds of loading, embeds
    arriving before the load completes block until it does."""

    def __init__(self, dims: int = DIMS, model: str = MODEL, load_delay: float = 1.0):
        srv = self
        self.dims = dims
        self.model = model
        self.load_delay = load_delay
        self.embed_requests = 0
        self.warm_at: float | None = None
        self._lock = threading.Lock()

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
                now = time.monotonic()
                with srv._lock:
                    srv.embed_requests += 1
                    if srv.warm_at is None:
                        srv.warm_at = now + srv.load_delay
                    wait = srv.warm_at - now
                if wait > 0:
                    time.sleep(wait)
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

        self.server = _QuietServer(("127.0.0.1", 0), Handler)
        self.server.block_on_close = False
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def cold_ollama_factory():
    servers = []

    def make(**kwargs) -> ColdStartOllama:
        server = ColdStartOllama(**kwargs)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


def seed_semantic_fixture(mem, url: str) -> None:
    """One paraphrase target embedded while a warm daemon is up, so the search
    under test exercises only the query-embed path."""
    env = {"MEM_OLLAMA_URL": url}
    assert mem("init", env_extra=env).returncode == 0
    result = mem(
        "save", "--title", "Sedan upkeep", "--body",
        "Regular servicing keeps an automobile dependable for years.",
        env_extra=env,
    )
    assert result.returncode == 0, result.stderr


def test_cold_model_search_retries_and_recovers_semantics(
    mem, kb, semantic_ollama_factory, cold_ollama_factory
):
    warm = semantic_ollama_factory()
    seed_semantic_fixture(mem, warm.url)

    cold = cold_ollama_factory(load_delay=1.0)
    result = mem(
        "search", QUERY, "--json",
        env_extra={
            "MEM_OLLAMA_URL": cold.url,
            "MEM_EMBED_QUERY_TIMEOUT": "0.25",  # < load_delay: first attempt aborts
            "MEM_EMBED_COLD_TIMEOUT": "15",
        },
    )
    assert result.returncode == 0, result.stderr

    # The retry path actually ran: first request aborted, second answered.
    assert cold.embed_requests >= 2, result.stderr
    assert "model loading" in result.stderr
    # NOT degraded - and the degraded marker consumers string-match is absent.
    assert "semantic leg skipped" not in result.stderr

    hits = json.loads(result.stdout)
    assert hits and hits[0]["slug"] == SLUG, hits
    assert hits[0]["semantic_similarity"] > 0.5


def test_hung_daemon_still_degrades_fast_with_verbatim_marker(
    mem, kb, semantic_ollama_factory
):
    warm = semantic_ollama_factory()
    seed_semantic_fixture(mem, warm.url)

    hung = semantic_ollama_factory(stall=True)
    start = time.monotonic()
    result = mem(
        "search", QUERY, "--json",
        env_extra={
            "MEM_OLLAMA_URL": hung.url,
            "MEM_EMBED_QUERY_TIMEOUT": "0.25",
            "MEM_EMBED_COLD_TIMEOUT": "30",  # must NOT be spent on a hung daemon
        },
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    warnings = [
        line for line in result.stderr.splitlines() if line.startswith("warning:")
    ]
    assert len(warnings) == 1, result.stderr
    # expert-wrangler string-matches this marker to classify degraded results.
    assert warnings[0].startswith("warning: semantic leg skipped"), result.stderr
    assert elapsed < 5.0, f"hung daemon cost {elapsed:.1f}s - cold budget leaked into the hung path"
    assert json.loads(result.stdout) is not None  # valid JSON, lexical+graph answered


def test_doctor_embed_check_survives_cold_model(mem, kb, cold_ollama_factory):
    assert mem("init").returncode == 0

    cold = cold_ollama_factory(load_delay=1.0)
    result = mem(
        "doctor",
        env_extra={"MEM_OLLAMA_URL": cold.url, "MEM_EMBED_COLD_TIMEOUT": "15"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert any(
        line.startswith("ok") and "embed-model" in line and str(DIMS) in line
        for line in lines
    ), result.stdout


def test_doctor_embed_probe_rides_the_cold_budget(mem, kb, cold_ollama_factory):
    """Negative control pinning the probe to MEM_EMBED_COLD_TIMEOUT: a load
    slower than the cold budget is a real failure and must still FAIL - which
    also proves the probe follows the knob rather than a hardcoded budget."""
    assert mem("init").returncode == 0

    cold = cold_ollama_factory(load_delay=1.5)
    result = mem(
        "doctor",
        env_extra={"MEM_OLLAMA_URL": cold.url, "MEM_EMBED_COLD_TIMEOUT": "0.3"},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert any(
        line.startswith("FAIL") and "embed-model" in line and "timed out" in line
        for line in result.stdout.splitlines()
    ), result.stdout
