from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import (
    OBSERVATION_CONFIG_MAP,
    RELEASE_NAME,
    apply_config_map,
    emit,
    helm,
    kubectl,
    load_scenario,
    namespace,
    require_success,
    write_restricted_agent_kubeconfig,
)
from faults import prepare_real_fault


REQUIRED_DEPLOYMENTS = (
    "otel-demo-checkoutservice",
    "otel-demo-frontend",
    "otel-demo-frontendproxy",
    "otel-demo-jaeger",
    "otel-demo-loadgenerator",
    "otel-demo-otelcol",
    "otel-demo-productcatalogservice",
    "otel-demo-prometheus-server",
)


def wait_for_required_baseline() -> None:
    for deployment in REQUIRED_DEPLOYMENTS:
        result = kubectl(
            [
                "-n",
                namespace(),
                "rollout",
                "status",
                f"deployment/{deployment}",
                "--timeout=5m",
            ],
            timeout=330,
        )
        if result.returncode == 0:
            continue
        pods = kubectl(
            ["-n", namespace(), "get", "pods", "-o", "wide"], timeout=60
        )
        events = kubectl(
            [
                "-n",
                namespace(),
                "get",
                "events",
                "--sort-by=.lastTimestamp",
            ],
            timeout=60,
        )
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(
            f"wait for baseline deployment/{deployment} failed: {detail}\n\n"
            f"Pod status:\n{pods.stdout.strip()}\n\n"
            f"Recent events:\n{events.stdout.strip()}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    ns = namespace()

    namespace_result = kubectl(["get", "namespace", ns])
    if namespace_result.returncode != 0:
        require_success(kubectl(["create", "namespace", ns]), "create namespace")
    if os.environ.get("OPSBENCH_OTEL_SKIP_INSTALL") != "1":
        chart_version = os.environ.get("OPSBENCH_OTEL_CHART_VERSION", "0.11.0")
        chart_archive = os.environ.get("OPSBENCH_OTEL_CHART_ARCHIVE", "")
        chart_reference = chart_archive or "open-telemetry/opentelemetry-demo"
        if not chart_archive:
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
        install_args = [
            "install",
            RELEASE_NAME,
            chart_reference,
            "--namespace",
            ns,
            "--values",
            str(Path(args.case_dir).resolve() / "otel-values.yaml"),
        ]
        if not chart_archive:
            install_args.extend(["--version", chart_version])
        require_success(
            helm(install_args, timeout=300),
            "install OpenTelemetry Demo",
        )
        wait_for_required_baseline()

    labels = {
        "app.kubernetes.io/part-of": "opentelemetry-demo",
        "app.kubernetes.io/component": "monitoring",
    }
    prepare_real_fault(scenario)
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
