from __future__ import annotations

from typing import Any


LeaderboardKey = tuple[str, str]
LeaderboardSummary = dict[LeaderboardKey, dict[str, float | int]]


def summarize_runs(runs: list[dict[str, Any]]) -> LeaderboardSummary:
    runs = _latest_attempts(runs)
    summary: LeaderboardSummary = {}
    total_duration: dict[LeaderboardKey, float] = {}
    for run in runs:
        agent = str(run["agent"])
        model = _model_name(run)
        leaderboard_key = (model, agent)
        agent_summary = summary.setdefault(
            leaderboard_key,
            {"runs": 0, "passes": 0, "pass_rate": 0.0, "average_duration_sec": 0.0},
        )
        agent_summary["runs"] = int(agent_summary["runs"]) + 1
        if _repair_passed(run):
            agent_summary["passes"] = int(agent_summary["passes"]) + 1
        total_duration[leaderboard_key] = total_duration.get(leaderboard_key, 0.0) + float(
            run.get("duration_sec", 0.0)
        )

    for leaderboard_key, agent_summary in summary.items():
        runs_count = int(agent_summary["runs"])
        passes = int(agent_summary["passes"])
        agent_summary["pass_rate"] = passes / runs_count if runs_count else 0.0
        agent_summary["average_duration_sec"] = (
            total_duration[leaderboard_key] / runs_count
        )

    return summary


def _latest_attempts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one result per model/agent/case so retries cannot inflate a score."""

    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for index, run in enumerate(runs):
        model = _model_name(run)
        agent = str(run["agent"])
        case_id = str(run.get("case_id", f"__legacy_attempt_{index}"))
        latest[(model, agent, case_id)] = run
    return list(latest.values())


def _model_name(run: dict[str, Any]) -> str:
    model = run.get("model")
    if isinstance(model, str) and model.strip():
        return model

    config = run.get("effective_agent_config")
    if isinstance(config, dict):
        for key in ("OPENAI_MODEL", "DEEPSEEK_MODEL", "ANTHROPIC_MODEL", "MODEL"):
            configured_model = config.get(key)
            if isinstance(configured_model, str) and configured_model.strip():
                return configured_model

    return "unknown"


def _repair_passed(run: dict[str, Any]) -> bool:
    """Prefer the verifier's raw decision so legacy runner coupling is ignored."""

    verification = run.get("verification")
    if isinstance(verification, dict) and isinstance(verification.get("passed"), bool):
        return verification["passed"]
    return run.get("verification_passed") is True


def format_leaderboard(summary: LeaderboardSummary) -> str:
    lines = [
        f"{'model':<24} {'agent':<24} {'runs':>4} {'passes':>6} "
        f"{'pass_rate':>9} {'avg_sec':>8}",
        "-" * 82,
    ]
    sorted_items = sorted(
        summary.items(),
        key=lambda item: (
            -float(item[1]["pass_rate"]),
            float(item[1]["average_duration_sec"]),
            item[0],
        ),
    )
    for (model, agent), agent_summary in sorted_items:
        pass_rate = float(agent_summary["pass_rate"]) * 100
        lines.append(
            f"{model:<24} "
            f"{agent:<24} "
            f"{int(agent_summary['runs']):>4} "
            f"{int(agent_summary['passes']):>6} "
            f"{pass_rate:>8.1f}% "
            f"{float(agent_summary['average_duration_sec']):>8.2f}"
        )
    return "\n".join(lines)
