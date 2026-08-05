"""D12 - link health: extract remaps links to batch-mates that landed
elsewhere (dedup skip -> match slug, suffixed save -> actual slug), so an
extract can never mint a dangling link to a slug it decided not to create;
`mem links` reports the dangling targets that do exist; doctor carries an
informational (never-failing) dangling-links count so drift stays visible.

Fixtures ride test_f9_extract's semantic fake (synonym-class embeddings):
linker candidates mix their own classes with a batch-mate's link words, and
every pairing is engineered to land clearly on one side of the calibrated
dedup threshold (cosines 0.5/0.707 vs 1.0 against a threshold in (0.71, 1)).
"""

import json

from agent_memory import okf, vector

from test_f9_extract import (  # noqa: F401  (fixture pulled in by import)
    NEAR_DUP,
    _rows,
    concept_files,
    run_extract,
    seed_kb,
    semantic_ollama,
)

# Docker/cache classes + the near-dup's slug words (spacing/review classes):
# cosine vs SEED = 2/(sqrt(4)*sqrt(2)) ~ 0.707, clear of the 0.79 threshold.
LINKER = {
    "title": "Docker cache ordering",
    "body": (
        "Docker reuses image layers; the cache rewards ordering. See"
        " [[spacing-effect-for-review|the spacing note]] and [[some-future-idea]]."
    ),
    "related": ["spacing-effect-for-review"],
}


def test_extract_remaps_links_to_dedup_match(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    seed_kb(mem, env)  # spaced-repetition-scheduling

    result = run_extract(mem, [NEAR_DUP, LINKER], "--json", env_extra=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["skipped_duplicate"] == 1
    assert payload["added"] == 1
    assert payload["links_remapped"] == 2  # one wikilink + one related entry

    saved = (kb.kb / "concepts" / "docker-cache-ordering.md").read_text(encoding="utf-8")
    concept = okf.parse(saved)
    # The batch-mate link follows the dedup match, alias preserved; the
    # aspirational link to a never-candidate slug is untouched.
    assert "[[spaced-repetition-scheduling|the spacing note]]" in concept.body
    assert "[[spacing-effect-for-review" not in concept.body
    assert "[[some-future-idea]]" in concept.body
    assert concept.related == ["spaced-repetition-scheduling"]

    # The stored vector followed the rewritten body (content hash current).
    rows = dict(_rows(kb, "SELECT slug, content_hash FROM vectors"))
    assert rows["docker-cache-ordering"] == vector.content_hash(vector.embed_text(concept))


# Occupies the slug the suffix test's candidate wants, with a vector far from
# it (title classes {4,5} + body classes {2,3} vs the candidate's {4,5}).
OCCUPANT_ENV = ("--title", "Docker layer caching",
                "--body", "Transformer attention grows with context window tokens.")
SUFFIX_CANDIDATE = {
    "title": "Docker layer caching",
    "body": "Docker reuses image layers; ordering commands preserves the cache.",
}
SUFFIX_LINKER = {
    "title": "Spaced review of builds",
    "body": "Reviews at increasing intervals beat cramming. See [[docker-layer-caching]].",
}


def test_extract_remaps_links_to_suffixed_slug(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem("save", *OCCUPANT_ENV, env_extra=env).returncode == 0

    result = run_extract(mem, [SUFFIX_CANDIDATE, SUFFIX_LINKER], "--json", env_extra=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["added"] == 2
    assert payload["links_remapped"] == 1
    assert "docker-layer-caching-2.md" in concept_files(kb)

    linker = okf.parse(
        (kb.kb / "concepts" / "spaced-review-of-builds.md").read_text(encoding="utf-8")
    )
    assert "[[docker-layer-caching-2]]" in linker.body
    assert "[[docker-layer-caching]]" not in linker.body

    # And because the remap happened, nothing dangles.
    links = mem("links", env_extra=env)
    assert links.returncode == 0
    assert "every wikilink/related target resolves" in links.stdout


def test_links_reports_dangling_targets(mem, kb, semantic_ollama):
    env = {"MEM_OLLAMA_URL": semantic_ollama.url}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", "Pointing note",
        "--body", "See [[never-written]] and [[never-written|alias]] for more.",
        env_extra=env,
    ).returncode == 0

    text = mem("links", env_extra=env)
    assert text.returncode == 0
    assert "never-written  <- pointing-note" in text.stdout
    assert "1 dangling target(s) across 1 reference(s)" in text.stdout

    as_json = mem("links", "--json", env_extra=env)
    assert as_json.returncode == 0
    payload = json.loads(as_json.stdout)
    assert payload == {
        "targets": 1,
        "references": 1,
        "dangling": {"never-written": ["pointing-note"]},
    }


def test_doctor_dangling_check_is_informational(mem, kb, semantic_ollama):
    # MEM_EMBED_DIMS matches the f9 fake (32) so the embed-model check passes.
    env = {"MEM_OLLAMA_URL": semantic_ollama.url, "MEM_EMBED_DIMS": "32"}
    assert mem("init", env_extra=env).returncode == 0
    assert mem(
        "save", "--title", "Pointing note", "--body", "See [[never-written]].",
        env_extra=env,
    ).returncode == 0

    result = mem("doctor", env_extra=env)
    assert result.returncode == 0, result.stdout + result.stderr  # never a failure
    lines = [line for line in result.stdout.splitlines() if "dangling-links" in line]
    assert len(lines) == 1
    assert lines[0].startswith("ok")
    assert "1 unresolved target(s) across 1 reference(s)" in lines[0]

    # Writing the missing concept clears the count.
    assert mem(
        "save", "--title", "Never written", "--body", "Now it exists.", env_extra=env
    ).returncode == 0
    result = mem("doctor", env_extra=env)
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if "dangling-links" in line]
    assert "every wikilink/related target resolves" in lines[0]
