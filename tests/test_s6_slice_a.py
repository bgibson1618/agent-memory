"""D18 S6 slice A - decide on current files (D29; BACKLOG "D18 S6, slice A").

Acceptance examples from the 2026-11-19 scoping plan (E2's dedup half, E7-E10, E12's no-traceback half) plus three
checks the slice adds: search never scores a stale vector, extract refuses when a changed card cannot be embedded, and the
current-text hash rebuilt from the lexical index equals `embed_text`'s. Synthetic KBs only; a deterministic hashed
bag-of-words fake embedder (identical texts -> cosine 1.0, disjoint vocabularies -> ~0)."""
import hashlib
import json
import multiprocessing as mp
import re
import sqlite3
import subprocess
import sys
import threading

import pytest
from fakes import FakeOllamaServer

from agent_memory import indexdb, lexical, okf, vector

DIMS, MODEL, DIGEST = 256, "nomic-embed-text:v1.5", "sha256:5a5a5a5a"
STOP = {"search", "document", "query", "the", "and", "for", "that", "this", "with", "are",
        "from", "its", "into", "not", "but", "can", "when", "than", "then", "has"}
MARKER = "unembeddable"

OLD = "Docker image layers are cached; order instructions so rarely changing steps come first."
NEW = ("Python str.splitlines treats U+2028 and U+2029 as line boundaries, so splitting JSON Lines "
       "text with splitlines breaks records whose strings contain those characters.")


def words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP}


def bow(text, dims):
    if MARKER in text:
        raise RuntimeError("fake embedder: refuses this text")
    v = [0.0] * dims
    for w in words(text):
        v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % dims] += 1.0
    if not any(v):
        v[0] = 1.0
    return v


@pytest.fixture
def ollama():
    srv = FakeOllamaServer(dims=DIMS, model=MODEL, embed_fn=bow, digest=DIGEST)
    yield srv
    srv.stop()


def setup(mem, ollama):
    env = {"MEM_OLLAMA_URL": ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    return env


def save(mem, env, title, body):
    r = mem("save", "--title", title, "--body", body, env_extra=env)
    assert r.returncode == 0, r.stderr
    return re.search(r"saved: (\S+)", r.stdout).group(1)


def concept_file(kb, slug):
    return kb.kb / "concepts" / f"{slug}.md"


def rewrite_body(path, body):
    front, _old = path.read_text(encoding="utf-8").split("\n---\n", 1)
    path.write_text(front + "\n---\n\n" + body + "\n", encoding="utf-8")


def rewrite_card(path, title, body):
    """Hand-edit title, description and body (shares no vocabulary with the old card)."""
    front, _old = path.read_text(encoding="utf-8").split("\n---\n", 1)
    front = re.sub(r"(?m)^title: .*$", f"title: {title}", front)
    front = re.sub(r"(?m)^description: .*$", f"description: {title}", front)
    path.write_text(front + "\n---\n\n" + body + "\n", encoding="utf-8")


def add_external(kb, template_slug, slug, title, body):
    front, _ = concept_file(kb, template_slug).read_text(encoding="utf-8").split("\n---\n", 1)
    front = re.sub(r"(?m)^title: .*$", f"title: {title}", front)
    front = re.sub(r"(?m)^description: .*$", f"description: {title}", front)
    concept_file(kb, slug).write_text(front + "\n---\n\n" + body + "\n", encoding="utf-8")


def run_extract(mem, env, kb, cands, tag="c"):
    f = kb.home / f"{tag}.json"
    f.write_text(json.dumps(cands), encoding="utf-8")
    return mem("extract", "--candidates", str(f), "--json", env_extra=env)


def run_dedup(mem, env, kb, cands, tag="d"):
    f = kb.home / f"{tag}.json"
    f.write_text(json.dumps(cands), encoding="utf-8")
    r = mem("dedup", str(f), "--json", "--no-log", env_extra=env)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["candidates"][0]


# --- externally edited concepts ------------------------------------------------------------------------------------

def test_E7_extract_sees_a_card_edited_by_hand(mem, kb, ollama):
    env = setup(mem, ollama)
    a = save(mem, env, "Cache layer ordering", OLD)
    rewrite_body(concept_file(kb, a), NEW)                      # edited outside mem; no other command runs first
    r = run_extract(mem, env, kb, [{"title": "splitlines and JSON Lines", "body": NEW}])
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)["results"][0]
    assert res["disposition"].startswith("skipped-duplicate") and res["match"] == a, res


