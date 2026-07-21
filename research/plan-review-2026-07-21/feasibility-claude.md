# Pre-build feasibility review — agent-memory (fresh eyes, plan only)

**Overall reading:** This is a buildable, unusually well-evidenced plan — settled design with
cited capstone data, a gate record already folded in — but its proof layer has real seams: two
features' declared proofs cannot observe what they claim (F12's socket guard vs. subprocess git;
F9's "calibration evidence" under `test`), one dependency edge is missing (F12 exercises
`reindex`, which F8 owns), and the entire test suite's true root — a provisioned Ollama with the
model pulled — belongs to no feature. All fixable on paper before the build loop starts.

---

## FINDINGS

### 1. Ollama provisioning is nobody's deliverable, yet the test suite's root prerequisite

- **CITATION:** `INTAKE.md:61` — "Host: WSL2 Ubuntu laptop, RTX 3070 (8 GB VRAM), 19 GB RAM.
  **Ollama not yet installed.**" vs. `FEATURES.md:25-27` (F1) — "`mem doctor` reports pass/fail
  per check — Ollama reachable, embedding model present with expected dimensions, FTS5
  available" and `FEATURES.md:70-72` (F4) — "A query sharing no keywords with a stored concept
  returns that concept in the vector leg's top-k, machine-asserted with a paraphrase fixture."
- **ANCHOR:** firm. (The absence is verified live: `curl localhost:11434/api/version` fails on
  this host today, 2026-07-21. What's judgment is whether provisioning must be a feature vs. a
  preflight step — but *nothing in the five artifacts assigns it to either*.)
- **WHY IT MATTERS:** F1's doctor "pass" checks, F4's real-embedding paraphrase fixture, F6's
  warm-path fusion, and F12's "with Ollama up" guard all require an installed daemon with
  `nomic-embed-text:v1.5` pulled and `num_ctx` configured. No feature delivers that, and the
  dependency graph calls F1 "the sole root" (`FEATURES.md:208`). First `uv run pytest` on the
  real machine fails on environment, not code — and the build loop can't distinguish "feature
  broken" from "host unprovisioned," burning attempts against the wrong cause.
- **DISPOSITION SUGGESTION:** amend — either add an F0 (environment provisioning: Ollama
  installed as systemd service, models pulled, `num_ctx` set, proved by `mem doctor`-style
  probe) or explicitly assign provisioning to `/kodos:preflight` in FEATURES.md's preamble with
  the Ollama/model checks named, so the gate is crossed before F1 is attempted.

### 2. F12's "socket-level guard" cannot see subprocess egress as specced — and git runs as a subprocess

- **CITATION:** `FEATURES.md:201-204` (F12) — "An automated socket-level guard runs save /
  search / get / list / extract / reindex and asserts zero connections to any non-localhost
  address … The guard runs inside `uv run pytest`" vs. `ARCHITECTURE.md:85` — "git (system
  binary, **via subprocess**)".
- **ANCHOR:** firm. (If "socket-level guard" means the standard in-process mechanism —
  pytest-socket / monkeypatched `socket.connect` — the gap is certain; the tentative escape is
  that the author intends an OS-level mechanism like a network namespace, but no artifact says
  so.)
- **WHY IT MATTERS:** An in-process socket guard only observes the Python interpreter's own
  sockets. Every `mem save` shells out to `git`, and the guard is blind to anything a
  subprocess does — precisely the seam where an egress regression (a hook, a misconfigured
  remote, a future helper binary) would live. F12 is the *permanent machine enforcement* of the
  project's one hard confidentiality line (`NFR_UX.md:30-32`); a guard that structurally cannot
  observe the subprocess path proves less than its success criterion claims, silently.
- **DISPOSITION SUGGESTION:** amend — spec the mechanism: run the guard suite inside an
  isolated network namespace with only loopback up (`unshare -n` + `ip link set lo up`, cheap
  on WSL2), which covers subprocesses for free and doubles as PRD success criterion 5's
  "networking disabled" offline test. Keep the in-process guard as the fast inner layer if
  desired, but the namespace run is the one that proves the claim.

### 3. F12 exercises `mem reindex` but does not depend on F8, which owns it

