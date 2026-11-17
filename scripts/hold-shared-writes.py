#!/usr/bin/env python3
"""Reversible operator steps that take a machine's shared-write configuration
out of service, each recorded in a receipt and each undoable from it.

  hold-profile    rename the shared-write profile aside so every KB marked
                  for shared writes fails closed ("profile is missing") with
                  no transport attempt; reads keep working
  restore-profile put a held profile back from its receipt
  remove-remote   remove one named git remote from a repository after
                  recording its URLs and refspecs
  restore-remote  re-add that remote from its receipt

Nothing here runs without explicit paths; --dry-run prints the plan and
changes nothing. KB content, indexes and markers are never touched.
"""

import argparse
import datetime as dt
import hashlib
import json
import os
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


def write_receipt(receipts: Path, name: str, data: dict) -> Path:
    receipts.mkdir(parents=True, exist_ok=True)
    path = receipts / f"{name}-{stamp()}.json"
    if path.exists():
        raise HoldError(f"receipt {path} already exists")
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    path.chmod(0o600)
    return path


def git(repo: Path, *args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check, timeout=30)


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
    os.rename(profile, held)
    plan["receipt"] = str(write_receipt(receipts, "hold-profile", plan))
    return plan


def restore_profile(receipt: Path, dry_run: bool) -> dict:
    data = json.loads(receipt.read_text())
    if data.get("action") != "hold-profile":
        raise HoldError("receipt is not a hold-profile receipt")
    profile, held = Path(data["profile"]), Path(data["held_as"])
    if profile.exists() or profile.is_symlink():
        raise HoldError(f"{profile} already exists; nothing restored")
    if held.is_symlink() or not held.is_file():
        raise HoldError(f"held copy {held} is missing")
    if sha256(held) != data["sha256"]:
        raise HoldError("held copy no longer matches its receipt; inspect before restoring")
    plan = {"action": "restore-profile", "profile": str(profile), "from": str(held),
            "sha256": data["sha256"], "at": now(), "receipt": str(receipt)}
    if dry_run:
        return {"dry_run": True, **plan}
    os.rename(held, profile)
    profile.chmod(int(data["mode"], 8))
    plan["restore_receipt"] = str(write_receipt(receipt.parent, "restore-profile", plan))
    return plan


# ---------------------------------------------------------------- remote ----

def remove_remote(repo: Path, name: str, receipts: Path, dry_run: bool) -> dict:
    if not (repo / ".git").exists():
        raise HoldError(f"{repo} is not a git repository")
    names = git(repo, "remote").stdout.split()
    if name not in names:
        raise HoldError(f"remote {name!r} is not configured in {repo}")
    fetch_url = git(repo, "remote", "get-url", name).stdout.strip()
    push_url = git(repo, "remote", "get-url", "--push", name).stdout.strip()
    refspecs = git(repo, "config", "--get-all", f"remote.{name}.fetch", check=False).stdout.split()
    plan = {"action": "remove-remote", "repo": str(repo.resolve()), "name": name,
            "fetch_url": fetch_url, "push_url": push_url, "fetch_refspecs": refspecs, "at": now()}
    if dry_run:
        return {"dry_run": True, **plan}
    git(repo, "remote", "remove", name)
    plan["receipt"] = str(write_receipt(receipts, f"remove-remote-{name}", plan))
    return plan


def restore_remote(receipt: Path, dry_run: bool) -> dict:
    data = json.loads(receipt.read_text())
    if data.get("action") != "remove-remote":
        raise HoldError("receipt is not a remove-remote receipt")
    repo, name = Path(data["repo"]), data["name"]
    if name in git(repo, "remote").stdout.split():
        raise HoldError(f"remote {name!r} already exists in {repo}; nothing restored")
    plan = {"action": "restore-remote", "repo": str(repo), "name": name,
            "fetch_url": data["fetch_url"], "push_url": data["push_url"], "at": now(),
            "receipt": str(receipt)}
    if dry_run:
        return {"dry_run": True, **plan}
    git(repo, "remote", "add", name, data["fetch_url"])
    if data["push_url"] != data["fetch_url"]:
        git(repo, "remote", "set-url", "--push", name, data["push_url"])
    if data.get("fetch_refspecs"):
        git(repo, "config", "--unset-all", f"remote.{name}.fetch", check=False)
        for spec in data["fetch_refspecs"]:
            git(repo, "config", "--add", f"remote.{name}.fetch", spec)
    plan["restore_receipt"] = str(write_receipt(receipt.parent, f"restore-remote-{name}", plan))
    return plan


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
