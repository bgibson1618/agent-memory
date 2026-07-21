# Decision Log — agent-memory

Why things are the way they are. Each entry records the context, the decision, and who/what
drove it. Discovery-phase artifacts (INTAKE/PRD/NFR_UX/ARCHITECTURE/FEATURES) carry the full
specs; this log carries the *reasoning* worth keeping when those specs change.

---

## D1 — Work-item recall policy: vendor-scoped, not blanket-filtered (2026-07-21)

- **Context:** The pre-build adversarial panel (`research/plan-review-2026-07-21/`,
  codex adversarial lens, finding #1, anchor *firm*) flagged that ambient agent recall places
  `[work]`-tagged memories into a model vendor's context with no per-use human decision — the
  NFR's "equivalent to typing it" reasoning only covered overt queries.
- **Decision (Brent):**
  1. `sensitivity: work` means **employer-specific material** only. General knowledge learned
     on the job is normal sensitivity — ambient-visible everywhere. Capture guidance: when in
     doubt, tag `work` or don't save.
  2. **Anthropic and OpenAI are approved vendors; Google is unconfirmed.** Work-tagged recall
     (ambient included) is permitted in Claude and Codex contexts. **Antigravity/Gemini-backed
     agents are excluded from memory work entirely** — enforced in the `AGENTS.md` instruction
     block and in orchestrator delegation practice (no KB-touching tasks to the antigravity
     backend).
  3. CLI defaults unchanged: include + `[work]` marker; `--no-work` for cautious contexts.
- **Why defensible:** preserves the KB's core value — ambient recall of job learning, the
  project's reason to exist — while making the confidentiality boundary structural exactly
  where vendor approval is unknown. Costs nothing in code (policy lives in instruction-block
  text and delegation practice); relaxable if Google is later approved.
- **AI involvement:** panel surfaced the gap (`suggested`); orchestrator proposed the
  semantics split (work = employer-specific vs work-derived); Brent set the vendor line
  (`changed` — vendor-scoping replaced the orchestrator's blanket ambient `--no-work`
  recommendation).
