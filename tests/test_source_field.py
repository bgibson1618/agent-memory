"""Provenance `source` field (DECISION_LOG D9).

Every concept carries a source citation: explicit via --source / candidate
"source", else an ambient/extract date stamp. An update without --source keeps
the existing citation - provenance never silently degrades to "ambient".
"""

import json

from test_f4_semantic import (
    semantic_ollama_factory,  # noqa: F401  (pytest fixture, found via this namespace)
)

BODY = "Source-field probe body.\n"


def frontmatter_source(kb, slug):
    text = (kb.kb / "concepts" / f"{slug}.md").read_text()
    for line in text.splitlines():
        if line.startswith("source:"):
            return line.split(":", 1)[1].strip().strip("'\"")
    return None


def test_save_with_source_round_trips(kb, mem):
    mem("init")
    mem("save", "--title", "Sourced probe", "--body", BODY,
        "--source", "Sweller (1988) Cognitive load during problem solving")
    assert frontmatter_source(kb, "sourced-probe") == \
        "Sweller (1988) Cognitive load during problem solving"
    got = json.loads(mem("get", "sourced-probe", "--json").stdout)
    assert got["source"] == "Sweller (1988) Cognitive load during problem solving"


def test_save_without_source_gets_ambient_stamp(kb, mem):
    mem("init")
    mem("save", "--title", "Unsourced probe", "--body", BODY)
    src = frontmatter_source(kb, "unsourced-probe")
    assert src.startswith("ambient (") and src.endswith(")")


def test_update_without_source_preserves_citation(kb, mem):
    mem("init")
    mem("save", "--title", "Keeper probe", "--body", BODY, "--source", "Original citation")
    mem("save", "--title", "Keeper probe", "--body", "Edited body.\n", "--update")
    assert frontmatter_source(kb, "keeper-probe") == "Original citation"
    # an explicit --source on update still wins
    mem("save", "--title", "Keeper probe", "--body", "Edited again.\n", "--update",
        "--source", "Corrected citation")
    assert frontmatter_source(kb, "keeper-probe") == "Corrected citation"


def test_extract_candidate_source_passes_through(kb, mem, tmp_path, semantic_ollama_factory):
    env = {"MEM_OLLAMA_URL": semantic_ollama_factory().url}
    mem("init", env_extra=env)
    cands = {"candidates": [
        {"title": "Extract sourced", "body": "Regular car maintenance keeps the vehicle safe.\n",
         "description": "d", "topics": ["cars"], "type": "concept",
         "sensitivity": "normal", "source": "Widget Corp (2026) Widget Manual"},
        {"title": "Extract unsourced", "body": "Dog training builds obedience through commands.\n",
         "description": "d", "topics": ["dogs"], "type": "concept",
         "sensitivity": "normal"},
    ]}
    f = tmp_path / "cands.json"
    f.write_text(json.dumps(cands))
    proc = mem("extract", "--candidates", str(f), env_extra=env)
    assert proc.returncode == 0, proc.stderr
    assert frontmatter_source(kb, "extract-sourced") == "Widget Corp (2026) Widget Manual"
    src = frontmatter_source(kb, "extract-unsourced")
    assert src.startswith("extract (")