def test_E8_extract_sees_a_card_added_by_hand(mem, kb, ollama):
    env = setup(mem, ollama)
    seed = save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    add_external(kb, seed, "splitlines-jsonl", "splitlines and JSON Lines", NEW)
    r = run_extract(mem, env, kb, [{"title": "Line boundaries in JSON Lines", "body": NEW}])
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout)["results"][0]
    assert res["disposition"].startswith("skipped-duplicate") and res["match"] == "splitlines-jsonl", res


def test_E9_dedup_ignores_a_stale_vector_and_says_so(mem, kb, ollama):
    env = setup(mem, ollama)
    a = save(mem, env, "Cache layer ordering", OLD)
    rewrite_body(concept_file(kb, a), NEW)
    c = run_dedup(mem, env, kb, [{"title": "Docker cache", "body": OLD}])   # matches only the OLD text
    assert not any(f["signal"] == "cosine_document_max" and f["against"] == a for f in c["flag_reasons"]), c["flag_reasons"]
    assert c["verdict"] == "novel", c["verdict"]
    assert any("stale" in n and a in n for n in c["notes"]), c["notes"]


def test_E9_chunk_leg_ignores_stale_chunks_of_a_card_outside_the_refresh_seeds(mem, kb, ollama):
    # Review s6a-review-1 finding 1: the opt-in chunk leg refreshed only its seeds (lexical and fresh-vector hits),
    # then scored every stored chunk row. After a hand edit sharing no words with the candidate, the edited card is
    # neither a lexical hit nor a fresh-vector hit: an intervening search with the embedding daemon down consumes the
    # lexical change-set and leaves its vector stale (mem dedup does not drain before deciding).
    env = {**setup(mem, ollama), "MEM_DEDUP_CHUNKS": "1"}
    a = save(mem, env, "Cache layer ordering", OLD)
    save(mem, env, "Docker layers", "Docker layers rebuild slowly when instructions change.")
    warm = run_dedup(mem, env, kb, [{"title": "Docker cache", "body": OLD}], "warm")      # a is a seed: chunks stored
    assert any(h["slug"] == a and h["cosine_best_chunk"] is not None for h in warm["hits"]), warm["hits"]
    unrelated = NEW.replace(", so splitting", "; splitting")    # no token in common with OLD, so not a lexical hit
    assert not words(unrelated) & words(OLD) and "so" not in re.findall(r"\w+", unrelated.lower())
    rewrite_card(concept_file(kb, a), "splitlines and JSON Lines", unrelated)
    assert mem("search", "anything at all", "--json").returncode == 0                      # daemon down (fixture default)
    c = run_dedup(mem, env, kb, [{"title": "Docker cache", "body": OLD}], "after")
    assert a not in [h["slug"] for h in c["hits"]], [(h["slug"], h["legs"], h["cosine_best_chunk"]) for h in c["hits"]]
    assert not any(f.get("against") == a for f in c["flag_reasons"]), c["flag_reasons"]
    assert any("vector_chunk" in n and "stale" in n and a in n for n in c["notes"]), c["notes"]


def test_E10_extract_reports_an_unparseable_card_by_name_and_continues(mem, kb, ollama):
    env = setup(mem, ollama)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    broken = kb.kb / "concepts" / "hand-broken.md"
    broken.write_text("---\ntitle: [unclosed\n---\n\nbody\n", encoding="utf-8")
    r = run_extract(mem, env, kb, [{"title": "Golf hotel india", "body": "Juliet kilo lima mike november oscar."}])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["results"][0]["disposition"] == "added", out
    assert out["unparseable"] == ["hand-broken.md"], out


def test_extract_refuses_when_a_changed_card_cannot_be_embedded(mem, kb, ollama):
    env = setup(mem, ollama)
    a = save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    rewrite_body(concept_file(kb, a), f"Self-testing beats restudying; {MARKER} marker text.")
    before = sorted(p.name for p in (kb.kb / "concepts").glob("*.md"))
    r = run_extract(mem, env, kb, [{"title": "Golf hotel india", "body": "Juliet kilo lima mike november oscar."}])
    assert r.returncode != 0
    assert "could not be embedded" in r.stderr, r.stderr
    assert sorted(p.name for p in (kb.kb / "concepts").glob("*.md")) == before    # nothing written


