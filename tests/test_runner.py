import contextlib
import io
import json
import os
import stat
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

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
            self.assertEqual(
                record["effective_agent_config"]["LANGCHAIN_MAX_STEPS"], "60"
            )
            self.assertNotIn("OPENAI_API_KEY", record["effective_agent_config"])
            self.assertEqual(record["case_id"], "fake-case")
            self.assertEqual(record["agent"], "fake-agent")
            self.assertEqual(
                record["model"], record["effective_agent_config"]["OPENAI_MODEL"]
            )
            self.assertEqual(
                record["hidden_labels"],
                {
                    "domain": "database",
                    "system": "postgresql",
                    "fault_type": "performance.missing_index",
                },
            )
            trace_dir = root / record["trace_dir"]
            self.assertTrue((trace_dir / "agent" / "agent-trace.md").exists())
            trace = (trace_dir / "agent" / "agent-trace.md").read_text(encoding="utf-8")
            self.assertIn("Shell service: db", trace)
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

    def test_runner_pins_explicit_step_budget_instead_of_ambient_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root)
            agent_path = self._write_fake_agent(root)

            with patch.dict(os.environ, {"LANGCHAIN_MAX_STEPS": "999"}):
                record = OpsBenchRunner(use_docker=False).run(
                    case_dir=case_dir,
                    agent_path=agent_path,
                    results_dir=root / "results",
                    timeout_sec=20,
                    max_steps=30,
                )

            self.assertEqual(
                record["effective_agent_config"]["LANGCHAIN_MAX_STEPS"], "30"
            )

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

    def test_agent_failure_still_scores_when_environment_is_repaired(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root, verify_passed=True)
            agent_path = self._write_fake_agent(root, exit_code=1)

            record = OpsBenchRunner(use_docker=False).run(
                case_dir=case_dir,
                agent_path=agent_path,
                results_dir=root / "results",
                timeout_sec=20,
            )

            self.assertEqual(record["phases"]["agent"]["returncode"], 1)
            self.assertFalse(record["agent_completed"])
            self.assertTrue(record["verification"]["passed"])
            self.assertTrue(record["verification_passed"])
            self.assertEqual(record["score"], 1.0)

    def test_docker_runner_executes_agent_inside_agent_runner_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root)
            agent_path = self._write_fake_agent(root)
            results_dir = root / "results"
            runner = _RecordingDockerRunner()

            record = runner.run(
                case_dir=case_dir,
                agent_path=agent_path,
                results_dir=results_dir,
                timeout_sec=20,
            )

            self.assertTrue(record["verification_passed"])
            agent_command = runner.commands["agent"]
            trace_dir = root / record["trace_dir"]
            agent_trace_dir = trace_dir / "agent"
            workspace_dir = Path("runtime") / record["run_id"] / "workspace"
            workspace_dir = workspace_dir.resolve()
            self.assertEqual(agent_command[0:5], ["docker", "compose", "-p", runner.compose_project, "-f"])
            self.assertEqual(agent_command[5], str(case_dir.resolve() / "docker-compose.yaml"))
            self.assertIn("run", agent_command)
            self.assertIn("--rm", agent_command)
            self.assertIn("--build", agent_command)
            self.assertIn("-T", agent_command)
            self.assertIn("agent-runner", agent_command)
            self.assertIn(f"{agent_path.parent.resolve()}:/agent:ro", agent_command)
            self.assertIn(f"{workspace_dir / 'task.md'}:/task/task.md:ro", agent_command)
            self.assertIn(f"{agent_trace_dir.resolve()}:/trace", agent_command)
            self.assertNotIn(f"{trace_dir.resolve()}:/trace", agent_command)
            self.assertIn("OPSBENCH_AGENT_CONTAINER=1", agent_command)
            self.assertIn("OPSBENCH_TRACE_DIR=/trace", agent_command)
            self.assertFalse(any("OPSBENCH_CASE_ID" in part for part in agent_command))
            self.assertFalse(any("OPSBENCH_RUN_ID" in part for part in agent_command))
            self.assertIn("OPENAI_API_KEY", agent_command)
            self.assertFalse(
                any(part.startswith("OPENAI_API_KEY=") for part in agent_command)
            )
            self.assertFalse(any("OPSBENCH_VERIFY_CMD" in part for part in agent_command))

            service_index = agent_command.index("agent-runner")
            self.assertEqual(
                agent_command[service_index + 1 : service_index + 10],
                [
                    "/agent/run.sh",
                    "--case-dir",
                    "/case",
                    "--task",
                    "/task/task.md",
                    "--work-dir",
                    "/tmp/agent-work",
                    "--timeout-sec",
                    "20",
                ],
            )

    def test_docker_runner_executes_agent_inside_target_service(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = self._write_fake_case(root, agent_service="target")
            agent_path = self._write_fake_agent(root)
            runner = _RecordingDockerRunner()

            runner.run(
                case_dir=case_dir,
                agent_path=agent_path,
                results_dir=root / "results",
                timeout_sec=20,
            )

            command = runner.commands["agent"]
            self.assertIn("exec", command)
            self.assertNotIn("run", command)
            self.assertNotIn("agent-runner", command)
            self.assertNotIn("sshpass", command)
            service_index = command.index("target")
            self.assertEqual(command[service_index + 1], "/agent/run.sh")
            self.assertIn("OPSBENCH_AGENT_CONTAINER=1", command)
            self.assertIn("OPSBENCH_TRACE_DIR=/trace", command)
            self.assertFalse(any("OPSBENCH_CASE_ID" in part for part in command))
            self.assertFalse(any("OPSBENCH_RUN_ID" in part for part in command))
            self.assertIn("OPENAI_API_KEY", command)
            self.assertFalse(any(part.startswith("OPENAI_API_KEY=") for part in command))

    def _write_fake_case(
        self,
        root: Path,
        verify_passed: bool = True,
        agent_service: str = "",
    ) -> Path:
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
                        "agent_service": agent_service,
                    },
                    "scripts": {
                        "inject": "scripts/inject.py",
                        "check_injected": "scripts/check_injected.py",
                        "verify": "scripts/verify.py",
                    },
                    "task": "task.md",
                    "hidden_metadata": "hidden/labels.yaml",
                    "tool_standard": {
                        "id": "postgres-ops-v1",
                        "tools": ["shell"],
                        "commands": ["psql"],
                    },
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

    def _write_fake_agent(self, root: Path, exit_code: int = 0) -> Path:
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
                test -z "${OPSBENCH_CASE_ID:-}"
                test -z "${OPSBENCH_RUN_ID:-}"
                {
                  echo "fake agent read task"
                  echo "Shell service: ${OPSBENCH_SHELL_SERVICE:-}"
                } > "$OPSBENCH_TRACE_DIR/agent-trace.md"
                exit EXIT_CODE
                """
            ).replace("EXIT_CODE", str(exit_code)),
            encoding="utf-8",
        )
        run_sh.chmod(run_sh.stat().st_mode | stat.S_IXUSR)
        return run_sh


class _RecordingDockerRunner(OpsBenchRunner):
    def __init__(self):
        super().__init__(use_docker=True)
        self.commands = {}
        self.compose_project = ""

    def _run_command(
        self,
        phase,
        command,
        trace_dir,
        env,
        timeout,
        check=True,
    ):
        self.commands[phase] = command
        self.compose_project = env["OPSBENCH_COMPOSE_PROJECT"]
        stdout = ""
        if phase == "verify":
            stdout = json.dumps({"passed": True, "checks": []})
        result = {
            "phase": phase,
            "command": command,
            "returncode": 0,
            "stdout": stdout,
            "stderr": "",
            "duration_sec": 0.001,
        }
        self._write_phase_log(trace_dir, phase, result)
        return result


if __name__ == "__main__":
    unittest.main()
