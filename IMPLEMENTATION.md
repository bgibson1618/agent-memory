# Implementation - agent-memory

> **Generated snapshot** (D21 / F30) — rendered by `scripts/render-snapshot.mjs` from
> `FEATURES.md` + `.kodos/state.json`. **Do not hand-edit** — re-render instead.
> Rendered: 2026-07-21T23:37:01Z.

## Status

**Phase `build` — 12 of 12 features proved.**

Current status and the next action are **owned by `.kodos/state.json`** — read them live
(this snapshot never asserts them, D2):

```bash
node scripts/schedule.mjs FEATURES.md .kodos/state.json   # or: /kodos:go
```

History lives in `BUILD_LOG.md` (append-only journal) and `DECISION_LOG.md` (durable
decisions); verify live with the project's verification command rather than trusting any
rendered count.

## Features (rendered from state)

| id | title | proof | status | evidence (abridged) |
|---|---|---|---|---|
| F1 | Initialized, verified KB home | test | proved | uv run pytest -> 13 passed (11 F1 + 2 preflight); parent re-run after applying work/agents/kodos-F1-20260721T… |
| F2 | Durable concept capture | test | proved | uv run pytest -> 27 passed after applying work/agents/kodos-F2-20260721T2115Z/implementer/F2.patch (14 F2 tes… |
| F3 | Keyword search | test | proved | uv run pytest -> 36 passed after applying kodos-F3 patch (9 F3 tests, Ollama absent); real-daemon smoke: lite… |
| F4 | Semantic recall | test | proved | uv run pytest -> 45 passed after hand-merging kodos-F4 patch (store.py/cli.py hunks conflicted with F3 — pare… |
| F5 | Concept graph | test | proved | uv run pytest -> 54 passed after applying kodos-F5 patch (9 F5 tests; import hunk hand-merged); real-daemon s… |
| F6 | Fused search | test | proved | uv run pytest -> 62 passed after applying kodos-F6 patch (6 F6 tests: single-leg fixtures incl. seed-neighbor… |
| F7 | Concurrent-session write safety | test | proved | uv run pytest -> 65 passed after applying kodos-F7 patch (3 contention tests: 10-way distinct-slug race, 8-wa… |
| F8 | External-edit resilience | test | proved | uv run pytest -> 70 passed after applying kodos-F8 patch (5 F8 tests incl. meaning-flip semantic refresh + fu… |
| F9 | Extract-knowledge CLI | test | proved | uv run pytest -> 78 passed; REAL calibration executed by parent against live daemon (research/dedup-calibrati… |
| F10 | Extraction procedure | observed | proved | .kodos/evidence/F10/ + run dirs f10-observe-roster / f10-observe-inline: (A) roster mode - real session follo… |
| F11 | Ambient agent integration | observed | proved | .kodos/evidence/F11/ - real deployment (uv tool install; mem 0.1.0 on PATH), real mem init (blocks in ~/.clau… |
| F12 | Zero-egress guarantee | test | proved | MEM_REQUIRE_NETNS=1 uv run pytest -> 89 passed (5 F12 tests: audit-hook guard + netns driver running all 8 co… |
