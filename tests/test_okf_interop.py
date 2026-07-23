"""OKF v0.1 interop hardening (DECISION_LOG D5).

Two gaps closed after the D2 conformance check against the official spec
(research/okf-spec-v0.1.md): the reserved filenames `index.md`/`log.md` are
refused as concept slugs (spec §3.1/§9 rule 3), and the spec-recommended
vocabulary is mirrored on write (`tags`, `timestamp`) and accepted on read.
"""

import json

import yaml

BODY = "Reserved-name and vocabulary interop probes for OKF v0.1.\n"


def read_front(kb, slug) -> dict:
    text = (kb.kb / "concepts" / f"{slug}.md").read_text()
    return yaml.safe_load(text.split("---\n")[1])


def test_reserved_titles_are_refused(kb, mem):
    mem("init")
    for title in ("Index", "Log"):
        proc = mem("save", "--title", title, "--body", BODY)
        assert proc.returncode == 1
        assert "reserved OKF filename" in proc.stderr
        assert len(proc.stderr.strip().splitlines()) == 1
    assert not (kb.kb / "concepts" / "index.md").exists()
    assert not (kb.kb / "concepts" / "log.md").exists()


def test_reserved_explicit_slug_is_refused(mem):
    mem("init")
    proc = mem("save", "--title", "Directory listing", "--slug", "index", "--body", BODY)
    assert proc.returncode == 1
    assert "reserved OKF filename" in proc.stderr


def test_extract_reports_reserved_candidate_as_invalid(kb, mem, fake_ollama):
    mem("init")
    candidates = json.dumps(
        [
            {"title": "Index", "body": BODY, "topics": ["meta"]},
            {"title": "Valid concept", "body": BODY, "topics": ["meta"]},
        ]
    )
    proc = mem(
        "extract", "--candidates", "-",
        input=candidates,
        env_extra={"MEM_OLLAMA_URL": fake_ollama.url},
    )
    assert proc.returncode == 0
    assert "1 added" in proc.stdout and "1 invalid" in proc.stdout
    assert "reserved OKF filename" in proc.stdout
    assert (kb.kb / "concepts" / "valid-concept.md").exists()
    assert not (kb.kb / "concepts" / "index.md").exists()


def test_serialized_frontmatter_mirrors_spec_vocabulary(kb, mem):
    mem("init")
    proc = mem(
        "save", "--title", "Mirrored concept", "--body", BODY,
        "--topics", "learning-science,tooling",
    )
    assert proc.returncode == 0
    front = read_front(kb, "mirrored-concept")
    assert front["tags"] == front["topics"] == ["learning-science", "tooling"]
    assert front["timestamp"] == front["updated"]


def test_update_keeps_mirrors_in_sync(kb, mem):
    mem("init")
    mem("save", "--title", "Sync probe", "--body", BODY, "--topics", "one")
    proc = mem(
        "save", "--title", "Sync probe", "--update", "--body", BODY + "more\n",
        "--topics", "one,two",
        env_extra={"MEM_NOW": "2026-07-22T23:59:59Z"},
    )
    assert proc.returncode == 0
    front = read_front(kb, "sync-probe")
    assert front["tags"] == front["topics"] == ["one", "two"]
    assert front["timestamp"] == front["updated"] == "2026-07-22T23:59:59Z"


def test_related_written_as_wikilinks_read_as_slugs(kb, mem):
    """D7: files carry '[[slug]]' related (Obsidian property links); the in-memory
    and --json form stays plain slugs."""
    mem("init")
    proc = mem(
        "save", "--title", "Linked concept", "--body", BODY,
        "--related", "forgetting-curve,spaced-repetition",
    )
    assert proc.returncode == 0
    front = read_front(kb, "linked-concept")
    assert front["related"] == ["[[forgetting-curve]]", "[[spaced-repetition]]"]
    got = mem("get", "linked-concept", "--json")
    assert json.loads(got.stdout)["related"] == ["forgetting-curve", "spaced-repetition"]


def test_topics_normalize_to_kebab_case_and_dedupe(kb, mem):
    """D7: space/case topic variants collapse to one kebab tag on write."""
    mem("init")
    proc = mem(
        "save", "--title", "Kebab probe", "--body", BODY,
        "--topics", "Learning Science,learning-science,Assessment Design",
    )
    assert proc.returncode == 0
    front = read_front(kb, "kebab-probe")
    assert front["tags"] == front["topics"] == ["learning-science", "assessment-design"]


def test_external_plain_slug_related_normalizes_on_read(kb, mem):
    """Pre-D7 files (and other OKF tools) write related as plain slugs; a mem
    update round-trips them into the wikilink form without changing meaning."""
    mem("init")
    external = (
        "---\n"
        "slug: plain-related\n"
        "title: Plain related concept\n"
        "description: Authored with plain-slug related\n"
        "type: concept\n"
        "topics: [interop]\n"
        "related: [forgetting-curve]\n"
        "timestamp: 2026-07-20T00:00:00Z\n"
        "---\n\n"
        "Body with plain-slug related frontmatter.\n"
    )
    (kb.kb / "concepts" / "plain-related.md").write_text(external)
    got = mem("get", "plain-related", "--json")
    assert got.returncode == 0
    assert json.loads(got.stdout)["related"] == ["forgetting-curve"]


def test_parse_accepts_spec_vocabulary_from_external_files(kb, mem):
    """A hand-authored file using only the spec-recommended keys still loads."""
    mem("init")
    external = (
        "---\n"
        "slug: external-spec-shaped\n"
        "title: External spec-shaped concept\n"
        "description: Written by another OKF tool with spec vocabulary only\n"
        "type: Reference\n"
        "tags: [interop, okf]\n"
        "timestamp: 2026-07-20T00:00:00Z\n"
        "---\n\n"
        "Body written outside mem, using tags/timestamp instead of topics/updated.\n"
    )
    (kb.kb / "concepts" / "external-spec-shaped.md").write_text(external)
    proc = mem("get", "external-spec-shaped", "--json")
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["topics"] == ["interop", "okf"]
    assert data["updated"] == "2026-07-20T00:00:00Z"
    assert data["created"] == "2026-07-20T00:00:00Z"  # falls back to timestamp
    listed = mem("list")
    assert "external-spec-shaped" in listed.stdout
