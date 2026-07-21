"""`mem` entry point - stdlib argparse, never interactive, one-line errors."""

import argparse
import subprocess
import sys

from agent_memory import __version__, doctor, initcmd


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
