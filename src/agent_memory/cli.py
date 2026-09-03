"""`mem` entry point - stdlib argparse, never interactive, one-line errors."""

import argparse
import subprocess
import sys
import time

from agent_memory import __version__, config, dedupcmd, doctor, extract, graph, initcmd, reindex, search, store, usage, vector


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="mem",
        description="Personal cross-agent knowledge base.",
    )
    parser.add_argument("--version", action="version", version=f"mem {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p_init = sub.add_parser(
        "init", help="create and verify the KB home; install agent instruction blocks"
    )
    p_init.set_defaults(func=initcmd.cmd_init)

    p_doctor = sub.add_parser("doctor", help="diagnose the KB environment")
    p_doctor.add_argument("--json", action="store_true", help="machine-readable output")
    p_doctor.set_defaults(func=doctor.cmd_doctor)

    p_save = sub.add_parser("save", help="save a concept as OKF markdown (one commit per save)")
    p_save.add_argument(
        "--title",
        help="concept title; the slug derives from it unless --slug is given"
             " (required for a fresh save; optional on --update when --slug is given,"
             " in which case the stored title is kept - pass --title explicitly to replace it)",
    )
    p_save.add_argument(
        "--body",
        help="markdown body (reads stdin when omitted; on --update, an omitted --body with a"
             " TTY or empty stdin keeps the stored body - piped non-empty stdin replaces it)",
    )
    p_save.add_argument(
        "--description",
        help="one-line summary (default on a fresh save: the body's first line; on --update,"
             " an omitted --description keeps the stored value unchanged - it is not"
             " re-derived from a new body)",
    )
    p_save.add_argument(
        "--topics",
        help="comma-separated topics (replaces the stored list on --update; omit to keep it)",
    )
    p_save.add_argument(
        "--type",
        help="concept type (default on a fresh save: concept; kept from the existing"
             " concept on --update)",
    )
    p_save.add_argument(
        "--sensitivity", choices=["normal", "work", "sensitive"],
        help="'work' = employer-specific material (DECISION_LOG D1); "
             "'sensitive' = PII/PHI (D16) (default on a fresh save: normal; kept from the"
             " existing concept on --update)",
    )
    p_save.add_argument(
        "--related",
        help="comma-separated related slugs (replaces the stored list on --update; omit to"
             " keep it)",
    )
    p_save.add_argument(
        "--source",
        help="provenance citation, e.g. a paper/book/document reference (default: kept from"
             " the existing concept on --update, else 'ambient (<date>)')",
    )
    p_save.add_argument("--slug", help="explicit slug (default: derived from --title)")
    p_save.add_argument(
        "--update", action="store_true",
        help="merge into an existing concept: fields you omit keep their stored value,"
             " created is kept and updated is bumped; a field you do pass explicitly"
             " replaces the stored value (warned on stderr) - use --clear to blank a"
             " clearable field instead of omitting it",
    )
    p_save.add_argument(
        "--clear", action="append", metavar="FIELD[,FIELD...]",
        help="with --update, explicitly clear a field instead of keeping its stored value"
             " (repeatable, or comma-separate multiple fields); clearable: description"
             " (re-derived from the body), topics, related",
    )
    p_save.add_argument(
        "--dedup-check", action="store_true", dest="dedup_check",
        help="advisory only: after saving, run the D18 detector and print its full"
             " report to stderr - never blocks the save or changes the exit code"
             " (the save-path bypass stays the designed recourse; D3)",
    )
    p_save.set_defaults(func=store.cmd_save)

    p_search = sub.add_parser(
        "search",
        help="fused search: lexical + semantic + graph via RRF (degrades to"
        " lexical + graph with Ollama down)",
    )
    p_search.add_argument("query", help="search terms")
    p_search.add_argument("--json", action="store_true", help="machine-readable output")
    p_search.add_argument("--limit", type=int, default=10, help="max hits (default: 10)")
    p_search.add_argument(
        "--no-work", action="store_true", dest="no_work",
        help="exclude sensitivity:work items entirely",
    )
    p_search.add_argument(
        "--no-sensitive", action="store_true", dest="no_sensitive",
        help="exclude sensitivity:sensitive (PII/PHI, D16) items entirely",
    )
    p_search.add_argument(
        "--type",
        help="comma-separated allow-list of concept types to return (e.g."
             " 'concept' to ground only in vetted knowledge, excluding sb-position"
             " hypotheses and other non-concept types)",
    )
    p_search.set_defaults(func=search.cmd_search)

    p_get = sub.add_parser("get", help="print one concept by slug")
    p_get.add_argument("slug")
    p_get.add_argument("--json", action="store_true", help="machine-readable output")
    p_get.add_argument(
        "--related", action="store_true",
        help="include the concept's graph neighborhood (link- and topic-neighbors)",
    )
    p_get.set_defaults(func=store.cmd_get)

    p_list = sub.add_parser("list", help="list saved concepts with their topics")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")
    p_list.set_defaults(func=store.cmd_list)

    p_extract = sub.add_parser(
        "extract",
        help="dedup candidate concepts against the KB and save the novel ones"
        " (refuses cleanly with Ollama down - dedup requires embeddings)",
    )
    p_extract.add_argument(
        "--candidates",
        help="candidate concepts as JSON: a file path, '-' for stdin, or an inline JSON array",
    )
    p_extract.add_argument(
        "--procedure", action="store_true",
        help="print the agent-side extract-knowledge procedure and exit",
    )
    p_extract.add_argument("--json", action="store_true", help="machine-readable output")
    p_extract.set_defaults(func=extract.cmd_extract)

    p_reindex = sub.add_parser(
        "reindex",
        help="rebuild all derived indexes (lexical, graph, vector) from the"
        " markdown; drain all queued embeddings",
    )
    p_reindex.add_argument(
        "--chunks", action="store_true",
        help="also eagerly (re)build the D18 chunk index (opt-in, disposable"
        " sub-card retrieval windows); without this flag, stale chunk rows"
        " are still dropped but not repopulated",
    )
    p_reindex.add_argument(
        "--claims", action="store_true",
        help="also eagerly (re)build the D18 claim-vector index (opt-in,"
        " disposable per-claim embeddings for the semantic claim leg);"
        " without this flag, stale claim vectors are still dropped but not"
        " repopulated - the leg otherwise embeds lazily, retrieval-scoped",
    )
    p_reindex.set_defaults(func=reindex.cmd_reindex)

    p_dedup = sub.add_parser(
        "dedup",
        help="detect near/likely-duplicate concepts via fused retrieval +"
        " claim-coverage (un-misreadable report: no score/semantic_similarity"
        " keys anywhere)",
    )
    p_dedup.add_argument(
        "file", nargs="?",
        help="candidates JSON (path, '-' for stdin, or inline), an OKF card,"
        " or a plain markdown file; omit only when using --adjudicate",
    )
    p_dedup.add_argument("--json", action="store_true", help="machine-readable output")
    p_dedup.add_argument("--deep-k", type=int, default=None, help="override MEM_DEDUP_DEEP_K")
    p_dedup.add_argument("--top-m", type=int, default=None, help="override MEM_DEDUP_UNION_M")
    p_dedup.add_argument(
        "--explain", action="store_true",
        help="add the per-claim match table to the text report (always present in --json)",
    )
    p_dedup.add_argument(
        "--no-log", action="store_true", help="skip writing .index/dedup-log.jsonl this run",
    )
    p_dedup.add_argument(
        "--title", help="title for a plain-markdown FILE lacking a heading",
    )
    p_dedup.add_argument(
        "--adjudicate", metavar="RUN_ID",
        help="append an adjudication record joining a prior detection run's candidate,"
        " instead of analyzing FILE",
    )
    p_dedup.add_argument("--candidate", metavar="HASH", help="candidate content_hash to adjudicate")
    p_dedup.add_argument(
        "--label", help="adjudication label: DUP, DISTINCT, or FOLD"
        " (validated by the command itself, not argparse `choices=`, so an"
        " invalid value gets the project's one-line `error:` convention"
        " instead of argparse's four-line usage block - gate note)",
    )
    p_dedup.add_argument("--by", help="who/what made the adjudication (free text)")
    p_dedup.set_defaults(func=dedupcmd.cmd_dedup)

    p_links = sub.add_parser(
        "links", help="link health: report dangling wikilink/related targets"
    )
    p_links.add_argument("--json", action="store_true", help="machine-readable report")
    p_links.set_defaults(func=graph.cmd_links)

    p_stats = sub.add_parser("stats", help="usage counts from the local invocation log (D8)")
    p_stats.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    p_stats.set_defaults(func=usage.cmd_stats)

    args = parser.parse_args(argv)
    _t0 = time.monotonic()
    try:
        rc = args.func(args)
    except FileNotFoundError as e:
        print(f"error: required tool missing: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        lines = (e.stderr or "").strip().splitlines()
        detail = lines[0] if lines else f"exit {e.returncode}"
        cmd = " ".join(str(part) for part in e.cmd[:2])
        print(f"error: {cmd} failed: {detail}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.command not in ("init", "stats"):
        usage.log_event(config.kb_root(), args.command, args, rc,
                        int((time.monotonic() - _t0) * 1000))

    # Bounded opportunistic drain: any ordinary invocation moves the embed
    # queue along a little; doctor/reindex drain fully themselves.
    if args.command not in ("init", "doctor", "reindex", "stats"):
        try:
            vector.opportunistic_drain(config.kb_root())
        except Exception:
            pass
    return rc


def run() -> None:
    sys.exit(main())
