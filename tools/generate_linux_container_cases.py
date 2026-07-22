from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASES_ROOT = ROOT / "cases"
TEMPLATE = CASES_ROOT / "_linux_container"


SCENARIOS = [
    {
        "id": "linux-cpu-runaway-002",
        "domain": "linux",
        "title": "Unexpected Compute Saturation",
        "symptom": "The target host has sustained CPU saturation and routine API checks have become inconsistent.",
        "strategy": "cpu_runaway",
        "fault_type": "resource.cpu_runaway",
        "root_cause": "unbounded_background_compute_worker",
    },
    {
        "id": "linux-memory-growth-003",
        "domain": "linux",
        "title": "Unexpected Memory Growth",
        "symptom": "The target host has lost most of its normal memory headroom even though request volume is low.",
        "strategy": "memory_growth",
        "fault_type": "resource.memory_growth",
        "root_cause": "background_worker_retains_memory",
    },
    {
        "id": "linux-fd-exhaustion-004",
        "domain": "linux",
        "title": "Intermittent Resource Allocation Failures",
        "symptom": "Repeated report-template requests eventually fail while CPU and disk usage remain normal.",
        "strategy": "fd_leak",
        "fault_type": "process.file_descriptor_leak",
        "root_cause": "application_does_not_close_report_files",
    },
    {
        "id": "linux-disk-full-005",
        "domain": "filesystem",
        "title": "Uploads Fail With Insufficient Storage",
        "symptom": "The API is healthy for reads, but new uploads fail with an insufficient-storage response.",
        "strategy": "disk_full",
        "fault_type": "filesystem.capacity_exhausted",
        "root_cause": "unexpected_archive_consumes_data_volume",
    },
    {
        "id": "linux-inode-exhaustion-006",
        "domain": "filesystem",
        "title": "New Files Cannot Be Created",
        "symptom": "The data volume still has byte capacity, but the service cannot create new upload files.",
        "strategy": "inode_full",
        "fault_type": "filesystem.inode_exhausted",
        "root_cause": "cache_contains_excessive_small_files",
    },
    {
        "id": "linux-upload-permission-007",
        "domain": "filesystem",
        "title": "Upload Directory Is Not Writable",
        "symptom": "Health checks pass, but every upload request is rejected by the application.",
        "strategy": "upload_permission",
        "fault_type": "filesystem.permission_denied",
        "root_cause": "upload_directory_owner_and_mode_changed",
    },
    {
        "id": "http-wrong-port-008",
        "domain": "network",
        "title": "API Is Missing From Its Published Port",
        "symptom": "Clients cannot connect to the API on port 8080 even though an application process is running.",
        "strategy": "wrong_port",
        "fault_type": "network.listen_port_mismatch",
        "root_cause": "application_listens_on_8081",
    },
    {
        "id": "http-loopback-bind-009",
        "domain": "network",
        "title": "API Works Locally But Not Across The Network",
        "symptom": "The service responds inside the target host but peer containers cannot reach it on port 8080.",
        "strategy": "loopback_bind",
        "fault_type": "network.loopback_only_bind",
        "root_cause": "application_bound_to_127_0_0_1",
    },
    {
        "id": "app-malformed-config-010",
        "domain": "configuration",
        "title": "Application Fails During Startup",
        "symptom": "The target container remains running, but the HTTP application exits during startup.",
        "strategy": "malformed_config",
        "fault_type": "configuration.invalid_json",
        "root_cause": "runtime_configuration_is_malformed",
    },
    {
        "id": "app-stale-pid-011",
        "domain": "process",
        "title": "Service Cannot Start Although No Instance Is Running",
        "symptom": "The API is down and its service control command refuses to start a replacement process.",
        "strategy": "stale_pid",
        "fault_type": "process.stale_pid_file",
        "root_cause": "stale_pid_file_blocks_startup",
    },
    {
        "id": "http-dependency-dns-012",
        "domain": "network",
        "title": "Order Requests Cannot Resolve Their Dependency",
        "symptom": "Health checks pass, but GET /orders returns 502 and dependency CPU usage is normal.",
        "strategy": "dependency_dns",
        "fault_type": "network.dependency_name_resolution",
        "root_cause": "catalog_dependency_hostname_is_invalid",
    },
    {
        "id": "http-dependency-port-013",
        "domain": "network",
        "title": "Order Requests Cannot Connect Downstream",
        "symptom": "Health checks pass, but GET /orders returns 502 while the catalog process remains alive.",
        "strategy": "dependency_port",
        "fault_type": "network.dependency_port_mismatch",
        "root_cause": "catalog_dependency_port_is_wrong",
    },
    {
        "id": "http-downstream-500-014",
        "domain": "distributed_system",
        "title": "Catalog Dependency Returns Server Errors",
        "symptom": "The main API is healthy, but order requests fail because the local catalog dependency returns errors.",
        "strategy": "dependency_status",
        "fault_type": "dependency.http_500",
        "root_cause": "catalog_dependency_error_mode_enabled",
    },
    {
        "id": "http-downstream-json-015",
        "domain": "distributed_system",
        "title": "Catalog Response Cannot Be Parsed",
        "symptom": "The catalog endpoint responds, but GET /orders returns 502 and logs report response parsing failures.",
        "strategy": "dependency_payload",
        "fault_type": "dependency.malformed_payload",
        "root_cause": "catalog_returns_invalid_json",
    },
    {
        "id": "http-upstream-timeout-016",
        "domain": "distributed_system",
        "title": "Order Requests Time Out Waiting For Catalog",
        "symptom": "The catalog eventually responds, but the main API abandons order requests first.",
        "strategy": "dependency_timeout",
        "fault_type": "dependency.timeout_mismatch",
        "root_cause": "client_timeout_shorter_than_dependency_latency",
    },
    {
        "id": "app-feature-flag-017",
        "domain": "configuration",
        "title": "Checkout Fails For The Enabled Code Path",
        "symptom": "Health and order requests pass, but GET /checkout consistently returns HTTP 500.",
        "strategy": "feature_flag",
        "fault_type": "configuration.feature_flag",
        "root_cause": "unsupported_checkout_v2_path_enabled",
    },
    {
        "id": "linux-file-lock-018",
        "domain": "process",
        "title": "Report Generation Remains Busy",
        "symptom": "GET /report always returns busy even though CPU usage is low and the API is otherwise healthy.",
        "strategy": "file_lock",
        "fault_type": "process.stale_file_lock",
        "root_cause": "background_worker_holds_report_lock",
    },
    {
        "id": "linux-temp-permission-019",
        "domain": "filesystem",
        "title": "Temporary Jobs Cannot Create Files",
        "symptom": "GET /temp fails while ordinary health and read requests continue to work.",
        "strategy": "temp_permission",
        "fault_type": "filesystem.temp_permission",
        "root_cause": "temporary_directory_not_writable_by_service_user",
    },
    {
        "id": "tls-hostname-mismatch-020",
        "domain": "tls",
        "title": "HTTPS Clients Reject The Service Certificate",
        "symptom": "The HTTPS endpoint responds when verification is disabled, but normal clients reject its certificate.",
        "strategy": "tls_hostname",
        "fault_type": "tls.hostname_mismatch",
        "root_cause": "certificate_san_does_not_include_target_hostname",
    },
    {
        "id": "app-env-override-021",
        "domain": "configuration",
        "title": "Effective Port Differs From The Configuration File",
        "symptom": "The configuration file says port 8080, but clients cannot connect there while the process is alive.",
        "strategy": "environment_override",
        "fault_type": "configuration.environment_override",
        "root_cause": "environment_variable_overrides_runtime_port",
    },
]

