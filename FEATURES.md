# FEATURES - agent-memory

The feature ledger **spec** — the human-authored plan: what this project must deliver, each
feature with success criteria, a proof method, and dependencies. Per the KodOS model, **state**
(status / attempts / evidence) lives in `.kodos/state.json`, not here; this file is read-only
during a build.

**Feature** = the smallest user-meaningful capability that can be independently proved.
**Proof methods:** `test` (automated), `observed` (agent runs it and watches the behavior),
`sign-off` (human confirms). Flat ids; `depends_on` drives build order and parallelism.

> **2026-11-17:** the KodOS state file (`.kodos/state.json`) is retired history; status is no longer
> tracked there. Criteria amended after the build are dated in place. The two observed features
> (F10, F11) are re-observed in bounded synthetic exercises before a release is called verified;
> records in `BUILD_LOG.md`.

**Environment root (pre-F1, as written 2026-07):** Ollama provisioning — systemd enabled in WSL2, the daemon
installed, `nomic-embed-text:v1.5` pulled with `num_ctx` configured, FTS5 present in the
system Python — is owned by **`/kodos:preflight`** and must pass before F1 is attempted. No
feature installs the daemon; the build loop must not burn attempts against an unprovisioned
host. Tests exercise daemon states (up / down / hung) through the sanctioned endpoint seam
(`MEM_OLLAMA_URL`) against an isolated test `HOME` — never the real service or the real KB.

---

## F1 — Initialized, verified KB home
- **Proof:** `test` (init creates the layout + managed blocks; doctor diagnoses truthfully, for life)
- **Depends on:** —

**Functionality:** Brent (or an agent) runs `mem init` once and has a working, verified KB home:
`~/.agent-memory/` with `concepts/`, the index, and a local git repo with no remote beyond
`.allowed-remotes` (D1 amendment, 2026-10-15) — plus the
managed agent-instruction blocks installed. `mem doctor` diagnoses the environment at any time,
including confidentiality-invariant decay.

**Success criteria**
- `mem init` on a machine without a KB creates `concepts/`, `.index/`, and an initialized git
  repo with **zero remotes configured**; a second run exits 0 with the KB home unchanged
  (idempotence means "exit 0, KB home unchanged" — the managed instruction blocks may refresh
  in place).
- `mem init` installs/refreshes clearly-delimited managed instruction blocks in the global
  `CLAUDE.md` and `AGENTS.md`; re-running updates in place with **no duplicate blocks**
  (test-proven mechanics; the ambient *behavior* those blocks produce is F11's observed
  surface). The blocks carry the confidentiality/vendor policy (NFR sensitivity semantics +
  DECISION_LOG D1: work-recall for Claude/Codex only; Antigravity excluded from memory work).
- `mem doctor` reports pass/fail per check — Ollama reachable, embedding model present with
  expected dimensions, FTS5 available — with a nonzero exit when a required check fails, so an
  agent can act on the diagnosis rather than guessing.
- **The remote invariant holds for the KB's life, not just at init:** with a remote injected
  into the KB repo after init, `mem doctor` fails loudly naming it, and write commands warn
  until it is removed — unless its exact URL is listed in the KB root's `.allowed-remotes`
  (D1, 2026-10-15: the work host over Tailscale), which doctor then reports as allowed.
- With Ollama stopped, `mem doctor` says exactly that in one line; all non-Ollama checks still
  pass and are reported.

## F2 — Durable concept capture
- **Proof:** `test` (save/get/list round-trip, OKF-valid, committed, collision-safe)
- **Depends on:** F1

**Functionality:** An agent or Brent saves a concept in one command and it is durably,
inspectably stored: valid OKF markdown with history, retrievable by slug, listable for audit.

**Success criteria**
- `mem save` with title/body/topics writes a valid OKF file (frontmatter: id/slug, title,
  description, type, `topics[]`, `sensitivity`, timestamps) at `concepts/<slug>.md`, and
  `mem get <slug>` (text and `--json`) round-trips it faithfully — the field contract matching
  ARCHITECTURE's `okf` component spec.
