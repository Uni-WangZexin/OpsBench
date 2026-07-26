from __future__ import annotations

import argparse
from pathlib import Path

from opsbench.cases import load_case
from opsbench.leaderboard import format_leaderboard, summarize_runs
from opsbench.kubernetes_cluster import MinikubeClusterManager
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
    run_parser.add_argument("--max-steps", type=int, default=60)
    run_parser.add_argument("--no-docker", action="store_true")

    leaderboard_parser = subparsers.add_parser("leaderboard")
    leaderboard_parser.add_argument("--results", default="results/runs.jsonl")

    cluster_parser = subparsers.add_parser("cluster")
    cluster_parser.add_argument("action", choices=("up", "status", "down"))

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
            max_steps=args.max_steps,
        )
        status = "PASS" if record["verification_passed"] else "FAIL"
        print(f"{status} {record['run_id']}")
        if not record.get("agent_completed", False):
            returncode = record.get("phases", {}).get("agent", {}).get("returncode")
            print(f"agent: incomplete (exit {returncode})")
        print(f"trace: {record['trace_dir']}")
        return 0 if record["verification_passed"] else 1

    if args.command == "leaderboard":
        runs = load_runs(args.results)
        print(format_leaderboard(summarize_runs(runs)))
        return 0

    if args.command == "cluster":
        manager = MinikubeClusterManager()
        if args.action == "up":
            kubeconfig = manager.ensure()
            print(f"RUNNING {manager.profile}")
            print(f"kubeconfig: {kubeconfig}")
            return 0
        if args.action == "down":
            manager.delete()
            print(f"DELETED {manager.profile}")
            return 0
        status = manager.status()
        state = "RUNNING" if status.running else "STOPPED"
        print(f"{state} {status.profile}")
        print(f"kubeconfig: {status.kubeconfig}")
        return 0 if status.running else 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
