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
LINUX_OPERATIONS_TOOL_NAMES = (
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
)
POSTGRES_OPERATIONS_TOOL_NAMES = (
    "shell",
    "inspect_database",
    "query_database",
    "explain_query",
)
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
    "linux-container-v1": STANDARD_TOOL_NAMES,
    "postgres-ops-v1": STANDARD_TOOL_NAMES,
    "linux-operations-v2": LINUX_OPERATIONS_TOOL_NAMES,
    "postgres-operations-v2": POSTGRES_OPERATIONS_TOOL_NAMES,
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
        "read_logs": lambda path="", query="", tail=200: _read_logs(
            context, path, query, tail
        ),
        "inspect_processes": lambda query="", limit=50: _inspect_processes(
            context, query, limit
        ),
        "inspect_sockets": lambda port=0, listening=True: _inspect_sockets(
            context, port, listening
        ),
        "query_host_metrics": lambda pid=0, sample_seconds=1.0: _query_host_metrics(
            context, pid, sample_seconds
        ),
        "inspect_filesystem": lambda path="/": _inspect_filesystem(context, path),
        "probe_http": (
            lambda url, method="GET", body="", timeout_sec=5, ca_file="":
            _probe_http(context, url, method, body, timeout_sec, ca_file)
        ),
        "inspect_file": lambda path, max_bytes=4000: _inspect_file(
            context, path, max_bytes
        ),
        "edit_file": lambda path, old_text, new_text: _edit_file(
            context, path, old_text, new_text
        ),
        "manage_service": lambda service, action: _manage_service(
            context, service, action
        ),
        "inspect_database": lambda scope="overview", relation="": _inspect_database(
            context, scope, relation
        ),
        "query_database": lambda sql: _query_database(context, sql),
        "explain_query": lambda sql, analyze=False: _explain_query(
            context, sql, analyze
        ),
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
    full_output = _redact_sensitive_text(full_output)
    context.next_log_path("shell").write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _read_logs(context: ToolContext, path: str, query: str, tail: int) -> str:
    tail = _bounded_int(tail, "tail", 1, 2000)
    log_root = Path("/var/log").resolve()
    if not path:
        files = sorted(
            str(item)
            for item in log_root.rglob("*")
            if item.is_file() and not item.is_symlink()
        )[:200]
        return _record_text(context, "logs", json.dumps({"log_files": files}, indent=2))
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(log_root):
        raise ValueError("log path must be inside /var/log")
    if not candidate.is_file():
        raise ValueError(f"log file does not exist: {candidate}")
    lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
    if query:
        needle = query.lower()
        lines = [line for line in lines if needle in line.lower()]
    payload = {
        "path": str(candidate),
        "query": query,
        "matched": len(lines),
        "lines": lines[-tail:],
    }
    return _record_text(context, "logs", json.dumps(payload, indent=2))


def _inspect_processes(context: ToolContext, query: str, limit: int) -> str:
    limit = _bounded_int(limit, "limit", 1, 200)
    completed = _run_tool_command(
        context,
        "processes",
        [
            "ps", "-eo", "pid,ppid,user,stat,%cpu,%mem,rss,etimes,comm,args",
            "--sort=-%cpu",
        ],
    )
    if completed.returncode != 0 or not query:
        return _completed_output(context, "processes", completed, already_recorded=True)
    lines = completed.stdout.splitlines()
    needle = query.lower()
    filtered = [lines[0], *[line for line in lines[1:] if needle in line.lower()][:limit]]
    return _record_text(context, "processes-filtered", "\n".join(filtered) + "\n")


def _inspect_sockets(context: ToolContext, port: int, listening: bool) -> str:
    port = _bounded_int(port, "port", 0, 65535)
    command = ["ss", "-H", "-n", "-t", "-u", "-p"]
    command.append("-l" if listening else "-a")
    completed = _run_tool_command(context, "sockets", command)
    if completed.returncode != 0 or port == 0:
        return _completed_output(context, "sockets", completed, already_recorded=True)
    matches = [
        line for line in completed.stdout.splitlines()
        if re.search(rf"(?:\]|:){port}(?:\s|$)", line)
    ]
    return _record_text(
        context,
        "sockets-filtered",
        json.dumps({"port": port, "listening": listening, "sockets": matches}, indent=2),
    )


