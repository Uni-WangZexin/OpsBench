from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, kubectl, load_scenario, namespace
from faults import wait_for_fault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    namespace_result = kubectl(["get", "namespace", namespace(), "-o", "name"])
    namespace_healthy = namespace_result.returncode == 0
    repaired, details = wait_for_fault(scenario, expected_active=False)
    frontdoor_result = kubectl(
        [
            "get",
            "--raw",
            f"/api/v1/namespaces/{namespace()}/services/"
            "http:otel-demo-frontendproxy:8080/proxy/",
        ],
        timeout=60,
    )
    frontdoor_healthy = (
        frontdoor_result.returncode == 0
        and "<!DOCTYPE html>" in frontdoor_result.stdout
    )
    passed = namespace_healthy and repaired and frontdoor_healthy
    checks = [
        {"name": "namespace_available", "passed": namespace_healthy},
        {
            "name": "real_fault_repaired",
            "passed": repaired,
            "details": details,
        },
        {
            "name": "frontend_business_sli",
            "passed": frontdoor_healthy,
            "probe": "kubernetes-service-proxy HTTP GET /",
        },
    ]
    if "metric" in details:
        checks.append(
            {
                "name": "resource_signal_recovered",
                "passed": repaired,
                "metric": details["metric"],
                "observed": details.get("value"),
                "active_threshold": details.get("active_threshold"),
                "recovery_threshold": details.get("recovery_threshold"),
            }
        )
    emit(
        {
            "passed": passed,
            "checks": checks,
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
