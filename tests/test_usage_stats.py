"""Usage log + `mem stats` (DECISION_LOG D8).

The log is the one non-derived file in `.index/`: invocations append to
usage.jsonl, stats reads it back, and reindex must not clobber it.
"""

import json

BODY = "Usage-log probe body.\n"


def read_log(kb):
    p = kb.kb / ".index" / "usage.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_invocations_append_to_usage_log(kb, mem):
    mem("init")
    mem("save", "--title", "Usage probe", "--body", BODY)
    mem("search", "usage probe")
    mem("get", "usage-probe")
    log = read_log(kb)
    cmds = [e["cmd"] for e in log]
    assert cmds == ["save", "search", "get"]  # init is deliberately unlogged
    search = log[1]
    assert search["arg"] == "usage probe" and search["rc"] == 0
    assert isinstance(search["ms"], int) and search["ts"].endswith("Z")


def test_stats_reports_counts_by_command(kb, mem):
    mem("init")
    mem("save", "--title", "Stats probe", "--body", BODY)
    mem("search", "stats probe")
    mem("search", "stats probe again")
    proc = mem("stats", "--days", "1")
    assert proc.returncode == 0
    assert "search   2" in proc.stdout
    assert "save     1" in proc.stdout
    # stats itself is not logged (it would inflate its own numbers)
    assert all(e["cmd"] != "stats" for e in read_log(kb))


def test_reindex_preserves_usage_log(kb, mem):
    mem("init")
    mem("save", "--title", "Reindex probe", "--body", BODY)
    before = len(read_log(kb))
    assert before == 1
    proc = mem("reindex")
    assert proc.returncode == 0
    log = read_log(kb)
    assert len(log) == before + 1  # reindex itself is logged, nothing lost
    assert log[-1]["cmd"] == "reindex"
