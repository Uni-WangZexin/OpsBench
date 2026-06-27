import contextlib
import io
import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path

from opsbench.cli import main
from opsbench.runner import OpsBenchRunner


class RunnerTests(unittest.TestCase):
    def test_runner_executes_lifecycle_and_records_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root)
            agent_path = self._write_fake_agent(root)
            results_dir = root / "results"

            runner = OpsBenchRunner(use_docker=False)
            record = runner.run(
                case_dir=case_dir,
                agent_path=agent_path,
                results_dir=results_dir,
                timeout_sec=20,
            )

            self.assertTrue(record["injection_passed"])
            self.assertTrue(record["verification_passed"])
            self.assertEqual(record["score"], 1.0)
            self.assertEqual(record["case_id"], "fake-case")
            self.assertEqual(record["agent"], "fake-agent")
            self.assertEqual(
                record["hidden_labels"],
                {
                    "domain": "database",
                    "system": "postgresql",
                    "fault_type": "performance.missing_index",
                },
            )
            trace_dir = root / record["trace_dir"]
            self.assertTrue((trace_dir / "agent-trace.md").exists())
            self.assertTrue((trace_dir / "agent-verify.json").exists())
            self.assertTrue((results_dir / "runs.jsonl").exists())

            recorded_lines = (results_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(recorded_lines), 1)
            self.assertEqual(json.loads(recorded_lines[0])["run_id"], record["run_id"])

    def test_validate_cli_prints_case_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = self._write_fake_case(Path(temp_dir))
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                exit_code = main(["validate", "--case", str(case_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn("fake-case", stdout.getvalue())

    def test_runner_records_failed_verification_without_raising(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root, verify_passed=False)
            agent_path = self._write_fake_agent(root)
            results_dir = root / "results"

            runner = OpsBenchRunner(use_docker=False)
            record = runner.run(
                case_dir=case_dir,
                agent_path=agent_path,
                results_dir=results_dir,
                timeout_sec=20,
            )

            self.assertTrue(record["injection_passed"])
            self.assertFalse(record["verification_passed"])
            self.assertEqual(record["score"], 0.0)
            recorded = json.loads((results_dir / "runs.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(recorded["run_id"], record["run_id"])

    def _write_fake_case(self, root: Path, verify_passed: bool = True) -> Path:
        case_dir = root / "cases" / "fake-case"
        scripts_dir = case_dir / "scripts"
        hidden_dir = case_dir / "hidden"
        scripts_dir.mkdir(parents=True)
        hidden_dir.mkdir()
        (case_dir / "manifest.yaml").write_text(
            json.dumps(
                {
                    "id": "fake-case",
                    "domain": "database",
                    "environment": {
                        "compose_file": "docker-compose.yaml",
                        "services": ["db"],
                    },
                    "scripts": {
                        "inject": "scripts/inject.py",
                        "check_injected": "scripts/check_injected.py",
                        "verify": "scripts/verify.py",
                    },
                    "task": "task.md",
                    "hidden_metadata": "hidden/labels.yaml",
                    "timeouts": {"agent_sec": 20},
                }
            ),
            encoding="utf-8",
        )
        (case_dir / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
        (case_dir / "task.md").write_text(
            "The order history workload is too slow. Fix it.",
            encoding="utf-8",
        )
        (hidden_dir / "labels.yaml").write_text(
            json.dumps(
                {
                    "domain": "database",
                    "system": "postgresql",
                    "fault_type": "performance.missing_index",
                }
            ),
            encoding="utf-8",
        )
        (scripts_dir / "inject.py").write_text(
            textwrap.dedent(
                """
                import argparse
                import json
                from pathlib import Path

                parser = argparse.ArgumentParser()
                parser.add_argument("--case-dir", required=True)
                args = parser.parse_args()
                Path(args.case_dir, ".injected").write_text("yes", encoding="utf-8")
                print(json.dumps({"passed": True, "phase": "inject"}))
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        (scripts_dir / "check_injected.py").write_text(
            textwrap.dedent(
                """
                import argparse
                import json
                import sys
                from pathlib import Path

                parser = argparse.ArgumentParser()
                parser.add_argument("--case-dir", required=True)
                args = parser.parse_args()
                passed = Path(args.case_dir, ".injected").exists()
                print(json.dumps({"passed": passed, "phase": "check_injected"}))
                sys.exit(0 if passed else 1)
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        verify_exit = 0 if verify_passed else 1
        (scripts_dir / "verify.py").write_text(
            textwrap.dedent(
                f"""
                import argparse
                import json
                import sys

                parser = argparse.ArgumentParser()
                parser.add_argument("--case-dir", required=True)
                parser.parse_args()
                print(json.dumps({{
                    "passed": {str(verify_passed)},
                    "checks": [{{"name": "fake_verify", "passed": {str(verify_passed)}}}]
                }}))
                sys.exit({verify_exit})
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return case_dir

    def _write_fake_agent(self, root: Path) -> Path:
        agent_dir = root / "agents" / "fake-agent"
        agent_dir.mkdir(parents=True)
        run_sh = agent_dir / "run.sh"
        run_sh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env bash
                set -euo pipefail

                task_file=""
                while [[ $# -gt 0 ]]; do
                  case "$1" in
                    --task)
                      task_file="$2"
                      shift 2
                      ;;
                    *)
                      shift
                      ;;
                  esac
                done

                mkdir -p "$OPSBENCH_TRACE_DIR"
                test -f "$task_file"
                echo "fake agent read task" > "$OPSBENCH_TRACE_DIR/agent-trace.md"
                "$OPSBENCH_VERIFY_CMD" > "$OPSBENCH_TRACE_DIR/agent-verify.json"
                """
            ),
            encoding="utf-8",
        )
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR)
        return run_sh


if __name__ == "__main__":
    unittest.main()
