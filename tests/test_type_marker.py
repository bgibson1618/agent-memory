"""Credence axis: non-`concept` types are marked in search and filterable (D10).

Retrieval is credence-blind (cosine has no epistemics), so a saved
`sb-position` hypothesis must be distinguishable from a vetted `concept` at
recall time: `[<type>]` in text, a `type` field in --json, and a `--type`
allow-list to ground only in chosen types.
"""

import json

from test_f4_semantic import (
    semantic_ollama_factory,  # noqa: F401  (pytest fixture, found via this namespace)
)


def seed(mem, env):
    assert mem("init", env_extra=env).returncode == 0
    # two entries that embed into the same meaning class (dog/training) so both
    # surface for one query, differing only by type
    mem("save", "--title", "Dog training builds obedience", "--body",
        "Dog training builds obedience through repeated commands.\n", env_extra=env)
    mem("save", "--title", "Our team thinks puppy obedience transfers",
        "--body", "A hypothesis: canine obedience training transfers to heel work.\n",
        "--type", "sb-position", env_extra=env)


def test_type_marked_in_text_and_json(mem, kb, semantic_ollama_factory):
    env = {"MEM_OLLAMA_URL": semantic_ollama_factory().url}
    seed(mem, env)

    proc = mem("search", "dog obedience training", env_extra=env)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    pos_line = next(l for l in lines if "our-team-thinks" in l)
    concept_line = next(l for l in lines if "dog-training-builds" in l)
    assert "[sb-position]" in pos_line
    assert "[sb-position]" not in concept_line and "[concept]" not in concept_line

    res = json.loads(mem("search", "dog obedience training", "--json", env_extra=env).stdout)
    by_slug = {h["slug"]: h for h in res}
    assert by_slug["our-team-thinks-puppy-obedience-transfers"]["type"] == "sb-position"
    assert by_slug["dog-training-builds-obedience"]["type"] == "concept"


def test_type_filter_grounds_in_vetted_only(mem, kb, semantic_ollama_factory):
    env = {"MEM_OLLAMA_URL": semantic_ollama_factory().url}
    seed(mem, env)

    res = json.loads(mem("search", "dog obedience training", "--json",
                         "--type", "concept", env_extra=env).stdout)
    slugs = {h["slug"] for h in res}
    assert "dog-training-builds-obedience" in slugs
    assert "our-team-thinks-puppy-obedience-transfers" not in slugs
    assert all(h["type"] == "concept" for h in res)
