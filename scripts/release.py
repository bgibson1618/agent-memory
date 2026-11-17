#!/usr/bin/env python3
"""Staged release, activation and rollback for the `mem` runtime.

Two install layers decide what the `mem` on PATH imports:

  1. the uv tool venv (<tool-dir>/agent-memory). Its receipt says whether the
     package is an *editable* install of a worktree (a .pth naming that
     worktree's src/, so commits there change the runtime) or a copy
     installed from a directory;
  2. an optional *selector*: a `zz_agent_memory_*.pth` file in that venv's
     site-packages that inserts a frozen release package ahead of everything
     else. A wrapper may pin the selector's hash.

A commit never touches either layer (scripts/git-hooks/post-commit). This
tool does, explicitly, and only where it is told to: every command names the
tool directory and bin directory it works on, canonicalizes every path it
records, refuses the live default prefix unless --allow-live is given (an
activation decision, not a development step), writes its undo journal
BEFORE changing anything, and measures the result through the prefix's own
interpreter.

  stage     archive one revision of a source repo into a read-only release
            directory with a manifest of file hashes (built in a temporary
            directory and renamed into place, so a failure leaves nothing)
  activate  journal the previous state, then install the release
            non-editably into the named prefix and point the selector at it
  rollback  journal, then restore the previous state recorded by the last
            activate (receipt layer and selectors); also recovers an
            interrupted activate from its journal
  status    report what the named prefix's `mem` imports right now

Exit codes: 0 ok, 1 refused or failed (one-line reason on stderr).
"""

import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

FORMAT = "mem-release/1"
SELECTOR_PREFIX = "zz_agent_memory_"
SELECTOR_NAME = "zz_agent_memory_release.pth"
ARCHIVE_PATHS = ("pyproject.toml", "uv.lock", "README.md", "src")


class ReleaseError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, env=None, cwd=None, input=None) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, capture_output=True, text=True, env=env, cwd=cwd,
                            input=input, timeout=600)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise ReleaseError(f"{argv[0]} failed: {detail[-1] if detail else result.returncode}")
    return result


def fsync_dir(path: Path) -> None:
    """A file is not durable until its directory entry is."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_durable(path: Path, mode: int = 0o755) -> list:
    """Create every missing ancestor of `path`, fsyncing each new directory's
    parent as it is created, so no new directory entry on the way to an undo
    record can be lost by a crash. Returns the directories created."""
    missing = []
    probe = path
    while not probe.exists():
        missing.append(probe)
        probe = probe.parent
    created = []
    for directory in reversed(missing):
        directory.mkdir(mode=mode)
        fsync_dir(directory.parent)
        created.append(directory)
    return created


def atomic_write_json(path: Path, data: dict) -> None:
    """Durable before it is visible: every new ancestor is created durably,
    the temp file is written and fsynced, renamed into place, and the
    directory is fsynced, so a crash after return cannot lose the journal."""
    mkdir_durable(path.parent)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(data, indent=1, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fsync_dir(path.parent)


# ---------------------------------------------------------------- prefix ----

def uv_env(tool_dir: Path, bin_dir: Path) -> dict:
    """An environment in which uv can only mean the named prefix: inherited
    UV_* settings that redirect where uv installs (tool, bin, project
    environment, config file) are dropped, so a stray UV_TOOL_DIR cannot point
    a test at the live installation; cache and offline settings pass through."""
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("UV_") and any(s in k for s in ("TOOL_", "ENVIRONMENT", "CONFIG")))}
    env.update(UV_TOOL_DIR=str(tool_dir), UV_TOOL_BIN_DIR=str(bin_dir), UV_NO_PROGRESS="1")
    return env


def live_default() -> tuple[Path, Path]:
    """Where uv would install by default in this environment (the live prefix)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("UV_")}
    tool = run(["uv", "tool", "dir"], env=env).stdout.strip()
    bins = run(["uv", "tool", "dir", "--bin"], env=env).stdout.strip()
    return Path(tool).resolve(), Path(bins).resolve()


