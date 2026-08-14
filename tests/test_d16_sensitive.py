"""D16 - `sensitive` sensitivity tier (PII/PHI).

Save accepts it, search marks it `[sensitive]` (text) / carries it (--json),
`--no-sensitive` excludes exactly that tier (work and normal unaffected, and
vice versa: `--no-work` leaves sensitive items in), invalid values still
refused. Daemon down throughout - the lexical leg carries search.
"""

import json


def _save(mem, title, sensitivity):
    r = mem("save", "--title", title, "--body", f"{title} body about phoenixes.",
            "--description", f"{title} description", "--topics", "d16",
            "--sensitivity", sensitivity)
    assert r.returncode == 0, r.stderr


def test_sensitive_tier_roundtrip_marking_and_filters(kb, mem):
    assert mem("init").returncode == 0
    _save(mem, "Phoenix normal fact", "normal")
    _save(mem, "Phoenix work fact", "work")
    _save(mem, "Phoenix sensitive fact", "sensitive")

    r = mem("search", "phoenixes", "--json")
    assert r.returncode == 0, r.stderr
    hits = {h["slug"]: h for h in json.loads(r.stdout)}
    assert hits["phoenix-sensitive-fact"]["sensitivity"] == "sensitive"
    assert hits["phoenix-work-fact"]["sensitivity"] == "work"
    assert "sensitivity" not in hits["phoenix-normal-fact"]

    r = mem("search", "phoenixes")
    assert "[sensitive]" in r.stdout and "[work]" in r.stdout

    r = mem("search", "phoenixes", "--json", "--no-sensitive")
    slugs = {h["slug"] for h in json.loads(r.stdout)}
    assert "phoenix-sensitive-fact" not in slugs
    assert {"phoenix-normal-fact", "phoenix-work-fact"} <= slugs

    r = mem("search", "phoenixes", "--json", "--no-work")
    slugs = {h["slug"] for h in json.loads(r.stdout)}
    assert "phoenix-work-fact" not in slugs
    assert {"phoenix-normal-fact", "phoenix-sensitive-fact"} <= slugs

    r = mem("get", "phoenix-sensitive-fact", "--json")
    assert json.loads(r.stdout)["sensitivity"] == "sensitive"


def test_invalid_sensitivity_still_refused(kb, mem):
    assert mem("init").returncode == 0
    r = mem("save", "--title", "Bad tier", "--body", "x",
            "--sensitivity", "secret")
    assert r.returncode != 0
