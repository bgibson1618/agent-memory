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

## D2 — OKF posture: clean-room from the field contract, no capstone code ported (2026-07-21)

- **Context:** ARCHITECTURE's open question required checking the capstone repo's license
  before porting `okf.py`-style code, "otherwise clean-room the schema from the format spec —
  resolve at build start." F2 is the first feature that could land capstone-derived code. The
  F2 build session is confined to this workspace and cannot read the capstone repo
  (`~/projects/capstone-workspace`), so the license could not be verified from the build seat.
- **Decision (implementer, F2 start):** take the pre-authorized conservative branch —
  **clean-room**. `src/agent_memory/okf.py` is implemented solely from the field contract
  already recorded in this repo (ARCHITECTURE `okf` component row + FEATURES F2 criteria:
  frontmatter id/slug, title, description, type, `topics[]`, `sensitivity`, created/updated,
  `related[]`; body with plain `[[wikilinks]]`). No capstone source was consulted, copied, or
  ported. The license check is thereby moot for v1; porting capstone code later remains
  possible if Brent verifies the license first.
- **Why defensible:** clean-room is safe under any license outcome; the contract is small
  (ten fields + a markdown body), so re-deriving it costs less than resolving the legal
  question, and the schema stays Obsidian-compatible by construction.
- **AI involvement:** implementer selected the fallback branch ARCHITECTURE pre-authorized
  (`accepted` shape, no new judgment call); flagged for Brent's confirmation at wave
  reconcile.

## D3 — Dedup threshold: 0.79, measured not guessed (2026-07-22)

- **Context:** ARCHITECTURE required the extract-knowledge dedup threshold be calibrated
  empirically (capstone D024: lexical similarity provably cannot separate near-dups; a real
  embedder changes the calculus but not the need to measure). The F9 builder shipped a runnable
  calibration harness and refused to fabricate the artifact from its execution-gated seat.
- **Decision:** `DEFAULT_DEDUP_THRESHOLD = 0.79`, from a live run of
  `research/dedup_calibration.py` against nomic-embed-text:v1.5 (26 labeled pairs): clean
  separation band 0.77–0.81, fp 0 / fn 0; near-dup sims 0.812–0.917, distinct 0.528–0.768.
  Artifact: `research/dedup-calibration.md`; a test pins config to the artifact's chosen value.
  Env seam `MEM_DEDUP_THRESHOLD` overrides.
- **Known limitation (observed live, wave-5 walkthrough):** umbrella-vs-member concept pairs
  can exceed the line (desirable-difficulties vs interleaving-effect at 0.84). The disposition
  report names the match + similarity, and direct `mem save` bypasses dedup — the designed
  recourse; extraction-procedure reviewers treat skipped-duplicate reports as reviewable.
- **AI involvement:** builder `suggested` the harness + provisional 0.85; parent measured and
  `changed` to 0.79; the limitation observation is the parent's walkthrough finding.

## D4 — Extract-choreography timing envelope: minutes, not seconds (2026-07-22)

- **Context:** NFR_UX and the shipped `extract-knowledge.md` procedure both targeted "< 60 s
  per document" for the full extract-knowledge choreography. The F10 roster-mode observation
  measured the cross-backend extractor fanout alone at ~83 s — before merge, review, and the
  `mem extract` call. The 60 s figure predated any live measurement of real subagent fan-outs.
- **Decision:** the documented envelope is **single-digit minutes per document with per-stage
  progress**; the deterministic CLI half (`mem extract --candidates`) keeps its
  seconds-scale expectation. NFR_UX.md and `agent_integration/extract-knowledge.md` revised
  to match. The quality mechanism (fresh-eyed fan-out + review) is the point of the
  procedure; compressing it to fit an aspirational number would trade away exactly what F10
  proved works.
- **AI involvement:** drift surfaced by the wave-6 cross-vendor fresh-eyes reviewer (codex);
  parent `changed` the target to the measured envelope. Flagged for Brent at closeout — if he
  wants a fast path, a single-extractor `--quick` mode is a post-v1 seam, not a v1 promise.

## D2 — Amended: confirmed by Brent against the official spec (2026-07-22)

- **New basis (Brent):** OKF is a public standard (Google,
  `GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md`, v0.1 Draft) — not a capstone-private
  format. His confirmation condition: "as long as the format we're using matches the official
  spec, the capstone code is irrelevant." The clean-room-vs-port question D2 originally
  flagged is thereby dissolved, not just resolved.
