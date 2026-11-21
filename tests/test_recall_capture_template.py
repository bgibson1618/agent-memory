"""Candidate memory guidance (2026-11-20 slice, local branch): task-start recall and scoped single-case capture.

Both shipped blocks must ask for a search at the start of non-trivial work and a check of a hit's stated
conditions; must allow a single tested observation to be saved when stated as one; must keep conclusions within
the evidence and route project-only facts to project notes; must ask that evidence be cited by project name and
project-relative path, never an absolute local path (added after the Opus pilot); and must keep the versioned-update rule."""
from agent_memory.blocks import AGENTS_BLOCK, CLAUDE_BLOCK, render_block

REQUIRED = [
    "at the start of non-trivial work",
    "stated conditions (versions, environment, evidence)",
    "treat it as a lead to verify, not an answer",
    "A single tested observation is worth saving",
    "when you state it as one",
    "generalize only when a checked source or broader test supports it",
    "label anything else as a hypothesis",
    "project's own notes",
    "Search before saving",
    "Cite evidence by project name and project-relative path, never by an absolute local path.",
]


def _flat(text):
    return " ".join(text.split())


def test_both_blocks_carry_the_recall_and_scoped_capture_rules():
    for name in (CLAUDE_BLOCK, AGENTS_BLOCK):
        text = _flat(render_block(name))
        missing = [phrase for phrase in REQUIRED if phrase not in text]
        assert not missing, (name, missing)


def test_old_recall_trigger_is_gone_and_update_rule_kept():
    for name in (CLAUDE_BLOCK, AGENTS_BLOCK):
        text = _flat(render_block(name))
        assert "may have studied" not in text, name
        assert text.startswith("<!-- BEGIN AGENT-MEMORY BLOCK v1") and text.rstrip().endswith("<!-- END AGENT-MEMORY BLOCK -->")
    assert "--expected-version" in render_block(CLAUDE_BLOCK)
