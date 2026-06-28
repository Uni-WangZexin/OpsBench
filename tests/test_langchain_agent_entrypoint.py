import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from agents.langchain_react_agent.agent import parse_args, write_missing_key_error


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


if __name__ == "__main__":
    unittest.main()
