# Architecture - agent-memory

## Role
System shape and technical intent for this project — what it is, how it's built, and which
choices are settled vs. still open. Grounded in `PRD.md` (what we're building) and `NFR_UX.md`
(how it must behave / feel), with backend choices grounded in `research/backend-research.md`
(gated 2026-07-21). Some decisions here are **locked**; others are stated assumptions to
resolve during the build.

## Overview
agent-memory is a **local-first Python monolith** whose single organizing idea is: **markdown is
the database; everything else is a rebuildable index.** One `agent_memory` package (installed
via `uv tool install`, entry point `mem`) owns OKF markdown files under `~/.agent-memory/` as
the sole source of truth; three derived indexes — lexical (FTS5), vector (local Ollama
embeddings), graph (wikilink edges) — serve every read through RRF fusion. **No resident
process of ours, ever**: all work happens in-process at CLI invocation time (pending embeddings
retry on the next call); the only daemon on the machine is Ollama. The primary caller is an
agent; the CLI is never interactive and every read command speaks `--json`.

## Components
| Component | Responsibility | Notes |
| --- | --- | --- |
| `store` | OKF markdown read/write — one concept per file, atomic write; **a single inter-process write lock** serializes store mutation + git commit (retry w/ backoff, never fail an agent's save); auto-commit to the local git | The only irreplaceable state; everything else rebuilds from it. Deterministic slugs (lowercase alnum-hyphen, NFKD-folded); saving onto an existing slug **errors unless `--update`** — no silent overwrite |
| `okf` | The OKF schema contract: frontmatter (id/slug, title, description, type, `topics[]`, `sensitivity`, timestamps, `related[]`) + body with `[[wikilinks]]` | Conformance sourced from the capstone OKF spec (see Open Questions re: license/clean-room) |
| `index.lexical` | SQLite **FTS5** table over title/description/body/topics; BM25 ranking | Capstone-measured over hand-rolled keyword index (0.842 vs 0.825 recall@10, ~5× faster writes); ships in stdlib `sqlite3` |
| `index.vector` | Ollama `/api/embed` client; vectors as BLOBs in SQLite; **numpy brute-force cosine** at query time; pending-embed queue | ~30 MB / <10 ms at the 10k ceiling; model tag + digest + dims stamped in metadata, mixed-dim writes refused; `num_ctx` set explicitly; **embed calls carry strict per-purpose client budgets — save/opportunistic-drain 500 ms (timeout ⇒ enqueue, never block); query 2.5 s (`MEM_EMBED_QUERY_TIMEOUT` seam — absorbs moderate model-reload windows; a full cold reload (~3.8 s measured) instead degrades that one query to lexical+graph and warms the model for the next — learning L4, wave-6 evidence); full drain (doctor/reindex) 30 s**; sqlite-vec ANN is a later seam, not a v1 dep |
| `index.graph` | Parse `[[wikilinks]]` + frontmatter `related` into direct edges and `topics` into **topic nodes** (concept → topic → concept — never materialized pairwise edges, so a broad tag can't go quadratic); mtime-invalidated cache; in-process traversal (pure Python — 1–2-hop expansion needs no traversal lib; networkx/rustworkx remain a later seam) | The research-gated "derived graph" — no graph daemon; Obsidian renders the same links natively |
| `fusion` | RRF across the three legs; rerank seam (no-op in v1); `[work]` marking + `--no-work` filter | Write-to-all + fuse-on-read is settled design (capstone D021/D023/D045) |
| `extract` | The **deterministic half** of extract-knowledge: candidate concepts (JSON) in → validate → embed → dedup vs KB → save novel → report added/skipped/near-dup | No LLM inside the CLI; thresholds calibrated empirically (capstone D024); with Ollama unreachable it **refuses cleanly** (dedup requires embeddings) — nothing partially saved |
| `cli` | `mem` entry point: `init · save · search · get · list · extract · reindex · doctor` | stdlib argparse; never interactive; meaningful exit codes; `--json` on every read; one-line errors. **`mem init` owns setup**: creates `~/.agent-memory` + git init, verifies Ollama/models/FTS5, and installs/refreshes the agent-integration instruction blocks into the global `CLAUDE.md`/`AGENTS.md` (managed marker section); `mem doctor` re-checks all of it |
| `agent-integration/` | Shipped **as data, not code**: the CLAUDE.md + AGENTS.md instruction blocks (when to save/search unprompted) and the **extract-knowledge procedure** | The invisibility mechanism, vendor-scoped per DECISION_LOG D1: ambient awareness is claimed and proved on Claude; the AGENTS.md block carries the same instructions to approved-vendor consumers (Codex), but for codex/agy v1 claims installation only (F11); Antigravity/Gemini-backed agents are excluded from memory work entirely |

**The extract-knowledge procedure** (agent-side, per Brent's design): ≥2 fresh-eyed extractor
subagents read the document independently and propose concept candidates — **cross-backend via
agent-roster when present, inline subagents when absent** (the KodOS research-seam pattern) —
then ≥2 fresh-eyed reviewers verify the merged candidates (accurate? durable? well-formed?
correctly tagged?). Only survivors reach `mem extract --candidates`, which dedups against the
KB and saves. The CLI half is deterministic and testable; the choreography is prompt-tooling.

## Data Flow
Primary action — fused search (`mem search "spaced repetition" [--json]`):
```
mem search → embed query (Ollama, warm; skip leg + warn if daemon down)
  ├─ lexical leg: FTS5 BM25 top-k
  ├─ vector leg:  numpy cosine scan over BLOBs → top-k
  └─ graph leg:   seed from lexical∪vector hits → 1–2-hop expansion, link-weighted
→ RRF fuse (k=60, unweighted v1) → rerank seam (no-op) → mark [work] → text/JSON out
```
Write path (`mem save`): validate OKF → acquire the write lock → atomic write to
`concepts/<slug>.md` → `git commit` → update FTS5 in-line → release lock → embed
with a 500 ms save budget (timeout/down ⇒ enqueue) → single-line confirmation, < 1 s.
The graph leg keeps no inline structure to update — it is a derived, mtime-invalidated
cache rebuilt lazily on the next load.

**Consistency & concurrency (gate-hardened):**
- `.index/mem.db` runs **WAL mode + busy_timeout** (`PRAGMA journal_mode=WAL; busy_timeout=5000`)
  — concurrent readers never block, concurrent writers wait instead of throwing.
- **One inter-process write lock** serializes the store-mutation critical section (file write +
  `git commit` + index update), eliminating `.git/index.lock` collisions between concurrent
  agent sessions. Lock waits use retry-with-backoff; a save never errors on contention.
- **External-edit staleness sweep**: `mem.db` keeps a manifest of `(path, mtime, hash)`; every
  read command starts with a fast scandir sweep (~tens of ms at 10k files) and incrementally
  re-indexes changed/new/deleted files (FTS5 + edges inline, embeddings enqueued) — so Obsidian
  edits behind the CLI's back are picked up on the next search, no manual `reindex` needed.
- **Bounded opportunistic queue drain**: any `mem` invocation, after its primary work, drains up
  to ~3 queued embeds iff Ollama answers a fast health check — never blocking the caller's
  budget; `mem doctor`/`mem reindex` drain fully.
- **Egress guard mechanism**: the zero-egress proof (F12) runs the full command surface —
  including `init`/`doctor` — inside a **loopback-only network namespace** (`unshare --user
  --net`, `lo` up — the unprivileged userns+netns form, verified working on this host at
  preflight), which covers subprocess egress (git) that an in-process socket guard is
  structurally blind to; the in-process guard remains the fast inner layer.

Source of truth: `~/.agent-memory/concepts/*.md`. All of `.index/mem.db` (FTS5 + vectors +
edges + queue + metadata, one SQLite file) is disposable — `mem reindex` rebuilds it from the
markdown. Storage layout:
```
~/.agent-memory/
  concepts/<slug>.md    # OKF source of truth (Obsidian-openable)
  .index/mem.db         # derived: fts5 / vectors / edges / embed-queue / meta
  .git/                 # local history, auto-commit per write, NO remote
```

## External Dependencies
| Dependency | Purpose | Constraint |
| --- | --- | --- |
| Python 3.12+ via `uv` | Runtime + packaging (`uv tool install`, `uv run pytest`) | WSL2 Linux side only |
| Ollama | Local embedding daemon — `nomic-embed-text:v1.5` default, `qwen3-embedding:0.6b` step-up | localhost only; `num_ctx` explicit (packaging default 2K); systemd-managed, `OLLAMA_KEEP_ALIVE` pinned; the ONLY permitted network target on the storage/index/search path. **Provisioning is owned by `/kodos:preflight`**, not any feature. The base URL honors **`MEM_OLLAMA_URL`** (default `localhost:11434`) — the sanctioned test seam for up/down/hung daemon states; tests always run against an isolated `HOME`/KB root, never the real service or KB |
| numpy | Vector math (cosine scan) | Boring, ubiquitous |
| PyYAML | OKF frontmatter parse/serialize | — |
| ~~networkx~~ — not shipped | 1–2-hop expansion proved to need no traversal lib (pure Python in `graph.py`) | Re-enters as a seam only if deeper traversal ever lands (rustworkx the likely pick) |
| git (system binary, via subprocess) | KB history/auto-commit | Local repo, no remote — hard confidentiality line |
| pytest (dev) | Verification (`uv run pytest`) | The KodOS verification command |

No paid services, no cloud, no copyleft/SSPL components — $0 and Apache/MIT/PSF throughout.

## Key Assumptions
- **The 10k-concept ceiling holds.** Brute-force cosine and in-process traversal are sized to
  it. If the KB grows ~10×, the seams flip on: sqlite-vec for ANN, cached traversal for graph —
  without changing the markdown source of truth or the CLI contract.
- **Ollama GPU passthrough works on this WSL2 host as researched.** If not, CPU embedding of
  note-sized inputs still fits the < 1 s save budget at this scale.
- **FTS5 is compiled into the system Python's sqlite3.** Verify at preflight; fallback is a
  keyword index (worse, known cost from the capstone).
- **Concurrent agent writes are safe via the write lock + WAL, not via file structure alone** —
  the gate refuted the naive "conflict-free by design" claim (`git` index.lock and SQLite
  locking are shared choke points even with one-file-per-concept). One concept per file still
  eliminates the *merge* surface; the lock + busy timeouts make the choke points safe.
- **Frontier-agent extraction beats a local generative model** for concept identification —
  the reason extraction is agent-mediated. If a fully-local path becomes necessary (e.g. for
  work-confidential documents), a `--local` extraction mode is additive, not a redesign.
- **Auto-commit stays cheap** (~tens of ms per write) at KB scale; if it ever doesn't, batching
  commits is a flag away.
- **OKF conformance is achievable from the capstone's public spec** without dragging in the
  eval-harness machinery around it.

## Open Architecture Questions
- **Dedup threshold** — ✅ **resolved during build**: calibrated empirically at **0.79**
  (band 0.77–0.81, fp 0 / fn 0 on 26 measured pairs) — DECISION_LOG **D3**,
  `research/dedup-calibration.md`.
- **Graph-leg scoring** — v1 seeds traversal from the other legs' hits and expands 1–2 hops;
  the exact hop-decay/link-weight scoring gets fixed against real KB data during build.
- **RRF tuning** — start k=60, unweighted. Tune only if real usage shows a leg drowning others.
- **OKF porting posture** — ✅ **resolved at build start**: clean-room implementation from the
  format spec, no capstone code ported (DECISION_LOG **D2** — flagged for Brent's explicit
  confirmation at closeout).
- **Topic taxonomy** — free-form tags in v1; whether a curated topic list (and topic hub pages
  in the graph) earns its keep is a post-v1 review against real accumulated tags.
- **WAL checkpoint cadence** — keep `mem.db`'s WAL small without blocking readers; pick a
  `wal_checkpoint(PASSIVE)` strategy during build (gate Q3).

---

**Gate record:** cross-vendor adversarial review by `verifier-g7of` (antigravity backend,
2026-07-21) — verdict **PASS-WITH-FIXES**; all six findings (concurrency locking BLOCKER,
queue-drain / external-edit staleness / embed-timeout MAJORs, slug-collision + integration-
deployment MINORs) folded into this document. Full review: `research/architecture-review-2026-07-21.md`.

---

*This is a living document. It records the current design intent; revise it as the build teaches
us what's actually true.*
