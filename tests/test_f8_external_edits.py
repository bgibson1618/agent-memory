"""F8 - external-edit resilience: editing the KB behind the CLI's back (in
Obsidian or any editor) never poisons search.

Direct edits are reflected lexically on the very next `mem search` and their
embedding refresh is enqueued automatically; the semantic refresh is proved,
not just queued - a meaning-flipping edit that shares zero words with its old
embed surface is recovered by a query matching the *new* meaning once the
queue drains, with no manual reindex. Files created or deleted directly on
disk appear/disappear on the next read with no ghost vector or queue rows.
`mem reindex` rebuilds the entire derived index (lexical FTS5 + graph cache +
vectors) from the markdown alone, byte-equivalently for unchanged content.

Reuses F4's deterministic synonym-class embedder (the capstone D020 pattern):
paraphrases land near each other while sharing zero literal terms, so the
vector leg's contribution is machine-distinguishable from the lexical leg's.
"""

import json
import shutil

from test_f4_semantic import (
    queue_slugs,
    semantic_ollama_factory,  # noqa: F401  (pytest fixture, found via this namespace)
    use_kb_env,
    vector_slugs,
    words_of,
)

from agent_memory import config, okf, vector

OLD_QUERY = "vehicle repairs"  # synonym classes: car + maintenance
NEW_QUERY = "dog training"     # synonym classes: dog + training


def write_concept(kb, slug, title, description, body, topics=()):
    """A file created/edited behind the CLI's back: valid OKF, written straight
    into concepts/ with no lock, no commit, no index update."""
    text = okf.serialize(
        okf.Concept(
            slug=slug,
            title=title,
            description=description,
            type="concept",
            topics=list(topics),
            sensitivity="normal",
            created="2026-07-21T00:00:00Z",
            updated="2026-07-21T00:00:00Z",
            body=body,
        )
    )
    (kb.kb / "concepts" / f"{slug}.md").write_text(text, encoding="utf-8")


def embed_surface_words(kb, slug) -> set:
    """The words of exactly what the vector leg embeds: title + description +
    topics + body (vector.embed_text's surface)."""
    concept = okf.parse((kb.kb / "concepts" / f"{slug}.md").read_text(encoding="utf-8"))
    return words_of(
        " ".join([concept.title, concept.description, " ".join(concept.topics), concept.body])
    )