INJECTION_DESCRIPTIONS = {
    "cpu_runaway": "Start a real SHA-256 compute loop; verify CPU time advances and later falls below the recovery threshold.",
    "memory_growth": "Start a process that allocates and retains 72 MiB; verify its live RSS and later disappearance.",
    "fd_leak": "Enable a real application descriptor leak under a nofile limit of 64 and exercise the affected endpoint.",
    "disk_full": "Fill the data tmpfs with an unlinked file that remains open in a live process; df is full while du cannot see the owner.",
    "inode_full": "Create small files until the tmpfs inode limit rejects another file even though byte capacity remains.",
    "upload_permission": "Remove write access for the non-root service user and verify a real upload fails.",
    "wrong_port": "Restart the application on 8081 while clients continue to use the published contract on 8080.",
    "loopback_bind": "Bind the application to 127.0.0.1 so local probes pass but peer-container traffic fails.",
    "malformed_config": "Install malformed runtime JSON and exercise the real startup parser failure path.",
    "stale_pid": "Leave a stale PID file that causes the service control command to reject a new start.",
    "dependency_dns": "Configure a non-resolving dependency hostname and verify the order request returns 502.",
    "dependency_port": "Point the client at a closed dependency port while the downstream process remains healthy.",
    "dependency_status": "Remove the downstream service user's access to its live catalog data so it returns HTTP 500.",
    "dependency_payload": "Corrupt the downstream catalog data file so the caller receives malformed JSON over a successful HTTP response.",
    "dependency_timeout": "Delay the downstream for 900 ms while the caller times out after 150 ms.",
    "feature_flag": "Enable a known-incompatible checkout code path and verify only checkout fails.",
    "file_lock": "Start a real process holding an advisory lock required by report generation.",
    "temp_permission": "Remove write access from the service temporary directory and exercise file creation.",
    "tls_hostname": "Serve a CA-valid certificate whose SAN names legacy.internal, remove the ready-made target certificate, and require correct reissuance.",
    "environment_override": "Set APP_PORT=8082 so the effective process configuration differs from the JSON file.",
}

