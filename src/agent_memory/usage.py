"""Usage log + stats (D8): every CLI invocation appends one JSON line to
`.index/usage.jsonl`. The log answers "how often do agents actually use the KB"
- data the git history only provides for writes. Unlike the rest of `.index/`
it is NOT derived state: reindex must leave it alone (proved by test), and it
stays out of git (`.index/` is ignored wholesale).

Best-effort by design: a logging failure must never break a KB operation.
"""

import datetime
import json
import subprocess

from agent_memory import config

_ARG_KEYS = ("query", "slug", "title", "candidates")  # first present wins


def log_path(root):
    return root / ".index" / "usage.jsonl"


def log_event(root, command: str, args, rc: int, ms: int) -> None:
    try:
        arg = next(
            (str(getattr(args, k)) for k in _ARG_KEYS
             if getattr(args, k, None) not in (None, "-")),
            "",
        )
        line = json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cmd": command,
            "arg": arg[:80],
            "rc": rc,
            "ms": ms,
        })
        p = log_path(root)
        p.parent.mkdir(exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # never let telemetry break the KB


def cmd_stats(args) -> int:
    root = config.kb_root()
    days = args.days
    cutoff = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    events = []
    p = log_path(root)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("ts", "") >= cutoff:
                events.append(e)

    by_cmd, by_day = {}, {}
    for e in events:
        by_cmd[e["cmd"]] = by_cmd.get(e["cmd"], 0) + 1
        day = e["ts"][:10]
        by_day[day] = by_day.get(day, 0) + 1

    try:
        saves = int(subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count",
             f"--since={days} days ago", "--grep=^mem \\(save\\|update\\)", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip() or 0)
    except Exception:
        saves = None

    print(f"usage over the last {days} day(s):")
    if not events:
        print("  no logged invocations (log began when this feature shipped)")
    for cmd in sorted(by_cmd, key=lambda c: -by_cmd[c]):
        print(f"  {cmd:8s} {by_cmd[cmd]}")
    if by_day:
        print("by day:")
        for day in sorted(by_day):
            print(f"  {day}  {by_day[day]}")
    if saves is not None:
        print(f"saves/updates in git (last {days}d): {saves}")
    return 0
