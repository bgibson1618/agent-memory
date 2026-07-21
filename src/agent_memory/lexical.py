"""Lexical index - SQLite FTS5 over title/description/body/topics, BM25-ranked.

Lives in `.index/mem.db` (WAL + busy_timeout per ARCHITECTURE) and is fully
derived: markdown under concepts/ is the source of truth, so the index self-heals
by syncing against file mtimes on every search. Saves update it in-line under the
write lock; a failed index write never un-lands a committed save. No network -
this leg answers with Ollama entirely absent.
"""

import re
import sqlite3
import sys
from pathlib import Path

from agent_memory import okf

DB_NAME = "mem.db"

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
)


def db_path(root: Path) -> Path:
    return root / ".index" / DB_NAME


def connect(root: Path) -> sqlite3.Connection:
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
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