def _query_host_metrics(context: ToolContext, pid: int, sample_seconds: float) -> str:
    pid = _bounded_int(pid, "pid", 0, 4_194_304)
    try:
        interval = float(sample_seconds)
    except (TypeError, ValueError) as exc:
        raise ValueError("sample_seconds must be numeric") from exc
    if not 0.1 <= interval <= 5.0:
        raise ValueError("sample_seconds must be between 0.1 and 5.0")
    script = """
import json, os, pathlib, time
pid = int(os.environ['OPSBENCH_METRIC_PID'])
interval = float(os.environ['OPSBENCH_METRIC_INTERVAL'])
mem = {}
for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
    key, value = line.split(':', 1)
    mem[key] = value.strip()
result = {
    'load_average': pathlib.Path('/proc/loadavg').read_text().strip(),
    'host_memory': {key: mem.get(key, '') for key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree')},
}
cgroup_root = pathlib.Path('/sys/fs/cgroup')
cgroup_files = {
    'current_bytes': 'memory.current',
    'max_bytes': 'memory.max',
    'high_bytes': 'memory.high',
    'events': 'memory.events',
    'stat': 'memory.stat',
    'pressure': 'memory.pressure',
}
cgroup_memory = {}
for key, name in cgroup_files.items():
    path = cgroup_root / name
    if path.is_file():
        cgroup_memory[key] = path.read_text().strip()
if not cgroup_memory:
    legacy = cgroup_root / 'memory'
    legacy_files = {
        'current_bytes': 'memory.usage_in_bytes',
        'max_bytes': 'memory.limit_in_bytes',
        'stat': 'memory.stat',
    }
    for key, name in legacy_files.items():
        path = legacy / name
        if path.is_file():
            cgroup_memory[key] = path.read_text().strip()
try:
    current = int(cgroup_memory.get('current_bytes', ''))
    maximum = int(cgroup_memory.get('max_bytes', ''))
    if maximum > 0:
        cgroup_memory['usage_percent'] = round(current / maximum * 100, 1)
except ValueError:
    pass
result['cgroup_memory'] = cgroup_memory
if pid:
    proc = pathlib.Path('/proc') / str(pid)
    if not proc.exists():
        raise SystemExit(f'PID not found: {pid}')
    ticks = os.sysconf(os.sysconf_names['SC_CLK_TCK'])
    first = proc.joinpath('stat').read_text().split()
    start = int(first[13]) + int(first[14])
    time.sleep(interval)
    second = proc.joinpath('stat').read_text().split()
    end = int(second[13]) + int(second[14])
    status = {}
    for line in proc.joinpath('status').read_text().splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            status[key] = value.strip()
    result['process'] = {
        'pid': pid,
        'name': status.get('Name', ''),
        'state': status.get('State', ''),
        'rss': status.get('VmRSS', ''),
        'threads': status.get('Threads', ''),
        'open_fds': len(list(proc.joinpath('fd').iterdir())),
        'cpu_cores': round((end - start) / ticks / interval, 3),
    }
print(json.dumps(result, indent=2, sort_keys=True))
"""
    env = os.environ.copy()
    env["OPSBENCH_METRIC_PID"] = str(pid)
    env["OPSBENCH_METRIC_INTERVAL"] = str(interval)
    completed = _run_tool_command(
        context, "host-metrics", ["python3", "-c", script], env=env
    )
    return _completed_output(context, "host-metrics", completed, already_recorded=True)


def _inspect_filesystem(context: ToolContext, path: str) -> str:
    candidate = Path(path).resolve()
    if not candidate.exists():
        raise ValueError(f"path does not exist: {candidate}")
    script = (
        "df -Pk -- \"$1\"; echo; df -Pi -- \"$1\"; echo; "
        "du -x -k -d 1 -- \"$1\" 2>/dev/null | sort -n | tail -30; echo; "
        "lsof +L1 -- \"$1\" 2>/dev/null | head -50 || true"
    )
    completed = _run_tool_command(
        context, "filesystem", ["sh", "-c", script, "sh", str(candidate)]
    )
    return _completed_output(context, "filesystem", completed, already_recorded=True)


def _probe_http(
    context: ToolContext,
    url: str,
    method: str,
    body: str,
    timeout_sec: int,
    ca_file: str,
) -> str:
    if not re.match(r"^https?://", url):
        raise ValueError("url must start with http:// or https://")
    method = method.upper()
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported HTTP method")
    timeout_sec = _bounded_int(timeout_sec, "timeout_sec", 1, 30)
    command = [
        "curl", "-sS", "--max-time", str(timeout_sec), "-X", method,
        "-w", "\n__OPSBENCH_HTTP__ status=%{http_code} total_sec=%{time_total} "
        "remote_ip=%{remote_ip} tls_verify=%{ssl_verify_result}\n",
    ]
    if body:
        command.extend(["--data-binary", body])
    if ca_file:
        command.extend(["--cacert", ca_file])
    command.append(url)
    completed = _run_tool_command(context, "http", command)
    return _completed_output(context, "http", completed, already_recorded=True)