- Before any capstone-derived code lands, the OKF license/clean-room posture is recorded as a
  DECISION_LOG entry (the ARCHITECTURE open question, resolved at F2 start).
- Slugs are deterministic (lowercase alnum-hyphen, NFKD-folded); saving onto an existing slug
  exits nonzero with a one-line error unless `--update`; `--update` bumps the updated timestamp.
- (2026-11, D21) `--update` must carry `--expected-version` equal to the `version` that
  `mem get <slug> --json` returned for what the caller read; a missing, malformed or stale token is
  refused with nothing written and no commit, and the caller re-reads and reconciles rather than
  retrying with a fresh token.
- Every successful save produces exactly one commit in the local git history identifying the slug.
- `mem list` shows saved concepts with their topics, so Brent can audit what has accumulated.
- A save interrupted mid-write never leaves a corrupt or partial concept file (atomic rename).

## F3 — Keyword search
- **Proof:** `test` (literal-term queries rank the right concept with Ollama absent)
- **Depends on:** F2

**Functionality:** `mem search` finds concepts by literal terms — working fully even with the
embedding daemon absent — and returns results an agent can act on.

**Success criteria**
- With Ollama entirely absent, `mem search "<literal terms>"` returns the matching concept in
  the top results, BM25-ranked, in both text and `--json` forms.
- Each hit carries slug, title, score, and a snippet — enough for the calling agent to decide
  whether to `mem get` the full concept without a second guess.
- An empty result set exits 0 with an empty list and one quiet line — no error noise for agents.
- (2026-11) When the KB holds concepts but the semantic index is unbuilt or empty, `mem search`
  still answers lexically and prints exactly one `warning: semantic leg skipped (...)` line on
  stderr naming the remedy; stdout keeps its contract (a plain JSON array with `--json`). An empty
  KB or a genuine no-match stays quiet.

## F4 — Semantic recall
- **Proof:** `test` (paraphrase fixture recovered; bounded-drain and timeout semantics machine-asserted)
- **Depends on:** F2

**Functionality:** Concepts are findable by meaning, not just wording — a paraphrased query
recovers the right concept via local embeddings — and embedding never blocks or loses a save.

**Success criteria**
- A query sharing no keywords with a stored concept returns that concept in the vector leg's
  top-k, machine-asserted with a paraphrase fixture (the capstone D020 pattern).
- Save with Ollama down: the save exits 0 in under a second and the embedding is queued; after
  the daemon returns, ordinary invocations drain the queue **boundedly (~3 items each)** and
  `mem doctor` / `mem reindex` drain it fully — the concept becomes semantically findable with
  **no manual reindex**; the test verifies both the bounded and the full drain paths.
- Embed calls carry a strict (~500 ms) client timeout; a hung daemon results in enqueue, never
  a stalled save — exercised via the `MEM_OLLAMA_URL` seam (down = closed port, hung = stalling
  fake endpoint).
- Index metadata records embedding model tag, digest, and dimensions; a write with mismatched
  dimensions is refused with a one-line error.

## F5 — Concept graph
- **Proof:** `test` (edges derived from links; topic-node structure; related retrieval returns both)
- **Depends on:** F2

**Functionality:** Concepts connect: `[[wikilinks]]`, `related:` frontmatter, and topics become
graph structure, and an agent can pull a concept's neighborhood in one step — the same links
Obsidian renders natively.

**Success criteria**
- Body `[[wikilinks]]` and frontmatter `related[]` yield direct edges; **topics connect concepts
  through topic nodes** (concept → topic → concept), never materialized pairwise edges — so a
  broad tag cannot explode the edge count quadratically past the ~50k assumption.
- `mem get <slug> --related` (text and `--json`) returns both link-neighbors and topic-neighbors
  so an agent can expand context in one command.
