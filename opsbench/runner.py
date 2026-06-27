from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opsbench.cases import Case, load_case, load_hidden_labels
from opsbench.results import append_run


class OpsBenchRunError(RuntimeError):
    """Raised when the runner cannot complete an infrastructure phase."""


class OpsBenchRunner:
    def __init__(self, use_docker: bool = True, python_executable: str | None = None):
        self.use_docker = use_docker
        self.python_executable = python_executable or sys.executable

    def run(
        self,
        case_dir: str | Path,
        agent_path: str | Path,
        results_dir: str | Path = "results",
        timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        case = load_case(case_dir)
        agent = Path(agent_path).resolve()
        results_root = Path(results_dir).resolve()
        results_root.mkdir(parents=True, exist_ok=True)

        agent_name = _agent_name(agent)
        started_at = datetime.now(UTC)
        run_id = _make_run_id(started_at, case.id, agent_name)
        trace_dir = results_root / "traces" / run_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir = Path("runtime") / run_id / "workspace"
        workspace_dir = workspace_dir.resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        compose_project = _compose_project_name(run_id)
        verify_cmd = self._write_verify_wrapper(case, workspace_dir)
        task_file = self._write_task_context(case, workspace_dir, verify_cmd)
        env = self._phase_env(case, run_id, compose_project, trace_dir, verify_cmd)
        effective_timeout = timeout_sec or case.agent_timeout_sec

        phases: dict[str, dict[str, Any]] = {}
        verification_result: dict[str, Any] = {"passed": False, "checks": []}
        started_monotonic = time.monotonic()

        try:
            if self.use_docker:
                phases["start"] = self._run_command(
                    "start",
                    _compose_cmd(case, compose_project, ["up", "-d", "--build", "--wait"]),
                    trace_dir,
                    env,
                    timeout=300,
                )

            phases["inject"] = self._run_script("inject", case, trace_dir, env)
            phases["check_injected"] = self._run_script(
                "check_injected", case, trace_dir, env
            )

            phases["agent"] = self._run_command(
                "agent",
                [
                    str(agent),
                    "--case-dir",
                    str(case.case_dir),
                    "--task",
                    str(task_file),
                    "--work-dir",
                    str(workspace_dir),
                    "--timeout-sec",
                    str(effective_timeout),
                ],
                trace_dir,
                env,
                timeout=effective_timeout,
                check=False,
            )

            phases["verify"] = self._run_script("verify", case, trace_dir, env, check=False)
            verification_result = _parse_last_json_object(phases["verify"]["stdout"])
        finally:
            if self.use_docker:
                phases["cleanup"] = self._run_command(
                    "cleanup",
                    _compose_cmd(case, compose_project, ["down", "-v"]),
                    trace_dir,
                    env,
                    timeout=120,
                    check=False,
                )

        duration_sec = round(time.monotonic() - started_monotonic, 3)
        injection_passed = (
            phases.get("inject", {}).get("returncode") == 0
            and phases.get("check_injected", {}).get("returncode") == 0
        )
        verification_passed = (
            phases.get("verify", {}).get("returncode") == 0
            and verification_result.get("passed") is True
        )
        record = {
            "run_id": run_id,
            "case_id": case.id,
            "agent": agent_name,
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "duration_sec": duration_sec,
            "injection_passed": injection_passed,
            "verification_passed": verification_passed,
            "score": 1.0 if verification_passed else 0.0,
            "hidden_labels": load_hidden_labels(case),
            "trace_dir": _relative_trace_path(trace_dir, results_root),
            "verification": verification_result,
            "phases": {
                name: {
                    "returncode": phase["returncode"],
                    "duration_sec": phase["duration_sec"],
                }
                for name, phase in phases.items()
            },
        }
        append_run(results_root / "runs.jsonl", record)
        return record

    def _run_script(
        self,
        phase: str,
        case: Case,
        trace_dir: Path,
        env: dict[str, str],
        timeout: int = 300,
        check: bool = True,
    ) -> dict[str, Any]:
        return self._run_command(
            phase,
            [
                self.python_executable,
                str(case.scripts[phase]),
                "--case-dir",
                str(case.case_dir),
            ],
            trace_dir,
            env,
            timeout=timeout,
            check=check,
        )

    def _run_command(
        self,
        phase: str,
        command: list[str],
        trace_dir: Path,
        env: dict[str, str],
        timeout: int,
        check: bool = True,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            returncode = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nTimed out after {timeout}s"

        duration_sec = round(time.monotonic() - started, 3)
        result = {
            "phase": phase,
            "command": command,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "duration_sec": duration_sec,
        }
        self._write_phase_log(trace_dir, phase, result)
        if check and returncode != 0:
            raise OpsBenchRunError(
                f"phase {phase} failed with exit code {returncode}; see {trace_dir}"
            )
        return result

    def _write_phase_log(
        self,
        trace_dir: Path,
        phase: str,
        result: dict[str, Any],
    ) -> None:
        log_path = trace_dir / f"{phase}.log"
        command = " ".join(shlex.quote(part) for part in result["command"])
        log_path.write_text(
            "\n".join(
                [
                    f"$ {command}",
                    f"returncode={result['returncode']}",
                    f"duration_sec={result['duration_sec']}",
                    "",
                    "[stdout]",
                    result["stdout"],
                    "",
                    "[stderr]",
                    result["stderr"],
                ]
            ),
            encoding="utf-8",
        )

    def _write_task_context(self, case: Case, workspace_dir: Path, verify_cmd: Path) -> Path:
        source_task = case.task_file.read_text(encoding="utf-8")
        task_path = workspace_dir / "task.md"
        task_path.write_text(
            source_task
            + "\n\n"
            + "## Runner Context\n\n"
            + f"- Case id: `{case.id}`\n"
            + f"- Case directory: `{case.case_dir}`\n"
            + f"- Docker Compose file: `{case.compose_file}`\n"
            + f"- Verify command: `{verify_cmd}`\n",
            encoding="utf-8",
        )
        return task_path

    def _write_verify_wrapper(self, case: Case, workspace_dir: Path) -> Path:
        verify_cmd = workspace_dir / "verify.sh"
        verify_cmd.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    "exec "
                    + " ".join(
                        [
                            shlex.quote(self.python_executable),
                            shlex.quote(str(case.scripts["verify"])),
                            "--case-dir",
                            shlex.quote(str(case.case_dir)),
                        ]
                    ),
                    "",
                ]
            ),
            encoding="utf-8",
        )
        verify_cmd.chmod(0o755)
        return verify_cmd

    def _phase_env(
        self,
        case: Case,
        run_id: str,
        compose_project: str,
        trace_dir: Path,
        verify_cmd: Path,
    ) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "OPSBENCH_CASE_ID": case.id,
                "OPSBENCH_RUN_ID": run_id,
                "OPSBENCH_COMPOSE_PROJECT": compose_project,
                "OPSBENCH_TRACE_DIR": str(trace_dir),
                "OPSBENCH_VERIFY_CMD": str(verify_cmd),
            }
        )
        return env


def _compose_cmd(case: Case, compose_project: str, args: list[str]) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        compose_project,
        "-f",
        str(case.compose_file),
        *args,
    ]


def _parse_last_json_object(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {"passed": False, "checks": [], "error": "no JSON object found"}


def _agent_name(agent_path: Path) -> str:
    if agent_path.name == "run.sh":
        return agent_path.parent.name
    return agent_path.stem


def _make_run_id(started_at: datetime, case_id: str, agent_name: str) -> str:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{case_id}-{agent_name}"


def _compose_project_name(run_id: str) -> str:
    digest = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:12]
    return f"opsbench_{digest}"


def _relative_trace_path(trace_dir: Path, results_root: Path) -> str:
    try:
        return trace_dir.relative_to(results_root.parent).as_posix()
    except ValueError:
        return trace_dir.as_posix()
