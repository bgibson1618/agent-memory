"""Lexical index - SQLite FTS5 over title/description/body/topics, BM25-ranked.

Lives in `.index/mem.db` (WAL + busy_timeout per ARCHITECTURE) and is fully
derived: markdown under concepts/ is the source of truth, so the index self-heals
by syncing against file mtimes on every search. Saves update it in-line under the
write lock; a failed index write never un-lands a committed save. No network -
this leg answers with Ollama entirely absent.
"""

import math
import re
import sqlite3
import sys
from pathlib import Path

from agent_memory import indexdb, okf

# bm25() weights per column: slug (UNINDEXED, ignored), title, description, body, topics.
_BM25_WEIGHTS = "0.0, 4.0, 2.0, 1.0, 2.0"

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS lexical_files (
        slug TEXT PRIMARY KEY,
        mtime_ns INTEGER NOT NULL,
        size INTEGER NOT NULL
    )""",
    """CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(
        slug UNINDEXED, title, description, body, topics
    )""",
    # D18 S1: df/idf source for `dedup_match_expr` - zero storage, a live view
    # over `lexical`, never touched by sync() or any writer.
    """CREATE VIRTUAL TABLE IF NOT EXISTS lexical_vocab USING fts5vocab(lexical, 'row')""",
)


def db_path(root: Path) -> Path:
    return root / ".index" / DB_NAME


def connect(root: Path) -> sqlite3.Connection:
    conn = indexdb.connect(root, autocommit=True)
    for statement in _SCHEMA:
        conn.execute(statement)
    return conn


def _upsert(conn: sqlite3.Connection, slug: str, concept: okf.Concept, stat) -> None:
    conn.execute("DELETE FROM lexical WHERE slug = ?", (slug,))
    conn.execute(
        "INSERT INTO lexical (slug, title, description, body, topics) VALUES (?, ?, ?, ?, ?)",
        (slug, concept.title, concept.description, concept.body, " ".join(concept.topics)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO lexical_files (slug, mtime_ns, size) VALUES (?, ?, ?)",
        (slug, stat.st_mtime_ns, stat.st_size),
    )


def _remove(conn: sqlite3.Connection, slug: str) -> None:
    conn.execute("DELETE FROM lexical WHERE slug = ?", (slug,))
    conn.execute("DELETE FROM lexical_files WHERE slug = ?", (slug,))


def record_save(root: Path, concept: okf.Concept, path: Path) -> None:
    """In-line index update on the save path (caller holds the write lock).
    The commit has already landed; the index is disposable, so a failure here
    warns and lets sync() heal it on the next search instead of failing the save."""
    try:
        conn = connect(root)
        try:
            conn.execute("BEGIN IMMEDIATE")
            _upsert(conn, concept.slug, concept, path.stat())
            conn.execute("COMMIT")
        finally:
            conn.close()
    except sqlite3.Error as e:
        print(
            f"warning: lexical index update failed ({e}) - it will self-heal on the next search",
            file=sys.stderr,
        )


def sync(conn: sqlite3.Connection, root: Path) -> tuple:
    """Reconcile the index with concepts/*.md by mtime+size: index new/changed
    files, drop rows for deleted ones. Slugs are file stems - the same key
    `mem get` resolves. Unparseable files are skipped with a warning, like list.

    Returns the change-set as (changed, removed): changed is [(slug, Concept)]
    for files (re-)indexed this sync, removed is [slug] for rows dropped
    (deleted or unparseable files). The vector leg reconciles from exactly
    this change-set (F8), so external edits pay one stat-scan, not one
    parse-scan, per search."""
    known = dict(conn.execute("SELECT slug, mtime_ns || ':' || size FROM lexical_files"))
    to_upsert, seen = [], set()
    for path in sorted((root / "concepts").glob("*.md")):
        slug = path.stem
        seen.add(slug)
        stat = path.stat()
        if known.get(slug) == f"{stat.st_mtime_ns}:{stat.st_size}":
            continue
        to_upsert.append((slug, path, stat))
    to_delete = [slug for slug in known if slug not in seen]
    if not to_upsert and not to_delete:
        return [], []

    changed, removed = [], []
    conn.execute("BEGIN IMMEDIATE")
    try:
        for slug, path, stat in to_upsert:
            try:
                concept = okf.parse(path.read_text(encoding="utf-8"))
            except okf.OKFError as e:
                print(f"warning: skipping {path}: {e}", file=sys.stderr)
                _remove(conn, slug)
                removed.append(slug)
                continue
            _upsert(conn, slug, concept, stat)
            changed.append((slug, concept))
        for slug in to_delete:
            _remove(conn, slug)
            removed.append(slug)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return changed, removed


def match_expr(query: str) -> str:
    """Literal terms only: each token is quoted (so FTS5 operators stay literal)
    and OR-joined - BM25 ranks concepts matching more terms higher, and a query
    with extra words still recalls partial matches."""
    return " OR ".join(f'"{term}"' for term in re.findall(r"\w+", query))


def dedup_match_expr(conn: sqlite3.Connection, body: str, n: int = 24) -> str:
    """D18 S1 - a dedup-sized sibling of `match_expr`. `match_expr` quotes and
    OR-joins *every* token, so a 1,749-char candidate body becomes a ~250-term
    OR dominated by stopwords (FTS5's default tokenizer applies no stoplist).
    This instead takes the `n` highest-IDF *indexed* content terms from `body`
    and OR-joins those, quoted so FTS5 operators in the body stay literal.

    Terms are the *unstemmed* surface form found in `body` - they must match
    what FTS5 actually indexed (unicode61: lowercased, no stemming), unlike
    `claims.tokenize`'s stemmed coverage tokens. df comes from the
    `lexical_vocab` shadow table (fts5vocab 'row': `(term, doc, cnt)`, `doc` =
    document frequency); idf is the smoothed `log((N+1)/(df+1)) + 1`.

    D18 W1 fix cycle (gate finding 1): a term with df=0 (out-of-corpus, e.g.
    novel vocabulary in a candidate not yet saved) cannot retrieve any row -
    `WHERE lexical MATCH ?` would just drop it - so scoring it at the smoothed
    *maximum* idf let it crowd every retrievable term out of the top `n` and
    starve the query to zero recall. df=0 terms are therefore excluded before
    ranking; only terms this index can actually retrieve compete for the `n`
    slots. If a candidate is entirely novel vocabulary (no indexed term at
    all), there is nothing this leg could retrieve, and the result is "".

    `n` is clamped to `[1, 24]` (gate finding 7): this function exists
    specifically to bound the query to a small, safe term count, so an
    out-of-range `n` (too large, zero, or negative) is silently corrected
    rather than trusted - `n=100` still emits at most 24 terms, `n<=0` still
    emits at least 1.

    `conn` must come from `connect()` so `lexical_vocab` exists."""
    n = min(max(n, 1), 24)
    seen = []
    for term in re.findall(r"\w+", body.lower()):
        if term not in seen:
            seen.append(term)
    if not seen:
        return ""
    total_docs = conn.execute("SELECT COUNT(*) FROM lexical").fetchone()[0]
    placeholders = ",".join("?" * len(seen))
    rows = conn.execute(
        f"SELECT term, doc FROM lexical_vocab WHERE term IN ({placeholders})", seen
    ).fetchall()
    df = dict(rows)
    indexed = [t for t in seen if df.get(t, 0) > 0]  # df=0 terms can never retrieve - excluded, not ranked
    if not indexed:
        return ""

    def idf(term: str) -> float:
        return math.log((total_docs + 1) / (df[term] + 1)) + 1.0

    ranked = sorted(indexed, key=lambda t: -idf(t))  # stable sort: ties keep body order
    return " OR ".join(f'"{term}"' for term in ranked[:n])


def search(conn: sqlite3.Connection, query: str, limit: int) -> list:
    expr = match_expr(query)
    if not expr:
        return []
    rows = conn.execute(
        f"""SELECT slug, title,
                   bm25(lexical, {_BM25_WEIGHTS}) AS neg_score,
                   snippet(lexical, -1, '', '', '…', 12) AS snip
            FROM lexical WHERE lexical MATCH ?
            ORDER BY neg_score, slug LIMIT ?""",
        (expr, limit),
    ).fetchall()
    return [
        {"slug": slug, "title": title, "score": round(-neg, 3), "snippet": snip}
        for slug, title, neg, snip in rows
    ]
