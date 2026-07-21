"""`mem doctor` - diagnose the KB environment, truthfully, for life.

Each check reports ok / fail / skip on its own line; any failing check makes
the exit code nonzero so an agent can act on the diagnosis instead of guessing.
"""

import json
import sqlite3
from dataclasses import asdict, dataclass

from agent_memory import blocks, config, gitkb, ollama, vector


@dataclass
class Check:
    name: str
    status: str  # ok | fail | skip
    detail: str
    required: bool = True


_BLOCK_PROBLEMS = {
    "missing": "{path} missing - run: mem init",
    "no-block": "no managed block in {path} - run: mem init",
    "duplicate": "duplicate managed blocks in {path} - run: mem init",
    "stale": "managed block outdated or edited in {path} - run: mem init",
}


def run_checks(mutate: bool = True) -> list[Check]:
    """mutate=False is the non-mutating diagnosis path (used by `mem init`):
    it reports queue depth without draining, so init never touches the
    derived index (F1 idempotence: KB home unchanged on a second run)."""
    checks: list[Check] = []
    root = config.kb_root()

    kb_ok = (root / "concepts").is_dir() and (root / ".index").is_dir()
    checks.append(
        Check(
            "kb-home",
            "ok" if kb_ok else "fail",
            str(root) if kb_ok else f"{root} missing or incomplete - run: mem init",
        )
    )

    if not kb_ok:
        checks.append(Check("git-repo", "skip", "no KB home"))
        checks.append(Check("no-remote", "skip", "no KB home"))
    elif not gitkb.is_repo(root):
        checks.append(Check("git-repo", "fail", f"{root} is not a git repository - run: mem init"))
        checks.append(Check("no-remote", "skip", "no git repository"))
    else:
        checks.append(Check("git-repo", "ok", "local repository present"))
        remote_names = gitkb.remotes(root)
        if remote_names:
            first = remote_names[0]
            url = gitkb.remote_url(root, first) or "no url"
            more = f" and {len(remote_names) - 1} more" if len(remote_names) > 1 else ""
            checks.append(
                Check(
                    "no-remote",
                    "fail",
                    f"remote '{first}' configured ({url}){more}"
                    f" - the KB must stay local-only; remove: git -C {root} remote remove {first}",
                )
            )
        else:
            checks.append(Check("no-remote", "ok", "no remotes configured"))

    for check_name, path, block_name in (
        ("blocks-claude", config.claude_md_path(), blocks.CLAUDE_BLOCK),
        ("blocks-agents", config.agents_md_path(), blocks.AGENTS_BLOCK),
    ):
        state = blocks.status_of(path, block_name)
        if state == "current":
            checks.append(Check(check_name, "ok", f"current ({path})"))
        else:
            checks.append(Check(check_name, "fail", _BLOCK_PROBLEMS[state].format(path=path)))

    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(content)")
        con.close()
        checks.append(Check("fts5", "ok", f"available (sqlite {sqlite3.sqlite_version})"))
    except sqlite3.Error as e:
        checks.append(Check("fts5", "fail", f"FTS5 unavailable in this Python ({e})"))

    base = config.ollama_base_url()
    daemon_up = False
    try:
        version = ollama.check_version(base)
        checks.append(Check("ollama", "ok", f"reachable at {base} (version {version})"))
        daemon_up = True
    except ollama.OllamaError as e:
        checks.append(Check("ollama", "fail", str(e)))

    model = config.embed_model()
    want_dims = config.embed_dims()
    if not daemon_up:
        checks.append(Check("embed-model", "skip", "ollama unreachable"))
    else:
        try:
            dims = ollama.probe_embed_dims(base, model)
            if dims == want_dims:
                checks.append(Check("embed-model", "ok", f"{model} embeds at {dims} dims"))
            else:
                checks.append(
                    Check(
                        "embed-model",
                        "fail",
                        f"{model} returns {dims} dims, expected {want_dims}"
                        " - pull the expected model or set MEM_EMBED_MODEL/MEM_EMBED_DIMS",
                    )
                )
        except ollama.OllamaError as e:
            checks.append(Check("embed-model", "fail", str(e)))

    # Doctor drains the embed queue fully (F4): pending items are only a
    # failure when the daemon is up and they still cannot be embedded.
    if not kb_ok:
        checks.append(Check("embed-queue", "skip", "no KB home"))
    else:
        pending = vector.queue_size(root)
        if pending == 0:
            checks.append(Check("embed-queue", "ok", "queue empty"))
        elif not daemon_up:
            checks.append(
                Check(
                    "embed-queue",
                    "skip",
                    f"{pending} pending embedding(s) - they drain when ollama returns",
                )
            )
        elif not mutate:
            checks.append(
                Check(
                    "embed-queue",
                    "ok",
                    f"{pending} pending embedding(s) - drain via mem doctor/reindex",
                )
            )
        else:
            drained, remaining, error = vector.drain_fully(root)
            if remaining == 0:
                checks.append(Check("embed-queue", "ok", f"drained {drained} pending embedding(s)"))
            else:
                checks.append(
                    Check("embed-queue", "fail", f"{remaining} embedding(s) stuck: {error}")
                )

    return checks


def cmd_doctor(args) -> int:
    checks = run_checks()
    failed = [c for c in checks if c.status == "fail"]
    ok = not failed
    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        tags = {"ok": "ok  ", "fail": "FAIL", "skip": "skip"}
        for c in checks:
            print(f"{tags[c.status]}  {c.name}: {c.detail}")
        print(f"doctor: {'ok' if ok else 'FAIL'} ({len(checks) - len(failed)}/{len(checks)} checks passed)")
    return 0 if ok else 1
