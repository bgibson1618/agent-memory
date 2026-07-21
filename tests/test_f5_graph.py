"""F5 - concept graph.

Proof for FEATURES.md F5: body `[[wikilinks]]` and frontmatter `related[]`
yield direct edges; topics connect concepts through topic nodes (memberships
in the cache, never materialized pairwise edges); `mem get <slug> --related`
returns link- and topic-neighbors in text and `--json`; the edge cache
invalidates on file mtime change and edges to deleted files stop surfacing;
concept files stay plain Obsidian wikilink syntax. Every test runs with the
Ollama seam pointing at a closed port - the graph needs no daemon.
"""

import json
import os


def save(mem, title, body, **overrides):
    args = {"title": title, "body": body}
    args.update(overrides)
    argv = ["save"]
    for key, value in args.items():
        argv.extend([f"--{key}", value])
    result = mem(*argv)
    assert result.returncode == 0, result.stderr
    return result


def neighbors_json(mem, slug):
    result = mem("get", slug, "--related", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "neighbors" in payload, payload
    return payload["neighbors"]


def link_slugs(neighbors) -> dict:
    return {link["slug"]: link["via"] for link in neighbors["links"]}


def seed_linked_pair(mem):
    """alpha --[[beta]]--> beta, plus gamma with no edges."""
    assert mem("init").returncode == 0
    save(mem, "Alpha", "Alpha builds on [[beta]] for context.")
    save(mem, "Beta", "Beta stands alone.")
    save(mem, "Gamma", "Gamma stands alone too.")


def test_wikilinks_and_related_frontmatter_yield_direct_edges(mem):
    assert mem("init").returncode == 0
    save(mem, "Alpha", "See [[beta]] and [[Gamma Note|the gamma alias]] and [[beta#history]].")
    save(mem, "Beta", "Beta body.")
    save(mem, "Gamma Note", "Gamma body.")
    save(mem, "Delta", "Delta body.", related="alpha")

    alpha = link_slugs(neighbors_json(mem, "alpha"))
    assert "beta" in alpha and "wikilink" in alpha["beta"]
    assert "gamma-note" in alpha  # [[Title|alias]] and [[slug#heading]] resolve to the slug
    assert "delta" in alpha and alpha["delta"] == ["backlink"]

    beta = link_slugs(neighbors_json(mem, "beta"))
    assert "alpha" in beta and beta["alpha"] == ["backlink"]

    delta = link_slugs(neighbors_json(mem, "delta"))
    assert "alpha" in delta and "related" in delta["alpha"]

    # neighbors carry slug + title, enough to `mem get` without a second guess
    entry = next(n for n in neighbors_json(mem, "alpha")["links"] if n["slug"] == "beta")
    assert entry["title"] == "Beta"


def test_topics_connect_through_topic_nodes(mem, kb):
    assert mem("init").returncode == 0
    for name in ("Xray", "Yankee", "Zulu"):
        save(mem, name, f"{name} body.", topics="python, testing")
    save(mem, "Offside", "No shared topics.", topics="cooking")

    got = neighbors_json(mem, "xray")
    assert got["links"] == []  # topic co-membership is not a direct edge
    by_topic = {t["topic"]: [m["slug"] for m in t["neighbors"]] for t in got["topics"]}
    assert by_topic == {"python": ["yankee", "zulu"], "testing": ["yankee", "zulu"]}

    # topic nodes are stored as per-concept memberships, never pairwise edges:
    # every record carries only its own links/related/topics
    cache = json.loads((kb.kb / ".index" / "graph.json").read_text(encoding="utf-8"))
    for record in cache["files"].values():
        assert set(record) == {"mtime_ns", "size", "title", "links", "related", "topics"}
        assert record["links"] == [] and record["related"] == []


def test_broad_topic_stays_linear_in_the_cache(mem, kb):
    assert mem("init").returncode == 0
    count = 12
    for i in range(count):
        save(mem, f"Broad {i}", f"Body {i}.", topics="broad")
    neighbors = neighbors_json(mem, "broad-0")
    assert len(neighbors["topics"][0]["neighbors"]) == count - 1

    # the serialized cache mentions the tag once per member - O(n), not O(n^2)
    text = (kb.kb / ".index" / "graph.json").read_text(encoding="utf-8")
    assert text.count('"broad"') == count


def test_text_output_lists_both_neighbor_kinds(mem):
    assert mem("init").returncode == 0
    save(mem, "Alpha", "Alpha cites [[beta]].", topics="learning")
    save(mem, "Beta", "Beta body.", topics="learning")

    result = mem("get", "alpha", "--related")
    assert result.returncode == 0, result.stderr
    assert "neighbors:" in result.stdout
    assert "link: beta (wikilink)  Beta" in result.stdout
    assert "topic learning: beta" in result.stdout

    plain = mem("get", "alpha")
    assert plain.returncode == 0
    assert "neighbors:" not in plain.stdout  # neighborhood only on request


def test_edge_cache_invalidates_on_mtime_change(mem, kb):
    seed_linked_pair(mem)
    assert "beta" in link_slugs(neighbors_json(mem, "alpha"))  # cache is now warm

    # an external editor rewrites alpha behind the CLI's back
    path = kb.kb / "concepts" / "alpha.md"
    stat = path.stat()
    path.write_text(
        path.read_text(encoding="utf-8").replace("[[beta]]", "[[gamma]]"), encoding="utf-8"
    )
    bumped = stat.st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(bumped, bumped))

    fresh = link_slugs(neighbors_json(mem, "alpha"))
    assert "gamma" in fresh and "beta" not in fresh
    assert "alpha" in link_slugs(neighbors_json(mem, "gamma"))  # backlink follows


def test_edges_to_deleted_files_stop_surfacing(mem, kb):
    seed_linked_pair(mem)
    assert "beta" in link_slugs(neighbors_json(mem, "alpha"))

    (kb.kb / "concepts" / "beta.md").unlink()

    assert "beta" not in link_slugs(neighbors_json(mem, "alpha"))
    cache = json.loads((kb.kb / ".index" / "graph.json").read_text(encoding="utf-8"))
    assert "beta" not in cache["files"]  # the node is gone, not just hidden

    gone = mem("get", "beta", "--related")
    assert gone.returncode == 1
    assert "no concept 'beta'" in gone.stderr


def test_dangling_wikilink_never_surfaces(mem):
    assert mem("init").returncode == 0
    save(mem, "Alpha", "Alpha cites [[never-written]] and [[???]].")
    got = neighbors_json(mem, "alpha")
    assert got == {"links": [], "topics": []}


def test_empty_neighborhood_is_quiet(mem):
    assert mem("init").returncode == 0
    save(mem, "Loner", "No links, no shared topics.", topics="solo")

    result = mem("get", "loner", "--related")
    assert result.returncode == 0, result.stderr
    assert "(none)" in result.stdout
    assert neighbors_json(mem, "loner") == {"links": [], "topics": []}


def test_concept_files_stay_plain_obsidian_syntax(mem, kb):
    assert mem("init").returncode == 0
    body = "Alpha builds on [[beta]] and [[Gamma Note|the alias]].\n"
    save(mem, "Alpha", body)
    text = (kb.kb / "concepts" / "alpha.md").read_text(encoding="utf-8")
    assert "[[beta]]" in text and "[[Gamma Note|the alias]]" in text
    assert body.strip() in text  # the body lands verbatim - no custom markup added
