# Releasing `mem`

A commit never deploys. The post-commit hook only prints which package the
`mem` on PATH imports right now; deployment is an explicit, recorded act of
`scripts/release.py`, and *activating* a release on a machine whose runtime
other tools depend on is an operator decision, not a development step.

## The two install layers

What `mem` imports is decided by two things inside the uv tool prefix
(`uv tool dir`, usually `~/.local/share/uv/tools`):

1. **The tool venv's receipt** (`agent-memory/uv-receipt.toml`). An
   *editable* install names a worktree's `src/` through a `.pth` file, so
   every commit in that worktree changes the runtime. A *directory* install
   copies the package into the venv.
2. **A selector**, any `zz_agent_memory_*.pth` in the venv's site-packages,
   which inserts a frozen release package ahead of everything else. A
   wrapper may pin that selector's hash and refuse to run when it changes.

Reinstalling the tool rebuilds the venv and silently removes any selector,
which is exactly why the hook stopped reinstalling.

## Commands

```bash
# 1. Freeze a revision into a read-only release directory with a manifest.
scripts/release.py stage --source . --rev HEAD --releases-dir ~/.local/lib/agent-memory/releases

# 2. See what a prefix imports now (measured through its own interpreter).
scripts/release.py status --tool-dir /path/to/uv/tools

# 3. Activate a staged release into a prefix: non-editable install from the
#    frozen copy + a selector pointing at it. Records the previous receipt and
#    selectors in <releases-dir>/active.json for rollback.
scripts/release.py activate --release <releases-dir>/<id> --releases-dir <releases-dir> \
    --tool-dir /path/to/uv/tools --bin-dir /path/to/bin

# 4. Roll back to the recorded previous state (receipt layer and selectors).
scripts/release.py rollback --releases-dir <releases-dir> --tool-dir ... --bin-dir ...
```

`activate` and `rollback` rebuild the venv with `uv tool install --reinstall`,
which resolves dependencies afresh rather than from `uv.lock`; uv's own
environment controls pass through, so pin the prefix's current versions with
`UV_CONSTRAINT=<file>` and `UV_OFFLINE=1` on both (uv splits `UV_CONSTRAINT` on
spaces: give a path without one, relative to the working directory if need be).

`activate` and `rollback` refuse the live default prefix unless `--allow-live`
is given. Leave that flag out during development and testing: `tests/
test_release_tool.py` exercises every command against disposable prefixes and
asserts the live prefix is byte-identical afterwards.

## Identity

`mem --version` prints the version and the imported package path on one
line; `mem doctor` starts with a `runtime` line naming the release id (or
"worktree" / "installed copy"), the package path, any selector with its hash
prefix, and the interpreter. Use these, not assumptions, to say what runs.
Use `--version` for a non-mutating runtime identity check. Commands that
reach normal command dispatch, including `mem extract --procedure`, can append
usage and drain queued embeddings; use a synthetic instance for behavioral
checks.

## What these tools write, and retention

`stage` writes one read-only directory per revision under the releases
directory (about the size of the source tree, a few hundred kilobytes) plus
its manifest; a failed staging is built in a temporary sibling and leaves
nothing. `activate` and `rollback` rewrite one `active.json` journal (with a
short history list) in the releases directory and rebuild the named uv tool
venv; uv also fills its own cache. `scripts/hold-shared-writes.py` writes one
small receipt per operation (owner-only) and renames, never copies, the
profile it holds. None of this grows on its own: directories and receipts
accumulate only with operator actions. Keep every receipt and the previously
active release until a rollback is no longer plausible; remove older staged
releases by hand, never automatically, and never the one `active.json` names.

## Activation on a real machine

Activation changes a running system and may invalidate a wrapper's pinned
selector hash. It needs its own reviewed checklist (what is active now, the
staged release id and manifest, the exact prefix, the rollback command, who
re-pins any wrapper), approval, and a status check afterwards. Nothing in
this repository activates anything on its own.

## What is active on the development laptop (2026-11-20)

Recorded here so that a new engineer can tell what runs without reading the operations records
(which stay private, outside this repository).

