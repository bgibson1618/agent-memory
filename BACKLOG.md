# Backlog — agent-memory

Everything known to be not done, in one list. Consolidated on 2026-11-18 from the deferred backlog
in `FEATURES.md`, the deferrals in `DECISION_LOG.md`, the quality reviews journaled in
`BUILD_LOG.md` and the PRD's non-goals. Every code finding below was re-checked against the source
on 2026-11-18; findings that had already been fixed are listed at the end.

Nothing here is a commitment. Each item is taken up as its own reviewed slice on the operator's
word, and anything that changes what runs on the laptop needs a new release (`RELEASE.md`).

## Suggested order

1. **F11 third observation**: it answers whether ambient capture works at all.
2. **Release the procedure entrypoint** (done in source, D28): freeze the runtime release and
   the plugin snapshot from one revision and switch both; it exercises the release flow end to end.
3. **D18 S6 with the dedup performance items**: they touch the same engine.

## Features and correctness

- **F11, third unprompted-capture observation.** Both bounded synthetic attempts on 2026-11-17
  showed unprompted recall but no unprompted capture. A third attempt under the same protocol
  should present a result the task states as confirmed; if capture is still not observed, F11
  flips to needs-you with findings. Source: `FEATURES.md` F11.
- **D18 S6, rewire `mem extract`'s duplicate decision onto `dedup.detect()`.** The ratified
  direction is the transactional batch: phase 1 does all daemon work, phase 2 is the unchanged
  sequential detect-then-save loop under the write lock, and any failure rolls the batch back.
  Reserved seams already exist (`strict_claim_leg`, `precomputed_claim_vecs`, `fakes.die_after`).
  Until then the procedure runs `mem dedup` as an explicit step. Source: D18 (2026-09-03), D24.
- **Procedure entrypoint: release and activation.** Implemented in source on 2026-11-18 (D28,
  `mem extract --procedure --entrypoint NAME`; the skill uses it). The laptop's frozen release and
  plugin snapshot predate it; releasing it means one runtime release and one plugin snapshot from
  the same revision, switched together on the operator's word. The skill's fallback mapping
  covers the older runtime meanwhile.
- **Extraction does not see unindexed external edits.** `mem extract` drains queued embeddings and
  checks duplicates against the index without first reconciling concept files edited outside
  `mem`, so a hand-edited concept can be missed as a duplicate. The 2026-08-14 review called this
  its most consequential advisory finding.
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
  (`_best_match`, 2026-08-17).
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
  the superseded plugin snapshots and the rehearsal scratch. The candidate clone goes only on a
  separate word. The prepared checklist is in the private operations records.
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

- The reproduced `NameError` in `lexical.db_path` (2026-08-10).
- Concept slugs `index` and `log`, reserved by OKF, are refused (D5).
