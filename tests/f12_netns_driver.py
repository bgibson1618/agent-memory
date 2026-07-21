"""F12 loopback-only namespace driver - the outer layer of the zero-egress proof.

test_f12_egress.py launches this script inside a fresh network namespace
(`unshare -rn`): the namespace has only its own `lo`, so *no* process in it -
Python, git, anything - can reach a non-localhost peer, and every syscall-level
escape attempt fails with ENETUNREACH. Inside, the driver brings `lo` up,
verifies the airgap, starts a deterministic fake Ollama on loopback, and runs
the full `mem` surface (init / doctor / save / search / get / list / extract /
reindex) three ways:

  up-leg      fake daemon reachable: every command succeeds fully, and the
              in-process guard log proves the only network peer across all
              operations is the local Ollama endpoint;
  down-leg    daemon at a closed loopback port: each command degrades exactly
              as specced (save queues, search warns once, extract refuses,
              doctor fails the ollama check, reindex leaves embeds queued);
  remote-leg  MEM_OLLAMA_URL pointing off-box: refused before a single
              socket opens (zero connect attempts recorded).

Also importable by the test module for its fake-Ollama and concept fixtures.
Stdout is one JSON report; exit 0 iff every check passed.
"""

import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIMS = 32
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:f12f12f1"

# The capstone D020 pattern (as in test_f9_extract): deterministic
# meaning-shaped embeddings - near-dups share synonym classes (cosine 1.0),
# distinct concepts land in disjoint classes (cosine 0.0), so dispositions
# never depend on the calibrated threshold's exact value.
SYNONYM_CLASSES = [
    {"spaced", "spacing", "interval", "intervals"},
    {"repetition", "review", "reviews", "rehearsal"},
    {"transformer", "attention", "quadratic"},
    {"context", "window", "tokens"},
    {"docker", "container", "image"},
    {"cache", "caching", "layer", "layers"},
]

SEED = {
    "title": "Spaced repetition scheduling",
    "body": "Reviews at increasing intervals beat cramming for retention.",
}
SEED_SLUG = "spaced-repetition-scheduling"
NEAR_DUP = {
    "title": "Spacing effect for review",
    "body": "Rehearsal spread across growing intervals outperforms massed study.",
}
NOVEL_DOCKER = {
    "title": "Docker layer caching",
    "body": "Docker reuses image layers; ordering commands preserves the cache.",
}
NOVEL_ATTENTION = {
    "title": "Attention is quadratic",
    "body": "Transformer attention cost grows with the square of the context window tokens.",
}


def semantic_vec(text: str, dims: int) -> list:
    words = set(re.findall(r"[a-z]+", text.lower()))
    vec = [0.0] * dims
    for i, cls in enumerate(SYNONYM_CLASSES):
        if words & cls:
            vec[i] = 1.0
    if not any(vec):
        vec[len(SYNONYM_CLASSES)] = 1.0  # orthogonal "no known meaning" direction
    return vec


class SemanticOllama:
    """Loopback Ollama double: /api/version, /api/tags, /api/embed."""

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
                    self._send(200, {"version": "0.0.0-netns-fake"})
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
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def bring_lo_up() -> None:
    """SIOCSIFFLAGS on `lo` - pure stdlib, so the namespace leg never depends
    on iproute2 being installed. `ip link set lo up` is the fallback."""
    SIOCGIFFLAGS, SIOCSIFFLAGS, IFF_UP, IFREQ_SIZE = 0x8913, 0x8914, 0x1, 40
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            req = struct.pack("16sH", b"lo", 0).ljust(IFREQ_SIZE, b"\x00")
            res = fcntl_ioctl(s.fileno(), SIOCGIFFLAGS, req)
            (flags,) = struct.unpack_from("H", res, 16)
            req = struct.pack("16sH", b"lo", flags | IFF_UP).ljust(IFREQ_SIZE, b"\x00")
            fcntl_ioctl(s.fileno(), SIOCSIFFLAGS, req)
        finally:
            s.close()
    except OSError:
        subprocess.run(["ip", "link", "set", "lo", "up"], check=True, capture_output=True)


def fcntl_ioctl(fd, request, arg):
    import fcntl

    return fcntl.ioctl(fd, request, arg)


def closed_loopback_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def read_log(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def inet_peers(entries: list) -> set:
    return {
        (e["peer"]["host"], e["peer"]["port"]) for e in entries if e["peer"]["family"] == "inet"
    }


class Report:
    def __init__(self):
        self.checks = []
        self.extra = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail[:2000]})
        return bool(ok)

    def emit(self) -> int:
        ok = all(c["ok"] for c in self.checks)
        print(json.dumps({"ok": ok, "checks": self.checks, **self.extra}, indent=2))
        return 0 if ok else 1


