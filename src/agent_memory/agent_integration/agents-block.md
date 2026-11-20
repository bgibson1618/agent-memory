<!-- BEGIN AGENT-MEMORY BLOCK v1 - managed by `mem init`; edits inside will be overwritten -->
## agent-memory - persistent cross-agent knowledge base

`mem` is Brent's durable knowledge base (OKF markdown, private; the project's
configured instance — default root `~/.agent-memory/`),
shared by his coding agents. Use it silently during ordinary work.

**Vendor policy (non-negotiable, DECISION_LOG D1):**
- Approved for memory work: Claude (Anthropic) and Codex (OpenAI) agents, including
  recall of `[work]`-marked items.
- Antigravity / Gemini-backed agents are excluded from memory work entirely: do not run
  `mem`, do not read `~/.agent-memory/`, and do not accept delegated tasks that touch
  the KB. Google is not an approved vendor.

**Search at the start of non-trivial work**, before diagnosing or designing:
`mem search "<topic>" --json` for the task's main subject (the tool, library, format,
service or concept involved); `mem get <slug> --json` for a relevant hit. Check a hit's
stated conditions (versions, environment, evidence) against the current task before
relying on it; when they differ, treat it as a lead to verify, not an answer.
**Save before you finish** when the task established something another project could
use: a confirmed behaviour of a tool, library, format or external service, a technique
that worked, or the general cause of a bug. A single tested observation is worth saving
when you state it as one: what happened, the conditions (versions, inputs, environment)
and the evidence (the test, command or source). Keep the conclusion within that
evidence; generalize only when a checked source or broader test supports it, and label
anything else as a hypothesis. Facts that matter only to this project belong in the
project's own notes. Search before saving and update an existing concept rather than
adding a near-duplicate: `mem save`. Pass `--source "<citation>"` whenever the knowledge traces to a
paper, book, doc, or person (an omitted source records as `ambient`). When unsure
whether material is employer-proprietary, tag it
`sensitivity: work` - or don't save it. Work-tagged items appear marked `[work]` in
results; treat that marker as a handle-with-care signal. `--no-work` excludes
work-tagged items from search. `sensitivity: sensitive` (D16) marks PII/PHI: prefer
not saving identifying details at all; when kept, items are marked `[sensitive]`
(`--no-sensitive` excludes) - do not quote them onward.
**Credence (type):** search marks non-`concept` types `[<type>]`. `type: concept` is
vetted knowledge; `type: position` is a named expert's/school's stance — cite it in
attributed voice ("Fish holds…"), never as fact; `type: sb-position` is a Superbuilders
project's working hypothesis — cite it as that project's stance; `type: sb-project` is a
project reference card; `type: reference` is a descriptor of an artifact/standard/index —
quote it as what the artifact specifies with its version/date, never as vetted knowledge.
Pass `--type concept` to ground a claim only in vetted knowledge.
**Extract** knowledge from a document Brent supplies: `mem extract --procedure`
prints the choreography to follow (approved-vendor subagents only; it includes a
`mem dedup` pass on the reviewer survivors, adjudications recorded, before `mem extract`).

**Update safely:** read first, `mem get <slug> --json`, and pass its `version` as
`mem save --update --slug <slug> --expected-version <version> ...`. A missing or
stale version is refused with nothing written: re-read, reconcile, resubmit with the
new version; never retry blindly with a fresh token. On an instance provisioned for
host-mediated shared writes the same command may report `pending` or `conflict`;
`mem pending` lists unresolved requests, `mem retry <operation-id>` resends an exact
request, and a pending request is not a confirmed save.

Instances (D15): `MEM_KB_ROOT` points `mem` at an alternate KB instance (personal
projects set it in their env to route at the personal KB); unset = the default
work-adjacent KB. Never mix instances in one task; every rule here applies
per-instance.

The KB's only permitted remotes are the exact URLs listed in its `.allowed-remotes`
file (one per line; D1); never a public, vendor or personal-cloud remote, for any
instance; its content goes nowhere but those listed machines and localhost Ollama.
`mem doctor` diagnoses the setup.
<!-- END AGENT-MEMORY BLOCK -->
