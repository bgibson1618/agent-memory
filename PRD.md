# agent-memory — Product Requirements Document

> A personal, cross-agent knowledge base for Brent's AI Education Engineer role: concepts
> captured once — by Brent or autonomously by his coding agents — are retrievable by any agent,
> in any project, from a fresh session. Grounded in `INTAKE.md`; backend choices grounded in
> `research/backend-research.md` (gated 2026-07-21).

- **Owner:** Brent (@bgibson1618)
- **Status:** Draft v0.1 — refined with Brent at the PRD session
- **Last updated:** 2026-07-21
- **Source:** `INTAKE.md`

---

## 1. Goal

Brent's knowledge compounds instead of evaporating: a concept captured once is retrievable by
any coding agent, in any project, from a fresh session — without the memory system demanding
his attention.

## 2. User / Persona

- **Primary:** Brent — an AI Education Engineer who runs daily work through AI coding agents
  and is absorbing a flood of new concepts he wants integrated into his AI workflow.
- **Secondary (and the main operator):** the coding agents themselves — Claude Code in v1 —
  saving and searching autonomously on Brent's behalf.

## 3. What the User Does Today

Claude Code's built-in file memory (per-project, Claude-only), chat history, and scattered
notes. No cross-agent access, no semantic recall, no concept graph — knowledge learned in one
session is effectively lost to every other agent and project.

## 4. Use Cases

1. **Silent recall** — mid-task, an agent queries the KB and retrieved concepts shape its
   output unprompted (e.g. the architect agent consulting instruction theory while designing a
   math tutoring app).
2. **Overt question** — Brent asks "how many concepts should a lesson include?"; the agent
   searches the KB and answers from stored learning-science data.
3. **Autonomous capture** — an agent encounters a durable concept mid-session and saves it
   unprompted, in one command.
4. **Extract knowledge** — Brent points the system at a document; it extracts candidate
   concepts, dedups them against the KB, saves what's new, and reports added vs. skipped.
5. **Manual capture** — Brent (or an instructed agent) saves a concept explicitly.
6. **Browse / audit** — Brent opens the KB directory in Obsidian (the wikilink graph renders
   natively) or lists it via the CLI.

## 5. In Scope (v1)

- OKF markdown store as the sole source of truth.
- Vector index built with local Ollama embeddings.
- Derived knowledge graph: wikilink/frontmatter edges parsed into in-process traversal (with a
  cache); no graph daemon.
- Fused (RRF) search across markdown, vector, and graph backends; writes go to all backends.
- Topic tags and a per-memory sensitivity field.
- The `mem` CLI: save / search / extract / list (exact surface fixed at architecture).
- The extract-knowledge document pipeline (extract → dedup → save new → report).
- **Agent integration:** an instruction block/skill teaching agents when to save and search
  unprompted — the invisibility mechanism — delivered both for Claude Code (global
  `CLAUDE.md`/skill) and as a provider-neutral `AGENTS.md` block so codex/agy delegates get the
  same ambient awareness (same content, two files).
- Degraded-but-working writes when the Ollama daemon is down (save lands; embedding catches up).

## 6. Non-Goals

- Dreaming/daydreaming consolidation — **later, if ever**.
- Classifier routing — **never**; retired by capstone evidence (D021/D023/D045).
- MCP server — **later, explicitly planned** (the cross-agent port).
- Session hooks / auto-injection of memories — **later**.
- Codex/agy integration beyond the CLI + `AGENTS.md` instruction block — **later**; the MCP
  server is the richer cross-agent seam. (CLI *access* was never gated — any agent on this
  machine can run `mem`.)
- Benchmark/eval harness — **never** for this project.
- Multi-user support, cloud sync anywhere on the storage path — **never**.

## 7. Success Criteria

1. From a fresh Claude session in a *different project*, a fused search for a previously saved
   concept returns it in the top results.
2. During a normal work session, Claude Code saves at least one concept *without being asked* —
   the invisibility test.
3. Extract-knowledge on a real document saves new concepts, skips near-duplicates, and reports
   which was which.
4. With the Ollama daemon stopped, a save still lands and becomes semantically searchable after
   the daemon returns.
5. The full storage/index path works with networking disabled (offline test passes).
6. Opening the KB directory in Obsidian renders the concept graph with zero export/sync steps.

## 8. Constraints

- WSL2 Ubuntu; Python 3.12+ via `uv`; `uv run pytest` is the verification command.
- **OKF format is mandatory** for the markdown store.
- **Embeddings are local-only** (employer confidentiality — content never leaves the machine at
  storage/index time): `nomic-embed-text:v1.5` default, `qwen3-embedding:0.6b` step-up; `num_ctx`
  must be set explicitly (Ollama's packaging defaults to 2K vs. the model's native 8K).
- Graph is **derived** from wikilinks/frontmatter, traversed in-process — no graph daemon.
- **KB data lives at `~/.agent-memory/`** — a dedicated directory that is itself a git repo with
  **no remote** (free history/diffs/recovery; backup remains a local concern). Never inside this
  code repo; never pushed to a personal remote.
- CLI name: **`mem`**.
- Write-to-all + RRF fusion is settled design; a rerank seam may be added later.

## 9. Open Questions

- Dedup similarity thresholds for extract-knowledge (capstone D024 showed lexical similarity
  can't separate near-dups; a real local embedder changes the calculus — calibrate empirically).
- Sensitivity-tag recall semantics: what the filter does by default at search time.
- Exact `mem` subcommand surface and flags (architecture decides).
