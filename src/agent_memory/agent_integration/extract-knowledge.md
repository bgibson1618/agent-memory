# extract-knowledge procedure v1

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
  to `sensitivity: work`; only clearly general knowledge stays `normal`. When
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
> stand alone: teachable to someone who never sees this document. Typical
> yield: 2-8 candidates. Return ONLY a JSON array of candidate objects:
> `[{"title": "...", "body": "markdown, standalone", "description": "one
> line", "topics": ["..."], "type": "concept", "sensitivity": "normal",
> "related": ["existing-or-sibling-slug"]}]`
>
> {DOCUMENT}

## 2. Merge

You merge the extractors' outputs yourself - no subagent:

- Union all candidates; where two extractors proposed the same concept, keep
  the better-written body and union the `topics`.
- Do NOT dedup against the KB - that is `mem extract`'s job.
- Number the merged list; reviewers refer to candidates by index.

## 3. Review - at least two fresh-eyed reviewers

Spawn **at least two** reviewer subagents (same backend rules as extractors).
Each receives the document and the merged, numbered candidates - nothing else.

Reviewer prompt template:

> You are a fresh-eyes reviewer gating what enters a personal knowledge base.
> Below: a source document and numbered candidate concepts extracted from it.
> For EACH candidate, judge: accurate (faithful to the document)? durable
> (reusable beyond this document)? well-formed (clear title, standalone body)?
> correctly tagged (sensible topics; sensitivity "work" iff employer-specific)?
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

## 4. Submit

Write the survivors to a JSON file and run the deterministic half:

```
mem extract --candidates /tmp/candidates.json --json
```

Candidate schema (the CLI rejects unknown fields item-wise): `title` and
`body` required; `description`, `topics`, `type` (default "concept"),
`sensitivity` ("normal" | "work"), `related` (slugs), `slug` (default: derived
from title) optional. Invalid candidates are reported individually; valid
siblings still land.

## 5. Review dispositions, then report

**skipped-duplicate is reviewable, not final** (DECISION_LOG D3): the
calibrated threshold is measured on near-dup vs distinct pairs, but
umbrella-vs-member concept pairs can exceed it (observed live: a member
concept at 0.84 against its umbrella). For each skipped-duplicate in the
report, run `mem get <match-slug> --json` and judge: same concept (true
duplicate - accept the skip) or genuinely distinct (umbrella/member, sibling)?
For a wrongly-skipped candidate the sanctioned override is a direct
`mem save` - it bypasses dedup by design.

Then report to Brent, in one readable block:

- **added** - slug per concept (including any override saves, marked as such)
- **skipped as true duplicates** - candidate title -> matching slug
- **rejected in review** - title + the reviewer's reason
- **invalid** - the CLI's item-wise reason, if any