- **CITATION:** `FEATURES.md:201-202` (F12) — "runs save / search / get / list / extract /
  **reindex**" with `FEATURES.md:195` — "**Depends on:** F6, F9" vs. `FEATURES.md:140-141`
  (F8) — "`mem reindex` rebuilds the entire index from markdown alone."
- **ANCHOR:** firm. (`reindex`'s success criteria live only in F8; F8 is not in F12's
  `depends_on` and is not transitively implied — F8 and F12 are declared parallel at the tail,
  `FEATURES.md:211-213`.)
- **WHY IT MATTERS:** The ledger says `depends_on` drives build order and parallelism
  (`FEATURES.md:10`). The scheduler may legally start F12 before F8 exists, at which point
  F12's guard either fails on a missing subcommand (wasted attempts) or is written against a
  stub `reindex` and must be reopened when F8 lands. (The rest of F12's list is covered:
  save/get/list via F2⇐F9, search via F6, extract via F9.)
- **DISPOSITION SUGGESTION:** amend — add F8 to F12's `depends_on` (one line), or drop
  `reindex` from F12's operation list and note why. The former is truer to intent: the egress
  guard should cover the full command surface.

### 4. Daemon-state-dependent tests need an endpoint/test seam no artifact provides

- **CITATION:** `FEATURES.md:72-77` (F4) — "Save with Ollama down: the save exits 0 … after
  the daemon returns a later `mem` invocation drains the queue — … no manual reindex";
  "a hung daemon results in enqueue, never a stalled save"; `FEATURES.md:28-29` (F1) — "With
  Ollama stopped, `mem doctor` says exactly that in one line"; `FEATURES.md:109-110` (F6) —
  "With Ollama down, fused search still answers." The architecture's Ollama row
  (`ARCHITECTURE.md:81`) fixes the daemon as systemd-managed localhost but specifies no
  configurable endpoint anywhere.
- **ANCHOR:** firm.
- **WHY IT MATTERS:** These are `test`-proofed criteria requiring three daemon states — up,
  down, and *hung* — inside `uv run pytest`. A test suite cannot (and must not) stop the real
  systemd service; the standard solution is an endpoint override (env var / config) pointed at
  a closed port (down) or a stalling fake server (hung). No component in ARCHITECTURE.md owns
  configuration at all — no config file, no env-var contract. Without that seam, the
  implementer either invents one ad hoc mid-feature (unreviewed surface area on the
  confidentiality-critical network path) or writes tests that mock the client and prove
  nothing about real timeout/queue behavior.
- **DISPOSITION SUGGESTION:** amend — add one line to ARCHITECTURE.md's `index.vector` or
  Environment section: the Ollama base URL is overridable (e.g. honor `OLLAMA_HOST` or a
  `MEM_OLLAMA_URL` env var), default `localhost:11434`, and name it the sanctioned test seam.
  The same amendment should note tests run against an isolated `HOME`/KB root so they never
  touch the real `~/.agent-memory` or the real global `CLAUDE.md`.

### 5. F9's "recorded calibration evidence" criterion is not provable by its declared proof method

- **CITATION:** `FEATURES.md:144` (F9) — "**Proof:** `test`" vs. `FEATURES.md:155-156` — "The
  dedup similarity threshold is a named configuration value whose chosen value carries recorded
  calibration evidence (measured, not guessed — the capstone D024 lesson)."
- **ANCHOR:** firm.
- **WHY IT MATTERS:** A pytest run can assert the threshold is a named config value and that
  fixtures dedup correctly at that value; it cannot assert that the *number was chosen from
  measurement* — that's a DECISION_LOG/human-judgment property (`ARCHITECTURE.md:111-114`
  itself says it "becomes a DECISION_LOG entry with data"). As written, either the build loop
  marks F9 proved on tests that don't cover this criterion (criterion silently unproved), or
  an honest verifier can never mark F9 proved by `test` alone (feature wedged).
- **DISPOSITION SUGGESTION:** amend — split the criterion: keep the machine half under `test`
  ("threshold is a named config; fixture batch dedups correctly at the shipped value") and move
  the evidence-recorded half to a `sign-off` clause or an explicit "DECISION_LOG entry exists
  with measurements" check named as such.

### 6. F10/F11's `observed` proofs hinge on *unprompted* behavior with no defined observation protocol

