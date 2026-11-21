"""Shared SQLite bootstrap for the derived indexes.

Both legs (lexical FTS5, vector) live in ONE file - `.index/mem.db` - under
one connection discipline (WAL + busy timeout). This seam exists so the two
modules cannot drift apart on the file name or the pragmas (D12 quality nit);
schema creation stays with each leg.
"""

import random
import sqlite3
import time
from pathlib import Path

DB_NAME = "mem.db"
BUSY_TIMEOUT_S = 5.0     # seconds a connection waits on another's lock
WAL_SWITCH_BUDGET = 5.0  # seconds; matches the busy timeout


class IndexBusyError(sqlite3.OperationalError):
    """The index could not be switched to WAL mode within the budget because
    another process kept it locked. The CLI turns this one case into a
    one-line error (S6 slice A); other SQLite errors stay distinguishable."""


def db_path(root: Path) -> Path:
    return root / ".index" / DB_NAME


def connect(root: Path, *, autocommit: bool = False) -> sqlite3.Connection:
    """WAL + 5s busy timeout; `autocommit=True` is the lexical leg's
    isolation_level=None mode, the vector leg commits explicitly."""
    path = db_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S,
                          isolation_level=None if autocommit else "")
    con.execute(f"PRAGMA busy_timeout={int(BUSY_TIMEOUT_S * 1000)}")
    try:
        _ensure_wal(con, path)
    except BaseException:
        con.close()
        raise
    return con


def _ensure_wal(con: sqlite3.Connection, path: Path) -> None:
    """Switch the database to WAL only if it is not already in WAL mode.

    Switching needs an exclusive lock. When two first connections to a fresh
    database both hold a shared lock and both ask to switch, SQLite answers
    "database is locked" at once instead of calling the busy handler (it would
    deadlock), so the 5 s busy timeout never applies (reproduced 2026-11-20:
    failures within 1 ms, none once the file is already WAL). The mode is
    persistent, so later connections only read it; a colliding switch retries
    with jittered backoff until another process has switched it or the budget
    runs out, which raises IndexBusyError naming the file."""
    deadline = time.monotonic() + WAL_SWITCH_BUDGET
    delay = 0.005
    while True:
        try:
            if str(con.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
                return
            mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() == "wal":
                return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e):
                raise
        if time.monotonic() >= deadline:
            raise IndexBusyError(
                f"database is locked: could not switch {path} to WAL within {WAL_SWITCH_BUDGET:g} s"
            )
        time.sleep(delay + random.uniform(0.0, delay))
        delay = min(delay * 2, 0.2)
