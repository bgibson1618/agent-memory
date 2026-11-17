# agent-memory

A personal, cross-agent knowledge base: concepts captured once are retrievable by AI coding agents, in any project, from a fresh session.

## Status (2026-11-17)

Version 0.2.1. Verified by the test suite on every change: capture with read-version-checked
updates, keyword / semantic / graph search fused by RRF, external-edit resilience, the
extraction CLI with duplicate detection, and the zero-egress guard (`FEATURES.md` states each
feature's criteria; `tests/` carries its proof). The two *observed* features — ambient use by an
agent (F11) and the agent-side extraction procedure (F10) — are re-observed in bounded synthetic
exercises before a release is called verified (protocol in `FEATURES.md`; records in
`BUILD_LOG.md`). Host-mediated shared writes (`SHARED-WRITES.md`) are a private deployment mode
that is currently held: the four transport commands (`retry`, `pending`, `refresh`, `delete`)
act only on an instance provisioned for it and refuse everywhere else.

Originally built (2026-07) with KodOS, a methodology-first agentic workflow; the project now
follows a shared delivery workflow of small reviewed slices (see "Getting oriented"). The
earlier "all 12 features proved" snapshot is kept as dated history in `IMPLEMENTATION.md`.

## What this is

Brent's coding agents each start every session cold — knowledge learned in one session is lost to every other agent and project. agent-memory is a memory harness: an OKF markdown store as the source of truth, plus a rebuildable lexical index (SQLite FTS5), a vector index (embedding computation stays in local Ollama), and a derived wikilink/topic graph, read through RRF fusion. Loosely descended from the agent-memory-harness capstone; deliberately minus its dreaming and classifier-routing features.

**Vendor scope (DECISION_LOG D1):** memory work is restricted to approved vendors — Claude (Anthropic) and Codex (OpenAI). Ambient behavior (unprompted save/search) is claimed and proved on Claude; for codex/agy the v1 claim is installation of the AGENTS.md instruction block only. Antigravity/Gemini-backed agents are excluded from memory work entirely.

This repo holds code only — KB data lives in the selected instance root (default
`~/.agent-memory`; `MEM_KB_ROOT` selects an alternate instance, D15), each a local git repo
whose **only permitted remotes are the exact URLs listed in its `.allowed-remotes` file** (D1
amendment, 2026-10-15; nothing public, vendor-hosted or personal-cloud) — a hard
confidentiality line.

## Using it

```bash
uv tool install --editable .   # installs `mem` (editable: this worktree becomes the runtime)
mem --version                  # prints the version AND the package path actually imported
mem init                       # creates the instance root (default ~/.agent-memory;
                               # MEM_KB_ROOT=<path> for an alternate), verifies Ollama,
                               # installs the managed agent blocks into ~/.claude/CLAUDE.md
                               # and ~/.agent-docs/AGENTS.md (MEM_CLAUDE_MD / MEM_AGENTS_MD
                               # override those two paths)
mem doctor                     # re-checks everything, starting with a `runtime` identity
                               # line; note: it drains pending embeddings (writes the index)
mem save --title "..." --topics "..."   # capture (reads body from stdin)
mem search "anything"          # fused lexical + semantic + graph search
mem get <slug> --json          # read; returns the `version` an update must carry
mem save --update --slug <slug> --expected-version <version> ...   # safe update
mem extract --procedure        # prints the extract-knowledge choreography
```

Updates are read-version checked: `--update` without the `version` returned by the preceding
`mem get --json`, or with a stale one, is refused and nothing is written — re-read, reconcile,
resubmit; never retry blindly with a fresh token.

In Claude Code, `/mem:extract <document>` (from the repo's bundled `mem` plugin) is a
deterministic entry point for that choreography. It is deliberately the only slash command:
search and save stay ambient — the managed blocks installed by `mem init` make sessions use
them unprompted.

Requires a local Ollama daemon with `nomic-embed-text:v1.5` for the semantic leg. With Ollama
down, saves queue their embeddings; with Ollama down **or the semantic index not yet built**,
search answers from lexical + graph and says so in exactly one stderr warning line (the JSON
output stays a plain array).

## Releasing and running a frozen copy

A commit never deploys. `scripts/release.py` stages a revision into a read-only release
directory and, as a separate operator step, activates it (or rolls back) in a uv tool prefix;
`mem --version` and `mem doctor`'s `runtime` line say which package is actually imported. See
`RELEASE.md`, including what these tools write and how long to keep it.

## Getting oriented

- `README.md` (this file) → `ARCHITECTURE.md` → `FEATURES.md` → `DECISION_LOG.md` — current
  design, criteria and the reasons behind them.
- `RELEASE.md`; `SHARED-WRITES.md` (historical, held) — operations.
- Dated history, preserved and not regenerated: `INTAKE.md`, `PRD.md`, `NFR_UX.md`
  (discovery, 2026-07), `IMPLEMENTATION.md` (build snapshot, 2026-09-03), `BUILD_LOG.md`
  (append-only journal), `.kodos/` (the retired KodOS state).

The project follows a shared delivery workflow: small end-to-end slices, one receipt per
candidate (command, source and config identity, duration, counts, evidence paths), independent
review of each slice, and explicit, separately approved activation.

## Ops

No scheduled jobs are part of the package. `scripts/agent-memory-backup` is a historical,
machine-specific backup script (WSL/Windows paths) that is no longer wired anywhere; it stays in
the tree as history. Backups remain the operator's concern.

## Environment

Linux (developed on Ubuntu; the 2026-07 environment was WSL2). Python 3.12+ via `uv`;
`uv run pytest` verifies. The zero-egress guard's outer leg needs an unprivileged user
namespace: where one is available, run with `MEM_REQUIRE_NETNS=1` so its absence is a failure
rather than a visible skip. Runtime deps: numpy + PyYAML only; the graph is a derived
in-process structure — no graph database.
