"""`mem` entry point - stdlib argparse, never interactive, one-line errors."""

import argparse
import subprocess
import sys

from agent_memory import __version__, doctor, initcmd, store


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
    p_save.add_argument("--title", required=True, help="concept title; the slug derives from it")
    p_save.add_argument("--body", help="markdown body (reads stdin when omitted)")
    p_save.add_argument("--description", help="one-line summary (defaults to the body's first line)")
    p_save.add_argument("--topics", help="comma-separated topics")
    p_save.add_argument("--type", default="concept", help="concept type (default: concept)")
    p_save.add_argument(
        "--sensitivity", choices=["normal", "work"], default="normal",
        help="'work' = employer-specific material (DECISION_LOG D1)",
    )
    p_save.add_argument("--related", help="comma-separated related slugs")
    p_save.add_argument("--slug", help="explicit slug (default: derived from --title)")
    p_save.add_argument(
        "--update", action="store_true",
        help="replace an existing concept: keeps created, bumps updated",
    )
    p_save.set_defaults(func=store.cmd_save)

    p_get = sub.add_parser("get", help="print one concept by slug")
    p_get.add_argument("slug")
    p_get.add_argument("--json", action="store_true", help="machine-readable output")
    p_get.set_defaults(func=store.cmd_get)

    p_list = sub.add_parser("list", help="list saved concepts with their topics")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")
    p_list.set_defaults(func=store.cmd_list)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
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


def run() -> None:
    sys.exit(main())
