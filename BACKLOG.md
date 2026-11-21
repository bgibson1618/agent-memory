# Backlog — agent-memory

Everything known to be not done, in one list. Consolidated on 2026-11-18 from the deferred backlog
in `FEATURES.md`, the deferrals in `DECISION_LOG.md`, the quality reviews journaled in
`BUILD_LOG.md` and the PRD's non-goals. Every code finding below was re-checked against the source
on 2026-11-18; findings that had already been fixed are listed at the end.

Nothing here is a commitment. Each item is taken up as its own reviewed slice on the operator's
word, and anything that changes what runs on the laptop needs a new release (`RELEASE.md`).

## Suggested order

1. **F11 capture protocol** (Brent, 2026-11-19: establish it before the dedup work): the reworded
   instruction raises captures (test 1); an added evidence limit lowered unverified content but no
   model met the strict readiness bar (test 2: Fable closest); a compact entry format shortened
   Sonnet's entries without improving their support or accuracy (test 3); an evidence-scoped paragraph
   kept the one saved entry within its evidence, but three of four sessions saved nothing and no reader
   retrieved memory before working (test 4); a candidate template asking for a search at task start and
   allowing scoped single-case saves met every gate on invented vendor facts (2026-11-20, branch
   `recall-capture-2026-11`); its sandbox's process-alias isolation was later independently confirmed with
   post-hoc limits, and on the same fixtures the previous wording produced no captures and little search
   (0 of 4; 3 of 12). On 2026-11-20 the operator chose the candidate wording; a model pilot (the same
   design on Opus 5.5 and Fable 5.2) found that recall and reuse carry over to both and that Fable met
   every gate, while 2 of 4 Opus entries cited evidence by absolute local path (outside the integrity
   bar) and the Opus readers that updated those entries each added their own. The operator then chose a
   one-sentence rule ("Cite evidence by project name and project-relative path, never by an absolute
   local path.", branch @ 7319d73); a 6-session Opus re-check of the capture slots met the capture gates
   (4 of 4 correct, scoped entries without such paths; controls saved nothing). Merged, released and
   active for Claude sessions on 2026-11-20 (release `0.2.1+732b914bc791`; the user-level Claude
   instruction file carries the wording). The Codex test is postponed (operator, 2026-11-20): no
   contained route can run it yet (see "Contained Codex test route" below); Codex guidance stays unchanged.
2. **D18 S6, slices A then B then C** (decided 2026-11-19, D29): extraction and duplicate detection
   decide on current files, write all-or-nothing, and share one decision. Slice A is built and merged
   into main (1d89173, 2026-11-20, the operator's word), and release `0.2.1+1d89173c57a4` is staged
   and rehearsed; switching it live waits for the operator's explicit word and a coordinated window.
   Then slice B.
3. **Close the D30 release's rollback window** on the operator's word, with the D27/D28 window (on or
   after 2026-11-25): keep `0.2.1+a6d77bfd71d2` and the saved copies until then.

## Features and correctness

- **F11, adopt the reworded capture instruction (tested 2026-11-19).** In an 18-session test the
  reworded search/save paragraphs produced 4 of 6 lesson captures and no control-task saves; the
  current wording produced none (`FEATURES.md` F11). The tested behavior — recording a confirmed,
  reusable lesson that the current approved task established — is what the governing memory policy
  already asks for through the personal entrypoint, so no authority expansion is involved. Adoption,
  held for the operator's choice, means: (a) a reviewed change to the guidance laptop sessions
  actually read (they load a policy-reference block, and regenerating live guidance is a separate
  configuration change) plus the package template, shipped by a release; (b) the wording adapted to
  the personal entrypoint with read-version-checked updates; (c) a limit to what the task verified:
  one of the four test saves added an unchecked claim, so the proposed (untested) addition is "save
  only what this task verified; say how, and where it applies". Tested 2026-11-19 on Sonnet, Opus and
  Fable (`FEATURES.md` F11): it lowered unverified claims for all three, but no model met the
  zero-unverified readiness bar; on Opus it cut captures and caused control-task saves; Sonnet's
  factual errors persisted. A compact format (test 3, Sonnet only, actual session guidance) shortened
  entries by about a fifth but kept a similar unverified share and one more incorrect claim; neither it
  nor the previous format met the bar, and both overstated a rule beyond the case the task tested.
  The evidence-scoped candidate (test 4, single-candidate pilot with fresh readers) produced one sound,
  scoped entry, but three of four capture sessions saved nothing despite a tested reusable finding, and no
  reader searched memory before working (0 of 12; the saved entry was never retrieved). Open questions for
  the next proposal (each needs its own approval): whether saving a scoped single-case observation should be
  stated explicitly as acceptable, and how retrieval at the start of work is prompted, since reuse cannot be
  shown without it; reader tasks should need knowledge the memory holds. Transfer tests (Opus, Fable; later
  Codex models) wait until the Sonnet approach is settled. 2026-11-20: the candidate (search at task start;
  scoped single-case saves; project-only facts to notes) is on local branch `recall-capture-2026-11` with a
  focused test; its acceptance exercise met all gates. Its review asked for proof that host-process
  aliases under `/proc` were denied. A focused independent check confirmed that for the recorded runs, with
  post-hoc limits. A comparison run of the previous wording used the same sandbox, with alias checks added
  to the per-run probe, and produced 0 of 4 captures, so it could not exercise reuse. Hiding host processes
  outright (`--unshare-pid` with a fresh `/proc`) was applied from the 2026-11-20 model pilot on, with a
  per-run check and failure-path controls; it was not applied mid-comparison because it would change the
  environment between groups. Messier evidence (no vendor statement,
  implicit versions) is untested. The wording is chosen (operator, 2026-11-20: the `recall-capture-2026-11`
  candidate, amended the same day with the evidence-reference sentence after Opus entries cited absolute
  local paths; re-checked on Opus captures only, reader updates untested); open choice: whether the
  zero-unverified condition is the right adoption bar. The explicit end-of-task step
  stays the fallback (Brent, 2026-11-19). Any further test must not use a Roster role whose prompt forbids
  writes outside its run directory.
- **Contained Codex test route (postponed test, 2026-11-20).** A Codex capture/reuse test needs a
  boundary the laptop does not offer today: Codex's command sandbox cannot run inside the bubblewrap test
  sandbox (nested user namespaces are refused), and the verified contained Codex route cannot hide the
  test's answer files, earlier runs, transcripts or the real memory commands without a change to its root
  launcher. The way forward is a separately scoped, reviewed launcher test mode (system-level approval),
  then the same design on one Codex model with Codex-adapted wording; until then Codex guidance stays
  unchanged. A weaker smoke test on the unchanged route would be a different, fully disclosed design.
- **Save-time path check in `mem` (backlogged 2026-11-20 with the operator's agreement).** `mem save`
  would warn on or refuse absolute paths under the home directory or the private research roots in an
  entry's body and source. It would cover reader updates and every model; the wording sentence was
  re-checked only on Opus captures. A separate product slice with its own review.
- **D18 S6, slice A — decide on current files.** Before deciding, extraction refreshes the index
  from the concept files and drains the embedding queue; no surface ever scores a vector whose
  content hash differs from the file's current text; unparseable files are reported by name; the
  concurrent-start sqlite "database is locked" crash at the WAL pragma becomes a one-line error or
  goes away; `mem dedup` stops excluding an existing card that shares a new candidate's slug.
  Reproduced 2026-11-19 on the active release's code: extract misses hand-edited and hand-added
  cards until another command refreshes the index; `mem dedup` flags against a hand-edited card's
  stale vector; `mem dedup` calls a same-title exact duplicate novel. Source: D29.
  **Built 2026-11-20 on branch `s6-slice-a-2026-11` (1092398 plus review fixes 9484dab and df2c097) and merged
  into main as 1d89173 the same day; release `0.2.1+1d89173c57a4` staged, not active** (`FEATURES.md` F8, F9). Each defect was first written as a test that
  failed on the code before the fix. The independent review (contained Codex, static) failed the
  first version: the opt-in chunk leg could still score stale chunks, and an exhausted WAL switch
  still reached extract and dedup as a traceback. Both are fixed with tests, along with a too-broad
  fallback in the freshness check; a second review found that fallback still accepted a damaged
  full-text index, and that `mem save --dedup-check` could fail a committed save on an index error
  (both fixed with tests); a third review passed the slice (one pre-existing cleanup item, below). Expected after release: the first extract re-embeds any card
  whose vector no longer matches its file (cards edited outside `mem` and not yet re-embedded; by
  the code history, otherwise only vectors written before 2026-07-23 and never refreshed).
- **D18 S6, slice B — all-or-nothing extraction batch.** Phase 1 does all daemon work; phase 2
  re-checks under the write lock that nothing changed, writes the batch, makes one path-limited
  commit, creates files exclusively, and on failure removes only its own files (never
  `git reset --hard`); a journal covers a crash between writes and commit; link remaps happen in
  memory with re-embedding queued after the commit; dedup-log records are history, written after
  the commit and kept in a pending file if the append fails. Today's decision rule is kept, so
  ordinary output is unchanged. Reproduced: a failure partway through leaves earlier concepts
  committed and a staged file behind; two concurrent extracts often both save the same concept
  (the second under `-2`, reported as distinct). Source: D29.
- **D18 S6, slice C — one decision.** `mem extract` decides with `dedup.detect()` and `mem dedup`'s
  coverage policy, acting on `recommended_action` (only `skip` skips; `review` and
  `update-existing` are held for judgment); `mem save --dedup-check` gets the same policy; the
  procedure's separate dedup step folds into extract's report. Reproduced: extract saved 10 of 10
  partial duplicates that `mem dedup` caught on a 3,300-card synthetic KB. Reserved seams exist
  (`strict_claim_leg`, `precomputed_claim_vecs`, `fakes.die_after`). Source: D29.
- **D18 S6, slice D (optional; Brent, 2026-11-19: decide after measuring) — rulings into extract.**
  Let `mem extract` accept the agent's recorded DUP/DISTINCT rulings so a held candidate judged
  distinct lands inside the same batch instead of through a separate direct `mem save`. Slice C
  must make the number of held candidates countable (report and dedup log), and the decision
  returns once real extractions show how many are held.
- **OKF v0.2 provenance fields, optional.** Emit `generated` and `sources[]` alongside the current
  fields, only if interoperability with a v0.2 provenance consumer is wanted. Source: D2
  (2026-11-17).

## Performance

- **Claim matching recomputes on every union round.** Memoize each claim's unit vector and norm,
  and compute the claim-match matrix once per hit for `greedy_union_cover`. A validated hazard,
  backlogged on 2026-09-03 as the first task of S6; it matters once the semantic claim leg, which
  ships off, is enabled at volume.
- **`mem list` parses every concept file** instead of querying the lexical table (2026-08-14,
  2026-09-03).
- **YAML is parsed with the pure-Python loader** although libyaml is available; switching to
  `CSafeLoader` is a one-line change (2026-08-14).
- **Extraction embeds the whole batch in one request under the flat embed timeout**, so a large
  batch can time out. Chunk the request (2026-08-10, repeated 2026-08-14 and 2026-08-17).
- **Extraction's nearest-match search is a Python loop over candidates times the whole KB**
  (`_best_match`, 2026-08-17). Goes away with S6 slice C, which uses the vectorized scan. Baseline
  (2026-11-19, synthetic 3,300 cards, fake embedder): 20 candidates take 1.0 s in `mem extract`
  and 3.3 s in `mem dedup`; no performance work is a prerequisite for S6.
- **Append-only logs are read whole.** `mem stats` reads all of `usage.jsonl` and the dedup-log
  reader reads all of `dedup-log.jsonl`; both files grow without bound (2026-09-03).

## Code quality

- `_extract` in `extract.py` is a single function of about 210 lines; split it.
- `extract.py` calls other modules' private helpers (`store._derive_description`,
  `store._split_csv`, `store._sweep_dead_temps`, `vector._stamp_meta`); make them public or move
  the logic.
- `chunks.py` and `claims.py` hand-mirror the same identity-stamp and rebuild engine; extract a
  shared helper (2026-09-03).
- The wikilink pattern is defined separately in `okf.py`, `graph.py` and `extract.py` (2026-08-10).
- A damaged index (for example a missing FTS5 backing table) reaches `mem extract` and `mem dedup`
  as a Python traceback; nothing is saved, and `mem search` already reports it in one line. A
  one-line `error:` naming `mem reindex` would match (2026-11-20, S6 slice A review 2).
- `dedup.build_corpus` leaves its lexical connection (and the optional chunk and claim connections)
  open if construction raises before the `Corpus` is returned; close them on that path. The
  connection lives only until the process exits (2026-11-20, S6 slice A review 3; pre-existing).
- `lexical.db_path()` raises `NameError`: it still refers to `DB_NAME`, which moved to `indexdb` on
  2026-08-05. Nothing calls it, so it is dead code; delete it or point it at `indexdb.db_path`.
  (Listed as fixed on 2026-11-18 in error; re-checked against the source on 2026-11-20.)
- `scripts/kb-obsidianize.py` hardcodes the default instance's concept directory, bypassing
  `MEM_KB_ROOT` (D15), and carries its own slug function that differs from `okf.slugify`.
- No linter is configured.
- Nits: two function-local `import re` in `chunks.py`; text-mode `mem get` omits the `source`
  field, which JSON mode carries.

## Product directions the PRD defers

- An MCP server, the planned cross-agent port.
- Session hooks or automatic injection of memories.
- Ambient behaviour for Codex and other agents beyond the CLI and the `AGENTS.md` block.
- A rerank stage for fused search.
- A single-extractor `--quick` extraction mode (D4).
- Consolidation ("dreaming"): later, if ever.
- Renaming the repository and CLI (the "Folio" working name).
- A format migration to OKF v0.2: reviewed and not planned (D2).

## Held: operator decisions, not code

- **Host-mediated shared writes (D20).** Built and held. Re-enabling them is an operator decision
  with its own approval; the operator profile is held aside on the development laptop.
- **Zero-egress outer leg (D23).** The network-namespace leg cannot run where unprivileged user
  namespaces are refused. Required acceptance runs from a context that can create one, or records
  the skip with its reason.

## Operations on the development laptop

- **Close the rollback window on 2026-11-25** if a week of normal use passes without issue.
  Archive the candidate clone's review-run transcripts first; then remove the rollback copies,
  the superseded plugin snapshots and the rehearsal scratch. Since the D28 release, release
  `0.2.1+a1c3a6319b61` and `plugin-0.2.1+8be9b0927063` are that release's rollback target and stay
  until its own window is closed. The candidate clone goes only on a separate word. The prepared
  checklist is in the private operations records.
- **Private historical evidence** under `.kodos/evidence/` stays untracked: keep it there or move
  it to the private records (D27).
- **A stale marketplace entry in the Codex configuration**, pre-existing and unrelated to this
  project, makes Codex's global plugin listing fail. The `mem` plugin itself is unaffected.

## Obsolete candidates awaiting the operator's word (D24)

Tied to a retired engagement or a retired machine layout; nothing has been deleted.

- The G1 per-instance calibration replay.
- The G2 60-ruling false-suppression sweep.
- The retired engagement's backup cron.
- The wiring of `scripts/agent-memory-backup`, whose bundle-verify diagnostic is also silenced
  (2026-08-17 nit).
- The personal-KB passport backup plan.
- The 2026-09-21 frozen-copy scheme, superseded by `scripts/release.py` (D22).

## Tracked in other repositories

Process items recorded in 2026-08 belong where they are tracked, not here.

- **agent-roster** keeps its own backlog under `docs/backlog-*.md`. The August items were result
  arrays compacting when a fanout lane fails, long-context model defaults for delegates, a
  delegate ending its turn while a fanout still runs, reviewer self-preference in cross-vendor
  pairs, and writer delegates without web tools. Later roster releases added a turn-end stall
  check, long-context model routing, fanout validation and cross-vendor skeptic gates, which bear
  on most of them; whether each is closed has not been re-verified.
- **The document-extraction pipeline's playbook**: review against the live KB, not only within
  the batch; persist every stage script; generalise the enforced-gate pattern; assert every
  substitution in a generated script.

## Fixed since first recorded

- The procedure entrypoint (D28) released and activated on the development laptop (2026-11-18):
  runtime `0.2.1+a6d77bfd71d2` and `plugin-0.2.1+a6d77bfd71d2`, from one revision, switched together.
- Concept slugs `index` and `log`, reserved by OKF, are refused (D5).
