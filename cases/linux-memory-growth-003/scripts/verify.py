from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, http_code, scenario
from faults import fault_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir).resolve()
    repaired, details = fault_state(case_dir, scenario(case_dir)["implementation"], active=False)
    health = http_code(case_dir, "http://127.0.0.1:8080/health")
    passed = repaired and health == 200
    emit(
        {
            "passed": passed,
            "checks": [
                {"name": "root_cause_repaired", "passed": repaired, **details},
                {"name": "service_health", "passed": health == 200, "http_status": health},
            ],
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
