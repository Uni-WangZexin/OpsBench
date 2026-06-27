import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


class BuiltInAgentTests(unittest.TestCase):
    def test_noop_agent_writes_trace_and_exits_successfully(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            task = root / "task.md"
            task.write_text("diagnose the incident", encoding="utf-8")
            work_dir = root / "work"
            work_dir.mkdir()
            trace_dir = root / "trace"
            env = os.environ.copy()
            env["OPSBENCH_TRACE_DIR"] = str(trace_dir)
            env["OPSBENCH_VERIFY_CMD"] = "/bin/true"

            result = subprocess.run(
                [
                    "agents/noop-agent/run.sh",
                    "--case-dir",
                    "cases/postgres-missing-index-001",
                    "--task",
                    str(task),
                    "--work-dir",
                    str(work_dir),
                    "--timeout-sec",
                    "30",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            trace = (trace_dir / "trace.md").read_text(encoding="utf-8")
            self.assertIn("No repair attempted", trace)

    def test_oracle_agent_is_executable_and_react_style(self):
        root = Path(__file__).resolve().parents[1]
        oracle = root / "agents" / "oracle-agent" / "run.sh"

        content = oracle.read_text(encoding="utf-8")

        self.assertTrue(oracle.stat().st_mode & stat.S_IXUSR)
        self.assertIn("Thought:", content)
        self.assertIn("Action:", content)
        self.assertIn("hidden/oracle_fix.sql", content)


if __name__ == "__main__":
    unittest.main()
