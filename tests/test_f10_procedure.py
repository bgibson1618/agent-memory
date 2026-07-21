"""F10 - extraction procedure: the agent-side extract-knowledge choreography
ships as package data (agent_integration/extract-knowledge.md), is printed by
`mem extract --procedure`, and both managed instruction blocks point agents at
it.

The procedure's *behavior* is F10's observed surface - a real document run
end-to-end in a real agent session, judged at wave reconcile. These tests pin
the shippable mechanics instead: the artifact is served without a KB or
daemon, its structure carries the FEATURES/ARCHITECTURE contract (fan-out
counts, both transports, reviewer gate, D3's reviewable skipped-duplicates),
and its candidate schema never drifts from the CLI's actual field set.
"""

import re

from agent_memory import blocks
from agent_memory.extract import CANDIDATE_FIELDS


def procedure_text() -> str:
    return blocks.render_block(blocks.EXTRACT_PROCEDURE)


def test_procedure_prints_without_kb_or_daemon(mem):
    # Default env: no `mem init` has run and MEM_OLLAMA_URL is a closed port.
    r = mem("extract", "--procedure")
    assert r.returncode == 0
    assert "extract-knowledge procedure" in r.stdout
    assert r.stderr == ""


def test_procedure_output_is_the_package_artifact(mem):
    r = mem("extract", "--procedure")
    assert r.stdout == procedure_text()


def test_procedure_structural_contract():
    text = procedure_text()
    # >= 2 fresh-eyed extractors AND >= 2 fresh-eyed reviewers.
    assert text.count("at least two") >= 2
    assert "fresh-eyed extractors" in text
    assert "fresh-eyed reviewers" in text
    # Both transports: cross-backend agent-roster and inline subagents.
    assert "agent-roster" in text
    assert "inline subagents" in text
    # Only reviewer-approved candidates reach the deterministic half.
    assert "Only reviewer-approved candidates reach `mem extract`" in text
    assert "mem extract --candidates" in text
    # D3: skipped-duplicate dispositions are reviewable; direct `mem save` is
    # the sanctioned override.
    assert "skipped-duplicate is reviewable" in text
    assert "`mem save`" in text
    # Vendor + confidentiality policy travel with the choreography.
    assert "Antigravity" in text
    assert "sensitivity: work" in text
    # Preflight names the diagnosis command.
    assert "mem doctor" in text


def test_procedure_schema_matches_cli_fields():
    text = procedure_text()
    for field in CANDIDATE_FIELDS:
        assert re.search(rf"\b{field}\b", text), f"schema field {field!r} missing"


def test_blocks_point_at_the_procedure():
    for name in (blocks.CLAUDE_BLOCK, blocks.AGENTS_BLOCK):
        assert "mem extract --procedure" in blocks.render_block(name)


def test_extract_requires_candidates_or_procedure(mem):
    r = mem("extract")
    assert r.returncode == 1
    assert r.stdout == ""
    lines = r.stderr.strip().splitlines()
    assert lines == ["error: extract requires --candidates (or --procedure)"]
