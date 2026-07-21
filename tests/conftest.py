"""Shared fixtures: isolated KB HOME + fake Ollama endpoints (MEM_OLLAMA_URL seam).

Tests never touch the real service or the real KB: every `mem` invocation runs
in a subprocess with a scratch HOME, and Ollama states (up / down / wrong-model /
wrong-dims) are simulated on localhost.
"""

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

DEFAULT_MODEL = "nomic-embed-text:v1.5"


class FakeOllama:
    """Minimal localhost Ollama double: /api/version + /api/embed."""

    def __init__(self, dims: int = 768, model: str = DEFAULT_MODEL):
        self.dims = dims
        self.model = model
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
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                if self.path != "/api/embed":
                    self._send(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    body = {}
                if body.get("model") != srv.model:
                    self._send(
                        404,
                        {"error": f"model '{body.get('model')}' not found, try pulling it first"},
                    )
                    return
                self._send(200, {"model": srv.model, "embeddings": [[0.1] * srv.dims]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_ollama_factory():
    servers = []

    def make(**kwargs) -> FakeOllama:
        server = FakeOllama(**kwargs)
        server.start()
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.stop()


@pytest.fixture
def fake_ollama(fake_ollama_factory) -> FakeOllama:
    return fake_ollama_factory()


@pytest.fixture
def closed_port_url() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return f"http://127.0.0.1:{port}"


class KBEnv:
    """An isolated HOME plus the environment dict `mem` subprocesses run with."""

    def __init__(self, home: Path, env: dict):
        self.home = home
        self.env = env

    @property
    def kb(self) -> Path:
        return self.home / ".agent-memory"

    @property
    def claude_md(self) -> Path:
        return self.home / ".claude" / "CLAUDE.md"

    @property
    def agents_md(self) -> Path:
        return self.home / ".agent-docs" / "AGENTS.md"


@pytest.fixture
def kb(tmp_path, closed_port_url) -> KBEnv:
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "MEM_OLLAMA_URL": closed_port_url,  # daemon "down" unless a test overrides
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONUTF8": "1",
    }
    return KBEnv(home=home, env=env)


@pytest.fixture
def mem(kb):
    def _run(*args, env_extra=None, input=None) -> subprocess.CompletedProcess:
        env = dict(kb.env)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-m", "agent_memory", *args],
            capture_output=True,
            text=True,
            env=env,
            input=input,
            timeout=60,
        )

    return _run
