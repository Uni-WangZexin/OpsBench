from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import (
    OBSERVATION_CONFIG_MAP,
    RELEASE_NAME,
    STATE_CONFIG_MAP,
    apply_config_map,
    emit,
    helm,
    kubectl,
    load_scenario,
    namespace,
    require_success,
    write_restricted_agent_kubeconfig,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    ns = namespace()

    require_success(kubectl(["create", "namespace", ns]), "create namespace")
    if os.environ.get("OPSBENCH_OTEL_SKIP_INSTALL") != "1":
        require_success(
            helm(
                [
                    "repo",
                    "add",
                    "open-telemetry",
                    "https://open-telemetry.github.io/opentelemetry-helm-charts",
                    "--force-update",
                ]
            ),
            "add OpenTelemetry Helm repository",
        )
        chart_version = os.environ.get("OPSBENCH_OTEL_CHART_VERSION", "0.11.0")
        require_success(
            helm(
                [
                    "install",
                    RELEASE_NAME,
                    "open-telemetry/opentelemetry-demo",
                    "--namespace",
                    ns,
                    "--version",
                    chart_version,
                    "--wait",
                    "--timeout",
                    "12m",
                ],
                timeout=780,
            ),
            "install OpenTelemetry Demo",
        )

    labels = {
        "app.kubernetes.io/part-of": "opentelemetry-demo",
        "opsbench.io/case-id": scenario["id"],
        "opsbench.io/simulated-kind": scenario["simulated_kind"].lower(),
    }
    apply_config_map(
        STATE_CONFIG_MAP,
        {
            "component": scenario["component"],
            "resource": scenario["resource"],
            scenario["state"]["field"]: scenario["state"]["healthy"],
        },
        labels,
    )
    apply_config_map(
        OBSERVATION_CONFIG_MAP,
        {
            "condition": "Healthy",
            "symptom": "No active incident",
            "signal": "baseline-ready",
        },
        labels,
    )
    restricted_kubeconfig = write_restricted_agent_kubeconfig()
    emit(
        {
            "passed": True,
            "phase": "setup",
            "namespace": ns,
            "agent_kubeconfig_created": restricted_kubeconfig.is_file(),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
