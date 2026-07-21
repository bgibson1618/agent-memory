"""F3 - keyword search.

Proof for FEATURES.md F3: with Ollama entirely absent (the kb fixture points
MEM_OLLAMA_URL at a closed loopback port), `mem search "<literal terms>"`
returns the matching concept in the top results, BM25-ranked, in text and
--json forms; every hit carries slug/title/score/snippet; empty result sets
exit 0 with an empty list and one quiet line.
"""

import json

CONCEPTS = [
    {
        "title": "Spaced Repetition Scheduling",
        "topics": "learning, memory",
        "body": (
            "Spaced repetition schedules reviews at increasing intervals.\n\n"
            "Each successful recall pushes the next review further out, so\n"
            "spaced repetition beats massed practice for retention.\n"
        ),
    },
    {
        "title": "Quaternion Rotation",
        "topics": "math, graphics",
        "body": (
            "A quaternion encodes 3D rotation without gimbal lock.\n\n"
            "Composing quaternion products chains rotations; normalizing the\n"
            "quaternion keeps it on the unit sphere.\n"
        ),
    },
    {
        "title": "Sourdough Starter Care",
        "topics": "baking",
        "body": (
            "Feed a sourdough starter daily at room temperature.\n\n"
            "A neglected starter smells of acetone and needs several feedings\n"
            "to revive before it can leaven bread again.\n"
        ),
    },
]


def seed(mem) -> None:
    assert mem("init").returncode == 0
    for concept in CONCEPTS:
        result = mem(
            "save", "--title", concept["title"],
            "--topics", concept["topics"], "--body", concept["body"],
        )
        assert result.returncode == 0, result.stderr


def search_json(mem, *args) -> list:
    result = mem("search", *args, "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_literal_terms_rank_matching_concept_with_ollama_absent(mem, kb):
    seed(mem)  # kb fixture: MEM_OLLAMA_URL -> closed port, i.e. daemon absent

    result = mem("search", "quaternion rotation")
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines and lines[0].startswith("quaternion-rotation  ")
    assert "Quaternion Rotation" in lines[0]
    assert result.stderr.strip() == ""  # no Ollama noise on the lexical path

    hits = search_json(mem, "sourdough starter")
    assert hits[0]["slug"] == "sourdough-starter-care"


def test_hits_carry_slug_title_score_snippet(mem, kb):
    seed(mem)
    hits = search_json(mem, "sourdough starter")
    top = hits[0]
    assert set(top) == {"slug", "title", "score", "snippet"}
    assert top["slug"] == "sourdough-starter-care"
    assert top["title"] == "Sourdough Starter Care"
    assert isinstance(top["score"], float) and top["score"] > 0
    assert any(term in top["snippet"].lower() for term in ("sourdough", "starter"))

    text = mem("search", "sourdough starter").stdout
    for field in (top["slug"], top["title"], top["snippet"]):
        assert field in text


def test_bm25_ranks_the_focused_concept_first(mem, kb):
    seed(mem)
    off_topic = (
        "Rotation matrices are 3x3 and orthogonal.\n\n"
        "They interpolate poorly compared to a quaternion, which is why\n"
        "animation pipelines convert at the last step. Euler angles are the\n"
        "third representation and suffer from gimbal lock in the middle axis.\n"
    )
    result = mem(
        "save", "--title", "Rotation Matrix Overview",
        "--topics", "math", "--body", off_topic,
    )
    assert result.returncode == 0, result.stderr
    # A fifth concept keeps "quaternion" a minority term - FTS5's BM25 IDF
    # floors near zero when a term appears in half the corpus, flattening scores.
    filler = mem(
        "save", "--title", "Euler Angles",
        "--topics", "math", "--body", "Three chained rotations about body axes.\n",
    )
    assert filler.returncode == 0, filler.stderr

    hits = search_json(mem, "quaternion")
    slugs = [hit["slug"] for hit in hits]
    assert slugs[0] == "quaternion-rotation"  # term-dense concept outranks the mention
    assert "rotation-matrix-overview" in slugs
    scores = [hit["score"] for hit in hits]
    assert scores == sorted(scores, reverse=True)  # ranked, best first


def test_extra_query_terms_still_recall_partial_matches(mem, kb):
    seed(mem)
    hits = search_json(mem, "spaced repetition flashcards anki")
    assert hits and hits[0]["slug"] == "spaced-repetition-scheduling"


def test_empty_result_exits_zero_with_empty_list_and_one_quiet_line(mem, kb):
    seed(mem)

    text = mem("search", "xyzzyplugh")
    assert text.returncode == 0
    assert text.stdout.strip().splitlines() == ["no matches: xyzzyplugh"]
    assert text.stderr.strip() == ""

    as_json = mem("search", "xyzzyplugh", "--json")
    assert as_json.returncode == 0
    assert json.loads(as_json.stdout) == []  # stdout stays machine-clean
    assert as_json.stderr.strip().splitlines() == ["no matches: xyzzyplugh"]


def test_operator_lookalike_queries_stay_literal(mem, kb):
    seed(mem)
    for query in ('starter AND "quotes" (parens) col:on', "NOT OR NEAR"):
        result = mem("search", query)
        assert result.returncode == 0, (query, result.stderr)


def test_new_and_updated_saves_are_immediately_searchable(mem, kb):
    seed(mem)
    assert search_json(mem, "quaternion")  # index exists before the next save

    result = mem(
        "save", "--title", "Interference Theory",
        "--topics", "memory", "--body", "Forgetting arises from interference.\n",
    )
    assert result.returncode == 0, result.stderr
    assert search_json(mem, "interference")[0]["slug"] == "interference-theory"

    update = mem(
        "save", "--title", "Interference Theory", "--update",
        "--topics", "memory", "--body", "Retroactive zymurgy overwrites older traces.\n",
    )
    assert update.returncode == 0, update.stderr
    assert search_json(mem, "zymurgy")[0]["slug"] == "interference-theory"


def test_index_self_heals_after_deletion(mem, kb):
    seed(mem)
    assert search_json(mem, "quaternion")
    (kb.kb / ".index" / "mem.db").unlink()  # the index is derived and disposable

    hits = search_json(mem, "quaternion")
    assert hits and hits[0]["slug"] == "quaternion-rotation"


def test_search_before_init_points_at_mem_init(mem, kb):
    result = mem("search", "anything")
    assert result.returncode != 0
    assert "mem init" in result.stderr
