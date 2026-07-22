---
description: Run the extract-knowledge choreography on a document — fresh-eyed extractor fan-out, fresh-eyed review, then `mem extract` dedup+save into the knowledge base. Use when the user runs /mem:extract <document>, or points you at a paper, article, spec, or transcript to mine for the KB.
---

# /mem:extract

You run **extract-knowledge**: Brent has pointed you at a document and wants its durable
knowledge in his KB (`~/.agent-memory`, local-only). This skill is a deterministic entry
point; **the choreography itself is owned by the CLI** — you will print it and follow it,
not improvise it.

## 1. Resolve the document

The argument is the document: a file path (relative paths resolve against the current
workspace) or, if it names something ambiguous, find it before starting. **No argument →
ask which document** and stop until answered. Confirm the file exists and is readable
before any other step.

## 2. Preflight

Run `mem doctor`. Gate on the extraction path:

- **Must pass:** kb-home, git-repo, no-remote, fts5, ollama, embed-model, embed-queue.
  Any of these failing → surface the doctor line(s) and stop; `mem doctor` output names
  the remedy. Never store knowledge elsewhere as a workaround.
- **Non-blocking:** `blocks-claude` / `blocks-agents` staleness alone — note it, suggest
  `mem init` afterwards, and proceed (the extraction path doesn't read the blocks).

## 3. Run the choreography

Run `mem extract --procedure` and **follow the printed procedure exactly** — it is the
single source of truth for the fan-out counts, fresh-eyes isolation rules, reviewer
templates, and the final `mem extract --candidates` call. Non-negotiables it will hold
you to, restated for emphasis:

- **Fresh eyes, twice** — extractors and reviewers are isolated subagents; only
  reviewer-approved candidates reach the CLI.
- **Approved vendors only** (DECISION_LOG D1): Claude and Codex subagents; never
  Gemini/Antigravity-backed agents. Cross-backend via agent-roster when available,
  inline subagents when not.
- **Dedup skips are reviewable**: the CLI names each skipped near-duplicate with its
  match and similarity. Adjudicate umbrella-vs-member cases (DECISION_LOG D3) — a
  distinct-but-related concept may be saved via direct `mem save` with a `related:`
  backlink, and that override must be reported, never silent.

Set expectations honestly: the run takes **minutes, not seconds** (DECISION_LOG D4) —
report progress as each stage completes.

## 4. Report

End with the added-vs-skipped report a human can read: what was added (slug + one-line
description), what was skipped and why (named match + similarity), any disposition-review
overrides, anything rejected in review or invalid. If nothing was added, say so plainly.