def guard_prefix(tool_dir: Path, bin_dir: Path, allow_live: bool) -> None:
    live_tool, live_bin = live_default()
    for given, live, what in ((tool_dir, live_tool, "tool"), (bin_dir, live_bin, "bin")):
        if given.resolve() == live and not allow_live:
            raise ReleaseError(
                f"{what} directory {given} is the live default prefix; pass --allow-live "
                "only as an approved activation step")


def site_packages(tool_dir: Path) -> Path:
    matches = sorted((tool_dir / "agent-memory" / "lib").glob("python*/site-packages"))
    if len(matches) != 1:
        raise ReleaseError(f"expected one site-packages under {tool_dir / 'agent-memory'}")
    return matches[0]


def receipt_path(tool_dir: Path) -> Path:
    return tool_dir / "agent-memory" / "uv-receipt.toml"


def selectors(tool_dir: Path) -> dict:
    try:
        site = site_packages(tool_dir)
    except ReleaseError:
        return {}
    return {p.name: p.read_text() for p in sorted(site.glob(SELECTOR_PREFIX + "*.pth"))}


# ----------------------------------------------------------------- stage ----

def _make_writable(root: Path) -> None:
    for path in root.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    root.chmod(0o755)


def stage(source: Path, rev: str, releases_dir: Path) -> Path:
    source = source.resolve()
    releases_dir = releases_dir.resolve()
    sha = run(["git", "-C", str(source), "rev-parse", "--verify", rev + "^{commit}"]).stdout.strip()
    pyproject = run(["git", "-C", str(source), "show", f"{sha}:pyproject.toml"]).stdout
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    if not match:
        raise ReleaseError("pyproject.toml at that revision has no version")
    version = match.group(1)
    release_id = f"{version}+{sha[:12]}"
    dest = releases_dir / release_id
    if dest.exists():
        raise ReleaseError(f"release {release_id} already staged at {dest}")
    mkdir_durable(releases_dir)
    work = releases_dir / f".staging-{release_id}-{os.getpid()}"
    if work.exists():
        _make_writable(work)
        shutil.rmtree(work)
    try:
        archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", sha, *ARCHIVE_PATHS],
                                 capture_output=True, timeout=600)
        if archive.returncode:
            raise ReleaseError("git archive failed: " + archive.stderr.decode(errors="replace").strip())
        tree = work / "source"
        tree.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(tree, filter="data")
        files = {str(p.relative_to(tree)): sha256_file(p)
                 for p in sorted(p for p in tree.rglob("*") if p.is_file())}
        manifest = {"format": FORMAT, "id": release_id, "version": version, "source_repo": str(source),
                    "rev": sha, "created": now(), "files": files}
        (work / "release.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
        for path in list(work.rglob("*")) + [work]:   # the tree is durable before it appears
            if path.is_dir():
                fsync_dir(path)
            else:
                fd = os.open(path, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        for path in tree.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        (work / "release.json").chmod(0o444)
        tree.chmod(0o555)
        os.rename(work, dest)      # the release appears only once it is complete
        fsync_dir(releases_dir)    # ...and its directory entry is durable
    except BaseException:
        if work.exists():
            _make_writable(work)
            shutil.rmtree(work, ignore_errors=True)
        raise
    dest.chmod(0o555)
    return dest


def verify_release(release_dir: Path) -> dict:
    manifest = json.loads((release_dir / "release.json").read_text())
    if manifest.get("format") != FORMAT:
        raise ReleaseError("not a mem release directory")
    tree = release_dir / "source"
    actual = {str(p.relative_to(tree)): sha256_file(p) for p in tree.rglob("*") if p.is_file()}
    if actual != manifest["files"]:
        raise ReleaseError(f"release {manifest['id']} does not match its manifest")
    return manifest


# -------------------------------------------------------------- activate ----

def state_path(releases_dir: Path) -> Path:
    return releases_dir / "active.json"


def load_state(releases_dir: Path) -> dict | None:
    path = state_path(releases_dir)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ReleaseError(f"{path} is unreadable ({error}); repair or move it aside first") from None
    if not isinstance(state, dict) or state.get("format") != FORMAT or "status" not in state:
        raise ReleaseError(f"{path} is not a {FORMAT} journal; repair or move it aside first")
    return state


def snapshot(tool_dir: Path) -> dict:
    receipt = receipt_path(tool_dir)
    return {"receipt": receipt.read_text() if receipt.is_file() else None,
            "selectors": selectors(tool_dir)}


def _reinstall(tool_dir: Path, bin_dir: Path, spec: list, python: str | None) -> None:
    argv = ["uv", "tool", "install", "--reinstall"]
    if python:
        argv += ["--python", python]
    run(argv + spec, env=uv_env(tool_dir, bin_dir))


def _write_selectors(tool_dir: Path, wanted: dict) -> None:
    site = site_packages(tool_dir)
    for existing in site.glob(SELECTOR_PREFIX + "*.pth"):
        existing.unlink()
    for name, content in wanted.items():
        (site / name).write_text(content)


def _spec_from_receipt(receipt: str | None) -> list:
    if not receipt:
        raise ReleaseError("previous state had no installed tool; remove the prefix by hand")
    editable = re.search(r'editable\s*=\s*"([^"]+)"', receipt)
    directory = re.search(r'directory\s*=\s*"([^"]+)"', receipt)
    if editable:
        return ["-e", editable.group(1)]
    if directory:
        return [directory.group(1)]
    raise ReleaseError("previous receipt names neither an editable worktree nor a directory")


def activate(release_dir: Path, releases_dir: Path, tool_dir: Path, bin_dir: Path,
             allow_live: bool = False, python: str | None = None) -> dict:
    release_dir, releases_dir = release_dir.resolve(), releases_dir.resolve()
    tool_dir, bin_dir = tool_dir.resolve(), bin_dir.resolve()
    manifest = verify_release(release_dir)
    guard_prefix(tool_dir, bin_dir, allow_live)
    state = load_state(releases_dir)
    if state and state["status"] in ("activating", "rolling-back"):
        raise ReleaseError(f"a previous {state['status']} did not complete; run rollback or inspect "
                           f"{state_path(releases_dir)} first")
    previous = snapshot(tool_dir)
    history = (state or {}).get("history", [])
    if state:
        history = history + [{"at": state["at"], "active": state.get("active"), "status": state["status"]}]
    selector = {SELECTOR_NAME: f"import sys; sys.path.insert(0, {str(release_dir / 'source' / 'src')!r})\n"}
    journal = {"format": FORMAT, "status": "activating", "at": now(), "active": manifest["id"],
               "release_dir": str(release_dir), "tool_dir": str(tool_dir), "bin_dir": str(bin_dir),
               "previous": previous, "selector": selector,
               "selector_sha256": hashlib.sha256(next(iter(selector.values())).encode()).hexdigest(),
               "history": history}
    atomic_write_json(state_path(releases_dir), journal)   # undo data is durable before any change
    _reinstall(tool_dir, bin_dir, [str(release_dir / "source")], python)
    _write_selectors(tool_dir, selector)
    journal.update(status="active", completed=now())
    atomic_write_json(state_path(releases_dir), journal)
    return status(tool_dir)


def rollback(releases_dir: Path, tool_dir: Path, bin_dir: Path, allow_live: bool = False,
             python: str | None = None) -> dict:
    releases_dir, tool_dir, bin_dir = releases_dir.resolve(), tool_dir.resolve(), bin_dir.resolve()
    guard_prefix(tool_dir, bin_dir, allow_live)
    state = load_state(releases_dir)
    if state is None:
        raise ReleaseError("nothing to roll back: no active.json")
    if Path(state["tool_dir"]).resolve() != tool_dir:
        raise ReleaseError("active.json was written for a different tool directory")
    if state["status"] == "rolling-back":
        raise ReleaseError("a previous rollback did not complete; inspect active.json")
    if state["status"] == "rolled-back":
        raise ReleaseError("already rolled back; activate a release to change the prefix again")
    previous = state["previous"]
    spec = _spec_from_receipt(previous.get("receipt"))
    journal = {"format": FORMAT, "status": "rolling-back", "at": now(),
               "rolled_back_from": state.get("active"), "interrupted": state["status"] == "activating",
               "previous": previous, "restored": {"spec": spec, "selectors": sorted(previous.get("selectors", {}))},
               "tool_dir": str(tool_dir), "bin_dir": str(bin_dir),
               "history": state.get("history", []) + [{"at": state["at"], "active": state.get("active"),
                                                        "status": state["status"]}]}
    atomic_write_json(state_path(releases_dir), journal)
    _reinstall(tool_dir, bin_dir, spec, python)
    _write_selectors(tool_dir, previous.get("selectors", {}))
    journal.update(status="rolled-back", completed=now())
    atomic_write_json(state_path(releases_dir), journal)
    return status(tool_dir)


# ---------------------------------------------------------------- status ----

def status(tool_dir: Path) -> dict:
    tool_dir = tool_dir.resolve()
    python = tool_dir / "agent-memory" / "bin" / "python"
    report = {"tool_dir": str(tool_dir), "python": str(python), "installed": python.is_file()}
    if not python.is_file():
        return report
    probe = run([str(python), "-I", "-c",
                 "import json, sys, agent_memory; print(json.dumps({'file': agent_memory.__file__, "
                 "'version': agent_memory.__version__, 'executable': sys.executable}))"], cwd="/")
    report.update(json.loads(probe.stdout))
    package = Path(report["file"]).parent
    release_json = package.parent.parent.parent / "release.json"
    report["release"] = None
    if release_json.is_file():
        try:
            report["release"] = json.loads(release_json.read_text()).get("id")
        except ValueError:
            report["release"] = "unreadable"
    receipt = receipt_path(tool_dir)
    text = receipt.read_text() if receipt.is_file() else ""
    editable = re.search(r'editable\s*=\s*"([^"]+)"', text)
    directory = re.search(r'directory\s*=\s*"([^"]+)"', text)
    report["receipt"] = ({"kind": "editable", "path": editable.group(1)} if editable else
                         {"kind": "directory", "path": directory.group(1)} if directory else
                         {"kind": "unknown", "path": None})
    report["selectors"] = {name: hashlib.sha256(content.encode()).hexdigest()
                           for name, content in selectors(tool_dir).items()}
    report["imports"] = ("release " + report["release"] if report["release"]
                         else "worktree " + str(package.parent.parent)
                         if report["receipt"]["kind"] == "editable" else "installed copy")
    return report


# ------------------------------------------------------------------ main ----

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="release.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("stage", help="archive a source revision into a read-only release")
    s.add_argument("--source", type=Path, required=True, help="git repository to archive")
    s.add_argument("--rev", default="HEAD", help="commit-ish to release (default HEAD)")
    s.add_argument("--releases-dir", type=Path, required=True)

    for name in ("activate", "rollback"):
        p = sub.add_parser(name)
        if name == "activate":
            p.add_argument("--release", type=Path, required=True, help="a staged release directory")
        p.add_argument("--releases-dir", type=Path, required=True, help="where active.json lives")
        p.add_argument("--tool-dir", type=Path, required=True, help="uv tool directory to change")
        p.add_argument("--bin-dir", type=Path, required=True, help="uv bin directory to change")
        p.add_argument("--allow-live", action="store_true",
                       help="permit the live default prefix (an approved activation step only)")
        p.add_argument("--python", help="interpreter for the tool venv (uv --python)")

    st = sub.add_parser("status", help="what the named prefix's mem imports now")
    st.add_argument("--tool-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            dest = stage(args.source, args.rev, args.releases_dir)
            manifest = json.loads((dest / "release.json").read_text())
            print(json.dumps({"staged": str(dest), "id": manifest["id"], "rev": manifest["rev"],
                              "files": len(manifest["files"])}, indent=1, sort_keys=True))
        elif args.command == "activate":
            print(json.dumps(activate(args.release, args.releases_dir, args.tool_dir, args.bin_dir,
                                      args.allow_live, args.python), indent=1, sort_keys=True))
        elif args.command == "rollback":
            print(json.dumps(rollback(args.releases_dir, args.tool_dir, args.bin_dir,
                                      args.allow_live, args.python), indent=1, sort_keys=True))
        else:
            print(json.dumps(status(args.tool_dir), indent=1, sort_keys=True))
    except (ReleaseError, OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"release.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
