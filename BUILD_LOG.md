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
session, different project (a separate scratch project; path redacted 2026-11-17), task on record and free of any memory
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

## Closeout  (done · 2026-07-22)
**Delivered:** `mem` 0.1.0 — OKF markdown store + FTS5 lexical + Ollama/numpy vector + derived
topic-node graph, RRF-fused; installed on PATH (`uv tool install --editable`), live KB at
`~/.agent-memory` (32 concepts, local-only, per-save commits), managed blocks in the real
`~/.claude/CLAUDE.md` + `~/.agent-docs/AGENTS.md`. 12/12 features proved; verification
`MEM_REQUIRE_NETNS=1 uv run pytest` → **89 passed**.
**Closeout gate (F37/F36):** both `observed` features re-observed against the FINAL tree —
F10 (`architect-iqj1`): full choreography unprompted on a new document, cross-backend per D1,
7 added incl. one D3 disposition-review override at 0.8403, all KB commits verified real;
F11 (`architect-wve5`): pure teaching task, unprompted `mem search`+`get`, deliverable grounded
in KB concepts (save leg not re-triggered — no KB gap; original observation stands). Final
whole-product walkthrough: 14 dynamic states, zero validated findings
(`.kodos/evidence/walkthrough/closeout-walkthrough.txt`). Learnings store refreshed at the
closeout seam (L4 updated, L5+L6 added; 6 records valid).
**Caveats / follow-ups for Brent:**
- **D2 (clean-room OKF) awaits his explicit confirmation** — flagged since F2.
- D4 revised the extract-choreography envelope to minutes (measured); a single-extractor
  `--quick` mode is a possible post-v1 seam.
- Product follow-up (both F10 observations + closeout run): intra-batch `related`-slug
  normalization belongs inside `mem extract`.
- KodOS upstream: the generated snapshot's `scripts/schedule.mjs` hint assumes the KodOS repo
  layout — misleading in a project checkout (wave-6 finding 1).
- Repo has a remote; **nothing pushed** — pushing is Brent's call (F14 approval gate).

## Post-closeout — standalone sanity checkpoint + remediation (2026-07-24)

Standalone `/kodos:sanity` (deterministic validators green; drift + code-quality reviewers via
roster, 3 findings validated per-finding): ARCHITECTURE.md's storage layout still placed graph
edges in `mem.db` (they live in `.index/graph.json`) and its organizing-idea line predated D8's
non-derived `usage.jsonl`; IMPLEMENTATION.md's render stamp (16:00:16Z) precedes state evidence
it renders (16:20:00Z, hand-rounded). **Remediated:** ARCHITECTURE.md storage section + organizing
idea amended to D7/D8 reality. The IMPLEMENTATION.md stamp is a generated-snapshot wrinkle —
accepted as-is (hand-edits to the snapshot are off-limits; a future KodOS engagement re-renders).
Quality lens: PASS, zero hazards; improvements journaled in the checkpoint report (chat).
**Supersedes a stale closeout caveat above:** "D2 (clean-room OKF) awaits his explicit
confirmation" was resolved 2026-07-22 — see DECISION_LOG "D2 — Amended: confirmed by Brent
against the official spec" (the question dissolved; OKF is a public standard). An external
doc-sweep on 2026-07-24 was misled by the stale caveat, which is what triggered this checkpoint.
Learnings L7-L8 captured at the checkpoint seam; `run.needs_you` cleared.

## 2026-08-05 — standalone sanity checkpoint (post-D13) + full remediation

Checkpoint (tree scope, roster verifiers): deterministic validators clean; drift
reviewer returned 2 CONFIRMED findings, both independently VALIDATED → needs_you
tripped. Findings: (1) ARCHITECTURE component contracts stale vs D8–D13 code (cli
listed 8 of 10 commands; okf row lacked `source`); (2) the F12 "full `mem` surface"
zero-egress enumeration no longer covered `links`/`stats`. Quality reviewer: 0
hazards ("unusually healthy"), 6 improvements + 6 nits — all promoted by Brent
("fix it all").