def test_direct_edit_reflected_lexically_and_enqueued(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert (
        mem(
            "save", "--title", "Car care", "--body",
            "Regular servicing keeps an automobile dependable.",
            env_extra=env,
        ).returncode
        == 0
    )
    assert queue_slugs(kb) == set()  # embedded inline, daemon up
    assert vector_slugs(kb) == {"car-care"}

    # Behind the CLI's back: rewrite with a token the index has never seen.
    write_concept(
        kb, "car-care", "Car care", "torque specs",
        "Always check the torquewrench calibration first.",
    )

    # Daemon down (default kb env): the lexical leg still picks the edit up on
    # this very search, and the embedding refresh is enqueued automatically.
    result = mem("search", "torquewrench")
    assert result.returncode == 0, result.stderr
    assert "car-care" in result.stdout
    assert queue_slugs(kb) == {"car-care"}


def test_external_edit_semantic_refresh_no_manual_reindex(
    mem, kb, monkeypatch, semantic_ollama_factory
):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert (
        mem(
            "save", "--title", "Sedan upkeep", "--body",
            "Regular servicing keeps an automobile dependable for years.",
            env_extra=env,
        ).returncode
        == 0
    )
    assert (
        mem(
            "save", "--title", "Sourdough starter", "--body",
            "Levain proofing determines the crumb of the loaf.",
            env_extra=env,
        ).returncode
        == 0
    )
    assert queue_slugs(kb) == set()

    old_words = embed_surface_words(kb, "sedan-upkeep")

    # The concept's meaning flips to dog training behind the CLI's back; the
    # file keeps its slug (filename) but the new embed surface shares zero
    # words with the old one - machine-asserted below.
    write_concept(
        kb, "sedan-upkeep", "Hound heel work", "Puppy obedience notes",
        "Our canine practices heel with obedience commands daily.",
    )
    new_words = embed_surface_words(kb, "sedan-upkeep")
    assert old_words.isdisjoint(new_words)
    # ...and the new-meaning query shares no literal terms with the stored
    # file (frontmatter included), so only the vector leg can recover it.
    stored = (kb.kb / "concepts" / "sedan-upkeep.md").read_text(encoding="utf-8")
    assert words_of(NEW_QUERY).isdisjoint(words_of(stored))

    # Any ordinary search notices the edit and enqueues the re-embed; the
    # post-command drain (daemon up) replaces the stale vector immediately.
    result = mem("search", "anything", env_extra=env)
    assert result.returncode == 0, result.stderr
    assert queue_slugs(kb) == set()  # drained, not just queued

    use_kb_env(monkeypatch, kb, daemon.url)
    hits = vector.top_k(config.kb_root(), NEW_QUERY, k=2)
    assert hits and hits[0][0] == "sedan-upkeep", hits
    assert hits[0][1] > 0.5  # cosine: same two synonym classes
    # The old meaning no longer recalls it: the stale vector is gone.
    old_hits = [
        slug for slug, score in vector.top_k(config.kb_root(), OLD_QUERY, k=2) if score > 0.0
    ]
    assert "sedan-upkeep" not in old_hits

    # And the full fused surface finds the new meaning.
    result = mem("search", NEW_QUERY, "--json", env_extra=env)
    assert result.returncode == 0, result.stderr
    assert "sedan-upkeep" in [hit["slug"] for hit in json.loads(result.stdout)]


def test_created_and_deleted_files_reflected_on_next_read(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert (
        mem(
            "save", "--title", "Alpha note", "--body",
            "Nothing else mentions xylographs anywhere.",
            env_extra=env,
        ).returncode
        == 0
    )
    assert vector_slugs(kb) == {"alpha-note"}

    # Created behind the CLI's back: on the next read it is in list and
    # search, and that same search enqueues + drains its embedding.
    write_concept(
        kb, "handmade-note", "Handmade note", "written by hand",
        "A handwritten zettel about quills.",
    )
    listing = mem("list", env_extra=env)
    assert listing.returncode == 0
    assert "handmade-note" in listing.stdout
    result = mem("search", "quills", env_extra=env)
    assert result.returncode == 0, result.stderr
    assert "handmade-note" in result.stdout
    assert "handmade-note" in vector_slugs(kb)
    assert queue_slugs(kb) == set()

    # Deleted behind the CLI's back: gone from list and search on the next
    # read, and its vector + queue rows are purged - no ghost hits pointing
    # at a missing path.
    (kb.kb / "concepts" / "alpha-note.md").unlink()
    result = mem("search", "xylographs", env_extra=env)
    assert result.returncode == 0, result.stderr
    assert "alpha-note" not in result.stdout
    assert "alpha-note" not in vector_slugs(kb)
    assert "alpha-note" not in queue_slugs(kb)
    listing = mem("list", env_extra=env)
    assert "alpha-note" not in listing.stdout


def test_identical_rewrite_does_not_reembed(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert (
        mem(
            "save", "--title", "Car care", "--body", "Regular automobile servicing.",
            env_extra=env,
        ).returncode
        == 0
    )
    assert queue_slugs(kb) == set()

    # A touch-style rewrite: mtime changes, content does not.
    path = kb.kb / "concepts" / "car-care.md"
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    # Daemon down: if this had enqueued a re-embed, the queue would show it.
    result = mem("search", "automobile")
    assert result.returncode == 0, result.stderr
    assert "car-care" in result.stdout
    assert queue_slugs(kb) == set()


def test_reindex_rebuilds_entire_index_equivalently(mem, kb, semantic_ollama_factory):
    daemon = semantic_ollama_factory()
    env = {"MEM_OLLAMA_URL": daemon.url}
    assert mem("init", env_extra=env).returncode == 0
    assert (
        mem(
            "save", "--title", "Sedan upkeep", "--body",
            "Regular servicing keeps an automobile dependable for years.",
            "--topics", "autos",
            env_extra=env,
        ).returncode
        == 0
    )
    assert (
        mem(
            "save", "--title", "Motor oils", "--body",
            "Vehicle maintenance notes; see [[sedan-upkeep]].",
            "--topics", "autos",
            env_extra=env,
        ).returncode
        == 0
    )
    assert (
        mem(
            "save", "--title", "Sourdough starter", "--body",
            "Levain proofing determines the crumb of the loaf.",
            env_extra=env,
        ).returncode
        == 0
    )

    before_search = mem("search", OLD_QUERY, "--json", env_extra=env)
    assert before_search.returncode == 0, before_search.stderr
    assert json.loads(before_search.stdout)  # non-empty: all three legs fed
    before_related = mem("get", "motor-oils", "--related", "--json", env_extra=env)
    assert before_related.returncode == 0, before_related.stderr

    shutil.rmtree(kb.kb / ".index")  # the whole derived index, gone

    result = mem("reindex", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3" in result.stdout
    assert queue_slugs(kb) == set()
    assert len(vector_slugs(kb)) == 3
    assert (kb.kb / ".index" / "graph.json").is_file()

    # Unchanged content: byte-equivalent results, lexical + vector + graph.
    after_search = mem("search", OLD_QUERY, "--json", env_extra=env)
    assert after_search.returncode == 0, after_search.stderr
    assert after_search.stdout == before_search.stdout
    after_related = mem("get", "motor-oils", "--related", "--json", env_extra=env)
    assert after_related.stdout == before_related.stdout
