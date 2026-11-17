"""Shared fixtures: isolated KB HOME + fake Ollama endpoints (MEM_OLLAMA_URL seam).

Tests never touch the real service or the real KB: every `mem` invocation runs
in a subprocess with a scratch HOME, and Ollama states (up / down / wrong-model /
wrong-dims) are simulated on localhost.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from fakes import DEFAULT_MODEL, FakeOllamaServer


# Proof-policy flags are not instance configuration: they decide whether a
# skipped proof is a failure, and the suite must see them (the 2026-09-14
# MEMORY-A1 finding: stripping them let the namespace proof skip silently
# under the very flag documented to forbid that).
PROOF_POLICY_FLAGS = ("MEM_REQUIRE_NETNS",)


def ambient_mem_keys(environ) -> list:
    """The MEM_* variables the hermetic fixture strips: every instance
    setting, never a proof-policy flag."""
    return [k for k in environ if k.startswith("MEM_") and k not in PROOF_POLICY_FLAGS]


@pytest.fixture(autouse=True)
def _hermetic_mem_env(monkeypatch):
    """Sanity 2026-09-03 (drift re-check finding, reproduced 2-failed pre-fix): the suite was not hermetic
    against the invoking shell's `MEM_*` config - a per-instance deployment
    setting such as `MEM_DEDUP_LOW=0.83` (D15/D17's own supported mechanism)
    made two tests fail for anyone running the documented verification
    command from that shell. Subprocess `mem` calls were already hermetic
    (the `kb` fixture builds an explicit env); in-process `config.*()` reads
    were not. Strip every ambient `MEM_*` variable for the test process so a
    test sees only what it sets itself (via monkeypatch or the kb env)."""
    for key in ambient_mem_keys(os.environ):
        monkeypatch.delenv(key, raising=False)

class FakeOllama(FakeOllamaServer):
    """Minimal double (flat constant embeddings, no /api/tags) - the shared
    parameterized server in fakes.py; suites needing meaning-shaped embeddings
    pass their own embed_fn there."""


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
