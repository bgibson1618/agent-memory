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

from agent_memory import config, indexdb, okf, ollama

DRAIN_LIMIT = 3            # bounded opportunistic drain: ~3 items per invocation
STRICT_TIMEOUT = 0.5       # save-path / opportunistic embed budget, seconds
FULL_DRAIN_TIMEOUT = 30.0  # doctor/reindex per-item budget, seconds
HEALTH_TIMEOUT = 0.5       # pre-drain daemon health check budget, seconds
QUERY_TIMEOUT = 2.5        # query-embed budget, seconds (inside NFR's <3s cold search;
                           # must survive Ollama's num_ctx-change model reload, the
                           # wave-4 walkthrough finding - see BUILD_LOG). A cold MODEL
                           # load (daemon restart) exceeds this: _embed_query proves
                           # the daemon alive, then retries once on the cold budget.
EMBED_MAX_CHARS = 32000    # ~8k tokens, the nomic num_ctx ceiling

# One failed daemon contact per process is enough evidence to skip further
# optional embed work this invocation - a hung daemon must cost ~one timeout.
_daemon_unhealthy = False


class VectorError(Exception):
    """A one-line, agent-actionable vector-index refusal."""


def mark_daemon_unhealthy() -> None:
    """Callers that just watched a daemon call fail record it here, so the
    post-command opportunistic drain doesn't pay another timeout."""
    global _daemon_unhealthy
    _daemon_unhealthy = True


def strict_timeout() -> float:
    return float(os.environ.get("MEM_EMBED_TIMEOUT", str(STRICT_TIMEOUT)))


def db_path(root: Path) -> Path:
    return indexdb.db_path(root)


def connect(root: Path) -> sqlite3.Connection:
    con = indexdb.connect(root)
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


def document_text(concept: okf.Concept) -> str:
    """The unprefixed, untruncated text `embed_text` and D18's chunker both
    build from - factored out so a card's ONE chunk (S3: no headings, <=1,000
    chars) can be byte-identical to what `embed_text` embeds, making
    cosine_best_chunk == cosine_document exactly rather than approximately."""
    return _document_text_from(concept.title, concept.description, concept.topics, concept.body)


def _document_text_from(title: str, description: str, topics: list, body: str) -> str:
    """The one place the document text is assembled, from a concept's fields or
    from its lexical-index row (S6 slice A), so the two can never diverge."""
    parts = [title, description, ", ".join(topics), body]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def embed_text(concept: okf.Concept) -> str:
    # nomic-embed retrieval prefixes: documents and queries embed into the same space
    return ("search_document: " + document_text(concept))[:EMBED_MAX_CHARS]


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def current_embed_hashes(con: sqlite3.Connection) -> dict | None:
    """{slug: content_hash of embed_text(current card)} for every card in the
    lexical index (S6 slice A: no surface scores a stale vector). Callers sync
    the lexical index first, so its rows are the files' current text. Topics
    are kebab-case slugs (okf.normalize_topics), so the index's space-joined
    column splits back exactly. Returns None only when the database has no
    lexical table at all (never synced): freshness cannot be checked there.
    Every production caller (search, dedup's build_corpus, extract) syncs
    first. Any other error propagates rather than turning freshness checking
    off - a lock, or a damaged FTS5 index whose backing table is missing
    (that also says "no such table", so `lexical`'s own absence is checked)."""
    try:
        rows = con.execute("SELECT slug, title, description, body, topics FROM lexical").fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e) or con.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'lexical'"
        ).fetchone():
            raise
        return None
    out = {}
    for slug, title, description, body, topics in rows:
        text = _document_text_from(title or "", description or "", (topics or "").split(), body or "")
        out[slug] = content_hash(("search_document: " + text)[:EMBED_MAX_CHARS])
    return out


def fresh_vector_rows(con: sqlite3.Connection, dims: int, stale_out: list | None = None,
                      current: dict | None = None) -> list:
    """[(slug, vec_blob)] ordered by slug, keeping only vectors whose stored
    content hash equals the card's current one. A card whose vector is stale
    (edited since it was embedded) is left out, appended to `stale_out`, and
    (re-)enqueued so the next drain heals it - the change-set reconcile only
    sees files changed since the last sync, so a vector left stale earlier
    would otherwise stay out of every leg. A vector with no current card is
    left out. Pass `current` (from current_embed_hashes) to reuse one
    snapshot across a batch."""
    if current is None:
        current = current_embed_hashes(con)
    rows = con.execute(
        "SELECT slug, content_hash, vec FROM vectors WHERE dims = ? ORDER BY slug", (dims,)
    ).fetchall()
    if current is None:  # never-synced database: nothing to check against
        return [(slug, blob) for slug, _h, blob in rows]
    fresh, stale = [], []
    for slug, stored_hash, blob in rows:
        now = current.get(slug)
        if now is not None and now == stored_hash:
            fresh.append((slug, blob))
        elif now is not None:
            stale.append(slug)
    if stale:
        for slug in stale:
            enqueue(con, slug)
        con.commit()
        if stale_out is not None:
            stale_out.extend(stale)
    return fresh


