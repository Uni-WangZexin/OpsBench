from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FAULTS_PATH = ROOT / "故障.md"
CASES_ROOT = ROOT / "cases"
KUBERNETES_TEMPLATE_ROOT = CASES_ROOT / "_kubernetes_otel"
KUBERNETES_SCRIPT_NAMES = (
    "common.py",
    "faults.py",
    "setup.py",
    "inject.py",
    "check_injected.py",
    "verify.py",
    "cleanup.py",
)


STATE_SPECS: dict[str, tuple[str, str, str, str, str]] = {
    "TCI038": ("cpu_load", "normal", "saturated", "Deployment/frontend", "Deployment"),
    "TCI039": ("memory_pressure", "normal", "exhausted", "Deployment/frontend", "Deployment"),
    "TCI040": ("disk_io_pressure", "normal", "saturated", "Pod/accounting", "Pod"),
    "TCI041": ("pod_lifecycle", "stable", "forced-restart", "Pod/checkout", "Pod"),
    "TCI042": ("listen_port", "8080", "closed", "Deployment/frontend-proxy", "Deployment"),
    "TCI043": ("pod_connectivity", "allowed", "denied", "NetworkPolicy/frontend", "NetworkPolicy"),
    "TCI044": ("cpu_limit", "500m", "100m", "Deployment/product-catalog", "Deployment"),
    "TCI045": ("node_network", "reachable", "unreachable", "Node/worker-0", "Node"),
    "TCI046": ("cpu_pressure", "false", "true", "Node/worker-0", "Node"),
    "TCI047": ("memory_pressure", "false", "true", "Node/worker-0", "Node"),
    "TCI048": ("disk_io_pressure", "false", "true", "Node/worker-0", "Node"),
    "TCI049": ("network_utilization", "normal", "saturated", "Node/worker-0", "Node"),
    "TCI050": ("kubelet_state", "running", "stopped", "Node/worker-0", "Node"),
    "TCI051": ("kubelet_certificate", "valid", "expired", "Node/worker-0", "Certificate"),
    "TCI052": ("cgroup_driver", "systemd", "mismatched", "Node/worker-0", "KubeletConfiguration"),
    "TCI053": ("root_filesystem", "writable", "read-only", "Node/worker-0", "Node"),
    "TCI054": ("disk_usage", "45%", "100%", "Node/worker-0", "Node"),
    "TCI055": ("ip_forward", "1", "0", "Node/worker-0", "Sysctl"),
    "TCI056": ("scheduler_capacity", "available", "insufficient", "Pod/load-generator", "Pod"),
    "TCI057": ("node_affinity", "satisfiable", "unsatisfiable", "Deployment/frontend", "Deployment"),
    "TCI058": ("volume_zone", "same-zone", "cross-zone", "PersistentVolume/checkout", "PersistentVolume"),
    "TCI059": ("nfs_endpoint", "available", "unavailable", "PersistentVolume/accounting", "PersistentVolume"),
    "TCI060": ("obs_access_key", "valid", "invalid", "Secret/telemetry-export", "Secret"),
    "TCI061": ("image_reference", "valid", "invalid-tag", "Deployment/frontend", "Deployment"),
    "TCI062": ("image_pull_secret", "valid", "invalid", "ServiceAccount/default", "Secret"),
    "TCI063": ("subnet_ip_capacity", "available", "exhausted", "Namespace/otel-demo", "NetworkAttachment"),
    "TCI064": ("conntrack_capacity", "available", "exhausted", "Pod/frontend-proxy", "Pod"),
    "TCI065": ("packet_loss", "0%", "50%", "NetworkPolicy/frontend", "NetworkPolicy"),
    "TCI066": ("egress_bandwidth", "normal", "saturated", "Service/frontend-proxy", "Service"),
    "TCI067": ("syn_backlog", "normal", "flooded", "Service/frontend-proxy", "Service"),
    "TCI068": ("security_group_port_80", "allow", "deny", "ConfigMap/security-group", "CloudSecurityGroup"),
    "TCI069": ("network_acl", "allow", "deny", "ConfigMap/network-acl", "CloudNetworkACL"),
    "TCI070": ("service_owner", "expected", "shadowed", "Service/critical-svc", "Service"),
    "TCI071": ("controller_config", "valid", "invalid", "ConfigMap/ingress-nginx-controller", "ConfigMap"),
    "TCI072": ("session_affinity", "cookie", "none", "Ingress/frontend", "Ingress"),
    "TCI073": ("service_selector", "matched", "missing", "Service/frontend", "Service"),
    "TCI074": ("rewrite_target", "/", "/invalid-path", "Ingress/frontend", "Ingress"),
    "TCI075": ("service_port", "80", "8080", "Service/frontend-proxy", "Service"),
    "TCI076": ("controller_image", "valid", "invalid", "Deployment/ingress-nginx-controller", "Deployment"),
    "TCI077": ("coredns_kubernetes_plugin", "enabled", "removed", "ConfigMap/coredns", "ConfigMap"),
    "TCI078": ("dns_ingress", "allowed", "denied", "NetworkPolicy/coredns", "NetworkPolicy"),
    "TCI079": ("nodelocaldns_upstream", "kube-dns", "127.0.0.1:9999", "ConfigMap/nodelocaldns", "ConfigMap"),
    "TCI080": ("dns_egress_udp_53", "allowed", "denied", "ConfigMap/vpc-dns-policy", "CloudSecurityGroup"),
    "TCI081": ("coredns_cpu_limit", "200m", "50m", "Deployment/coredns", "Deployment"),
    "TCI082": ("dns_query_rate", "normal", "overloaded", "Job/dns-stress-test", "Job"),
    "TCI083": ("backend_replicas", "2", "0", "Deployment/checkout", "Deployment"),
    "TCI084": ("backend_memory_limit", "256Mi", "10Mi", "Deployment/checkout", "Deployment"),
    "TCI085": ("upstream_retries", "3", "1", "Ingress/frontend", "Ingress"),
    "TCI086": ("ingress_path", "/", "/wrong-path", "Ingress/frontend", "Ingress"),
    "TCI087": ("backend_service", "present", "deleted", "Service/checkout", "Service"),
    "TCI088": ("backend_latency", "0ms", "500ms", "Pod/checkout", "Pod"),
    "TCI089": ("ingress_cpu_limit", "500m", "100m", "Deployment/ingress-controller", "Deployment"),
    "TCI090": ("ssl_redirect", "true", "false", "Ingress/frontend", "Ingress"),
    "TCI091": ("tls_certificate", "valid", "expired", "Secret/frontend-tls", "Secret"),
    "TCI092": ("elb_eip", "bound", "unbound", "Service/frontend-proxy", "CloudLoadBalancer"),
}


