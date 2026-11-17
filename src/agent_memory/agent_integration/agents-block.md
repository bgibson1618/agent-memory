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

**Search** before designing or explaining a topic Brent may have studied:
`mem search "<topic>" --json`; `mem get <slug> --json` for the full concept.
**Save** durable, reusable concepts (principles, techniques, findings - not session
trivia): `mem save`. Pass `--source "<citation>"` whenever the knowledge traces to a
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

Instances (D15): `MEM_KB_ROOT` points `mem` at an alternate KB instance (personal
projects set it in their env to route at the personal KB); unset = the default
work-adjacent KB. Never mix instances in one task; every rule here applies
per-instance.

The default and personal KBs use host-mediated saves when provisioned for shared
writes. Use native `mem save` and `mem extract`; never edit/commit their Markdown
directly. Before an update, read `mem get <slug> --json` and pass its `version` as
`mem save --update --slug <slug> --expected-version <version> ...`. A conflict requires
re-reading and reconciling; do not blindly overwrite with a new token. If a request
is pending, use `mem retry <operation-id>` with the original ID. `mem pending`
lists outstanding requests. An offline request is pending, not confirmed saved.

KB content stays between Brent's Linux laptop and work-host through the exact
private endpoints in `.allowed-remotes`, never GitHub or personal cloud storage.
Indexes and usage/dedup logs stay on their respective machines. Shared saves and
explicit `kb-sync` do not authorize hooks, background jobs, freshness checks, or
other destinations. `mem doctor` diagnoses the setup.
<!-- END AGENT-MEMORY BLOCK -->