- **Runtime:** release `0.2.1+732b914bc791` (frozen from revision 732b914, main after the D30 merge:
  D28's `--entrypoint` plus the D30 memory templates; the program code equals `0.2.1+a6d77bfd71d2`),
  installed non-editably into the uv tool prefix and selected by `zz_agent_memory_release.pth`. It was
  activated offline with the prefix's numpy 2.5.5 and PyYAML 6.0.3 as uv constraints, on Python
  3.12.13. `<releases-dir>/active.json` journals the previous release, `0.2.1+a6d77bfd71d2` (its
  receipt and selector), so `rollback` returns to that release; earlier journals (to `0.2.1+a1c3a6319b61`
  and to the editable worktree install) are kept in the private records. `mem --version` prints the
  release path.
- **Guarded personal wrapper:** a private launcher pins the release package and that selector's
  hash and selects one private local instance; it refuses when either pin drifts and holds
  `doctor`, `init` and the four transport commands. Its path and instance are operator policy, not
  part of this repository.
- **Plugin:** both agent harnesses serve `.claude-plugin/` and `skills/` from a frozen plugin
  snapshot, `<releases-dir>/plugin-0.2.1+a6d77bfd71d2`, frozen from revision a6d77bf (see "Plugin
  snapshots" below), not from a worktree. The plugin files are unchanged at 732b914, so the D30
  release kept this snapshot.
- **Claude guidance (D30, Claude only):** the user-level Claude instruction file carries an appended
  section, "Agent Memory use (`mem-personal`)": the D30 wording (search at the start of non-trivial
  work; save a scoped single tested observation; cite evidence by project name and project-relative
  path; read-version-checked updates), adapted to the personal entrypoint, after the unchanged
  policy-reference block. Running sessions keep what they loaded; new sessions read it. Codex
  guidance is unchanged until a Codex test (BACKLOG).
- **Holds (receipted, reversible):** the shared-write operator profile is held aside by
  `scripts/hold-shared-writes.py hold-profile` (so every marked replica fails closed), and an
  obsolete remote was removed from the development checkout by `remove-remote`. Each receipt is
  the input of the matching `restore-*` command.
- **Rollback of the D30 release, in reverse order:** the Claude instruction file back to its saved
  bytes through the guarded tool (it refuses unless the file is exactly the D30 version); the wrapper
  from its saved copy; then `scripts/release.py rollback --allow-live`, run once and only after
  checking that `active.json` is this release's journal (the venv is rebuilt, not byte-identical).
  Rolling back further, to the D28 state's predecessor, follows the D28 packet: Codex re-registered on
  `plugin-0.2.1+8be9b0927063`, Claude's four `mem-local` routing fields moved back field by field
  (never a whole-file restore — those files also carry other tools' settings), the wrapper, then a
  rollback. The guarded commands are in the private operator packets.
  Keep every saved copy, the previous release and the previous snapshot until the operator closes
  the rollback window.

## Plugin snapshots

`stage` archives the runtime (`pyproject.toml`, `uv.lock`, `README.md`, `src/`) and nothing
else, so the harness plugin is frozen separately: copy `.claude-plugin/marketplace.json`,
`.claude-plugin/plugin.json` and `skills/extract/SKILL.md` from the exact revision (`git show
<rev>:<path>`) into `<releases-dir>/plugin-<version>+<sha12>/`, write `SNAPSHOT-SOURCE.txt`
(`rev <sha> created <UTC>`), write `SNAPSHOT-MANIFEST.sha256` over those four files (it excludes
itself), make directories 0555 and files 0444, and check with `sha256sum --check`. When the skill
depends on a CLI option the running release lacks (D28's `--entrypoint`), freeze the runtime
release and the plugin snapshot from the same revision and switch them together. The plugin
version stays the CLI's version; the snapshot id carries the commit. A snapshot that nothing
serves any more may be removed by hand, never automatically.

Pointing a harness at a snapshot:

- **Claude Code.** The authoritative registration is the `extraKnownMarketplaces` entry for the
  `mem-local` marketplace in the user's `settings.json`: Claude Code merges it into
  `plugins/known_marketplaces.json` at every fresh process start, so editing the registry files
  alone does not persist. Point that setting's `path` at the snapshot, then the installed plugin's
  `installPath` in `plugins/installed_plugins.json` (what actually loads) and the two marketplace
  fields at the same snapshot. Verify after a *fresh* session start, not only after an in-session
  reload: `claude plugin list` must read `mem@mem-local` from the snapshot and a new session must
  load the skill from it. Enabling the plugin is a separate setting (`claude plugin enable
  mem@mem-local`). Settings are the operator's; keep a saved copy before and after.
- **Codex.** A same-name `marketplace add` from a changed source is refused, so refresh in three
  steps — `codex plugin marketplace remove mem-local --json`, `codex plugin marketplace add
  <snapshot> --json`, `codex plugin add mem@mem-local --json` — then check that the config's
  `marketplaces.mem-local.source` is the only changed value (compare semantically; the stanza
  may move within the file), the plugin stays enabled, and the cache under
  `plugins/cache/mem-local/mem/<version>/` equals the snapshot per its manifest. A desktop
  restart loads the new copy; a pre-existing broken marketplace elsewhere in the config makes the
  global `codex plugin list` fail without blocking these operations.