- The edge cache invalidates on file mtime change; edges to deleted files stop surfacing.
- Concept files use plain `[[slug]]` wikilink syntax with no custom markup, so the concepts
  directory opens in Obsidian and renders the graph with zero export or sync steps.

## F6 — Fused search
- **Proof:** `test` (single-leg fixtures surface in fused results; sensitivity marking honored)
- **Depends on:** F3, F4, F5

**Functionality:** One `mem search` fuses lexical, semantic, and graph evidence via RRF — an
agent gets the union of all three retrieval strengths in one ranked list, with sensitivity
visible.

**Success criteria**
- A concept findable by only one leg (lexical-only, semantic-only, and graph-only fixtures)
  still surfaces in fused top-k — the fuse-all property the capstone proved. (The graph-only
  fixture is a seed-neighbor construction: the query hits concept A lexically; concept B —
  sharing no query terms — links to A and surfaces via 1-hop expansion.)
- `sensitivity: work` items appear marked `[work]` in text output and as a field in `--json`;
  `--no-work` excludes them entirely.
- With Ollama down, fused search still answers from lexical + graph with exactly one warning
  line and exit 0 — degraded, never broken.
- (2026-11) The same single warning line covers an unbuilt or empty semantic index on a KB with
  concepts; a silent empty semantic leg is a defect. When the daemon is unreachable *and* the index
  is unbuilt, the warning names the daemon.
- Hits keep the agent-parseable contract (slug / title / score / snippet), one screen by default.

## F7 — Concurrent-session write safety
- **Proof:** `test` (parallel writers all land; zero lock errors)
- **Depends on:** F2, F3

**Functionality:** Multiple agent sessions write simultaneously without corruption, lost saves,
or lock crashes — the gate-hardened locking discipline holds under real contention.

**Success criteria**
- N parallel `mem save` processes (N ≥ 8, distinct slugs): all exit 0, N files exist, N commits
  land, and no invocation errors with `index.lock` or "database is locked".
- Parallel saves to the *same* slug resolve per the collision rule (non-`--update` saves error
  cleanly; `--update` saves serialize) with no interleaved or corrupt file.
- The concurrency test runs as part of `uv run pytest`, so regressions in the locking discipline
  are caught permanently.

## F8 — External-edit resilience
- **Proof:** `test` (direct edits reflected lexically AND semantically; reindex rebuilds equivalently)
- **Depends on:** F3, F4, F5

**Functionality:** Editing the KB behind the CLI's back — in Obsidian or any editor — never
poisons search: the next read picks up changes, stale vectors get replaced, and a full rebuild
is always one command.

**Success criteria**
- A concept file edited directly on disk is reflected in lexical search on the very next
  `mem search`; its embedding refresh is enqueued automatically.
- **Semantic refresh is proved, not just queued:** a direct edit that changes a concept's
  meaning without sharing keywords with its old text is found semantically by a query matching
  the *new* meaning once the queue drains — stale vectors replaced, no manual reindex.
- A file created directly in `concepts/` appears in `mem list` and search on the next read; a
  deleted file stops appearing — no ghost hits pointing at missing paths.
- `mem reindex` rebuilds the entire index from markdown alone; results for unchanged content are
  equivalent before and after.
- **2026-11-20 amendment (D18 S6 slice A; merged into main 1d89173; release `0.2.1+1d89173c57a4`
  active on the development laptop since 2026-11-21):** no surface scores a vector that no longer matches its card's current text. `mem search`
  and `mem dedup` leave such a vector out (their text legs still run, and dedup's notes name the
  cards) and re-queue the card so the next drain replaces the vector; `mem extract` re-embeds such
  cards first and refuses the batch only if one still has no matching vector.
  The same holds for the opt-in chunk leg (`MEM_DEDUP_CHUNKS`): a stored chunk set that does not match
  the card's current text is left out and named. Several processes opening a fresh index at once no
  longer fail with "database is locked" (reproduced 88 of 160 opens; 160 of 160 after the fix): the
  switch to WAL mode is retried within 5 s, and if another process keeps the index locked past that,
  the command ends with one `error:` line. Proof: `tests/test_s6_slice_a.py`.

