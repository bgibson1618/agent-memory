"""F9 - extract-knowledge CLI: `mem extract` dedups candidate concepts against
the KB and saves the genuinely new ones, reporting every candidate's
disposition (added / skipped-duplicate / invalid) in text and --json.

All KB writes go through `mem` subprocesses against an isolated HOME; daemon
states ride the MEM_OLLAMA_URL seam. The fake embedder is deterministic and
semantic (synonym-class dimensions, the capstone D020 pattern), so a near-dup
pair shares synonym classes (cosine 1.0) while distinct concepts land in
disjoint classes (cosine 0.0) - both sides clear of any calibrated threshold
in (0, 1), keeping these tests insensitive to recalibration. The threshold's
*value* is pinned separately: it must equal the measured choice recorded in
the committed calibration artifact (research/dedup-calibration.md).
"""

import json
import re
import sqlite3
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_memory import config

DIMS = 32
MODEL = "nomic-embed-text:v1.5"
DIGEST = "sha256:f9f9f9f9"

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
        vec[len(SYNONYM_CLASSES)] = 1.0  # orthogonal "no known meaning" direction
    return vec


class SemanticOllama:
    """Localhost Ollama double: deterministic meaning-shaped embeddings plus
    /api/tags (extract stamps the model digest on a fresh index)."""

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
def semantic_ollama():
    server = SemanticOllama()
    yield server
    server.stop()


def git_kb(kb, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(kb.kb), *args],
        capture_output=True,
        text=True,
        env=kb.env,
        check=True,
    )


def commit_subjects(kb) -> list:
    return git_kb(kb, "log", "--format=%s").stdout.strip().splitlines()


def concept_files(kb) -> set:
    return {p.name for p in (kb.kb / "concepts").glob("*.md")}


def _rows(kb, sql):
    db = kb.kb / ".index" / "mem.db"
    if not db.exists():
        return []
    con = sqlite3.connect(db)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def vector_slugs(kb) -> set:
    return {row[0] for row in _rows(kb, "SELECT slug FROM vectors")}


def queue_slugs(kb) -> set:
    return {row[0] for row in _rows(kb, "SELECT slug FROM embed_queue")}


# The seed concept and its near-duplicate share synonym classes 0+1 while
# sharing no phrasing; the novel candidates land in disjoint classes.
SEED = {
    "title": "Spaced repetition scheduling",
    "body": "Reviews at increasing intervals beat cramming for retention.",
}
NEAR_DUP = {
    "title": "Spacing effect for review",
    "body": "Rehearsal spread across growing intervals outperforms massed study.",
}
NOVEL_ATTENTION = {
    "title": "Attention is quadratic",
    "body": "Transformer attention cost grows with the square of the context window tokens.",
    "topics": ["ml", "transformers"],
}
NOVEL_DOCKER = {
    "title": "Docker layer caching",
    "body": "Docker reuses image layers; ordering commands preserves the cache.",
    "topics": "devops, docker",
}
INVALID_NO_BODY = {"title": "No body here"}


def seed_kb(mem, env):
    result = mem("save", "--title", SEED["title"], "--body", SEED["body"], env_extra=env)
    assert result.returncode == 0, result.stderr
    return "spaced-repetition-scheduling"


def run_extract(mem, payload, *flags, env_extra=None):
    return mem("extract", "--candidates", json.dumps(payload), *flags, env_extra=env_extra)


