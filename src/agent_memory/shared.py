"""Explicit, private, host-mediated KB writes and durable retry requests."""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import uuid

from agent_memory import config, coordinator

MARKER = "agent-memory.sharedWrites"
# Endpoint policy belongs to the operator's private profile file, never to this
# package: the receiver/refresh program paths and, on a laptop, the SSH
# destination. The package only checks the profile's shape and ownership.
PROFILE_PATH = ".config/agent-sync/shared-kb.json"
_HOST_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,252}[A-Za-z0-9])?")
_USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
TERMINAL = {"applied", "conflict"}
MAX_REQUEST = 16 * 1024 * 1024


class SharedError(Exception):
    """An actionable refusal without confidential payload details."""


def version(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
               GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    return env


def git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-c", "gc.auto=0", "-C", str(root), *args],
        capture_output=True, text=True, env=git_env(), timeout=15,
    )


def _validated(profile: dict) -> dict:
    """Shape-check a profile that governs THIS root. Endpoint values are the
    operator's; the package never carries or compares against its own."""
    expected_roots = {
        "default": str(Path.home() / ".agent-memory"),
        "personal": str(Path.home() / ".agent-memory-personal"),
    }
    if (profile.get("version") != 1 or profile.get("machine") not in {"host", "laptop"}
            or profile.get("roots") != expected_roots):
        raise SharedError("shared-write profile differs from the approved private setup")
    for key in ("receiver", "receiver_python", "refresh"):
        value = profile.get(key)
        if not isinstance(value, str) or not value.startswith("/") or any(c in value for c in "\n\0"):
            raise SharedError(f"shared-write profile {key} must be an absolute path")
    if profile["machine"] == "laptop":
        t = profile.get("transport")
        if (not isinstance(t, dict) or set(t) != {"alias", "hostname", "user", "port"}
                or not all(isinstance(t[k], str) for k in ("alias", "hostname", "user"))
                or not _HOST_RE.fullmatch(t["alias"]) or not _HOST_RE.fullmatch(t["hostname"])
                or not _USER_RE.fullmatch(t["user"])
                or type(t["port"]) is not int or not 1 <= t["port"] <= 65535):
            raise SharedError(
                "shared-write profile transport must name alias, hostname, user and port"
            )
    return profile


def profile_for(root: Path) -> dict | None:
    """The profile entry governing `root`, or None for an unconfigured local KB.

    A marked KB (git marker or required-file) with no usable profile fails
    closed. An unmarked root is governed only by a readable profile that lists
    it; an unreadable, malformed or unsafe profile, or one that lists other
    roots, never disturbs an unrelated instance."""
    marked = git(root, "config", "--bool", "--get", MARKER).stdout.strip() == "true"
    marked = marked or (root / ".index/shared-write-required.json").exists()
    path = Path.home() / PROFILE_PATH
    if not path.exists():
        if marked:
            raise SharedError("shared-write profile is missing; local source writes are disabled")
        return None
    try:
        if path.is_symlink() or path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            raise SharedError("shared-write profile must be an owner-only regular file")
        profile = json.loads(path.read_text())
        roots = profile.get("roots")
        if not isinstance(roots, dict):
            raise SharedError("shared-write profile is unreadable or invalid; writes are disabled")
        name = next((n for n, location in roots.items()
                     if isinstance(location, str) and Path(location).resolve() == root.resolve()),
                    None)
    except SharedError:
        # Governance is the KB's own marker, not the profile file: a marked
        # root fails closed on an unusable profile; an unmarked root is simply
        # not governed by it (2026-11-17 reviewer finding).
        if marked:
            raise
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        if marked:
            raise SharedError("shared-write profile is unreadable or invalid; writes are disabled") from None
        return None
    if name is None:
        if marked:
            raise SharedError("shared KB root is not in the approved private profile")
        return None
    return dict(_validated(profile), kb=name)


def require_profile(root: Path) -> dict:
    profile = profile_for(root)
    if profile is None:
        raise SharedError("this KB is not configured for shared writes")
    return profile


def clean_head(root: Path) -> str:
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    if status.returncode or status.stdout:
        raise SharedError("KB has local source changes; reconcile them before shared writes")
    result = git(root, "rev-parse", "HEAD")
    if result.returncode:
        raise SharedError("cannot read KB source revision")
    return result.stdout.strip()


