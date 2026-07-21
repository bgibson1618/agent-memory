"""Managed agent-instruction blocks for the global CLAUDE.md / AGENTS.md.

Block text ships as package data (agent_integration/); `mem init` installs it
between clearly-delimited markers and refreshes in place - never duplicating,
never touching content outside the markers.
"""

import os
import re
from importlib import resources
from pathlib import Path

CLAUDE_BLOCK = "claude-block.md"
AGENTS_BLOCK = "agents-block.md"

_SPAN = re.compile(
    r"<!-- BEGIN AGENT-MEMORY BLOCK.*?<!-- END AGENT-MEMORY BLOCK -->\n?",
    re.DOTALL,
)


def render_block(name: str) -> str:
    text = (
        resources.files("agent_memory")
        .joinpath("agent_integration", name)
        .read_text(encoding="utf-8")
    )
    return text.rstrip("\n") + "\n"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".mem-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def status_of(path: Path, name: str) -> str:
    """One of: current | missing | no-block | duplicate | stale."""
    if not path.is_file():
        return "missing"
    text = path.read_text(encoding="utf-8")
    spans = _SPAN.findall(text)
    if not spans:
        return "no-block"
    if len(spans) > 1:
        return "duplicate"
    if spans[0].rstrip("\n") != render_block(name).rstrip("\n"):
        return "stale"
    return "current"


def install(path: Path, name: str) -> str:
    """Install or refresh the managed block. Returns installed|refreshed|unchanged."""
    block = render_block(name)
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, block)
        return "installed"
    text = path.read_text(encoding="utf-8")
    match = _SPAN.search(text)
    if match is None:
        if not text.strip():
            new = block
        else:
            sep = "\n" if text.endswith("\n") else "\n\n"
            new = text + sep + block
        _atomic_write(path, new)
        return "installed"
    # Replace every existing span (healing duplicates) with one fresh block at
    # the position of the first.
    start = match.start()
    stripped = _SPAN.sub("", text)
    new = stripped[:start] + block + stripped[start:]
    if new == text:
        return "unchanged"
    _atomic_write(path, new)
    return "refreshed"
