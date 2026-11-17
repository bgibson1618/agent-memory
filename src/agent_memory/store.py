"""`mem save` / `mem get` / `mem list` - durable concept capture.

Markdown is the database: one OKF file per concept under concepts/, written
atomically (temp file + rename) under the single inter-process write lock,
then committed to the local git - exactly one commit per successful save,
message naming the slug - and reflected in the lexical index in-line. Saving
onto an existing slug errors unless --update, which MERGES into the stored
concept (D19): an omitted field keeps its stored value, an explicit field
replaces it (warned on stderr), and --clear blanks a clearable field instead.
"""

import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from agent_memory import config, coordinator, gitkb, graph, lexical, okf, ollama, shared, vector


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
    """Warn on every write about a remote that .allowed-remotes does not list (D1)."""
    disallowed = gitkb.disallowed_remotes(root)
    if disallowed:
        names = ", ".join(f"{n} ({u})" for n, u in disallowed)
        print(
            f"warning: KB git repo has remote(s) not listed in {gitkb.ALLOWED_REMOTES_FILE}: {names}"
            f" - remove: git -C {root} remote remove {disallowed[0][0]}",
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
    except (StoreError, okf.OKFError, shared.SharedError, coordinator.CoordinatorError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _dedup_check(root: Path, concept: okf.Concept) -> None:
    """D18 S8 - `mem save --dedup-check`'s advisory-only detector run: the
    full `dedup.detect()` report to STDERR, after the save has already
    landed. Never blocks, never changes the exit code, never touches the
    KB - D3 Sec66-69 made the `mem save` bypass the designed recourse for
    umbrella/member overrides, and this flag must not quietly take that
    back. Any daemon/config/index trouble degrades to a one-line stderr note
    instead of a failure, since there is nothing left to refuse into - the
    write already committed (D18 W3 fix cycle, gate finding 4: this covers
    `vector.VectorError` too - e.g. a model swap since the index was built -
    not just the embed call's own `ollama.OllamaError`, which was already
    caught around that one call but let every OTHER detector/index failure
    upstream and downstream of it propagate uncaught).

    Deferred import: `dedup.py` imports `store` (for `Corpus.concept()`'s
    `store.load`/`store.StoreError`), so a module-level `from agent_memory
    import dedup` here would be circular; importing inside the function
    body resolves fine because both modules are already fully loaded by
    the time a real `mem save --dedup-check` invocation reaches this call."""
    from agent_memory import dedup

    try:
        cfg = dedup.load_config()
        corpus = dedup.build_corpus(root, cfg)
    except dedup.DedupError as e:
        print(f"dedup-check: skipped (invalid dedup config: {e})", file=sys.stderr)
        return
    except vector.VectorError as e:
        print(f"dedup-check: skipped ({e})", file=sys.stderr)
        return
    try:
        corpus.embed_model = config.embed_model()
        vec = None
        try:
            text = vector.embed_text(concept)
            vec = ollama.embed(
                config.ollama_base_url(), config.embed_model(), [text],
                timeout=vector.FULL_DRAIN_TIMEOUT,
            )[0]
            # W3b gate finding 1: the semantic legs' identity is model AND
            # digest - resolve it exactly as `mem dedup` does, so a stale
            # same-model claim/chunk row is refused and repopulated here too.
            # `model_digest` never fails over metadata: with /api/tags
            # unavailable it yields 'unknown', which is stamped and compared
            # exactly as standalone `mem dedup` does - identical identity
            # semantics on both surfaces, never a silent cross-space compare.
            corpus.embed_digest = ollama.model_digest(config.ollama_base_url(), config.embed_model())
        except ollama.OllamaError as e:
            vec = None
            print(f"dedup-check: semantic legs skipped ({e})", file=sys.stderr)
        report = dedup.detect(corpus, concept, vec)
        print(f"dedup-check: verdict={report['verdict']} flagged={report['flagged']}", file=sys.stderr)
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
    except (vector.VectorError, dedup.DedupError, StoreError, ollama.OllamaError) as e:
        print(f"dedup-check: skipped ({e})", file=sys.stderr)
    finally:
        corpus.close()


# D19: fields an --update may blank explicitly instead of merging. Not listed
# here (source, body, title, slug, created, updated, type, sensitivity) are
# refused by _validate_clear - source in particular never degrades (D9); set
# the others explicitly instead of clearing them.
CLEARABLE_FIELDS = ("description", "topics", "related")

# Fields compared old-vs-new to decide whether a --update warrants the D19
# loud-change report; created/updated are expected to move on every update and
# are not "replaced" in the sense this warns about.
_WARN_FIELDS = ("title", "description", "type", "sensitivity", "topics", "related", "source", "body")


def _parse_clear(raw) -> list:
    fields = []
    for item in raw or []:
        for field in _split_csv(item):
            if field not in fields:
                fields.append(field)
    return fields


def _validate_clear(fields: list, args) -> None:
    explicit = {"description": args.description, "topics": args.topics, "related": args.related}
    for field in fields:
        if field == "source":
            raise StoreError(
                "--clear source is refused - provenance never degrades (D9);"
                " pass a new --source to replace it"
            )
        if field not in CLEARABLE_FIELDS:
            raise StoreError(f"--clear {field} is refused - set --{field} explicitly instead")
        if explicit.get(field) is not None:
            raise StoreError(f"--clear {field} conflicts with --{field} - pass one or the other")


def _field_repr(value, elide: bool = False) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    text = " ".join(str(value).split())  # collapse a multi-line body onto one line
    if not text:
        return "(empty)"
    if elide and len(text) > 80:
        return text[:77] + "..."
    return text


def _report_update_changes(existing: okf.Concept, new: okf.Concept) -> None:
    """D19: loud, non-blocking stderr report of every field an --update is
    about to replace or clear - printed before the write so an agent-driven
    caller sees exactly what changed, unlike the silent clobber this replaces.
    Ruling 5 permits elision only for long bodies; every other field is shown
    in full so the value an audit needs is never the part that got truncated."""
    for field in _WARN_FIELDS:
        old_value = getattr(existing, field)
        new_value = getattr(new, field)
        if old_value == new_value:
            continue
        elide = field == "body"
        print(
            f"warning: --update replaces {field}: "
            f"{_field_repr(old_value, elide)} -> {_field_repr(new_value, elide)}",
            file=sys.stderr,
        )


def _save(args) -> int:
    root = config.kb_root()
    require_kb(root)
    shared_profile = shared.profile_for(root)
    expected = getattr(args, "expected_version", None)
    if shared_profile:
        shared.clean_head(root)
        if args.update and not expected:
            raise StoreError(
                "shared updates require --expected-version from the concept's mem get --json "
                "read; refresh and reconcile before replacing a stale version"
            )
    elif args.update and not expected:
        raise StoreError(
            "updates require --expected-version from the concept's mem get --json "
            "read; re-read and reconcile before replacing a stale version"
        )
    if expected is not None and (not args.update or not re.fullmatch(r"[a-f0-9]{64}", expected)):
        raise StoreError("--expected-version must be the read version for an --update")
    warn_if_remote(root)

    # D19: check the RAW argument, before CSV-parsing drops empty pieces - a
    # supplied `--clear ""` must not look like "no --clear" to the checks below.
    raw_clear = getattr(args, "clear", None)
    clear_fields = _parse_clear(raw_clear)
    if not args.update:
        if raw_clear:
            raise StoreError("--clear is only valid with --update")
        if not args.title:
            raise StoreError("--title is required")
    elif not args.title and not args.slug:
        raise StoreError("--update requires --title or --slug to locate the concept")
    if raw_clear and not clear_fields:
        raise StoreError("--clear requires at least one field name")
    _validate_clear(clear_fields, args)

    slug = okf.slugify(args.slug or args.title)
    path = concept_path(root, slug)
    stamp = okf.now_stamp()

    if not args.update and path.exists():
        # Non-authoritative early exit: a doomed fresh save shouldn't consume
        # stdin first. The lock below redoes this check authoritatively.
        raise StoreError(f"concept '{slug}' exists - pass --update to modify it")

    # D19 fix: a blocking stdin read must never happen while the write lock is
    # held - that stalls every other writer behind it. Read stdin here, before
    # locking; only the state-dependent merge below happens under the lock.
    piped_body = None
    fresh_body_input = ""
    if args.body is None:
        if args.update:
            if not sys.stdin.isatty():
                piped = sys.stdin.read()
                piped_body = piped if piped.strip() else None
        else:
            fresh_body_input = sys.stdin.read()

    with (coordinator.read_lock(root) if shared_profile else write_lock(root)):
        if args.update:
            if shared_profile:
                if not path.is_file():
                    raise StoreError(f"no concept '{slug}'; refresh the private replica first")
                raw = path.read_bytes()
                if shared.version(raw) != expected:
                    raise StoreError("stale local read version; refresh, re-read, and reconcile the edit")
                existing = okf.parse(raw.decode("utf-8"))
            else:
                existing = load(root, slug)  # errors "no concept '<slug>'" if absent
                # Compared under the writer lock: the token is the sha256 of the
                # bytes `mem get --json` showed, so a write that landed since
                # that read refuses here instead of being overwritten.
                if shared.version(path.read_bytes()) != expected:
                    raise StoreError("stale local read version; re-read and reconcile the edit")
            created = existing.created
            prior_source = existing.source

            title = args.title if args.title is not None else existing.title
            concept_type = args.type if args.type is not None else existing.type
            sensitivity = args.sensitivity if args.sensitivity is not None else existing.sensitivity

            if "topics" in clear_fields:
                topics = []
            elif args.topics is not None:
                topics = _split_csv(args.topics)
            else:
                topics = list(existing.topics)

            if "related" in clear_fields:
                related = []
            elif args.related is not None:
                related = [okf.slugify(r) for r in _split_csv(args.related)]
            else:
                related = list(existing.related)

            if args.body is not None:
                body = args.body
            elif piped_body is not None:
                body = piped_body
            else:
                body = existing.body

            if "description" in clear_fields:
                description = _derive_description(body)
            elif args.description is not None:
                description = args.description
            else:
                description = existing.description
        else:
            if path.exists():  # collision check redone under the lock
                raise StoreError(f"concept '{slug}' exists - pass --update to modify it")
            existing = None
            created = stamp
            prior_source = ""
            title = args.title
            concept_type = args.type if args.type is not None else okf.TYPE_DEFAULT
            sensitivity = args.sensitivity if args.sensitivity is not None else "normal"
            topics = _split_csv(args.topics)
            related = [okf.slugify(r) for r in _split_csv(args.related)]
            body = args.body if args.body is not None else fresh_body_input
            if not body.strip():
                raise StoreError("empty body - pass --body or pipe markdown on stdin")
            description = args.description or _derive_description(body)

        # Provenance never silently degrades (D9): an update without --source
        # keeps the existing citation; only a truly unsourced save gets the
        # ambient stamp.
        source = (getattr(args, "source", None) or "").strip() or prior_source \
            or f"ambient ({stamp[:10]})"

        concept = okf.Concept(
            slug=slug,
            title=title,
            description=description,
            type=concept_type,
            topics=topics,
            sensitivity=sensitivity,
            created=created,
            updated=stamp,
            related=related,
            source=source,
            body=body,
        )

        if existing is not None:
            _report_update_changes(existing, concept)

        text = okf.serialize(concept)

        if not shared_profile:
            _sweep_dead_temps(concepts_dir(root))
            atomic_write(path, text)
            verb = "update" if args.update else "save"
            committed = gitkb.commit_path(root, f"concepts/{slug}.md", f"mem {verb}: {slug}")
            lexical.record_save(root, concept, path)

    if shared_profile:
        result = shared.submit(root, [{
            "slug": slug, "expected_version": expected if args.update else None,
            "content": text,
        }], operation_id=getattr(args, "operation_id", None))
        rc = shared.report(result, json_output=getattr(args, "json", False))
        if rc == 0 and getattr(args, "dedup_check", False) and result.get("replica_current"):
            _dedup_check(root, concept)
        return rc

    if not committed:
        # A no-op update (identical content, same-second stamp) is not a
        # "successful save" in the one-commit-per-save contract - say so.
        print(f"unchanged: {slug} (identical content - nothing to commit)")
        return 0

    # Outside the lock: embed within the strict budget or enqueue - never blocks.
    vector.index_saved(root, concept)

    print(f"{'updated' if args.update else 'saved'}: {slug} ({path})")
    if getattr(args, "dedup_check", False):
        _dedup_check(root, concept)
    return 0


def cmd_get(args) -> int:
    root = config.kb_root()
    try:
        require_kb(root)
        raw = concept_path(root, args.slug).read_bytes()
        concept = okf.parse(raw.decode("utf-8"))
    except FileNotFoundError:
        print(f"error: no concept '{args.slug}'", file=sys.stderr)
        return 1
    except (StoreError, okf.OKFError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # graph neighborhood (F5); "related" already names the frontmatter field,
    # so the neighborhood travels under "neighbors"
    neighbors = graph.load(root).neighbors(args.slug) if args.related else None

    if args.json:
        data = concept.to_dict()
        # Report the key that actually resolved: lookup, every index, and
        # Obsidian all go by file stem - after an external rename, frontmatter
        # slug can disagree and would point consumers at a ghost path.
        data["slug"] = data["id"] = args.slug
        data["path"] = str(concept_path(root, args.slug))
        data["version"] = shared.version(raw)
        if neighbors is not None:
            data["neighbors"] = neighbors
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(f"slug: {args.slug}")
        print(f"version: {shared.version(raw)}")
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
        if neighbors is not None:
            print()
            print("neighbors:")
            if not neighbors["links"] and not neighbors["topics"]:
                print("  (none)")
            for link in neighbors["links"]:
                print(f"  link: {link['slug']} ({', '.join(link['via'])})  {link['title']}")
            for entry in neighbors["topics"]:
                members = ", ".join(m["slug"] for m in entry["neighbors"])
                print(f"  topic {entry['topic']}: {members}")
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
            concepts.append((path.stem, okf.parse(path.read_text(encoding="utf-8"))))
        except okf.OKFError as e:
            print(f"warning: skipping {path}: {e}", file=sys.stderr)

    if args.json:
        summaries = []
        for stem, concept in concepts:
            data = concept.to_dict()
            del data["body"]
            # stem is the resolved key (see cmd_get) - frontmatter can lag a rename
            data["slug"] = data["id"] = stem
            data["path"] = str(concept_path(root, stem))
            summaries.append(data)
        print(json.dumps(summaries, indent=2, ensure_ascii=False))
    else:
        for stem, concept in concepts:
            print(f"{stem}  [{', '.join(concept.topics)}]  {concept.title}")
    return 0