Remediation (same session): ARCHITECTURE re-trued (10 commands, `source` field);
netns driver extended to the full 10-command surface + a parity test pinning driver
coverage == subparser set (kills the recurrence class); filter-aware leg-pool
widening (recall cliff) + test; backup sweep now under the KB write lock (F7 race);
Graph precomputes reverse adjacency (O(N) once vs O(seeds×N) per search); six
fake-Ollama doubles consolidated into tests/fakes.py; get/list --json report the
resolved file stem; corrupt vector DB degrades the semantic leg with the standard
marker + test; nits (module-level time import, shared indexdb seam, vector.check_meta,
initcmd reuses warn_if_remote, kb-obsidianize usage guard, scripts/one-shots/,
backup stderr no longer discarded). Suite 116 → **119 passed** (incl. the netns leg
live). Learnings: L1 updated (doc↔surface skew, both directions), L9 added (pin
proof enumerations with parity tests). needs_you cleared.

## 2026-08-10 — standalone sanity checkpoint (post-D14) + remediation

Checkpoint (tree scope, roster verifiers): deterministic validators clean; drift
reviewer returned 1 CONFIRMED finding, independently VALIDATED → needs_you tripped.
Finding: PRD.md:113 §9 flag-grammar parenthetical quoted the v1 8-command surface
while citing ARCHITECTURE (10 commands, matching cli.py) as the settled record —
the PRD instance of the L1 skew class that survived the 2026-08-05 ARCHITECTURE
remediation. Drift reviewer also re-ran the suite live: 119 passed (netns leg
running); all state evidence refs verified on disk; KB zero-remote invariant
confirmed. Quality reviewer: 0 hazards ("unusually healthy"), 5 improvements
(incl. a reproduced NameError in dead lexical.db_path; embed batching x2; repair
script unlocked writes; wikilink regex triplication) + 5 nits — all advisory,
surfaced in chat, none promoted yet.

Remediation (same session, Brent: "fix the prd to match reality"): PRD
parenthetical re-trued as dated version history (v1 8 commands; post-v1 + links ·
stats per D12/D8, current surface pinned by the F12 parity test). L1 learning
updated (F27 checkpoint seam): the skew class hides in EVERY surface-quoting doc,
not just the contract doc — sweep PRD/NFR resolutions too. needs_you cleared;
state + learnings validated. Last-CLEAN marker NOT advanced (post-fix tree awaits
its own adjudication). Commit 1d9b210.

## 2026-08-14 — standalone sanity checkpoint (post-D15/D16) — CLEAN

Deterministic: ledger OK, state + bidirectional join OK, scheduler coherent (12/12
proved, next: done). Judgment (tree scope, roster executors, paths-only): drift
reviewer verifier-eo81 → **CLEAN** — every state evidence ref real on disk, suite
re-run live 124 passed with netns leg required, live KB zero remotes (2,521
concepts), D15/D16 coherent docs↔state↔code both directions, managed blocks
verbatim-current in the installed CLAUDE.md/AGENTS.md; two advisory observations
(D15/D16 journal cadence — this entry closes it; FEATURES.md frozen single-root
language — documented read-only history, not drift). Quality reviewer
verifier-qair → **no HAZARDs**; advisory: 4 IMPROVEMENTs (lexical.db_path
NameError dead code + no linter [repeat from 2026-08-10]; extract dedup blind to
un-searched external edits — reconcile before drain_fully [NEW, most
consequential]; unchunked batch embed under flat 30s timeout [repeat];
mem list full-KB reparse + pure-Python yaml loader despite libyaml present
[NEW, CSafeLoader is a one-liner]) + 6 NITs (incl. kb-obsidianize bypassing the
D15 instance seam). Advisory only — the loop never self-assigns; Brent promotes
what he wants. **Last-CLEAN marker advanced to 8d349bd** (.kodos/sanity.last-clean,
now gitignored with handoff.latch under the F23 machine-state block).

## 2026-08-17 — D17 (two-band dedup) + standalone sanity checkpoint — DRIFT → remediated

