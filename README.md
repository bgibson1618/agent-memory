# agent-memory

A personal, cross-agent knowledge base: concepts captured once are retrievable by any AI coding agent, in any project, from a fresh session.

## Status

Early discovery. Built with [KodOS](https://github.com/) — a methodology-first agentic workflow. The current intake brief is in `INTAKE.md`.

## What this is

Brent's coding agents (claude, codex, agy) each start every session cold — knowledge learned in one session is lost to every other agent and project. agent-memory is a memory harness they can all reach: an OKF markdown store as the source of truth, plus a vector index (local Ollama embeddings — memory content never leaves the machine) and a knowledge graph, read through RRF fusion. Loosely descended from the agent-memory-harness capstone; deliberately minus its dreaming and classifier-routing features. This repo holds code only — KB data lives outside it and is never pushed.

## Getting oriented

This project follows the KodOS read order — there is no `CONTEXT.md`:

- `INTAKE.md` — the intake brief (problem, users, constraints, environment)
- `PRD.md` — product intent (once written)
- `ARCHITECTURE.md` — system shape and decisions (once written)
- `FEATURES.md` — the feature plan (once written)
- `IMPLEMENTATION.md` — current state and next step (during build)

Run `/kodos:go` to start or resume the workflow.

## Environment

Python 3.12+ via `uv` on WSL2 (Ubuntu); `uv run pytest` to verify. Local Ollama daemon for embeddings; graph backend under evaluation.
