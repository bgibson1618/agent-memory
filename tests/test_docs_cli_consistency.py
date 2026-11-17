"""Docs/CLI consistency (Stage 2, 2026-11; the project's recurring "L1 skew"):
the command list ARCHITECTURE.md's `cli` row advertises must equal the set of
subcommands cli.py registers; the PRD must not restate that surface as a prose
count; and both shipped instruction blocks must name the commands and the
safe-update flag agents are told to use. Proportional: a few set checks, not
a documentation framework."""

import re
from pathlib import Path

from agent_memory import blocks, cli

REPO = Path(__file__).resolve().parents[1]


def registered_commands() -> set:
    return set(re.findall(r'add_parser\(\s*"(\w+)"', Path(cli.__file__).read_text(encoding="utf-8")))


def architecture_commands() -> set:
    row = next(line for line in (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8").splitlines()
               if line.startswith("| `cli` |"))
    listed = re.search(r"entry point: `([^`]+)`", row).group(1)
    return {part.strip() for part in listed.split("·")}


def test_architecture_cli_row_matches_the_parser():
    assert architecture_commands() == registered_commands()


def test_prd_states_no_prose_command_count():
    text = (REPO / "PRD.md").read_text(encoding="utf-8")
    assert not re.search(r"\b\d+-command\b", text)


def test_shipped_blocks_name_the_agent_facing_surface():
    for name in (blocks.CLAUDE_BLOCK, blocks.AGENTS_BLOCK):
        text = blocks.render_block(name)
        for needle in ("mem search", "mem save", "mem get", "mem extract --procedure",
                       "--expected-version", "mem pending", "mem retry"):
            assert needle in text, (name, needle)
