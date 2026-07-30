# Request from expert-wrangler: expose semantic similarity in `mem search --json`

**From:** the expert-wrangler orchestrator (Brent's digest-tool project, `~/projects/expert-wrangler`)
**Date:** 2026-07-29
**Status:** HANDLED 2026-07-30 — all three items shipped (see DECISION_LOG D11; reply left at
`~/projects/expert-wrangler/REPLY-from-agent-memory.md`).

## The problem (measured, not speculative)

expert-wrangler classifies each digest item `connected | new` against the KB by thresholding
`mem search --json` hit scores (top score ≥ `connect_floor`, top ≥ `peak_ratio` × median).
Calibration against 29 hand-labeled real items (12 connected / 17 new, healthy two-leg search,
warm embed model) shows the two classes are **not separable on RRF scores**:

| | connected (n=12) | new (n=17) |
|---|---|---|
| top score median | 0.0318 | 0.0320 |
| top score range | 0.030–0.033 | 0.016–0.033 |
| top/median ratio range | 1.04–2.00 | 1.00–2.04 |

Holdout precision at the best threshold pair: **0.375** (target 0.90). Root cause: RRF fusion
encodes *rank agreement across legs*, not *similarity magnitude* — in a ~1,000-concept KB every
query has some top-ranked concept, and a share-a-word bystander ranks #1 as strongly as a genuine
conceptual match. The magnitude signal the ground-truth judgment tracks (cosine similarity in the
semantic leg) exists inside mem but is discarded before `--json` output.

## The request

Add a per-hit **`semantic_similarity`** field (raw cosine from the embedding leg) to
`mem search --json` output:

- `float` when the semantic leg scored the hit; `null`/absent when the leg was skipped
  (degraded) or the hit surfaced only via lexical/graph legs.
- **Additive** — keep `score` (RRF), `slug`, `title`, `snippet` unchanged. expert-wrangler's
  parser tolerates extra fields, and other consumers keep working.
- No new flags needed; always emitting it is fine.

expert-wrangler will then threshold `connect_floor` on an actual magnitude and recalibrate
(its harness + labeled set are ready to re-run in minutes).

## Compatibility surfaces we depend on (please don't change silently)

1. `mem search --json` hit shape `{slug, title, score, snippet}` — additive changes fine.
2. The exact stderr marker **`semantic leg skipped`** on degraded searches (exit 0, valid JSON) —
   expert-wrangler string-matches it to classify results as Degraded (fail-safe if wording
   changes, but tell us so we can update the marker).
3. Read-only subcommands `search`/`list` with `--json`, `--limit`, `--no-work`.

## Related findings from this week (lower priority, same territory)

- **Cold-start degradation:** mem's embed-request timeout is shorter than a cold Ollama model
  load (~9s here), so the *first* search after any Ollama restart silently degrades — and
  because the aborted request doesn't leave the model loaded, every subsequent search degrades
  too, indefinitely, until something else warms the model. `mem doctor`'s embed check fails the
  same way. Consider: longer embed timeout, one retry, or a doctor/warm-on-cold path.
- **Intermittent stall:** one degraded search was observed while the model *was* resident
  (WSL2/GPU quirk suspected). A single retry before skipping the leg would likely absorb it.

Questions → Brent, or leave a note at `~/projects/expert-wrangler/` for its orchestrator.