def _inspect_file(context: ToolContext, path: str, max_bytes: int) -> str:
    max_bytes = _bounded_int(max_bytes, "max_bytes", 1, 20_000)
    candidate = Path(path).resolve()
    stat = candidate.stat()
    payload: dict[str, object] = {
        "path": str(candidate),
        "mode": oct(stat.st_mode & 0o7777),
        "uid": stat.st_uid,
        "gid": stat.st_gid,
        "size": stat.st_size,
        "is_file": candidate.is_file(),
        "is_dir": candidate.is_dir(),
    }
    if candidate.is_file():
        sample = candidate.read_bytes()[:max_bytes]
        if _looks_binary(sample):
            payload["content_type"] = "binary"
            payload["preview_hex"] = sample[:64].hex()
        else:
            payload["content_type"] = "text"
            payload["content"] = sample.decode("utf-8")
        payload["truncated"] = stat.st_size > max_bytes
    return _record_text(context, "file", json.dumps(payload, indent=2))


def _edit_file(context: ToolContext, path: str, old_text: str, new_text: str) -> str:
    if not old_text:
        raise ValueError("old_text must not be empty")
    candidate = Path(path).resolve()
    if not candidate.is_file():
        raise ValueError(f"file does not exist: {candidate}")
    if candidate.stat().st_size > 1_000_000:
        raise ValueError("edit_file supports files up to 1 MB")
    content = candidate.read_text(encoding="utf-8")
    occurrences = content.count(old_text)
    if occurrences != 1:
        raise ValueError(f"old_text must occur exactly once; found {occurrences}")
    candidate.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
    payload = {
        "path": str(candidate),
        "changed": True,
        "old_length": len(old_text),
        "new_length": len(new_text),
    }
    return _record_text(context, "file-edit", json.dumps(payload, indent=2))


def _manage_service(context: ToolContext, service: str, action: str) -> str:
    services = {"demo-app": "/opt/opsbench/runtime/appctl.sh"}
    if action == "list":
        return _record_text(context, "service", json.dumps({"services": sorted(services)}, indent=2))
    if service not in services:
        raise ValueError(f"unknown service: {service}; use action=list")
    if action not in {"status", "start", "stop", "restart"}:
        raise ValueError("action must be list, status, start, stop, or restart")
    completed = _run_tool_command(context, "service", [services[service], action])
    return _completed_output(context, "service", completed, already_recorded=True)


def _inspect_database(context: ToolContext, scope: str, relation: str) -> str:
    escaped = relation.replace("'", "''")
    queries = {
        "overview": "SELECT current_database() AS database, current_user AS user, version();",
        "tables": "SELECT schemaname, relname, n_live_tup, seq_scan, idx_scan FROM pg_stat_user_tables ORDER BY n_live_tup DESC;",
        "indexes": "SELECT schemaname, tablename, indexname, indexdef FROM pg_indexes WHERE schemaname NOT IN ('pg_catalog','information_schema')" + (f" AND tablename='{escaped}'" if relation else "") + " ORDER BY tablename,indexname;",
        "activity": "SELECT pid, usename, state, wait_event_type, wait_event, now()-query_start AS age, left(query,300) AS query FROM pg_stat_activity WHERE pid <> pg_backend_pid() ORDER BY query_start;",
        "table_stats": "SELECT * FROM pg_stat_user_tables" + (f" WHERE relname='{escaped}'" if relation else "") + " ORDER BY relname;",
        "settings": "SELECT name, setting, unit, source FROM pg_settings WHERE name IN ('shared_buffers','work_mem','effective_cache_size','max_connections','log_min_duration_statement') ORDER BY name;",
    }
    if scope not in queries:
        raise ValueError(f"scope must be one of: {', '.join(queries)}")
    return _psql(context, "database-inspect", queries[scope])


def _query_database(context: ToolContext, sql: str) -> str:
    if not sql.strip():
        raise ValueError("sql must not be empty")
    return _psql(context, "database-query", sql)