DIFFICULTY_BY_STRATEGY = {
    "upload_permission": "low",
    "wrong_port": "low",
    "malformed_config": "low",
    "stale_pid": "low",
    "temp_permission": "low",
    "cpu_runaway": "medium",
    "inode_full": "medium",
    "loopback_bind": "medium",
    "dependency_dns": "medium",
    "dependency_port": "medium",
    "feature_flag": "medium",
    "file_lock": "medium",
    "environment_override": "medium",
    "memory_growth": "hard",
    "fd_leak": "hard",
    "disk_full": "hard",
    "dependency_status": "hard",
    "dependency_payload": "hard",
    "dependency_timeout": "hard",
    "tls_hostname": "hard",
}


COMPOSE = """services:
  target:
    build:
      context: ../..
      dockerfile: __CASE_ID__/Dockerfile
      args:
        CASE_DIR: __CASE_ID__
    hostname: target
    working_dir: /agent-runtime
    cpus: 1.00
    mem_limit: 384m
    pids_limit: 128
    tmpfs:
      - /data:size=24m,nr_inodes=256,mode=0777
      - /tmp/app-cache:size=8m,mode=0777
    volumes:
      - ${OPSBENCH_AGENT_SOURCE}:/agent:ro
      - ${OPSBENCH_TASK_SOURCE}:/task/task.md:ro
      - ${OPSBENCH_AGENT_TRACE_DIR}:/trace
"""


def manifest(item: dict[str, str]) -> dict[str, object]:
    return {
        "id": item["id"],
        "domain": item["domain"],
        "environment": {
            "type": "compose",
            "compose_file": "docker-compose.yaml",
            "services": ["target"],
            "agent_service": "target",
            "baseline": {
                "image_family": "python:3.12-slim-bookworm",
                "target_cpu": "1.00",
                "target_memory": "384MiB",
                "data_tmpfs": "24MiB",
            },
        },
        "scripts": {
            "inject": "scripts/inject.py",
            "check_injected": "scripts/check_injected.py",
            "verify": "scripts/verify.py",
        },
        "task": "task.md",
        "hidden_metadata": "hidden/labels.yaml",
        "tool_standard": {
            "id": "linux-operations-v2",
            "tools": [
                "shell",
                "read_logs",
                "inspect_processes",
                "inspect_sockets",
                "query_host_metrics",
                "inspect_filesystem",
                "probe_http",
                "inspect_file",
                "edit_file",
                "manage_service",
            ],
            "commands": [
                "curl",
                "ps",
                "top",
                "free",
                "df",
                "du",
                "ss",
                "lsof",
                "find",
                "stat",
                "openssl",
            ],
        },
        "timeouts": {"agent_sec": 300},
    }


