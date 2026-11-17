#!/usr/bin/env python3
"""Reversible operator steps that take a machine's shared-write configuration
out of service, each recorded in a receipt BEFORE the change and each undoable
from it.

  hold-profile    rename the shared-write profile aside so every KB marked
                  for shared writes fails closed ("profile is missing") with
                  no transport attempt; reads keep working
  restore-profile put a held profile back from its receipt
  remove-remote   remove one named git remote from a repository after
                  recording every remote.<name>.* configuration entry and
                  every remote-tracking ref under it
  restore-remote  re-add that remote, its configuration and its refs

Git runs with inherited GIT_* overrides stripped and hooks disabled, and the
repository named by --repo must be the repository git actually operates on.
Nothing runs without explicit paths; --dry-run prints the plan and changes
nothing. KB content, indexes and markers are never touched.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


class HoldError(Exception):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:64] or "unnamed"


# -------------------------------------------------------------- receipts ----

def fsync_dir(path: Path) -> None:
    """A file is not durable until its directory entry is."""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_durable(path: Path, mode: int = 0o700) -> list:
    """Create every missing ancestor of `path`, fsyncing each new directory's
    parent as it is created, so no directory entry on the way to a receipt can
    be lost by a crash. Returns the directories created."""
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


def open_receipt(receipts: Path, name: str, plan: dict) -> Path:
    """Create the receipt exclusively, owner-only, with status "planned", and
    make its directory entries durable, before anything changes. A failure
    here stops the operation."""
    mkdir_durable(receipts)
    path = receipts / f"{safe_name(name)}-{stamp()}-{os.getpid()}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({**plan, "status": "planned"}, indent=1, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    fsync_dir(receipts)
    return path


def finish_receipt(path: Path, plan: dict) -> None:
    temp = path.with_name(path.name + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(json.dumps({**plan, "status": "done", "completed": now()}, indent=1, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    fsync_dir(path.parent)


def read_receipt(path: Path, action: str) -> dict:
    data = json.loads(path.read_text())
    if data.get("action") != action:
        raise HoldError(f"receipt is not a {action} receipt")
    if data.get("status") != "done":
        raise HoldError(f"receipt status is {data.get('status')!r}, not done; inspect before restoring")
    return data


# ------------------------------------------------------------------- git ----

def git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    return env


def git(repo: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                           "-C", str(repo), *args],
                          capture_output=True, text=True, check=check, timeout=30, env=git_env())


def verify_repo(repo: Path) -> Path:
    """The repository git operates on must be exactly the one named."""
    repo = repo.resolve()
    if not (repo / ".git").exists():
        raise HoldError(f"{repo} is not a git repository")
    top = git(repo, "rev-parse", "--show-toplevel", check=False)
    if top.returncode or Path(top.stdout.strip()).resolve() != repo:
        raise HoldError(f"{repo} is not the top level of the repository git resolves it to")
    return repo


def remote_config(repo: Path, name: str) -> list:
    """Every remote.<name>.* entry in the repository's own config, in order."""
    pattern = "^remote\\." + re.escape(name) + "\\."
    out = git(repo, "config", "--local", "--get-regexp", "--null", pattern, check=False)
    if out.returncode not in (0, 1):
        raise HoldError("git config failed: " + out.stderr.strip())
    entries = []
    for record in out.stdout.split("\0"):
        if record:
            key, _, value = record.partition("\n")
            entries.append([key, value])
    return entries


def remote_refs(repo: Path, name: str) -> list:
    """[refname, objectname, symbolic_target] per remote-tracking ref; the
    symbolic target is "" for a direct ref (a remote's HEAD is normally
    symbolic and must come back as one)."""
    out = git(repo, "for-each-ref", "--format=%(refname)%00%(objectname)%00%(symref)",
              f"refs/remotes/{name}/")
    return [line.split("\0") for line in out.stdout.splitlines() if line]


# --------------------------------------------------------------- profile ----

def hold_profile(profile: Path, receipts: Path, dry_run: bool) -> dict:
    if profile.is_symlink() or not profile.is_file():
        raise HoldError(f"{profile} is not a regular file")
    held = profile.with_name(profile.name + ".held-" + stamp())
    if held.exists():
        raise HoldError(f"{held} already exists")
    plan = {"action": "hold-profile", "profile": str(profile), "held_as": str(held),
            "sha256": sha256(profile), "mode": oct(profile.stat().st_mode & 0o777), "at": now()}
    if dry_run:
        return {"dry_run": True, **plan}
    receipt = open_receipt(receipts, "hold-profile", plan)
    plan["receipt"] = str(receipt)
    os.rename(profile, held)
    finish_receipt(receipt, plan)
    return {**plan, "status": "done"}