**D17 engagement** (Brent-approved; roster delegate→gate→commit): calibrated the
personal-instance dedup profile on 381 KB-existence-labeled pairs from the 5-batch
cancer-corpus extraction (`research/dedup-calibration-personal-2026-08-17.md`; no
single threshold separates the classes — bottom band clean below 0.8413, top band
not worth enabling), then shipped `MEM_DEDUP_LOW`/`MEM_DEDUP_HIGH` two-band
mechanism, back-compatible by default (522ffef). Gate cycle: codex verifier FAIL
(3 real blockers — default JSON not byte-identical + a test asserting the
violation; no equality-boundary tests; D-log overclaims) → fix cycle (+ decided
addition: invalid band config refuses cleanly) → codex re-gate PASS across all 7
dimensions. Suite 124 → **138 passed**, re-run green by the committing orchestrator.
Personal instance deploys `MEM_DEDUP_LOW=0.83` via the hub's agent-contract env
routing (per-instance config is env-var-only, the D15 pattern). Run dirs:
`work/agents/d17-two-band`, `d17-gate`, `d17-fix`, `d17-gate2`.

**Standalone sanity checkpoint** (tree scope; roster verifier reviewers per the
role-dispatch seam): deterministic validators 3/3 OK. Drift reviewer
(sanity-drift) → DRIFT, one finding, independently VALIDATED (sanity-val-f1):
PRD/NFR_UX/ARCHITECTURE dedup-resolution lines still described the pre-D17
single-0.79 surface with no dated annotation — the **L1 skew class, third
recurrence**. Tripped `run.needs_you`; Brent approved remediation same-session:
dated "Since D17" annotations added to all three docs + ARCHITECTURE extract-row
disposition list re-trued; L1 updated in `.kodos/learnings.json` (rule-on-record
didn't self-execute; durable kill = mechanical doc-sweep at the decision-commit
seam). Advisory (this entry closes the journal-cadence advisory, same as
2026-08-14): D17 had no BUILD_LOG entry until now. Quality reviewer
(sanity-quality) → **no HAZARDs**; 6 IMPROVEMENTs (repeats: lexical.db_path
NameError dead code, unchunked batch embed under flat 30s timeout; new:
extract.py cross-module underscore-private imports, per-candidate Python-loop
_best_match [O(candidates×KB)], _extract wall-of-function, kb-obsidianize
hardcodes the work-KB root around the D15 seam + divergent slugify) + 9 NITs
(incl. backup script's silenced bundle-verify diagnostic, text `mem get` drops
`source:`). Advisory only — Brent promotes what he wants. Everything else CLEAN:
all 12 features' evidence refs real on disk, both KBs zero-remote, managed blocks
current, D17 chain coherent end-to-end. Re-check checkpoint follows this
remediation; marker advances only on its CLEAN.

## 2026-09-03 — standalone sanity checkpoint (tree scope; first deep read since D18/D19)

