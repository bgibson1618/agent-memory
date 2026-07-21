The feature ledger is well-aligned with product intent and system architecture overall, but contains minor dependency gaps, proof-method bundling mismatches, and test fixture ambiguities that should be amended before build execution.

### FINDINGS

1. **CITATION:**
   - `file:///home/brent-gibson/projects/agent-memory/ARCHITECTURE.md#L30-L31`: "**`mem init` owns setup**: creates `~/.agent-memory` + git init, verifies Ollama/models/FTS5, and installs/refreshes the agent-integration instruction blocks into the global `CLAUDE.md`/`AGENTS.md` (managed marker section); `mem doctor` re-checks all of it"
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L23-L24`: "`mem init` on a machine without a KB creates `concepts/`, `.index/`, and an initialized git repo with **zero remotes configured**; a second run is a no-op that exits 0 (idempotent)."
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L180-L186`: "`mem init` installs managed instruction blocks into the global `CLAUDE.md` and `AGENTS.md`... `mem init` installs/refreshes clearly-delimited managed blocks in the global `CLAUDE.md` and `AGENTS.md`; re-running updates in place with no duplicate blocks."
   **ANCHOR:** certain
   **WHY IT MATTERS:** `mem init` setup logic is split across F1 (at the root of the dependency tree) and F11 (at the tail of the tree). Building F1 without block installation creates an incomplete `mem init` command. Furthermore, block installation logic (`CLAUDE.md`/`AGENTS.md` file mutation and marker rendering) is a deterministic CLI capability that should be verified via automated unit testing (`test`), but F11 assigns `Proof: observed` to the entire feature, leaving the block insertion code unverified by automated tests.
   **DISPOSITION SUGGESTION:** amend (Move the instruction block installation criteria and automated `test` proof into F1 alongside `mem init` setup, or create a small `test`-proven feature for instruction block installation before F11; reserve F11 strictly for observing live, unprompted agent behavior).

2. **CITATION:**
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L195`: "- **Depends on:** F6, F9"
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L201`: "An automated socket-level guard runs save / search / get / list / extract / reindex and asserts zero connections to any non-localhost address."
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L133-L140`: "F8 — External-edit resilience ... `mem reindex` rebuilds the entire index from markdown alone..."
   **ANCHOR:** certain
   **WHY IT MATTERS:** F12's automated test suite explicitly executes `mem reindex` under the socket-level egress guard, but F12 does not include F8 (which implements and tests `mem reindex`) in its `depends_on` list. In a parallel build, an orchestrator could schedule F12 to run as soon as F6 and F9 finish, before F8 is implemented, causing F12's test suite to fail when invoking `mem reindex`.
   **DISPOSITION SUGGESTION:** amend (Update F12's `depends_on` field to include `F8`, changing it to `- **Depends on:** F6, F8, F9`).

3. **CITATION:**
   - `file:///home/brent-gibson/projects/agent-memory/ARCHITECTURE.md#L46`: "  └─ graph leg:   seed from lexical∪vector hits → 1–2-hop expansion, link-weighted"
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L105-L106`: "A concept findable by only one leg (lexical-only, semantic-only, and graph-only fixtures) still surfaces in fused top-k — the fuse-all property the capstone proved."
   **ANCHOR:** firm
   **WHY IT MATTERS:** Per `ARCHITECTURE.md`, the graph leg requires seed hits from lexical or vector search to perform 1–2-hop expansion. If a test author sets up an isolated "graph-only fixture" concept that matches neither keyword nor semantic search, zero seed hits are returned, making graph expansion impossible. Without specifying that the graph fixture requires a matching seed neighbor, the test setup will be ambiguous or fail.
   **DISPOSITION SUGGESTION:** amend (Clarify in F6 success criteria that the "graph-only fixture" test setup consists of a query matching a seed concept via lexical/semantic search, which then surfaces a neighboring non-keyword/non-semantic concept strictly via 1-hop graph expansion).

4. **CITATION:**
   - `file:///home/brent-gibson/projects/agent-memory/ARCHITECTURE.md#L63-L65`: "**Bounded opportunistic queue drain**: any `mem` invocation, after its primary work, drains up to ~3 queued embeds iff Ollama answers a fast health check — never blocking the caller's budget; `mem doctor`/`mem reindex` drain fully."
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L72-L74`: "Save with Ollama down: the save exits 0 in under a second, the embedding is queued, and after the daemon returns a later `mem` invocation drains the queue — the concept becomes semantically findable with **no manual reindex**."
   **ANCHOR:** firm
   **WHY IT MATTERS:** `ARCHITECTURE.md` explicitly caps opportunistic queue draining to ~3 items per invocation to protect agent response latencies. If F4's test suite enqueues a large batch (>3 items) while Ollama is down and expects a single subsequent `mem` invocation to drain the entire queue, the test will fail against a compliant implementation. Conversely, if an implementer removes the ~3-item limit to pass a batch test, agent execution latencies will be compromised.
   **DISPOSITION SUGGESTION:** amend (Update F4's success criteria to explicitly state that opportunistic queue drain is bounded to ~3 items per invocation, and verify both that 1–3 items drain on an ordinary invocation and that full queue drain occurs under `mem reindex` or `mem doctor`).

5. **CITATION:**
   - `file:///home/brent-gibson/projects/agent-memory/ARCHITECTURE.md#L111-L114`: "**Dedup threshold** — the cosine-similarity line between 'near-duplicate, skip' and 'distinct, save' must be calibrated empirically during build (capstone D024: lexical similarity alone provably cannot separate these; a real embedder changes the calculus but not the need to measure). Becomes a DECISION_LOG entry with data."
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L145`: "- **Proof:** `test` (candidate fixtures: novel saved, near-dups skipped, dispositions reported)"
   - `file:///home/brent-gibson/projects/agent-memory/FEATURES.md#L155-L156`: "The dedup similarity threshold is a named configuration value whose chosen value carries recorded calibration evidence (measured, not guessed — the capstone D024 lesson)."
   **ANCHOR:** firm
   **WHY IT MATTERS:** Unit testing (`test`) validates deterministic CLI behavior given a configured threshold value, but cannot perform empirical calibration on embedding distributions or produce a `DECISION_LOG` entry. Lumping empirical calibration into a feature acceptance criterion risks an implementer hardcoding an uncalibrated default threshold to pass synthetic unit test mocks, skipping the required empirical measurement and DECISION_LOG artifact.
   **DISPOSITION SUGGESTION:** amend (Explicitly separate empirical threshold calibration into a documented pre-build/early-build calibration step or pre-requisite task in the ledger, keeping F9 focused on proving deterministic CLI execution with configured thresholds).

### NOTES

- **Obsidian Graph Rendering Verification:** F5 and PRD Section 7 Criterion 6 highlight opening the KB directory in Obsidian for native wikilink rendering (`[[slug]]`). While F5 verifies standard `[[slug]]` syntax in generated files via automated tests, full visual graph rendering in Obsidian is an external UI observation that sits outside automated unit tests.
- **Environment & Hardware Assumptions:** INTAKE.md and NFR_UX.md note WSL2 Ubuntu with RTX 3070 CUDA passthrough. F4 and F12 test fallback semantics and localhost socket bounds, but GPU vs CPU performance limits under heavy embedding workloads remain environmental variables to verify during initial runs.
