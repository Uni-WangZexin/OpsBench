from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode


MAX_TOOL_OUTPUT_CHARS = 6000
STANDARD_TOOL_NAMES = ("shell",)
KUBERNETES_OBSERVABILITY_TOOL_NAMES = (
    "shell",
    "kubectl_logs",
    "list_metrics",
    "query_metrics",
    "search_traces",
    "get_trace",
    "query_logs",
)
TOOL_STANDARD_CONTRACTS = {
    "shell-v1": STANDARD_TOOL_NAMES,
    "postgres-ops-v1": STANDARD_TOOL_NAMES,
    "kubernetes-observability-v1": KUBERNETES_OBSERVABILITY_TOOL_NAMES,
}


def tool_names_for_standard(tool_standard: str) -> tuple[str, ...]:
    try:
        return TOOL_STANDARD_CONTRACTS[tool_standard]
    except KeyError as exc:
        raise ValueError(f"unknown tool standard: {tool_standard}") from exc


@dataclass
class ToolContext:
    """Runtime context for the benchmark-owned agent tool contract."""

    execution_dir: Path
    trace_dir: Path
    command_timeout_sec: int = 60
    tool_standard: str = "shell-v1"
    namespace: str = ""
    _log_counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.execution_dir = self.execution_dir.resolve()
        self.trace_dir = self.trace_dir.resolve()
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def next_log_path(self, prefix: str) -> Path:
        self._log_counter += 1
        return self.trace_dir / f"tool-{prefix}-{self._log_counter:03d}.log"


def create_tools(context: ToolContext) -> dict[str, Callable[..., str]]:
    """Return the benchmark tool surface declared by the case standard."""

    implementations: dict[str, Callable[..., str]] = {
        "shell": lambda command: _shell(context, command),
        "kubectl_logs": lambda pod, container="", since="10m", tail=200, previous=False: (
            _kubectl_logs(context, pod, container, since, tail, previous)
        ),
        "list_metrics": lambda match="", limit=200: _list_metrics(context, match, limit),
        "query_metrics": lambda promql, time="": _query_metrics(context, promql, time),
        "search_traces": (
            lambda service, operation="", lookback="1h", limit=20, tags="":
            _search_traces(context, service, operation, lookback, limit, tags)
        ),
        "get_trace": lambda trace_id: _get_trace(context, trace_id),
        "query_logs": lambda query, service="", limit=100: (
            _query_logs(context, query, service, limit)
        ),
    }
    return {
        name: implementations[name]
        for name in tool_names_for_standard(context.tool_standard)
    }