def restore_profile(receipt: Path, dry_run: bool) -> dict:
    data = read_receipt(receipt, "hold-profile")
    profile, held = Path(data["profile"]), Path(data["held_as"])
    if profile.exists() or profile.is_symlink():
        raise HoldError(f"{profile} already exists; nothing restored")
    if held.is_symlink() or not held.is_file():
        raise HoldError(f"held copy {held} is missing")
    if sha256(held) != data["sha256"]:
        raise HoldError("held copy no longer matches its receipt; inspect before restoring")
    plan = {"action": "restore-profile", "profile": str(profile), "from": str(held),
            "sha256": data["sha256"], "mode": data["mode"], "at": now(), "hold_receipt": str(receipt)}
    if dry_run:
        return {"dry_run": True, **plan}
    restore = open_receipt(receipt.parent, "restore-profile", plan)
    plan["receipt"] = str(restore)
    os.rename(held, profile)
    profile.chmod(int(data["mode"], 8))
    finish_receipt(restore, plan)
    return {**plan, "status": "done"}


# ---------------------------------------------------------------- remote ----

def remove_remote(repo: Path, name: str, receipts: Path, dry_run: bool) -> dict:
    repo = verify_repo(repo)
    if name not in git(repo, "remote").stdout.split():
        raise HoldError(f"remote {name!r} is not configured in {repo}")
    config = remote_config(repo, name)
    refs = remote_refs(repo, name)
    plan = {"action": "remove-remote", "repo": str(repo), "name": name, "config": config,
            "refs": refs, "at": now()}
    if dry_run:
        return {"dry_run": True, **plan}
    receipt = open_receipt(receipts, "remove-remote-" + name, plan)
    plan["receipt"] = str(receipt)
    git(repo, "remote", "remove", name)
    finish_receipt(receipt, plan)
    return {**plan, "status": "done"}


def ref_entries(data: dict) -> list:
    """Refs as [refname, objectname, symbolic_target]. Receipts written before
    symbolic targets were recorded hold [refname, objectname] pairs; those are
    direct refs."""
    entries = []
    for entry in data.get("refs", []):
        if isinstance(entry, list) and len(entry) == 2:
            entry = [entry[0], entry[1], ""]
        if (not isinstance(entry, list) or len(entry) != 3
                or not all(isinstance(x, str) for x in entry)):
            raise HoldError("receipt refs entry is not [refname, objectname, symbolic_target]")
        entries.append(entry)
    return entries


def restore_remote(receipt: Path, dry_run: bool) -> dict:
    data = read_receipt(receipt, "remove-remote")
    data["refs"] = ref_entries(data)
    repo, name = verify_repo(Path(data["repo"])), data["name"]
    if name in git(repo, "remote").stdout.split() or remote_config(repo, name):
        raise HoldError(f"remote {name!r} already exists in {repo}; nothing restored")
    for refname, sha, symref in data["refs"]:
        if not symref and git(repo, "cat-file", "-e", sha, check=False).returncode:
            raise HoldError(f"object {sha} for {refname} is gone; cannot restore faithfully")
    plan = {"action": "restore-remote", "repo": str(repo), "name": name, "config": data["config"],
            "refs": data["refs"], "at": now(), "remove_receipt": str(receipt)}
    if dry_run:
        return {"dry_run": True, **plan}
    restore = open_receipt(receipt.parent, "restore-remote-" + name, plan)
    plan["receipt"] = str(restore)
    for key, value in data["config"]:
        git(repo, "config", "--local", "--add", key, value)
    for refname, sha, symref in data["refs"]:
        if not symref:
            git(repo, "update-ref", refname, sha)
    for refname, sha, symref in data["refs"]:
        if symref:
            git(repo, "symbolic-ref", refname, symref)
    finish_receipt(restore, plan)
    return {**plan, "status": "done"}


# ------------------------------------------------------------------ main ----

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hold-shared-writes.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("hold-profile")
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--receipts", type=Path, required=True)
    p = sub.add_parser("restore-profile")
    p.add_argument("--receipt", type=Path, required=True)
    p = sub.add_parser("remove-remote")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--receipts", type=Path, required=True)
    p = sub.add_parser("restore-remote")
    p.add_argument("--receipt", type=Path, required=True)
    for s in sub.choices.values():
        s.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "hold-profile":
            result = hold_profile(args.profile, args.receipts, args.dry_run)
        elif args.command == "restore-profile":
            result = restore_profile(args.receipt, args.dry_run)
        elif args.command == "remove-remote":
            result = remove_remote(args.repo, args.name, args.receipts, args.dry_run)
        else:
            result = restore_remote(args.receipt, args.dry_run)
    except (HoldError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"hold-shared-writes: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
