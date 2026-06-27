from __future__ import annotations

import argparse
from pathlib import Path

from opsbench.cases import load_case
from opsbench.leaderboard import format_leaderboard, summarize_runs
from opsbench.results import load_runs
from opsbench.runner import OpsBenchRunner


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="opsbench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--case", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--case", required=True)
    run_parser.add_argument("--agent", required=True)
    run_parser.add_argument("--results-dir", default="results")
    run_parser.add_argument("--timeout-sec", type=int)
    run_parser.add_argument("--no-docker", action="store_true")

    leaderboard_parser = subparsers.add_parser("leaderboard")
    leaderboard_parser.add_argument("--results", default="results/runs.jsonl")

    args = parser.parse_args(argv)

    if args.command == "validate":
        case = load_case(Path(args.case))
        print(f"{case.id} ({case.domain})")
        return 0

    if args.command == "run":
        runner = OpsBenchRunner(use_docker=not args.no_docker)
        record = runner.run(
            case_dir=args.case,
            agent_path=args.agent,
            results_dir=args.results_dir,
            timeout_sec=args.timeout_sec,
        )
        status = "PASS" if record["verification_passed"] else "FAIL"
        print(f"{status} {record['run_id']}")
        print(f"trace: {record['trace_dir']}")
        return 0 if record["verification_passed"] else 1

    if args.command == "leaderboard":
        runs = load_runs(args.results)
        print(format_leaderboard(summarize_runs(runs)))
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
