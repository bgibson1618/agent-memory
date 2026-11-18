"""D28 - `mem extract --procedure --entrypoint NAME` prints the extract-knowledge procedure as
the caller runs it: every command form names NAME (inline and fenced, arguments unchanged), the
preflight section is left to the caller that resolved NAME from its memory policy (so a guarded
entrypoint's held `doctor` never appears as a step), and nothing else changes. Without the option
the output stays the portable package artifact. Values a shell would split or expand are refused.
"""

import re

import pytest

from agent_memory import blocks



def _forms(text, cmd):
    """(subcommand, rest of its line) for every command form `cmd <sub>` at a command position."""
    form = re.compile(rf"(?:^|(?<=`)){re.escape(cmd)} (?P<sub>extract|dedup|get|save)\b", re.MULTILINE)
    return [(m.group("sub"), text[m.end():].split("\n", 1)[0]) for m in form.finditer(text)]

BARE_MEM = re.compile(r"(?:^|[^A-Za-z0-9_./-])mem(?:[^A-Za-z0-9_.-]|$)", re.MULTILINE)


def _sections(text):
    head, rest = text.split("## 0. Preflight\n\n", 1)
    preflight, tail = rest.split("\n## 1. ", 1)
    return head, preflight, tail


def test_default_output_is_the_package_artifact(mem):
    r = mem("extract", "--procedure")
    assert (r.returncode, r.stderr) == (0, "")
    assert r.stdout == blocks.render_block(blocks.EXTRACT_PROCEDURE) == blocks.render_procedure()
    assert "run `mem doctor` first" in r.stdout                    # the portable preflight stays


@pytest.mark.parametrize("name", ["synthkb", "mem-synth", "/opt/example/bin/mem-wrapper", "mem"])
def test_every_command_names_the_entrypoint_and_nothing_else_changes(mem, name):
    r = mem("extract", "--procedure", "--entrypoint", name)
    assert (r.returncode, r.stderr) == (0, ""), r.stderr
    assert r.stdout == blocks.render_procedure(name)
    default = blocks.render_procedure()
    d_head, _, d_tail = _sections(default)
    e_head, e_pre, e_tail = _sections(r.stdout)
    # outside the preflight section, the ONLY difference is `mem ` -> `NAME ` at command positions
    for d, e in ((d_head, e_head), (d_tail, e_tail)):
        assert e == re.sub(r"(?:^|(?<=`))mem (?=(?:extract|dedup|get|save)\b)", name + " ", d, flags=re.M)
    # every form the default shows is present, same subcommand and arguments, under NAME
    # outside preflight: the same forms in the same order, with the same arguments
    d_forms = _forms(d_head + d_tail, "mem")
    e_forms = [(sub, rest.replace(f"`{name} ", "`mem ")) for sub, rest in _forms(e_head + e_tail, name)]
    assert len(d_forms) >= 14 and e_forms == d_forms
    if name != "mem":
        assert _forms(r.stdout, "mem") == []
    for needle in ("dedup /tmp/candidates.json --json > /tmp/dedup-report.json",
                   "dedup --adjudicate <log.run_id> --candidate",
                   "get <slug> --json", "save --update --slug <slug> --expected-version",
                   "extract --candidates /tmp/candidates.json --json"):
        assert f"{name} {needle}" in r.stdout, needle
    # the caller owns preflight: no doctor step, the hold rule and the stop rule are stated
    assert "doctor" not in e_pre and "doctor" not in r.stdout.replace("/mem:extract", "")
    assert f"never run a command\n`{name}` holds" in e_pre
    assert "surface the refusal to Brent and stop" in e_pre
    assert "never store knowledge" in e_pre


def test_no_bare_mem_command_remains():
    text = blocks.render_procedure("synthkb")
    assert not BARE_MEM.search(text.replace("/mem:extract", "")), BARE_MEM.search(text)
    assert BARE_MEM.search(blocks.render_procedure())             # the default does name `mem`


@pytest.mark.parametrize("value", ["", "uv run mem", "mem;true", "$(id)", "`id`", "a'b",
                                   "./mem", "bin/mem", "-x", "/opt/../mem", "/", "/opt/bin/"])
def test_values_a_shell_would_split_or_expand_are_refused(mem, value):
    r = mem("extract", "--procedure", f"--entrypoint={value}")
    assert r.returncode == 1
    assert r.stdout == ""
    lines = r.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error: --entrypoint takes one command name")
    assert repr(value) in lines[0]


def test_entrypoint_without_procedure_is_refused(mem):
    r = mem("extract", "--entrypoint", "synthkb")
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr.strip().splitlines() == ["error: --entrypoint applies only to --procedure"]
    r = mem("extract", "--candidates", "[]", "--entrypoint", "synthkb")
    assert (r.returncode, r.stdout) == (1, "")
    assert r.stderr.strip().splitlines() == ["error: --entrypoint applies only to --procedure"]


def test_printing_needs_no_kb_and_no_daemon(mem, kb):
    # the fixture's KB root is never initialised and its Ollama URL is a closed port
    r = mem("extract", "--procedure", "--entrypoint", "/opt/example/bin/mem-wrapper")
    assert (r.returncode, r.stderr) == (0, "")
    assert not kb.kb.exists()
