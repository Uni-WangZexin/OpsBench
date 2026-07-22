from __future__ import annotations

import json
import hashlib
import time
import math
from typing import Any
from urllib.parse import urlencode

from common import kubectl, namespace, require_success


FAULT_IMAGE = "redis:alpine"
PROXY_IMAGE = "python:3.12-alpine"


def fault_name(scenario: dict[str, Any]) -> str:
    suffix = hashlib.sha1(str(scenario["id"]).encode("utf-8")).hexdigest()[:8]
    return f"otel-demo-health-agent-{suffix}"


def prepare_real_fault(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    strategy = implementation["strategy"]
    if strategy == "config_probe":
        _apply_config_probe(scenario, implementation["healthy"])
        _wait_deployment(fault_name(scenario), ready=True, timeout=180)
    elif strategy == "ingress":
        _apply_ingress(scenario, implementation["healthy"])
    elif strategy == "service" and implementation["fault"] == "affinity":
        _patch_service(implementation["component"], {"sessionAffinity": implementation["healthy"]})


def inject_real_fault(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    strategy = implementation["strategy"]
    if strategy == "stress":
        _apply_stress_pod(scenario)
    elif strategy == "workload_stress":
        _inject_workload_stress(scenario)
    elif strategy == "deployment":
        _inject_deployment(implementation)
    elif strategy == "service":
        _inject_service(implementation)
    elif strategy == "network_policy":
        _apply_network_policy(scenario)
    elif strategy == "proxy":
        _inject_proxy(scenario)
    elif strategy == "node":
        _inject_node(implementation)
    elif strategy == "config_probe":
        _patch_config_probe(scenario, implementation["faulty"])
    elif strategy == "pending":
        _apply_pending_pod(scenario)
    elif strategy == "pull_secret":
        _inject_pull_secret(scenario)
    elif strategy == "quota":
        _inject_quota(scenario)
    elif strategy == "ingress":
        _apply_ingress(scenario, implementation["faulty"])
    else:
        raise RuntimeError(f"unsupported real fault strategy: {strategy}")


def cleanup_real_fault(scenario: dict[str, Any]) -> None:
    """Restore cluster-scoped changes that namespace deletion cannot remove."""

    implementation = scenario["implementation"]
    if implementation["strategy"] != "node":
        return
    node_result = kubectl(["get", "nodes", "-o", "jsonpath={.items[0].metadata.name}"])
    if node_result.returncode != 0 or not node_result.stdout.strip():
        return
    node = node_result.stdout.strip()
    if implementation["fault"] == "cordon":
        kubectl(["uncordon", node])
    else:
        kubectl(["taint", "node", node, f"{implementation['key']}-"])


def fault_is_active(scenario: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    implementation = scenario["implementation"]
    strategy = implementation["strategy"]
    if strategy == "stress":
        pod = _get_json("pod", fault_name(scenario), allow_missing=True)
        phase = _dig(pod, "status", "phase") if pod else "Missing"
        signal_ok, signal_details = _stress_signal_state(scenario, active=True)
        return phase == "Running" and signal_ok, {
            "pod_phase": phase,
            **signal_details,
        }
    if strategy == "workload_stress":
        deployment = _deployment(implementation["component"])
        sidecar = _find_container(deployment, _stress_container_name())
        signal_ok, signal_details = _stress_signal_state(scenario, active=True)
        return sidecar is not None and signal_ok, {
            "sidecar_present": sidecar is not None,
            **signal_details,
        }
    if strategy == "deployment":
        return _deployment_fault_state(implementation, active=True)
    if strategy == "service":
        return _service_fault_state(implementation, active=True)
    if strategy == "network_policy":
        exists = _get_json("networkpolicy", fault_name(scenario), allow_missing=True) is not None
        return exists, {"network_policy_exists": exists}
    if strategy == "proxy":
        return _proxy_fault_state(scenario, active=True)
    if strategy == "node":
        return _node_fault_state(implementation, active=True)
    if strategy == "config_probe":
        value = _config_value(fault_name(scenario))
        ready = _deployment_ready(fault_name(scenario))
        active = value == str(implementation["faulty"]) and not ready
        return active, {"config_value": value, "probe_ready": ready}
    if strategy == "pending":
        pod = _get_json("pod", fault_name(scenario), allow_missing=True)
        phase = _dig(pod, "status", "phase") if pod else "Missing"
        return phase == "Pending", {"pod_phase": phase}
    if strategy == "pull_secret":
        component = implementation["component"]
        deployment = _deployment(component)
        container = _container(deployment, component)
        names = [item.get("name") for item in _dig(deployment, "spec", "template", "spec", "imagePullSecrets", default=[])]
        reasons = _component_waiting_reasons(component)
        active = (
            fault_name(scenario) in names
            and str(container.get("image", "")).startswith("invalid.local/")
            and bool({"ErrImagePull", "ImagePullBackOff"} & set(reasons))
        )
        return active, {
            "image": container.get("image"),
            "image_pull_secrets": names,
            "waiting_reasons": reasons,
        }
    if strategy == "quota":
        quota = _get_json("resourcequota", fault_name(scenario), allow_missing=True)
        if not quota:
            return False, {"quota_exists": False}
        hard = int(_dig(quota, "status", "hard", "pods", default="0"))
        used = int(_dig(quota, "status", "used", "pods", default="0"))
        return used >= hard > 0, {"quota_hard": hard, "quota_used": used}
    if strategy == "ingress":
        value = _ingress_value(scenario)
        return value == str(implementation["faulty"]), {"ingress_value": value}
    raise RuntimeError(f"unsupported real fault strategy: {strategy}")


def fault_is_repaired(scenario: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    implementation = scenario["implementation"]
    strategy = implementation["strategy"]
    if strategy in {"stress", "pending", "network_policy"}:
        kind = "networkpolicy" if strategy == "network_policy" else "pod"
        exists = _get_json(kind, fault_name(scenario), allow_missing=True) is not None
        if strategy == "stress":
            signal_ok, signal_details = _stress_signal_state(scenario, active=False)
            return not exists and signal_ok, {
                "load_resource_exists": exists,
                **signal_details,
            }
        return not exists, {"fault_resource_exists": exists}
    if strategy == "workload_stress":
        component = implementation["component"]
        deployment = _deployment(component)
        sidecar = _find_container(deployment, _stress_container_name())
        signal_ok, signal_details = _stress_signal_state(scenario, active=False)
        ready = _deployment_ready(f"otel-demo-{component}")
        return sidecar is None and ready and signal_ok, {
            "sidecar_present": sidecar is not None,
            "deployment_ready": ready,
            **signal_details,
        }
    if strategy == "proxy":
        return _proxy_fault_state(scenario, active=False)
    if strategy == "deployment":
        return _deployment_fault_state(implementation, active=False)
    if strategy == "service":
        return _service_fault_state(implementation, active=False)
    if strategy == "node":
        return _node_fault_state(implementation, active=False)
    if strategy == "config_probe":
        value = _config_value(fault_name(scenario))
        ready = _deployment_ready(fault_name(scenario))
        repaired = value == str(implementation["healthy"]) and ready
        return repaired, {"config_value": value, "probe_ready": ready}
    if strategy == "pull_secret":
        component = implementation["component"]
        deployment = _deployment(component)
        image = str(_container(deployment, component).get("image", ""))
        names = [item.get("name") for item in _dig(deployment, "spec", "template", "spec", "imagePullSecrets", default=[])]
        deployment_name = f"otel-demo-{component}"
        ready = _deployment_ready(deployment_name)
        repaired = (
            fault_name(scenario) not in names
            and image.startswith("otel/demo:")
            and ready
        )
        return repaired, {
            "image": image,
            "image_pull_secrets": names,
            "deployment_ready": ready,
        }
    if strategy == "quota":
        quota = _get_json("resourcequota", fault_name(scenario), allow_missing=True)
        if not quota:
            return True, {"quota_exists": False}
        hard = int(_dig(quota, "status", "hard", "pods", default="0"))
        used = int(_dig(quota, "status", "used", "pods", default="0"))
        return hard > used, {"quota_hard": hard, "quota_used": used}
    if strategy == "ingress":
        value = _ingress_value(scenario)
        return value == str(implementation["healthy"]), {"ingress_value": value}
    raise RuntimeError(f"unsupported real fault strategy: {strategy}")


def wait_for_fault(scenario: dict[str, Any], expected_active: bool, timeout: int = 180) -> tuple[bool, dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_details: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result, last_details = (
            fault_is_active(scenario) if expected_active else fault_is_repaired(scenario)
        )
        if result:
            return True, last_details
        time.sleep(2)
    return False, last_details


def _apply_stress_pod(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    mode = implementation["mode"]
    workers = int(implementation.get("workers", 2))
    memory_mib = int(implementation.get("memory_mib", 512))
    commands = {
        "cpu": f"for i in $(seq 1 {workers}); do while :; do :; done & done; wait",
        "memory": f"dd if=/dev/zero of=/dev/shm/cache bs=1M count={memory_mib}; sleep 3600",
        "io": "while :; do dd if=/dev/zero of=/data/io bs=1M count=128 conv=fsync; rm -f /data/io; done",
        "disk_fill": "dd if=/dev/zero of=/data/full bs=1M count=768; sleep 3600",
        "network": "while :; do wget -q -O /dev/null http://otel-demo-frontendproxy:8080/ || true; done",
        "connections": "while :; do for p in 8080 8081 8082 8083; do nc -z -w 1 otel-demo-frontendproxy $p & done; wait; done",
        "dns": "while :; do nslookup otel-demo-frontendproxy >/dev/null 2>&1 || true; done",
        "latency": "while :; do wget -q -O /dev/null http://otel-demo-checkoutservice:8080/ || true; sleep 0.5; done",
    }
    memory_limit = max(memory_mib + 128, 256)
    resources = {
        "limits": {"cpu": "3500m" if implementation.get("target") == "node" else "1500m", "memory": f"{memory_limit}Mi"},
        "requests": {"cpu": "100m", "memory": "32Mi"},
    }
    volumes: list[dict[str, Any]] = []
    mounts: list[dict[str, Any]] = []
    if mode in {"io", "disk_fill"}:
        volumes = [{"name": "data", "emptyDir": {"sizeLimit": "1Gi"}}]
        mounts = [{"name": "data", "mountPath": "/data"}]
    manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": fault_name(scenario), "namespace": namespace(), "labels": _fault_labels(scenario)},
        "spec": {
            "restartPolicy": "Never",
            "containers": [{"name": "system-monitor", "image": FAULT_IMAGE, "command": ["/bin/sh", "-c", commands[mode]], "resources": resources, "volumeMounts": mounts}],
            "volumes": volumes,
        },
    }
    _apply(manifest)


def _inject_workload_stress(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    mode = implementation["mode"]
    commands = {
        "cpu": "while :; do :; done",
        "memory": "dd if=/dev/zero of=/dev/shm/cache bs=1M count=448; sleep 3600",
        "io": "while :; do dd if=/dev/zero of=/cache/io bs=1M count=64 conv=fsync; rm -f /cache/io; done",
    }
    mounts: list[dict[str, Any]] = []
    volumes: list[dict[str, Any]] = []
    if mode == "io":
        mounts = [{"name": "telemetry-cache", "mountPath": "/cache"}]
        volumes = [{"name": "telemetry-cache", "emptyDir": {"sizeLimit": "512Mi"}}]
    sidecar = {
        "name": _stress_container_name(),
        "image": FAULT_IMAGE,
        "command": ["/bin/sh", "-c", commands[mode]],
        "resources": {
            "requests": {"cpu": "20m", "memory": "16Mi"},
            "limits": {
                "cpu": "1000m" if mode == "cpu" else "250m",
                "memory": "640Mi" if mode == "memory" else "128Mi",
            },
        },
        "volumeMounts": mounts,
    }
    patch: dict[str, Any] = {
        "spec": {"template": {"spec": {"containers": [sidecar]}}}
    }
    if volumes:
        patch["spec"]["template"]["spec"]["volumes"] = volumes
    _patch(
        "deployment",
        f"otel-demo-{implementation['component']}",
        patch,
        patch_type="strategic",
    )


def _stress_signal_state(
    scenario: dict[str, Any], active: bool
) -> tuple[bool, dict[str, Any]]:
    implementation = scenario["implementation"]
    mode = implementation["mode"]
    if mode not in {"cpu", "memory"}:
        return True, {"resource_signal": "not-required"}
    pods = _stress_metric_pods(scenario, active)
    pod_pattern = "|".join(pods) if pods else "metric-series-does-not-exist"
    selector = f'namespace="{namespace()}",pod=~"{pod_pattern}"'
    if mode == "cpu":
        query = f"sum(rate(container_cpu_usage_seconds_total{{{selector}}}[30s]))"
        metric = "cpu_cores"
    else:
        query = f"max(container_memory_working_set_bytes{{{selector}}})"
        metric = "memory_working_set_bytes"
    value = _prometheus_scalar(query)
    active_threshold = float(implementation["active_threshold"])
    recovery_threshold = float(
        implementation.get("recovery_threshold", active_threshold * 0.2)
    )
    if active:
        matches = value is not None and value >= active_threshold
    elif implementation["strategy"] == "workload_stress":
        matches = value is not None and value < recovery_threshold
    else:
        matches = value is None or value < recovery_threshold
    return matches, {
        "metric": metric,
        "value": value,
        "pods": pods,
        "active_threshold": active_threshold,
        "recovery_threshold": recovery_threshold,
    }


def _stress_metric_pods(scenario: dict[str, Any], active: bool) -> list[str]:
    implementation = scenario["implementation"]
    if implementation["strategy"] == "stress":
        return [fault_name(scenario)]
    component = implementation["component"]
    result = kubectl(
        [
            "-n",
            namespace(),
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/component={component}",
            "-o",
            "json",
        ]
    )
    require_success(result, f"list metric pods for {component}")
    pods: list[str] = []
    for pod in json.loads(result.stdout).get("items", []):
        names = [item.get("name") for item in _dig(pod, "spec", "containers", default=[])]
        if not active or _stress_container_name() in names:
            pods.append(str(_dig(pod, "metadata", "name", default="")))
    return [name for name in pods if name]


def _prometheus_scalar(query: str) -> float | None:
    service = "otel-demo-prometheus-server"
    path = (
        f"/api/v1/namespaces/{namespace()}/services/http:{service}:9090/"
        f"proxy/api/v1/query?{urlencode({'query': query})}"
    )
    result = kubectl(["get", "--raw", path], timeout=60)
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        values = payload.get("data", {}).get("result", [])
        if not values:
            return None
        value = float(values[0]["value"][1])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _stress_container_name() -> str:
    return "telemetry-health"


def _inject_deployment(implementation: dict[str, Any]) -> None:
    name = f"otel-demo-{implementation['component']}"
    fault = implementation["fault"]
    container = implementation["component"]
    if fault == "replicas":
        patch = {"spec": {"replicas": implementation["faulty"]}}
    elif fault == "image":
        patch = {"spec": {"template": {"spec": {"containers": [{"name": container, "image": f"invalid.local/opsbench/{container}:missing"}]}}}}
    elif fault in {"cpu_limit", "memory_limit"}:
        resource = "cpu" if fault == "cpu_limit" else "memory"
        patch = {"spec": {"template": {"spec": {"containers": [{"name": container, "resources": {"limits": {resource: implementation["faulty"]}, "requests": {resource: implementation["faulty"]}}}]}}}}
    elif fault == "node_selector":
        patch = {"spec": {"template": {"spec": {"nodeSelector": {"opsbench.io/nonexistent": "true"}}}}}
    elif fault == "read_only_root":
        patch = {"spec": {"template": {"spec": {"containers": [{"name": container, "securityContext": {"readOnlyRootFilesystem": True}}]}}}}
    elif fault == "crash":
        patch = {"spec": {"template": {"spec": {"containers": [{"name": container, "command": ["/bin/sh", "-c"], "args": ["echo forced crash >&2; exit 1"]}]}}}}
    else:
        raise RuntimeError(f"unsupported deployment fault: {fault}")
    _patch("deployment", name, patch, patch_type="strategic")


def _deployment_fault_state(implementation: dict[str, Any], active: bool) -> tuple[bool, dict[str, Any]]:
    deployment = _deployment(implementation["component"])
    fault = implementation["fault"]
    container = _container(deployment, implementation["component"])
    details: dict[str, Any] = {"deployment_ready": _deployment_object_ready(deployment)}
    if fault == "replicas":
        observed = _dig(deployment, "spec", "replicas", default=1)
        expected = implementation["faulty" if active else "healthy"]
    elif fault == "image":
        observed = str(container.get("image", ""))
        expected = "invalid.local/" if active else "otel/demo:"
        details["image"] = observed
        matches = observed.startswith(expected)
        return (matches and (active or details["deployment_ready"])), details
    elif fault in {"cpu_limit", "memory_limit"}:
        resource = "cpu" if fault == "cpu_limit" else "memory"
        observed = _dig(container, "resources", "limits", resource)
        expected = implementation["faulty" if active else "healthy"]
    elif fault == "node_selector":
        observed = _dig(deployment, "spec", "template", "spec", "nodeSelector", "opsbench.io/nonexistent")
        expected = "true" if active else None
    elif fault == "read_only_root":
        observed = _dig(container, "securityContext", "readOnlyRootFilesystem", default=False)
        expected = True if active else False
    elif fault == "crash":
        observed = container.get("command")
        expected = ["/bin/sh", "-c"] if active else None
    else:
        raise RuntimeError(f"unsupported deployment fault: {fault}")
    details["observed"] = observed
    matches = observed == expected
    return (matches and (active or details["deployment_ready"])), details


def _inject_service(implementation: dict[str, Any]) -> None:
    component = implementation["component"]
    fault = implementation["fault"]
    if fault == "delete":
        _delete("service", f"otel-demo-{component}")
    elif fault == "selector":
        _patch_service(component, {"selector": {"app.kubernetes.io/component": implementation["faulty"]}})
    elif fault == "target_port":
        _patch("service", f"otel-demo-{component}", [{"op": "replace", "path": "/spec/ports/0/targetPort", "value": implementation["faulty"]}], patch_type="json")
    elif fault == "affinity":
        _patch_service(component, {"sessionAffinity": implementation["faulty"]})
    elif fault == "type":
        _patch_service(component, {"type": implementation["faulty"]})
    else:
        raise RuntimeError(f"unsupported service fault: {fault}")


def _service_fault_state(implementation: dict[str, Any], active: bool) -> tuple[bool, dict[str, Any]]:
    component = implementation["component"]
    service = _get_json("service", f"otel-demo-{component}", allow_missing=True)
    fault = implementation["fault"]
    if fault == "delete":
        exists = service is not None
        if active:
            return not exists, {"service_exists": exists}
        endpoints = _endpoint_count(component) if exists else 0
        return exists and endpoints > 0, {"service_exists": exists, "endpoint_count": endpoints}
    if service is None:
        return False, {"service_exists": False}
    expected = implementation["faulty" if active else "healthy"]
    if fault == "selector":
        observed = _dig(service, "spec", "selector", "app.kubernetes.io/component")
    elif fault == "target_port":
        observed = _dig(service, "spec", "ports", default=[{}])[0].get("targetPort")
    elif fault == "affinity":
        observed = _dig(service, "spec", "sessionAffinity", default="None")
    elif fault == "type":
        observed = _dig(service, "spec", "type", default="ClusterIP")
    else:
        raise RuntimeError(f"unsupported service fault: {fault}")
    endpoints = _endpoint_count(component)
    details = {"observed": observed, "endpoint_count": endpoints}
    matches = str(observed) == str(expected)
    if active:
        return matches, details
    requires_endpoints = fault in {"selector", "target_port", "delete"}
    return matches and (not requires_endpoints or endpoints > 0), details


def _apply_network_policy(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    component = implementation["component"]
    fault = implementation["fault"]
    spec: dict[str, Any] = {"podSelector": {"matchLabels": {"app.kubernetes.io/component": component}}}
    if fault in {"deny_ingress", "deny_all"}:
        spec.update({"policyTypes": ["Ingress"], "ingress": []})
    if fault == "deny_egress":
        spec.update({"policyTypes": ["Egress"], "egress": []})
    _apply({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": fault_name(scenario), "namespace": namespace(), "labels": _fault_labels(scenario)}, "spec": spec})


def _inject_node(implementation: dict[str, Any]) -> None:
    node = _node_name()
    if implementation["fault"] == "cordon":
        require_success(kubectl(["cordon", node]), "cordon node")
    else:
        require_success(kubectl(["taint", "node", node, f"{implementation['key']}=true:NoSchedule", "--overwrite"]), "taint node")


def _node_fault_state(implementation: dict[str, Any], active: bool) -> tuple[bool, dict[str, Any]]:
    node = _get_json("node", _node_name(), namespaced=False)
    if implementation["fault"] == "cordon":
        observed = bool(_dig(node, "spec", "unschedulable", default=False))
        return observed == active, {"unschedulable": observed}
    taints = _dig(node, "spec", "taints", default=[])
    present = any(item.get("key") == implementation["key"] for item in taints)
    return present == active, {"taint_present": present}


def _apply_config_probe(scenario: dict[str, Any], value: str) -> None:
    implementation = scenario["implementation"]
    name = fault_name(scenario)
    labels = _fault_labels(scenario)
    _apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name, "namespace": namespace(), "labels": labels}, "data": {"value": str(value), "expected": str(implementation["healthy"])}})
    _apply({
        "apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "namespace": namespace(), "labels": labels},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}}, "template": {"metadata": {"labels": {"app": name, **labels}}, "spec": {"containers": [{"name": "validator", "image": FAULT_IMAGE, "command": ["/bin/sh", "-c"], "args": ["while :; do test \"$(cat /config/value)\" = \"$(cat /config/expected)\" || exit 1; sleep 2; done"], "volumeMounts": [{"name": "config", "mountPath": "/config", "readOnly": True}], "resources": {"limits": {"memory": "64Mi", "cpu": "100m"}}}], "volumes": [{"name": "config", "configMap": {"name": name}}]}}}
    })


