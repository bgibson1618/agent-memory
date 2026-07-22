# agent-memory

A personal, cross-agent knowledge base: concepts captured once are retrievable by AI coding agents, in any project, from a fresh session.

## Status

**Built — all 12 features proved** (see `IMPLEMENTATION.md` for the generated snapshot and `BUILD_LOG.md` for how). Developed with KodOS, a methodology-first agentic workflow.

## What this is

Brent's coding agents each start every session cold — knowledge learned in one session is lost to every other agent and project. agent-memory is a memory harness: an OKF markdown store as the source of truth, plus a rebuildable lexical index (SQLite FTS5), a vector index (local Ollama embeddings — memory content never leaves the machine), and a derived wikilink/topic graph, read through RRF fusion. Loosely descended from the agent-memory-harness capstone; deliberately minus its dreaming and classifier-routing features.

**Vendor scope (DECISION_LOG D1):** memory work is restricted to approved vendors — Claude (Anthropic) and Codex (OpenAI). Ambient behavior (unprompted save/search) is claimed and proved on Claude; for codex/agy the v1 claim is installation of the AGENTS.md instruction block only. Antigravity/Gemini-backed agents are excluded from memory work entirely.

This repo holds code only — KB data lives in `~/.agent-memory` (a local git repo with **no remote**, a hard confidentiality line) and is never pushed.

## Using it

```bash
uv tool install --editable .   # installs `mem`
mem init                       # creates ~/.agent-memory, verifies Ollama, installs agent blocks
mem doctor                     # re-checks everything
mem save --title "..." --topics "..."   # capture (reads body from stdin)
mem search "anything"          # fused lexical + semantic + graph search
mem extract --procedure        # prints the extract-knowledge choreography
```

Requires a local Ollama daemon with `nomic-embed-text:v1.5` for the semantic leg; with Ollama down, saves queue their embeddings and search degrades to lexical + graph with a one-line warning.

## Getting oriented

This project follows the KodOS read order — there is no `CONTEXT.md`:

- `INTAKE.md` → `PRD.md` → `NFR_UX.md` → `ARCHITECTURE.md` → `FEATURES.md` — discovery artifacts
- `IMPLEMENTATION.md` — generated build snapshot (do not hand-edit)
- `BUILD_LOG.md` — append-only build journal; `DECISION_LOG.md` — durable decisions and why

Run `/kodos:go` to resume the workflow.

## Environment

Python 3.12+ via `uv` on WSL2 (Ubuntu); `uv run pytest` to verify (the netns egress guard needs `MEM_REQUIRE_NETNS=1` to be asserted rather than skipped). Runtime deps: numpy + PyYAML only; the graph is a derived in-process structure — no graph database.