def _operation_id(value=None) -> str:
    try:
        result = str(uuid.UUID(value)) if value is not None else str(uuid.uuid4())
    except (ValueError, AttributeError, TypeError):
        raise SharedError("operation ID must be a UUID") from None
    if value is not None and value != result:
        raise SharedError("operation ID must use canonical lowercase UUID form")
    return result


def _directory(root: Path, name: str) -> Path:
    for path in [root / ".index", root / ".index/shared-write",
                 root / ".index/shared-write" / name]:
        if path.is_symlink():
            raise SharedError("shared-write state directories must not be symlinks")
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        else:
            _sync_dir(path.parent)
        if path.stat().st_uid != os.getuid():
            raise SharedError("shared-write state must belong to the current user")
        path.chmod(0o700)
    return path


def _canonical(data) -> bytes:
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _persist(path: Path, data, *, replace=False) -> None:
    raw = _canonical(data)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            if path.is_symlink():
                raise SharedError("shared-write receipt must not be a symlink")
            os.replace(temp, path)
        else:
            try:
                os.link(temp, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != raw:
                    raise SharedError(
                        "operation ID already records a different request; use mem retry "
                        "for its original payload, or a new ID for a reconciled edit"
                    ) from None
        _sync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def transport(profile: dict, envelope: dict) -> dict:
    command = [profile["receiver_python"], profile["receiver"]]
    if profile["machine"] == "laptop":
        t = profile["transport"]
        command = [
            "/usr/bin/ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-o", "ConnectionAttempts=1", "-o", "StrictHostKeyChecking=yes",
            "-o", "ForwardAgent=no", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", f"HostName={t['hostname']}", "-o", f"User={t['user']}",
            "-o", f"Port={t['port']}", "-o", "ProxyCommand=none", "-o", "ProxyJump=none",
            t["alias"], shlex.join(command),
        ]
    try:
        result = subprocess.run(
            command, input=_canonical(envelope).decode(), text=True, capture_output=True,
            timeout=150, env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SharedError("private write transport unavailable or timed out") from None
    if result.returncode:
        raise SharedError("private write transport failed; its outcome may be unknown")
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise SharedError("private write transport returned an unreadable acknowledgment") from None


def refresh(profile: dict) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, profile["refresh"], profile["kb"]], capture_output=True, text=True,
            timeout=180, env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise SharedError("replica refresh unavailable or timed out") from None
    if result.returncode:
        raise SharedError("replica refresh failed; committed host save is preserved")
    reconcile_refreshed_receipts(Path(profile["roots"][profile["kb"]]))
    return True


def reconcile_refreshed_receipts(root: Path) -> None:
    """A refreshed descendant proves a previously acknowledged save is present."""
    try:
        with coordinator.read_lock(root):
            head = clean_head(root)
            for path in _directory(root, "receipts").glob("*.json"):
                if path.is_symlink():
                    raise SharedError("shared-write receipt must not be a symlink")
                receipt = json.loads(path.read_text())
                commit = receipt.get("commit")
                if (receipt.get("status") == "applied" and receipt.get("replica_current") is False
                        and isinstance(commit, str)
                        and re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit)
                        and git(root, "merge-base", "--is-ancestor", commit, head).returncode == 0):
                    receipt["replica_current"] = True
                    _persist(path, receipt, replace=True)
    except (OSError, ValueError, coordinator.CoordinatorError):
        raise SharedError("replica refreshed; receipt reconciliation still needs attention") from None


def _send(root: Path, profile: dict, envelope: dict) -> dict:
    operation = envelope["request"]["operation_id"]
    try:
        result = transport(profile, envelope)
        if (not isinstance(result, dict) or result.get("protocol") != 1
                or result.get("operation_id") != operation
                or result.get("status") not in TERMINAL | {"pending", "busy", "error"}):
            raise SharedError("private write acknowledgment does not match this request")
        if result["status"] == "applied":
            expected = {
                item["slug"]: None if item["content"] is None else version(item["content"].encode())
                for item in envelope["request"]["mutations"]
            }
            commit = result.get("commit")
            if (not isinstance(commit, str) or not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit)
                    or result.get("versions") != expected):
                raise SharedError("private write acknowledgment does not verify the submitted source")
    except SharedError:
        result = {"protocol": 1, "operation_id": operation, "status": "pending",
                  "code": "transport_unknown"}
    if result["status"] == "applied":
        try:
            result["replica_current"] = refresh(profile)
        except SharedError:
            result["replica_current"] = False
    _persist(_directory(root, "receipts") / f"{operation}.json", result, replace=True)
    return result