def _explain_query(context: ToolContext, sql: str, analyze: bool) -> str:
    normalized = sql.lstrip().lower()
    if not (normalized.startswith("select") or normalized.startswith("with")):
        raise ValueError("explain_query accepts SELECT or WITH statements only")
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "COSTS, FORMAT JSON"
    return _psql(context, "database-explain", f"EXPLAIN ({options}) {sql}")


def _psql(context: ToolContext, prefix: str, sql: str) -> str:
    completed = _run_tool_command(
        context, prefix, ["psql", "-X", "-v", "ON_ERROR_STOP=1", "--csv", "-c", sql]
    )
    return _completed_output(context, prefix, completed, already_recorded=True)


def _run_tool_command(
    context: ToolContext,
    prefix: str,
    command: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        shell=False,
        cwd=context.execution_dir,
        env=env or os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )
    full_output = _format_command_output(
        " ".join(command), completed.returncode, completed.stdout, completed.stderr
    )
    full_output = _redact_sensitive_text(full_output)
    context.next_log_path(prefix).write_text(full_output, encoding="utf-8")
    return completed


def _completed_output(
    context: ToolContext,
    prefix: str,
    completed: subprocess.CompletedProcess[str],
    already_recorded: bool = False,
) -> str:
    full_output = _format_command_output(
        " ".join(str(item) for item in completed.args),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    full_output = _redact_sensitive_text(full_output)
    if not already_recorded:
        context.next_log_path(prefix).write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _record_text(context: ToolContext, prefix: str, output: str) -> str:
    output = _redact_sensitive_text(output)
    context.next_log_path(prefix).write_text(output, encoding="utf-8")
    return _truncate(output)


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
    full_output = _redact_sensitive_text(full_output)
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
        path="jaeger/ui/api/traces",
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
        path=f"jaeger/ui/api/traces/{quote(trace_id, safe='')}",
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
    bounded_limit = _bounded_int(limit, "limit", 1, 500)
    try:
        return _service_proxy_get(
            context,
            component="opensearch",
            port=9200,
            path="_search",
            params={"q": log_query, "size": bounded_limit},
            log_prefix="logs",
        )
    except RuntimeError as exc:
        if "no opensearch Service" not in str(exc):
            raise
        return _query_kubernetes_logs(context, query, service, bounded_limit)


def _query_kubernetes_logs(
    context: ToolContext, query: str, service: str, limit: int
) -> str:
    _require_namespace(context)
    args = ["-n", context.namespace, "get", "pods", "-o", "json"]
    if service:
        args.extend(["-l", f"app.kubernetes.io/component={service}"])
    listed = _run_kubectl(context, args)
    if listed.returncode != 0:
        return _kubectl_result(context, "logs", args)
    pods = json.loads(listed.stdout).get("items", [])
    needle = query.lower()
    matches: list[dict[str, str]] = []
    for pod in pods:
        pod_name = str(pod.get("metadata", {}).get("name", ""))
        for container in pod.get("spec", {}).get("containers", []):
            container_name = str(container.get("name", ""))
            completed = _run_kubectl(
                context,
                [
                    "-n",
                    context.namespace,
                    "logs",
                    pod_name,
                    "-c",
                    container_name,
                    "--since=1h",
                    "--tail=500",
                ],
            )
            for line in completed.stdout.splitlines():
                if needle in line.lower():
                    matches.append(
                        {"pod": pod_name, "container": container_name, "line": line}
                    )
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break
        if len(matches) >= limit:
            break
    output = json.dumps(
        {
            "backend": "kubernetes-pod-logs",
            "query": query,
            "service": service,
            "matches": matches,
        },
        indent=2,
        sort_keys=True,
    )
    full_output = _format_command_output("query Kubernetes pod logs", 0, output, "")
    full_output = _redact_sensitive_text(full_output)
    context.next_log_path("logs").write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


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
    full_output = _redact_sensitive_text(full_output)
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


def _looks_binary(content: bytes) -> bool:
    if not content:
        return False
    if b"\x00" in content:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    control_bytes = sum(
        byte < 32 and byte not in {9, 10, 13}
        for byte in content
    )
    return control_bytes / len(content) > 0.05


def _redact_sensitive_text(output: str) -> str:
    redacted = output
    sensitive_name = re.compile(r"(?:API_KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)$")
    values = {
        value
        for name, value in os.environ.items()
        if sensitive_name.search(name) and len(value) >= 12
    }
    for value in sorted(values, key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{16,}\b", "[REDACTED]", redacted)


def _truncate(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    return output[:MAX_TOOL_OUTPUT_CHARS] + "\n[truncated]\n"
