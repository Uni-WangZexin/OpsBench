from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, kubectl, load_scenario, namespace, state_value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    observed = state_value(scenario)
    expected = scenario["state"]["healthy"]
    namespace_result = kubectl(["get", "namespace", namespace(), "-o", "name"])
    namespace_healthy = namespace_result.returncode == 0
    repaired = observed == expected
    passed = namespace_healthy and repaired
    emit(
        {
            "passed": passed,
            "checks": [
                {"name": "namespace_available", "passed": namespace_healthy},
                {
                    "name": "incident_state_repaired",
                    "passed": repaired,
                    "observed": observed,
                },
            ],
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