def test_search_never_scores_a_stale_vector(mem, kb, ollama):
    env = setup(mem, ollama)
    a = save(mem, env, "Cache layer ordering", OLD)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    rewrite_body(concept_file(kb, a), NEW)
    r = mem("search", "docker image instructions rarely changing steps", "--json", env_extra=env)
    assert r.returncode == 0, r.stderr
    hits = {h["slug"]: h for h in json.loads(r.stdout)}
    assert "semantic_similarity" not in hits.get(a, {}), hits.get(a)


# --- candidate identity ----------------------------------------------------------------------------------------------

def test_E2_dedup_does_not_hide_an_existing_card_that_has_the_candidates_slug(mem, kb, ollama):
    env = setup(mem, ollama)
    a = save(mem, env, "Cache layer ordering", OLD)
    same = run_dedup(mem, env, kb, [{"title": "Cache layer ordering", "body": OLD}], "same")   # same title -> same slug
    assert a in [h["slug"] for h in same["hits"]], same["hits"]
    assert same["verdict"] != "novel" and same["recommended_action"] == "skip", (same["verdict"], same["recommended_action"])
    other = run_dedup(mem, env, kb, [{"title": "Docker build cache", "body": OLD}], "other")
    assert other["verdict"] != "novel" and other["recommended_action"] == "skip"


def test_save_dedup_check_still_excludes_the_card_it_just_saved(mem, kb, ollama):
    env = setup(mem, ollama)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    r = mem("save", "--title", "Golf hotel india", "--body", "Juliet kilo lima mike november oscar.", "--dedup-check",
            env_extra=env)
    assert r.returncode == 0, r.stderr
    assert "dedup-check: verdict=novel" in r.stderr, r.stderr


# --- current-text hashes ---------------------------------------------------------------------------------------------

def test_current_embed_hashes_equal_embed_text_hashes(tmp_path):
    root = tmp_path / "kb"
    (root / "concepts").mkdir(parents=True)
    meta = {"type": "concept", "sensitivity": "normal", "created": "2026-11-20T00:00:00Z", "updated": "2026-11-20T00:00:00Z"}
    concepts = [
        okf.Concept(slug="a", title="Alpha", description="first", topics=["x-y", "zeta"], body="Body one.", **meta),
        okf.Concept(slug="b", title="Beta", description="second", topics=[], body="  Body two, padded.  ", **meta),
        okf.Concept(slug="c", title="Gamma", description="third", topics=["solo"], body="Long " * 2000, **meta),
    ]
    for c in concepts:
        (root / "concepts" / f"{c.slug}.md").write_text(okf.serialize(c), encoding="utf-8")
    con = lexical.connect(root)
    try:
        lexical.sync(con, root)
        got = vector.current_embed_hashes(con)
    finally:
        con.close()
    want = {c.slug: vector.content_hash(vector.embed_text(okf.parse((root / "concepts" / f"{c.slug}.md").read_text())))
            for c in concepts}
    assert got == want


def test_current_embed_hashes_propagates_errors_other_than_a_missing_table(tmp_path):
    # Review s6a-review-1 finding 3: only "no lexical table" may mean "freshness unknown"; a lock or query failure
    # must not silently turn freshness checking off.
    con = sqlite3.connect(tmp_path / "empty.db")
    try:
        assert vector.current_embed_hashes(con) is None
    finally:
        con.close()

    class Locked:
        def execute(self, *_a):
            raise sqlite3.OperationalError("database is locked")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        vector.current_embed_hashes(Locked())


def damage_lexical_index(kb):
    """Drop the FTS5 table's backing content table: `lexical` still exists, but reading it fails."""
    con = sqlite3.connect(indexdb.db_path(kb.kb))
    try:
        con.execute("DROP TABLE lexical_content")
        con.commit()
    finally:
        con.close()


def test_current_embed_hashes_propagates_a_damaged_lexical_index(tmp_path):
    # Review s6a-review-2: "no such table" alone is not "never synced" - a damaged FTS5 index reports it too.
    root = tmp_path / "kb"
    (root / "concepts").mkdir(parents=True)
    con = lexical.connect(root)
    try:
        con.execute("DROP TABLE lexical_content")
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            vector.current_embed_hashes(con)
    finally:
        con.close()


def test_extract_refuses_on_a_damaged_lexical_index_and_saves_nothing(mem, kb, ollama):
    env = setup(mem, ollama)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    damage_lexical_index(kb)
    before = sorted(p.name for p in (kb.kb / "concepts").glob("*.md"))
    r = run_extract(mem, env, kb, [{"title": "Golf hotel india", "body": "Juliet kilo lima mike november oscar."}])
    assert r.returncode != 0 and "lexical_content" in r.stderr, (r.returncode, r.stderr[-400:])
    assert sorted(p.name for p in (kb.kb / "concepts").glob("*.md")) == before


