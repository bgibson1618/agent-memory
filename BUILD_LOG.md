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

## F11 — Ambient agent integration  (proved · observed · 2026-07-21)
**Route:** deployment + observation, run by the parent (Brent's explicit go on the real-config
gate): `uv tool install --editable` → `mem` 0.1.0 on PATH; real `mem init` → KB home + managed
blocks in the real `~/.claude/CLAUDE.md` and `~/.agent-docs/AGENTS.md` (one block each,
existing content intact, doctor 9/9); KB seeded with four genuine learning-science concepts.
**Proof (observed, protocol-conformant):** staged session `f11-observe-1` — fresh claude
session, different project (`~/projects/tutor-scratch`), task on record and free of any memory
mention. Observed: **unprompted** `mem search --json` as the first substantive move → `mem get`
×4 → results grounded the deliverable; then **unprompted `mem save interleaving-effect`**
(correctly linked + topiced) after the agent noticed a KB gap. Both observed criteria in one
session (protocol allowed 3). Evidence: `.kodos/evidence/F11/`. codex/agy = installation-only
claim, covered by F1 tests + the real AGENTS.md block. Brent judges "unprompted" per protocol —
task text preserved; veto open.

## Wave 5 dispatch  (2026-07-21)
Executor: roster (auto, claude role-default). Ready set was F8 + F9 + F11: builders dispatched
for F8/F9; **F11 held at the §3b user gate** (installs into Brent's real global agent config)
and released by Brent's explicit "go on F11" — run by the parent (see F11 entry above).

## F8 — External-edit resilience  (proved · test · 2026-07-22)
**Route:** lexical sync change-set + `vector.reconcile` wired into search (deleted files lose
vector+queue rows; edits re-enqueue on content-hash mismatch; touches cost nothing) +
cross-leg `reindex.py` (FTS5 + graph cache + vectors from markdown alone). Patch applied clean.
**Parent fix at reconcile:** the builder's own byte-equivalence test caught that per-leg tie
order was not rebuild-invariant (RRF credit shifted 1/62→1/61 across a rebuild); parent made
leg ordering deterministic (lexical `ORDER BY neg_score, slug`; vector `ORDER BY slug` + stable
argsort).
**Proof:** parent ran `uv run pytest` → **70 passed** (5 F8 tests incl. the machine-asserted
meaning-flip semantic refresh and full-`.index/`-delete equivalence).

## F9 — Extract-knowledge CLI  (proved · test · 2026-07-22)
**Route:** `extract.py` reusing store save mechanics; batched up-front embedding with
drain-before-dedup so Ollama failure can never partially save a batch; intra-batch dedup;
slug-collision auto-suffix under the lock; threshold in config with `MEM_DEDUP_THRESHOLD` seam.
Patch carried only cli/config hunks — extract.py/tests/harness promoted from the deliverable
tree. **The builder refused to fabricate the calibration artifact** (execution-gated seat;
D024 discipline) and shipped a runnable harness instead.
**Proof:** parent ran the REAL calibration against the live daemon → threshold **0.79**
(DECISION_LOG D3; builder's provisional 0.85 corrected by measurement); `uv run pytest` →
**78 passed**; real-KB extract walkthrough: blatant near-dup skipped at 0.93 with named
match+score (`.kodos/evidence/walkthrough/wave5-extract.txt`). Advisory: umbrella-vs-member
pairs can exceed the line (0.84 observed) — report+override is the designed recourse.

## Wave 5 checkpoint  (CLEAN · 2026-07-22)
Deterministic half green. Fresh-eyes review: **deferred — 2nd consecutive** (ran wave 3);
**mandatory at wave 6**, which is also the final build wave — the reviewer gets the complete
tree. Walkthrough (F36): extract exercised on the real KB (see F9 entry); prior integrated
path unchanged and green.

## Wave 6 dispatch  (2026-07-22)
Final wave; ready set F10 + F12. F12 → roster builder `kodos-F12-20260722T0105Z` (first
dispatch stopped inside a minute — brief was missing the matched L2 learnings block — appended
and relaunched; the learning about learnings held). F10's deterministic half rode the same
builder cycle; its **observed** half ran as two staged live sessions (`f10-observe-roster`,
`f10-observe-inline` — `architect` role used as the plain-session vehicle; roster has no bare
`claude` role).

## F12 — Zero-egress guarantee  (proved · test · 2026-07-22)
**Route:** two layers. Product hardening: `ollama.py` refuses non-loopback base URLs before
any socket or DNS work (a hostile `MEM_OLLAMA_URL` never yields a connect attempt). Test
layer: a `sitecustomize` audit-hook guard plus a netns driver that re-execs the suite under
`unshare --user --net` (loopback only) with an in-namespace fake Ollama, then runs **all 8
commands** there — up-leg proves the only peer ever contacted is Ollama on 127.0.0.1;
down-leg proves the documented one-line degradations; remote-URL leg proves zero connects.
**Proof:** `MEM_REQUIRE_NETNS=1 uv run pytest` → **89 passed**; the netns test is asserted
RUNNING, not skipped. Guard lives entirely in the test layer — zero product runtime cost.

## F10 — Extraction procedure  (proved · observed · 2026-07-22)
**Route:** `extract-knowledge.md` procedure shipped in `agent_integration/` and printed by
`mem extract --procedure`; deterministic half covered by tests 84–89. **Observed proof, both
modes** (protocol: staged is legit — the session prompts never mention the memory system):
**(A) roster mode** — a real session pointed at `research/backend-research.md` followed the
printed choreography unprompted: cross-backend `agent-roster fanout` per D1 (Codex+Claude),
2 extractor lenses → 13→12 merged candidates, 2 fresh-eyed reviewers → 0 rejections + 4 fixes
applied → `mem extract`: **11 added, 1 skipped-dup**; D3's disposition-review recourse used
once (0.8032 umbrella-vs-sibling, saved via direct `mem save`). **(B) inline mode** — roster
made genuinely undiscoverable (PATH symlink held out); same procedure on the capstone router
doc via `claude -p` one-shot subagents (2 extractors, 2 reviewers, 1 fix): **6 added,
2 skipped-dup, 2 sanctioned overrides**. Both runs ended with the readable added-vs-skipped
report. Evidence: `.kodos/evidence/F10/`. Managed blocks refreshed after observation
(`mem init`; doctor 9/9). **Follow-up journaled (not v1 scope):** both observation reports
independently flagged that intra-batch `related`-slug normalization belongs inside
`mem extract` (candidates referencing each other's not-yet-existing slugs).

## Wave 6 checkpoint — fresh-eyes review  (DRIFT → remediated · 2026-07-22)
Deterministic validators all green (ledger, state+join, learnings, scheduler → closeout).
**Mandatory final review ran on CODEX** (run `verifier-ca8z`, read-only sandbox, paths-only
cold prompt over the complete tree at fbad261): **VERDICT: DRIFT, 11 findings** (8 MAJOR /
2 MINOR / 1 NIT) — all verified by the parent against the cited files; 10 genuine, 1 reframed.
Dispositions:
1. `IMPLEMENTATION.md` cites `scripts/schedule.mjs`, absent in this repo — the path lives in
   the KodOS install, not the project; snapshot is generated (no hand-edit). **Upstream KodOS
   template feedback**, recorded here; the `# or: /kodos:go` alternative in the same line is
   correct for cold readers.
2. **CORRECTION to the F10 entry above (append-only journal):** its parenthetical "the session
   prompts never mention the memory system" imported F11's protocol by mistake. F10's ledger
   protocol has no such clause — F10 is literally "Brent points an agent at a document" and
   the observation prompts rightly did; what they never pre-specified was the *choreography*
   (fan-out counts, reviewer structure), which is what the observation proves the shipped
   procedure supplied. The evidence stands; the journal sentence was wrong.
3. Extract timing: NFR + shipped procedure claimed < 60 s/document; roster observation
   measured the extractor fanout alone at 83 s. **DECISION_LOG D4**: envelope revised to
   single-digit minutes with per-stage progress (CLI half stays seconds-scale); NFR_UX.md +
   `extract-knowledge.md` reworded. Flagged for Brent at closeout.
4. F36 post-fix retest had no evidence artifact — and re-running it live exposed a real
   overclaim: **CORRECTION to the wave-4 checkpoint above** — "first search now succeeds" was
   environment-dependent (page-cache-warm reload). Measured at wave 6: full cold reload 3.83 s
   (no NFR-compatible budget covers it); the durable contract is graceful degradation + self-
   warm (first cold query: lexical+graph, warning, 2.661 s; second query: semantic leg back,
   0.431 s, paraphrase → testing-effect). Query budget kept at 2.5 s. Evidence:
   `.kodos/evidence/walkthrough/wave6-f36-postfix.txt`; second F6 evidence entry appended;
   ARCHITECTURE reworded honestly.
5. ARCHITECTURE "~500 ms every embed call" → rewritten to the real per-purpose budgets
   (save/drain 500 ms · query 2.5 s · full drain 30 s).
6. ARCHITECTURE save-path "FTS5 + edge cache in-line" → corrected: lexical inline; graph is a
   lazy mtime-invalidated derived cache; vector queued/post-save.
7. README + ARCHITECTURE "provider-neutral, same ambient awareness for codex/agy" → rewritten
   to D1 scope (Claude+Codex approved; ambient proved on Claude; codex/agy installation-only;
   Antigravity excluded).
8. README "Early discovery / graph backend under evaluation" → refreshed to built state
   (12/12 proved, usage quickstart, real environment notes).
9. networkx listed as dependency/traversal lib → corrected (pure Python; numpy+PyYAML only).
10. Resolved open questions in PRD/NFR/ARCHITECTURE → annotated with D2/D3/NFR-session
    resolutions (D2 still awaiting Brent's explicit confirm).
11. Stale snapshot render timestamp → re-rendered via `render-snapshot.mjs`.
**Post-remediation:** `MEM_REQUIRE_NETNS=1 uv run pytest` → **89 passed**; state re-validated.
Build phase complete → `/kodos:closeout`.