def _shell(context: ToolContext, command: str) -> str:
    completed = subprocess.run(
        command,
        shell=True,
        cwd=context.execution_dir,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )
    full_output = _format_command_output(
        command,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    context.next_log_path("shell").write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _kubectl_logs(
    context: ToolContext,
    pod: str,
    container: str,
    since: str,
    tail: int,
    previous: bool,
) -> str:
    _require_namespace(context)
    _require_resource_name(pod, "pod")
    if container:
        _require_resource_name(container, "container")
    if not re.fullmatch(r"\d+[smhd]", since):
        raise ValueError("since must look like 30s, 10m, 2h, or 1d")
    tail = _bounded_int(tail, "tail", 1, 2000)
    args = ["-n", context.namespace, "logs", pod, f"--since={since}", f"--tail={tail}"]
    if container:
        args.extend(["-c", container])
    if previous:
        args.append("--previous")
    return _kubectl_result(context, "kubectl-logs", args)


def _query_metrics(context: ToolContext, promql: str, time: str) -> str:
    if not promql.strip():
        raise ValueError("promql must not be empty")
    params = {"query": promql}
    if time:
        params["time"] = time
    return _service_proxy_get(
        context,
        component="prometheus",
        port=9090,
        path="api/v1/query",
        params=params,
        log_prefix="metrics",
    )


def _list_metrics(context: ToolContext, match: str, limit: int) -> str:
    limit = _bounded_int(limit, "limit", 1, 1000)
    _require_namespace(context)
    service = _discover_service(context, "prometheus", 9090)
    raw_path = (
        f"/api/v1/namespaces/{quote(context.namespace, safe='')}/services/"
        f"http:{quote(service, safe='')}:9090/proxy/api/v1/label/__name__/values"
    )
    args = ["get", "--raw", raw_path]
    completed = _run_kubectl(context, args)
    output = completed.stdout
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
            names = [str(name) for name in payload.get("data", [])]
            if match:
                needle = match.lower()
                names = [name for name in names if needle in name.lower()]
            output = json.dumps(
                {
                    "status": payload.get("status", "success"),
                    "matched": len(names),
                    "returned": min(len(names), limit),
                    "metrics": sorted(names)[:limit],
                },
                indent=2,
                sort_keys=True,
            )
        except json.JSONDecodeError:
            pass
    full_output = _format_command_output(
        " ".join(["kubectl", *args]),
        completed.returncode,
        output,
        completed.stderr,
    )
    context.next_log_path("metric-names").write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _search_traces(
    context: ToolContext,
    service: str,
    operation: str,
    lookback: str,
    limit: int,
    tags: str,
) -> str:
    if not service.strip():
        raise ValueError("service must not be empty")
    if not re.fullmatch(r"\d+[smhd]", lookback):
        raise ValueError("lookback must look like 10m, 1h, or 1d")
    params: dict[str, str | int] = {
        "service": service,
        "lookback": lookback,
        "limit": _bounded_int(limit, "limit", 1, 100),
    }
    if operation:
        params["operation"] = operation
    if tags:
        params["tags"] = tags
    return _service_proxy_get(
        context,
        component="jaeger",
        port=16686,
        path="api/traces",
        params=params,
        log_prefix="traces",
    )


def _get_trace(context: ToolContext, trace_id: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{16,32}", trace_id):
        raise ValueError("trace_id must be a 16-32 character hexadecimal trace ID")
    return _service_proxy_get(
        context,
        component="jaeger",
        port=16686,
        path=f"api/traces/{quote(trace_id, safe='')}",
        params={},
        log_prefix="trace",
    )


def _query_logs(context: ToolContext, query: str, service: str, limit: int) -> str:
    if not query.strip():
        raise ValueError("query must not be empty")
    log_query = query
    if service:
        escaped_service = service.replace('"', '\\"')
        log_query = (
            f'({query}) AND (serviceName:"{escaped_service}" OR '
            f'resource.attributes.service.name:"{escaped_service}")'
        )
    return _service_proxy_get(
        context,
        component="opensearch",
        port=9200,
        path="_search",
        params={"q": log_query, "size": _bounded_int(limit, "limit", 1, 500)},
        log_prefix="logs",
    )


def _service_proxy_get(
    context: ToolContext,
    component: str,
    port: int,
    path: str,
    params: dict[str, str | int],
    log_prefix: str,
) -> str:
    _require_namespace(context)
    service = _discover_service(context, component, port)
    query = urlencode(params)
    raw_path = (
        f"/api/v1/namespaces/{quote(context.namespace, safe='')}/services/"
        f"http:{quote(service, safe='')}:{port}/proxy/{path}"
    )
    if query:
        raw_path = f"{raw_path}?{query}"
    return _kubectl_result(context, log_prefix, ["get", "--raw", raw_path], pretty_json=True)


def _discover_service(context: ToolContext, component: str, port: int) -> str:
    completed = _run_kubectl(
        context,
        ["-n", context.namespace, "get", "services", "-o", "json"],
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "failed to list Kubernetes Services")
    try:
        services = json.loads(completed.stdout).get("items", [])
    except json.JSONDecodeError as exc:
        raise RuntimeError("kubectl returned invalid Service JSON") from exc

    candidates: list[tuple[int, str]] = []
    for item in services:
        metadata = item.get("metadata", {})
        name = str(metadata.get("name", ""))
        searchable = " ".join(
            [name, *[str(value) for value in metadata.get("labels", {}).values()]]
        ).lower()
        ports = item.get("spec", {}).get("ports", [])
        has_port = any(entry.get("port") == port for entry in ports)
        score = (4 if component in searchable else 0) + (2 if has_port else 0)
        if score >= 4:
            candidates.append((score, name))
    if not candidates:
        raise RuntimeError(
            f"no {component} Service was discovered in namespace {context.namespace}"
        )
    return max(candidates)[1]


def _kubectl_result(
    context: ToolContext,
    prefix: str,
    args: list[str],
    pretty_json: bool = False,
) -> str:
    completed = _run_kubectl(context, args)
    output = completed.stdout
    if pretty_json and completed.returncode == 0:
        try:
            output = json.dumps(json.loads(output), indent=2, sort_keys=True)
        except json.JSONDecodeError:
            pass
    full_output = _format_command_output(
        " ".join(["kubectl", *args]),
        completed.returncode,
        output,
        completed.stderr,
    )
    context.next_log_path(prefix).write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _run_kubectl(context: ToolContext, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["kubectl", *args],
        shell=False,
        cwd=context.execution_dir,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )


def _require_namespace(context: ToolContext) -> None:
    if not context.namespace:
        raise ValueError("Kubernetes namespace is not configured")


def _require_resource_name(value: str, field_name: str) -> None:
    if not re.fullmatch(r"[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?", value):
        raise ValueError(f"{field_name} is not a valid Kubernetes resource name")


def _bounded_int(value: int, field_name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _format_command_output(
    command: str,
    returncode: int,
    stdout: str,
    stderr: str,
) -> str:
    return textwrap.dedent(
        f"""\
        $ {command}
        returncode={returncode}

        [stdout]
        {stdout}

        [stderr]
        {stderr}
        """
    )


def _truncate(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    return output[:MAX_TOOL_OUTPUT_CHARS] + "\n[truncated]\n"
