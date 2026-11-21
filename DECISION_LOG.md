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

## D10 — Credence axis: typed entries, non-`concept` types marked + filterable at recall (2026-07-27)

- **Context:** Brent will ingest brain lifts from ~65 concurrent Superbuilders
  projects. These are colleagues' working hypotheses, NOT scientific truth — they must
  never be laundered into the same epistemic status as the vetted learning-science
  `concept`s. The two existing axes don't cover this: `sensitivity` is confidentiality
  (who may see it), `source` is provenance (where it came from), neither is credence
  (how much to trust it). Cosine similarity is credence-blind — a fused search returns
  hypotheses and vetted concepts interleaved by relevance alone.
- **Decision:** credence rides the existing `type` field (free-text; was effectively
  `concept`/`reference` only). New company-scoped vocabulary: **`sb-project`** (one
  reference card per project — name, thesis, team, links) and **`sb-position`** (a
  hypothesis/"spiky point of view" extracted from a project, cited as that project's
  stance, never as fact). Retrieval stops treating type as invisible: `mem search`
  marks any non-`concept` type `[<type>]` in text, carries `type` in every `--json`
  hit (a contract extension — F3/F6 hit-shape tests updated), and `--type a,b`
  restricts to an allow-list (`--type concept` grounds a proposal only in vetted
  knowledge). Defense in depth mirrors the anti-launder discipline already used for the
  rewards controversy and MAW: the marker protects recall, an attributed-voice
  `description` protects the skim, an attributed body protects the quote. Company-scoped
  names are acceptable in a local-only personal KB (a future rename is sed + reindex).
- **Proof:** `tests/test_type_marker.py` (2 tests: text marker + json type present and
  correct; `--type` allow-list filters); F3/F6 contract tests updated for the new key;
  full suite → **107 passed**.
- **AI involvement:** Brent set the requirement and chose the `sb-` vocabulary; the
  agent proposed the credence-axis framing, the type-rides-`type` mechanism, the
  recall-time marker/filter (from the `[work]`/`--no-work` template), and the
  project-card-vs-position split; Brent accepted and refined (`sb-project` =
  reference data, `sb-position` = underpinning hypotheses).

## D11 — Cosine magnitude in search hits + cold-model embed retry (2026-07-30)

- **Context:** expert-wrangler (Brent's digest-tool project) measured that
  connected-vs-new classification cannot be thresholded on RRF scores: RRF encodes
  rank agreement across legs, not similarity magnitude, so in a ~1,600-concept KB the
  top hit's RRF score is nearly constant regardless of whether anything is actually
  close (measured medians 0.0318 vs 0.0320 across hand-labeled classes; holdout
  precision 0.375 vs a 0.90 target). Separately, it reported the cold-start class:
  the query-embed timeout (2.5s) is shorter than a cold Ollama model load (~9-11s
  measured), and — verified live on 2026-07-30 — an aborted request does NOT leave
  the model loading, so after a daemon restart every search silently degrades until
  something else warms the model; `mem doctor`'s 10s probe flapped FAIL the same way.
- **Decision:** (1) Hits the vector leg scored carry `semantic_similarity` (raw
  cosine, rounded like `score`) in `--json` — additive, conditional-key like
  `sensitivity`; absent on lexical/graph-only hits, zero-evidence queries, and
  degraded searches, where absence is itself signal. Only the leg's top
  `max(limit,10)` positive-cosine hits carry it (documented caveat). (2) Cold-model
  retry, health-check-gated: `ollama.embed` raises `OllamaTimeout` (subclass) on
  timeout; the query path then proves the daemon alive via a 0.5s version check and
  retries ONCE on `MEM_EMBED_COLD_TIMEOUT` (default 60s), holding the connection open
  so the load completes and sticks. A dead/hung daemon fails the version check and
  still costs ~one timeout — the original "hung daemon costs ~one timeout" invariant
  survives (raising QUERY_TIMEOUT instead would have spent the whole budget on every
  hung-daemon search). `mem doctor`'s embed probe rides the cold budget outright (its
  preceding version check already proved liveness; a diagnostic must not flap on a
  healthy-but-cold daemon). Save path and opportunistic drain deliberately untouched
  (0.5s + durable queue is correct there). The degraded-path stderr marker
  `semantic leg skipped` is preserved verbatim (expert-wrangler string-matches it);
  the retry notice is a distinct line.
- **Proof:** `tests/test_cold_retry.py` (cold search retries and recovers semantics;
  hung daemon degrades fast with the verbatim marker; doctor survives cold model;
  negative control pins the probe to the cold budget); `test_f6_fusion.py`
  semantic_similarity per-leg presence/absence; full suite → **112 passed**. Live:
  cold search 15.0s total with real results (pre-fix: degraded at 3.3s and model
  still unloaded 20s later); cold `mem doctor` 9/9 in 10.9s on a ~11s load that the
  old 10s probe would have flapped on.
- **AI involvement:** requirements arrived as a written request from the
  expert-wrangler orchestrator (repo-root note, 2026-07-29) relayed by Brent; the
  agent proposed the conditional-key shape, the OllamaTimeout/health-check-gated
  retry, and the doctor budget; Brent approved the batch.

## D12 — Link integrity: batch-mate remap at extract, visible lint, calibrated backfill (2026-08-05)

- **Context:** Brent clicked two links in Obsidian that silently created blank notes;
  the trail led to a systemic gap: 1,238 dangling wikilink/related references across
  602 concepts (37% of the KB), pointing at 851 nonexistent targets. Four sources:
  dedup-skipped candidates whose batch-mates kept linking their never-created slug
  (the dedup pass knows the match and threw it away), suffixed saves breaking sibling
  links the same way, aspirational links to never-candidates, and wikified citation
  numbers ([[91]]). Cost: lost graph-leg recall (edges to real concepts earning no
  RRF credit) and the Obsidian blank-note/dirty-mirror trap.
- **Decision:** (1) Extract remaps links to batch-mates wherever they land — skipped
  duplicate → its match, suffixed save → the actual slug — rewriting bodies AND
  `related`, then re-embedding rewritten concepts so content hashes stay true; an
  extract can no longer mint a link to a slug it declined to create. (2) `mem links`
  reports {dangling target ← referrers} (text/--json, always exit 0) and doctor
  carries an informational, never-failing dangling-links count — a dangling link can
  be a legitimate worth-writing-later marker, so any nonzero count must not gate.
  (3) One-shot backfill (`scripts/repair-dangling-links.py`, report in
  learning-science pipeline/runs/link-repair-2026-08-05/): de-kebabed targets embed
  as queries against a pool restricted to `concept`/`reference` types (the D10
  credence boundary applies to edges — vetted material never gets repointed at an
  sb-position), floor/margin picked from the measured distribution (0.78/0.02 —
  every sampled match above it correct, including all 27 smallest-gap cases; the
  0.72–0.78 band mixed generic one-word targets with narrower claims and stays
  manual). Body rewrites preserve display text via alias ([[match|original]]);
  `updated:` stamps preserved (backfill-source precedent).
- **Proof:** `tests/test_link_health.py` (4 tests: dedup remap incl. alias tail +
  vector hash follows body; suffix remap ends with zero dangling; `mem links`
  text+json contract; doctor check informational both ways); full suite →
  **116 passed**. Live: 169 targets auto-repaired + 2 delinked = 266 references in
  223 concepts (KB commit 7630554), 851→680 targets / 1,238→972 refs; every repaired
  reference proved to be a `related:` entry (Obsidian Properties links — matching how
  the blank notes got created); duplicate shorthand+real pairs folded by the rewrite
  dedupe. 680 review-tail targets listed in repair-report.json for future curation.
- **AI involvement:** Brent spotted the phenomenon (blank Obsidian notes) and asked
  the root-cause question; the agent diagnosed the four sources, proposed the
  three-element shape (Brent approved verbatim), and calibrated the backfill floor
  from sampled bands.

## D13 — `position`: general credence type for attributed, non-empirical stances (2026-08-05)