def task(item: dict[str, str]) -> str:
    return f"""# OpsBench Task: {item['title']}

{item['symptom']}

Diagnose the live target container and apply the smallest durable repair. Do not
work around the symptom by disabling validation or repeatedly restarting the
service without correcting the underlying state.

## Runtime Access

The evaluated agent process is already running inside the lightweight target
container. Shell commands execute directly in the same PID, network, cgroup and
filesystem environment as the affected services; do not use SSH or Docker.

The public service contract expects HTTP on port `8080` and HTTPS on port
`8443`. Normal Linux process, socket, filesystem, HTTP and TLS diagnostic tools
are installed in the target. Discover the effective runtime configuration,
logs and process-control mechanism from live state; their internal paths and
precedence are intentionally not supplied here.

## Success Criteria

The benchmark independently verifies that the original user-visible operation
works again, the underlying fault signal is gone, and the main health endpoint
returns HTTP 200. The target container must remain running.
"""


def generate() -> None:
    for item in SCENARIOS:
        destination = CASES_ROOT / item["id"]
        destination.mkdir(parents=True, exist_ok=True)
        for relative in ["Dockerfile", "runtime", "scripts"]:
            source = TEMPLATE / relative
            target = destination / relative
            if source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        (destination / "hidden").mkdir(exist_ok=True)
        compose = COMPOSE.replace("__CASE_ID__", f"cases/{item['id']}")
        (destination / "docker-compose.yaml").write_text(compose, encoding="utf-8")
        (destination / "manifest.yaml").write_text(
            json.dumps(manifest(item), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        (destination / "task.md").write_text(task(item), encoding="utf-8")
        labels = {
            "domain": item["domain"],
            "system": "lightweight_linux_container",
            "difficulty": DIFFICULTY_BY_STRATEGY[item["strategy"]],
            "fault_type": item["fault_type"],
            "symptom": item["symptom"],
            "root_cause": item["root_cause"],
            "expected_fix_type": "in_place_runtime_repair",
        }
        (destination / "hidden" / "labels.yaml").write_text(
            json.dumps(labels, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        scenario = {
            "case_id": item["id"],
            "implementation": {"strategy": item["strategy"]},
        }
        (destination / "hidden" / "scenario.json").write_text(
            json.dumps(scenario, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
    generate_document()


def generate_document() -> None:
    lines = [
        "# Lightweight Container Fault Cases",
        "",
        "Cases 002-021 each start one resource-bounded Debian target container. The",
        "evaluated Agent process runs directly in that target container after fault",
        "injection. Injection and verification remain benchmark-side operations.",
        "",
        "Common target limits: 1.00 CPU, 384 MiB memory, 128 PIDs, a 24 MiB",
        "data tmpfs, and an 8 MiB temporary tmpfs. The application process is",
        "separately capped at 64 file descriptors for the FD exhaustion case.",
        "",
        "| Case | Domain | Strategy | Real injection and verification |",
        "| --- | --- | --- | --- |",
    ]
    for item in SCENARIOS:
        lines.append(
            f"| `{item['id']}` | {item['domain']} | `{item['strategy']}` | "
            f"{INJECTION_DESCRIPTIONS[item['strategy']]} |"
        )
    lines.extend(
        [
            "",
            "## Agent Boundary",
            "",
            "All 20 cases use `linux-operations-v2`: structured logs, processes,",
            "sockets, host metrics, filesystem, HTTP/TLS, file inspection/editing and",
            "service-management tools, plus an audited shell fallback. The Agent runs in the target",
            "container alongside the affected services. It does not receive the case directory, scenario",
            "JSON, injection code, verifier, Docker socket, or host filesystem.",
            "Only the Agent-owned trace subdirectory is mounted at `/trace`; benchmark phase logs",
            "such as setup, injection, and verification output remain outside the container mount.",
            "Model credentials are added only to the Agent process and are not inherited by the service.",
            "Target Python services are compiled during image construction; source files",
            "and healthy bootstrap copies are removed before the Agent starts.",
            "",
            "The target contains the live service, logs, runtime configuration and Linux",
            "tools. A valid repair must remove the underlying process, resource, file,",
            "permission, socket, dependency, TLS or effective-configuration signal and",
            "restore the affected user operation plus `/health`.",
            "",
        ]
    )
    (ROOT / "Lightweight容器故障说明.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    generate()