Deterministic half: ledger OK, state + bidirectional join OK, scheduler `done`
(12/12 proved). Judgment half (roster verifiers, sonnet, subscription lane —
two earlier attempts discarded: `--emit-artifact` put both reviewers into Claude
Plan Mode and they delivered no verdict; a further relaunch was found billing
the org gateway because the lane var never reaches delegate panes — both filed
in the roster AGENT-NOTE, fixed for this session with a tmux session-scoped
`CLAUDE_PIPE=personal`, verified from `/proc`). **Drift reviewer → DRIFT, one
finding, validated by a fresh validator:** `PRD.md:123-126` quoted "the current
10-command surface"; the CLI has 11 since D18 W2's `mem dedup` (L1 skew class,
**4th recurrence**). Remediated same-session (Brent: "fix the PRD"): re-trued to
11, `dedup` added to the post-v1 growth list with its D18 citation, and the
sentence reworded to name no count ARCHITECTURE does not also carry; L1 record
in `.kodos/learnings.json` updated (structural lesson: a prose count is not a
pin). **Quality reviewer → one HAZARD (validated):** `dedup.py`'s
`greedy_union_cover` recomputes the claim-match matrix on every union round
and `_claim_cosine` recomputes vector norms per pair — real redundant work,
material only once the (shipped-off) semantic claim leg is enabled at volume;
disposition pending Brent (fix now vs IMPROVEMENT backlog). Advisory: 3
IMPROVEMENTs (`mem list` parses every file instead of querying the lexical
table; `dedup-log.jsonl`/`usage.jsonl` scanned linearly in full on every
lookup — unbounded-growth pattern; `chunks.py`/`claims.py` hand-mirrored
identity/rebuild engine → extract a shared helper) + 2 NITs (local `import re`
in chunks.py; blank-line run in the W3b test file). Everything else CLEAN: all
12 features' evidence real on disk, S6-deferral claims verified byte-exact
against the W2 commit, procedure-v2 ordering pinned, 305 tests collected =
D-log's count, tree clean. Run flipped to needs-you for the two validated
findings; marker does not advance until resume + a clean re-check.
Disposition (Brent, 2026-09-03): the validated HAZARD is **backlogged as
IMPROVEMENT** — it is the first task of the S7-enablement / S6 follow-up
engagement (memoize claim vectors' norms; compute the claim-match matrix once
and let `greedy_union_cover` consume it). `run-resume` applied; drift re-check
follows for the marker.
Drift re-check (2026-09-03, after the PRD remediation) → **DRIFT, one NEW
validated finding; everything else CLEAN incl. the PRD fix:** the suite was not
hermetic against the invoking shell's `MEM_*` config — with the personal
instance's own `MEM_DEDUP_LOW=0.83` exported (D15/D17's supported deployment
mechanism), the documented verification command `uv run pytest` failed two
tests (`test_mixed_batch_dispositions_json`: in-process `config.dedup_threshold()`
read the ambient 0.83 while the subprocess report said 0.79; a W2 Ruling-A test
tripped `MEM_DEDUP_HIGH (0.8) must be greater than dedup_low (0.83)`). The
orchestrator had been masking this all week with `env -u MEM_DEDUP_LOW` — the
reviewer's fresh eyes saw what the operator's habit hid. Remediated: an
`autouse` fixture in `tests/conftest.py` strips every ambient `MEM_*` variable
from the test process (subprocess `mem` calls were already hermetic via the
`kb` env dict). Proof: the two tests pass and the full suite is 305 green with
`MEM_DEDUP_LOW=0.83` exported and NO `env -u`, netns asserted. New learnings
class recorded (test hermeticity vs ambient per-instance env).
Validator note: the per-finding validator returned REFUTED — "already resolved on
disk" — because the orchestrator's remediation had landed in the working tree
before the validator read it (parallel sequencing, not a disputed finding). The
finding stands as real: the reviewer reproduced 2 failed / 303 passed, and the
orchestrator independently reproduced the pre-fix failure by stashing the
fixture (2 failed) and restoring it (2 passed). Recorded as learnings L10.
Final drift re-check (verified personal-lane delegate) → **CLEAN**: the PRD
remediation, the hermeticity fix (reviewer re-ran the full suite live and the
targeted reproduction), the backlogged hazard, the S6-deferral byte-identity,
and the procedure-v2 pin all cohere with disk. Last-CLEAN marker advanced to
1b66b6e (2026-09-03T18:11:47Z). Checkpoint closed; handoff follows.


## 2026-10-16 — D1: an allowlist for the KB's remote (0.2.1, branch d1-allowed-remotes)

Brent ruled on 2026-10-15 (D1 of the work host readiness) that the KB keeps a git remote on his
tailnet host and that `mem doctor`'s no-remote check and the managed CLAUDE.md line change to match.
Change: `gitkb.allowed_remotes()` reads `<kb root>/.allowed-remotes` (one URL per line, `#`
comments); `disallowed_remotes()` lists every configured remote whose URL is not there. Doctor's
`no-remote` check fails only on a disallowed remote (naming the file and the two remedies) and
reports allowed ones; `store.warn_if_remote` warns only on disallowed ones. Both managed blocks say
so. Tests: `tests/test_d1_allowed_remotes.py`. Release into the read-only copies on both machines and
`mem init` (block refresh) are Brent's word, as every freeze is.

## 2026-11-17 — Review and three-stage remediation (branch remediation-2026-11, isolated candidate)

