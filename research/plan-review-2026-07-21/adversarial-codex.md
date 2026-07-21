The plan is coherent and close to buildable, but through an adversarial lens it overstates several guarantees before pinning their proof boundaries, especially confidentiality, extraction, graph scale, and provider-neutral agent behavior.

FINDINGS

1. Recall-time confidentiality is treated as settled without a safe ambient-agent boundary.
   CITATION - `NFR_UX.md:33-38`: "search **includes** `work`-tagged items by default with a visible `[work]` marker in output; a `--no-work` flag excludes them for cautious contexts." / "Recall-time exposure (retrieved content entering an agent's vendor context) is accepted and equivalent to typing it; the `[work]` marker keeps that judgment visible." Also `FEATURES.md:187-191`: "a fresh Claude Code session in a *different project*, doing ordinary work that touches a learned topic, queries `mem search` unprompted and uses the result in its answer." / "the agent saves at least one durable concept unprompted".
   ANCHOR - firm.
   WHY IT MATTERS - The plan's zero-egress guarantees cover the local CLI path, but the intended ambient behavior can still place `work` memories into a model-vendor context by default and without an explicit per-use human decision.
   DISPOSITION SUGGESTION - amend: define the agent-integration rule for `work` items before build, e.g. ambient sessions default to `--no-work` unless the backend/context is explicitly approved, or record a conscious acceptance of automatic recall-time vendor exposure.

2. The zero-egress test claims "all operations" but omits two shipped CLI commands.
   CITATION - `FEATURES.md:197-204`: "no memory operation can send content anywhere but localhost" / "An automated socket-level guard runs save / search / get / list / extract / reindex" / "With Ollama up, the same guard asserts the only network peer is the local Ollama endpoint." Also `ARCHITECTURE.md:30`: "`mem` entry point: `init · save · search · get · list · extract · reindex · doctor`".
   ANCHOR - certain.
   WHY IT MATTERS - `init` and `doctor` are memory operations in the architecture, and they touch setup, model checks, and global instruction files. A build could satisfy F12 while leaving those commands outside the confidentiality proof.
   DISPOSITION SUGGESTION - amend: either include `mem init` and `mem doctor` in the socket-level guard, or narrow the claim from "all operations" to the listed storage/index/read operations.

3. The no-remote confidentiality invariant is only proven at initialization.
   CITATION - `PRD.md:98-100`: "KB data lives at `~/.agent-memory/` — a dedicated directory that is itself a git repo with **no remote**" / "Never inside this code repo; never pushed to a personal remote." Also `FEATURES.md:23-27`: "`mem init` on a machine without a KB creates `concepts/`, `.index/`, and an initialized git repo with **zero remotes configured**" / "`mem doctor` reports pass/fail per check — Ollama reachable, embedding model present with expected dimensions, FTS5 available".
   ANCHOR - firm.
   WHY IT MATTERS - If a remote is added later by accident, the plan does not require `doctor`, `save`, or `extract` to detect it. The strongest storage confidentiality claim can silently decay after F1 passes.
   DISPOSITION SUGGESTION - amend: add an invariant test where a remote is injected after init; require `mem doctor` to fail clearly and write operations to refuse or warn until the remote is removed.

4. Shared-topic graph edges contradict the stated 10k-concept scale assumption.
   CITATION - `FEATURES.md:84-90`: "`[[wikilinks]]`, `related:` frontmatter, and shared topics become graph edges" / "Body `[[wikilinks]]`, frontmatter `related[]`, and shared topics all yield edges". Also `NFR_UX.md:19-20`: "v1 ceiling **10,000 concepts** (~50k graph edges)."
   ANCHOR - firm.
   WHY IT MATTERS - Pairwise edges for shared topics can become quadratic. One broad tag on thousands of concepts can exceed the entire 50k-edge assumption by orders of magnitude, undermining traversal cost and test fixtures.
   DISPOSITION SUGGESTION - amend: model topics as virtual tag nodes or query-time expansions rather than materialized pairwise edges, or specify edge caps/scoring rules that preserve the 50k target.

5. The extract-performance requirement targets `mem extract` "per document", but the architecture makes `mem extract` candidate-JSON only.
   CITATION - `NFR_UX.md:16-18`: "`mem extract` < 60 s per document, with progress reported." `ARCHITECTURE.md:29`: "`extract` | The **deterministic half** of extract-knowledge: candidate concepts (JSON) in → validate → embed → dedup vs KB → save novel → report added/skipped/near-dup". `FEATURES.md:152-154`: "`mem extract --candidates <json>` with a mix of novel and near-duplicate candidates saves the novel ones, skips the near-dups, and reports every candidate's disposition".
   ANCHOR - firm.
   WHY IT MATTERS - Builders can honestly disagree whether v1 needs a document-ingesting CLI with progress or only an agent-side procedure that eventually feeds candidates to the CLI.
   DISPOSITION SUGGESTION - amend: rename the NFR target to "extract-knowledge procedure <60s per document" or add an explicit `mem extract <document>` feature with progress semantics.