- **Conformance verified (spec §9, snapshot pinned at `research/okf-spec-v0.1.md`):**
  (1) every concept file carries parseable YAML frontmatter — serializer-guaranteed, and a
  live sweep of all 32 real KB concepts passed; (2) every frontmatter has non-empty `type` —
  required by `okf.py` validate, default `concept`; (3) reserved filenames (`index.md`,
  `log.md`) — none exist in the KB. **Verdict: conformant with OKF v0.1.** Our extra fields
  (`id`, `slug`, `topics`, `sensitivity`, `created`, `updated`, `related`) are
  spec-sanctioned producer extensions (§4.1); `[[wikilinks]]` don't affect conformance (§9
  ignores link form) and Obsidian-compatibility matches the spec's own kinship note (§10).
- **Known gaps, recorded not remediated (post-v1 candidates):**
  1. *Latent reserved-name edge:* a concept titled "Index" or "Log" would slugify to a
     reserved filename carrying frontmatter, breaking §9 rule 3 — no guard exists in
     `slugify`/store. Trivial fix (refuse or auto-suffix those two slugs).
  2. *Interop vocabulary:* we emit `topics`/`created`/`updated` (extensions) instead of the
     spec-recommended `tags`/`timestamp`, so conforming OKF consumers see no
     tags/last-modified. Additive fix if wanted: mirror `tags:` and `timestamp:` at
     serialize time.
- **AI involvement:** Brent supplied the spec URL and the confirmation condition; parent
  fetched, pinned, and machine-verified conformance (`suggested`→`accepted`).

## D5 — OKF interop hardening: reserved-slug guard + spec-vocabulary mirrors (2026-07-22)

- **Context:** the D2 amendment recorded two gaps against the official OKF v0.1 spec as
  post-v1 candidates; Brent asked for both to be addressed same-day.
- **Decision:**
  1. `index` and `log` are refused as concept slugs in `Concept.validate()` — one guard
     covering `mem save` (derived and explicit `--slug`) and extract candidates (reported
     as `invalid` with the reason), closing the §9-rule-3 edge. Refuse, not auto-suffix:
     silently mutating an explicitly requested slug is worse than a one-line error.
  2. The serializer mirrors the spec-recommended vocabulary (`tags` <- `topics`,
     `timestamp` <- `updated`) so conforming OKF consumers see categorization and
     last-modified; the parser accepts `tags`/`timestamp` (and derives `created` from
     `timestamp`) as fallback so externally-authored spec-shaped files load. Canonical
     keys stay `topics`/`created`/`updated`; a stale mirror in a hand-edited file
     self-heals on the next save/update (parse prefers canonical, serialize re-syncs).
- **Migration:** all 33 existing live-KB concepts re-serialized in place (229 insertions,
  0 deletions — mirrors only), single KB commit; `mem reindex` re-drained all embeddings;
  doctor 9/9.
- **Proof:** `tests/test_okf_interop.py` (6 tests: reserved title/slug refusal, extract
  invalid reporting, mirror emission, update sync, external spec-vocabulary parse);
  full suite `MEM_REQUIRE_NETNS=1 uv run pytest` → **95 passed**.
- **AI involvement:** parent implemented on Brent's direct request; refuse-vs-suffix call
  is the parent's (`suggested`), open to reversal if it ever bites.

## D6 — Slash-command surface: /mem:extract only; search/save stay ambient (2026-07-22)

- **Context:** Brent asked how to invoke the system in other sessions and whether a plugin
  with `/mem:extract`-style commands was planned. V1 shipped no plugin (Claude-first via
  managed blocks; MCP deferred).
- **Decision:** a minimal Claude Code plugin (`mem`, bundled in this repo:
  `.claude-plugin/` + `skills/extract/`) ships exactly one command. **Extraction earns a
  slash command** because it is inherently user-triggered and benefits from a deterministic
  entry point; the skill is a thin driver that gates on `mem doctor`, then follows
  `mem extract --procedure` verbatim (the CLI stays the single source of truth for the
  choreography — no duplicated instructions to drift, per learning L1). **Search and save
  deliberately get no commands**: wrapping them would undo the PRD's invisibility behavior,
  which is installed by `mem init` and proved by F11. Registered via `mem-local` directory
  marketplace + `claude plugin install mem@mem-local`.
- **Proof:** fresh headless session: `/mem:extract` with no argument follows the skill —
  asks for the document, names the choreography stages, runs nothing. The full-run path is
  the same procedure already observed live three times (F10 + closeout re-observe).
- **AI involvement:** parent `suggested` the extract-only scope in conversation; Brent
  `accepted` and requested the build.