An assessment of the live tree (HEAD dc76e55 plus an uncommitted 2026-10-20 shared-write release)
found that a source commit could silently redeploy the daily tool and remove the release selector;
that source accepted stale local updates the installed release refused; that a never-built semantic
index produced a silent empty result; that a required network-proof flag was stripped by a test
fixture; and that documentation, served plugin copies and runtime selection had drifted apart. The
remediation ran in an isolated candidate clone, one slice at a time, each with a receipt and an
independent opposite-vendor review, with every existing KB left untouched and activation held.

- **Stage 1 (318e12c..5e90a93):** the shared-write release imported as a curated commit with endpoint
  values moved to an operator profile; the post-commit hook prints an identity line and never
  installs (D22); every `--update` carries the version it was based on, compared under the writer
  lock, plus the extraction link-remap race check (D21), with the old-contract tests reconciled;
  the shipped instruction blocks made portable again with the safe-update contract; a profile that
  is unusable never disturbs an unmarked root; `mem --version` and `mem doctor`'s `runtime` line name
  the imported package; `scripts/release.py` (stage/activate/rollback/status, both install layers)
  and `scripts/hold-shared-writes.py` (receipted, reversible). Four review rounds to PASS; suite
  391 passed.
- **Stage 2 (4e4848d..d076093):** an unbuilt or empty semantic index on a KB with concepts now
  produces exactly one warning line while the JSON array contract is unchanged; `MEM_REQUIRE_NETNS`
  survives the hermetic fixture and a controlled unavailable namespace fails when required and
  skips visibly when optional (D23); a docs/CLI consistency test pins the ARCHITECTURE command row to
  the parser; the staged-tree fsync ordering is asserted in full. Review PASS; suite 399 passed with
  the outer namespace leg skipped in the builder's context and passed (8/8, required) in a
  namespace-capable context on the same revision; direct regressions for each refusal branch added.
- **Stage 3 (ab4b89e..):** documentation reconciled with the shipped behaviour and the shared
  delivery workflow (D24), dated history preserved; decisions D1-amend, D2-amend, D20–D24 logged.
  Bounded synthetic exercises on disposable KBs. Executable attribution per run: the extraction and
  safe-update runs on the candidate printed `mem --version` in-run (candidate package path); the
  first set of runs resolved `mem` to the installed 0.2.1 release (the launcher's own PATH prepend,
  understood afterwards) and is kept as evidence about that release; the ambient runs cannot print
  a version (their prompt must not name the tool), so the first is attributed to the installed
  release and the second to the candidate by lane configuration and a diagnostic control. Observed:
  ambient recall in both ambient runs and unprompted capture in neither (F11 note); the extraction
  procedure end to end in inline-subagent mode with the report matching the KB (F10 note); the
  designed safe-update opportunity (read, version token, one update commit) with scripted
  missing/stale/malformed-token refusals leaving content and history untouched.
- **Redaction (2026-11-17, completed after review round 2):** deployment-specific identifiers were
  replaced by neutral placeholders across every tracked file — this file, `DECISION_LOG.md`,
  `IMPLEMENTATION.md`, `SHARED-WRITES.md`, `research/*.md`, `research/dedup_detection_calibration.py`,
  `.kodos/evidence/**`, `.kodos/state.json`, the `refresh` help string in `cli.py`, the fixture URLs
  in `tests/test_d1_allowed_remotes.py` (`kb-host`) and the hard-coded home path in
  `scripts/kb-obsidianize.py` (now `~` expansion). Map: a retired engagement's KB instance path ->
  `<engagement-kb>`, its project path -> `<engagement-project>`, its corpus prefix -> `engagement`;
  a scratch project's path -> `<scratch-project>`; this repo's absolute path -> `<repo>`; other home
  paths -> `<home>`, `<capstone-workspace>`, `<agent-roster>`, `<walkthrough-home>`; the authority
  host's alias -> "the work host". The one retained literal is the guard in
  `tests/test_shared_writes.py` that asserts the alias is absent from source. Events, dates and
  decisions are unchanged; the original text is preserved in the private provenance records.
