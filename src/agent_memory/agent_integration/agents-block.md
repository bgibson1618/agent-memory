<!-- BEGIN AGENT-MEMORY BLOCK v1 - managed by `mem init`; edits inside will be overwritten -->
## agent-memory - persistent cross-agent knowledge base

`mem` is Brent's durable knowledge base (OKF markdown at `~/.agent-memory/`, local-only),
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
trivia): `mem save`. When unsure whether material is employer-proprietary, tag it
`sensitivity: work` - or don't save it. Work-tagged items appear marked `[work]` in
results; treat that marker as a handle-with-care signal. `--no-work` excludes
work-tagged items from search.
**Extract** knowledge from a document Brent supplies: `mem extract --procedure`
prints the choreography to follow (approved-vendor subagents only).

The KB is local-only: never add a git remote to `~/.agent-memory`; its content goes
nowhere but localhost Ollama. `mem doctor` diagnoses the setup.
<!-- END AGENT-MEMORY BLOCK -->
