"""Shared SQLite bootstrap for the derived indexes.

Both legs (lexical FTS5, vector) live in ONE file - `.index/mem.db` - under
one connection discipline (WAL + busy timeout). This seam exists so the two
modules cannot drift apart on the file name or the pragmas (D12 quality nit);
schema creation stays with each leg.
"""

import sqlite3
from pathlib import Path

DB_NAME = "mem.db"


def db_path(root: Path) -> Path:
    return root / ".index" / DB_NAME


def connect(root: Path, *, autocommit: bool = False) -> sqlite3.Connection:
    """WAL + 5s busy timeout; `autocommit=True` is the lexical leg's
    isolation_level=None mode, the vector leg commits explicitly."""
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5.0,
                          isolation_level=None if autocommit else "")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con