- **Held / pending:** host-mediated shared writes (D20); live runtime and plugin activation, with its
  rollback, as a separately approved checklist; the laptop launcher bound to a release.

## 2026-11-17 (evening) — Activation, plugin routing correction, closeout (branch closeout-2026-11)

Activation of the remediation on the development laptop, on the operator's direct approval, from a
reviewed pre-activation packet (checklist with a check and a rollback per live step; protected-state
copies; rehearsal in a disposable prefix; seven review rounds to a passing packet). Executed in
order: the staged runtime release `0.2.1+a1c3a6319b61` activated into the uv tool prefix (journal
first; `mem --version` and `doctor` name the release; fingerprint deltas exactly the receipt layer and
the selector set); the guarded personal wrapper re-pinned (non-writing `stats` check; the private
instance's metadata unchanged); both harnesses pointed at a frozen plugin snapshot — Claude through its
registry files, Codex through its own remove/add/re-add route, after that route had been reproduced on
a byte copy of the full live config because a pre-existing unrelated marketplace entry made the global
listing fail; the two receipted holds (profile aside, obsolete remote removed); an end-to-end proof of
save, token-checked update, stale/missing-token refusals and held commands on a wholly synthetic
instance. Independent live verification: 31 of 31 checks. No existing instance was written at any step.

Findings during activation, each recorded with its lesson in the private records: a process scan
matched the command's own shell twice (abort before mutation, harmless); the reproduction of the Codex
route was home-isolated, not network-isolated, and must be named so; the plugin was disabled in the
user's settings since earlier that day (registered, enabled and loaded are three facts); and the frozen
skill still routed to bare `mem`, a default instance, `doctor` and `init`.

The skill was corrected (D26) in two commits — a portable entrypoint resolution with an explicit mapping
and an honest preflight, plus tests pinning the contracts — after a first review found the preflight
overstated what `stats` proves, the tests missed fenced command forms and mapping destinations, and the
plan's fingerprint baseline was stale; the recheck passed. A new snapshot was frozen and both harnesses
switched to it (one semantic change in the Codex config; the two Claude registry hashes), verified 14 of
14. A fresh contained session then loaded the corrected skill from the snapshot and selected the
guarded entrypoint from the policy, but its own `claude plugin list` named the worktree: the user's
`extraKnownMarketplaces` setting re-merges into the registry at every fresh start (D25). The operator
pinned that one setting value; a fresh start then wrote the snapshot path (verified 11 of 11), and a
restart of the Codex desktop app loaded the corrected skill there.

Closeout: a reconciliation map of the original checkout's sixteen preserved changes (six byte-identical
at head, seven entered the candidate byte-identical at the curated import and were changed only by
reviewed commits, two had private endpoint values removed at import with the originals preserved and
the delta recorded, one historical evidence record deliberately not imported); the runtime release's
archived files confirmed byte-identical to head except `README.md`, which the closeout commits changed
after the freeze (documentation only; no re-staging), and the plugin snapshot byte-identical; this entry, D25–D27, the
README's status and "Where development happens", `RELEASE.md`'s laptop state and plugin-snapshot
procedure, and the deferred backlog in `FEATURES.md`. Documentation-only; the focused documentation and
consistency tests re-run; the full suite's last run (406 passed on 8207268) still covers the unchanged
source. The fast-forward of the original checkout's `main`, the publication of the branch and any
removal of superseded copies are prepared as proposals for the operator; nothing was pushed, published
or deleted. Records: private operations directory (outside the repository). Those records also hold
the account of the one incident of the day — an unquoted shell heredoc in the original checkout ran a
backticked `git reset --hard` from prose and discarded the dirty tracked changes, which were restored
within a minute from the provenance diff and independently verified (16 of 16 hashes) — and the
lessons drawn from it (literal writes only; explicit working directory; never the served checkout).
Publication is additionally gated: the outgoing history carries, at the import commit, lines with the
alias that was later redacted, so a push needs an explicitly authorized treatment first (D27).

## 2026-11-18 — The original checkout's `main` fast-forwarded (D27 executed)

