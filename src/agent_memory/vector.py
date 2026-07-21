"""Vector leg - semantic recall via local Ollama embeddings.

The derived vector index lives in `.index/mem.db` (WAL): float32 vectors as
BLOBs, a pending-embed queue, and index metadata (model tag + digest + dims).
Embedding never blocks or loses a save: the save path embeds within a strict
~500 ms client budget and enqueues on any daemon trouble; ordinary invocations
drain up to DRAIN_LIMIT queued items iff the daemon answers a fast health
check, and `mem doctor` / `mem reindex` drain fully. A vector write whose
dimensions or model tag disagree with the stamped metadata is refused with a
one-line error - `mem reindex` re-stamps.
"""

import hashlib
import os
import sqlite3
import sys
from array import array
from pathlib import Path

from agent_memory import config, okf, ollama

DRAIN_LIMIT = 3            # bounded opportunistic drain: ~3 items per invocation
STRICT_TIMEOUT = 0.5       # save-path / opportunistic embed budget, seconds
FULL_DRAIN_TIMEOUT = 30.0  # doctor/reindex per-item budget, seconds
HEALTH_TIMEOUT = 0.5       # pre-drain daemon health check budget, seconds
QUERY_TIMEOUT = 2.0        # query-embed budget, seconds
EMBED_MAX_CHARS = 32000    # ~8k tokens, the nomic num_ctx ceiling

# One failed daemon contact per process is enough evidence to skip further
# optional embed work this invocation - a hung daemon must cost ~one timeout.
_daemon_unhealthy = False


class VectorError(Exception):
    """A one-line, agent-actionable vector-index refusal."""


def strict_timeout() -> float:
    return float(os.environ.get("MEM_EMBED_TIMEOUT", str(STRICT_TIMEOUT)))


