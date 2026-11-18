"""Managed agent-instruction blocks for the global CLAUDE.md / AGENTS.md.

Block text ships as package data (agent_integration/); `mem init` installs it
between clearly-delimited markers and refreshes in place - never duplicating,
never touching content outside the markers. The same package-data directory
carries the extract-knowledge procedure, served by `mem extract --procedure`.
"""

import os
import re
from importlib import resources
from pathlib import Path

CLAUDE_BLOCK = "claude-block.md"
AGENTS_BLOCK = "agents-block.md"
EXTRACT_PROCEDURE = "extract-knowledge.md"

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


# `mem extract --procedure --entrypoint NAME` (D28). The caller resolved NAME
# from its memory policy and ran that policy's preflight; the printed procedure
# then names NAME in every command it shows and leaves preflight to the caller,
# so a guarded entrypoint's held `doctor` never appears as a step.
PROCEDURE_FORMS = ("extract", "dedup", "get", "save")
_FORM = re.compile(r"(?:^|(?<=`))mem (?=(?:extract|dedup|get|save)\b)", re.MULTILINE)
_NAME_PART = re.compile(r"[A-Za-z0-9._+-]+\Z")
_PREFLIGHT_HEAD = "## 0. Preflight\n\n"
_NEXT_HEAD = "\n## 1. "
_CALLER_PREFLIGHT = (
    "`{name}` was resolved by your caller from its memory policy, and that\n"
    "policy's preflight ran before this procedure was printed (for `/mem:extract`,\n"
    "the skill's preflight step). Do not repeat it here, and never run a command\n"
    "`{name}` holds - its refusals are final. `mem extract` and `mem dedup` need\n"
    "the local embedding daemon; if either refuses for a reason that preflight\n"
    "could not see, surface the refusal to Brent and stop - never store knowledge\n"
    "elsewhere as a workaround.\n"
)


def check_entrypoint(name: str) -> str:
    """One command name, or one absolute path; nothing a shell would split or expand."""
    parts = name[1:].split("/") if name.startswith("/") else [name]
    if not name or name.startswith("-") or not all(
        _NAME_PART.match(part) and part not in (".", "..") for part in parts
    ):
        raise ValueError(
            "--entrypoint takes one command name or one absolute path (letters, digits"
            " and . _ + -, with / only between path components); no spaces, quotes or"
            f" shell characters - use a wrapper script for a command with arguments; got {name!r}"
        )
    return name


def render_procedure(entrypoint: str | None = None) -> str:
    """The extract-knowledge procedure; with an entrypoint, as that caller runs it."""
    text = render_block(EXTRACT_PROCEDURE)
    if entrypoint is None:
        return text
    name = check_entrypoint(entrypoint)
    start = text.index(_PREFLIGHT_HEAD) + len(_PREFLIGHT_HEAD)
    end = text.index(_NEXT_HEAD, start)
    text = text[:start] + _CALLER_PREFLIGHT.format(name=name) + text[end:]
    return _FORM.sub(lambda _m: name + " ", text)


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
