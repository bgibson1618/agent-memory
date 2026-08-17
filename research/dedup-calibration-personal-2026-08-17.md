# Dedup calibration — personal-instance medical corpus (2026-08-17)

Second calibration study, motivating the two-band dedup scheme (D17). The first
study (`research/dedup-calibration.md`, F9) chose 0.79 on 26 pairs from the
learning-science-adjacent corpus with clean separation (fp 0, fn 0, band
0.77–0.81). This study measures the cancer-research corpus extracted into the
personal instance (`~/.agent-memory-personal`) across 5 batches / 62 documents.

## Dataset

Every `mem extract` skip across the five Stage B batches, joined to ground
truth by **KB existence**: a D3-overridden candidate has a KB entry (label:
distinct), a confirmed true duplicate does not (label: true-dup). Labels are
therefore the batches' D3 full-body adjudications, not similarity judgments.

- Source records: `~/projects/knowledge-sources-personal/runs/cancer-*/*/`
  (submit-result.json similarity scores) + `~/.agent-memory-personal/concepts/`.
- Analysis scripts + raw output:
  `~/projects/knowledge-sources-personal/work/calibration/` (analyze3.py,
  results-v3-kb-truth-2026-08-17.txt).
- **n = 381 labeled pairs: 330 distinct, 51 true-dup.**

## Findings

| class | n | min | p5 | median | p95 | max |
|---|---|---|---|---|---|---|
| distinct (overridden) | 330 | 0.7909 | 0.7961 | 0.8501 | 0.9116 | 0.9635 |
| true-dup (skipped) | 51 | 0.8413 | 0.8442 | 0.8924 | 0.9393 | 0.9599 |

1. **No single threshold separates the classes** — they overlap from 0.84 to
   0.96. The domain's dense shared vocabulary (drug/trial/disease names)
   compresses embedding space; flag rates ran 81–100% per batch with 87–95%
   of flags false-positive, so at 0.79 the threshold did almost no
   discriminative work and every candidate cost a full-body D3 read.
2. **The bottom band is clean**: zero true-duplicates below 0.8413. Auto-add
   below 0.83 removes 28% of D3 reads at zero observed error (margin 0.011
   below the lowest true-dup); 0.84 removes 34% at zero observed error, no
   margin.
3. **The top band is not worth enabling**: auto-skip at 0.94 would falsely
   drop 2 distinct entries to save 1 read. Confident-skip stays a mechanism,
   disabled by default.

## Decision input (→ DECISION_LOG D17)

Two-band mechanism: `dedup_low` (auto-add below; **default 0.79** — byte-for-
byte today's behavior, so the work instance is unaffected) and `dedup_high`
(confident-skip at/above; **default disabled**). Per-instance config sets the
personal instance to `dedup_low = 0.83`, `dedup_high` disabled.

## Caveats

- 51 true-dups is a modest sample; the 0.8413 floor could move with new
  corpora. The 0.01 margin and per-instance configurability are the hedges.
  Re-run analyze3.py after future large extractions to re-check the floor.
- Labels inherit the batches' D3 judgments (delegate full-body reads, spot-
  checked by the orchestrator). Highest-similarity "distinct" overrides
  (0.92–0.96) are umbrella/member-style pairs — the known F9 advisory class.
