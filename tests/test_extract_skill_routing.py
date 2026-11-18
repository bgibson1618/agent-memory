"""The shipped /mem:extract skill routes every command through the entrypoint the
governing memory policy permits (2026-11 activation follow-up).

The skill is text, so these are textual contracts a fresh agent can be held to:

  - the skill resolves ENTRYPOINT from policy before any tool call, with both routes
    spelled out (a guarded wrapper for one instance; the ordinary CLI for an authorized
    instance) and a stop rule when neither is established;
  - every `mem <subcommand>` form the printed procedure (extract-knowledge.md) uses is
    mapped explicitly, so nothing is left to inference;
  - the skill's own command examples use ENTRYPOINT, never bare `mem`;
  - `doctor` is confined to the route that permits it, `init` is never a step, no default
    instance path is baked in, and the preflight says what it cannot prove.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "extract" / "SKILL.md").read_text()
PROCEDURE = (ROOT / "src" / "agent_memory" / "agent_integration" / "extract-knowledge.md").read_text()

MAPPING_LINE = re.compile(r"^- `mem (?P<sub>[a-z]+)[^`]*` → ", re.MULTILINE)
PROCEDURE_FORM = re.compile(r"`mem (?P<sub>[a-z]+)")


def _mapped_subcommands():
    return {m.group("sub") for m in MAPPING_LINE.finditer(SKILL)}


def test_every_procedure_command_form_is_mapped():
    used = {m.group("sub") for m in PROCEDURE_FORM.finditer(PROCEDURE)}
    assert used, "the procedure names no mem commands?"
    assert used <= _mapped_subcommands(), f"unmapped procedure forms: {used - _mapped_subcommands()}"


def test_held_commands_are_mapped_explicitly():
    mapped = _mapped_subcommands()
    assert {"doctor", "init"} <= mapped
    doctor_line = next(l for l in SKILL.splitlines() if l.startswith("- `mem doctor"))
    init_line = next(l for l in SKILL.splitlines() if l.startswith("- `mem init"))
    assert "held" in doctor_line and "step 2" in doctor_line
    assert "never" in init_line


def test_both_routes_and_the_stop_rule_are_spelled_out():
    assert "guarded entrypoint" in SKILL
    assert "`mem`, against the instance the policy names" in SKILL
    assert "stop and ask Brent" in SKILL
    assert "not permission to use a default instance" in SKILL
    assert "before any tool call or delegate" in SKILL


def test_skill_examples_use_entrypoint_not_bare_mem():
    for line in SKILL.splitlines():
        line = line.replace("`mem …`", "")          # the generic form in the routing sentence
        if "`mem " not in line:
            continue
        # bare `mem` may appear only in the mapping bullets, the routing table, or the
        # sentence forbidding the fallback
        assert line.startswith("- `mem ") or line.startswith("|") or "never fall back" in line, line
    assert SKILL.count("ENTRYPOINT") >= 12
    assert "`ENTRYPOINT extract --procedure`" in SKILL
    assert "`ENTRYPOINT get <slug> --json`" in SKILL
    assert "`ENTRYPOINT save --update`" in SKILL


def test_no_default_instance_path_and_no_init_step():
    assert "~/.agent-memory" not in SKILL
    assert ".agent-memory-personal" not in SKILL          # no laptop path baked in either
    assert "suggest\n`mem init`" not in SKILL and "suggest `mem init`" not in SKILL
    assert "do not run `init` from this skill" in SKILL
    assert "MEM_KB_ROOT` only when the policy names that root" in SKILL


def test_preflight_states_what_it_cannot_prove():
    preflight = SKILL.split("## 2. Preflight", 1)[1].split("## 3.", 1)[0]
    assert "`ENTRYPOINT --version`" in preflight and "`ENTRYPOINT stats`" in preflight
    assert "non-writing" in preflight
    assert "/api/version" in preflight and "/api/tags" in preflight
    assert "do NOT check the instance's embed queue or FTS5" in preflight
    assert "stop before authoring any fan-out" in preflight
    assert "drains pending embeddings" in preflight      # doctor's write is named where it is permitted
    assert "Never store knowledge elsewhere" in SKILL


def test_report_names_entrypoint_and_limits():
    report = SKILL.split("## 4. Report", 1)[1]
    assert "ENTRYPOINT and instance used" in report
    assert "preflight limit" in report