The prepared operation was executed by the coordinator at 12:01 CST after a fresh precondition
check and with the hook's no-reinstall seam: the checkout's uncommitted 2026-10-20 tree became
commit 0b02228 on the local branch `preserve/dirty-tree-2026-10-20` (fifteen files, each
byte-identical to its provenance copy; the branch is never pushed), and `main` was fast-forwarded
from dc76e55 to cbad20c. Verified afterwards, independently of the executor: the private review
record still untracked and unchanged, the identity-only hook and the corrected skill at head,
`mem --version` and every recorded runtime, wrapper, selector and plugin-registration hash
unchanged, the candidate clone unchanged. Development happens in this checkout's `main` from here.
Documentation only (this entry, D27's amendment, the README's "Where development happens"); the
focused documentation and consistency tests re-run. Nothing pushed, published or deleted;
publication remains blocked (D27).

Later the same day the operator decided the three open questions: publish `main` as it is (the
alias judged harmless; no rewrite) — pushed to `origin` after the recorded pre-push scan, task
branches and the preservation branch not pushed; keep every rollback copy, superseded snapshot and
the candidate clone until the rollback window closes; close that window on 2026-11-25 if a week of
normal use passes without issue (D27, second amendment).

## 2026-11-18 — One backlog

`BACKLOG.md` now lists everything not done: the deferred items from `FEATURES.md` (whose section
points there), the deferrals in the decision log, the advisory findings of the 2026-08 and 2026-09
quality reviews and the PRD's deferred product directions. Each code finding was re-checked against
the source first; two had been fixed and are listed as such. Documentation only.

## 2026-11-18 — The printed procedure names the caller's entrypoint (D28)

`mem extract --procedure --entrypoint NAME` prints every command the procedure shows as `NAME …`
and leaves preflight to the caller, so a guarded entrypoint's held `doctor` is never a step; the
`/mem:extract` skill prints it that way and keeps its hand mapping only as the fallback for a
runtime without the option. Values a shell would split or expand are refused. Without the option
the output is the unchanged package artifact. Full suite 435 passed (one namespace-leg skip, D23);
the new tests failed against three deliberate mutations (a dropped form, the default preflight
kept, spaces accepted).

Skill handoff, observed once in a bounded synthetic exercise on the development source: a bounded
synthetic Claude session (Roster implementer, sonnet, inline subagents; not run under a containment
driver — its Roster record says uncontained) was given the skill text, a 610-word
synthetic document and a guarded synthetic entrypoint over a three-concept synthetic instance that
holds `doctor` and the operator commands, with neither the ordinary CLI nor the private wrapper on
its PATH. It printed the procedure with `--entrypoint`, ran two extractors and two reviewers
before any write, ran `dedup` before `extract`, routed every memory command through the
entrypoint (the instance's usage log shows only those), ran no held command, judged one
duplicate-skip as distinct and saved it through the documented override, and its report matched
the synthetic KB: four added, one rejected in review, two adjudications logged; 139 s from
launch to done. The fallback trigger was checked separately: the frozen release refuses the option
with `unrecognized arguments: --entrypoint`, the message the skill names. No real-instance
operations appear in the recorded handoff commands, and the recorded instance fingerprints and
live-selection hashes were unchanged; the frozen release and plugin snapshot on the laptop are
unchanged. Records: private operations directory.

A second session, from the same fixtures in a fresh synthetic workspace and instance, ran under
Roster's process containment (`--contain`; recorded as contained by `bwrap`: its own PID
namespace, a private `/tmp`, the user and system buses, tmux and Docker hidden). That boundary
leaves the filesystem unchanged and localhost reachable, so it is not a filesystem no-access
boundary. The session behaved as the first: the procedure printed with `--entrypoint`, two
extractors and two reviewers before any write, `dedup` before `extract`, every memory command
through the entrypoint, no held command, one duplicate-skip judged distinct and saved through the
override, and a report matching the synthetic KB (four added, one rejected in review, one
adjudication logged); 161 s from launch to done. Roster's write confinement refused one scratch
write outside the run directory, and the session wrote its scratch there instead, as its report
says. No real-instance operations appear in its recorded commands; the recorded fingerprints and
live-selection hashes were unchanged.