def _patch_config_probe(scenario: dict[str, Any], value: str) -> None:
    name = fault_name(scenario)
    _patch("configmap", name, {"data": {"value": str(value)}})
    _delete_pods_by_label(f"app={name}")


def _apply_pending_pod(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    spec: dict[str, Any] = {"restartPolicy": "Never", "containers": [{"name": "pending", "image": FAULT_IMAGE, "command": ["sleep", "3600"], "resources": {"requests": {"cpu": "100"}}}]}
    if implementation["fault"] == "volume_zone":
        spec["containers"][0]["resources"] = {"requests": {"cpu": "10m", "memory": "16Mi"}}
        spec["nodeSelector"] = {"topology.kubernetes.io/zone": "unavailable-zone"}
        spec["volumes"] = [{"name": "data", "emptyDir": {}}]
        spec["containers"][0]["volumeMounts"] = [{"name": "data", "mountPath": "/data"}]
    _apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": fault_name(scenario), "namespace": namespace(), "labels": _fault_labels(scenario)}, "spec": spec})


def _inject_pull_secret(scenario: dict[str, Any]) -> None:
    name = fault_name(scenario)
    _apply({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": name, "namespace": namespace(), "labels": _fault_labels(scenario)}, "type": "kubernetes.io/dockerconfigjson", "data": {".dockerconfigjson": "e30="}})
    component = scenario["implementation"]["component"]
    _patch(
        "deployment",
        f"otel-demo-{component}",
        {
            "spec": {
                "template": {
                    "spec": {
                        "imagePullSecrets": [{"name": name}],
                        "containers": [
                            {
                                "name": component,
                                "image": f"invalid.local/private/{component}:missing",
                            }
                        ],
                    }
                }
            }
        },
        patch_type="strategic",
    )


def _inject_proxy(scenario: dict[str, Any]) -> None:
    implementation = scenario["implementation"]
    component = implementation["component"]
    service = _get_json("service", f"otel-demo-{component}")
    assert service is not None
    original_ports = _dig(service, "spec", "ports", default=[])
    first_port = original_ports[0]
    listen_port = int(first_port.get("targetPort", first_port["port"]))
    upstream_port = int(first_port["port"])
    name = fault_name(scenario)
    alias_name = f"{name}-upstream"
    labels = _fault_labels(scenario)
    _apply(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": alias_name, "namespace": namespace(), "labels": labels},
            "spec": {
                "selector": {"app.kubernetes.io/component": component},
                "ports": original_ports,
            },
        }
    )
    _apply(
        {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": name,
                "namespace": namespace(),
                "labels": {**labels, "opsbench.io/proxy": scenario["id"]},
            },
            "spec": {
                "restartPolicy": "Always",
                "containers": [
                    {
                        "name": "fault-proxy",
                        "image": PROXY_IMAGE,
                        "command": ["python", "-u", "-c", _proxy_program()],
                        "env": [
                            {"name": "LISTEN_PORT", "value": str(listen_port)},
                            {"name": "UPSTREAM_HOST", "value": alias_name},
                            {"name": "UPSTREAM_PORT", "value": str(upstream_port)},
                            {"name": "FAULT_MODE", "value": implementation["mode"]},
                        ],
                        "resources": {
                            "requests": {"cpu": "20m", "memory": "24Mi"},
                            "limits": {"cpu": "250m", "memory": "96Mi"},
                        },
                    }
                ],
            },
        }
    )
    _patch(
        "service",
        f"otel-demo-{component}",
        [
            {
                "op": "replace",
                "path": "/spec/selector",
                "value": {"opsbench.io/proxy": scenario["id"]},
            }
        ],
        patch_type="json",
    )


def _proxy_fault_state(
    scenario: dict[str, Any], active: bool
) -> tuple[bool, dict[str, Any]]:
    implementation = scenario["implementation"]
    component = implementation["component"]
    service = _get_json("service", f"otel-demo-{component}", allow_missing=True)
    selector = _dig(service or {}, "spec", "selector", default={})
    proxy_selected = selector.get("opsbench.io/proxy") == scenario["id"]
    pod = _get_json("pod", fault_name(scenario), allow_missing=True)
    pod_phase = _dig(pod or {}, "status", "phase", default="Missing")
    details = {
        "service_selector": selector,
        "proxy_pod_phase": pod_phase,
        "endpoint_count": _endpoint_count(component),
    }
    if active:
        return proxy_selected and pod_phase == "Running" and details["endpoint_count"] > 0, details
    original_selected = selector.get("app.kubernetes.io/component") == component
    return original_selected and details["endpoint_count"] > 0, details


def _proxy_program() -> str:
    return """import os, random, socket, threading, time
listen_port = int(os.environ['LISTEN_PORT'])
upstream = (os.environ['UPSTREAM_HOST'], int(os.environ['UPSTREAM_PORT']))
mode = os.environ['FAULT_MODE']
def relay(source, target):
    try:
        while True:
            data = source.recv(4096)
            if not data:
                break
            target.sendall(data)
            if mode == 'bandwidth':
                time.sleep(len(data) / 16384)
    except OSError:
        pass
    finally:
        try: target.shutdown(socket.SHUT_WR)
        except OSError: pass
def handle(client):
    if mode == 'packet_loss' and random.random() < 0.5:
        client.close()
        return
    if mode == 'latency':
        time.sleep(0.5)
    try:
        remote = socket.create_connection(upstream, timeout=10)
        threading.Thread(target=relay, args=(client, remote), daemon=True).start()
        relay(remote, client)
    except OSError:
        client.close()
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', listen_port))
server.listen(128)
while True:
    client, _ = server.accept()
    threading.Thread(target=handle, args=(client,), daemon=True).start()
"""


def _inject_quota(scenario: dict[str, Any]) -> None:
    pods = _list_json("pods")
    count = len(pods.get("items", []))
    _apply({"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": fault_name(scenario), "namespace": namespace(), "labels": _fault_labels(scenario)}, "spec": {"hard": {"pods": str(max(count, 1))}}})


