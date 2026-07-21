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

## Wave 3 checkpoint — fresh-eyes review  (DRIFT → remediated · 2026-07-21)
Wave committed `6bf8d5e`. Deterministic half green. Fresh-eyes review: **ran this wave**
(mandatory after 2 deferrals) — cold codex reviewer `kodos-sanity-w3-20260721`, paths-only,
read-only. **VERDICT: DRIFT**, 4 validated findings; `run.needs_you` set, then remediated in
the same engagement:
1. (certain) agents-block advertised F6's unbuilt `--no-work` → flag mention removed from the
   installed block; F6 restores flag docs when the flag exists.
2. (firm) F4 mismatch-dim test wording read as save-refusal → comment now names the
   vector-index write; refusal was already machine-asserted (no vector row, meta unchanged).
3. (firm) F2 one-commit criterion had a no-op-update hole (identical content, same-second
   stamp → success with zero commits) → no-op updates now report `unchanged` with no commit;
   `MEM_NOW` clock seam + regression test pin it.
4. (firm) `mem init` routed through the mutating doctor drain, breaking idempotence semantics →
   `run_checks(mutate=False)` non-mutating path for init; regression test proves a queued
   embed survives re-init with the daemon up.
Remediation proof: `uv run pytest` → **56 passed** (54 + 2 regression). Learnings captured
(seam `checkpoint`): L1 doc-vs-CLI reconcile check, L2 non-mutating init verification,
L3 exact-invariant no-op edges. `run.needs_you` cleared. Walkthrough (F36): CLI path exists
but fused search (F6) not yet — deferred to the wave-4 line.

## Wave 4 dispatch  (2026-07-21)
Executor: roster (auto, claude role-default). Ready set: **F6 (fusion) + F7 (concurrency)**.
F6's brief carried learnings block [L1] (prefilter match on "--no-work") + explicit scope note:
restoring the flag sentence to agents-block is in-scope once the flag exists.

## F6 — Fused search  (proved · test · 2026-07-21)
**Route:** `fusion.py` (RRF k=60; exact ties break lexical > vector > graph, then slug) +
three-leg orchestration in `search.py`; zero-cosine vector hits carry no RRF credit; graph leg
= 1-hop seed-neighbor expansion (link > topic weighted); `[work]` marking + `--no-work`;
agents-block flag sentence restored **with** the flag (L1 honored).
**Decisions:** sensitivity field in `--json` only on work hits (preserves F3's 4-key contract);
1-hop expansion (within ARCHITECTURE's 1–2-hop; networkx still unneeded).
**Proof:** parent applied + `uv run pytest` → 62 passed; live fused paraphrase search verified
in the walkthrough (below), including the cold-window re-test after remediation.

## F7 — Concurrent-session write safety  (proved · test · 2026-07-21)
**Route:** test-only slice — the F2/F3 locking discipline already satisfied the criteria; added
the permanent contention proof: 10-way distinct-slug race, 8-way same-slug race, 8-way
`--update` race, with a flock start-barrier so contention is deterministic, asserting zero
`index.lock` / database-is-locked / traceback across all racers.
**Proof:** parent applied + `uv run pytest` → **65 passed**.

## Wave 4 checkpoint + walkthrough  (F36 finding → remediated · 2026-07-21)
Deterministic half green. Fresh-eyes review: deferred — ran wave 3, 1 wave ago (1st deferral of
the new cycle). **Walkthrough (F36): RAN — first integrated pass** (init → saves incl. a
work-tagged concept → fused search → `--no-work` → `get --related` → daemon-down degradation;
evidence: `.kodos/evidence/walkthrough/wave4-walkthrough.txt`). **One validated finding**
(firm): the fused paraphrase search lost its semantic leg on first contact after idle — mem's
`num_ctx` 8192 request forces an Ollama model RELOAD that exceeded the 2.0s query budget;
observed live ("semantic leg skipped (timed out)" with a warm daemon). `run.needs_you` set →
remediated in-engagement → cleared: query-embed budget raised to 2.5s (inside the NFR's <3s
cold search) with a `MEM_EMBED_QUERY_TIMEOUT` seam; save path keeps its strict 500ms.
Re-test reproduced the exact cold window (forced unload + default-ctx reload) — first search
now succeeds. 65 passed post-fix. Learning L4 captured (num_ctx reload class). Ops follow-up
for Brent: pin `OLLAMA_KEEP_ALIVE` in the systemd override to shrink the window structurally.
