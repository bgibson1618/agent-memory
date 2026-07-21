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
