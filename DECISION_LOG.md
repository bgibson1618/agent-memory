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

## D7 — Obsidian-readable canonical form: wikilink related[], kebab topics (2026-07-23)

- **Context:** Brent's Obsidian viewing mirror showed a near-edgeless graph: only 9/700
  bodies carried `[[wikilinks]]`, because `related:` was stored as plain slug strings
  (not indexed as links by Obsidian), and space-form topics ("learning science") are
  invalid Obsidian tags, splitting labels across space/hyphen variants.
- **Decision:** two-boundary canonicalization in `okf.py`, no store/extract changes
  needed. In memory, `related` is always plain slugs and `topics` always kebab-case:
  `Concept.__post_init__` normalizes every construction path (save, extract, parse), so
  externally-authored variants ("Learning Science", `[[slug]]`) canonicalize on read.
  On write, `serialize` emits `related` as quoted `"[[slug]]"` wikilinks (Obsidian
  property links) and kebab `topics`/`tags`. `mem get --json` therefore returns plain
  slugs while files carry the wikilink form — an intentional divergence. Spec-safe:
  OKF v0.1 defines no `related` field (it is a mem key, ours to shape) and spec `tags`
  are free strings; graph-side `slugify()` strips brackets, so pre-D7 files and other
  OKF writers parse unchanged. Topics that cannot slugify are silently dropped.
- **Migration:** the live KB (700 concepts) was bulk-rewritten the same day BEFORE this
  code change, via `scripts/kb-obsidianize.py` (KB commits b722ed9 links, 42bdd40 kebab
  in ~/.agent-memory); `mem reindex` re-drained 700 embeddings; doctor 9/9. The script
  stays as a one-shot re-normalizer for externally-introduced drift.
- **Proof:** 3 new tests in `tests/test_okf_interop.py` (wikilink-on-write/slug-on-read
  round-trip, kebab normalize+dedupe, pre-D7 plain-slug file reads clean) + updated F2
  capture round-trip; full suite → **98 passed**.
- **AI involvement:** parent `suggested` the native-write form after the bulk KB
  transform exposed forward drift (new saves would revert to plain form); Brent
  `accepted` and requested the build.

## D8 — Usage log + `mem stats`: measure whether the KB earns its keep (2026-07-23)

- **Context:** Brent asked how many times agents have queried the KB. Writes were fully
  auditable (907 save commits in git) but reads left no trace; transcript grepping
  undercounts badly (misses subprocess calls and non-Claude harnesses).
- **Decision:** every CLI invocation (except `init` and `stats` itself) appends one JSON
  line — ts/cmd/arg/rc/ms — to `.index/usage.jsonl` at the `main()` dispatch seam.
  `mem stats [--days N]` reports counts by command and by day, plus git-derived
  save counts. The log is the ONE non-derived file in `.index/`: reindex leaves it
  alone (tested), it stays out of git (`.index/` ignored), and logging is best-effort —
  a telemetry failure can never break a KB operation (bare-except by design).
  `stats` is unlogged so it cannot inflate its own numbers.
- **Proof:** `tests/test_usage_stats.py` (3 tests: append + field shape, stats counts,
  reindex preservation); full suite → **101 passed**.
- **AI involvement:** parent implemented on Brent's direct request ("I want some data on
  how useful this KB actually is").

## D9 — Provenance: every concept carries a `source` citation (2026-07-24)

- **Context:** Brent needs to trace any concept he cites in a proposal back to its
  source/expert. Provenance existed only as a three-hop join (KB git history → dated
  run block → run artifacts' chunk maps) plus best-effort inline attribution; ambient
  saves traced to nothing but a commit date, and no field surfaced in Obsidian or
  `mem get --json`.
- **Decision:** `Concept.source` — a free-text citation string in frontmatter, emitted
  on every serialize. `mem save --source` sets it; a save without it gets
  `ambient (<date>)`; **an `--update` without `--source` PRESERVES the existing
  citation** (deliberate divergence from the other clobber-on-update fields:
  provenance must never silently degrade — the roster-metadata clobber of 2026-07-24
  motivated the exception). `mem extract` accepts a per-candidate `source` key and
  stamps `extract (<date>)` when absent. Like `related` (D7), `source` is a mem key,
  not OKF v0.1 vocabulary — spec-conformant as a free field; parse tolerates its
  absence so externally-authored files still load. Existing concepts backfilled from
  run artifacts (`scripts/backfill-source.py`): per-chunk citations where survivor
  joins exist (mot/cmp), corpus-level citations for single-source runs, cohort
  segmentation via expert-roster update commits for the brain-lift era, honest
  `ambient (<date>)` for the rest.
- **Proof:** `tests/test_source_field.py` (4 tests: round-trip, ambient default,
  update-preserves + explicit-wins, extract passthrough + extract default); full
  suite → **105 passed**.
- **AI involvement:** parent implemented on Brent's direct request ("every concept I
  submit in a proposal needs to be traced back to an expert"); design (preserve-on-
  update, ambient/extract defaults) proposed by the agent, accepted by Brent.
