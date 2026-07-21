"""F12 in-process egress guard - the fast inner layer of the zero-egress proof.

Any Python process launched with this directory on PYTHONPATH imports this
module automatically at interpreter startup (the `site` machinery), so the
test suite can arm every `mem` subprocess without touching product code.

sys.addaudithook sees every socket.connect made by *Python* code in the
process: each attempt is appended to MEM_EGRESS_LOG as one JSON line, and in
enforce mode a non-loopback peer raises before the syscall ever runs. What an
audit hook cannot see - subprocess egress (git) and libc-internal DNS - is
exactly what the loopback-only network namespace in test_f12_egress.py
catches; the two layers are a set.

Env contract (the module is inert when MEM_EGRESS_GUARD is unset):
  MEM_EGRESS_GUARD  enforce | record
  MEM_EGRESS_LOG    append-only JSONL of every observed connect attempt
"""

import ipaddress
import json
import os
import sys

_MODE = os.environ.get("MEM_EGRESS_GUARD", "")
_LOG = os.environ.get("MEM_EGRESS_LOG", "")


def _peer(address) -> dict:
    """Normalize a connect() address: AF_UNIX paths are str/bytes, AF_INET is
    (host, port), AF_INET6 is (host, port, flowinfo, scope_id)."""
    if isinstance(address, (str, bytes)):
        text = address if isinstance(address, str) else address.decode("utf-8", "replace")
        return {"family": "unix", "address": text}
    if isinstance(address, tuple) and len(address) >= 2:
        return {"family": "inet", "host": str(address[0]), "port": int(address[1])}
    return {"family": "other", "address": repr(address)}


def _is_loopback(peer: dict) -> bool:
    if peer["family"] == "unix":
        return True  # filesystem sockets never leave the machine
    if peer["family"] != "inet":
        return False
    host = peer["host"].partition("%")[0]  # strip any IPv6 scope id
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _record(peer: dict, allowed: bool) -> None:
    if not _LOG:
        return
    try:
        # One short O_APPEND write per event: safe across the sequential
        # subprocesses the suite runs against a shared log.
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"peer": peer, "allowed": allowed}) + "\n")
    except OSError:
        pass  # the log is evidence, never a reason to change behavior


def _hook(event: str, args) -> None:
    if event != "socket.connect":
        return
    peer = _peer(args[1])
    allowed = _is_loopback(peer)
    _record(peer, allowed)
    if not allowed and _MODE == "enforce":
        raise RuntimeError(f"mem egress guard: blocked non-loopback connect to {peer}")


if _MODE:
    sys.addaudithook(_hook)