6. OKF validity is required before the OKF source/licensing posture is resolved.
   CITATION - `FEATURES.md:39-40`: "`mem save` with title/body/topics writes a valid OKF file (frontmatter: id/slug, title, description, type, `topics[]`, `sensitivity`, timestamps)". `ARCHITECTURE.md:24`: "`okf` | The OKF schema contract: frontmatter (id/slug, title, description, type, `topics[]`, `sensitivity`, timestamps, `related[]`) + body with `[[wikilinks]]`". `ARCHITECTURE.md:118-119`: "**OKF porting posture** — check the capstone repo's license before porting `okf.py`-style code; otherwise clean-room the schema from the format spec."
   ANCHOR - firm.
   WHY IT MATTERS - F2 is the trunk feature, but "valid OKF" can become circular if the schema, fixtures, and reuse/clean-room boundary are decided during implementation instead of before it.
   DISPOSITION SUGGESTION - amend: add a pre-F2 decision or F0 task that freezes the OKF field contract, validation fixtures, and license/clean-room posture.

7. Dedup calibration is required, but the plan does not define what evidence is sufficient.
   CITATION - `FEATURES.md:152-156`: "`mem extract --candidates <json>` with a mix of novel and near-duplicate candidates saves the novel ones, skips the near-dups" / "The dedup similarity threshold is a named configuration value whose chosen value carries recorded calibration evidence (measured, not guessed — the capstone D024 lesson)." `ARCHITECTURE.md:111-114`: "the cosine-similarity line between \"near-duplicate, skip\" and \"distinct, save\" must be calibrated empirically during build".
   ANCHOR - firm.
   WHY IT MATTERS - A tiny fixture can be tuned to its own threshold and still satisfy the wording. The feature can pass while failing on real near-duplicate documents.
   DISPOSITION SUGGESTION - amend: require a durable calibration artifact with representative examples, chosen metric, threshold, false-positive/false-negative review, and the DECISION_LOG entry that records it.

8. Provider-neutral ambient awareness is claimed, but the feature proof only observes Claude Code.
   CITATION - `PRD.md:59-62`: "delivered both for Claude Code (global `CLAUDE.md`/skill) and as a provider-neutral `AGENTS.md` block so codex/agy delegates get the same ambient awareness (same content, two files)." `FEATURES.md:187-189`: "a fresh Claude Code session in a *different project*, doing ordinary work that touches a learned topic, queries `mem search` unprompted and uses the result in its answer."
   ANCHOR - firm.
   WHY IT MATTERS - The build can pass F11 while only proving Claude behavior, leaving the codex/agy "same ambient awareness" claim untested.
   DISPOSITION SUGGESTION - amend: either add observed codex/agy acceptance checks, or reword v1 to claim AGENTS.md installation only, not proven ambient behavior outside Claude Code.

9. External-edit resilience does not prove semantic refresh after direct disk edits.
   CITATION - `FEATURES.md:129-141`: "direct file edits reflected on next read; reindex rebuilds equivalently" / "A concept file edited directly on disk is reflected in lexical search on the very next `mem search`; its embedding refresh is enqueued automatically." / "`mem reindex` rebuilds the entire index from markdown alone; results for unchanged content are equivalent before and after." Also `ARCHITECTURE.md:59-65`: "every read command starts with a fast scandir sweep" / "embeddings enqueued" / "any `mem` invocation, after its primary work, drains up to ~3 queued embeds iff Ollama answers a fast health check".
   ANCHOR - firm.
   WHY IT MATTERS - The criteria prove lexical freshness and queue creation, but not that stale vectors are replaced and semantic search reflects the edited/new file after Ollama returns.
   DISPOSITION SUGGESTION - amend: add a direct-edit semantic fixture that changes meaning without shared keywords, verifies queue drain, and asserts the new embedding is used without manual `reindex`.

10. The CLI surface is both "fixed" and still "open" in the discovery set.
   CITATION - `PRD.md:57`: "The `mem` CLI: save / search / extract / list (exact surface fixed at architecture)." `PRD.md:109`: "Exact `mem` subcommand surface and flags (architecture decides)." `NFR_UX.md:105`: "Exact `mem` subcommand surface and flags — architecture decides." `ARCHITECTURE.md:30`: "`mem` entry point: `init · save · search · get · list · extract · reindex · doctor`".
   ANCHOR - certain.
   WHY IT MATTERS - The docs disagree on whether the command set is settled; flags remain unspecified even though feature tests depend on `--json`, `--update`, `--related`, `--no-work`, and `--candidates`.
   DISPOSITION SUGGESTION - amend: remove the stale open questions or split them into "subcommands settled; exact flag grammar still open" with the flag list the build must implement.

NOTES

- I did not inspect referenced research or capstone artifacts because this run was scoped to the five named discovery files; any claim whose only support is outside those files was treated as unsupported within this review surface.
- `FEATURES.md` is currently untracked in the workspace (`git status --short` showed `?? FEATURES.md`). If the build runner consumes tracked state only, confirm the orchestrator uses this exact ledger.
