"""F12 - zero-egress guarantee: no memory operation, including its
subprocesses, can send content anywhere but localhost, and any regression
fails this suite.

Two layers, per the feature spec:

  inner (fast)   tests/egress_guard/sitecustomize.py rides PYTHONPATH into
                 every `mem` subprocess and audits each Python socket.connect:
                 non-loopback peers are refused before the syscall, and every
                 peer is recorded so we can assert the only one ever contacted
                 is the local Ollama endpoint. Audit hooks cannot see git's
                 sockets or libc-internal DNS - that is the outer layer's job.

  outer (truth)  tests/f12_netns_driver.py runs the full command surface
                 (init / doctor / save / search / get / list / extract /
                 reindex) inside `unshare -rn` - a network namespace holding
                 nothing but its own `lo` - so subprocess egress of any kind
                 is impossible at the kernel level, and each command must
                 succeed or degrade exactly as specced with no non-localhost
                 connectivity in existence.

If this machine cannot create user+network namespaces, the outer leg skips
with a loud reason (the inner layer still runs); set MEM_REQUIRE_NETNS=1 to
turn that skip into a hard failure when proving the feature.
"""

import functools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import f12_netns_driver as driver

TESTS_DIR = Path(__file__).resolve().parent
GUARD_DIR = TESTS_DIR / "egress_guard"
DRIVER = TESTS_DIR / "f12_netns_driver.py"


# --------------------------- inner layer -----------------------------------


def guarded_env(log: Path) -> dict:
    return {
        "PYTHONPATH": str(GUARD_DIR),
        "MEM_EGRESS_GUARD": "enforce",
        "MEM_EGRESS_LOG": str(log),
    }


def run_canary(script: str, log: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONUTF8": "1", **guarded_env(log)}
    return subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=60
    )


def test_inner_guard_blocks_nonloopback_connect(tmp_path):
    # 192.0.2.1 is TEST-NET-1: even without the guard nothing would answer,
    # but the assertion demands the guard's own message - proving the hook
    # loaded and refused *before* the syscall, not that the network was lucky.
    log = tmp_path / "connects.jsonl"
    result = run_canary(
        "import socket\n"
        "s = socket.socket(); s.settimeout(5)\n"
        "s.connect(('192.0.2.1', 9))\n",
        log,
    )
    assert result.returncode != 0
    assert "mem egress guard: blocked non-loopback connect" in result.stderr
    entries = driver.read_log(log)
    assert entries and entries[-1]["allowed"] is False
    assert entries[-1]["peer"]["host"] == "192.0.2.1"


def test_inner_guard_allows_loopback(tmp_path):
    log = tmp_path / "connects.jsonl"
    result = run_canary(
        "import socket\n"
        "srv = socket.socket(); srv.bind(('127.0.0.1', 0)); srv.listen(1)\n"
        "c = socket.socket(); c.settimeout(5)\n"
        "c.connect(srv.getsockname())\n"
        "print('loopback-ok')\n",
        log,
    )
    assert result.returncode == 0, result.stderr
    assert "loopback-ok" in result.stdout
    entries = driver.read_log(log)
    assert entries and all(e["allowed"] for e in entries)


def test_full_surface_inner_guard_only_ollama_peer(mem, tmp_path):
    """Every command of the surface, enforced guard armed, semantic fake up:
    all succeed, and the only recorded network peer is the Ollama endpoint."""
    fake = driver.SemanticOllama()
    try:
        log = tmp_path / "connects.jsonl"
        env = {
            "MEM_OLLAMA_URL": fake.url,
            "MEM_EMBED_DIMS": str(driver.DIMS),
            **guarded_env(log),
        }
        for args in (
            ("init",),
            ("doctor",),
            ("save", "--title", driver.SEED["title"], "--body", driver.SEED["body"]),
            ("search", "spaced repetition intervals", "--json"),
            ("get", driver.SEED_SLUG, "--json"),
            ("list",),
            ("extract", "--candidates", json.dumps([driver.NOVEL_DOCKER]), "--json"),
            ("reindex",),
        ):
            result = mem(*args, env_extra=env)
            assert result.returncode == 0, (args, result.stdout, result.stderr)

        entries = driver.read_log(log)
        assert len(entries) >= 3, "guard log empty - sitecustomize never loaded?"
        assert all(e["allowed"] for e in entries)
        assert driver.inet_peers(entries) == {("127.0.0.1", fake.port)}
    finally:
        fake.stop()


def test_nonloopback_ollama_url_refused_before_any_socket(mem, kb, tmp_path):
    """A stray MEM_OLLAMA_URL pointing off-box must be refused pre-socket:
    doctor diagnoses it, save still lands locally (embed queued), and the
    guard log shows zero connect attempts of any kind."""
    log = tmp_path / "connects.jsonl"
    env = {"MEM_OLLAMA_URL": "http://203.0.113.7:11434", **guarded_env(log)}

    result = mem("init", env_extra=env)
    assert result.returncode == 0, result.stderr  # init warns, never fails offline

    result = mem("doctor", env_extra=env)
    assert result.returncode == 1
    assert "refusing non-loopback Ollama URL" in result.stdout

    result = mem(
        "save", "--title", driver.SEED["title"], "--body", driver.SEED["body"], env_extra=env
    )
    assert result.returncode == 0, result.stderr
    assert (kb.kb / "concepts" / f"{driver.SEED_SLUG}.md").is_file()

    assert driver.inet_peers(driver.read_log(log)) == set()


# --------------------------- outer layer -----------------------------------


@functools.lru_cache(maxsize=1)
def netns_unavailable_reason() -> str:
    """Empty string when `unshare -rn` works here; otherwise why not."""
    if shutil.which("unshare") is None:
        return "unshare(1) is not installed"
    try:
        probe = subprocess.run(
            ["unshare", "-rn", sys.executable, "-c", "pass"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return f"unshare -rn would not run: {e}"
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip() or f"exit {probe.returncode}"
        return f"cannot create a user+network namespace: {detail}"
    return ""


def require_netns() -> None:
    reason = netns_unavailable_reason()
    if not reason:
        return
    if os.environ.get("MEM_REQUIRE_NETNS"):
        pytest.fail(f"MEM_REQUIRE_NETNS is set but the namespace leg cannot run: {reason}")
    pytest.skip(
        f"F12 outer leg SKIPPED - {reason}. The loopback-only namespace proof"
        " did NOT run; set MEM_REQUIRE_NETNS=1 to make this a failure instead."
    )


def test_full_surface_inside_loopback_only_namespace(tmp_path):
    require_netns()
    cfg = json.dumps({"workdir": str(tmp_path), "guard_dir": str(GUARD_DIR)})
    result = subprocess.run(
        ["unshare", "-rn", sys.executable, str(DRIVER), cfg],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"netns driver failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}"
    )
    report = json.loads(result.stdout)

    failed = [c for c in report["checks"] if not c["ok"]]
    assert report["ok"] and not failed, json.dumps(failed, indent=2)
    assert report["interfaces"] == ["lo"]
    # With Ollama up, the only peer across the whole surface is the local
    # Ollama endpoint - one loopback (host, port), nothing else, ever.
    assert len(report["up_peers"]) == 1 and report["up_peers"][0][0] == "127.0.0.1"
    assert report["remote_inet_attempts"] == 0