def main(config_json: str) -> int:
    cfg = json.loads(config_json)
    workdir = Path(cfg["workdir"])
    guard_dir = cfg["guard_dir"]
    rep = Report()

    bring_lo_up()

    # --- Airgap: the namespace must offer loopback and nothing else. -------
    interfaces = sorted(name for _idx, name in socket.if_nameindex())
    rep.extra["interfaces"] = interfaces
    rep.check("only-lo-interface", interfaces == ["lo"], f"interfaces: {interfaces}")

    try:
        probe = socket.socket()
        probe.settimeout(2)
        try:
            probe.connect(("192.0.2.1", 9))
            rep.check("external-unreachable", False, "connect to 192.0.2.1 SUCCEEDED - namespace leaked")
        except OSError as e:
            rep.check("external-unreachable", True, f"192.0.2.1 refused by kernel: {e}")
        finally:
            probe.close()
    except Exception as e:  # pragma: no cover - diagnostics only
        rep.check("external-unreachable", False, f"probe crashed: {e}")

    try:
        probe = socket.socket()
        probe.settimeout(2)
        try:
            probe.connect(("127.0.0.1", closed_loopback_port()))
            lo_ok, lo_detail = False, "closed loopback port accepted a connection"
        except ConnectionRefusedError:
            lo_ok, lo_detail = True, "loopback answers (ECONNREFUSED on a closed port)"
        except OSError as e:
            lo_ok, lo_detail = False, f"loopback not answering: {e}"
        finally:
            probe.close()
    except Exception as e:  # pragma: no cover
        lo_ok, lo_detail = False, f"probe crashed: {e}"
    rep.check("loopback-up", lo_ok, lo_detail)

    # --- Environment for `mem` subprocesses (guard armed in every one). ----
    home = workdir / "home"
    home.mkdir(parents=True, exist_ok=True)
    log_up = workdir / "connects-up.jsonl"
    log_down = workdir / "connects-down.jsonl"
    log_remote = workdir / "connects-remote.jsonl"

    fake = SemanticOllama()

    def env_for(url: str, log: Path) -> dict:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "MEM_OLLAMA_URL": url,
            "MEM_EMBED_DIMS": str(DIMS),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONUTF8": "1",
            "PYTHONPATH": guard_dir,
            "MEM_EGRESS_GUARD": "enforce",
            "MEM_EGRESS_LOG": str(log),
        }

    def mem(env: dict, *args, input=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_memory", *args],
            capture_output=True,
            text=True,
            env=env,
            input=input,
            timeout=120,
        )

    def stderr_lines(result) -> list:
        return [line for line in result.stderr.splitlines() if line.strip()]

    # ======================= up-leg: daemon reachable =======================
    up = env_for(fake.url, log_up)

    r = mem(up, "init")
    rep.check("up-init", r.returncode == 0 and "initialized:" in r.stdout, r.stdout + r.stderr)

    r = mem(up, "doctor")
    rep.check(
        "up-doctor-all-ok",
        r.returncode == 0 and "FAIL" not in r.stdout,
        r.stdout + r.stderr,
    )

    r = mem(up, "save", "--title", SEED["title"], "--body", SEED["body"])
    rep.check("up-save", r.returncode == 0 and not stderr_lines(r), r.stdout + r.stderr)

    r = mem(up, "list")
    rep.check("up-list", r.returncode == 0 and SEED_SLUG in r.stdout, r.stdout + r.stderr)

    r = mem(up, "get", SEED_SLUG, "--json")
    try:
        got_title = json.loads(r.stdout).get("title")
    except ValueError:
        got_title = None
    rep.check("up-get", r.returncode == 0 and got_title == SEED["title"], r.stdout + r.stderr)

    r = mem(up, "search", "spaced repetition intervals", "--json")
    try:
        hit_slugs = [h["slug"] for h in json.loads(r.stdout)]
    except ValueError:
        hit_slugs = []
    rep.check(
        "up-search-fused-no-warning",
        r.returncode == 0 and SEED_SLUG in hit_slugs and not stderr_lines(r),
        r.stdout + r.stderr,
    )

    r = mem(up, "extract", "--candidates", json.dumps([NEAR_DUP, NOVEL_DOCKER]), "--json")
    try:
        dispositions = [x["disposition"] for x in json.loads(r.stdout)["results"]]
    except (ValueError, KeyError):
        dispositions = []
    rep.check(
        "up-extract-dedup",
        r.returncode == 0 and dispositions == ["skipped-duplicate", "added"],
        r.stdout + r.stderr,
    )

    r = mem(up, "reindex")
    rep.check(
        "up-reindex-drained",
        r.returncode == 0
        and r.stdout.startswith("reindexed: 2 concept(s)")
        and "embedding(s) drained" in r.stdout
        and not stderr_lines(r),
        r.stdout + r.stderr,
    )

    up_entries = read_log(log_up)
    up_peers = inet_peers(up_entries)
    rep.extra["up_connects"] = len(up_entries)
    rep.extra["up_peers"] = sorted(map(list, up_peers))
    rep.check(
        "up-guard-live",
        len(up_entries) >= 3,
        f"{len(up_entries)} connect(s) recorded - the guard was loaded and embedding traffic flowed",
    )
    rep.check(
        "up-only-peer-is-ollama",
        bool(up_peers) and up_peers == {("127.0.0.1", fake.port)},
        f"peers: {sorted(up_peers)} vs ollama 127.0.0.1:{fake.port}",
    )
    rep.check(
        "up-all-connects-allowed",
        all(e["allowed"] for e in up_entries),
        "every recorded connect was loopback",
    )

    # ================== down-leg: daemon at a closed port ==================
    down = env_for(f"http://127.0.0.1:{closed_loopback_port()}", log_down)

    r = mem(down, "save", "--title", NOVEL_ATTENTION["title"], "--body", NOVEL_ATTENTION["body"])
    rep.check("down-save-queues-quietly", r.returncode == 0 and not stderr_lines(r), r.stdout + r.stderr)

    r = mem(down, "search", "transformer attention", "--json")
    lines = stderr_lines(r)
    try:
        hit_slugs = [h["slug"] for h in json.loads(r.stdout)]
    except ValueError:
        hit_slugs = []
    rep.check(
        "down-search-degrades-one-warning",
        r.returncode == 0
        and "attention-is-quadratic" in hit_slugs
        and len(lines) == 1
        and lines[0].startswith("warning: semantic leg skipped"),
        r.stdout + r.stderr,
    )

    r = mem(down, "extract", "--candidates", json.dumps([{"title": "Container images", "body": "A container image is a layered filesystem snapshot."}]))
    lines = stderr_lines(r)
    rep.check(
        "down-extract-refuses-one-line",
        r.returncode == 1
        and len(lines) == 1
        and lines[0].startswith("error: cannot dedup without embeddings:"),
        r.stdout + r.stderr,
    )

    # ============ remote-leg: off-box URL refused before any socket ============
    # Runs before the down-leg reindex on purpose: reindex wipes vector_meta,
    # after which search's vector leg returns early without ever contacting
    # the daemon - the refusal warning below needs a stamped index to fire.
    remote = env_for("http://203.0.113.7:11434", log_remote)

    r = mem(remote, "doctor")
    rep.check(
        "remote-doctor-refuses",
        r.returncode == 1 and "refusing non-loopback Ollama URL" in r.stdout,
        r.stdout + r.stderr,
    )

    r = mem(remote, "search", "spaced repetition", "--json")
    lines = stderr_lines(r)
    rep.check(
        "remote-search-degrades-with-refusal",
        r.returncode == 0
        and len(lines) == 1
        and lines[0].startswith("warning: semantic leg skipped")
        and "refusing non-loopback" in lines[0],
        r.stdout + r.stderr,
    )

    remote_attempts = len(inet_peers(read_log(log_remote)))
    rep.extra["remote_inet_attempts"] = remote_attempts
    rep.check(
        "remote-zero-connect-attempts",
        remote_attempts == 0,
        "the refusal happens before a single socket opens",
    )

    # =============== down-leg tail: reindex + final diagnosis ===============
    r = mem(down, "reindex")
    rep.check(
        "down-reindex-queues",
        r.returncode == 0 and "they drain when the daemon returns" in r.stderr,
        r.stdout + r.stderr,
    )

    r = mem(down, "doctor")
    rep.check(
        "down-doctor-fails-ollama-only",
        r.returncode == 1
        and "FAIL  ollama:" in r.stdout
        and r.stdout.count("FAIL") == 2  # the ollama line + the summary line
        and "skip  embed-queue:" in r.stdout,
        r.stdout + r.stderr,
    )

    down_entries = read_log(log_down)
    rep.check(
        "down-all-connects-loopback",
        bool(down_entries) and all(e["allowed"] for e in down_entries),
        f"{len(down_entries)} connect(s), all loopback",
    )

    fake.stop()
    return rep.emit()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
