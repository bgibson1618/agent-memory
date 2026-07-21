# Implementation - agent-memory

> **Generated snapshot** (D21 / F30) — rendered by `scripts/render-snapshot.mjs` from
> `FEATURES.md` + `.kodos/state.json`. **Do not hand-edit** — re-render instead.
> Rendered: 2026-07-21T21:50:24Z.

## Status

**Phase `build` — 5 of 12 features proved.**

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
| F6 | Fused search | test | todo | — |
| F7 | Concurrent-session write safety | test | todo | — |
| F8 | External-edit resilience | test | todo | — |
| F9 | Extract-knowledge CLI | test | todo | — |
| F10 | Extraction procedure | observed | todo | — |
| F11 | Ambient agent integration | observed | todo | — |
| F12 | Zero-egress guarantee | test | todo | — |
