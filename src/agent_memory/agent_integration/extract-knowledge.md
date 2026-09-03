# extract-knowledge procedure v2

You are the orchestrating agent. Brent has pointed you at a document - a paper,
article, spec, chapter, or transcript - and wants its durable knowledge in his
KB. `mem extract` is the deterministic half (validate, dedup, save); this
procedure is everything before and after that call. Expect a few minutes per
document - the subagent fan-outs dominate (a cross-backend extractor fanout
alone measures ~83s); the `mem extract` call itself completes in seconds.
Report progress as each stage completes.

Non-negotiables:

- **Fresh eyes, twice.** Extractors read the document independently - they see
  neither each other's output nor your conversation. Reviewers see the document
  and the merged candidates - never the extraction chatter. Each subagent
  prompt contains ONLY what its template below specifies.
- **Only reviewer-approved candidates reach `mem extract`.**
- **Vendor policy (DECISION_LOG D1).** Fan out across Claude and Codex
  backends only. Gemini-backed agents (Antigravity) take no part in memory
  work - not as extractor, not as reviewer.
- **Confidentiality.** If the document is employer material, candidates default
  to `sensitivity: work`; only clearly general knowledge stays `normal`; PII/PHI
  about real people defaults to dropping the identifiers - `sensitivity: sensitive`
  (D16) only when they must be kept. When
  unsure, tag `work` - or drop the candidate.

## 0. Preflight

`mem extract` requires the local embedding daemon and refuses cleanly when it
is down. If in doubt, run `mem doctor` first; if it fails, surface the failure
to Brent and stop - never store knowledge elsewhere as a workaround.

## 1. Extract - at least two fresh-eyed extractors

Spawn **at least two** extractor subagents, each reading the document
independently. Use cross-backend fan-out via agent-roster when it is available
in your session (e.g. `agent-roster fanout` across approved backends); use
inline subagents (your runtime's subagent/Task tool) when it is not. The
procedure works identically in both modes - independence is what matters, not
the transport.

Give each extractor a different lens (e.g. "principles and mental models" vs
"techniques and procedures") so the union covers more of the document.

Extractor prompt template - pass the document content or path, a lens, and
nothing else:

> You are a fresh-eyes knowledge extractor for a personal knowledge base.
> Read the document below. Propose the durable, reusable concepts it teaches -
> principles, techniques, hard-won explanations - not document trivia, section
> summaries, or project-local facts. Lens: {LENS}. Each concept's body must
> stand alone: teachable to someone who never sees this document. PII/PHI
> (identifying or health details about real people): distill the knowledge and
> DROP the identifiers; if an identifier is essential, set "sensitivity":
> "sensitive". Typical
> yield: 2-8 candidates. Return ONLY a JSON array of candidate objects:
> `[{"title": "...", "body": "markdown, standalone", "description": "one
> line", "topics": ["..."], "type": "concept", "sensitivity": "normal",
> "source": "citation of THIS document (author/title/year as known)",
> "related": ["existing-or-sibling-slug"]}]`
>
> {DOCUMENT}

## 2. Merge

You merge the extractors' outputs yourself - no subagent:

- Union all candidates; where two extractors proposed the same concept, keep
  the better-written body and union the `topics`.
- Do NOT dedup against the KB by hand - that is step 4's job (`mem dedup`) and
  then `mem extract`'s.
- Number the merged list; reviewers refer to candidates by index.

## 3. Review - at least two fresh-eyed reviewers

Spawn **at least two** reviewer subagents (same backend rules as extractors).
Each receives the document and the merged, numbered candidates - nothing else.

Reviewer prompt template:

> You are a fresh-eyes reviewer gating what enters a personal knowledge base.
> Below: a source document and numbered candidate concepts extracted from it.
> For EACH candidate, judge: accurate (faithful to the document)? durable
> (reusable beyond this document)? well-formed (clear title, standalone body)?
> correctly tagged (sensible topics; sensitivity "work" iff employer-specific,
> "sensitive" iff it carries PII/PHI - and prefer a fix that drops the
> identifiers over keeping them)?
> Return ONLY a JSON array:
> `[{"index": 0, "verdict": "approve" | "reject" | "fix", "reason": "one
> line", "fix": {only-the-changed-fields}}]`
> Reject what is inaccurate, ephemeral, or trivial - the KB's value is
> precision, not volume.
>
> {DOCUMENT}
>
> {CANDIDATES}

Survival rule: a candidate reaches the CLI only if **no reviewer rejects it**.
Apply reviewers' `fix` fields before submitting; if two fixes conflict, take
the more conservative one. Keep every rejection's reason for the final report.

## 4. Detect duplicates with `mem dedup` (DECISION_LOG D18)

`mem extract`'s own dedup is a single whole-document cosine check; on a dense
KB it misses most confirmed duplicates (measured: recall 0.41 at the default
threshold - `research/dedup-detection-calibration-2026-09-02.md`). The full
detector - fused deep-K retrieval plus claim-grain coverage, which catches
subset, composite, and lexical duplicates cosine cannot see - is
`mem dedup`. Run it on the reviewer survivors BEFORE submitting:

```
mem dedup /tmp/candidates.json --json > /tmp/dedup-report.json
```

Read only these fields per candidate - the report deliberately has no key
named `score` or `semantic_similarity`, so there is nothing to misread:
`verdict` (`novel` | `review-duplicate` | `confident-duplicate`),
`recommended_action`, `flag_reasons[]` (each names its signal, value, and
threshold), and the top hit's `relation` (`equivalent` | `candidate-subset` |
`candidate-superset` | `overlapping` | `unrelated`). Then, per candidate:

