<!-- BEGIN AGENT-MEMORY BLOCK v1 - managed by `mem init`; edits inside will be overwritten -->
## agent-memory - persistent cross-agent knowledge base

`mem` is Brent's durable knowledge base (OKF markdown at `~/.agent-memory/`, local-only).
Use it silently during ordinary work; never narrate it or ask permission.

**Search it** when a task touches a concept Brent may have studied before (design
choices, teaching/learning science, tooling patterns): `mem search "<topic>" --json`,
then `mem get <slug> --json` for the full concept. No relevant hit: proceed normally.

**Save to it** when a session yields a durable, reusable concept (a principle,
technique, or hard-won explanation - not session trivia or project-local facts):
`mem save`. Claude Code's built-in memory keeps operational/session facts; the KB owns
durable knowledge - keep pointers between them, never duplicated content.

**Extract from a document** when Brent points you at a paper, article, or doc to
mine for the KB: run `mem extract --procedure` and follow the printed choreography
(fresh-eyed extractor fan-out, fresh-eyed review, then `mem extract`).

**Confidentiality (non-negotiable):**
- `sensitivity: work` marks employer-specific material ONLY; general knowledge learned
  on the job is normal sensitivity. When unsure whether material is
  employer-proprietary, tag it `work` - or don't save it.
- The KB is local-only: never add a git remote to `~/.agent-memory`; its content goes
  nowhere but localhost (Ollama embeddings). `[work]`-marked results may be used in
  Claude and Codex contexts only (approved vendors: Anthropic, OpenAI).
- `mem doctor` diagnoses the setup; if it fails, surface the failure - never store
  knowledge elsewhere as a workaround.
<!-- END AGENT-MEMORY BLOCK -->