def _apply_ingress(scenario: dict[str, Any], value: str) -> None:
    implementation = scenario["implementation"]
    name = fault_name(scenario)
    path = value if implementation["fault"] == "path" else "/"
    annotations = {"nginx.ingress.kubernetes.io/ssl-redirect": value if implementation["fault"] == "ssl_redirect" else "true"}
    _apply({"apiVersion": "networking.k8s.io/v1", "kind": "Ingress", "metadata": {"name": name, "namespace": namespace(), "labels": _fault_labels(scenario), "annotations": annotations}, "spec": {"rules": [{"host": f"{name}.test", "http": {"paths": [{"path": path, "pathType": "Prefix", "backend": {"service": {"name": "otel-demo-frontendproxy", "port": {"number": 8080}}}}]}}]}})


def _ingress_value(scenario: dict[str, Any]) -> str:
    ingress = _get_json("ingress", fault_name(scenario))
    if scenario["implementation"]["fault"] == "path":
        return str(_dig(ingress, "spec", "rules", default=[{}])[0].get("http", {}).get("paths", [{}])[0].get("path", ""))
    return str(_dig(ingress, "metadata", "annotations", "nginx.ingress.kubernetes.io/ssl-redirect", default=""))


def _apply(manifest: dict[str, Any]) -> None:
    import subprocess
    result = subprocess.run(["kubectl", "apply", "-f", "-"], input=json.dumps(manifest), text=True, capture_output=True, timeout=120, check=False)
    require_success(result, f"apply {manifest['kind']}/{manifest['metadata']['name']}")