- **`novel`** - keep it for step 5.
- **`confident-duplicate`** with relation `equivalent` or `candidate-subset` -
  drop it (the KB already holds everything it says); record it as a dedup skip
  in your final report.
- **`review-duplicate`** (any relation) and **any `candidate-superset`** - run
  `mem get <slug> --json` on the named hit and judge: **DUP** (same concept -
  drop), **DISTINCT** (umbrella/member, sibling - keep for step 5), or **FOLD**
  (the candidate adds material to the existing card - merge it INTO that card
  with `mem save --update --slug <slug> --body ...`; D19 merge semantics keep
  every field you omit; then drop the candidate from the batch). A
  `candidate-superset` is never auto-skipped: skipping would discard the new
  material.
- **Record every judgment** so the detector can be recalibrated mechanically
  (D18 §4.5): `mem dedup --adjudicate <log.run_id> --candidate
  <candidates[].content_hash> --label DUP|DISTINCT|FOLD --by <your name>`.
  Both ids are in the report. Never pass `--no-log` in this choreography.

If the embedding daemon is down, `mem dedup` still runs its lexical coverage
legs and says so in `config.legs_run` - proceed, but note the degraded run in
your report. `mem dedup` flags on coverage by default; `mem extract` (next
step) flags on cosine only, so a candidate can be `novel` here and still be
skipped there - see step 6.

## 5. Submit

Write the step-4 survivors (novel + DISTINCT) to a JSON file and run the
deterministic half:

```
mem extract --candidates /tmp/candidates.json --json
```

Candidate schema (the CLI rejects unknown fields item-wise): `title` and
`body` required; `description`, `topics`, `type` (default "concept"),
`sensitivity` ("normal" | "work" | "sensitive"), `related` (slugs), `slug` (default: derived
from title) optional. Invalid candidates are reported individually; valid
siblings still land.

## 6. Review dispositions, then report

**skipped-duplicate is reviewable, not final** (DECISION_LOG D3): the
calibrated `dedup_low` threshold is measured on near-dup vs distinct pairs,
but umbrella-vs-member concept pairs can exceed it (observed live: a member
concept at 0.84 against its umbrella). For each `skipped-duplicate` in the
report, run `mem get <match-slug> --json` and judge: same concept (true
duplicate - accept the skip) or genuinely distinct (umbrella/member, sibling)?
For a wrongly-skipped candidate the sanctioned override is a direct
`mem save` - it bypasses dedup by design. A candidate you already judged
**DISTINCT** in step 4 that extract still skips on cosine is exactly this
case: save it directly, and cite the step-4 adjudication in your report.

**`skipped-duplicate-confident`** (DECISION_LOG D17) is a second, higher
`dedup_high` band: similarity so high a full-body read adds no signal. You may
accept these without the `mem get` read above - the report still carries
match + similarity if you want to spot-check one. Both bands are per-instance
config, measured against that instance's own corpus
(`research/dedup-calibration.md`, `research/dedup-calibration-personal-2026-08-17.md`);
`dedup_high` is disabled by default, so most instances see only
`skipped-duplicate`.

Then report to Brent, in one readable block:

- **added** - slug per concept (including any override saves, marked as such)
- **skipped as true duplicates** - candidate title -> matching slug (mark
  `skipped-duplicate-confident` entries as such)
- **rejected in review** - title + the reviewer's reason
- **invalid** - the CLI's item-wise reason, if any