- **Context:** the Fish (2011) writing-craft extraction surfaces material with two
  distinct credences: structural/conventional claims about how sentences work
  (reference-book epistemics → `concept`) and normative/aesthetic judgments resting
  on the author's authority — taste rankings, "should"s, method-efficacy claims with
  no cited evidence. Typing those `concept` would launder stance into "what's known"
  (`--type concept` grounding); `sb-position` is wrong (that's a colleague's untested
  working bet, company-scoped).
- **Decision:** new general type **`position`** — a named expert's or school's
  considered stance, quotable only in attributed voice ("Fish holds…"), never as
  fact. Generalizes the sb-position family: `sb-position` = a Superbuilders
  project's stance; bare `position` = anyone else's. Attribution rides `source`
  (D9). Zero mem code: D10's machinery is type-agnostic (`[position]` search marker,
  `--type` allow-list exclusion, attributed description/body defense-in-depth all
  already fire). Extraction boundary rule: how-it-works/convention claims →
  `concept`; valuations, shoulds, and authority-resting method claims → `position`;
  method claims independently corroborated by existing vetted concepts may be
  promoted to `concept` by review lanes; default `position` when in doubt
  (promotion later is a one-field edit; demotion after a proposal cites it is too
  late).
- **Proof:** no code change to prove; the D10 tests already pin marker + filter
  behavior for arbitrary non-`concept` types. Managed agent blocks updated to teach
  the extended credence rule; first corpus applying the split: fish-2026-08-05.
- **AI involvement:** Brent spotted the standards-vs-style split and asked whether a
  new tag was needed; the agent drew the works/authority boundary, proposed the
  `position` name for family symmetry, and Brent approved.

## D14 — `reference` generalized: descriptor of an artifact, standard, or index (2026-08-06)

- **Context:** the College Board AP Business with Personal Finance CED (Effective
  Fall 2026) is the first corpus that is neither vetted knowledge nor anyone's
  stance — it *describes a designed thing*: exam structure, unit weightings, task
  verbs, scoring rules, and required content. Typing such facts `concept` would rot
  the `--type concept` grounding lane with expirable artifact facts (CEDs get
  revised) — the same laundering D10 exists to prevent, on a different axis:
  not authority-stance but artifact-description. The `reference` type already
  existed with one instance (expert-master-index, a generated lookup).
- **Decision:** generalize **`reference`** — a descriptor of an artifact, standard,
  or index (an exam spec, a CED, a generated roster), quotable only as what the
  artifact specifies WITH its version/date ("the CED (Fall 2026) requires…"), never
  as vetted knowledge; the described thing can change, so the D9 `source` carries
  issuer + version. Extraction boundary: framework content statements extract as
  "the exam requires X" reference cards (the KB records the requirement without
  asserting unvetted domain content); clearly general established knowledge may
  still be typed `concept`; default `reference` for anything from a descriptor
  document when in doubt. Zero mem code: D10's machinery is type-agnostic
  (`[reference]` marker, `--type` filtering already fire). Credence family is now:
  concept ("is this true?"), position/sb-position ("who holds this?"), reference/
  sb-project ("what does the thing specify, as of when?").
- **Proof:** no code change to prove; D10 tests pin marker + filter behavior for
  arbitrary non-`concept` types. Managed agent blocks updated to teach the extended
  rule; first corpus applying it: the 2026-08-06 engagement corpus (learning-science pipeline; identifier redacted 2026-11-17).
- **AI involvement:** Brent spotted that a CED is "just describing a thing" and
  asked whether a new tag was needed; the agent inventoried the type census, argued
  generalize-don't-mint from the D13 precedent (and the versioned-artifact rot risk
  for `concept` grounding), and Brent approved.

## D15 — `MEM_KB_ROOT`: multi-instance KB routing (2026-08-14)

- **Context:** Brent is standing up a second, personal KB (rare-cancer research
  for his mom's conditions, SCOTUS rulings) that must never surface in
  work-session ambient recall — a privacy/recall-scope boundary, not a topic
  tag. The store was single-rooted: `config.kb_root()` hardcoded
  `~/.agent-memory`; tests isolated via scratch `$HOME`, so no seam existed for
  a second live instance.
- **Decision:** add **`MEM_KB_ROOT`** — an env seam (consistent with the
  `MEM_*` family) that points the entire CLI at an alternate KB instance;
  `~` expands; unset keeps the default. Instances are fully isolated: own git
  repo, own indexes, own usage log; every invariant (local-only/no-remote, OKF,
  sensitivity semantics, D9 provenance, D10/D13/D14 credence) applies
  per-instance. Partition doctrine: work↔personal splits at the *instance*
  (recall context + confidentiality); subjects within an instance split by
  topics. Projects route via env (personal projects set `MEM_KB_ROOT`);
  the managed blocks teach the rule.
- **Proof:** `tests/test_d15_kb_root.py` — two live instances each resolve their
  own content and NOT the other's with both KB homes present (isolation both
  ways, both directions exercised), blank/whitespace override falls back to the
  default root, `~` expansion honored; full suite green
  (`MEM_REQUIRE_NETNS=1 uv run pytest`). Codex gate (verifier-9bnu) FAILed the
  first cut — one-way-only isolation proof, five single-root doc statements
  (the L1 doc↔surface skew class, again), default-only backup tooling — all
  three remediated: docs now speak per-instance (FEATURES.md untouched as
  read-only history), `agent-memory-backup` takes `MEM_BACKUP_KB_ROOT`/`_DEST`/
  `_MIRROR` for one-instance-per-job scheduling.
- **AI involvement:** Brent asked how to partition personal knowledge (cancer
  research + SCOTUS in one place?); the agent argued instance-split-by-recall-
  context over per-subject KBs, identified the hardcoded root, and Brent
  approved the seam.

## D16 — `sensitive` sensitivity tier for PII/PHI (2026-08-14)

- **Context:** the personal KB (D15) will hold rare-cancer research and SCOTUS
  material. Brent will NOT pull his mom's actual medical records into the KB,
  but wants a marking for any PII/PHI that does need keeping — the existing
  enum was `{normal, work}`, whose `work` semantics (employer-specific) don't
  fit personally-identifying or health information.
- **Decision:** add **`sensitive`** as a third `sensitivity` value: PII/PHI —
  personally identifying or health information about real people. Semantics are
  symmetric with `work`: included in recall and marked `[sensitive]` in text
  (carried in `--json`), `--no-sensitive` excludes the tier; recall marking
  generalized to any non-`normal` sensitivity. Capture guidance (taught in the
  managed blocks and extract procedure): prefer NOT saving identifying details
  at all — distill the knowledge, drop the identifiers; tag `sensitive` when
  they must be kept, and never quote `[sensitive]` content onward. Applies
  per-instance like everything else (D15).
- **Proof:** `tests/test_d16_sensitive.py` — save/get roundtrip, `[sensitive]`
  text marker + `--json` field, `--no-sensitive` excludes exactly its tier
  (`--no-work` leaves sensitive items in, and vice versa), invalid values still
  refused; full suite green (`MEM_REQUIRE_NETNS=1 uv run pytest`).
- **AI involvement:** the agent flagged the enum gap while standing up the
  personal KB; Brent ruled out storing family medical records and asked for the
  tag; the agent implemented with symmetric-to-`work` semantics and the
  drop-identifiers-first capture default.

## D17 — Two-band dedup thresholds: `dedup_low` / `dedup_high` (2026-08-17)

- **Context:** D3's single threshold (0.79) was measured on a 26-pair,
  clean-separation corpus. The personal instance's cancer-research corpus
  (`research/dedup-calibration-personal-2026-08-17.md`, n=381: 330 distinct,
  51 true-dup) has dense shared vocabulary that compresses embedding space:
  the classes overlap from 0.84 to 0.96, so no single line separates them, and
  at 0.79 the threshold did almost no discriminative work (81-100% flag rates,
  87-95% false-positive) — every candidate cost a full-body D3 read. The study
  also found the bottom band clean (zero true-dups below 0.8413) and the top
  band not worth auto-skipping by default (0.94 would falsely drop 2 distinct
  entries to save 1 read).