def test_save_dedup_check_skips_on_a_damaged_lexical_index_without_failing_the_save(mem, kb, ollama):
    # Review s6a-review-2 should-fix: the advisory runs after the save committed, so index trouble is a skip note.
    env = setup(mem, ollama)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    damage_lexical_index(kb)
    r = mem("save", "--title", "Golf hotel india", "--body", "Juliet kilo lima mike november oscar.", "--dedup-check",
            env_extra=env)
    assert r.returncode == 0, r.stderr[-600:]
    assert "dedup-check: skipped" in r.stderr and "Traceback" not in r.stderr, r.stderr[-600:]
    assert concept_file(kb, "golf-hotel-india").is_file()


# --- concurrent start (E12's no-traceback half) ----------------------------------------------------------------------

def _connect_worker(root, barrier, q):
    barrier.wait()
    try:
        indexdb.connect(root).close()
        q.put("ok")
    except sqlite3.OperationalError as e:
        q.put(f"OperationalError: {e}")


def test_E12_concurrent_first_connections_never_fail_with_database_is_locked(tmp_path):
    ctx = mp.get_context("fork")
    outcomes = []
    for r in range(20):
        root = tmp_path / f"r{r:02d}"
        root.mkdir()
        barrier, q = ctx.Barrier(4), ctx.Queue()
        ps = [ctx.Process(target=_connect_worker, args=(root, barrier, q)) for _ in range(4)]
        [p.start() for p in ps]
        [p.join(30) for p in ps]
        outcomes += [q.get(timeout=5) for _ in ps]
    assert outcomes == ["ok"] * 80, sorted(set(outcomes))


def test_E12_two_concurrent_extracts_produce_no_traceback(mem, kb):
    srv = FakeOllamaServer(dims=DIMS, model=MODEL, embed_fn=bow, digest=DIGEST, load_delay=1.0)
    try:
        env = {"MEM_OLLAMA_URL": srv.url}
        assert mem("init", env_extra=env).returncode == 0
        cand = [{"title": "splitlines and JSON Lines", "body": NEW}]
        out = {}

        def run(tag):
            out[tag] = run_extract(mem, env, kb, cand, tag)
        ts = [threading.Thread(target=run, args=(t,)) for t in ("p1", "p2")]
        [t.start() for t in ts]
        [t.join() for t in ts]
        for t in ("p1", "p2"):
            assert "Traceback" not in out[t].stderr and "database is locked" not in out[t].stderr, out[t].stderr
    finally:
        srv.stop()


# Review s6a-review-1 finding 2: when the WAL switch stays impossible (another process holds the database exclusively),
# the command ends with one actionable line, no traceback and no save. The driver shortens the waits so the test is fast.
_SHORT_WAITS = ("import sys; from agent_memory import indexdb, cli; "
                "indexdb.BUSY_TIMEOUT_S = 0.05; indexdb.WAL_SWITCH_BUDGET = 0.3; "
                "sys.exit(cli.main(sys.argv[1:]))")


@pytest.mark.parametrize("command", ["extract", "dedup"])
def test_E12_wal_switch_exhaustion_is_a_one_line_error_and_saves_nothing(mem, kb, ollama, command):
    env = setup(mem, ollama)
    save(mem, env, "Retrieval practice", "Self-testing beats restudying for delayed retention.")
    f = kb.home / "c.json"
    f.write_text(json.dumps([{"title": "Golf hotel india", "body": "Juliet kilo lima mike november oscar."}]),
                 encoding="utf-8")
    argv = (["extract", "--candidates", str(f), "--json"] if command == "extract"
            else ["dedup", str(f), "--json", "--no-log"])
    before = sorted(p.name for p in (kb.kb / "concepts").glob("*.md"))
    holder = sqlite3.connect(indexdb.db_path(kb.kb), isolation_level=None)
    try:
        assert holder.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        holder.execute("BEGIN EXCLUSIVE")
        r = subprocess.run([sys.executable, "-c", _SHORT_WAITS, *argv], env={**kb.env, **env},
                           capture_output=True, text=True, timeout=60)
    finally:
        holder.close()
    lines = r.stderr.strip().splitlines()
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert len(lines) == 1 and lines[0].startswith("error: ") and "WAL" in lines[0], r.stderr
    assert sorted(p.name for p in (kb.kb / "concepts").glob("*.md")) == before
