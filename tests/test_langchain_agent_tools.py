import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.langchain_react_agent.tools import ToolContext, create_langchain_tools
from opsbench.agent_tools import (
    KUBERNETES_OBSERVABILITY_TOOL_NAMES,
    STANDARD_TOOL_NAMES,
    create_tools,
)


class AgentToolContractTests(unittest.TestCase):
    def test_standard_contract_exposes_only_container_shell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(execution_dir=root, trace_dir=root / "trace")

            tools = create_tools(context)

            self.assertEqual(tuple(tools), STANDARD_TOOL_NAMES)
            self.assertEqual(STANDARD_TOOL_NAMES, ("shell",))

    def test_shell_runs_in_the_agent_execution_environment_and_logs_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                command_timeout_sec=5,
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "inside container\n", "")

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["shell"]("psql -h db -c 'SELECT 1'")

            self.assertIn("inside container", output)
            command, kwargs = calls[0]
            self.assertEqual(command, "psql -h db -c 'SELECT 1'")
            self.assertEqual(kwargs["cwd"], root.resolve())
            self.assertTrue(kwargs["shell"])
            self.assertTrue(list((root / "trace").glob("tool-shell-*.log")))

    def test_kubernetes_standard_exposes_uniform_observability_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="kubernetes-observability-v1",
                namespace="ops-case",
            )

            self.assertEqual(
                tuple(create_tools(context)), KUBERNETES_OBSERVABILITY_TOOL_NAMES
            )

    def test_metrics_tool_discovers_prometheus_and_uses_service_proxy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="kubernetes-observability-v1",
                namespace="ops-case",
            )
            services = json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "demo-prometheus-server"},
                            "spec": {"ports": [{"port": 9090}]},
                        }
                    ]
                }
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                if len(calls) == 1:
                    return subprocess.CompletedProcess(command, 0, services, "")
                return subprocess.CompletedProcess(
                    command, 0, '{"status":"success","data":{"result":[]}}', ""
                )

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["query_metrics"]("up == 0")

            self.assertIn('"status": "success"', output)
            self.assertEqual(calls[0][0][:5], ["kubectl", "-n", "ops-case", "get", "services"])
            proxy_path = calls[1][0][-1]
            self.assertIn(
                "/services/http:demo-prometheus-server:9090/proxy/api/v1/query",
                proxy_path,
            )
            self.assertIn("query=up+%3D%3D+0", proxy_path)
            self.assertFalse(calls[1][1]["shell"])

    def test_list_metrics_filters_and_limits_prometheus_metric_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="kubernetes-observability-v1",
                namespace="ops-case",
            )
            services = json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "demo-prometheus-server"},
                            "spec": {"ports": [{"port": 9090}]},
                        }
                    ]
                }
            )
            metric_names = json.dumps(
                {
                    "status": "success",
                    "data": ["http_requests_total", "process_cpu_seconds_total", "up"],
                }
            )
            responses = iter([services, metric_names])

            def fake_run(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, next(responses), "")

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["list_metrics"]("total", 1)

            self.assertIn('"returned": 1', output)
            self.assertIn("http_requests_total", output)
            self.assertNotIn("process_cpu_seconds_total", output)

    def test_langchain_adapter_preserves_the_standard_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(execution_dir=root, trace_dir=root / "trace")
            langchain_module = types.ModuleType("langchain")
            tools_module = types.ModuleType("langchain.tools")
            tools_module.tool = lambda fn: fn

            with patch.dict(
                sys.modules,
                {"langchain": langchain_module, "langchain.tools": tools_module},
            ):
                tools = create_langchain_tools(context)

            self.assertEqual(tuple(tool.__name__ for tool in tools), STANDARD_TOOL_NAMES)

    def test_langchain_adapter_exposes_kubernetes_observability_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="kubernetes-observability-v1",
                namespace="ops-case",
            )
            langchain_module = types.ModuleType("langchain")
            tools_module = types.ModuleType("langchain.tools")
            tools_module.tool = lambda fn: fn

            with patch.dict(
                sys.modules,
                {"langchain": langchain_module, "langchain.tools": tools_module},
            ):
                tools = create_langchain_tools(context)

            self.assertEqual(
                tuple(tool.__name__ for tool in tools),
                KUBERNETES_OBSERVABILITY_TOOL_NAMES,
            )


if __name__ == "__main__":
    unittest.main()