- **CITATION:** `FEATURES.md:186-191` (F11) — "a fresh Claude Code session in a *different
  project*, doing ordinary work that touches a learned topic, queries `mem search` unprompted
  and uses the result in its answer … the agent saves at least one durable concept unprompted";
  similarly `FEATURES.md:169-171` (F10) — "an actual Claude Code session invoking the shipped
  procedure on a real document, not a scripted harness."
- **ANCHOR:** firm.
- **WHY IT MATTERS:** These are the right criteria — invisibility genuinely can't be proved by
  a scripted harness — but as written the proof is unbounded and undefined: which project, what
  counts as "ordinary work," whether staged-but-not-prompted scenarios are allowed, how many
  sessions before a non-observation counts as failure. The failure mode is either an
  indefinitely blocked closeout (waiting for spontaneous behavior) or quiet goalpost-softening
  at observation time (a prompt that nudges toward `mem`, which un-proves invisibility).
- **DISPOSITION SUGGESTION:** amend — add a short observation protocol to F10/F11: a staged
  scenario is legitimate provided the session prompt never mentions the memory system (e.g.
  seed the KB with a topic, open a real task in another repo that touches it); bound it (e.g.
  observed within N sessions or the feature flips to needs-you with findings); name who judges
  "unprompted."

### 7. `mem init`'s block-install behavior is architecturally F1's but proved only in F11 — with a latent idempotence tension

- **CITATION:** `ARCHITECTURE.md:30` — "**`mem init` owns setup**: … installs/refreshes the
  agent-integration instruction blocks into the global `CLAUDE.md`/`AGENTS.md`" vs.
  `FEATURES.md:23-24` (F1) — success criteria for `mem init` that never mention instruction
  blocks and require "a second run is a no-op that exits 0 (idempotent)"; `FEATURES.md:185-186`
  (F11) — "`mem init` installs/refreshes clearly-delimited managed blocks … re-running updates
  in place with no duplicate blocks."
- **ANCHOR:** tentative. (A consistent reading exists: F1 ships init without blocks; F11
  extends it, and "refresh to identical content" still satisfies "no-op.")
- **WHY IT MATTERS:** F11 (tail of the graph, depends on F6) retroactively modifies a command
  whose behavior contract was tested and frozen at F1 (the root). If F1's idempotence test
  asserts "no filesystem effect outside `~/.agent-memory`," F11's global-`CLAUDE.md` write
  breaks it — a late-build regression in the trunk feature, plus the question of whether F1's
  "no-op" means exit-0 or no-writes gets decided implicitly by whoever hits it first.
- **DISPOSITION SUGGESTION:** amend (cheap) — one sentence in F1 or F11 stating the split
  explicitly: F1 proves init's KB-home behavior; block installation is F11's surface, and F1's
  idempotence criterion means "exit 0, KB home unchanged," not "no writes anywhere."

---

## NOTES (uncited, no anchors)

- **WSL2 + systemd:** the architecture assumes a systemd-managed Ollama service; WSL2 only runs
  systemd if enabled in `/etc/wsl.conf`. Worth one preflight check alongside finding 1.
- **Paraphrase fixture stability (F4):** the fixture's pass/fail depends on the embedding
  model's actual geometry. Pinning model tag+digest (which the plan does) makes it stable, but
  expect fixture *selection* to be empirical — a candidate paraphrase may simply not land in
  top-k and need swapping. Not a spec defect; a build-time expectation.
- **Graph-only fixture (F6):** the graph leg has no independent query entry — it seeds from
  lexical∪vector hits. The "graph-only fixture" is therefore constructible only as a
  neighbor-of-a-seed (query hits A lexically; B links to A and shares nothing with the query).
  Fine, but the test author should know the shape in advance.
- **`mem extract` with Ollama down:** F9's dedup requires embeddings; the degradation posture
  ("saves land, embedding catches up") is specced for `save` but not for `extract`, whose whole
  point is embedding-based dedup. Presumably it refuses cleanly — worth a line somewhere before
  F9 is built.
- **Overall:** the dependency graph is otherwise clean and honestly annotated (the
  F1→F2→F4→F9→F10 long pole matches my reading), the gate record shows the
  concurrency/staleness class of risk was already caught once, and the architecture's Key
  Assumptions section is exactly the right kind of pre-registered honesty. The findings above
  are proof-layer tightening, not redesign.
