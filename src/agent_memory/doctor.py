"""`mem doctor` - diagnose the KB environment, truthfully, for life.

Each check reports ok / fail / skip on its own line; any failing check makes
the exit code nonzero so an agent can act on the diagnosis instead of guessing.
"""

import hashlib
import json
import sqlite3
import sys
import sysconfig
from dataclasses import asdict, dataclass
from pathlib import Path

import agent_memory
from agent_memory import blocks, config, gitkb, graph, ollama, vector


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


def runtime_identity() -> dict:
    """Which package this interpreter imports and how it got there: a frozen
    release (release.json beside it), a worktree (an editable install), or an
    installed copy; plus any zz_agent_memory_*.pth selector in this
    interpreter's site-packages. Lets a stale or surprising deployment be seen
    instead of assumed (Stage 1, 2026-11)."""
    package = Path(agent_memory.__file__).resolve().parent
    identity = {"package": str(package), "version": agent_memory.__version__,
                "python": sys.executable, "release": None, "selectors": {}}
    release_json = package.parent.parent.parent / "release.json"
    if release_json.is_file():
        try:
            identity["release"] = json.loads(release_json.read_text()).get("id")
        except ValueError:
            identity["release"] = "unreadable"
    site = Path(sysconfig.get_paths()["purelib"])
    for pth in sorted(site.glob("zz_agent_memory_*.pth")):
        identity["selectors"][pth.name] = hashlib.sha256(pth.read_bytes()).hexdigest()[:16]
    if identity["release"]:
        identity["kind"] = "release"
    elif any(p.name.endswith(".pth") and "agent_memory" in p.name and not p.name.startswith("zz_")
             for p in site.glob("*.pth")):
        identity["kind"] = "worktree (editable install)"
    elif site in package.parents:
        identity["kind"] = "installed copy"
    else:
        identity["kind"] = "source checkout"
    return identity


def runtime_check() -> Check:
    ident = runtime_identity()
    where = f"release {ident['release']}" if ident["release"] else ident["kind"]
    sel = ", ".join(f"{n} ({h})" for n, h in ident["selectors"].items()) or "none"
    return Check("runtime", "ok", f"{where}: {ident['package']}; selector: {sel}; python {ident['python']}",
                 required=False)


def run_checks(mutate: bool = True) -> list[Check]:
    """mutate=False is the non-mutating diagnosis path (used by `mem init`):
    it reports queue depth without draining, so init never touches the
    derived index (F1 idempotence: KB home unchanged on a second run)."""
    checks: list[Check] = [runtime_check()]
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
        disallowed = gitkb.disallowed_remotes(root)
        if disallowed:
            first, url = disallowed[0]
            more = f" and {len(disallowed) - 1} more" if len(disallowed) > 1 else ""
            checks.append(
                Check(
                    "no-remote",
                    "fail",
                    f"remote '{first}' configured ({url}){more} is not listed in"
                    f" {root / gitkb.ALLOWED_REMOTES_FILE}"
                    f" - remove it (git -C {root} remote remove {first}) or, if it is the"
                    f" work host over Tailscale (D1), list its exact URL there",
                )
            )
        elif remote_names:
            listed = ", ".join(f"{n} ({gitkb.remote_url(root, n)})" for n in remote_names)
            checks.append(
                Check("no-remote", "ok", f"remote(s) listed in {gitkb.ALLOWED_REMOTES_FILE}: {listed}")
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
            # The version check above proved the daemon alive, so a slow probe
            # here means a cold model load, not a hang: the long budget lets
            # the load complete instead of flapping FAIL right after a restart.
            dims = ollama.probe_embed_dims(base, model, timeout=ollama.cold_timeout())
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

    # Link health is informational, never a failure: a dangling link can be a
    # deliberate worth-writing-later marker. The count stays visible in every
    # doctor run so drift cannot regrow silently (D12); `mem links` details it.
    if not kb_ok:
        checks.append(Check("dangling-links", "skip", "no KB home", required=False))
    else:
        report = graph.load(root).dangling()
        if not report:
            checks.append(
                Check("dangling-links", "ok", "every wikilink/related target resolves", required=False)
            )
        else:
            references = sum(len(refs) for refs in report.values())
            checks.append(
                Check(
                    "dangling-links",
                    "ok",
                    f"{len(report)} unresolved target(s) across {references} reference(s)"
                    " - informational; detail: mem links",
                    required=False,
                )
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
