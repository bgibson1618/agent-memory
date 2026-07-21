# BUILD_LOG — agent-memory

Append-only journal of the build (KodOS F16): per-feature routes, decisions, and proof
outcomes; wave checkpoint lines. Parent-written only.

## Wave 1 dispatch  (2026-07-21)
Executor: **roster** (mode auto; backend `claude` via role-default — no pin). Cockpit:
http://127.0.0.1:48947/ (already live for this workspace). Context sensor: Tier 1, 34% —
healthy. Ready set: **F1** (sole root). Run `kodos-F1-20260721T2050Z` dispatched with the
delegation-contract brief (paths-only; no retry/learnings blocks — first attempt, no store).

## F1 — Initialized, verified KB home  (proved · test · 2026-07-21)
**Route:** src-layout `agent_memory` package (uv_build, `mem` entry point), stdlib-only:
`initcmd` (layout + git-no-remote + managed blocks, idempotent, offline-safe) + `doctor`
(8 checks, `--json`, nonzero on fail); subprocess tests against isolated HOME + fake/closed-port
Ollama via `MEM_OLLAMA_URL`. Delivered as F1.patch (roster session write-blocked; honest
`ok: false` — proof not executable in its seat).
**Decisions:** managed-block targets `~/.claude/CLAUDE.md` + `~/.agent-docs/AGENTS.md`
(env-overridable `MEM_CLAUDE_MD`/`MEM_AGENTS_MD`); init warns-never-fails, doctor is the
failing surface; `MEM_EMBED_MODEL`/`MEM_EMBED_DIMS` seams; KB repo gets local git identity +
gpgsign off; AGENTS block carries the D1 Antigravity exclusion verbatim.
**Proof:** parent applied the patch and ran `uv run pytest` → **13 passed** (11 F1 + 2
preflight); real-env smoke: `mem doctor` diagnoses 5/8 with actionable one-liners, exit 1.
Note: the late-remote criterion's write-path-warn half is a `gitkb` seam consumed by F2's
save — held to at F2 reconcile.

## Wave 1 checkpoint  (CLEAN · 2026-07-21)
Wave committed as `ee5eda7`. Deterministic half green (ledger + state validators, scheduler
coherent: F1 proved, F2 ready). Fresh-eyes review: **deferred — 1st consecutive deferral**
(single-feature scaffold wave, nothing integrated); fires by wave 3 at the latest.
Walkthrough (F36): no integrated path yet — no-op. Context sensor flapping Tier 1↔0 between
invocations (34% when readable) — noted, not a gate.

## F2 — Durable concept capture  (proved · test · 2026-07-21)
**Route:** clean-room `okf.py` (DECISION_LOG D2) + `store.py` (flock write-lock, atomic
temp+rename, per-path git commit) + save/get/list CLI; `MEM_FAULT` crash seam for the
atomicity proof; write-path remote warning consumed from the F1 holdover. Delivered as
F2.patch (`ok: false` — execution gated in the builder's seat).
**Decisions:** D2 clean-room (capstone unreadable from the build seat; pre-authorized
fallback; flagged for Brent) · `--update` requires an existing concept, replaces fields,
preserves `created` · one path-scoped commit per save (never sweeps unrelated KB changes) ·
dead-writer temp sweep under the lock.
**Proof:** parent applied the patch and ran `uv run pytest` → **27 passed** (14 F2 + 11 F1 +
2 preflight); pyyaml re-lock folded into the wave commit. All six criteria test-mapped; the
F1 holdover (write warns on late remote) is proven by `test_save_warns_while_a_remote_is_configured`.

## Wave 2 checkpoint  (CLEAN · 2026-07-21)
Wave committed as `4b52573`. Deterministic half green (ledger + state validators, scheduler
coherent: F1+F2 proved; F3/F4/F5 ready). Fresh-eyes review: **deferred — 2nd consecutive
deferral** (single-feature wave); **mandatory at wave 3**. Walkthrough (F36): save/get/list
exists but no retrieval path yet — no-op.

## Wave 3 dispatch  (2026-07-21)
Executor: roster (auto, backend claude role-default). First parallel fan-out: **F3 (lexical) +
F4 (vector) + F5 (graph)**, one builder each, concurrent — dependency-independent by
construction.

## F3 — Keyword search  (proved · test · 2026-07-21)
**Route:** FTS5 table (slug UNINDEXED / title / desc / body / topics) in `.index/mem.db` with
WAL+busy_timeout; self-healing mtime+size sync on every search; in-lock upsert on save; quoted
OR-joined terms; BM25 weights 4/2/1/2; `mem search` text/`--json`.
**Decisions:** index self-heals (no manual rebuild path needed); save-path index failure warns,
never fails a committed save; empty `--json` prints `[]` on stdout, quiet line on stderr.
**Proof:** parent applied cleanly, `uv run pytest` → 36 passed; real-daemon smoke: literal
search returns the BM25-ranked hit with snippet.

## F4 — Semantic recall  (proved · test · 2026-07-21)
**Route:** vector leg in `mem.db` (namespaced vectors/embed_queue/vector_meta); strict-timeout
embed-or-enqueue save hook; CLI-central bounded drain (~3); doctor/reindex full drain; numpy
cosine top-k; nomic `search_document:`/`search_query:` prefixes with explicit `num_ctx` 8192.
Store/cli hunks conflicted with F3's (parallel siblings) — parent hand-merged at reconcile.
**Decisions:** enqueue-first-then-embed-then-dequeue (crash leaves a queued item, never a lost
save); mixed model-tag refused like mixed dims; `mem reindex` added vector-scoped (F8 extends).
**Proof:** parent merged + `uv run pytest` → 45 passed; **live degradation proof**: cold model
→ both saves enqueued (timeout honored), model warmed → two ordinary invocations drained
queue 2→0, vectors=2, meta stamped (model+digest+768).

## F5 — Concept graph  (proved · test · 2026-07-21)
**Route:** clean-room `graph.py` over the OKF markdown: wikilink/`related` direct edges +
topic-node memberships; mtime_ns/size-keyed JSON cache at `.index/graph.json`; `mem get
--related` (neighbors key) in text/`--json`. Import hunk hand-merged.
**Decisions:** networkx deferred to F6 (1-hop needs no traversal lib); no inline edge-cache
update in the save path (mtime sweep guarantees freshness, avoids sibling collisions); node
identity = file stem (Obsidian's link target), existing files only.
**Proof:** parent applied + `uv run pytest` → **54 passed** (full suite); real-daemon smoke:
`get --related` returns the wikilink neighbor + topic co-member.
