from __future__ import annotations

from typing import Callable

from opsbench.agent_tools import ToolContext, create_tools


def create_langchain_tools(context: ToolContext) -> list[object]:
    """Adapt the benchmark-owned tool contract to LangChain."""

    try:
        from langchain.tools import tool
    except ImportError as exc:
        raise RuntimeError(
            "langchain is required for langchain-react-agent; install "
            "agents/langchain-react-agent/requirements.txt"
        ) from exc

    tools = create_tools(context)

    @tool
    def shell(command: str) -> str:
        """Run an expert fallback shell command in the Agent environment."""

        return _tool_result(lambda: tools["shell"](command))

    @tool
    def read_logs(path: str = "", query: str = "", tail: int = 200) -> str:
        """List log files or read and filter a log under /var/log."""

        return _tool_result(lambda: tools["read_logs"](path, query, tail))

    @tool
    def inspect_processes(query: str = "", limit: int = 50) -> str:
        """Inspect processes with PID, owner, CPU, memory, age, and command."""

        return _tool_result(lambda: tools["inspect_processes"](query, limit))

    @tool
    def inspect_sockets(port: int = 0, listening: bool = True) -> str:
        """Inspect TCP/UDP sockets, optionally filtering one port."""

        return _tool_result(lambda: tools["inspect_sockets"](port, listening))

    @tool
    def query_host_metrics(pid: int = 0, sample_seconds: float = 1.0) -> str:
        """Read host memory/load or sample one process's CPU, RSS, threads, and FDs."""

        return _tool_result(lambda: tools["query_host_metrics"](pid, sample_seconds))

    @tool
    def inspect_filesystem(path: str = "/") -> str:
        """Inspect byte/inode usage, largest children, and deleted open files."""

        return _tool_result(lambda: tools["inspect_filesystem"](path))

    @tool
    def probe_http(
        url: str,
        method: str = "GET",
        body: str = "",
        timeout_sec: int = 5,
        ca_file: str = "",
    ) -> str:
        """Probe HTTP/HTTPS and report body, status, latency, address, and TLS result."""

        return _tool_result(
            lambda: tools["probe_http"](url, method, body, timeout_sec, ca_file)
        )

    @tool
    def inspect_file(path: str, max_bytes: int = 4000) -> str:
        """Inspect file metadata and a bounded text preview."""

        return _tool_result(lambda: tools["inspect_file"](path, max_bytes))

    @tool
    def edit_file(path: str, old_text: str, new_text: str) -> str:
        """Apply one exact text replacement to a runtime configuration file."""

        return _tool_result(lambda: tools["edit_file"](path, old_text, new_text))

    @tool
    def manage_service(service: str, action: str) -> str:
        """List or start, stop, restart, and inspect a managed service."""

        return _tool_result(lambda: tools["manage_service"](service, action))

    @tool
    def inspect_database(scope: str = "overview", relation: str = "") -> str:
        """Inspect PostgreSQL overview, tables, indexes, activity, stats, or settings."""

        return _tool_result(lambda: tools["inspect_database"](scope, relation))

    @tool
    def query_database(sql: str) -> str:
        """Execute SQL against the configured PostgreSQL database, including repairs."""

        return _tool_result(lambda: tools["query_database"](sql))

    @tool
    def explain_query(sql: str, analyze: bool = False) -> str:
        """Run PostgreSQL EXPLAIN JSON for a SELECT/WITH query, optionally ANALYZE."""

        return _tool_result(lambda: tools["explain_query"](sql, analyze))

    @tool
    def kubectl_logs(
        pod: str,
        container: str = "",
        since: str = "10m",
        tail: int = 200,
        previous: bool = False,
    ) -> str:
        """Read recent logs for a Pod in the case namespace."""

        return _tool_result(
            lambda: tools["kubectl_logs"](pod, container, since, tail, previous)
        )

    @tool
    def list_metrics(match: str = "", limit: int = 200) -> str:
        """List Prometheus metric names, optionally filtered by a substring."""

        return _tool_result(lambda: tools["list_metrics"](match, limit))

    @tool
    def query_metrics(promql: str, time: str = "") -> str:
        """Run an instant PromQL query against the Demo Prometheus backend."""

        return _tool_result(lambda: tools["query_metrics"](promql, time))

    @tool
    def search_traces(
        service: str,
        operation: str = "",
        lookback: str = "1h",
        limit: int = 20,
        tags: str = "",
    ) -> str:
        """Search Jaeger traces by service and optional operation or tags."""

        return _tool_result(
            lambda: tools["search_traces"](
                service, operation, lookback, limit, tags
            )
        )

    @tool
    def get_trace(trace_id: str) -> str:
        """Fetch one complete trace from Jaeger by hexadecimal trace ID."""

        return _tool_result(lambda: tools["get_trace"](trace_id))

    @tool
    def query_logs(query: str, service: str = "", limit: int = 100) -> str:
        """Search OpenSearch logs with a query string and optional service filter."""

        return _tool_result(lambda: tools["query_logs"](query, service, limit))

    adapters = {
        "shell": shell,
        "read_logs": read_logs,
        "inspect_processes": inspect_processes,
        "inspect_sockets": inspect_sockets,
        "query_host_metrics": query_host_metrics,
        "inspect_filesystem": inspect_filesystem,
        "probe_http": probe_http,
        "inspect_file": inspect_file,
        "edit_file": edit_file,
        "manage_service": manage_service,
        "inspect_database": inspect_database,
        "query_database": query_database,
        "explain_query": explain_query,
        "kubectl_logs": kubectl_logs,
        "list_metrics": list_metrics,
        "query_metrics": query_metrics,
        "search_traces": search_traces,
        "get_trace": get_trace,
        "query_logs": query_logs,
    }
    return [adapters[name] for name in tools]


def _tool_result(call: Callable[[], str]) -> str:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - tool misuse should be observable, not fatal.
        return f"ERROR: {type(exc).__name__}: {exc}"
