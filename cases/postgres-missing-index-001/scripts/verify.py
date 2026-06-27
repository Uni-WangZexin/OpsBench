from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from common import emit, explain_execution_ms, load_manifest, psql, wait_for_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir)
    manifest = load_manifest(case_dir)
    verification = manifest["verification"]
    customer_id = int(verification["customer_id"])
    samples = int(verification["samples"])
    average_threshold = float(verification["average_ms_threshold"])
    p95_threshold = float(verification["p95_ms_threshold"])

    wait_for_db(case_dir)
    count_result = psql(
        case_dir,
        f"SELECT count(*) FROM orders WHERE customer_id = {customer_id};",
        timeout=120,
    )
    row_count = int(count_result.stdout.strip() or "0") if count_result.returncode == 0 else 0
    correctness_passed = count_result.returncode == 0 and row_count > 0

    execution_times: list[float] = []
    plan = {}
    explain_error = ""
    for _ in range(samples):
        try:
            execution_ms, plan = explain_execution_ms(case_dir, customer_id)
            execution_times.append(execution_ms)
        except Exception as exc:  # noqa: BLE001 - verifier returns the failure as JSON.
            explain_error = str(exc)
            break

    average_ms = statistics.mean(execution_times) if execution_times else float("inf")
    p95_ms = max(execution_times) if execution_times else float("inf")
    latency_average_passed = average_ms <= average_threshold
    latency_p95_passed = p95_ms <= p95_threshold
    passed = correctness_passed and latency_average_passed and latency_p95_passed

    emit(
        {
            "passed": passed,
            "checks": [
                {
                    "name": "row_count_positive",
                    "passed": correctness_passed,
                    "value": row_count,
                },
                {
                    "name": "latency_average_ms",
                    "passed": latency_average_passed,
                    "value": round(average_ms, 3),
                    "threshold": average_threshold,
                },
                {
                    "name": "latency_p95_ms",
                    "passed": latency_p95_passed,
                    "value": round(p95_ms, 3),
                    "threshold": p95_threshold,
                },
            ],
            "diagnostics": {
                "execution_times_ms": [round(value, 3) for value in execution_times],
                "plan": plan,
                "error": explain_error,
            },
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
