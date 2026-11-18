"""The shipped /mem:extract skill routes every command through the entrypoint the
governing memory policy permits (2026-11 activation follow-up).

The skill is text, so these are textual contracts a fresh agent can be held to:

  - the skill resolves ENTRYPOINT from policy before any tool call, with both routes
    spelled out (a guarded wrapper for one instance; the ordinary CLI for an authorized
    instance), a stop rule when neither is established, and no fallback to a default or
    held instance, a root override or bare `mem`;
  - every `mem <subcommand>` form the printed procedure (extract-knowledge.md) uses -
    inline or in a fenced block - is mapped explicitly: permitted forms to the same
    subcommand and arguments under ENTRYPOINT, held forms to their restriction;
  - the skill's own command examples use ENTRYPOINT, never bare `mem`;
  - `doctor` is confined to the route that permits it and named as a write, `init` is
    never a step, no default instance path is baked in, and the preflight claims only
    what each check proves.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = (ROOT / "skills" / "extract" / "SKILL.md").read_text()
PROCEDURE = (ROOT / "src" / "agent_memory" / "agent_integration" / "extract-knowledge.md").read_text()

PERMITTED = {"extract", "dedup", "get", "save"}
HELD = {"doctor", "init"}

# a command form is `mem <sub>` inline, or a line that begins with it (fenced block / shell line)
FORM = re.compile(r"(?:`|^)mem (?P<sub>[a-z]+)", re.MULTILINE)
PERMITTED_MAP = re.compile(
    r"^- `mem (?P<sub>[a-z]+)(?P<args>[^`]*)` → `ENTRYPOINT (?P<dsub>[a-z]+)(?P<dargs>[^`]*)`", re.MULTILINE)
HELD_MAP = re.compile(r"^- `mem (?P<sub>[a-z]+)` → (?P<rest>.+)$", re.MULTILINE)


def _norm(text):
    return re.sub(r"\s+", " ", text)


def _forms(text):
    return {m.group("sub") for m in FORM.finditer(text)}


def test_procedure_forms_are_detected_inline_and_fenced():
    fenced = {m.group("sub") for m in re.finditer(r"^mem (?P<sub>[a-z]+)", PROCEDURE, re.MULTILINE)}
    assert {"dedup", "extract"} <= fenced, "the procedure's fenced examples must be seen"
    assert _forms(PROCEDURE) == PERMITTED | {"doctor"}


def test_every_procedure_form_is_mapped_with_its_destination():
    permitted = {m.group("sub"): m for m in PERMITTED_MAP.finditer(SKILL)}
    held = {m.group("sub"): m.group("rest") for m in HELD_MAP.finditer(SKILL)}
    assert set(permitted) == PERMITTED
    assert set(held) == HELD
    assert _forms(PROCEDURE) <= set(permitted) | set(held)
    for sub, m in permitted.items():                       # same subcommand, same arguments, under ENTRYPOINT
        assert m.group("dsub") == sub and m.group("dargs") == m.group("args"), m.group(0)
    assert "held" in held["doctor"] and "step 2" in held["doctor"]
    assert "never" in held["init"]


def test_both_routes_stop_rule_and_no_fallback():
    norm = _norm(SKILL)
    assert "guarded entrypoint" in norm
    assert "`mem`, against the instance the policy names" in norm
    assert "stop and ask Brent" in norm and "before any tool call or delegate" in norm
    assert "not permission to use a default instance" in norm
    assert "a held instance is never a fallback" in norm
    assert "Policy restrictions override procedure examples" in norm
    assert "never fall back to bare `mem`, a root override, or a different instance" in norm
    assert "Name the ENTRYPOINT and instance in your report" in norm


def test_skill_examples_use_entrypoint_not_bare_mem():
    for line in SKILL.splitlines():
        probe = line.replace("`mem …`", "")                # the generic form in the routing sentence
        if not re.search(r"(?:`|^)mem ", probe):
            continue
        # bare `mem` may appear only in the mapping bullets, the routing table, or the no-fallback sentence
        assert probe.startswith("- `mem ") or probe.startswith("|") or "never fall back" in probe, line
    norm = _norm(SKILL)
    for needle in ("`ENTRYPOINT --version`", "`ENTRYPOINT doctor`", "`ENTRYPOINT stats`",
                   "`ENTRYPOINT extract --procedure`", "`ENTRYPOINT extract --candidates`",
                   "`ENTRYPOINT get <slug> --json`", "`ENTRYPOINT save --update`", "direct `ENTRYPOINT save`"):
        assert needle in norm, needle


def test_no_default_instance_path_and_no_init_step():
    assert "~/.agent-memory" not in SKILL
    assert ".agent-memory-personal" not in SKILL          # no laptop path baked in either
    assert "suggest `mem init`" not in _norm(SKILL)
    assert "do not run `init` from this skill" in SKILL
    assert "`MEM_KB_ROOT` only when the policy names that root" in SKILL


def test_preflight_claims_only_what_each_check_proves():
    preflight = _norm(SKILL.split("## 2. Preflight", 1)[1].split("## 3.", 1)[0])
    assert "`ENTRYPOINT --version`" in preflight
    assert "wrapper validated its instance before dispatching" in preflight
    assert "its success proves nothing about the instance" in preflight          # stats is telemetry
    assert "drains pending embeddings, which writes that instance's index" in preflight   # doctor named as a write
    assert "If neither the selected wrapper nor a policy-permitted check establishes the instance" in preflight
    assert "/api/version" in preflight and "/api/tags" in preflight
    assert "do NOT check the instance's embed queue or FTS5" in preflight
    assert preflight.count("stop before authoring any fan-out") >= 2
    assert "Never store knowledge elsewhere" in preflight


def test_report_names_entrypoint_and_limits():
    report = SKILL.split("## 4. Report", 1)[1]
    assert "ENTRYPOINT and instance used" in report
    assert "preflight limit" in report
