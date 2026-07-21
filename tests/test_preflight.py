"""Environment smoke tests — the preflight floor the build stands on.

These assert the environment contract from ARCHITECTURE.md holds on this host;
feature tests land beside them as the build proceeds.
"""

import sqlite3
import sys


def test_python_meets_floor():
    assert sys.version_info >= (3, 12)


def test_sqlite_fts5_available():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(content)")
    con.execute("INSERT INTO t VALUES ('hello knowledge base')")
    rows = con.execute("SELECT content FROM t WHERE t MATCH 'knowledge'").fetchall()
    assert rows == [("hello knowledge base",)]
