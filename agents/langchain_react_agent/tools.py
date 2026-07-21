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
        """Run a shell command inside the agent container."""

        return _tool_result(lambda: tools["shell"](command))

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