def test_mixed_batch_dispositions_text(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    seed = seed_kb(mem, env)

    result = run_extract(
        mem, [NEAR_DUP, NOVEL_ATTENTION, INVALID_NO_BODY, NOVEL_DOCKER], env_extra=env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout

    assert f"skipped-duplicate: {NEAR_DUP['title']} - matches '{seed}'" in out
    assert "added: attention-is-quadratic (Attention is quadratic)" in out
    assert "invalid: candidate #3 (No body here) - missing required field: body" in out
    assert "added: docker-layer-caching (Docker layer caching)" in out
    assert "extract: 2 added, 1 skipped-duplicate, 1 invalid" in out

    # Novel candidates landed as real concepts (file + one commit each + vector);
    # the near-dup and the invalid one left no trace.
    assert concept_files(kb) == {
        f"{seed}.md", "attention-is-quadratic.md", "docker-layer-caching.md",
    }
    subjects = commit_subjects(kb)
    assert subjects.count("mem extract: attention-is-quadratic") == 1
    assert subjects.count("mem extract: docker-layer-caching") == 1
    assert vector_slugs(kb) == {seed, "attention-is-quadratic", "docker-layer-caching"}
    assert queue_slugs(kb) == set()

    # The saved concept round-trips through the ordinary read surface.
    got = mem("get", "attention-is-quadratic", "--json", env_extra=env)
    assert got.returncode == 0, got.stderr
    data = json.loads(got.stdout)
    assert data["title"] == NOVEL_ATTENTION["title"]
    assert data["topics"] == ["ml", "transformers"]


def test_mixed_batch_dispositions_json(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    seed = seed_kb(mem, env)

    result = run_extract(
        mem, [NEAR_DUP, NOVEL_ATTENTION, INVALID_NO_BODY], "--json", env_extra=env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)

    assert report["threshold"] == config.dedup_threshold()
    assert (report["added"], report["skipped_duplicate"], report["invalid"]) == (1, 1, 1)
    assert [r["index"] for r in report["results"]] == [0, 1, 2]

    dup, added, invalid = report["results"]
    assert dup["disposition"] == "skipped-duplicate"
    assert dup["match"] == seed
    assert dup["similarity"] >= report["threshold"]
    assert added["disposition"] == "added"
    assert added["slug"] == "attention-is-quadratic"
    assert Path(added["path"]).is_file()
    assert invalid["disposition"] == "invalid"
    assert "body" in invalid["reason"]


def test_ollama_down_refuses_cleanly_nothing_saved(mem, kb):
    assert mem("init").returncode == 0  # default env: closed port = daemon down
    init_baseline = commit_subjects(kb)

    # Round 1 - empty queue: the batch-embed call is the first daemon contact.
    result = run_extract(mem, [NOVEL_ATTENTION, NOVEL_DOCKER])
    assert result.returncode == 1
    err_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(err_lines) == 1, result.stderr
    assert err_lines[0].startswith("error:")
    assert "embed" in err_lines[0]
    assert concept_files(kb) == set()
    assert commit_subjects(kb) == init_baseline

    # Round 2 - queued backlog: the pre-dedup queue drain is what refuses.
    assert mem("save", "--title", SEED["title"], "--body", SEED["body"]).returncode == 0
    baseline = commit_subjects(kb)
    assert queue_slugs(kb) == {"spaced-repetition-scheduling"}

    result = run_extract(mem, [NOVEL_ATTENTION])
    assert result.returncode == 1
    err_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(err_lines) == 1, result.stderr
    assert err_lines[0].startswith("error:")
    assert concept_files(kb) == {"spaced-repetition-scheduling.md"}
    assert commit_subjects(kb) == baseline


def test_intra_batch_near_dups_deduped(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0

    result = run_extract(mem, [SEED, NEAR_DUP], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    first, second = json.loads(result.stdout)["results"]
    assert first["disposition"] == "added"
    assert first["slug"] == "spaced-repetition-scheduling"
    assert second["disposition"] == "skipped-duplicate"
    assert second["match"] == "spaced-repetition-scheduling"
    assert concept_files(kb) == {"spaced-repetition-scheduling.md"}


def test_queued_backlog_drained_before_dedup(mem, kb, semantic_ollama):
    # Seed while the daemon is down: the concept exists but its embedding is
    # only queued - a dedup that skipped the drain would wrongly call the
    # near-dup novel.
    assert mem("init").returncode == 0
    seed = seed_kb(mem, kb.env)
    assert vector_slugs(kb) == set()
    assert queue_slugs(kb) == {seed}

    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    result = run_extract(mem, [NEAR_DUP], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["results"][0]["disposition"] == "skipped-duplicate"
    assert report["results"][0]["match"] == seed
    assert queue_slugs(kb) == set()
    assert vector_slugs(kb) == {seed}


def test_slug_collision_with_distinct_content_gets_fresh_slug(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", NOVEL_DOCKER["title"], "--body", NOVEL_DOCKER["body"],
        env_extra=env,
    ).returncode == 0

    # Same slug, semantically distinct content (disjoint synonym classes, so
    # similarity is 0 regardless of the calibrated threshold): novel knowledge
    # - extract never overwrites, it takes a fresh slug.
    homonym = {
        "slug": "docker-layer-caching",
        "title": NOVEL_ATTENTION["title"],
        "body": NOVEL_ATTENTION["body"],
    }
    result = run_extract(mem, [homonym], "--json", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    entry = json.loads(result.stdout)["results"][0]
    assert entry["disposition"] == "added"
    assert entry["slug"] == "docker-layer-caching-2"
    assert "note" in entry
    assert concept_files(kb) == {"docker-layer-caching.md", "docker-layer-caching-2.md"}


def test_malformed_candidates_refused_cleanly(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0

    for bad in ("[not json", '{"foo": 1}', "no-such-file.json"):
        result = mem("extract", "--candidates", bad, env_extra=env)
        assert result.returncode == 1, bad
        err_lines = [line for line in result.stderr.splitlines() if line.strip()]
        assert len(err_lines) == 1 and err_lines[0].startswith("error:"), result.stderr
    assert concept_files(kb) == set()

    # An empty batch is processed (not a refusal): zero dispositions reported.
    result = run_extract(mem, [], "--json", env_extra=env)
    assert result.returncode == 0
    assert json.loads(result.stdout)["results"] == []


def test_threshold_matches_committed_calibration_artifact():
    artifact = Path(__file__).resolve().parents[1] / "research" / "dedup-calibration.md"
    assert artifact.is_file(), (
        "research/dedup-calibration.md is missing - the dedup threshold must be"
        " measured, not guessed (capstone D024); generate it against the real"
        " daemon with: uv run python research/dedup_calibration.py"
    )
    match = re.search(
        r"^chosen-threshold:\s*([0-9]+\.[0-9]+)\s*$", artifact.read_text(encoding="utf-8"), re.M
    )
    assert match, "artifact lacks a machine-readable 'chosen-threshold: <value>' line"
    assert float(match.group(1)) == config.DEFAULT_DEDUP_THRESHOLD, (
        f"config.DEFAULT_DEDUP_THRESHOLD={config.DEFAULT_DEDUP_THRESHOLD} does not equal"
        f" the calibrated choice {match.group(1)} recorded in {artifact}"
    )
    assert 0.0 < config.DEFAULT_DEDUP_THRESHOLD < 1.0
