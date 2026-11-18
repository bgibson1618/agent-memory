---
description: Run the extract-knowledge choreography on a document — fresh-eyed extractor fan-out, fresh-eyed review, then the CLI's `extract` dedup+save into the knowledge base, through the entrypoint the governing memory policy permits. Use when the user runs /mem:extract <document>, or points you at a paper, article, spec, or transcript to mine for the KB.
---

# /mem:extract

You run **extract-knowledge**: Brent has pointed you at a document and wants its durable
knowledge in his KB. This skill is a deterministic entry point; **the choreography itself is
owned by the CLI** — you will print it and follow it, not improvise it. Which instance you
extract into, and through which command, is decided by the governing memory policy, not by
this skill: resolve it first (step 0) and carry it through every command.

## 0. Resolve the entrypoint — before any tool call or delegate

Read the governing memory policy: the managed Agent Memory block in your CLAUDE.md/AGENTS.md
names the policy document; follow its current permissions and instance routing. Then fix
ENTRYPOINT for the whole run:

| the policy says | ENTRYPOINT | consequences |
|---|---|---|
| a guarded entrypoint for one specific instance (for example a `mem-personal` wrapper that selects a private local KB) | that command | the wrapper selects the instance (no `MEM_KB_ROOT`); the commands it holds (typically `doctor`, `init`, `retry`, `pending`, `refresh`, `delete`) are not run and not worked around; its refusals are final |
| the ordinary CLI for an authorized instance | `mem`, against the instance the policy names (`MEM_KB_ROOT` only when the policy names that root) | the full CLI is available where the policy allows it |
| nothing readable, or no authorized route for this document | — | **stop and ask Brent** before any tool call or delegate; an unset instance is not permission to use a default instance, and a held instance is never a fallback |

Every `mem …` command in this skill AND every `mem …` command in the printed procedure runs as
`ENTRYPOINT …`. The complete mapping (the procedure uses exactly these forms):

- `mem extract …` → `ENTRYPOINT extract …`
- `mem dedup …` → `ENTRYPOINT dedup …`
- `mem get …` → `ENTRYPOINT get …`
- `mem save …` → `ENTRYPOINT save …`
- `mem doctor` → only where ENTRYPOINT permits it (step 2); held under a guarded entrypoint
- `mem init` → never from this skill; managed-block regeneration is a policy decision, not a preflight step

Policy restrictions override procedure examples: if the printed procedure names a command that
ENTRYPOINT holds, do the policy-permitted equivalent given here or stop — never fall back to bare
`mem`, a root override, or a different instance. Name the ENTRYPOINT and instance in your report.

## 1. Resolve the document

The argument is the document: a file path (relative paths resolve against the current
workspace) or, if it names something ambiguous, find it before starting. **No argument →
ask which document** and stop until answered. Confirm the file exists and is readable
before any other step.

## 2. Preflight — honest about what each check proves

1. **Runtime identity.** `ENTRYPOINT --version` must name the package or release the policy
   expects. Anything else → stop and say so. Under a guarded entrypoint a successful `--version`
   also means the wrapper validated its instance before dispatching (it refuses otherwise); that
   validation is the wrapper's evidence, not this skill's.
2. **Instance readiness** — the instance must exist, be a repository, carry no disallowed remote
   and have a working index:
   - Where ENTRYPOINT permits `doctor` (ordinary CLI): run `ENTRYPOINT doctor` against the
     instance you are extracting into, and only that one — it drains pending embeddings, which
     writes that instance's index. Must pass: kb-home, git-repo, no-remote, fts5, ollama,
     embed-model, embed-queue. Any failure → surface the doctor line(s) and stop. `blocks-*`
     staleness alone is non-blocking: note it; do not run `init` from this skill.
   - Under a guarded entrypoint that holds `doctor`: the wrapper's pre-dispatch validation
     (check 1) is the instance evidence. `ENTRYPOINT stats` is non-writing telemetry you may run,
     but its success proves nothing about the instance — the ordinary CLI's `stats` succeeds even
     when the KB is missing.
   - If neither the selected wrapper nor a policy-permitted check establishes the instance, stop
     before authoring any fan-out.
3. **Embedding daemon and model** — the dependency `extract` and `dedup` need:
   - Ordinary route: covered by `doctor` above (ollama, embed-model, embed-queue, fts5).
   - Under a guarded entrypoint: probe the daemon read-only through your own shell at the loopback
     endpoint the policy or wrapper configures (default `http://127.0.0.1:11434`): `GET /api/version`
     must answer, and `GET /api/tags` must list the configured embedding model (default
     `nomic-embed-text:v1.5`). These establish daemon and model presence; they do NOT check the
     instance's embed queue or FTS5, which only `doctor` can see. If the probe fails, stop before
     authoring any fan-out. If `dedup` or `extract` later refuse for a reason this preflight could
     not see, stop and report — do not drain, reindex or retry by hand.

Never store knowledge elsewhere as a workaround for a failed preflight.

## 3. Run the choreography

Run `ENTRYPOINT extract --procedure` and **follow the printed procedure exactly**, applying the
step-0 mapping to every command it names — it is the single source of truth for the fan-out
counts, fresh-eyes isolation rules, reviewer templates, and the final `ENTRYPOINT extract
--candidates` call. Non-negotiables it will hold you to, restated for emphasis:

- **Fresh eyes, twice** — extractors and reviewers are isolated subagents; only
  reviewer-approved candidates reach the CLI.
- **Approved vendors only** (DECISION_LOG D1): Claude and Codex subagents; never
  Gemini/Antigravity-backed agents. Cross-backend via agent-roster when available,
  inline subagents when not.
- **Dedup skips are reviewable**: the CLI names each skipped near-duplicate with its
  match and similarity. Adjudicate umbrella-vs-member cases (DECISION_LOG D3) — a
  distinct-but-related concept may be saved via direct `ENTRYPOINT save` with a `related:`
  backlink, and that override must be reported, never silent.
- **Safe updates only**: when step 4's adjudication folds a candidate into an existing card,
  read the card first (`ENTRYPOINT get <slug> --json`) and pass its `version` as
  `--expected-version` to `ENTRYPOINT save --update`; a refusal means re-read and reconcile,
  never a fresh-token retry.

Set expectations honestly: the run takes **minutes, not seconds** (DECISION_LOG D4) —
report progress as each stage completes.

## 4. Report

End with the added-vs-skipped report a human can read: the ENTRYPOINT and instance used; what
was added (slug + one-line description); what was skipped and why (named match + similarity);
any disposition-review overrides; anything rejected in review or invalid; any preflight limit
that applied (for example a guarded entrypoint's unverifiable queue state). If nothing was
added, say so plainly.