def db_path(root: Path) -> Path:
    return root / ".index" / "mem.db"


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.execute(
        "CREATE TABLE IF NOT EXISTS vectors ("
        " slug TEXT PRIMARY KEY, model TEXT NOT NULL, dims INTEGER NOT NULL,"
        " content_hash TEXT NOT NULL, vec BLOB NOT NULL, updated TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS embed_queue ("
        " slug TEXT PRIMARY KEY, enqueued TEXT NOT NULL)"
    )
    con.execute("CREATE TABLE IF NOT EXISTS vector_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    return con


def embed_text(concept: okf.Concept) -> str:
    parts = [concept.title, concept.description, ", ".join(concept.topics), concept.body]
    text = "\n\n".join(p.strip() for p in parts if p and p.strip())
    # nomic-embed retrieval prefixes: documents and queries embed into the same space
    return ("search_document: " + text)[:EMBED_MAX_CHARS]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_meta(con: sqlite3.Connection) -> dict | None:
    rows = dict(con.execute("SELECT key, value FROM vector_meta"))
    return rows or None


def _stamp_meta(con: sqlite3.Connection, model: str, digest: str, dims: int) -> None:
    for key, value in (("model", model), ("digest", digest), ("dims", str(dims))):
        con.execute("INSERT OR REPLACE INTO vector_meta(key, value) VALUES(?, ?)", (key, value))


def enqueue(con: sqlite3.Connection, slug: str) -> None:
    con.execute(
        "INSERT INTO embed_queue(slug, enqueued) VALUES(?, ?) ON CONFLICT(slug) DO NOTHING",
        (slug, okf.now_stamp()),
    )


def queue_size(root: Path) -> int:
    if not db_path(root).exists():
        return 0
    con = connect(root)
    try:
        return con.execute("SELECT COUNT(*) FROM embed_queue").fetchone()[0]
    finally:
        con.close()


def _embed_one(con: sqlite3.Connection, slug: str, concept: okf.Concept, timeout: float) -> None:
    """Embed one concept and store its vector, dequeuing it. Raises
    ollama.OllamaError on daemon trouble, VectorError on a refused write."""
    base = config.ollama_base_url()
    model = config.embed_model()
    text = embed_text(concept)
    vec = ollama.embed(base, model, [text], timeout=timeout)[0]

    meta = get_meta(con)
    if meta is None:
        _stamp_meta(con, model, ollama.model_digest(base, model), len(vec))
    elif meta.get("model") != model:
        raise VectorError(
            f"index built with model {meta.get('model')}, current model is {model}"
            " - vector write refused; run: mem reindex"
        )
    elif int(meta.get("dims", 0)) != len(vec):
        raise VectorError(
            f"embedding dims {len(vec)} != index dims {meta.get('dims')}"
            " - vector write refused; run: mem reindex"
        )

    con.execute(
        "INSERT OR REPLACE INTO vectors(slug, model, dims, content_hash, vec, updated)"
        " VALUES(?, ?, ?, ?, ?, ?)",
        (slug, model, len(vec), content_hash(text), array("f", vec).tobytes(), okf.now_stamp()),
    )
    con.execute("DELETE FROM embed_queue WHERE slug = ?", (slug,))
    con.commit()


def index_saved(root: Path, concept: okf.Concept) -> None:
    """Post-save hook: embed now within the strict budget or leave the durable
    queue entry for a later drain. Never raises, never blocks the save."""
    global _daemon_unhealthy
    try:
        con = connect(root)
        try:
            enqueue(con, concept.slug)  # durable intent first; _embed_one dequeues on success
            con.commit()
            _embed_one(con, concept.slug, concept, strict_timeout())
        finally:
            con.close()
    except ollama.OllamaError:
        _daemon_unhealthy = True  # queued; a later invocation drains
    except VectorError as e:
        print(f"error: {e}", file=sys.stderr)
    except Exception as e:  # the vector index must never break a save
        print(f"warning: vector index update failed: {e}", file=sys.stderr)


def _drain(root: Path, limit: int | None, timeout: float):
    """Drain queued embeds oldest-first, up to `limit` (None = all). Returns
    (drained, remaining, error) - error is the exception that stopped the
    drain, or None if the queue emptied / the limit was reached."""
    global _daemon_unhealthy
    con = connect(root)
    try:
        drained = 0
        error = None
        while limit is None or drained < limit:
            row = con.execute(
                "SELECT slug FROM embed_queue ORDER BY enqueued, slug LIMIT 1"
            ).fetchone()
            if row is None:
                break
            slug = row[0]
            path = root / "concepts" / f"{slug}.md"
            if not path.is_file():
                con.execute("DELETE FROM embed_queue WHERE slug = ?", (slug,))
                con.commit()
                continue
            try:
                concept = okf.parse(path.read_text(encoding="utf-8"))
            except okf.OKFError:
                con.execute("DELETE FROM embed_queue WHERE slug = ?", (slug,))
                con.commit()
                continue
            try:
                _embed_one(con, slug, concept, timeout)
            except ollama.OllamaError as e:
                _daemon_unhealthy = True
                error = e
                break
            except VectorError as e:
                error = e
                break
            drained += 1
        remaining = con.execute("SELECT COUNT(*) FROM embed_queue").fetchone()[0]
        return drained, remaining, error
    finally:
        con.close()


def opportunistic_drain(root: Path) -> None:
    """After a command's primary work: drain up to DRAIN_LIMIT queued embeds
    iff the daemon answers a fast health check. Quiet; never raises."""
    global _daemon_unhealthy
    try:
        if _daemon_unhealthy or not db_path(root).exists() or queue_size(root) == 0:
            return
        ollama.check_version(config.ollama_base_url(), timeout=HEALTH_TIMEOUT)
        _drain(root, DRAIN_LIMIT, strict_timeout())
    except ollama.OllamaError:
        _daemon_unhealthy = True
    except Exception:
        pass


def drain_fully(root: Path, timeout: float = FULL_DRAIN_TIMEOUT):
    """Drain the whole queue (doctor / reindex). Returns (drained, remaining, error)."""
    return _drain(root, None, timeout)


def top_k(root: Path, query: str, k: int = 5, timeout: float = QUERY_TIMEOUT) -> list:
    """The vector leg: brute-force cosine over stored vectors, best first.
    Returns [(slug, score), ...]; raises ollama.OllamaError when the daemon
    cannot embed the query (callers decide how to degrade)."""
    if not db_path(root).exists():
        return []
    con = connect(root)
    try:
        meta = get_meta(con)
        if meta is None:
            return []
        qvec = ollama.embed(
            config.ollama_base_url(), config.embed_model(),
            ["search_query: " + query], timeout=timeout,
        )[0]
        if len(qvec) != int(meta.get("dims", 0)):
            raise VectorError(
                f"query embedding dims {len(qvec)} != index dims {meta.get('dims')} - run: mem reindex"
            )
        rows = con.execute("SELECT slug, vec FROM vectors WHERE dims = ?", (len(qvec),)).fetchall()
    finally:
        con.close()
    if not rows:
        return []

    import numpy as np  # deferred: only query paths pay the import

    mat = np.vstack([np.frombuffer(blob, dtype=np.float32) for _, blob in rows])
    q = np.asarray(qvec, dtype=np.float32)
    qnorm = float(np.linalg.norm(q))
    norms = np.linalg.norm(mat, axis=1)
    if qnorm == 0.0:
        return []
    scores = (mat @ q) / (np.where(norms == 0.0, 1.0, norms) * qnorm)
    order = np.argsort(-scores)[:k]
    return [(rows[i][0], float(scores[i])) for i in order]


def cmd_reindex(args) -> int:
    """Rebuild the vector index from markdown alone: wipe vectors + metadata,
    enqueue every valid concept, drain fully."""
    root = config.kb_root()
    if not (root / "concepts").is_dir():
        print(f"error: no KB home at {root} - run: mem init", file=sys.stderr)
        return 1

    con = connect(root)
    try:
        con.execute("DELETE FROM vectors")
        con.execute("DELETE FROM embed_queue")
        con.execute("DELETE FROM vector_meta")
        for path in sorted((root / "concepts").glob("*.md")):
            try:
                okf.parse(path.read_text(encoding="utf-8"))
            except okf.OKFError as e:
                print(f"warning: skipping {path}: {e}", file=sys.stderr)
                continue
            enqueue(con, path.stem)
        con.commit()
    finally:
        con.close()

    drained, remaining, error = drain_fully(root)
    if remaining == 0:
        print(f"reindexed: {drained} concept embedding(s) rebuilt")
        return 0
    if isinstance(error, ollama.OllamaError):
        print(
            f"reindexed: {drained} embedded, {remaining} queued - {error};"
            " they drain when the daemon returns",
            file=sys.stderr,
        )
        return 0
    print(f"error: {error} ({remaining} embedding(s) still queued)", file=sys.stderr)
    return 1
