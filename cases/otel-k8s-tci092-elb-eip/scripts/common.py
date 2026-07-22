from __future__ import annotations

import json
import os
import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


OBSERVATION_CONFIG_MAP = "otel-demo-alert-context"
RELEASE_NAME = "otel-demo"
AGENT_CLUSTER_ROLE = "opsbench-agent-node-repair"


def namespace() -> str:
    value = os.environ.get("OPSBENCH_NAMESPACE", "")
    if not value:
        raise RuntimeError("OPSBENCH_NAMESPACE is required")
    return value


def load_scenario(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "hidden" / "scenario.json").read_text(encoding="utf-8"))


def run(command: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def kubectl(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return run(["kubectl", *args], timeout=timeout)


def helm(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return run(["helm", *args], timeout=timeout)


def require_success(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"{action} failed: {detail}")


def apply_config_map(name: str, data: dict[str, str], labels: dict[str, str]) -> None:
    manifest = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": namespace(), "labels": labels},
        "data": data,
    }
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(manifest),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    require_success(result, f"apply ConfigMap/{name}")


def create_warning_event(scenario: dict[str, Any]) -> None:
    event = {
        "apiVersion": "events.k8s.io/v1",
        "kind": "Event",
        "metadata": {"generateName": "opsbench-incident-", "namespace": namespace()},
        "eventTime": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "action": "DetectingIncident",
        "reason": "OperationalStateDegraded",
        "regarding": {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "name": OBSERVATION_CONFIG_MAP,
            "namespace": namespace(),
        },
        "reportingController": "opsbench.io/runner",
        "reportingInstance": "otel-demo-monitor",
        "type": "Warning",
        "note": scenario["signal"],
    }
    result = subprocess.run(
        ["kubectl", "create", "-f", "-"],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    require_success(result, "create incident Event")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


def write_restricted_agent_kubeconfig() -> Path:
    ns = namespace()
    service_account = "opsbench-agent"
    rbac = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {"name": service_account, "namespace": ns},
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "Role",
                "metadata": {"name": service_account, "namespace": ns},
                "rules": [
                    {
                        "apiGroups": ["", "apps", "batch", "networking.k8s.io", "events.k8s.io"],
                        "resources": ["*"],
                        "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"],
                    },
                    {
                        "apiGroups": [""],
                        "resources": ["services/proxy"],
                        "verbs": ["get"],
                    }
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {"name": service_account, "namespace": ns},
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": service_account,
                        "namespace": ns,
                    }
                ],
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role",
                    "name": service_account,
                },
            },
        ],
    }
    applied = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(rbac),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    require_success(applied, "create restricted agent RBAC")
    cluster_rbac = {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRole",
                "metadata": {"name": AGENT_CLUSTER_ROLE},
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["nodes"],
                        "verbs": ["get", "list", "watch", "patch", "update"],
                    }
                ],
            },
            {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "ClusterRoleBinding",
                "metadata": {"name": agent_cluster_role_binding(ns)},
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": service_account,
                        "namespace": ns,
                    }
                ],
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": AGENT_CLUSTER_ROLE,
                },
            },
        ],
    }
    cluster_applied = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=json.dumps(cluster_rbac),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    require_success(cluster_applied, "create restricted node repair RBAC")
    token_result = kubectl(
        ["-n", ns, "create", "token", service_account, "--duration=1h"],
        timeout=120,
    )
    require_success(token_result, "create restricted agent token")
    config_result = kubectl(
        ["config", "view", "--raw", "--flatten", "-o", "json"], timeout=120
    )
    require_success(config_result, "read active kubeconfig")
    source = json.loads(config_result.stdout)
    current_context_name = source["current-context"]
    current_context = next(
        item["context"] for item in source["contexts"] if item["name"] == current_context_name
    )
    cluster_name = current_context["cluster"]
    cluster = next(
        item["cluster"] for item in source["clusters"] if item["name"] == cluster_name
    )
    cluster = agent_reachable_cluster(cluster)
    restricted = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [{"name": "opsbench", "cluster": cluster}],
        "contexts": [
            {
                "name": "opsbench",
                "context": {
                    "cluster": "opsbench",
                    "namespace": ns,
                    "user": "opsbench-agent",
                },
            }
        ],
        "current-context": "opsbench",
        "users": [
            {
                "name": "opsbench-agent",
                "user": {"token": token_result.stdout.strip()},
            }
        ],
    }
    output = Path(os.environ["OPSBENCH_AGENT_KUBECONFIG"]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(restricted), encoding="utf-8")
    output.chmod(0o600)
    return output


def agent_cluster_role_binding(ns: str) -> str:
    return f"{ns}-agent-node-access"[:63].rstrip("-")


def agent_reachable_cluster(source_cluster: dict[str, Any]) -> dict[str, Any]:
    """Translate a host-loopback API endpoint for a sibling Docker container."""

    cluster = deepcopy(source_cluster)
    server = str(cluster.get("server", ""))
    parsed = urlsplit(server)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return cluster
    if parsed.port is None:
        raise RuntimeError(f"loopback Kubernetes API server has no port: {server}")
    cluster["server"] = urlunsplit(
        (
            parsed.scheme,
            f"host.docker.internal:{parsed.port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )
    cluster["tls-server-name"] = parsed.hostname
    return cluster