FAULT_IMPLEMENTATIONS: dict[str, dict[str, Any]] = {
    "TCI038": {"strategy": "workload_stress", "mode": "cpu", "component": "frontend", "active_threshold": 0.65, "recovery_threshold": 0.35},
    "TCI039": {"strategy": "workload_stress", "mode": "memory", "component": "frontend", "active_threshold": 367001600, "recovery_threshold": 314572800},
    "TCI040": {"strategy": "workload_stress", "mode": "io", "component": "checkoutservice"},
    "TCI041": {"strategy": "deployment", "component": "checkoutservice", "fault": "crash"},
    "TCI042": {"strategy": "service", "component": "frontendproxy", "fault": "target_port", "healthy": 8080, "faulty": 65535},
    "TCI043": {"strategy": "network_policy", "component": "frontend", "fault": "deny_ingress"},
    "TCI044": {"strategy": "deployment", "component": "productcatalogservice", "fault": "cpu_limit", "healthy": "500m", "faulty": "100m"},
    "TCI045": {"strategy": "node", "fault": "taint", "key": "opsbench.io/network-unreachable"},
    "TCI046": {"strategy": "stress", "mode": "cpu", "target": "node", "workers": 4, "active_threshold": 2.0, "recovery_threshold": 0.2},
    "TCI047": {"strategy": "stress", "mode": "memory", "target": "node", "memory_mib": 1280, "active_threshold": 1073741824, "recovery_threshold": 134217728},
    "TCI048": {"strategy": "stress", "mode": "io", "target": "node"},
    "TCI049": {"strategy": "stress", "mode": "network", "target": "frontendproxy"},
    "TCI050": {"strategy": "node", "fault": "cordon"},
    "TCI051": {"strategy": "config_probe", "key": "certificate", "healthy": "valid", "faulty": "expired"},
    "TCI052": {"strategy": "config_probe", "key": "cgroup-driver", "healthy": "systemd", "faulty": "cgroupfs"},
    "TCI053": {"strategy": "deployment", "component": "frontend", "fault": "read_only_root"},
    "TCI054": {"strategy": "stress", "mode": "disk_fill", "target": "node"},
    "TCI055": {"strategy": "config_probe", "key": "ip-forward", "healthy": "1", "faulty": "0"},
    "TCI056": {"strategy": "pending", "fault": "oversized_cpu"},
    "TCI057": {"strategy": "deployment", "component": "frontend", "fault": "node_selector"},
    "TCI058": {"strategy": "pending", "fault": "volume_zone"},
    "TCI059": {"strategy": "config_probe", "key": "nfs-endpoint", "healthy": "nfs.internal:2049", "faulty": "203.0.113.1:2049"},
    "TCI060": {"strategy": "config_probe", "key": "obs-access-key", "healthy": "valid-access-key", "faulty": "invalid-access-key"},
    "TCI061": {"strategy": "deployment", "component": "frontend", "fault": "image"},
    "TCI062": {"strategy": "pull_secret", "component": "frontend"},
    "TCI063": {"strategy": "quota"},
    "TCI064": {"strategy": "stress", "mode": "connections", "target": "frontendproxy"},
    "TCI065": {"strategy": "proxy", "component": "frontendproxy", "mode": "packet_loss"},
    "TCI066": {"strategy": "proxy", "component": "frontendproxy", "mode": "bandwidth"},
    "TCI067": {"strategy": "stress", "mode": "connections", "target": "frontendproxy"},
    "TCI068": {"strategy": "network_policy", "component": "frontendproxy", "fault": "deny_ingress"},
    "TCI069": {"strategy": "network_policy", "component": "frontendproxy", "fault": "deny_all"},
    "TCI070": {"strategy": "service", "component": "checkoutservice", "fault": "selector", "healthy": "checkoutservice", "faulty": "shadow-backend"},
    "TCI071": {"strategy": "config_probe", "key": "controller-config", "healthy": "valid", "faulty": "invalid"},
    "TCI072": {"strategy": "service", "component": "frontendproxy", "fault": "affinity", "healthy": "ClientIP", "faulty": "None"},
    "TCI073": {"strategy": "service", "component": "frontend", "fault": "selector", "healthy": "frontend", "faulty": "missing-backend"},
    "TCI074": {"strategy": "ingress", "fault": "path", "healthy": "/", "faulty": "/invalid-path"},
    "TCI075": {"strategy": "service", "component": "frontendproxy", "fault": "target_port", "healthy": 8080, "faulty": 9999},
    "TCI076": {"strategy": "deployment", "component": "frontendproxy", "fault": "image"},
    "TCI077": {"strategy": "config_probe", "key": "coredns-kubernetes-plugin", "healthy": "enabled", "faulty": "removed"},
    "TCI078": {"strategy": "network_policy", "component": "otelcol", "fault": "deny_ingress"},
    "TCI079": {"strategy": "config_probe", "key": "dns-upstream", "healthy": "kube-dns", "faulty": "127.0.0.1:9999"},
    "TCI080": {"strategy": "network_policy", "component": "loadgenerator", "fault": "deny_egress"},
    "TCI081": {"strategy": "stress", "mode": "dns", "target": "kube-dns"},
    "TCI082": {"strategy": "stress", "mode": "dns", "target": "kube-dns"},
    "TCI083": {"strategy": "deployment", "component": "checkoutservice", "fault": "replicas", "healthy": 1, "faulty": 0},
    "TCI084": {"strategy": "deployment", "component": "checkoutservice", "fault": "memory_limit", "healthy": "128Mi", "faulty": "10Mi"},
    "TCI085": {"strategy": "config_probe", "key": "upstream-retries", "healthy": "3", "faulty": "1"},
    "TCI086": {"strategy": "ingress", "fault": "path", "healthy": "/", "faulty": "/wrong-path"},
    "TCI087": {"strategy": "service", "component": "checkoutservice", "fault": "delete", "healthy": "present", "faulty": "deleted"},
    "TCI088": {"strategy": "proxy", "component": "checkoutservice", "mode": "latency"},
    "TCI089": {"strategy": "deployment", "component": "frontendproxy", "fault": "cpu_limit", "healthy": None, "faulty": "100m"},
    "TCI090": {"strategy": "ingress", "fault": "ssl_redirect", "healthy": "true", "faulty": "false"},
    "TCI091": {"strategy": "config_probe", "key": "tls-certificate", "healthy": "valid", "faulty": "expired"},
    "TCI092": {"strategy": "service", "component": "frontendproxy", "fault": "type", "healthy": "ClusterIP", "faulty": "LoadBalancer"},
}


