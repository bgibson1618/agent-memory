# Implementation - agent-memory

> **Generated snapshot** (D21 / F30) — rendered by `scripts/render-snapshot.mjs` from
> `FEATURES.md` + `.kodos/state.json`. **Do not hand-edit** — re-render instead.
> Rendered: 2026-07-21T21:10:34Z.

## Status

**Phase `build` — 1 of 12 features proved.**

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
| F2 | Durable concept capture | test | todo | — |
| F3 | Keyword search | test | todo | — |
| F4 | Semantic recall | test | todo | — |
| F5 | Concept graph | test | todo | — |
| F6 | Fused search | test | todo | — |
| F7 | Concurrent-session write safety | test | todo | — |
| F8 | External-edit resilience | test | todo | — |
| F9 | Extract-knowledge CLI | test | todo | — |
| F10 | Extraction procedure | observed | todo | — |
| F11 | Ambient agent integration | observed | todo | — |
| F12 | Zero-egress guarantee | test | todo | — |