- **Decision:** replace the single threshold with two calibrated bands. `s` =
  candidate's max cosine similarity to an existing entry: `s < dedup_low` →
  `added` (unchanged auto-add path); `dedup_low ≤ s < dedup_high` →
  `skipped-duplicate` (unchanged string, still the D3-reviewable band);
  `s ≥ dedup_high` → new disposition `skipped-duplicate-confident`, accepted
  by the extract procedure without a full-body D3 read (still reports
  match + similarity for a spot-check). Config: env seams `MEM_DEDUP_LOW` /
  `MEM_DEDUP_HIGH` (consistent with the `MEM_*` family, D15's pattern —
  per-instance, no persisted config file anywhere in this codebase).
  **Defaults: `dedup_low = 0.79`** (D3's measured value; default `--json`
  output is exactly the pre-D17 object — no `dedup_high` or
  `skipped_duplicate_confident` keys at all, proven by an exact key-set
  comparison against the pre-D17 shape, not just unchanged-value assertions —
  the work instance is unaffected) **and `dedup_high` disabled** (`None`) —
  a confident band is a per-instance calibration choice, never a global
  default. `MEM_DEDUP_THRESHOLD` (the pre-D17 name) is kept as a back-compat
  fallback for `dedup_low`, so existing per-instance env config needs no
  change; `MEM_DEDUP_LOW` takes precedence when both are set. Per-instance
  deployment: the personal instance sets `dedup_low = 0.83` (removes ~28% of
  D3 reads at zero observed error, per the study) with `dedup_high` left
  disabled — the top band stays a mechanism, not a default, until a larger
  sample moves the 0.8413 floor with confidence. **Band config is validated
  when read:** `mem extract` refuses cleanly (one-line `error:` message,
  exit 1 — the same `ExtractError` pattern the command already uses for a
  down daemon or malformed candidates) if `MEM_DEDUP_HIGH` is configured and
  not strictly greater than `dedup_low`, or if either value is non-finite or
  unparseable. A reversed or degenerate pair would silently make the
  confident band swallow the reviewable one (or vice versa) with no visible
  symptom; this was raised as an open question at gate and the orchestrator
  decided fail-fast refusal over silent tolerance.
- **Proof:** `tests/test_d17_dedup_bands.py` — below-low → added; inside the
  reviewable band → `skipped-duplicate` (`dedup_high` disabled, or configured
  but not crossed); exact equality at `dedup_low` and, separately, at a
  configured `dedup_high` are each pinned through the real extract flow using
  identical-vector (cosine exactly 1.0) candidates, so both inclusive `>=`
  boundaries are proven bit-exactly rather than approximated by a margin;
  above a configured `dedup_high` → `skipped-duplicate-confident` (JSON and
  text-report forms, counted separately in the summary line); confident band
  stays disabled by default even at very high similarity; the default
  `--json` object's exact key set matches the pre-D17 golden (no `dedup_high`
  / `skipped_duplicate_confident` keys present at all), with a separate test
  proving those two keys appear only once `dedup_high` is configured;
  `dedup_high <= dedup_low` and non-finite/unparseable band values are each
  refused cleanly with a nonzero exit; legacy `MEM_DEDUP_THRESHOLD` still
  maps to `dedup_low`; `MEM_DEDUP_LOW` takes precedence when both env vars
  are set; the personal calibration artifact's documented defaults are
  pinned against `config.DEFAULT_DEDUP_LOW`/`DEFAULT_DEDUP_HIGH` the same way
  `tests/test_f9_extract.py` pins D3's artifact. Full suite green
  (`MEM_REQUIRE_NETNS=1 uv run pytest`, 138 passed, up from 124).
