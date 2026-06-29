from __future__ import annotations

import argparse
import sys

from cpu_process_limit_windows.core import (
    Win32Error,
    launch_limited_process,
    limit_existing_process,
)
from cpu_process_limit_windows.settings import parse_cpu_percent


def _cpu_percent_arg(value: str) -> float:
    try:
        return parse_cpu_percent(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _normalize_remainder(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a Windows Job Object CPU hard cap to a process.",
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    pid_parser = subparsers.add_parser("pid", help="limit an existing process by PID")
    pid_parser.add_argument("pid", type=int)
    pid_parser.add_argument("--cpu", required=True, type=_cpu_percent_arg)

    run_parser = subparsers.add_parser("run", help="start a command with a CPU hard cap")
    run_parser.add_argument("--cpu", required=True, type=_cpu_percent_arg)
    run_parser.add_argument("command", nargs=argparse.REMAINDER)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.mode == "pid":
            session = limit_existing_process(args.pid, args.cpu)
            print(
                f"Limited PID {session.pid} to {session.cpu_percent:g}% CPU. "
                "Keep this process running to keep the job object alive."
            )
            return session.wait_until_exit()
        if args.mode == "run":
            session = launch_limited_process(
                _normalize_remainder(args.command),
                args.cpu,
            )
            print(
                f"Started PID {session.pid} with "
                f"{session.cpu_percent:g}% CPU hard cap."
            )
            return session.wait_until_exit()
    except KeyboardInterrupt:
        print("Stopped by user.", file=sys.stderr)
        return 130
    except (ValueError, Win32Error) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.error("unknown mode")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
