import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import agents.langchain_react_agent.agent as agent_module
from agents.langchain_react_agent.agent import build_agent, parse_args, write_missing_key_error
from agents.langchain_react_agent.config import AgentConfig
from agents.langchain_react_agent.tools import ToolContext


class LangChainAgentEntrypointTests(unittest.TestCase):
    def test_parse_args_accepts_opsbench_agent_protocol(self):
        args = parse_args(
            [
                "--case-dir",
                "/case",
                "--task",
                "/task.md",
                "--work-dir",
                "/work",
                "--timeout-sec",
                "300",
            ]
        )

        self.assertEqual(args.case_dir, "/case")
        self.assertEqual(args.task, "/task.md")
        self.assertEqual(args.work_dir, "/work")
        self.assertEqual(args.timeout_sec, 300)

    def test_missing_key_error_writes_trace_and_final_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir) / "trace"
            trace_dir.mkdir()

            write_missing_key_error(trace_dir, RuntimeError("DEEPSEEK_API_KEY is required"))

            self.assertIn("DEEPSEEK_API_KEY", (trace_dir / "trace.md").read_text(encoding="utf-8"))
            final = json.loads((trace_dir / "final.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "configuration_error")

    def test_run_sh_invokes_python_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_python = root / "python3"
            capture = root / "capture.txt"
            fake_python.write_text(
                "#!/usr/bin/env bash\n" f"printf '%s\\n' \"$@\" > {capture}\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{root}:{env['PATH']}"
            env["OPSBENCH_TRACE_DIR"] = str(root / "trace")

            result = subprocess.run(
                [
                    "agents/langchain-react-agent/run.sh",
                    "--case-dir",
                    "/case",
                    "--task",
                    "/task.md",
                    "--work-dir",
                    "/work",
                    "--timeout-sec",
                    "300",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            captured = capture.read_text(encoding="utf-8")
            self.assertIn("-m", captured)
            self.assertIn("agents.langchain_react_agent.agent", captured)
            self.assertIn("--case-dir", captured)

    def test_build_agent_prefers_langchain_create_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            calls = {}

            agents_module = types.ModuleType("langchain.agents")

            def create_agent(model, tools, system_prompt):
                calls["model"] = model
                calls["tools"] = tools
                calls["prompt"] = system_prompt
                return "langchain-agent"

            agents_module.create_agent = create_agent
            openai_module = types.ModuleType("langchain_openai")

            class ChatOpenAI:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

            openai_module.ChatOpenAI = ChatOpenAI
            langchain_module = types.ModuleType("langchain")
            tools_module = types.ModuleType("langchain.tools")
            tools_module.tool = lambda fn: fn
            langchain_module.agents = agents_module
            langgraph_module = types.ModuleType("langgraph")
            prebuilt_module = types.ModuleType("langgraph.prebuilt")

            def deprecated_create_react_agent(**kwargs):
                raise AssertionError("deprecated langgraph create_react_agent should not be used")

            prebuilt_module.create_react_agent = deprecated_create_react_agent

            with patch.dict(
                sys.modules,
                {
                    "langchain_openai": openai_module,
                    "langchain": langchain_module,
                    "langchain.agents": agents_module,
                    "langchain.tools": tools_module,
                    "langgraph": langgraph_module,
                    "langgraph.prebuilt": prebuilt_module,
                },
            ):
                result = build_agent(
                    AgentConfig(
                        api_key="secret",
                        base_url="https://api.deepseek.com",
                        model="deepseek-v4-pro",
                        max_steps=12,
                        temperature=0.0,
                    ),
                    ToolContext(
                        execution_dir=case_dir,
                        trace_dir=trace_dir,
                    ),
                )

            self.assertEqual(result, "langchain-agent")
            self.assertIn("OpsBench", calls["prompt"])
            self.assertEqual(calls["model"].kwargs["model"], "deepseek-v4-pro")

    def test_write_react_trace_records_actions_and_observations(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir) / "trace"
            trace_dir.mkdir()
            response = {
                "messages": [
                    {"role": "human", "content": "Fix the slow query."},
                    _FakeMessage(
                        "ai",
                        "Thought: inspect indexes.",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "name": "shell",
                                "args": {"command": "psql -c 'select 1'"},
                            }
                        ],
                    ),
                    _FakeMessage(
                        "tool",
                        "returncode=0\nidx_orders_customer_id missing",
                        name="shell",
                        tool_call_id="call_1",
                    ),
                    _FakeMessage("ai", "Final: created the missing index."),
                ]
            }

            self.assertTrue(hasattr(agent_module, "_write_react_trace"))

            agent_module._write_react_trace(trace_dir, response)

            markdown = (trace_dir / "react-trace.md").read_text(encoding="utf-8")
            self.assertIn("## 2. Assistant", markdown)
            self.assertIn("Thought: inspect indexes.", markdown)
            self.assertIn("### Action 1", markdown)
            self.assertIn("shell", markdown)
            self.assertIn("psql -c 'select 1'", markdown)
            self.assertIn("## 3. Observation", markdown)
            self.assertIn("idx_orders_customer_id missing", markdown)

            payload = json.loads((trace_dir / "react-trace.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["messages"][1]["actions"][0]["name"], "shell")
            self.assertEqual(payload["messages"][2]["tool_call_id"], "call_1")


class _FakeMessage:
    def __init__(
        self,
        message_type,
        content,
        tool_calls=None,
        name=None,
        tool_call_id=None,
    ):
        self.type = message_type
        self.content = content
        self.tool_calls = tool_calls or []
        self.name = name
        self.tool_call_id = tool_call_id


if __name__ == "__main__":
    unittest.main()
