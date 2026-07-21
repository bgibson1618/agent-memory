"""F7 - concurrent-session write safety.

Proof for FEATURES.md F7: N parallel `mem save` processes (N >= 8, distinct
slugs) all land - every process exits 0, N files exist, N commits land, and
no invocation trips over git's index.lock or SQLite's "database is locked".
Same-slug contention resolves per the collision rule: exactly one
non-`--update` writer wins and the rest error cleanly in one line;
`--update` writers all serialize with no interleaved or corrupt file.

The test holds the KB's own inter-process write lock while spawning the
contenders, then releases it - so every process is provably queued on the
lock at once (a real race, not just processes launched close together).
"""

import fcntl
import json
import subprocess
import sys
import time
from contextlib import contextmanager

import yaml

LOCK_ERROR_MARKERS = ("index.lock", "database is locked", "Traceback")


def commit_subjects(kb) -> list:
    return subprocess.run(
        ["git", "-C", str(kb.kb), "log", "--format=%s"],
        capture_output=True, text=True, env=kb.env, check=True,
    ).stdout.strip().splitlines()


def spawn_save(kb, *args) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "agent_memory", "save", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=kb.env,
    )


@contextmanager
def held_write_lock(kb):
    """Hold the KB's write lock (the same flock `mem save` takes) so spawned
    savers pile up behind it; releasing starts the race for real."""
    lock_path = kb.kb / ".index" / "write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def run_racing(kb, arg_sets) -> list:
    """Spawn one `mem save` per arg set while the write lock is held, release,
    and return (returncode, stdout, stderr) per process."""
    with held_write_lock(kb):
        procs = [spawn_save(kb, *args) for args in arg_sets]
        time.sleep(2.5)  # let every process boot and block on the lock
    results = []
    for proc in procs:
        out, err = proc.communicate(timeout=60)
        results.append((proc.returncode, out, err))
    return results


def assert_no_lock_errors(results) -> None:
    for _, out, err in results:
        blob = out + err
        for marker in LOCK_ERROR_MARKERS:
            assert marker not in blob, blob


def test_parallel_distinct_slug_saves_all_land(mem, kb):
    assert mem("init").returncode == 0
    baseline = commit_subjects(kb)

    n = 10
    arg_sets = [
        ("--title", f"Concurrent Concept {i:02d}",
         "--body", f"Writer {i:02d} landing under contention.\n",
         "--topics", "concurrency")
        for i in range(n)
    ]
    results = run_racing(kb, arg_sets)

    assert [code for code, _, _ in results] == [0] * n, results
    assert_no_lock_errors(results)

    files = sorted(p.name for p in (kb.kb / "concepts").glob("*.md"))
    assert files == [f"concurrent-concept-{i:02d}.md" for i in range(n)]
    assert list((kb.kb / "concepts").glob(".*.tmp")) == []  # no temp debris

    subjects = commit_subjects(kb)
    assert len(subjects) == len(baseline) + n
    assert set(subjects) - set(baseline) == {
        f"mem save: concurrent-concept-{i:02d}" for i in range(n)
    }

    # every file parses as valid OKF - list round-trips all N
    listed = json.loads(mem("list", "--json").stdout)
    assert {item["slug"] for item in listed} == {
        f"concurrent-concept-{i:02d}" for i in range(n)
    }


def test_same_slug_race_has_exactly_one_winner(mem, kb):
    assert mem("init").returncode == 0
    baseline = commit_subjects(kb)

    n = 8
    bodies = [f"Writer {i} took the contested slug: marker-{i}.\n" for i in range(n)]
    results = run_racing(kb, [("--title", "Contested Save", "--body", b) for b in bodies])

    assert_no_lock_errors(results)
    winners = [r for r in results if r[0] == 0]
    losers = [r for r in results if r[0] != 0]
    assert len(winners) == 1 and len(losers) == n - 1, results
    for _, _, err in losers:
        lines = err.strip().splitlines()
        assert len(lines) == 1 and "--update" in lines[0], err

    text = (kb.kb / "concepts" / "contested-save.md").read_text(encoding="utf-8")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["slug"] == "contested-save"

    data = json.loads(mem("get", "contested-save", "--json").stdout)
    markers = [i for i in range(n) if f"marker-{i}." in data["body"]]
    assert len(markers) == 1  # exactly one writer's body, whole and un-interleaved
    assert data["body"].strip() == bodies[markers[0]].strip()

    subjects = commit_subjects(kb)
    assert len(subjects) == len(baseline) + 1
    assert subjects[0] == "mem save: contested-save"


def test_parallel_updates_serialize_without_corruption(mem, kb):
    assert mem("init").returncode == 0
    seed = mem("save", "--title", "Contested Update", "--body", "Seed body.\n")
    assert seed.returncode == 0, seed.stderr
    created = json.loads(mem("get", "contested-update", "--json").stdout)["created"]
    baseline = commit_subjects(kb)

    n = 8
    bodies = [f"Revision from writer {i}: marker-{i}.\n" for i in range(n)]
    results = run_racing(
        kb, [("--title", "Contested Update", "--body", b, "--update") for b in bodies]
    )

    assert [code for code, _, _ in results] == [0] * n, results
    assert_no_lock_errors(results)

    data = json.loads(mem("get", "contested-update", "--json").stdout)
    assert data["created"] == created
    markers = [i for i in range(n) if f"marker-{i}." in data["body"]]
    assert len(markers) == 1  # the last writer's body, whole and un-interleaved
    assert data["body"].strip() == bodies[markers[0]].strip()

    # distinct bodies mean every serialized update lands its own commit
    subjects = commit_subjects(kb)
    assert len(subjects) == len(baseline) + n
    assert set(subjects[:n]) == {"mem update: contested-update"}