def _patch(kind: str, name: str, patch: Any, patch_type: str = "merge") -> None:
    result = kubectl(["-n", namespace(), "patch", kind, name, f"--type={patch_type}", "-p", json.dumps(patch)])
    require_success(result, f"patch {kind}/{name}")


def _patch_service(component: str, spec_patch: dict[str, Any]) -> None:
    _patch("service", f"otel-demo-{component}", {"spec": spec_patch})


def _delete(kind: str, name: str) -> None:
    result = kubectl(["-n", namespace(), "delete", kind, name, "--ignore-not-found=true", "--wait=false"])
    require_success(result, f"delete {kind}/{name}")


def _delete_pods_by_label(selector: str) -> None:
    result = kubectl(["-n", namespace(), "delete", "pod", "-l", selector, "--wait=false"])
    require_success(result, f"delete pods matching {selector}")


def _get_json(kind: str, name: str, allow_missing: bool = False, namespaced: bool = True) -> dict[str, Any] | None:
    args = (["-n", namespace()] if namespaced else []) + ["get", kind, name, "-o", "json"]
    result = kubectl(args)
    if allow_missing and result.returncode != 0:
        return None
    require_success(result, f"get {kind}/{name}")
    return json.loads(result.stdout)


def _list_json(kind: str) -> dict[str, Any]:
    result = kubectl(["-n", namespace(), "get", kind, "-o", "json"])
    require_success(result, f"list {kind}")
    return json.loads(result.stdout)


