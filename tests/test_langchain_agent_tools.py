import tempfile
import unittest
from pathlib import Path

from agents.langchain_react_agent.tools import ToolContext, create_tools


class LangChainAgentToolTests(unittest.TestCase):
    def test_read_and_write_file_are_root_guarded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            (case_dir / "task.md").write_text("hello", encoding="utf-8")
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
