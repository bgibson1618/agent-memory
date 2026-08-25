# Dedup calibration — work-instance matured corpus (2026-08-19)

Third calibration study; first re-check of the **work instance** (default KB,
`~/.agent-memory`) since D3 chose 0.79 on the original 26-pair clean-separation
set (`research/dedup-calibration.md`). The personal-instance study
(`research/dedup-calibration-personal-2026-08-17.md`, n=381) found that a
topically dense corpus compresses embedding space until 0.79 does almost no
discriminative work, and moved that instance to `dedup_low = 0.83` (D17). This
study measures whether the work corpus — now dense in psychometrics/IRT,
learning science, and agent-governance concepts after the August extraction
runs — has developed the same signature. It has.

## Dataset

Every `mem extract` skip across two extraction sessions, labeled by the same
KB-existence methodology as the personal study: a D3-overridden candidate has a
KB entry (label: distinct); an accepted skip does not (label: true-dup).
Labels are the sessions' full-body D3 adjudications (cross-backend
extractor/reviewer choreography, single orchestrator adjudicating).

- Batch 1 (2026-08-18): Quipu, arXiv:2608.16813 — 19 candidates, 13 flagged.
- Batch 2 (2026-08-19): Interpretable Humans, Alien LLMs, arXiv:2608.17810 —
  15 candidates, 15 flagged.
- **n = 28 labeled pairs: 27 distinct, 1 true-dup.**

## Findings

| class | n | min | median | max |
|---|---|---|---|---|
| distinct (overridden) | 27 | 0.7923 | 0.8295 | 0.8912 |
| true-dup (skipped) | 1 | 0.8461 | 0.8461 | 0.8461 |

1. **0.79 no longer discriminates on this corpus.** Flag rate across the two
   batches: 28 of 34 candidates (82%; 100% in batch 2), with 27 of 28 flags
   (96%) false-positive. Every flag cost a full-body D3 read. This is the
   personal-corpus signature (81–100% flag rates, 87–95% FP) reproduced on the
   work instance.
2. **The bottom band is clean.** Zero true-dups below 0.8461 in real
   work-corpus data. `dedup_low = 0.83` would have auto-added 13 of 28 flags
   (46% of D3 reads) at zero observed error, with margin 0.016 below the
   observed true-dup. This matches the personal study (floor 0.8413,
   chosen 0.83, margin 0.011).
3. **Known contrary data point.** The original synthetic calibration set
   contains one deliberate reworded-duplicate pair at 0.812 (below 0.83):
   "Retrieval practice ~ Testing effect". Real-corpus true-dups in both
   instances have floors ≥ 0.8413; the synthetic pair shows tight rewordings
   *can* land below 0.83. Accepted risk, hedged by the margin, per-instance
   revisability, and re-calibration after future large extractions.
4. **`dedup_high` stays disabled.** One true-dup is far too thin a sample to
   calibrate a confident-skip band.

## Decision

Set the work instance to `dedup_low = 0.83` via `MEM_DEDUP_LOW` in
`~/.bashrc` (the D15/D17 env-var pattern; the default instance has no project
env, so the ambient shell profile is its config surface). `dedup_high` remains
disabled. `config.DEFAULT_DEDUP_LOW` stays 0.79 — it is test-asserted against
`research/dedup-calibration.md` and is the fallback for uncalibrated
instances.

## Raw labeled pairs