def get_meta(con: sqlite3.Connection) -> dict | None:
    rows = dict(con.execute("SELECT key, value FROM vector_meta"))
    return rows or None


def _stamp_meta(con: sqlite3.Connection, model: str, digest: str, dims: int) -> None:
    for key, value in (("model", model), ("digest", digest), ("dims", str(dims))):
        con.execute("INSERT OR REPLACE INTO vector_meta(key, value) VALUES(?, ?)", (key, value))


def check_meta(
    meta: dict | None, model: str, dims: int, refusal: str, digest: str | None = None,
) -> None:
    """Refuse a (model, dims[, digest]) pair that disagrees with the stamped
    index metadata - one wording for the write path, extract's batch gate,
    and D18's document/chunk scans. `digest` is optional and back-compat:
    omitted (extract.py's call, byte-untouched this wave), it is not
    checked - callers that KNOW the digest they embedded with (D18's
    dedup.Corpus, which computes it right after the batch embed) pass it so
    a same-named model whose installed weights changed since the index was
    built is refused too, not just a renamed model (gate finding 3)."""
    if meta is None:
        return
    if meta.get("model") != model:
        raise VectorError(
            f"index built with model {meta.get('model')}, current model is {model}"
            f" - {refusal}; run: mem reindex"
        )
    if int(meta.get("dims", 0)) != dims:
        raise VectorError(
            f"embedding dims {dims} != index dims {meta.get('dims')}"
            f" - {refusal}; run: mem reindex"
        )
    if digest is not None and meta.get("digest") not in (None, "unknown", digest):
        raise VectorError(
            f"index built with model {model} digest {meta.get('digest')}, current digest is {digest}"
            f" - {refusal}; run: mem reindex"
        )


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
    else:
        check_meta(meta, model, len(vec), "vector write refused")

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


def reconcile(root: Path, changed, removed) -> None:
    """External-edit healing for the vector leg (F8), fed by lexical.sync's
    change-set on every search. Removed slugs lose their vector rows and queue
    entries - no ghost hits pointing at missing paths. Changed slugs whose
    stored embedding no longer matches the file's current embed-text are
    (re-)enqueued; a touch or byte-identical rewrite matches its content hash
    and costs nothing. Local DB work only - never contacts the daemon, never
    raises: the index is derived state and must not break a search."""
    if not changed and not removed:
        return
    try:
        con = connect(root)
        try:
            for slug in removed:
                con.execute("DELETE FROM vectors WHERE slug = ?", (slug,))
                con.execute("DELETE FROM embed_queue WHERE slug = ?", (slug,))
            for slug, concept in changed:
                row = con.execute(
                    "SELECT content_hash FROM vectors WHERE slug = ?", (slug,)
                ).fetchone()
                if row is not None and row[0] == content_hash(embed_text(concept)):
                    continue  # vector still current
                enqueue(con, slug)
            con.commit()
        finally:
            con.close()
    except Exception as e:
        print(f"warning: vector reconcile failed: {e}", file=sys.stderr)


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


def query_timeout() -> float:
    return float(os.environ.get("MEM_EMBED_QUERY_TIMEOUT", str(QUERY_TIMEOUT)))


def _embed_query(base: str, model: str, text: str, timeout: float) -> list:
    """Embed the query, riding out a cold model load. A timeout alone cannot
    distinguish a hung daemon from a healthy one still loading the model
    (daemon restart), and an aborted request does not leave the model loaded -
    so on timeout, a fast version check proves the daemon is alive, then one
    long-budget retry holds the connection open for the load to complete. A
    dead/hung daemon fails the version check and still costs ~one timeout."""
    try:
        return ollama.embed(base, model, [text], timeout=timeout)[0]
    except ollama.OllamaTimeout:
        ollama.check_version(base, timeout=HEALTH_TIMEOUT)
        budget = ollama.cold_timeout()
        print(
            f"warning: embed model loading; retrying query embed (up to {budget:.0f}s)",
            file=sys.stderr,
        )
        return ollama.embed(base, model, [text], timeout=budget)[0]


def _scan_rows(rows: list, qvec: list, k: int | None) -> list:
    """Shared brute-force cosine scan: `rows` is [(slug, vec_blob), ...],
    `k=None` returns the FULL ranked list (D18's `top_k_doc` whole-KB scope),
    otherwise the top `k`. Factored out of `top_k` unchanged (same stable
    argsort, same tie-break) so `top_k_doc` doesn't duplicate it."""
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
    limit = len(scores) if k is None else k
    order = np.argsort(-scores, kind="stable")[:limit]
    return [(rows[i][0], float(scores[i])) for i in order]


def _has_concepts(root: Path) -> bool:
    """Whether there is anything to know: one concept file is enough."""
    return next((root / "concepts").glob("*.md"), None) is not None


