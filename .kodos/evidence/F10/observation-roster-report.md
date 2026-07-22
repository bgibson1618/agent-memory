# Knowledge extraction: research/backend-research.md → KB

```text
VERDICT: PASS
DIMENSIONS:
  - preflight: PASS
  - extraction-independence: PASS
  - review-gate: PASS
  - submission: PASS
  - disposition-review: PASS
BLOCKING:
RIGOR: tuned
```

Procedure: extract-knowledge v1 (`mem extract --procedure`), followed end to end.
All 12 reviewer-approved concepts are now in the KB (`~/.agent-memory/concepts/`).

## Result summary

**Added via `mem extract` (11)** — threshold 0.79:

1. `keep-authoring-data-canonical-and-indexes-disposable`
2. `let-scale-thresholds-select-infrastructure`
3. `budget-local-ai-systems-for-coexistence`
4. `embedding-model-pinning-and-dimension-enforcement-to-protect-a-vector-index` (merged: same concept from both extractor lenses)
5. `use-mtime-caches-to-buy-latency-without-owning-a-service`
6. `make-architecture-decisions-falsifiable`
7. `dependency-selection-includes-maintenance-licensing-and-verification`
8. `ollama-on-wsl2-native-install-with-windows-cuda-passthrough-and-systemd-lifecycle`
9. `ollama-api-embed-use-the-batch-endpoint-not-the-legacy-api-embeddings`
10. `derived-graph-pattern-markdown-as-source-of-truth-in-process-graph-plus-mtime-indexed-sqlite-cache`
11. `gate-technique-re-verify-a-research-agent-s-fast-moving-claims-before-accepting-its-recommendation`

**Added via sanctioned override `mem save` (1)** — DECISION_LOG D3 disposition review:

- `embedding-context-window-pitfalls-silent-truncation-and-packaging-vs-native-limits` — dedup
  skipped it at similarity 0.8032 against the model-pinning concept. Judged genuinely distinct
  (sibling, not duplicate): pinning teaches model-identity provenance (tags/digest/dimensions);
  this one teaches context-window truncation (packaging 2K vs native 8K, `num_ctx`, effective-window
  testing). Another live datapoint that sibling concepts in the same family can clear the 0.79
  threshold.

**Skipped as true duplicates:** none. **Rejected in review:** none. **Invalid (CLI):** none.

## Pipeline trace

- **Preflight:** `mem doctor` FAIL (7/9) — only `blocks-claude`/`blocks-agents` (managed guidance
  blocks outdated; expected drift from this working tree's uncommitted block-template edits). All
  extraction-path checks passed (Ollama, embed model 768-dim, queue empty, FTS5, kb-home, no
  remote), so I proceeded rather than halting; the remedy (`mem init`) writes outside my run dir.
  See questions.md.
- **Extract:** `agent-roster fanout`, 2 fresh-eyes lenses, D1-compliant (Codex + Claude, no
  Gemini). Codex/principles → 7 candidates; Claude/techniques → 6. Schema-validated; 83s.
- **Merge (orchestrator, no subagent):** 13 → 12. Merged the one same-concept pair (embedding
  model as index schema ⊂ pinning + dimension enforcement); kept mtime-cache principle and
  derived-graph recipe both — different altitude, cross-linked.
- **Review:** second fanout, 2 fresh-eyes reviewers (Codex + Claude), document + numbered
  candidates only. 0 rejections; 4 `fix` verdicts, all applied: [9] soften over-claimed `truncate`
  semantics; [10] "Measured" → "Reported … directional estimates, not yet measured locally";
  [0]/[2] dangling `related` slugs.
- **Submit:** `mem extract --candidates … --json` → 11 added, 1 skipped-duplicate, 0 invalid.
- **Post-save link normalization (beyond the printed procedure, judgment call):** extractors
  referenced siblings by invented short slugs; the CLI derives slugs from titles, so every
  intra-batch `related` link dangled against a concept that actually exists. Applied the
  deterministic invented→actual mapping via `mem save --update` on all 12 (content untouched,
  created timestamps kept) so the concept graph connects.

## Artifacts (this run dir)

`extract-fanout-spec.json`, `extractors-result.json`, `candidates-raw.json`,
`candidates-merged.json`, `review-fanout-spec.json`, `reviewers-result.json`,
`candidates-final.json`, `extract-output.json`, `slugmap.json`.
Lens run dirs: `work/agents/fanout-1784675648-711013/` (extractors) and the reviewer fanout's
sibling dir — raw bodies stayed on disk per the fanout hygiene contract.

## Risks / follow-ups

- `mem doctor` block drift is real but cosmetic for extraction; `mem init` needs to run outside
  this sandbox (or land with the pending block-template changes).
- Procedure improvement worth considering: have `mem extract` emit each added concept's final slug
  → extractor-invented slug mapping, or resolve `related` against actual slugs at save time —
  the dangling-link normalization I did by hand is deterministic and belongs in the tool.
- Codex-lens bodies carry `Evidence: research/backend-research.md:NN` lines. Both reviewers
  approved them, so they stand, but they are project-local pointers inside otherwise standalone
  KB bodies — a lens-prompt tweak ("no file-line citations in bodies") would prevent them.