| batch | candidate | best match | cosine | label |
|---|---|---|---|---|
| quipu | Four store defaults that fail under agent writers | pre-audit-rating-instruments-for-construct-semantics… | 0.7975 | distinct |
| quipu | Start strict: let agents bear the cost of strictness | review-verdicts-inherit-briefing-constraints | 0.8064 | distinct |
| quipu | Gate writes against the post-state, not the pre-state | gate-technique-re-verify-a-research-agent-s-fast-moving-claims… | 0.7965 | distinct |
| quipu | Verdict permanence: the refusal record must outlive the rollback… | gate-technique-re-verify-a-research-agent-s-fast-moving-claims… | 0.8034 | distinct |
| quipu | Governance as data: store the spec where it governs… | single-compliance-boundary-dictates-platform | 0.8064 | distinct |
| quipu | The container fallacy: evidence presence is not evidence sufficiency | evidence-and-warrants | 0.8167 | distinct |
| quipu | Use structured refusals as an agent correction protocol | structured-decision-taxonomy-for-ai-drafted-content-review-queues | 0.8185 | distinct |
| quipu | Evaluation claims must be scoped to the mechanism actually measured | evaluation-design-for-a-predictive-estimation-model | 0.8086 | distinct |
| quipu | Cross-checkers should expose semantic disagreement, not erase it | pre-audit-rating-instruments-for-construct-semantics… | 0.7989 | distinct |
| quipu | Historical replay must evaluate both data and rules as of the decision | bitemporality-must-reach-the-rules-not-just-the-data | 0.8461 | **true-dup** |
| quipu | Evidence sufficiency must be scored at the property level | evidence-and-warrants | 0.8306 | distinct |
| quipu | Synthetic benchmarks and wild-trace replay answer different validity questions | process-traces-are-evidence-only-when-tied-to-a-hypothesis | 0.7923 | distinct |
| quipu | A benchmark should be capable of falsifying and improving its subject | deterministic-lifecycle-benchmarks-can-serve-as-executable-oracles | 0.8405 | distinct |
| latent | Equal test scores do not imply equal constructs | variable-clarification-uses-meaningful-mismatches-to-separate-constructs | 0.8323 | distinct |
| latent | Blind expert interpretation of factor structures as a validity probe | exploratory-and-confirmatory-factor-analysis-answer-different-measurement-questions | 0.8448 | distinct |
| latent | SME factor-interpretation protocol: three lenses plus a discrimination check | exploratory-and-confirmatory-factor-analysis-answer-different-measurement-questions | 0.8161 | distinct |
| latent | In two assessments, pooled-LLM latent factors were largely opaque… | prompt-engineering-techniques-for-calibrated-llm-prediction… | 0.8141 | distinct |
| latent | Aggregate accuracy masks mechanism divergence | scoring-noise-mechanically-depresses-an-item-s-discrimination… | 0.8656 | distinct |
| latent | When content can't explain a factor, check item format and structure | choose-response-formats-for-the-evidence-they-can-elicit | 0.8500 | distinct |
| latent | Test-taking strategies can emerge as latent factors alongside content knowledge | teach-test-format-strategy-separately-from-subject-knowledge | 0.8295 | distinct |
| latent | Statistical model fit does not establish semantic meaning | model-adequacy-requires-triangulation | 0.8486 | distinct |
| latent | An extracted factor does not by itself establish a latent trait | factor-scores-are-estimates-not-observed-values-of-latent-factors | 0.8507 | distinct |
| latent | A study-specific EFA pipeline for binary assessment responses | binary-item-difficulty-can-create-spurious-factors… | 0.8432 | distinct |
| latent | Screen binary items for unstable pairwise correlations | binary-item-difficulty-can-create-spurious-factors… | 0.8692 | distinct |
| latent | Control prompt-induced variance in assessment studies | stimulus-control | 0.8436 | distinct |
| latent | Pooling model responses improves estimability but creates mixture-level factors | partial-pooling-stabilizes-estimates-when-each-unit-has-little-data | 0.8477 | distinct |
| latent | Measurement invariance as the precondition for cross-population ability comparison | measurement-comparisons-require-a-linked-latent-scale | 0.8912 | distinct |
| latent | Shared latent structure as a prerequisite for AI in meaning-dependent educational roles | use-llms-as-expert-predictors-not-simulated-students | 0.8502 | distinct |

## Caveats

- n = 28 with a **single** true-dup: the 0.8461 floor is one observation, not
  a distribution. The personal study's 51-dup floor (0.8413) is the stronger
  anchor; the two agree that 0.83 leaves margin.
- Labels are one orchestrator's D3 adjudications from two sessions
  (cross-backend double-reviewed candidates, full-body match reads). All 27
  overrides are spot-checkable: each has a KB entry with a `related:` backlink
  to its match where kinship is real.
- Re-run this analysis after the next few large extractions (append their
  labeled skips to the table above). If a real reworded duplicate is ever
  observed below 0.83, lower `dedup_low` back toward 0.79 or recalibrate with
  the new pair included.
- Process gap surfaced by this study: `mem extract` skips leave no durable
  trace (KB git history records saves only; candidate/match/similarity records
  live in ephemeral session scratch). Persisting per-run skip records would
  make future recalibrations and audits mechanical.
