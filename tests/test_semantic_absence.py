"""Stage 2 (2026-11) regressions the acceptance reviewer asked for by name:
the semantic leg's structural refusals in `vector.require_built` and the one
warning line they produce, each pinned beside a valid-empty control so the
warning fires only when there is something to know and nothing built.

Unit level (require_built on a disposable root):
  - no concepts: a missing database, an unstamped index and a stamped index
    with no vectors all stay quiet;
  - concepts present: missing database and unstamped index say "not built";
    a stamped index with zero stored vectors says how many are pending; one
    stored vector is a built index.

CLI level (`mem search` in an isolated KB, fake loopback daemon):
  - daemon up, saves queued while it was down (index never stamped): exactly
    one "semantic leg skipped (vector index not built ...)" line and the JSON
    array intact;
  - daemon up, a stamped index emptied under it (what an interrupted reindex
    leaves): the pending-count wording;
  - daemon down on the same unbuilt KB: the warning names the daemon, never
    a reindex (daemon-error precedence);
  - valid-empty controls: an initialised KB with no concepts, and a built
    index whose query embedding has zero norm, return an empty result with
    no warning at all.
"""

import json
import sqlite3

import pytest

from agent_memory import indexdb, vector

NOT_BUILT = "warning: semantic leg skipped (vector index not built - run: mem reindex)"


# ------------------------------------------------------------- unit ----

@pytest.fixture
def root(tmp_path):
    kb = tmp_path / "kb"
    (kb / "concepts").mkdir(parents=True)
    (kb / ".index").mkdir()
    return kb


def _concept(root, slug="one"):
    (root / "concepts" / f"{slug}.md").write_text("---\nslug: one\n---\nsynthetic\n")


def _stamp(con, dims=4):
    vector._stamp_meta(con, "fake-model", "unknown", dims)
    con.commit()


def test_require_built_stays_quiet_without_concepts(root):
    assert vector.require_built(root, None) is None            # no database
    con = vector.connect(root)
    try:
        assert vector.require_built(root, con) is None         # tables, never stamped
        _stamp(con)
        assert vector.require_built(root, con)["model"] == "fake-model"  # stamped, empty
    finally:
        con.close()


def test_require_built_names_each_structural_absence_with_concepts(root):
    _concept(root)
    with pytest.raises(vector.VectorError, match=r"^vector index not built - run: mem reindex$"):
        vector.require_built(root, None)
    con = vector.connect(root)
    try:
        with pytest.raises(vector.VectorError, match=r"^vector index not built - run: mem reindex$"):
            vector.require_built(root, con)
        _stamp(con)
        vector.enqueue(con, "one")
        vector.enqueue(con, "two")
        con.commit()
        with pytest.raises(vector.VectorError,
                           match=r"^no embeddings stored yet \(2 pending\) - run: mem reindex$"):
            vector.require_built(root, con)
        con.execute(
            "INSERT INTO vectors(slug, model, dims, content_hash, vec, updated)"
            " VALUES('one', 'fake-model', 4, 'h', X'00000000000000000000000000000000', 't')"
        )
        con.commit()
        assert vector.require_built(root, con)["dims"] == "4"  # one vector: built
    finally:
        con.close()


# -------------------------------------------------------------- cli ----

CONCEPTS = [
    ("Spaced Repetition Scheduling", "Reviews at increasing intervals beat massed practice.\n"),
    ("Quaternion Rotation", "A quaternion encodes 3D rotation without gimbal lock.\n"),
]


def seed(mem, env_extra=None) -> None:
    assert mem("init").returncode == 0
    for title, body in CONCEPTS:
        result = mem("save", "--title", title, "--body", body, env_extra=env_extra)
        assert result.returncode == 0, result.stderr


def warnings_of(result) -> list:
    return [line for line in result.stderr.splitlines() if line.startswith("warning:")]


def test_unbuilt_index_with_daemon_up_warns_once_and_keeps_the_json_array(mem, kb, fake_ollama):
    seed(mem)                                   # daemon down: every save queues, nothing stamped
    result = mem("search", "quaternion", "--json", env_extra={"MEM_OLLAMA_URL": fake_ollama.url})
    assert result.returncode == 0, result.stderr
    hits = json.loads(result.stdout)            # the lexical answer still arrives as a JSON array
    assert hits and hits[0]["slug"] == "quaternion-rotation"
    assert warnings_of(result) == [NOT_BUILT], result.stderr


def test_emptied_stamped_index_reports_the_pending_count(mem, kb, fake_ollama):
    up = {"MEM_OLLAMA_URL": fake_ollama.url}
    seed(mem, env_extra=up)                     # daemon up: stamped, two vectors stored
    con = sqlite3.connect(indexdb.db_path(kb.kb))
    with con:                                   # the state an interrupted reindex leaves behind
        con.execute("DELETE FROM vectors")
        for slug in ("spaced-repetition-scheduling", "quaternion-rotation"):
            con.execute("INSERT OR IGNORE INTO embed_queue(slug, enqueued) VALUES(?, 't')", (slug,))
    con.close()
    result = mem("search", "quaternion", env_extra=up)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("quaternion-rotation  ")
    assert warnings_of(result) == [
        "warning: semantic leg skipped (no embeddings stored yet (2 pending) - run: mem reindex)"
    ], result.stderr


def test_daemon_error_takes_precedence_over_structural_absence(mem, kb):
    seed(mem)                                   # unbuilt AND the daemon is down
    result = mem("search", "quaternion", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)[0]["slug"] == "quaternion-rotation"
    [warning] = warnings_of(result)
    assert warning.startswith("warning: semantic leg skipped (embed request to http://127.0.0.1:"), warning
    assert "reindex" not in warning and "not built" not in warning


def test_empty_kb_with_daemon_up_returns_nothing_and_says_nothing(mem, kb, fake_ollama):
    assert mem("init").returncode == 0          # concepts/ exists and is empty
    up = {"MEM_OLLAMA_URL": fake_ollama.url}
    as_json = mem("search", "anything", "--json", env_extra=up)
    assert as_json.returncode == 0 and json.loads(as_json.stdout) == [], as_json.stderr
    assert as_json.stderr.strip().splitlines() == ["no matches: anything"]
    text = mem("search", "anything", env_extra=up)
    assert text.returncode == 0 and text.stdout.strip() == "no matches: anything"
    assert text.stderr == ""


def test_zero_norm_query_on_a_built_index_is_a_valid_empty_result(mem, kb, fake_ollama_factory):
    zero = fake_ollama_factory(embed_fn=lambda text, dims: [0.0] * dims)
    up = {"MEM_OLLAMA_URL": zero.url}
    seed(mem, env_extra=up)                     # stamped index, vectors stored (all zero norm)
    result = mem("search", "xyzzyplugh", "--json", env_extra=up)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
    assert result.stderr.strip().splitlines() == ["no matches: xyzzyplugh"]
