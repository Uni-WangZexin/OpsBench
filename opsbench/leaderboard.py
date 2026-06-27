from __future__ import annotations

from typing import Any


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    total_duration: dict[str, float] = {}
    for run in runs:
        agent = str(run["agent"])
        agent_summary = summary.setdefault(
            agent,
            {"runs": 0, "passes": 0, "pass_rate": 0.0, "average_duration_sec": 0.0},
        )
        agent_summary["runs"] = int(agent_summary["runs"]) + 1
        if run.get("verification_passed") is True:
            agent_summary["passes"] = int(agent_summary["passes"]) + 1
        total_duration[agent] = total_duration.get(agent, 0.0) + float(
            run.get("duration_sec", 0.0)
        )

    for agent, agent_summary in summary.items():
        runs_count = int(agent_summary["runs"])
        passes = int(agent_summary["passes"])
        agent_summary["pass_rate"] = passes / runs_count if runs_count else 0.0
        agent_summary["average_duration_sec"] = total_duration[agent] / runs_count

    return summary


def format_leaderboard(summary: dict[str, dict[str, float | int]]) -> str:
    lines = [
        f"{'agent':<24} {'runs':>4} {'passes':>6} {'pass_rate':>9} {'avg_sec':>8}",
        "-" * 57,
    ]
    sorted_items = sorted(
        summary.items(),
        key=lambda item: (-float(item[1]["pass_rate"]), float(item[1]["average_duration_sec"])),
    )
    for agent, agent_summary in sorted_items:
        pass_rate = float(agent_summary["pass_rate"]) * 100
        lines.append(
            f"{agent:<24} "
            f"{int(agent_summary['runs']):>4} "
            f"{int(agent_summary['passes']):>6} "
            f"{pass_rate:>8.1f}% "
            f"{float(agent_summary['average_duration_sec']):>8.2f}"
        )
    return "\n".join(lines)
