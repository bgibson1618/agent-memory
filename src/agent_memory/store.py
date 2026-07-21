"""`mem save` / `mem get` / `mem list` - durable concept capture.

Markdown is the database: one OKF file per concept under concepts/, written
atomically (temp file + rename) under the single inter-process write lock,
then committed to the local git - exactly one commit per successful save,
message naming the slug. Saving onto an existing slug errors unless --update.
"""

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from agent_memory import config, gitkb, okf


class StoreError(Exception):
    """A one-line, agent-actionable error."""


def concepts_dir(root: Path) -> Path:
    return root / "concepts"


def concept_path(root: Path, slug: str) -> Path:
    return concepts_dir(root) / f"{slug}.md"


def require_kb(root: Path) -> None:
    if not concepts_dir(root).is_dir() or not gitkb.is_repo(root):
        raise StoreError(f"no KB home at {root} - run: mem init")


def warn_if_remote(root: Path) -> None:
    remote_names = gitkb.remotes(root)
    if remote_names:
        print(
            f"warning: KB git repo has remote(s): {', '.join(remote_names)}"
            f" - the KB must stay local-only; remove: git -C {root} remote remove {remote_names[0]}",
            file=sys.stderr,
        )


@contextmanager
def write_lock(root: Path):
    """The single inter-process write lock (ARCHITECTURE): file write + git
    commit + index update happen inside it. Blocking flock - contenders wait,
    they never error."""
    lock_path = root / ".index" / "write.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _sweep_dead_temps(directory: Path) -> None:
    """Drop temp files whose writer is gone, so a crashed save leaves no debris
    for a later `git add -A` to sweep into history. Runs under the write lock;
    a live writer's pid answers kill(pid, 0), so its temp is left alone."""
    for tmp in directory.glob(".*.tmp"):
        try:
            os.kill(int(tmp.name.split(".")[-2]), 0)
        except (ValueError, IndexError, ProcessLookupError):
            tmp.unlink(missing_ok=True)
        except PermissionError:
            pass  # pid exists under another uid - not ours, leave it


def atomic_write(path: Path, text: str) -> None:
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    if os.environ.get("MEM_FAULT") == "save-crash-before-rename":
        os._exit(70)  # test seam: a save killed mid-write must leave no partial file
    os.replace(tmp, path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def load(root: Path, slug: str) -> okf.Concept:
    path = concept_path(root, slug)
    if not path.is_file():
        raise StoreError(f"no concept '{slug}'")
    try:
        return okf.parse(path.read_text(encoding="utf-8"))
    except okf.OKFError as e:
        raise StoreError(f"{path}: {e}") from e


def _split_csv(raw) -> list:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _derive_description(body: str) -> str:
    for line in body.splitlines():
        line = " ".join(line.split())
        if line:
            return line if len(line) <= 200 else line[:197] + "..."
    return ""


def cmd_save(args) -> int:
    try:
        return _save(args)
    except (StoreError, okf.OKFError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _save(args) -> int:
    root = config.kb_root()
    require_kb(root)
    warn_if_remote(root)

    body = args.body if args.body is not None else sys.stdin.read()
    if not body.strip():
        raise StoreError("empty body - pass --body or pipe markdown on stdin")
    slug = okf.slugify(args.slug or args.title)
    path = concept_path(root, slug)
    stamp = okf.now_stamp()

    if args.update:
        existing = load(root, slug)  # errors "no concept '<slug>'" if absent
        created = existing.created
    else:
        if path.exists():
            raise StoreError(f"concept '{slug}' exists - pass --update to modify it")
        created = stamp

    concept = okf.Concept(
        slug=slug,
        title=args.title,
        description=args.description or _derive_description(body),
        type=args.type,
        topics=_split_csv(args.topics),
        sensitivity=args.sensitivity,
        created=created,
        updated=stamp,
        related=[okf.slugify(r) for r in _split_csv(args.related)],
        body=body,
    )
    text = okf.serialize(concept)

    with write_lock(root):
        if not args.update and path.exists():  # collision check redone under the lock
            raise StoreError(f"concept '{slug}' exists - pass --update to modify it")
        _sweep_dead_temps(concepts_dir(root))
        atomic_write(path, text)
        verb = "update" if args.update else "save"
        gitkb.commit_path(root, f"concepts/{slug}.md", f"mem {verb}: {slug}")

    print(f"{'updated' if args.update else 'saved'}: {slug} ({path})")
    return 0


def cmd_get(args) -> int:
    root = config.kb_root()
    try:
        require_kb(root)
        concept = load(root, args.slug)
    except StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        data = concept.to_dict()
        data["path"] = str(concept_path(root, concept.slug or args.slug))
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"slug: {args.slug}")
        print(f"title: {concept.title}")
        print(f"type: {concept.type}")
        print(f"sensitivity: {concept.sensitivity}")
        print(f"topics: {', '.join(concept.topics)}")
        print(f"related: {', '.join(concept.related)}")
        print(f"created: {concept.created}")
        print(f"updated: {concept.updated}")
        print(f"description: {concept.description}")
        print()
        print(concept.body.rstrip())
    return 0


def cmd_list(args) -> int:
    root = config.kb_root()
    try:
        require_kb(root)
    except StoreError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    concepts = []
    for path in sorted(concepts_dir(root).glob("*.md")):
        try:
            concepts.append(okf.parse(path.read_text(encoding="utf-8")))
        except okf.OKFError as e:
            print(f"warning: skipping {path}: {e}", file=sys.stderr)

    if args.json:
        summaries = []
        for concept in concepts:
            data = concept.to_dict()
            del data["body"]
            data["path"] = str(concept_path(root, concept.slug))
            summaries.append(data)
        print(json.dumps(summaries, indent=2, ensure_ascii=False))
    else:
        for concept in concepts:
            print(f"{concept.slug}  [{', '.join(concept.topics)}]  {concept.title}")
    return 0