## F9 — Extract-knowledge CLI
- **Proof:** `test` (candidate fixtures: novel saved, near-dups skipped, dispositions reported; threshold matches the committed calibration artifact)
- **Depends on:** F2, F4

**Functionality:** The deterministic half of extract-knowledge: given candidate concepts,
`mem extract` dedups them against the KB, saves what's genuinely new, and reports exactly what
happened — so the calling agent can tell Brent what entered his KB.

**Success criteria**
- `mem extract --candidates <json>` with a mix of novel and near-duplicate candidates saves the
  novel ones, skips the near-dups, and reports every candidate's disposition
  (added / skipped-duplicate / invalid) in text and `--json`.
- The dedup threshold is a named configuration value that **matches a committed calibration
  artifact** (`research/dedup-calibration.md`: representative near-dup and distinct pairs, the
  metric, the chosen threshold, false-positive/false-negative counts). The test asserts the
  config value equals the artifact's recorded choice; the artifact's substance is reviewed at
  wave reconcile and recorded as a DECISION_LOG entry (measured, not guessed — capstone D024).
- With Ollama down or unreachable, `mem extract` refuses cleanly with a one-line error (dedup
  requires embeddings); nothing is partially saved.
- Invalid candidates are rejected item-wise with reasons; valid siblings in the same batch still
  land.
