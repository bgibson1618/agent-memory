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

`activate` and `rollback` refuse the live default prefix unless `--allow-live`
is given. Leave that flag out during development and testing: `tests/
test_release_tool.py` exercises every command against disposable prefixes and
asserts the live prefix is byte-identical afterwards.

## Identity

`mem --version` prints the version and the imported package path on one
line; `mem doctor` starts with a `runtime` line naming the release id (or
"worktree" / "installed copy"), the package path, any selector with its hash
prefix, and the interpreter. Use these, not assumptions, to say what runs.

## Activation on a real machine

Activation changes a running system and may invalidate a wrapper's pinned
selector hash. It needs its own reviewed checklist (what is active now, the
staged release id and manifest, the exact prefix, the rollback command, who
re-pins any wrapper), approval, and a status check afterwards. Nothing in
this repository activates anything on its own.
