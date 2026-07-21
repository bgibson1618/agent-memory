# NFR / UX-Feel — agent-memory

> Non-functional requirements and the intended *feel* of the UX. The companion to `PRD.md`
> (what the product does); this captures **how well** it must do it and **how it should feel**.
> Authored by `/kodos:nfr-ux`. Feeds `/kodos:architect`.

- **Project type:** Headless CLI (`mem`) + Python library — agent-first, no human-facing UI beyond terminal output
- **Source:** `PRD.md`
- **Last updated:** 2026-07-21

---

## Part A — Non-Functional Requirements

### Performance
- **Targets:** fused `mem search` < 1 s end-to-end with the Ollama daemon warm; < 3 s worst-case
  cold. `mem save` perceived < 1 s (embedding may complete asynchronously). `mem extract` < 60 s
  per document, with progress reported. Derived-graph load < 5 ms cached / < 250 ms cold parse.
- **Scale assumptions:** v1 ceiling **10,000 concepts** (~50k graph edges). Single user; a
  handful of concurrent agent sessions at most.
- **Degradation posture:** graceful, never blocking — Ollama down ⇒ saves land (embedding queued),
  search degrades to lexical + graph with a one-line warning. Memory ops must never stall an
  agent's session.

### Security & Privacy
- **Sensitive data:** personal learning notes; some may derive from employer context. A
  per-memory `sensitivity` field marks `work` items.
- **AuthN / AuthZ:** n/a — single local user on a personal machine.
- **Data handling:** all data at rest as plain files under `~/.agent-memory/` (a local git repo
  with **no remote**). **Zero network egress on the storage/index/search path** except localhost
  Ollama — provable by the offline test (PRD criterion 5). No encryption at rest (OS/disk
  encryption is the platform's job). Memories persist until deleted; no auto-expiry.
- **Sensitivity semantics (confirmed):** search **includes** `work`-tagged items by default with
  a visible `[work]` marker in output; a `--no-work` flag excludes them for cautious contexts.
- **Threat posture:** the realistic threat is **egress** (confidential content leaving the
  machine), not intrusion. Out of scope: local adversaries, multi-user isolation, at-rest
  encryption. Recall-time exposure (retrieved content entering an agent's vendor context) is
  accepted and equivalent to typing it; the `[work]` marker keeps that judgment visible.

### Reliability & Availability
- **Uptime / availability target:** best-effort local tool; must work fully offline.
- **Failure handling:** the markdown store is the only irreplaceable state. Writes are atomic;
  concurrent agent sessions are safe via atomic writes + file locks (one concept per file, so
  no merge surface). Vector + graph indexes are **derived and rebuildable** (`mem reindex`) —
  index corruption means rebuild, never data loss. Embedding failures queue and retry; a save
  never fails because the embedder is down.
- **Backups / durability (confirmed):** every write **auto-commits to the local git repo** at
  `~/.agent-memory/` — free history, diffs, and undo. Off-machine backup remains a manual,
  Brent-owned concern (no remote allowed).

### Environment & Constraints
- **Runtime / platform:** WSL2 Ubuntu (`/home/...` side only); Python 3.12+ via `uv`.
  RTX 3070 8 GB available to Ollama via WSL2 CUDA passthrough.
- **Toolchain:** `uv`, `pytest` (`uv run pytest` is the verification command), `git`, Ollama
  (systemd service; `OLLAMA_KEEP_ALIVE` pinned so the embedder stays warm).
- **Deployment / distribution:** installed from this repo via `uv tool install` (editable), so
  `mem` is on PATH for every shell and agent. No packaging/publishing in v1.
- **External dependencies & limits:** Ollama with `nomic-embed-text:v1.5` (default; `num_ctx`
  set explicitly — packaging defaults to 2K) and optionally `qwen3-embedding:0.6b` (step-up).
  Model tag + digest + dimensions stamped into index metadata; mixed-dimension writes refused.
  Cost ceiling: $0 — nothing paid anywhere in the system.
- **Compliance / licensing:** employer-confidentiality rule (no work material to personal
  remotes or non-approved vendors) is a hard design input; all chosen components are
  open-source (Apache-2.0 / MIT / PSF) — no copyleft or SSPL dependencies.

### Accessibility
n/a — headless CLI; no human-facing UI beyond terminal text. (Output readability is covered in
Part B.)

---

## Part B — UX Feel (trimmed for headless CLI)
<!-- BEGIN UX-FEEL — trimmed: command ergonomics, output readability, error tone only. -->

> Primary "user" is an agent; secondary is Brent at a terminal. Everything below serves the
> north star: **almost invisible**.

### Tone & Personality
- **In three words:** quiet, fast, trustworthy.
- **Voice:** terse, factual, zero decoration — `git`-plumbing energy. Single-line confirmations
  (`saved: spaced-repetition-effect [learning-science]`).
- **Feeling on first use:** "it just worked and got out of the way."

### Interaction Feel (CLI ergonomics)
- **Never interactive:** no prompts, ever — an agent can't answer them. Meaningful exit codes
  (0 ok / non-zero distinct per failure class). Destructive operations require an explicit flag.
- **Output contract:** human-readable terse by default; **`--json` on every read command** —
  agents get structure now, and it becomes the MCP seam later.
- **Errors:** one line — what failed and what to do next. Never a stack trace at the user.
  Degraded modes warn once, then proceed.

### Reference Products
- **Like:** `git` — terse, composable, trustworthy, scriptable; trusted enough that agents call
  it reflexively.
- **Unlike:** chatty CLIs, interactive wizards, anything that narrates itself — attention spent
  on the tool is attention stolen from the work.

<!-- END UX-FEEL -->

---

## Open Questions
- Dedup similarity thresholds for extract-knowledge — calibrate empirically during build
  (capstone D024: lexical similarity alone cannot separate near-dups).
- Exact `mem` subcommand surface and flags — architecture decides.