def require_built(root: Path, con: sqlite3.Connection | None) -> dict | None:
    """Structural absence of the semantic index, when the KB does hold
    concepts, is a degraded search and must be said: a missing database, an
    index never built (no metadata) or no stored vectors at all each raise
    VectorError with the remedy, so the caller's one warning line fires.
    A KB with no concepts has nothing to know and stays quiet; a genuine
    no-match or a zero-norm query also stays an empty result (Stage 2,
    2026-11; the 2026-09-14 AM-1 finding)."""
    if con is None:
        if _has_concepts(root):
            raise VectorError("vector index not built - run: mem reindex")
        return None
    meta = get_meta(con)
    if meta is None:
        if _has_concepts(root):
            raise VectorError("vector index not built - run: mem reindex")
        return None
    stored = con.execute("SELECT count(*) FROM vectors").fetchone()[0]
    if stored == 0 and _has_concepts(root):
        pending = con.execute("SELECT count(*) FROM embed_queue").fetchone()[0]
        raise VectorError(f"no embeddings stored yet ({pending} pending) - run: mem reindex")
    return meta


def top_k(root: Path, query: str, k: int = 5, timeout: float | None = None,
          stale_out: list | None = None) -> list:
    """The vector leg: brute-force cosine over stored vectors, best first.
    Returns [(slug, score), ...]; raises ollama.OllamaError when the daemon
    cannot embed the query and VectorError when the index is structurally
    absent for a KB that has concepts (callers decide how to degrade). The
    daemon is consulted first so that, when both are true, the warning names
    the unreachable embedder rather than advising a reindex that could not
    embed either."""
    con = connect(root) if db_path(root).exists() else None
    try:
        qvec = _embed_query(
            config.ollama_base_url(), config.embed_model(),
            "search_query: " + query,
            timeout if timeout is not None else query_timeout(),
        )
        meta = require_built(root, con)
        if meta is None:
            return []
        assert con is not None  # require_built returns None when there is no index
        if len(qvec) != int(meta.get("dims", 0)):
            raise VectorError(
                f"query embedding dims {len(qvec)} != index dims {meta.get('dims')} - run: mem reindex"
            )
        # ORDER BY slug + stable argsort below: leg ranking (and thus RRF rank
        # credit) must be rebuild-invariant - exact-tie order can't depend on
        # insertion order (the wave-5 byte-equivalence catch). Stale vectors
        # (card edited since it was embedded) are never scored (S6 slice A).
        rows = fresh_vector_rows(con, len(qvec), stale_out)
    finally:
        if con is not None:
            con.close()
    return _scan_rows(rows, qvec, k)


def top_k_doc(
    root: Path, text: str | None = None, *, vec: list | None = None,
    k: int | None = None, timeout: float | None = None,
    model: str | None = None, digest: str | None = None,
    stale_out: list | None = None, current: dict | None = None,
) -> list:
    """D18 S4.2 - the document-prefixed twin of `top_k`: `search_document:`
    on BOTH sides (`top_k` prefixes the query side with `search_query:`),
    so results are on the calibrated document-document cosine scale D3/D17's
    bands were measured against - reusing `top_k`'s query-prefixed leg for
    dedup would put a query-prefixed vector against document vectors and
    produce numbers not comparable to those bands (the design's "prefix
    trap"). `extract._best_match` is this function's degenerate k=1 case
    (S6, not wired here). `k=None` returns the FULL ranked list - the
    document-cosine flag is evaluated over the WHOLE KB (D18 S4.1), not a
    top-K pool, since the brute-force scan is whole-KB regardless and a
    deep-K cutoff would silently reintroduce failure mode 1 for the semantic
    signal. Pass a precomputed `vec` (already embedded, `search_document:`
    prefixed) to skip embedding - a dedup batch embeds once and reuses it.

    `model`/`digest` (gate finding 3) identify which model actually produced
    `vec`/`text`'s embedding - default to the CURRENT `config.embed_model()`
    so a caller that never passed one still gets checked against whatever
    model is configured NOW. Checked against the index's stamped
    `vector_meta` via `check_meta` BEFORE scanning: two same-dimension
    embedding spaces from different models are numerically incomparable, and
    a dims-only check (the pre-fix behavior) let that through silently."""
    con = connect(root) if db_path(root).exists() else None
    try:
        query_model = model or config.embed_model()
        if vec is None:
            qvec = _embed_query(
                config.ollama_base_url(), query_model,
                "search_document: " + (text or ""),
                timeout if timeout is not None else query_timeout(),
            )
        else:
            qvec = vec
        meta = require_built(root, con)
        if meta is None:
            return []
        assert con is not None  # require_built returns None when there is no index
        check_meta(meta, query_model, len(qvec), "document-cosine scan refused", digest=digest)
        rows = fresh_vector_rows(con, len(qvec), stale_out, current)   # stale vectors never scored (S6 slice A)
    finally:
        if con is not None:
            con.close()
    return _scan_rows(rows, qvec, k)
