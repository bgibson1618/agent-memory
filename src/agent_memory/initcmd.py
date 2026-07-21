"""`mem init` - create and verify the KB home; install agent instruction blocks.

Idempotent: a second run exits 0 with the KB home unchanged (the managed
instruction blocks may refresh in place). Never configures a git remote.
Environment problems (Ollama down, etc.) warn but never fail init - the KB
must be creatable offline; `mem doctor` is the failing diagnosis.
"""

import sys

from agent_memory import blocks, config, doctor, gitkb


def cmd_init(args) -> int:
    root = config.kb_root()
    fresh = not gitkb.is_repo(root)

    (root / "concepts").mkdir(parents=True, exist_ok=True)
    (root / ".index").mkdir(parents=True, exist_ok=True)

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".index/\n", encoding="utf-8")

    if not gitkb.is_repo(root):
        gitkb.init_repo(root)
        gitkb.commit_all(root, "mem init: create KB home")

    remote_names = gitkb.remotes(root)
    if remote_names:
        print(
            f"warning: KB git repo has remote(s): {', '.join(remote_names)}"
            f" - the KB must stay local-only; remove: git -C {root} remote remove {remote_names[0]}",
            file=sys.stderr,
        )

    results = []
    for path, name in (
        (config.claude_md_path(), blocks.CLAUDE_BLOCK),
        (config.agents_md_path(), blocks.AGENTS_BLOCK),
    ):
        results.append(f"{blocks.install(path, name)}: {path}")

    if fresh:
        print(f"initialized: {root} (concepts/, .index/, git - no remote)")
    else:
        print(f"ok: {root} already initialized")
    print("blocks: " + "; ".join(results))

    failing = [c for c in doctor.run_checks(mutate=False) if c.status == "fail"]
    if failing:
        names = ", ".join(c.name for c in failing)
        print(
            f"warning: {len(failing)} check(s) failing ({names}) - run: mem doctor",
            file=sys.stderr,
        )
    return 0