def _deployment(component: str) -> dict[str, Any]:
    result = _get_json("deployment", f"otel-demo-{component}")
    assert result is not None
    return result


def _container(deployment: dict[str, Any], name: str) -> dict[str, Any]:
    containers = _dig(deployment, "spec", "template", "spec", "containers", default=[])
    return next(item for item in containers if item.get("name") == name)


def _find_container(
    deployment: dict[str, Any], name: str
) -> dict[str, Any] | None:
    containers = _dig(deployment, "spec", "template", "spec", "containers", default=[])
    return next((item for item in containers if item.get("name") == name), None)


def _deployment_ready(name: str) -> bool:
    deployment = _get_json("deployment", name, allow_missing=True)
    return bool(deployment and _deployment_object_ready(deployment))


def _deployment_object_ready(deployment: dict[str, Any]) -> bool:
    desired = int(_dig(deployment, "spec", "replicas", default=1) or 0)
    available = int(_dig(deployment, "status", "availableReplicas", default=0) or 0)
    return desired > 0 and available >= desired


def _wait_deployment(name: str, ready: bool, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _deployment_ready(name) == ready:
            return
        time.sleep(2)
    raise RuntimeError(f"deployment/{name} did not reach ready={ready}")


def _config_value(name: str) -> str:
    config = _get_json("configmap", name, allow_missing=True)
    return str(_dig(config or {}, "data", "value", default=""))


def _endpoint_count(component: str) -> int:
    endpoints = _get_json("endpoints", f"otel-demo-{component}", allow_missing=True)
    return sum(len(subset.get("addresses", [])) for subset in _dig(endpoints or {}, "subsets", default=[]))


def _component_waiting_reasons(component: str) -> list[str]:
    result = kubectl(
        [
            "-n",
            namespace(),
            "get",
            "pods",
            "-l",
            f"app.kubernetes.io/component={component}",
            "-o",
            "json",
        ]
    )
    require_success(result, f"list pods for {component}")
    reasons: list[str] = []
    for pod in json.loads(result.stdout).get("items", []):
        for status in _dig(pod, "status", "containerStatuses", default=[]):
            reason = _dig(status, "state", "waiting", "reason")
            if reason:
                reasons.append(str(reason))
    return reasons


def _node_name() -> str:
    result = kubectl(["get", "nodes", "-o", "jsonpath={.items[0].metadata.name}"])
    require_success(result, "read benchmark node name")
    return result.stdout.strip()


def _fault_labels(scenario: dict[str, Any]) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": "otel-demo",
        "app.kubernetes.io/instance": "otel-demo",
        "app.kubernetes.io/part-of": "opentelemetry-demo",
        "app.kubernetes.io/component": "health-agent",
    }


def _dig(value: Any, *keys: Any, default: Any = None) -> Any:
    current = value
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current