- **AI involvement:** the agent ran the personal-instance calibration study
  (five extraction batches, `analyze3.py`, KB-existence ground truth) that
  surfaced the class overlap and motivated a second band; Brent approved the
  two-band mechanism and its defaults (2026-08-17); the agent chose the
  `dedup_low`/`dedup_high` names and the env-seam implementation, consistent
  with the existing `MEM_*` config family and D15's per-instance pattern. A
  gate cycle (verifier) found the default JSON was not actually
  byte-identical, the equality boundaries were untested, and this record
  overstated both; the orchestrator additionally decided the open question
  on malformed band config (fail fast, don't tolerate silently). This fix
  cycle corrected the implementation, replaced the misleading test with a
  golden comparison, added the boundary and validation tests, and corrected
  this entry to match.

## D18 — Dedup DETECTION accuracy: parked engagement, Brent-approved for the backlog (2026-08-24)

- **Context:** the AP-BPF remediation (ap-business-personal-finance,
  `work/kb-extraction-plan-2026-08-21.md` header, runs `r1p2a-gate1..4`)
  stress-tested near-dup detection against a dense 1,221-card instance. Four
  independent adversarial gates each found confirmed duplicates the previous
  "exhaustive" check had cleared. Failure modes, all evidenced in the run
  dirs: (1) true dup ranked below a topical false positive (rank 3–8);
  (2) confirmed dups at 0.63–0.73 semantic similarity, below any usable
  threshold; (3) composite dups spanning the UNION of two live cards;
  (4) subset dups (candidate body ⊂ live card) that symmetric cosine
  under-scores; (5) reference/spine cards invisible to embedding search,
  found only by lexical grep; (6) a tool-interface misread (`mem search
  --json`'s hybrid `score` grabbed instead of `semantic_similarity`).
  D17's two-band thresholds solved save-time ROUTING; this is the DETECTION
  layer beneath it — whether the true duplicate reaches the adjudicator at
  all. The gates' ~90 adjudicated DUP/DISTINCT/FOLD labels (with scores) are
  a ready-made calibration set; the 2026-08-19 work-instance study already
  flagged that skips leave no durable trace.
- **Decision (Brent, 2026-08-24): PARKED — approved for the backlog, to fire
  after the AP-BPF KB is finished and handed to the ap agent.** Scope when it
  fires: (a) a first-class `mem dedup <file>` command encapsulating the
  correct method once (fused RRF retrieval incl. the lexical leg — the save
  path is embedding-only today; fixed deep-K full hit list; un-misreadable
  report), (b) containment/coverage scoring at sentence-or-claim grain
  against single cards AND unions of top-M (catches subsets + composites),
  (c) flag on EITHER semantic OR lexical-coverage signal, (d) include
  reference/spine cards in the dedup surface (chunk long cards), (e) persist
  per-run skip/adjudication records so recalibration is mechanical,
  calibrating first on the 2026-08-24 gate labels, (f) rewire the save-path
  check to consume the same detector, (g) [added 2026-08-25, Brent]: run the
  FALSE-SUPPRESSION sweep over the AP-BPF remediation's 60 prior-cycle
  NO-ACTION-DUP-class rulings (r1-phase2 dup-rulings artifact) with the new
  tooling — those rulings remain trusted until this sweep runs (R3 gate's
  deferred-with-owner disposition). Not in scope here: agent-roster's
  fanout result-compaction fix (results keyed by lens role) — a roster-repo
  item recorded in the session memory's process-retro backlog.
- **AI involvement:** the orchestrator surfaced the failure taxonomy and
  proposed the scope from the gate evidence; Brent approved parking it on
  the backlog (2026-08-24 evening) and set the trigger (post-handoff,
  process-improvement pass). No code has been written; nothing in the store
  changes until the engagement fires.

## D19 — `mem save --update` merge semantics + deletion warning: approved, parked until after AP-BPF r5b (2026-08-26)

- **Context:** during the AP-BPF r5b engagement, an orchestrator `mem save
  --update` call that passed a partial field set silently clobbered four
  frontmatter fields on `current-and-noncurrent-balance-sheet-classifications`
  (title, description, `related:`, and the R5-added `ced-3-7` retag — a tag
  backing a live coverage citation). `--update` replaces every field from the
  invocation's arguments/defaults rather than merging with the stored concept;
  omitted fields fall back to derivation (description from body line 1) or
  empty (`related: []`). Caught in the post-edit diff and restored within the
  minute; net damage zero, but the failure is silent by construction and the
  operator was the project's own author-orchestrator — a worst-case-friendly
  UX.
- **Decision (Brent, 2026-08-26): approved for implementation, parked.**
  Scope: (a) merge semantics for `--update` — Brent leans merge-by-default
  (or minimally a `--merge` flag; the default is an implementation-time
  ruling); (b) a LOUD warning whenever an update would delete or replace an
  existing field's value without an explicit delete/clear verb being invoked;
  (c) an explicit field-removal mechanism so intentional deletions remain
  possible; (d) tests covering partial-invocation updates. Timing: fires
  after AP-BPF r5b completes (or at the next natural pause) — `mem save
  --update` is load-bearing inside the running engagement (retag and
  coverage-card paths), and write-semantics changes should not land
  mid-stream under the copyright-firewall KB.
- **AI involvement:** the orchestrator caused, caught, and repaired the
  incident, and proposed the parking rationale; Brent approved the change and
  delegated the now-vs-later call (2026-08-26).

## D19 — implemented (2026-09-02)

- **Rulings applied (implementation-time, orchestrator-settled):** (1) merge
  is the default on `--update` — every omitted field keeps its stored value
  (description is never re-derived just because it was omitted); (2)
  omitted-vs-explicit is distinguishable — `--type`/`--sensitivity` parser
  defaults changed to `None`, with the fresh-save defaults (`concept`,
  `normal`, derived description) applied only on a fresh save; (3) `--title`
  is optional on `--update` when `--slug` is given, still required otherwise
  and on every fresh save; (4) body on `--update` is kept when `--body` is
  absent and stdin is a TTY or empty, replaced by non-empty piped stdin; (5) a
  loud `warning: --update replaces <field>: <old> -> <new>` line on stderr for
  every field an update would actually change, silent when the value is
  identical; (6) an explicit `--clear FIELD[,FIELD...]` verb (clearable:
  description, topics, related; refused with one exit-1 `error:` line for
  source (D9), body, title, slug, created, updated, type, sensitivity, for a
  fresh save, or for a field also set explicitly); (7) lists (`--topics`,
  `--related`) are replaced wholesale when passed explicitly, never unioned —
  no `--add-topics` verb, out of scope. Caller audit (grep across the save
  path, `blocks.py`, README, and the extract procedure text): no caller
  depends on replace-all behavior — none needed updating beyond the `mem save
  --help` text itself.
- **Gate cycle:** first pass FAILED (five Class-1 findings + one Class-2,
  `work/agents/d19-gate/verifier/output.md`) — a pre-lock merge race (the
  headline finding), a fresh-save `--description ""` regression, a `--clear
  ""` bypass on a fresh save, warning truncation applied to every field
  instead of only long bodies, a weak incident-replay test that failed
  pre-change only via argparse, and this addendum's absence. This entry
  records the fix cycle that resolved all six.
- **The race fix:** the merge was being computed (`load` the existing
  concept, then merge its fields against the invocation's arguments) BEFORE
  the inter-process write lock was taken. Two concurrent partial `--update`
  calls (e.g. one setting `--topics`, one setting `--related`) could each
  load the same pre-update state, merge independently, and both exit 0 — the
  second writer's merge silently discarding the first writer's change with
  no warning, because the merge itself never saw it. This is the exact
  incident class that motivated D19 in the first place, now reproducible
  under contention instead of just under an unlucky retag. Fix: `_save` now
  reads stdin (if the invocation needs it) BEFORE acquiring `write_lock`,
  then performs load → merge → change-report → serialize → atomic write →
  commit → lexical index entirely INSIDE the lock, so a second writer's merge
  always reads the first writer's already-committed state. `vector.index_saved`
  stays outside the lock, unchanged. Proven by
  `test_concurrent_disjoint_partial_updates_both_land`, which holds the write
  lock while spawning both writers (so they queue on it for real, mirroring
  `tests/test_f7_concurrency.py`'s pattern) and asserts both disjoint fields
  land.
- **Deviations:** none forced. The fresh-save `--description ""` regression
  and the `--clear ""` bypass were both defects in the first-pass diff
  against the brief's own rulings, not new design forks — fixed to match
  Ruling 2 (fresh-save byte-identity) and Ruling 6 (`--clear` refused on a
  fresh save) respectively, each pinned with an explicit test.
- **Proof:** `tests/test_d19_update_merge.py`, 21 → 28 tests (7 added: the
  concurrency race, the fresh-save empty-description A/B, `--clear ""` /
  `--clear ","` refusal on both fresh and update, and the long-source-full /
  long-body-elided warning pair). Full suite 159 → 166 passed, both
  `uv run pytest` and `MEM_REQUIRE_NETNS=1 uv run pytest` green. The
  strengthened incident-replay test was independently confirmed to fail
  against the true pre-D19 committed code (`git show HEAD:src/agent_memory/
  store.py`) for the real reason — the description re-derived from the new
  body (`'Balance sheet items split by operating-cycle horizon.' ->
  'Revised wording for clarity.'`) — not merely on the old parser's
  `--title`-required argparse error.
- **AI involvement:** the orchestrator delegated the fix cycle after gate
  FAIL; the implementer applied all six mandated corrections and reran both
  full-suite commands to green before this addendum was written
  (2026-09-02).

## D18 — design accepted (2026-09-02)

- **Design:** `research/d18-dedup-detection-design-2026-09-02.md` (architect run
  `d18-dedup-design`, opus, read-only; fence on the engagement's own KB instance honored (path redacted 2026-11-17) —
  calibration evidence drawn entirely from the fence-free
  `work/kbx-2026-08-21/r1-phase2/` archive joined to the live default KB).
  Headline measurements: shipping argmax-cosine detector recalls only 0.41 of
  confirmed dups at `dedup_low=0.79` (0.20 at the work instance's 0.83); classes
  do not separate on cosine; lexical claim-coverage FP side measured at 0.021 max
  over 225 real topical negatives. Doctrine: threshold each leg for its own
  precision, take recall from the union.
- **Decision (Brent, 2026-09-02): design accepted, "go with defaults" — all eight
  open questions resolved to their stated defaults**, including: build the chunk
  index (S3, lowest priority, opt-in); `mem save` keeps its bypass (+ advisory
  `--dedup-check`); `mem dedup` logs by default; coverage flag on in `mem dedup`,
  off in `mem extract` pending instance log evidence; semantic claim leg built,
  shipped off (R1 recorded); superset never auto-skips; sweep escalation bar
  fixed up front at >=4 overturn-distinct of 60; label mapping NO-ACTION-DUP→DUP,
  NEW-SAVE→DISTINCT, FOLD→positive-for-detection.
- **Execution note (orchestrator):** slices S1–S8 run as three gated waves
  (W1 = S1+S2, W2 = S3+S4+S5, W3 = S6+S7+S8), each wave delegate→gate→commit
  with the design's per-slice proof obligations as gate checklist; S6's golden
  byte-identity is the hardest gate criterion. G1/G2 remain post-fence.
- **AI involvement:** architect produced the design and calibration analysis;
  Brent accepted and ratified the defaults; the orchestrator chose the wave
  batching. Full implementation addendum to follow at completion (§7 rule 7).

## D18 — Wave 1 implemented (S1+S2: claims + detector core), with amendment (2026-09-02)

- **Landed:** `claims.py` (segmentation + coverage tokenizer), `dedup.py`
  (containment, directional IDF-mass coverage, relation table, greedy union,
  fail-fast config), additive `lexical.py` (`lexical_vocab` fts5vocab shadow
  table + `dedup_match_expr`, df=0 terms excluded, n clamped to [1,24]) and
  `config.py` (eleven `MEM_DEDUP_*` seams incl. `MEM_DEDUP_CHUNKS`). No
  retrieval wiring, CLI, extract/save change, chunk table, or log writes —
  W2/W3 scope. Suite 166 → 239, both commands, netns asserted.
- **AMENDMENT (orchestrator ruling on the gate's open question): coverage IDF
  is CARD-GRAIN, stem-aligned, in-memory** (document = card body, df = cards
  containing the token), selectable grain removed; `fts5vocab` feeds ONLY the
  lexical query builder's unstemmed term selection. Rationale: the design's own
  §3.3/§3.4 calibration was computed card-grain in-memory, and fts5vocab's
  unstemmed vocabulary cannot align with the stemmed coverage tokenizer.
- **Gate cycle:** codex round 1 FAIL (7 Class-1, all reproduced: unseen-term
  query starvation; a superset high-band auto-skip bypass; initialism
  mis-splits; quadratic segmentation >32KiB; two config gaps; caller-bypassable
  term cap) → fix cycle (sonnet) killed 6 → round 2 FAIL on one residual
  (fresh `R&D. Dept.` shapes still dropped content) → orchestrator in-seat fix:
  `&`-joined initialisms guarded structurally, `dept` enumerated, and
  **sentence splitting made loss-proof by construction** (a sub-floor fragment
  MERGES into its neighbor, never drops; residual mis-splits are cosmetic) —
  flipping the measurement corpus's last mismatch family to byte-exact (0/20
  hand-labeled, 0/100 overall, pinned) → scoped round 3 **PASS, 0 blocking**,
  incl. fresh adversarial shapes, backward-merge edge, linearity re-check.
- **Class-2 disposition (gate-concurred):** the mis-split measurement stays a
  deterministic synthetic corpus with exact expected boundaries — a real-card
  fixture would embed KB content in the repo tree.
- **AI involvement:** implementer + fix-cycle lanes (sonnet), three codex gate
  rounds, orchestrator in-seat fix cycle 2 and the IDF ruling; Brent's
  standing "go with defaults" (2026-09-02) authorized the wave.

## D18 — Wave 2 implemented (S3+S4+S5: chunk index + `mem dedup` + durable log), with rulings (2026-09-02)

- **Landed:** `chunks.py` (block-grain section chunker + `chunks` table, lazy +
  `mem reindex --chunks` eager population, oversize skip), `dedupcmd.py`
  (`mem dedup`: input sniffing, fused deep-K retrieval, un-misreadable JSON/text
  reports — no key named `score` or `semantic_similarity` at any depth, RRF
  emits only integer `fusion_rank`; `--adjudicate`), `deduplog.py`
  (`.index/dedup-log.jsonl`: detection + adjudication records joined on
  (run_id, content_hash), config embedded per record, STRICT <4096B atomic
  lines, reindex-preserved — the second deliberate non-derived exception after
  D8's usage.jsonl), `vector.top_k_doc` (document-prefixed scan with
  model/digest/dims identity enforcement), additive `lexical.search_expr`,
  ARCHITECTURE.md storage/CLI reconciliation. extract.py/store.py byte-untouched
  (W3 scope). Suite 239 → 294, both commands, netns asserted.
- **Ruling A:** fallback relation labels (0.35/0.85 when coverage unconfigured)
  are PRESENTATION ONLY — verdict routing reads configured thresholds
  exclusively; the superset confident→review downgrade applies only under
  configured coverage. **Ruling B:** semantic-flag + unrelated-coverage maps to
  the generic `review` action — ratified as a NEW W2 routing rule after the
  gate proved (git archaeology at a8d4456) the implementer's "pre-existing W1
  bug" provenance claim false. **Ruling C (round-2 residuals, orchestrator
  in-seat):** zero-overlap chunk advances are never permitted — single-block
  chunks force-include the next block under the hard cap; an over-cap block
  pair takes the ratified `_windows` character fallback; block-grain resume
  re-includes the trailing block. **Standalone `mem dedup` coverage overlay:**
  0.35/0.85/0.55 when env unset, dedup command only; extract globals stay
  disabled (ratified Q3).
- **Gate cycle:** codex round 1 FAIL (10 Class-1, all reproduced — headline:
  the coverage-on default missing from the very surface it was ratified for; a
  fallback-bound verdict leak; no embedding-identity enforcement; advisory
  4096B bound; untruthful legs_run; block-cutting chunker; stale ARCHITECTURE;
  the false provenance claim) → fix cycle (sonnet) killed 8 → round 2 FAIL on
  two boundary conditions (<= at exactly 4096; zero-overlap two-block advance)
  → orchestrator in-seat fixes → round 3 (cap round) confirmed ALL runtime
  behavior correct, FAILed only the orchestrator's own boundary regression pin
  as mutation-ineffective (title-swept; the builder elides titles) →
  orchestrator rewrote the pin through the non-elided config field + ran the
  gate's mutation check both directions in-seat (each reverted guard fails its
  pin) → **escalated per GATE-POLICY's cap rule; Brent ruled commit-now on the
  mutation evidence (2026-09-02 16:38)**.
- **AI involvement:** implementer + fix lanes (sonnet), three codex gate
  rounds, orchestrator rulings A–C + two in-seat fix cycles; Brent's cap-round
  commit ruling.

## D18 — Wave 3b implemented (S7 + S8); S6 DEFERRED with its follow-up spec (2026-09-03)

- **Landed (S7):** the semantic claim leg — `claim_vectors` table in `claims.py`
  (identity-stamped like chunks; lazy, retrieval-scoped population; `mem reindex
  --claims` eager build; plain reindex drops stale rows), `MEM_DEDUP_CLAIM_SEM`
  activates claim-pair matching as lexical OR semantic; **shipped OFF** (ratified
  Q4; R1 — the paraphrase gap while off — stands recorded). Proof: paraphrased
  claims sharing zero tokens → lexical 0.000, semantic high, OR-flag fires;
  cache (second run zero new embeds); scope bounded by deep-K; graceful degrade
  in standalone `mem dedup`.
- **Landed (S8):** `research/dedup_detection_calibration.py` + committed
  artifact `research/dedup-detection-calibration-2026-09-02.md` — Stage 1a
  (coverage mechanics + FP side, synthetic, D3's 26 pairs as negative control)
  and Stage 1b (archive replay, md5-pinned canonical labels, NEVER globbed)
  reproducing the design baseline EXACTLY: recall@1 0.810, recall@10 0.968,
  MRR 0.872, threshold recall 0.410 @0.79 / 0.197 @0.83. A test pins the
  shipped standalone `mem dedup` overlay (0.35/0.85/0.55) to the artifact
  (config.py globals stay disabled). `mem save --dedup-check`: advisory only
  (stderr report; save, stdout, exit code unchanged), resolving model+digest
  identity exactly as `mem dedup` does (W3b gate finding 1).
- **S6 (extract rewiring onto `dedup.detect()`) — DEFERRED (Brent, option 3,
  2026-09-03).** History: W3 round 1 FAIL (6 C1) → fix → round 2 FAIL (2
  residuals) → orchestrator ruled "two-phase extraction with provisional
  in-batch candidates" → cap round FAIL: the provisional mechanism opened 4
  real new C1 (provisionals visible to the vector leg only → lexical intra-batch
  dups saved; durable ghost claim rows after refusal; unprotected predicted
  slugs under concurrent saves; untruthful legs_run) + 1 FALSE finding (D12's
  link-remap second commit + re-embed are PRE-EXISTING HEAD behavior — the
  orchestrator's gate criterion was wrong, not the code). Escalated per
  GATE-POLICY's cap rule; Brent chose to ship S7+S8 and defer S6.
  **Follow-up spec (ratified as the direction for S6 when it fires): the
  TRANSACTIONAL BATCH** — phase 1 performs ALL daemon work (candidate document
  + claim embeds; pre-populate claim/chunk vectors for each candidate's
  pre-batch deep-K; in-batch cards reuse their candidate vectors); phase 2 is
  the UNCHANGED pre-D18 sequential detect→save loop under the write lock
  (intra-batch semantics + golden byte-identity preserved by construction);
  any failure rolls back (delete created files, `git reset --hard` to the
  pre-batch head, purge derived rows, log records buffered until success). No
  provisional machinery. Meanwhile the extract PROCEDURE may invoke `mem dedup`
  as an explicit step — the full detector reaches the adjudicator today on
  gated code. **First task of that follow-up (sanity 2026-09-03, validated
  HAZARD, Brent-backlogged):** memoize each `Claim`'s unit vector/norm and
  compute the claim-match matrix once per hit so `greedy_union_cover` consumes
  it instead of recomputing `matched()`/`_claim_cosine()` every union round. `extract.py`/`vector.py` are byte-identical to the W2 commit;
  `dedup.detect()`'s `strict_claim_leg`/`precomputed_claim_vecs` and
  `fakes.die_after` are documented RESERVED/unused seams for that follow-up.
- **W3b gate cycle:** round 1 FAIL (3 C1: the advisory's missing digest
  identity; the orchestrator's S6 pruning residue in the renamed test file;
  the calibration generator/artifact citing the removed test and misstating
  the overlay pin) + 1 C2 (dead seams/false docstring) → all fixed in-seat
  (digest fix mutation-checked both ways) → round 2 **PASS-W-NOTES, 0
  blocking** (three cosmetic notes, cleared before commit). Suite 294 → 305,
  both commands, netns asserted. D18 in-repo scope is now complete except the
  deferred S6; G1 (per-instance calibration replay) and G2 (the 60-ruling
  false-suppression sweep, escalation bar ≥4/60 fixed up front) remain
  post-fence.
- **AI involvement:** implementer/fix lanes (sonnet, personal lane by Brent's
  intent), five codex gate rounds across W3/W3b, orchestrator rulings + two
  in-seat fix passes, Brent's option-3 ruling and commit-and-deploy decision.
- **Procedure v2 (2026-09-03, Brent-requested):** the extract-knowledge
  choreography gains step 4 — `mem dedup` on the reviewer survivors BEFORE
  `mem extract`, reading only verdict/recommended_action/flag_reasons/relation,
  with the DUP/DISTINCT/FOLD judgment recorded via `--adjudicate` (calibration
  data from day one) and FOLD landing on D19's `mem save --update` merge;
  candidate-superset is never auto-skipped. This is what makes the S6 deferral
  cheap: the full detector reaches the adjudicator on gated code with
  extract's write path untouched. Both managed instruction blocks name the
  step; `tests/test_f10_procedure.py` pins its presence and ordering. In-seat
  doc/choreography change, suite 305 green; no gate (no runtime behavior
  changed).

## Handoff flush (2026-09-03) — two durable calls not yet on the record

- **Follow-up trigger (Brent, 2026-09-03):** the deferred S6 extract rewiring
  (transactional-batch spec above), G1 (per-instance calibration replay against
  a pinned clone), G2 (the 60-ruling false-suppression sweep, report-only,
  escalation bar >=4/60) and that engagement's backup-cron wiring all fire together
  **when the ap-business agent is not spun up** — the same fence-lift condition
  as the sweep's precondition (1); none of them runs while that agent holds the
  engagement's KB instance (path redacted 2026-11-17). First task when it fires: the backlogged
  dedup union-recomputation hazard.
- **Post-commit deploy seam (Brent, 2026-09-02):** `scripts/git-hooks/post-commit`
  auto-reinstalls the `mem` tool on any commit touching `src/`, `pyproject.toml`
  or `uv.lock` — deliberately, so the CLI agents invoke never drifts from HEAD —
  and honors `MEM_HOOK_NO_REINSTALL=1` to defer that deploy when another agent is
  live on the installed tool (a loud skip line names the deliberate deploy
  command). Rationale: the D19 commit hot-deployed merge semantics under a live
  engagement without a decision point; the seam restores one without giving up
  deploy-on-commit as the default. Not a product feature; repo tooling.

## D1 — Amended: an allowlist for the KB's remote (ruled 2026-10-15; logged 2026-11-17)

- **Decision (Brent, 2026-10-15):** a KB instance may keep a git remote whose exact URL is listed
  in `<kb root>/.allowed-remotes` (one URL per line, `#` comments); every other remote remains a
  `mem doctor` failure and a write-path warning. Public, vendor-hosted and personal-cloud remotes
  are never allowed. Shipped in 0.2.1 (`BUILD_LOG.md` 2026-10-16: `gitkb.allowed_remotes()`,
  `tests/test_d1_allowed_remotes.py`); the managed blocks say so. Logged here because the
  2026-10-16 build entry carried the ruling without a decision entry.

## D2 — Amended again: OKF v0.2 reviewed, no migration (2026-11-17)

- **Basis:** the pinned v0.1 snapshot (`research/okf-spec-v0.1.md`) came from a repository that is
  now a frozen copy; the specification moved to `GoogleCloudPlatform/open-knowledge-format`
  (`SPEC.md`, "Version 0.2", read 2026-11-17).
- **Finding, limited to what was checked:** ordinary concept files remain compatible with v0.2
  consumers — parseable YAML frontmatter, non-empty `type`, no reserved file names. v0.2 supersedes
  `timestamp` with `generated.{by,at}` (consumers may fall back to `timestamp`) and body citations
  with frontmatter `sources[]`; it adds `verified`, `status`, `stale_after`, `resource`, an actor
  convention and an Attested Computation type with its own required keys, which we never emit.
  This is not a claim about every v0.2 type.
- **Decision:** no format upgrade; the serializer's `tags`/`timestamp` mirrors stay as legacy-
  compatible interop. Additive `generated`/`sources` emission is backlog, taken up only if interop
  with a v0.2 provenance consumer is wanted.

## D20 — Host-mediated shared writes: built 2026-10-20, a held private deployment mode (2026-11-17)

- **What exists:** `shared.py` / `coordinator.py` and the `retry · pending · refresh · delete`
  commands implement host-mediated writes. Governance (`shared.profile_for`) has two steps. First,
  obtaining a listing from the operator profile (an owner-only regular file under the user's config
  directory): when the profile is missing, unreadable, malformed, has no `roots` table or lists only
  other roots, a KB carrying the `agent-memory.sharedWrites` git marker refuses local source writes
  (fail closed) and an unmarked KB is simply local. Second, once the profile lists the root, it is
  validated (machine, receiver paths, and on a laptop a complete `transport` entry: alias, hostname,
  user, port); a validation failure refuses writes regardless of the marker. So a listed root is
  governed by its profile whether or not it is marked, and a laptop profile without `transport`
  governs every root it lists into refusal. `init` refuses a governed KB. Endpoint values live only
  in the profile's `transport` entry, never in source (2026-11 curation).
- **Status:** held. The suite exercises the transport only against synthetic profiles and synthetic
  roots with the transport mocked (`tests/test_shared_writes.py`, `tests/test_coordinator.py`);
  live transport is not exercised. `SHARED-WRITES.md` is kept as the historical procedure under a
  banner saying so. Re-enabling it is an operator decision with its own approval, not a code change.

## D21 — Every update carries the version it was based on (2026-11-17)

- **Decision:** `mem save --update` requires `--expected-version` equal to the `version` returned
  by the preceding `mem get <slug> --json`, compared under the writer lock; missing, malformed or
  stale tokens are refused with nothing written and no commit. Extraction's link remap re-checks
  each touched card under the lock and refuses a card that changed during extraction. The shipped
  instruction blocks carry the read → version → update contract and forbid blind retries with a
  fresh token.
- **Why:** the privately installed release already enforced this (2026-11-11) while source still
  accepted stale local updates, so a future source-based release could have lost the protection.
  A deliberate public update-contract change; D19's merge semantics are unchanged.

## D22 — A commit never deploys; release, activation and rollback are explicit (2026-11-17)

- **Decision:** the post-commit hook no longer reinstalls the tool (it prints one identity line:
  what `mem` on PATH imports now). `scripts/release.py` stages a revision into a read-only release
  directory with a manifest, and activation into a uv tool prefix (non-editable install plus a
  selector `.pth`) or rollback is a separate, receipted operator action that refuses the live
  default prefix unless explicitly allowed. `mem --version` and `mem doctor`'s `runtime` line name
  the imported package, selector and interpreter.
- **Why:** a reinstall silently removed any release selector and changed what bare `mem` ran, which
  a pinned wrapper then refused. This supersedes the 2026-09-02 "post-commit deploy seam" handoff
  note above; `MEM_HOOK_NO_REINSTALL` is no longer needed.

## D23 — Zero-egress outer leg: required where a user namespace is available (2026-11-17)

- **Decision:** `MEM_REQUIRE_NETNS` survives the test suite's hermetic environment fixture; with it
  set, an unavailable user+network namespace is a failure, without it an explicit visible skip.
  Required acceptance runs from a context that can create the namespace; a context that cannot
  (for example a shell confined so that unprivileged user namespaces are refused) records the
  skip with its reason. No security-setting change is made to obtain the capability.

## D24 — Lifecycle: the shared delivery workflow replaces KodOS for this project (2026-11-17)

- **Decision:** development proceeds in small reviewed slices with one receipt per candidate
  (command, source and configuration identity, duration, exit status, counts, evidence paths),
  independent review of each slice, and separately approved activation. The KodOS artifacts
  (`INTAKE.md`, `PRD.md`, `NFR_UX.md`, `IMPLEMENTATION.md`, `BUILD_LOG.md`, `.kodos/`) are
  preserved as dated history and are not regenerated; the repository's `AGENTS.md`/`CLAUDE.md`
  point at the shared workflow.
- **Backlog separation (2026-11-17):** D18 S6 (rewiring `mem extract`'s dedup decision onto
  `dedup.detect()`, with its transactional-batch spec) stays deferred and reusable. Items tied to a
  retired engagement or a retired machine layout — the G1 calibration replay, the G2 60-ruling
  sweep, the retired engagement's backup cron, `scripts/agent-memory-backup`'s wiring, the personal-KB passport
  backup plan and the 2026-09-21 frozen-copy scheme — are listed as obsolete candidates awaiting
  Brent's word; nothing is deleted.

## D25 — Frozen plugin serving: the harness's declaration is the registration (2026-11-17)

- **Decision:** both agent harnesses serve the `mem` plugin from a read-only plugin snapshot frozen
  from one revision (`<releases-dir>/plugin-<version>+<sha12>`, manifest, 0555/0444), never from a
  worktree. For Claude Code the authoritative registration is the user's `extraKnownMarketplaces`
  setting, which the harness re-merges into its marketplace registry at every fresh start; the
  registry files are derived state and the installed plugin's `installPath` is what loads. For
  Codex the registration is its config's marketplace source, changed only through its own CLI
  (remove, add, re-add) and verified by a semantic comparison of the config and the cache bytes.
- **Why:** on 2026-11-17 the registry had been repointed at a snapshot and a fresh Claude start
  silently restored the worktree path from the setting while the loaded skill still came from the
  snapshot; the two facts had to be separated and the setting pinned. Serving from a worktree
  meant that a dirty checkout, or any later commit, was what agents loaded.

## D26 — `/mem:extract` resolves its entrypoint from the governing memory policy (2026-11-17)

- **Decision:** the shipped skill names no default instance and no laptop-specific command. Before
  any tool call or delegate it resolves ENTRYPOINT from the policy in effect: a guarded entrypoint
  for one instance (a wrapper that selects the instance and holds `doctor`, `init`, `retry`,
  `pending`, `refresh`, `delete`), or the ordinary `mem` for an authorized instance; with no
  authorized route it stops and asks — an unset instance is not permission to use a default, and a
  held instance is never a fallback. Every command form the printed procedure uses is mapped
  explicitly; policy restrictions override procedure examples. The preflight claims only what each
  check proves: `--version` for runtime identity (and, under a guard, the wrapper's own instance
  validation), `doctor` where permitted and named as a write, otherwise a read-only daemon/model
  probe that cannot see the embed queue or FTS5, with a stop before any fan-out.
  `tests/test_extract_skill_routing.py` pins these contracts against the procedure text.
- **Why:** the earlier skill told a session to use a held default instance, to run `doctor` (a
  derived-state write) and to suggest `init`; on an installation whose policy routes through a
  guarded wrapper those steps were outside the permitted path and would have been attempted first.
  The skill text is a shipped, portable artifact; the laptop's routing belongs to its policy.

## D27 — Closeout of the 2026-11 remediation: where development happens (2026-11-17)

- **Decision:** the reviewed branch `remediation-2026-11` plus the closeout commits (branch
  `closeout-2026-11`, made in the isolated candidate clone) is the development line. The original
  checkout's `main` is to be fast-forwarded to it — a prepared, separately confirmed operation; at the
  time of this entry that checkout still sits at dc76e55 with its uncommitted tree — after that
  uncommitted 2026-10-20 release tree is committed onto a local preservation branch
  (`preserve/dirty-tree-2026-10-20`, never pushed — it carries pre-redaction endpoint values) so that
  nothing is stashed, reset, cleaned or deleted — every one of those sixteen files is either
  byte-identical at the new head, present in git history at the curated import commit or on the
  preservation branch, or preserved outside the repository with its delta recorded (the
  reconciliation map in the private records). The one file deliberately not imported,
  a private historical review record under `.kodos/evidence/`, stays untracked and is not
  committed to a publishable branch; whether to move it out is the operator's decision. The isolated
  candidate clone, superseded plugin snapshots and rehearsal scratch are retained until the operator
  closes the rollback window; nothing is deleted in the closeout, and nothing is pushed or published.
  Publication is blocked until the operator decides how to treat the outgoing history: the import
  commit (318e4df) carries lines with the private host alias that commit 8207268 later redacted from
  the tree, and a push of `main` would publish those blobs; rewriting history is not authorized by
  this decision. Until the fast-forward is confirmed, the candidate clone's `closeout-2026-11` is where
  development happens; afterwards it is the original checkout's `main`.
- **Why:** the checkout had been the served source for the Claude plugin and still carries the hook
  that reinstalls the runtime on a source commit; with the frozen release and snapshots active, and
  with the identity-only hook (D22) reaching the checkout through the pending fast-forward itself, it
  can again be the ordinary place to develop. Preserving the uncommitted tree in two forms — a local
  preservation branch made with the hook's no-reinstall seam, and the provenance copies outside the
  repository — is what makes the fast-forward safe to propose without any stash, reset or deletion.
- **Amendment (2026-11-18):** done. The coordinator executed the prepared operation at 12:01 CST
  after a fresh precondition check: the uncommitted tree became commit 0b02228 on the local branch
  `preserve/dirty-tree-2026-10-20` (fifteen files, each byte-identical to its provenance copy; the
  hook's no-reinstall seam used), and `main` was fast-forwarded from dc76e55 to cbad20c. Verified
  afterwards, independently of the executor: the private review record still untracked and
  unchanged, the identity-only hook and the corrected skill at head, `mem --version` and every
  recorded runtime, wrapper, selector and plugin-registration hash unchanged, the candidate clone
  unchanged. Development happens in this checkout's `main` from here; nothing was pushed, published
  or deleted, and publication stays blocked as stated above.
- **Amendment (2026-11-18, later the same day — publication):** the operator judged the alias in
  the import commit's history harmless (a nickname, not a hostname or credential) and chose to
  publish `main` as it is, without any rewrite; `main` is pushed to `origin` after the recorded
  pre-push scan (alias lines only at the import commit; no home paths, private data root, e-mail
  addresses or non-synthetic endpoints in the outgoing history). Task branches are not pushed; the
  preservation branch is never pushed. The rollback window is to be closed on 2026-11-25 if a week
  of normal use passes without issue; every saved copy stays until then.

## D28 — The printed procedure names the caller's entrypoint (2026-11-18)

- **Decision:** `mem extract --procedure --entrypoint NAME` prints the extract-knowledge procedure
  with every command form (`extract`, `dedup`, `get`, `save`, inline or fenced, arguments
  unchanged) as `NAME …`, and replaces the procedure's preflight section with one paragraph: NAME
  was resolved by the caller from its memory policy, the policy's preflight has run, and a command
  NAME holds is never run. NAME is one command name or one absolute path (letters, digits,
  `. _ + -`, `/` only between path components); anything a shell would split or expand, a relative
  path with a slash, a leading `-` or a `.`/`..` component is refused with exit 1 and one error
  line, as is `--entrypoint` without `--procedure`. Without the option the output is unchanged:
  the portable package artifact, bare `mem`, its own preflight. The `/mem:extract` skill prints
  the procedure with `--entrypoint ENTRYPOINT`; its hand mapping remains only for a runtime that
  rejects the option as unrecognized, and any other refusal is a stop.
- **Why:** the skill made agents translate every bare `mem` in the printed text through a mapping,
  and a plain name substitution is not enough: the procedure's only held form under a guarded
  entrypoint is its preflight `doctor`, whose refusal the procedure treats as a stop. Leaving
  preflight to the caller keeps policy out of the package (the CLI never learns which commands an
  entrypoint holds) and puts the check where the policy is read.
- **Consequences:** the skill text depends on the option, so the next runtime release and plugin
  snapshot are frozen from the same revision; until then the laptop's frozen copies keep the
  2026-11-17 behaviour, which the skill's fallback still covers. No version change in this
  decision; the release step is separate.
- **Amendment (2026-11-18, released):** revision a6d77bf was frozen as runtime release
  `0.2.1+a6d77bfd71d2` and plugin snapshot `plugin-0.2.1+a6d77bfd71d2` and both were switched
  together on the development laptop (operator: the coordinator, on the operator's instruction),
  with the guarded wrapper's pins moved to the new release. The version stays 0.2.1; the release id
  carries the commit. Rollback returns to `0.2.1+a1c3a6319b61` / `plugin-0.2.1+8be9b0927063`
  (`RELEASE.md`).

## D29 — Extraction adopts the dedup detector; the batch rollback never hard-resets (2026-11-19)

- **Decision (Brent, 2026-11-19):** when D18 S6 is built, `mem extract` decides duplicates with
  the same detector and policy as `mem dedup` (`dedup.detect()` with the command's coverage
  overlay), acting on the detector's `recommended_action`: `skip` skips, `add` saves, anything else
  (`review`, `update-existing`) is reported for judgment and not saved. This replaces the 2026-09-03
  follow-up spec's assumption that extract's output stays byte-identical with the new settings
  unset: by default some candidates that are saved today will be held for judgment instead.
- **Decision (Brent, 2026-11-19):** the transactional batch does not roll back with
  `git reset --hard`, which could discard uncommitted hand edits in a KB. The batch writes its
  files, makes one path-limited commit at the end, creates new files exclusively, and on a failure
  before that commit removes only the files it created (verified by content hash); a small journal
  covers process death between the writes and the commit. The dedup log is history, not a cache:
  its records are written after the commit, tagged with it, and kept in a pending file if the append
  fails.
- **Why:** reproduced on the active release's code (private scoping record, 2026-11-19):
  extract saved 10 of 10 planted partial duplicates that `mem dedup` flagged on a 3,300-card
  synthetic KB; extract misses concept files edited or added outside `mem` until another command
  refreshes the index; a failure partway through a batch leaves earlier concepts committed and a
  staged file behind; two concurrent extracts often both save the same concept; `mem dedup`
  reports a same-title exact duplicate as novel because it excludes the candidate's own slug.
- **Plan:** slices A (decide on current files: refresh and drain before deciding, never score a
  stale vector, fix the WAL-lock crash and the slug self-exclusion), B (the all-or-nothing batch
  above, with today's decision rule), C (the shared decision), optional D (accept recorded
  DUP/DISTINCT rulings in extract; undecided). Each slice is reviewed on its own; nothing is
  released without a separate activation decision. The scoping plan was reviewed by Codex (FAIL on
  its first draft: skip keyed on the verdict, the slug self-exclusion, the dedup log treated as a
  cache) and corrected; the corrections were not re-reviewed.
- **Slice A built (2026-11-20, the operator's "proceed when ready" on the slice plan):** local
  branch `s6-slice-a-2026-11` (1092398, review fixes 9484dab and df2c097). The rule "no surface scores a stale
  vector" is implemented as a content-hash check against the card's current text, rebuilt from the
  lexical index. Search and dedup leave a stale vector out and re-queue the card, and leave a stale
  chunk set out until the card is next retrieved and re-chunked; neither refuses. `mem extract`
  re-embeds first and refuses the batch only when a card still cannot be embedded.
  Merged into main as 1d89173 (operator, 2026-11-20: "Go ahead and merge the branch then arrange a
  release window with Hub"); released as `0.2.1+1d89173c57a4` and switched live on 2026-11-21 in a
  coordinated quiet window (operator: "Switch the live runtime when you get a quiet window"), runtime
  and wrapper only; rollback returns to `0.2.1+732b914bc791`.


## D30 — The candidate capture/recall wording is chosen (2026-11-20)

- **Decision (Brent, 2026-11-20):** move forward with the candidate memory wording on local branch
  `recall-capture-2026-11` (fbbc111): search memory at the start of non-trivial work and check a hit's
  stated conditions; save a single tested observation stated as one, kept within its evidence. The
  other variants tested on 2026-11-19 (evidence limit, compact format, evidence-scoped paragraph) are
  not pursued.
- **Not decided by this entry:** merging the branch, a release, activation, and the change to the
  guidance laptop sessions actually read. Each still needs the operator's word.
- **Follow-up evidence (same day):** a model pilot on Opus 5.5 and Fable 5.2 (FEATURES F11) showed
  recall and reuse carrying over to both models and Fable meeting every gate; 2 of 4 Opus entries cited
  evidence by absolute local path, outside the integrity bar. How to handle that (a wording sentence
  with an Opus re-check, a save-time check in `mem`, or adoption as is) is the operator's next choice.
- **Amendment (Brent, 2026-11-20 evening, agreeing with Folio's recommendation):** add one sentence to
  the chosen wording, "Cite evidence by project name and project-relative path, never by an absolute
  local path." (both shipped blocks, focused test; branch @ 7319d73), and re-check the Opus captures.
  The re-check (6 sessions, the pilot's capture slots) met the capture gates: 4 of 4 entries correct and
  scoped with no absolute or private path; both controls saved nothing. A save-time path check in `mem`
  is backlogged as a separate slice. Merge, release and activation still each need the operator's word.
- **Released and activated for Claude only (Brent, 2026-11-20 evening):** "Merge the branch, release,
  switch the wording live"; asked whether to test Codex first, he agreed to release for Claude now and
  add Codex after a Codex test ("Claude only for now. Proceed in your proposed order"). Main merged the
  branch (732b914); release `0.2.1+732b914bc791` was activated with the entrypoint re-pinned, and the
  wording, adapted to `mem-personal`, was appended to the user-level Claude instruction file (outside
  the managed policy-reference block; the shared-write `pending`/`retry` sentence left out because the
  laptop instance holds those commands). Folio operated under the operator's direct word; the
  coordinator reviewed the package and arranged a quiet window with the other local agents. Codex
  guidance and the shared policy are unchanged.
- **Codex test postponed (Brent, 2026-11-20):** the contained Codex check found no route that can isolate
  the test (the command sandbox cannot nest inside the test sandbox; the verified route cannot take the
  test's masks or a stand-in memory command without a root-launcher change). Of postponing, building a
  launcher test mode first, or a weaker disclosed smoke test, the operator chose to postpone. Codex keeps
  its current guidance; a launcher test mode is backlogged.
