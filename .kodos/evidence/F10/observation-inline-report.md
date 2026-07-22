# Extraction report: router_architecture_recommendations.md

Ran `mem extract --procedure` v1 end to end on
`/home/brent-gibson/projects/capstone-workspace/docs/router_architecture_recommendations.md`.
**All 8 reviewer-approved concepts are now in the KB** — 6 landed via `mem extract`, 2 via the
sanctioned `mem save` override after disposition review found both "duplicate" skips were
umbrella/sibling matches, not true duplicates.

## added (8)

Via `mem extract` (6):

- `route-with-local-model-embed-with-frontier` — two-tier embedding: local MiniLM-class model routes, API model embeds only on the vector path
- `stdlib-test-floor-not-feature-ceiling` — zero-dependency baseline is the permanent offline test floor, heavier backends are eval-first upgrades
- `ann-index-in-sqlite-blob` — single-file vector store: HNSW index serialized into a SQLite BLOB, with index-coherence caveats
- `two-stage-ann-then-sql-filter` — oversampled ANN candidates then SQL metadata filter; post-filter starvation + ordering-bug pitfalls
- `embedded-real-engines-over-mocks` — parity-test against embedded real engines; different wire protocol = new backend; port semantics (MATCH vs MERGE)
- `graphs-as-sparse-matrices` — GraphBLAS-style engines run traversals as sparse linear algebra; predictable sub-ms multi-hop, no JVM

Via override `mem save` after disposition review (2, marked as such):

- `review-verdicts-inherit-briefing-constraints` — **override**: dedup matched `make-architecture-decisions-falsifiable` at 0.7937 (threshold 0.79). Judged distinct: the existing entry is about documenting reversal thresholds for decisions; this one is about mis-briefed reviews producing artifact rejections (constraint-rejected vs evaluated-and-rejected, reframe-not-discard).
- `fts5-write-through-cache` — **override**: dedup matched `ann-index-in-sqlite-blob` at 0.7951 — a *sibling added earlier in the same batch*. Judged distinct: lexical FTS5 write-through over canonical files vs serialized HNSW vector index; both members of the "derived index in SQLite" family (umbrella: `keep-authoring-data-canonical-and-indexes-disposable`), exactly the D3 umbrella-vs-member failure mode.

## skipped as true duplicates (0)

None — both skipped-duplicate dispositions were overturned on review (above).

## rejected in review (0)

None. Reviewer 1 approved all 8; reviewer 2 approved 7 and issued one `fix`
(candidate "Stdlib baseline is a test floor, not a feature ceiling": deduped the redundant
`dependencies`/`dependency-management` topic pair), which was applied before submission.

## invalid (0)

None — all 8 candidates passed CLI validation.

## Process notes

- Extractors: 2 fresh-eyes inline subagents (Claude backend — D1 vendor policy satisfied;
  this run's inline mode, no agent-roster fanout), lenses "principles and mental models"
  (8 candidates) and "techniques and procedures" (6 candidates). Merge unioned to 8:
  6 concepts proposed by both extractors (better body kept, topics unioned), 2 unique to
  the principles lens.
- Reviewers: 2 fresh-eyes inline subagents given only document + numbered candidates.
  Survival rule applied: no rejections → all 8 submitted.
- Document is Brent's personal capstone material → `sensitivity: normal` throughout.
- All `related` slugs were verified to exist in the KB before submission (9 existing
  KB slugs referenced, plus sibling links within the batch).
- All 8 slugs verified resolvable via `mem get` after the run.
- Artifacts in this run dir: `merged-candidates.json` (numbered, pre-review),
  `candidates.json` (post-fix, as submitted).

## Flag for Brent (non-blocking)

`mem doctor` exits FAIL on two checks: `blocks-claude` and `blocks-agents` (managed guidance
blocks outdated in `~/.claude/CLAUDE.md` and `~/.agent-docs/AGENTS.md`; fix is `mem init`).
All extraction-critical checks pass (KB home, no-remote, FTS5, Ollama daemon, embed model,
empty queue), so extraction proceeded. I did not run `mem init` — it rewrites files outside
this run directory, which the Observable Session Contract forbids. Run `mem init` yourself
when convenient.
