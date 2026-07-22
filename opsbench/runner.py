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
from opsbench.kubernetes_cluster import MinikubeClusterManager
from opsbench.results import append_run


class OpsBenchRunError(RuntimeError):
    """Raised when the runner cannot complete an infrastructure phase."""


class OpsBenchRunner:
    def __init__(
        self,
        use_docker: bool = True,
        python_executable: str | None = None,
        cluster_manager: MinikubeClusterManager | None = None,
    ):
        self.use_docker = use_docker
        self.python_executable = python_executable or sys.executable
        self.cluster_manager = cluster_manager or MinikubeClusterManager()

    def run(
        self,
        case_dir: str | Path,
        agent_path: str | Path,
        results_dir: str | Path = "results",
        timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        case = load_case(case_dir)
        if case.environment_type == "kubernetes":
            with self.cluster_manager.run_lock():
                return self._run_case(
                    case,
                    agent_path,
                    results_dir=results_dir,
                    timeout_sec=timeout_sec,
                )
        return self._run_case(
            case,
            agent_path,
            results_dir=results_dir,
            timeout_sec=timeout_sec,
        )

    def _run_case(
        self,
        case: Case,
        agent_path: str | Path,
        results_dir: str | Path,
        timeout_sec: int | None,
    ) -> dict[str, Any]:
        managed_kubeconfig: Path | None = None
        if case.environment_type == "kubernetes":
            managed_kubeconfig = self.cluster_manager.ensure()
        agent = Path(agent_path).resolve()
        results_root = Path(results_dir).resolve()
        results_root.mkdir(parents=True, exist_ok=True)

        agent_name = _agent_name(agent)
        started_at = datetime.now(UTC)
        run_id = _make_run_id(started_at, case.id, agent_name)
        trace_dir = results_root / "traces" / run_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        agent_trace_dir = trace_dir / "agent"
        agent_trace_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir = Path("runtime") / run_id / "workspace"
        workspace_dir = workspace_dir.resolve()
        workspace_dir.mkdir(parents=True, exist_ok=True)

        compose_project = _compose_project_name(run_id)
        task_file = self._write_task_context(case, workspace_dir)
        env = self._phase_env(case, run_id, compose_project, trace_dir, workspace_dir)
        env["OPSBENCH_AGENT_SOURCE"] = str(agent.parent)
        env["OPSBENCH_TASK_SOURCE"] = str(task_file)
        if managed_kubeconfig is not None:
            env["KUBECONFIG"] = str(managed_kubeconfig)
            env["OPSBENCH_OTEL_CHART_ARCHIVE"] = str(
                self.cluster_manager.chart_archive
            )
        effective_timeout = timeout_sec or case.agent_timeout_sec

        phases: dict[str, dict[str, Any]] = {}
        verification_result: dict[str, Any] = {"passed": False, "checks": []}
        started_monotonic = time.monotonic()

        try:
            if self.use_docker and case.environment_type == "compose":
                phases["start"] = self._run_command(
                    "start",
                    _compose_cmd(case, compose_project, ["up", "-d", "--build", "--wait"]),
                    trace_dir,
                    env,
                    timeout=300,
                )

            if "setup" in case.scripts:
                phases["setup"] = self._run_script(
                    "setup", case, trace_dir, env, timeout=900
                )

            phases["inject"] = self._run_script("inject", case, trace_dir, env)
            phases["check_injected"] = self._run_script(
                "check_injected", case, trace_dir, env
            )

            agent_env = env.copy()
            agent_env["OPSBENCH_TRACE_DIR"] = str(agent_trace_dir)
            agent_env.update(_agent_config_env(env))
            phases["agent"] = self._run_command(
                "agent",
                self._agent_command(
                    case=case,
                    agent=agent,
                    task_file=task_file,
                    workspace_dir=workspace_dir,
                    trace_dir=agent_trace_dir,
                    timeout_sec=effective_timeout,
                    env=env,
                ),
                trace_dir,
                agent_env,
                timeout=effective_timeout,
                check=False,
            )

            phases["verify"] = self._run_script("verify", case, trace_dir, env, check=False)
            verification_result = _parse_last_json_object(phases["verify"]["stdout"])
        finally:
            if "cleanup" in case.scripts:
                phases["case_cleanup"] = self._run_script(
                    "cleanup", case, trace_dir, env, timeout=300, check=False
                )
            if self.use_docker and case.environment_type == "compose":
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
            phases.get("agent", {}).get("returncode") == 0
            and
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

    def _agent_command(
        self,
        case: Case,
        agent: Path,
        task_file: Path,
        workspace_dir: Path,
        trace_dir: Path,
        timeout_sec: int,
        env: dict[str, str],
    ) -> list[str]:
        if not self.use_docker:
            return [
                str(agent),
                "--case-dir",
                str(case.case_dir),
                "--task",
                str(task_file),
                "--work-dir",
                str(workspace_dir),
                "--timeout-sec",
                str(timeout_sec),
            ]
        return _agent_container_cmd(
            case=case,
            agent=agent,
            task_file=task_file,
            workspace_dir=workspace_dir,
            trace_dir=trace_dir,
            timeout_sec=timeout_sec,
            env=env,
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

    def _write_task_context(self, case: Case, workspace_dir: Path) -> Path:
        source_task = case.task_file.read_text(encoding="utf-8")
        task_path = workspace_dir / "task.md"
        task_path.write_text(source_task, encoding="utf-8")
        return task_path

    def _phase_env(
        self,
        case: Case,
        run_id: str,
        compose_project: str,
        trace_dir: Path,
        workspace_dir: Path,
    ) -> dict[str, str]:
        env = os.environ.copy()
        phase_env = {
            "OPSBENCH_CASE_ID": case.id,
            "OPSBENCH_RUN_ID": run_id,
            "OPSBENCH_COMPOSE_PROJECT": compose_project,
            "OPSBENCH_TRACE_DIR": str(trace_dir),
            "OPSBENCH_AGENT_TRACE_DIR": str(trace_dir / "agent"),
            "OPSBENCH_TOOL_STANDARD": case.tool_standard["id"],
            "OPSBENCH_TOOL_COMMANDS": ",".join(case.tool_standard["commands"]),
            "OPSBENCH_AGENT_KUBECONFIG": str(workspace_dir / "agent-kubeconfig.json"),
        }
        namespace_suffix = hashlib.sha1(run_id.encode("utf-8")).hexdigest()[:10]
        phase_env["OPSBENCH_NAMESPACE"] = (
            f"{case.namespace_prefix}-{namespace_suffix}"[:63].rstrip("-")
        )
        if case.services:
            phase_env["OPSBENCH_SHELL_SERVICE"] = case.services[0]
        env.update(phase_env)
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


def _agent_container_cmd(
    case: Case,
    agent: Path,
    task_file: Path,
    workspace_dir: Path,
    trace_dir: Path,
    timeout_sec: int,
    env: dict[str, str],
) -> list[str]:
    container_agent = f"/agent/{agent.name}"
    if case.agent_service:
        return _agent_service_exec_cmd(
            case=case,
            container_agent=container_agent,
            timeout_sec=timeout_sec,
            env=env,
        )
    command = [
        "docker",
        "compose",
        "-p",
        env["OPSBENCH_COMPOSE_PROJECT"],
        "-f",
        str(case.compose_file),
        "run",
        "--rm",
        "--build",
        "-T",
        "--no-deps",
        "-v",
        f"{agent.parent}:/agent:ro",
        "-v",
        f"{task_file}:/task/task.md:ro",
        "-v",
        f"{trace_dir}:/trace",
        "-e",
        "OPSBENCH_AGENT_CONTAINER=1",
        "-e",
        f"OPSBENCH_CASE_ID={env.get('OPSBENCH_CASE_ID', '')}",
        "-e",
        f"OPSBENCH_RUN_ID={env.get('OPSBENCH_RUN_ID', '')}",
        "-e",
        "OPSBENCH_TRACE_DIR=/trace",
        "-e",
        f"OPSBENCH_SHELL_SERVICE={case.services[0] if case.services else ''}",
        "-e",
        f"OPSBENCH_NAMESPACE={env.get('OPSBENCH_NAMESPACE', '')}",
        "-e",
        f"OPSBENCH_TOOL_STANDARD={case.tool_standard['id']}",
        "-e",
        f"OPSBENCH_TOOL_COMMANDS={','.join(case.tool_standard['commands'])}",
    ]
    _append_agent_config_env(command, env)
    if case.environment_type == "kubernetes":
        kubeconfig = Path(env["OPSBENCH_AGENT_KUBECONFIG"]).resolve()
        if not kubeconfig.is_file():
            raise OpsBenchRunError(
                f"restricted agent kubeconfig was not created by setup: {kubeconfig}"
            )
        command.extend(
            [
                "-v",
                f"{kubeconfig}:/kube/config:ro",
                "-e",
                "KUBECONFIG=/kube/config",
            ]
        )
    command.extend(
        [
            "agent-runner",
            container_agent,
            "--case-dir",
            "/case",
            "--task",
            "/task/task.md",
            "--work-dir",
            "/tmp/agent-work",
            "--timeout-sec",
            str(timeout_sec),
        ]
    )
    return command


def _agent_service_exec_cmd(
    case: Case,
    container_agent: str,
    timeout_sec: int,
    env: dict[str, str],
) -> list[str]:
    command = [
        "docker",
        "compose",
        "-p",
        env["OPSBENCH_COMPOSE_PROJECT"],
        "-f",
        str(case.compose_file),
        "exec",
        "-T",
    ]
    runtime_env = {
        "OPSBENCH_AGENT_CONTAINER": "1",
        "OPSBENCH_CASE_ID": env.get("OPSBENCH_CASE_ID", ""),
        "OPSBENCH_RUN_ID": env.get("OPSBENCH_RUN_ID", ""),
        "OPSBENCH_TRACE_DIR": "/trace",
        "OPSBENCH_SHELL_SERVICE": case.services[0] if case.services else "",
        "OPSBENCH_NAMESPACE": env.get("OPSBENCH_NAMESPACE", ""),
        "OPSBENCH_TOOL_STANDARD": case.tool_standard["id"],
        "OPSBENCH_TOOL_COMMANDS": ",".join(case.tool_standard["commands"]),
    }
    for key, value in runtime_env.items():
        command.extend(["-e", f"{key}={value}"])
    _append_agent_config_env(command, env)
    command.extend(
        [
            case.agent_service,
            container_agent,
            "--case-dir",
            "/case",
            "--task",
            "/task/task.md",
            "--work-dir",
            "/tmp/agent-work",
            "--timeout-sec",
            str(timeout_sec),
        ]
    )
    return command


def _append_agent_config_env(command: list[str], env: dict[str, str]) -> None:
    for key in _agent_config_env(env):
        command.extend(["-e", key])


def _agent_config_env(env: dict[str, str]) -> dict[str, str]:
    defaults = {
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-v4-pro",
        "LANGCHAIN_MAX_STEPS": "60",
        "LANGCHAIN_TEMPERATURE": "0",
    }
    return {key: env.get(key, default) for key, default in defaults.items()}


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
