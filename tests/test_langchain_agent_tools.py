import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.langchain_react_agent.tools import ToolContext, create_langchain_tools, create_tools


class LangChainAgentToolTests(unittest.TestCase):
    def test_read_and_write_file_are_root_guarded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            hidden_dir = case_dir / "hidden"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            hidden_dir.mkdir()
            (case_dir / "task.md").write_text("hello", encoding="utf-8")
            (hidden_dir / "oracle_fix.sql").write_text("secret", encoding="utf-8")
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            self.assertEqual(tools["read_file"]("task.md"), "hello")
            self.assertIn("wrote", tools["write_file"]("note.txt", "fixed"))
            self.assertEqual((work_dir / "note.txt").read_text(encoding="utf-8"), "fixed")
            with self.assertRaises(ValueError):
                tools["read_file"]("../outside.txt")
            with self.assertRaises(ValueError):
                tools["read_file"]("hidden/oracle_fix.sql")
            with self.assertRaises(ValueError):
                tools["write_file"](str(case_dir / "patch.sql"), "CREATE INDEX bad;")

    def test_shell_captures_output_and_writes_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            output = tools["shell"]("printf hi")

            self.assertIn("returncode=0", output)
            self.assertIn("hi", output)
            self.assertTrue(list(trace_dir.glob("tool-shell-*.log")))

    def test_shell_runs_locally_inside_agent_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            (case_dir / "docker-compose.yaml").write_text("services: {db: {}}\n", encoding="utf-8")
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "inside container\n", "")

            env = {
                "OPSBENCH_AGENT_CONTAINER": "1",
                "OPSBENCH_COMPOSE_PROJECT": "opsbench_test",
                "OPSBENCH_SHELL_SERVICE": "db",
            }
            with patch.dict(os.environ, env, clear=False), patch(
                "agents.langchain_react_agent.tools.subprocess.run",
                side_effect=fake_run,
            ):
                output = tools["shell"]("pwd")

            self.assertIn("inside container", output)
            command, kwargs = calls[0]
            self.assertEqual(
                command,
                "pwd",
            )
            self.assertTrue(kwargs.get("shell", False))
            self.assertEqual(kwargs["cwd"], case_dir.resolve())

    def test_psql_query_uses_read_only_transaction_against_service_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "1\n", "")

            with patch("agents.langchain_react_agent.tools.subprocess.run", side_effect=fake_run):
                output = tools["psql_query"]("SELECT 1;")

            self.assertIn("returncode=0", output)
            command, kwargs = calls[0]
            self.assertEqual(command[:7], ["psql", "-h", "db", "-U", "opsbench", "-d", "opsbench"])
            self.assertIn("BEGIN READ ONLY;", kwargs["input"])
            self.assertIn("SELECT 1;", kwargs["input"])
            self.assertIn("ROLLBACK;", kwargs["input"])
            self.assertEqual(kwargs["env"]["PGPASSWORD"], "opsbench")
            self.assertFalse(kwargs.get("shell", False))

    def test_psql_execute_runs_repair_sql_against_service_host(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                return subprocess.CompletedProcess(command, 0, "CREATE INDEX\n", "")

            sql = "CREATE INDEX idx_orders_customer_id ON orders(customer_id);"
            with patch("agents.langchain_react_agent.tools.subprocess.run", side_effect=fake_run):
                output = tools["psql_execute"](sql)

            self.assertIn("CREATE INDEX", output)
            command, kwargs = calls[0]
            self.assertEqual(command[:7], ["psql", "-h", "db", "-U", "opsbench", "-d", "opsbench"])
            self.assertEqual(kwargs["input"], sql)
            self.assertEqual(kwargs["env"]["PGPASSWORD"], "opsbench")
            self.assertFalse(kwargs.get("shell", False))

    def test_langchain_tool_returns_error_string_for_tool_misuse(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            langchain_module = types.ModuleType("langchain")
            tools_module = types.ModuleType("langchain.tools")
            tools_module.tool = lambda fn: fn

            with patch.dict(
                sys.modules,
                {"langchain": langchain_module, "langchain.tools": tools_module},
            ):
                tools = create_langchain_tools(context)

            read_file = next(tool for tool in tools if tool.__name__ == "read_file")

            output = read_file(str(case_dir))

            self.assertIn("ERROR:", output)
            self.assertIn("Is a directory", output)

    def test_run_verifier_uses_verify_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            verify = work_dir / "verify.sh"
            verify.write_text("#!/usr/bin/env bash\necho verified\n", encoding="utf-8")
            verify.chmod(0o755)
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd=str(verify),
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            output = tools["run_verifier"]()

            self.assertIn("verified", output)
            self.assertTrue(context.verifier_called)


if __name__ == "__main__":
    unittest.main()