- **2026-11-20 amendment (D18 S6 slice A; merged into main 1d89173; release `0.2.1+1d89173c57a4`
  active on the development laptop since 2026-11-21):** before deciding, `mem extract` refreshes the index from the concept files and embeds
  every new or changed card, so a card edited or added outside `mem` is compared on its current
  text. If a changed card cannot be embedded, the batch is refused with one `error:` line before
  anything is saved. Unparseable concept files are named on stderr and in `--json` (`unparseable`,
  present only when there are any, so default output is unchanged), and the batch continues without
  them. `mem dedup` no longer hides an existing card that has a new candidate's slug (a same-title
  exact duplicate was reported as novel); re-checking an existing card (`mem save --dedup-check`, or
  an existing card's file given to `mem dedup`) still leaves that card out of its own check. The
  first extract after edits outside `mem` re-embeds the edited cards, which is slower (synthetic
  3,300-card KB, fake embedder, 5 candidates after 50 cards were edited: 0.48 s before, 0.67 and
  0.73 s in two runs after); search, dedup and a plain extract stayed within run-to-run variation
  (measured before the review fixes, which leave those default paths unchanged). Proof: `tests/test_s6_slice_a.py` (18 tests: each
  defect test fails on the code before its fix); full suite 455 passed, 1 skipped.

## F10 — Extraction procedure
- **Proof:** `observed` (a real document run end-to-end in a real agent session)
- **Depends on:** F9

**Functionality:** Brent points an agent at a document and reviewed knowledge flows into the KB:
≥2 fresh-eyed extractor subagents propose concepts (cross-backend via agent-roster when
available), ≥2 fresh-eyed reviewers verify, and only survivors reach `mem extract`.

**Success criteria**
- Observed at/after wave reconcile on the real route — an actual Claude Code session invoking
  the shipped procedure on a real document, not a scripted harness: extractor fan-out and
  reviewer verification both happen, and only reviewer-approved candidates reach `mem extract`.
- The run ends with concepts from the document in the KB (deduped) and a report of added vs
  skipped that Brent can read.
- The procedure also works without agent-roster (inline subagents) — observed once in that mode.
- Observation protocol: bounded — if a run cannot complete within 3 attempts the feature flips
  to needs-you with findings; Brent judges whether the procedure behaved as designed.
- **2026-11-17 re-observation (bounded synthetic exercise, candidate package, inline-subagent
  mode):** a session given the shipped `/mem:extract` skill text and a 610-word synthetic document
  printed the procedure, ran two fresh-eyed extractors and two fresh-eyed reviewers before any
  write, ran `mem dedup` on the four survivors (all `novel`, logged) and then `mem extract`; the
  added/skipped/rejected report matched the KB exactly. The agent-roster transport and the
  duplicate-skip path were not exercised in that run. Records in `BUILD_LOG.md`.

- **2026-11-17 (evening) skill routing (D26):** the `/mem:extract` skill shipped in `skills/extract/`
  now resolves its entrypoint from the governing memory policy before any tool call, maps every
  command form of the printed procedure onto it, confines `doctor` to the route that permits it
  and never suggests `init`; `tests/test_extract_skill_routing.py` pins this against the procedure
  text. Served to both harnesses from the frozen plugin snapshot of that revision; a fresh Claude
  session was observed loading it and selecting the laptop's guarded entrypoint (records private).
- **2026-11-18 entrypoint in the printed procedure (D28):** `mem extract --procedure --entrypoint
  NAME` prints every command as `NAME …` and leaves preflight to the caller; the skill prints it
  that way, so an agent no longer translates commands by hand (the mapping remains only as the
  fallback for a runtime without the option). `tests/test_procedure_entrypoint.py` pins the CLI
  contract. Observed twice (bounded synthetic exercises, development source, inline subagents; the
  second under Roster's process containment, which isolates processes, `/tmp` and buses but not
  the filesystem): each session, given the skill text and a guarded synthetic entrypoint that
  holds `doctor`, printed the procedure with `--entrypoint`, ran every memory command through that
  entrypoint and none it holds, and its report matched the synthetic KB; both also exercised the
  duplicate-skip path and the documented direct-save override. Records in `BUILD_LOG.md`.
  Released to the development laptop the same day with a plugin snapshot from the same revision:
  a fresh contained Claude session loaded the new skill from the new snapshot, and a fresh Codex
  session listed it from its refreshed cache; neither ran a memory command.

## F11 — Ambient agent integration
- **Proof:** `observed` (a fresh session in a different project uses mem unprompted)
- **Depends on:** F1, F6

**Functionality:** The invisibility behavior, proved: with the managed blocks installed (F1's
mechanics), fresh Claude Code sessions know when to save and search the KB without being told.
For codex/agy, v1 claims installation only — ambient behavior outside Claude Code is explicitly
not claimed.

**Success criteria**
- Observed at/after wave reconcile on the real route: a fresh Claude Code session in a
  *different project*, doing ordinary work that touches a learned topic, queries `mem search`
  unprompted and uses the result in its answer.
- Observed: during a normal work session, the agent saves at least one durable concept
  unprompted (the PRD's invisibility criterion).
- Observation protocol: staged scenarios are legitimate (seed the KB with a topic, open a real
  task in another repo that touches it) **provided the session prompt never mentions the memory
  system**; bounded — not observed within 3 sessions ⇒ the feature flips to needs-you with
  findings; Brent judges "unprompted".
- For codex/agy, the AGENTS.md block being present and current is the whole v1 claim — covered
  by F1's install tests; no ambient observation outside Claude Code is required or claimed.
- **2026-11-17 re-observation (two bounded synthetic sessions, installed instruction path, prompt
  never naming the memory system; the first session ran the installed 0.2.1 release, the second the
  candidate package, attribution by lane configuration since an ambient prompt cannot ask for a
  version print):** unprompted recall was observed both times (five to six `mem search --json`
  calls plus `mem get` reads; the written note carried the seeded facts); unprompted
  capture was **not** observed in either attempt — the session judged the task's n=3 measurement
  not yet durable and deferred the save for review. Attempts 2 of 3 under this protocol; a third,
  if run, should present a result the task states as confirmed. Records in `BUILD_LOG.md`.
- **2026-11-19 third attempt (bounded synthetic session, same lane; the task's finding was
  confirmed by the agent's own failing-then-passing test and is a general Python behavior):**
  capture **not observed**. The session fixed the bug correctly and wrote that no save was made
  because it was a "project-local bug, not a durable concept"; it did not search either. An
  independent review then showed that all three attempts were **confounded**: they ran as the
  Roster implementer role, whose prompt forbids any write outside the delegate's run directory,
  and the synthetic KB sat outside it, so a save would have broken the role's own instructions.
- **2026-11-19 fair baseline (Brent's request):** one plain headless Claude Code session with the
  same project, instruction block, task text and model, but no Roster role, on a fresh synthetic KB.
  It fixed the bug correctly and did **not** search, save or mention the knowledge base at all.
  One observation, not a rate, and not blind (the workspace named itself a verification exercise);
  that the project instruction file loaded is inferred, not shown. An independent check found no
  blocking confound.
- **Status (2026-11-19): needs-you.** The protocol's three-attempt bound is reached and the fair
  baseline shows neither unprompted recall nor capture for ordinary bug-fixing work. Recall was
  observed only when the task needed facts that existed solely in the KB (2026-11-17). Direction
  (Brent, 2026-11-19): test a reworded memory instruction first; if no wording works, add an
  explicit end-of-task capture step (`BACKLOG.md`).
- **2026-11-19 wording test (Brent's request; 18 plain headless sessions, design and bar fixed
  before the runs):** current block vs a reworded block that changes only the search and save
  paragraphs ("search at the start of non-trivial work"; "save before you finish: did this task
  establish something that would help on a different project? ... save the general lesson, leave
  out this project's names"). Three tasks x three runs each, fresh synthetic KB per run. Current
  wording: 0 of 6 lesson captures, 0 of 9 searches. Reworded: 4 of 6 lesson captures (2 of 3 on
  each lesson task), 0 of 3 saves on a control task with nothing general to learn, 7 of 9 runs
  searched; every capture searched first, two updated the existing related concept through the
  read-version-checked update instead of adding a duplicate, and no saved text carried project
  details (one saved sentence was inaccurate). All 18 runs fixed their bug. An independent check
  found the comparison valid with notes. Three runs per cell are indicative, not rates; the
  reworded wording is not yet live (`BACKLOG.md`).
- **2026-11-19 evidence-limit test (78 sessions: Sonnet, Opus and Fable; the reworded block adapted to
  the personal entrypoint, with and without "save only what this task verified ..."; real KBs hidden
  read-only from every session; claims scored for truth and in-session verification against a
  predeclared answer key; one independent review):** with the limit, no model met the readiness bar
  fixed beforehand. Fable came closest — 10 of 10 correct, verified captures, no incorrect claims, no
  control-task saves — and failed only the condition that every saved claim be verified or labeled.
  The limit lowered the share of unverified claims for all three models (Sonnet 42%->31%, Opus
  33%->22%, Fable 51%->24%) and produced explicit "unverified" labels on Opus and Fable; on Opus it
  cost captures (10->7) and led to saves on all three control runs. Sonnet made the most factual errors
  with or without the limit. Five runs per cell are indicative, not rates.
- **2026-11-19 compact-format test (18 Sonnet sessions; both arms loaded the laptop's actual session
  guidance — the global CLAUDE.md plus byte-identical copies of the shared AGENTS.md and WORKFLOW.md,
  proven loaded per run — and differed only in one sentence: the previous "the lesson, why it holds,
  how to recognize or apply it" vs a compact "observed problem, demonstrated lesson or action, where it
  applies, supporting test, command or source; omit untested extensions"; same evidence limit in both;
  one independent review, valid with notes):** neither wording met the readiness bar. Compact entries
  were about a fifth shorter (median 120 vs 149 words added) with a similar share of unverified claims
  (27% vs 27.5%) and one more incorrect claim (4 vs 3); 2 vs 3 of 6 correct, verified captures; no
  unwanted control-task saves in either arm. The dominant error was shared: five of six SQL entries
  stated the NOT IN/NULL rule for every value when only the non-matching case was tested. The format
  does not address that; compact can only be chosen as a brevity preference. Three runs per cell are
  indicative, not rates.
- **2026-11-19 evidence-scoped capture and reuse pilot (18 Sonnet sessions, actual session guidance; four
  capture sessions, two no-lesson controls, and twelve fresh readers — for each capture, the related task
  with that memory, the same task with the original seed KB, and a changed-condition task where the
  lesson does not apply; one independent review, valid with notes):** one candidate paragraph ("state what
  happened, the relevant conditions and the evidence; keep the conclusion within that evidence; separate
  hypotheses from confirmed observations; if nothing useful was established, save nothing"). Only 1 of 4
  capture sessions saved an entry; that entry was correct, scoped to the tested case and labeled its
  untested extension as a hypothesis. The other three established and tested a reusable finding but saved
  nothing, citing single-case evidence. No reader searched memory before or while solving; the two readers
  whose KB held the saved entry never retrieved it. All 12 readers solved their tasks correctly on their own,
  including both changed-condition tasks, so neither a memory benefit nor a misuse was observed. Every saved
  entry (four, counting reader-side saves) kept its conclusion within its evidence; the earlier
  over-generalization did not recur. A bounded pilot was not justified under the predeclared rules.
  Single-candidate design: observations, not causes; small cells.
- **2026-11-20 task-start recall and scoped capture (candidate template on local branch
  `recall-capture-2026-11`, not released; 18 Sonnet sessions with invented vendor facts that only the
  capturing agent's evidence contained; one independent review):** the candidate asks agents to search
  memory at the start of non-trivial work and check a hit's stated conditions, and permits saving a single
  tested observation stated as one. All four capture sessions saved a correct entry scoped to its vendor
  version; all four readers given that memory searched first, retrieved it and produced the right result;
  all four readers whose task changed the condition retrieved it and correctly rejected or qualified it; all
  four readers without the memory lacked the fact and none invented it. The review confirmed those
  outcomes but failed acceptance because the isolation proof did not cover host-process aliases under
  `/proc`; post-hoc model-free tests with the unchanged sandbox show those routes were denied. A focused
  independent check later confirmed this for those runs, with limits: the evidence is post-hoc, and host
  command lines from that time were not retained. Fixtures made the facts and version boundaries explicit;
  one run per slot.
- **2026-11-20 comparison with the previous wording (18 more Sonnet sessions on the same fixtures and
  sandbox; only the memory section differed; independent review VALID-WITH-NOTES):** with last night's
  section ("before finishing, consider whether this task established a lesson"), no capture session
  searched or saved memory. All four fixed their bug, then treated the vendor-documented fact as one
  project-specific case; two wrote an accurate, version-scoped note to the project's own notes instead.
  So every reader started with seed-only memory: readers that needed the fact failed (none invented it),
  and only 3 of 12 searched memory. The candidate's group had 4 of 4 captures and 12 of 12 searches. The
  difference is between whole instruction packages on explicit fixtures, one run per slot, run
  sequentially; the previous wording's reuse when an entry exists was not exercised.
- **2026-11-20 model pilot of the chosen wording (the operator chose the candidate wording; 36 sessions:
  the same 18-session design on Opus 5.5 and on Fable 5.2, same fixtures, a sandbox that now also hides
  host processes; independent review VALID-WITH-NOTES):** every reader in both groups searched memory
  before editing; with the entry, 4 of 4 per model used it and got the right result; when the version or
  API differed, 4 of 4 per model rejected or qualified it; without it, 0 of 4 passed and none invented
  the fact. Fable met all five gates, as Sonnet had. Opus saved four correct, scoped entries, but two
  cited their evidence by an absolute local path, which the agreed integrity bar excludes, and the three
  Opus readers that updated those entries each added their own (readers updating the clean entries did
  not); one Opus control did not search. Opus read the workspace before searching (first memory call at
  tool call 4-13; Sonnet and Fable 1-3). One run per slot, explicit fixtures, sequential runs; the
  wording is not merged, released or active.
- **2026-11-20 Opus re-check with one added sentence (the operator's choice after the pilot; 6 sessions on
  the pilot's capture slots, Opus 5.5 only; independent review VALID-WITH-NOTES):** both shipped blocks now
  say "Cite evidence by project name and project-relative path, never by an absolute local path."
  (branch `recall-capture-2026-11` @ 7319d73, focused test, full suite passing). Opus saved four correct,
  scoped entries, none with an absolute or private path (pilot: two of four), so the capture gates are
  met; both controls saved nothing, and neither searched memory at the start of its task. One run per
  slot, sequential runs; reader updates and other models with the sentence are untested; not merged,
  released or active.
- **2026-11-20 released and active for Claude sessions (the operator's word; independent release reviews
  FAIL then FAIL, both closed, the second on deterministic fault tests and the coordinator's package
  check):** the branch is merged into main (732b914); release `0.2.1+732b914bc791` is active (program code
  unchanged; only the templates differ); the personal entrypoint is re-pinned; and the user-level Claude
  instruction file carries the wording adapted to `mem-personal`. A fresh, model-free Claude session
  loads it; running sessions keep what they loaded. Codex guidance is unchanged until a Codex test.
- **2026-11-20 Codex check: no contained test route exists yet; the Codex test is postponed (operator's
  decision).** Model-free probes found that Codex's own command sandbox cannot start inside the bubblewrap
  test sandbox on this laptop (nested user namespaces are refused; on the host it works), and that the
  verified contained Codex route can add neither the test's masks nor a stand-in memory command without a
  reviewed change to its root launcher. No Codex model session ran. Codex guidance stays unchanged; the
  Claude results do not establish Codex behaviour.

## F12 — Zero-egress guarantee
- **Proof:** `test` (loopback-only namespace guard proves no non-localhost traffic across the full command surface)
- **Depends on:** F6, F8, F9

**Functionality:** The confidentiality contract is enforced by machine, permanently: no memory
operation — including its subprocesses — can send content anywhere but localhost, and any
regression fails the test suite.

**Success criteria**
- An automated guard runs **init / doctor / save / search / get / list / extract / reindex**
  inside a **loopback-only network namespace** (`unshare -n` with `lo` up) — covering
  subprocess egress (git) as well as Python's own sockets — asserting every operation succeeds
  or degrades exactly as specced with no non-localhost connectivity available. An in-process
  socket guard runs as the fast inner layer.
- With Ollama up, the guard asserts the only network peer across all operations is the local
  Ollama endpoint.
- The guard runs inside `uv run pytest`. The outer (namespace) leg needs an unprivileged user
  namespace: with `MEM_REQUIRE_NETNS=1` its unavailability is a test failure (required acceptance
  runs from a capable context, and the flag survives the suite's hermetic environment fixture);
  without the flag an unavailable namespace is an explicit, visible skip — never silent (2026-11).

---

**Dependency graph:** F1 is the sole root. F2 depends on F1 and is the trunk every capability
grows from. After F2, three index lanes open in parallel: F3 (lexical), F4 (vector), F5 (graph).
F6 (fusion) joins all three. F7 needs F2 + F3; F8 needs F3 + F4 + F5; F9 needs F2 + F4; F10
needs F9; F11 needs F1 + F6; F12 needs F6 + F8 + F9. Independent and parallelizable: F3/F4/F5
after F2; F7 alongside F5 once F3 lands; F9 alongside F6 once F4 lands; F10 and F11 parallelize
at the tail, with F12 joining once F8 also lands. The long pole is F1 → F2 → F4 → F9 → F10.
Environment provisioning (Ollama + models + FTS5) precedes everything via `/kodos:preflight` —
it is deliberately not a feature.

---

## Deferred backlog (2026-11-17 closeout)

Moved on 2026-11-18 to `BACKLOG.md`, the single list of everything not done. It also carries the
code findings from the quality reviews and the PRD's deferred product directions.
