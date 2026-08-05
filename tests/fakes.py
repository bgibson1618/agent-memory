"""Shared fake-Ollama HTTP double (importable WITHOUT pytest - the netns
driver uses it as a plain module). One parameterized server replaces the six
hand-rolled copies the 2026-08-05 quality review counted; each call site keeps
only its distinctive knob:

- `embed_fn(text, dims) -> vector` - meaning-shaped embeddings (each suite
  keeps its own SYNONYM_CLASSES vocabulary); default is a flat constant vector.
- `stall=True` - hung daemon: accepts connections, never answers.
- `load_delay=S` - cold model: first embed contact starts an S-second load
  clock; embeds arriving before it expires block until it does (like the real
  daemon queuing requests behind the loading runner). `embed_requests` counts.
- `digest="sha256:..."` - serve /api/tags with this digest (extract/doctor
  stamp it); omit to 404 the endpoint.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MODEL = "nomic-embed-text:v1.5"


def flat_embed(text: str, dims: int) -> list:
    return [0.1] * dims


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass  # aborted clients (deliberate timeouts) are a feature here


class FakeOllamaServer:
    """Localhost Ollama double: /api/version, /api/embed, optional /api/tags."""

    def __init__(self, dims: int = 768, model: str = DEFAULT_MODEL,
                 embed_fn=flat_embed, stall: bool = False,
                 load_delay: float | None = None, digest: str | None = None):
        srv = self
        self.dims = dims
        self.model = model
        self.embed_fn = embed_fn
        self.stall = stall
        self.load_delay = load_delay
        self.digest = digest
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
                if srv.stall:
                    time.sleep(5)
                    return  # hung: accepted, never answered
                if self.path == "/api/version":
                    self._send(200, {"version": "0.0.0-fake"})
                elif self.path == "/api/tags" and srv.digest is not None:
                    self._send(
                        200,
                        {"models": [{"name": srv.model, "model": srv.model, "digest": srv.digest}]},
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
                now = time.monotonic()
                with srv._lock:
                    srv.embed_requests += 1
                    if srv.load_delay is not None and srv.warm_at is None:
                        srv.warm_at = now + srv.load_delay
                    wait = (srv.warm_at - now) if srv.warm_at is not None else 0.0
                if wait > 0:
                    time.sleep(wait)  # cold model: block until "loaded"
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                if body.get("model") != srv.model:
                    self._send(
                        404,
                        {"error": f"model '{body.get('model')}' not found, try pulling it first"},
                    )
                    return
                texts = body.get("input")
                if isinstance(texts, str):
                    texts = [texts]
                self._send(
                    200,
                    {
                        "model": srv.model,
                        "embeddings": [srv.embed_fn(t, srv.dims) for t in texts or []],
                    },
                )

        self.server = _QuietServer(("127.0.0.1", 0), Handler)
        self.server.block_on_close = False  # stalled handlers must not hang teardown
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def start(self):
        return self  # already serving; kept for legacy call sites

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
