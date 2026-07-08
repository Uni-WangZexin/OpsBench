from __future__ import annotations

import os
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


MAX_TOOL_OUTPUT_CHARS = 6000


@dataclass
class ToolContext:
    case_dir: Path
    work_dir: Path
    trace_dir: Path
    verify_cmd: str
    command_timeout_sec: int = 60
    verifier_called: bool = False
    _log_counter: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.case_dir = self.case_dir.resolve()
        self.work_dir = self.work_dir.resolve()
        self.trace_dir = self.trace_dir.resolve()
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def next_log_path(self, prefix: str) -> Path:
        self._log_counter += 1
        return self.trace_dir / f"tool-{prefix}-{self._log_counter:03d}.log"


def create_tools(context: ToolContext) -> dict[str, Callable[..., str]]:
    return {
        "shell": lambda command: _shell(context, command),
        "read_file": lambda path: _read_file(context, path),
        "write_file": lambda path, content: _write_file(context, path, content),
        "psql_query": lambda sql: _psql_query(context, sql),
        "psql_execute": lambda sql: _psql_execute(context, sql),
        "run_verifier": lambda: _run_verifier(context),
    }


def create_langchain_tools(context: ToolContext) -> list[object]:
    try:
        from langchain.tools import tool
    except ImportError as exc:
        raise RuntimeError(
            "langchain is required for langchain-react-agent; install "
            "agents/langchain-react-agent/requirements.txt"
        ) from exc

    tools = create_tools(context)

    @tool
    def shell(command: str) -> str:
        """Run an arbitrary shell command in the agent execution environment."""
        return _tool_result(lambda: tools["shell"](command))

    @tool
    def read_file(path: str) -> str:
        """Read a text file under the case directory or work directory."""
        return _tool_result(lambda: tools["read_file"](path))

    @tool
    def write_file(path: str, content: str) -> str:
        """Write a text file under the work directory for notes or temporary SQL."""
        return _tool_result(lambda: tools["write_file"](path, content))

    @tool
    def psql_query(sql: str) -> str:
        """Run read-only PostgreSQL diagnostic SQL against the case database."""
        return _tool_result(lambda: tools["psql_query"](sql))

    @tool
    def psql_execute(sql: str) -> str:
        """Run PostgreSQL repair SQL against the case database."""
        return _tool_result(lambda: tools["psql_execute"](sql))

    @tool
    def run_verifier() -> str:
        """Run the OpsBench verifier command for this case."""
        return _tool_result(lambda: tools["run_verifier"]())

    return [shell, read_file, write_file, psql_query, psql_execute, run_verifier]


def _tool_result(call: Callable[[], str]) -> str:
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - tool misuse should be observable, not fatal.
        return f"ERROR: {type(exc).__name__}: {exc}"


def _shell(context: ToolContext, command: str) -> str:
    completed = subprocess.run(
        command,
        shell=True,
        cwd=context.case_dir,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )
    log_path = context.next_log_path("shell")
    full_output = _format_command_output(
        command,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    log_path.write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _read_file(context: ToolContext, path: str) -> str:
    resolved = _resolve_guarded_path(context, path, prefer_work_dir=False)
    _reject_hidden_case_path(context, resolved)
    return resolved.read_text(encoding="utf-8")


def _write_file(context: ToolContext, path: str, content: str) -> str:
    resolved = _resolve_work_path(context, path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"wrote {resolved}"


def _psql_query(context: ToolContext, sql: str) -> str:
    wrapped_sql = f"BEGIN READ ONLY;\n{sql}\nROLLBACK;\n"
    return _run_psql(context, "psql-query", wrapped_sql)


def _psql_execute(context: ToolContext, sql: str) -> str:
    return _run_psql(context, "psql-execute", sql)


def _run_psql(context: ToolContext, prefix: str, sql: str) -> str:
    command = [
        "psql",
        "-h",
        os.environ.get("PGHOST", "db"),
        "-U",
        os.environ.get("PGUSER", "opsbench"),
        "-d",
        os.environ.get("PGDATABASE", "opsbench"),
        "-v",
        "ON_ERROR_STOP=1",
        "-qAt",
    ]
    env = os.environ.copy()
    env.setdefault("PGPASSWORD", "opsbench")
    completed = subprocess.run(
        command,
        input=sql,
        shell=False,
        cwd=context.case_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )
    full_output = _format_command_output(
        " ".join(command),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    log_path = context.next_log_path(prefix)
    log_path.write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _run_verifier(context: ToolContext) -> str:
    context.verifier_called = True
    if not context.verify_cmd:
        full_output = _format_command_output(
            "OPSBENCH_VERIFY_CMD",
            0,
            "No verifier command is available inside the agent container; "
            "the OpsBench runner will run final verification after the agent exits.\n",
            "",
        )
        log_path = context.next_log_path("verifier")
        log_path.write_text(full_output, encoding="utf-8")
        return _truncate(full_output)
    completed = subprocess.run(
        context.verify_cmd,
        shell=True,
        cwd=context.case_dir,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=context.command_timeout_sec,
        check=False,
    )
    log_path = context.next_log_path("verifier")
    full_output = _format_command_output(
        context.verify_cmd,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    log_path.write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _resolve_guarded_path(context: ToolContext, path: str, prefer_work_dir: bool) -> Path:
    raw = Path(path)
    candidates = []
    if raw.is_absolute():
        candidates.append(raw.resolve())
    else:
        primary = context.work_dir if prefer_work_dir else context.case_dir
        secondary = context.case_dir if prefer_work_dir else context.work_dir
        candidates.extend([(primary / raw).resolve(), (secondary / raw).resolve()])

    for candidate in candidates:
        if _is_within(candidate, context.case_dir) or _is_within(candidate, context.work_dir):
            return candidate
    raise ValueError(f"path is outside allowed roots: {path}")


def _resolve_work_path(context: ToolContext, path: str) -> Path:
    raw = Path(path)
    candidate = raw.resolve() if raw.is_absolute() else (context.work_dir / raw).resolve()
    if _is_within(candidate, context.work_dir):
        return candidate
    raise ValueError(f"path is outside writable work directory: {path}")


def _reject_hidden_case_path(context: ToolContext, path: Path) -> None:
    try:
        relative = path.relative_to(context.case_dir)
    except ValueError:
        return
    if "hidden" in relative.parts:
        raise ValueError(f"path is not public case data: {path}")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _format_command_output(
    command: str,
    returncode: int,
    stdout: str,
    stderr: str,
) -> str:
    return textwrap.dedent(
        f"""\
        $ {command}
        returncode={returncode}

        [stdout]
        {stdout}

        [stderr]
        {stderr}
        """
    )

def _truncate(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    return output[:MAX_TOOL_OUTPUT_CHARS] + "\n[truncated]\n"
