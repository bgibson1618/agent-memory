# D18 dedup-DETECTION calibration - Stage 1a + 1b

generated-by: `uv run python research/dedup_detection_calibration.py`
daemon: none required for Stage 1a (lexical coverage is a pure text metric); Stage 1b reads only the archive's already-recorded scores
model+digest: n/a (no embeddings computed by this script)
metric: IDF-mass-weighted lexical claim containment (`dedup.coverage_of_candidate`/`coverage_of_card`), claim-match tau_lex = 0.6 (config.DEFAULT_DEDUP_CLAIM_LEX)

Stage 1a IDF source: IDF corpus: synthetic, in-script (no --kb given)

## Stage 1a - coverage mechanics + the FP side (synthetic, fence-free)

| construction | stats |
| --- | --- |
| verbatim subset (candidate claims ⊂ its own card) | n=240 min 1.0000 median 1.0000 max 1.0000 |
| hard negative (distinct synthetic card, directional both ways) | n=30 min 0.0720 median 0.0864 max 0.0926 |
| composite (½A+½B) - best single card | n=15 min 0.5676 median 0.6274 max 0.6569 |
| composite - union of {A, B} | n=15 min 1.0000 median 1.0000 max 1.0000 |

D3's 12 near-dup pairs (paraphrase, negative control - lexical coverage must score near-zero; a harness that 'fixes' this has a bug): n=12 min 0.0000 median 0.0000 max 0.0000
D3's 14 distinct pairs (same-domain hard negatives + easy negatives): n=14 min 0.0000 median 0.0000 max 0.0000

## Stage 1b - the AP-BPF archive replay (fence-free; read-only)

Archive: `/home/brent-gibson/work/ap-business-personal-finance/work/kbx-2026-08-21/r1-phase2/dup-rulings-r1p2.json` (md5 prefix asserted: `e66073d1`)
Positives (dup-class, cited live_slug): 63; negatives (NEW-SAVE): 22

| K | recall@K |
| --- | --- |
| 1 | 0.810 |
| 2 | 0.889 |
| 3 | 0.937 |
| 5 | 0.968 |
| 10 | 0.968 |

MRR: 0.872
Absent from the archived top-10: 2/63 (os-mis-030, os-mis-046)

True-match `semantic_similarity`: n=61 min 0.6368 p10 0.7110 median 0.7750 p90 0.8417 max 0.8811

| class | max(semantic_similarity) over each record's hits |
| --- | --- |
| dup-class (positive) | n=63 min 0.6509 p10 0.7021 median 0.7746 p90 0.8417 max 0.8811 |
| NEW-SAVE (negative) | n=22 min 0.6141 p10 0.6470 median 0.7155 p90 0.7591 max 0.7762 |

| `dedup_low` | recall of confirmed dups (whole-document cosine alone) |
| --- | --- |
| 0.79 | 0.410 |
| 0.83 | 0.197 |
| 0.85 | 0.082 |
| 0.88 | 0.016 |

## Recommended defaults (S4.4), unchanged shipped config

- `MEM_DEDUP_COVERAGE_LOW` recommended: 0.35
- `MEM_DEDUP_COVERAGE_HIGH` recommended: 0.85
- `MEM_DEDUP_UNION_LOW` recommended: 0.55

These three values are the design's recommendations (S4.4/§0's doctrine) and they SHIP in exactly one place: the standalone `mem dedup` command's coverage overlay (`dedupcmd._DEDUP_CMD_COVERAGE_LOW_DEFAULT` / `_HIGH_DEFAULT` / `_UNION_LOW_DEFAULT`, applied only when the env seams are unset - W2 Ruling, D18 design Q3). Every `DEFAULT_DEDUP_*` global in `config.py` stays disabled/unset, so `mem extract` and every other surface remain opt-in (D18's ratified per-instance posture). A test (`tests/test_d18_w3_claim_leg_calibration.py`) pins the overlay's three numbers to this artifact, mirroring `research/dedup_calibration.py`'s config-pinning pattern.