def submit(root: Path, mutations: list, *, operation_id=None, expected_head=None) -> dict:
    profile = require_profile(root)
    operation = _operation_id(operation_id)
    request = {"protocol": 1, "operation_id": operation, "mutations": mutations}
    if expected_head is not None:
        request["expected_head"] = expected_head
    envelope = {"kb": profile["kb"], "request": request}
    if len(_canonical(envelope)) > MAX_REQUEST:
        raise SharedError("shared-write request exceeds 16 MiB; split the proposed batch before saving")
    _persist(_directory(root, "requests") / f"{operation}.json", envelope)
    return _send(root, profile, envelope)


def retry(root: Path, operation_id: str) -> dict:
    profile = require_profile(root)
    operation = _operation_id(operation_id)
    path = _directory(root, "requests") / f"{operation}.json"
    try:
        if path.is_symlink() or path.stat().st_mode & 0o077:
            raise SharedError("retry request must be an owner-only regular file")
        envelope = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SharedError("no readable durable request for that operation ID") from None
    if (envelope.get("kb") != profile["kb"]
            or envelope.get("request", {}).get("operation_id") != operation):
        raise SharedError("retry request does not match this KB and operation ID")
    return _send(root, profile, envelope)


def pending(root: Path) -> list:
    require_profile(root)
    requests = _directory(root, "requests")
    receipts = _directory(root, "receipts")
    result = []
    for path in sorted(requests.glob("*.json")):
        operation = _operation_id(path.stem)
        receipt = receipts / path.name
        status = "pending"
        if receipt.exists():
            try:
                data = json.loads(receipt.read_text())
                status = data.get("status", "pending")
                if status == "applied" and data.get("replica_current") is False:
                    status = "refresh_pending"
            except (OSError, ValueError):
                pass
        if status not in TERMINAL:
            result.append({"operation_id": operation, "status": status})
    return result


def report(result: dict, *, json_output=False) -> int:
    status, operation = result["status"], result["operation_id"]
    if json_output:
        print(json.dumps(result, sort_keys=True))
    elif status == "applied":
        print(f"saved on the shared host: operation {operation}")
        if result.get("replica_current") is False:
            print("Local replica refresh is pending; run mem refresh.", file=sys.stderr)
    elif status == "conflict":
        print(f"conflict: operation {operation}; re-read the current concept, reconcile "
              "your edit, and submit a new operation", file=sys.stderr)
    elif status in {"pending", "busy"}:
        if result.get("action_required"):
            print(f"pending: operation {operation}; code={result.get('code', 'unknown')}; "
                  "inspect the host recovery state before retrying; retain this operation ID",
                  file=sys.stderr)
        elif result.get("pending_operation_id"):
            print(f"pending: operation {operation}; earlier host operation "
                  f"{result['pending_operation_id']} needs recovery first; retain both IDs",
                  file=sys.stderr)
        else:
            print(f"pending: operation {operation}; retry exactly this request with "
                  f"mem retry {operation}", file=sys.stderr)
    else:
        print(f"attention required: operation {operation}; code={result.get('code', 'unknown')}; "
              "retain its durable request and inspect the host state before retrying",
              file=sys.stderr)
    return 0 if status == "applied" else 3 if status in {"pending", "busy"} else 2


def cmd_retry(args) -> int:
    try:
        return report(retry(config.kb_root(), args.operation_id), json_output=args.json)
    except SharedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def cmd_pending(args) -> int:
    try:
        rows = pending(config.kb_root())
        if args.json:
            print(json.dumps(rows))
        else:
            for row in rows:
                print(f"{row['operation_id']} {row['status']}")
            if not rows:
                print("No pending shared writes.")
        return 0
    except SharedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def cmd_refresh(args) -> int:
    try:
        refresh(require_profile(config.kb_root()))
        print("Private KB replica refreshed.")
        return 0
    except SharedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def cmd_delete(args) -> int:
    try:
        root = config.kb_root()
        require_profile(root)
        clean_head(root)
        if not re.fullmatch(r"[a-f0-9]{64}", args.expected_version):
            raise SharedError("--expected-version must be the version from mem get --json")
        result = submit(root, [{
            "slug": args.slug, "expected_version": args.expected_version, "content": None,
        }], operation_id=args.operation_id)
        return report(result, json_output=args.json)
    except SharedError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