def parse_fault_rows() -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for line in FAULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not re.match(r"^\| TCI\d{3} \|", line):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        rows[columns[0]] = {
            "tc": columns[0],
            "scene": columns[1],
            "subscene": columns[2],
            "question": columns[5],
            "context": re.sub(r"<br\s*/?>", "\n", columns[6]),
            "root_cause": columns[7],
            "difficulty": columns[13],
        }
    return rows


def command_clients(tc_number: int) -> list[str]:
    if 64 <= tc_number <= 76 or 83 <= tc_number <= 92:
        return ["kubectl", "helm", "curl", "jq"]
    if 77 <= tc_number <= 82:
        return ["kubectl", "helm", "dig", "nslookup", "jq"]
    return ["kubectl", "helm", "jq"]


def make_case(row: dict[str, str], spec: tuple[str, str, str, str, str]) -> None:
    tc = row["tc"]
    field, healthy, faulty, resource, simulated_kind = spec
    case_id = f"otel-k8s-{tc.lower()}-{field.replace('_', '-')}"
    case_dir = CASES_ROOT / case_id
    (case_dir / "hidden").mkdir(parents=True, exist_ok=True)
    (case_dir / "scripts").mkdir(parents=True, exist_ok=True)

    scenario = {
        "id": case_id,
        "tc": tc,
        "component": resource.split("/", 1)[-1],
        "resource": resource,
        "simulated_kind": simulated_kind,
        "severity": "warning" if row["difficulty"].lower() == "basic" else "critical",
        "symptom": f"{row['subscene']}：OpenTelemetry Demo 服务状态异常",
        "signal": f"{resource} reports {field}={faulty}",
        "state": {"field": field, "healthy": healthy, "faulty": faulty},
        "implementation": FAULT_IMPLEMENTATIONS[tc],
    }
    manifest: dict[str, Any] = {
        "id": case_id,
        "domain": "kubernetes",
        "environment": {
            "type": "kubernetes",
            "compose_file": "docker-compose.yaml",
            "services": [],
            "namespace_prefix": f"ops-{tc.lower()}",
            "baseline": {
                "distribution": "kubernetes-1.24+",
                "helm_chart": "open-telemetry/opentelemetry-demo",
                "chart_version": "0.11.0",
                "values_file": "otel-values.yaml",
                "memory_requirement": "6Gi",
            },
        },
        "scripts": {
            "setup": "scripts/setup.py",
            "inject": "scripts/inject.py",
            "check_injected": "scripts/check_injected.py",
            "verify": "scripts/verify.py",
            "cleanup": "scripts/cleanup.py",
        },
        "task": "task.md",
        "hidden_metadata": "hidden/labels.yaml",
        "tool_standard": {
            "id": "kubernetes-observability-v1",
            "tools": [
                "shell",
                "kubectl_logs",
                "list_metrics",
                "query_metrics",
                "search_traces",
                "get_trace",
                "query_logs",
            ],
            "commands": command_clients(int(tc[3:])),
        },
        "timeouts": {"agent_sec": 420},
    }
    labels = {
        "domain": "kubernetes",
        "system": "opentelemetry-demo",
        "source_tc": tc,
        "scene": row["scene"],
        "subscene": row["subscene"],
        "fault_type": field,
        "root_cause": row["root_cause"],
        "difficulty": row["difficulty"],
        "injection": f"kubernetes-real:{FAULT_IMPLEMENTATIONS[tc]['strategy']}",
    }
    task = f"""# OpsBench Task: {tc} {row['subscene']}

The OpenTelemetry Demo environment is reporting an operational incident in its
dedicated Kubernetes namespace. Diagnose the cause from live Kubernetes state
and restore the affected resource to a healthy condition.

## Observed Symptom

{scenario['symptom']}

Use the namespace and command-line clients supplied in the runtime context.
Do not delete the namespace, reinstall the Helm release, or access benchmark
control files. Make the smallest in-place repair and summarize your evidence.

## Success Criteria

The benchmark independently checks that the namespace remains available and
that the real injected fault and its workload impact have been repaired.
"""

    write_json(case_dir / "manifest.yaml", manifest)
    write_json(case_dir / "hidden" / "labels.yaml", labels)
    write_json(case_dir / "hidden" / "scenario.json", scenario)
    (case_dir / "task.md").write_text(task, encoding="utf-8")
    (case_dir / "docker-compose.yaml").write_text(
        (KUBERNETES_TEMPLATE_ROOT / "docker-compose.agent.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    (case_dir / "otel-values.yaml").write_text(
        (KUBERNETES_TEMPLATE_ROOT / "otel-values.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for script_name in KUBERNETES_SCRIPT_NAMES:
        (case_dir / "scripts" / script_name).write_text(
            (KUBERNETES_TEMPLATE_ROOT / "scripts" / script_name).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    rows = parse_fault_rows()
    missing_rows = sorted(set(STATE_SPECS) - set(rows))
    missing_specs = sorted(set(rows) - set(STATE_SPECS))
    missing_implementations = sorted(set(STATE_SPECS) - set(FAULT_IMPLEMENTATIONS))
    if missing_rows or missing_specs or missing_implementations:
        raise SystemExit(
            "catalog mismatch: "
            f"missing_rows={missing_rows}, missing_specs={missing_specs}, "
            f"missing_implementations={missing_implementations}"
        )
    for tc in sorted(rows):
        make_case(rows[tc], STATE_SPECS[tc])
    print(f"generated {len(rows)} Kubernetes cases")


if __name__ == "__main__":
    main()
