import json
import os
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
    LINUX_OPERATIONS_TOOL_NAMES,
    POSTGRES_OPERATIONS_TOOL_NAMES,
    STANDARD_TOOL_NAMES,
    create_tools,
    tool_names_for_standard,
)


class AgentToolContractTests(unittest.TestCase):
    def test_linux_container_standard_exposes_only_shell(self):
        self.assertEqual(tool_names_for_standard("linux-container-v1"), ("shell",))

    def test_linux_operations_standard_exposes_real_operations_surface(self):
        self.assertEqual(
            tool_names_for_standard("linux-operations-v2"),
            LINUX_OPERATIONS_TOOL_NAMES,
        )

    def test_postgres_operations_standard_exposes_database_surface(self):
        self.assertEqual(
            tool_names_for_standard("postgres-operations-v2"),
            POSTGRES_OPERATIONS_TOOL_NAMES,
        )

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

    def test_file_inspection_and_exact_edit_are_audited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "app.conf"
            config.write_text("port=8081\n", encoding="utf-8")
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="linux-operations-v2",
            )
            tools = create_tools(context)

            before = tools["inspect_file"](str(config), 100)
            changed = tools["edit_file"](str(config), "8081", "8080")

            self.assertIn("port=8081", before)
            self.assertIn('"changed": true', changed)
            self.assertEqual(config.read_text(encoding="utf-8"), "port=8080\n")
            self.assertTrue(list((root / "trace").glob("tool-file-*.log")))
            self.assertTrue(list((root / "trace").glob("tool-file-edit-*.log")))

    def test_host_metrics_distinguishes_host_and_cgroup_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="linux-operations-v2",
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "host_memory": {"MemTotal": "8 GB"},
                            "cgroup_memory": {
                                "current_bytes": "1048576",
                                "max_bytes": "402653184",
                                "usage_percent": 0.3,
                            },
                        }
                    ),
                    "",
                )

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["query_host_metrics"](0, 0.1)

            self.assertIn('"host_memory"', output)
            self.assertIn('"cgroup_memory"', output)
            self.assertNotIn('\n  "memory":', output)
            self.assertIn("memory.current", calls[0][0][2])
            self.assertIn("memory.max", calls[0][0][2])

    def test_file_inspection_reports_binary_without_dumping_gibberish(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "service.pyc"
            binary.write_bytes(b"\xa7\r\r\n\x00\x00compiled\xffpayload")
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="linux-operations-v2",
            )

            output = create_tools(context)["inspect_file"](str(binary), 4000)

            self.assertIn('"content_type": "binary"', output)
            self.assertIn('"preview_hex"', output)
            self.assertNotIn('"content"', output)

    def test_tool_output_redacts_model_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(execution_dir=root, trace_dir=root / "trace")
            credential = "sk-examplecredential123456789"

            with patch.dict(os.environ, {"OPENAI_API_KEY": credential}):
                with patch(
                    "opsbench.agent_tools.subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        "env", 0, f"OPENAI_API_KEY={credential}\n", ""
                    ),
                ):
                    output = create_tools(context)["shell"]("env")

            self.assertNotIn(credential, output)
            self.assertIn("[REDACTED]", output)
            log = next((root / "trace").glob("tool-shell-*.log"))
            self.assertNotIn(credential, log.read_text(encoding="utf-8"))

    def test_database_query_uses_psql_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="postgres-operations-v2",
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "answer\n1\n", "")

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["query_database"]("SELECT 1")

            self.assertIn("answer", output)
            self.assertEqual(calls[0][0][-2:], ["-c", "SELECT 1"])
            self.assertFalse(calls[0][1]["shell"])
            self.assertTrue(list((root / "trace").glob("tool-database-query-*.log")))

    def test_http_probe_uses_argument_vector_and_records_latency_format(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="linux-operations-v2",
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(
                    command, 0, "ok\n__OPSBENCH_HTTP__ status=200 total_sec=0.01\n", ""
                )

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["probe_http"](
                    "http://127.0.0.1:8080/health", "GET", "", 5, ""
                )

            self.assertIn("status=200", output)
            self.assertEqual(calls[0][0][0], "curl")
            self.assertFalse(calls[0][1]["shell"])
            self.assertTrue(list((root / "trace").glob("tool-http-*.log")))

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

    def test_query_logs_falls_back_to_kubernetes_pod_logs_without_opensearch(self):
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
            pods = json.dumps(
                {
                    "items": [
                        {
                            "metadata": {"name": "frontend-1"},
                            "spec": {"containers": [{"name": "frontend"}]},
                        }
                    ]
                }
            )
            responses = iter([services, pods, "ready\nconnection refused\n"])

            def fake_run(command, **kwargs):
                return subprocess.CompletedProcess(command, 0, next(responses), "")

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["query_logs"](
                    "connection refused", "frontend", 10
                )

            self.assertIn('"backend": "kubernetes-pod-logs"', output)
            self.assertIn("connection refused", output)
            self.assertIn("frontend-1", output)

    def test_trace_tool_uses_jaeger_service_proxy_base_path(self):
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
                            "metadata": {"name": "demo-jaeger"},
                            "spec": {"ports": [{"port": 16686}]},
                        }
                    ]
                }
            )
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                output = services if len(calls) == 1 else '{"data":[]}'
                return subprocess.CompletedProcess(command, 0, output, "")

            with patch("opsbench.agent_tools.subprocess.run", side_effect=fake_run):
                output = create_tools(context)["search_traces"](
                    "frontend", "", "1h", 10, ""
                )

            self.assertIn('"data": []', output)
            self.assertIn("/proxy/jaeger/ui/api/traces?", calls[1][-1])

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

    def test_langchain_adapter_exposes_linux_operations_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="linux-operations-v2",
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
                tuple(tool.__name__ for tool in tools), LINUX_OPERATIONS_TOOL_NAMES
            )

    def test_langchain_adapter_exposes_postgres_operations_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = ToolContext(
                execution_dir=root,
                trace_dir=root / "trace",
                tool_standard="postgres-operations-v2",
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
                tuple(tool.__name__ for tool in tools), POSTGRES_OPERATIONS_TOOL_NAMES
            )


if __name__ == "__main__":
    unittest.main()
