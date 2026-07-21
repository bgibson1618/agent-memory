# Intake — agent-memory

> First discovery artifact. A structured brief of what we're building and why, captured with the
> user. Feeds the PRD. Authored by `/kodos:intake`; revise it by hand or re-run the skill.

- **Captured:** 2026-07-21
- **Status:** Draft — confirmed with the user at intake

## Problem
Brent has just started a new role as an AI Education Engineer and is absorbing a flood of new
concepts. Nothing durably captures what he learns in a form his coding agents can use — each
session and each agent (claude, codex, agy) starts cold, so learned knowledge never compounds.

## Target user / persona
Brent himself — an engineer who runs his daily work through AI coding agents on multiple backends
(claude / codex / agy, orchestrated via agent-roster). The direct consumers of the system are as
much the *agents* as Brent: they save and search on his behalf during ordinary work sessions.

## What they do today
Claude Code's built-in file memory (per-project, Claude-only), chat history, and scattered notes.
No cross-agent access, no semantic recall, no graph of related concepts. Knowledge learned in one
session is effectively lost to every other agent and project.

## Goal / what success looks like
Before: every session starts cold; learning evaporates. After: a concept captured once — by Brent
or autonomously by an agent — is retrievable by any agent, in any project, from a fresh session,
via one fused search over markdown, vector, and graph backends.

## Success criteria
- A concept saved via the CLI is retrievable by fused (RRF) search from a fresh Claude session in a different project.
- Relevant results rank in the top handful for concept queries.
- Capture is a single low-friction command an agent can run unprompted.
- No memory content leaves the machine at storage/index time (local embeddings only).
- KB data lives outside this git repo and is never pushed to a personal remote.

## Vision north-star
*(Elicited from Brent, 2026-07-21.)*
- **Feel like:** "Honestly, I want the memory harness to be almost invisible. I want my coding
  agent to have the autonomy to save concepts and search the KB as he sees fit during any
  session." The harness "should run behind the scenes as much as possible." He also wants an
  **"extract knowledge" process** "that can review a document, look for relevant concepts,
  compare those concepts to those already stored in memory, and then save the new concepts."

## Usefulness — in the user's own words
"As an example, let's say I'm creating a math tutoring app. The memory harness could silently
impact the build because my architect agent will query the KB about proper instruction theory
during the design phase. Or I could overtly ask my coding agent how many concepts I should
include in a single lesson, and he would search the KB for data from learning scientists to
provide an answer."

## Constraints
- **Employer confidentiality (non-negotiable):** memory content never leaves the machine at
  storage/index time → local Ollama embeddings only; KB data never committed to this repo or
  pushed to any personal remote. A per-memory sensitivity field is kept in the schema as a
  recall-time filter.
- **OKF format is mandatory** for the markdown store (Brent's explicit call — portable,
  spec-conformant markdown + YAML frontmatter, per the capstone lineage).
- **Settled design (capstone-grounded, do not relitigate without Brent):** no classifier router —
  write-to-all backends, RRF fusion reads, rerank seam left for later (capstone D021/D023/D045).
- **Claude Code first**; MCP server port is a later phase.
- Host: WSL2 Ubuntu laptop, RTX 3070 (8 GB VRAM), 19 GB RAM. Ollama not yet installed.
- Global scope with topic tagging (not per-project). Two-tier relationship with Claude Code's
  built-in memory: built-in keeps operational/session facts; the KB owns durable knowledge —
  pointers between them, never duplicated content.

## Scope notes (in / out)
- **In:** OKF markdown store (source of truth) · vector index (local Ollama embeddings) ·
  knowledge graph · RRF fusion read path · write-to-all write path · topic tags + sensitivity
  field · a CLI usable by Claude Code and by Brent · the "extract knowledge" document-ingestion
  process (review a document → find concepts → dedup against the KB → save new ones).
- **Out (v1):** dreamer/daydreamer consolidation features · classifier routing · MCP server
  (planned later) · session hooks / auto-injection (later) · eval-benchmark harness ·
  non-Claude agent integration beyond whatever the CLI already affords.

## Environment contract
The build/run environment, pinned now so preflight and verification are unambiguous later.

| Aspect | Value |
| --- | --- |
| **Runs where** | Local CLI + Python library in WSL2; KB data in a local directory outside this repo (exact path fixed at architecture) |
| **OS / shell boundary** | WSL2 Ubuntu; all files and tools on the Linux side under `/home/...` |
| **Language / runtime** | Python 3.12+ via `uv` |
| **Toolchain** | `uv`, `pytest`, `git`, Ollama daemon (local) |
| **Verification command** | `uv run pytest` |
| **Key dependencies / services** | Ollama (local embeddings; model TBD by research) · graph backend TBD by research · no cloud services anywhere on the storage/index path |

## Open questions
- Knowledge-graph backend: Neo4j vs FalkorDB vs Obsidian-style derived wikilink graph vs embedded
  engines — researcher run in flight (see `discovery/checklist.json`).
- Default local embedding model (and step-up alternative) — same researcher run.
- CLI name and command surface.
- Exact KB data directory location and backup strategy (private backup remote?).
- Extract-knowledge dedup mechanics — capstone D024 showed lexical dedup can't separate near-dups;
  a real local embedder changes the calculus, but thresholds need calibration.
- Sensitivity-tag semantics: what the recall-time filter does by default.
- Do codex/agy get CLI access before the MCP port (the CLI is inherently agent-agnostic)?

---

*Next phase: **PRD** (`/kodos:prd`) turns this brief into `PRD.md`. Run `/kodos:go` to advance.*
