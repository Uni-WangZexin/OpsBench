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
        """Run an arbitrary shell command in the case directory."""
        return tools["shell"](command)

    @tool
    def read_file(path: str) -> str:
        """Read a text file under the case directory or work directory."""
        return tools["read_file"](path)

    @tool
    def write_file(path: str, content: str) -> str:
        """Write a text file under the case directory or work directory."""
        return tools["write_file"](path, content)

    @tool
    def run_verifier() -> str:
        """Run the OpsBench verifier command for this case."""
        return tools["run_verifier"]()

    return [shell, read_file, write_file, run_verifier]


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
    full_output = _format_command_output(command, completed.returncode, completed.stdout, completed.stderr)
    log_path.write_text(full_output, encoding="utf-8")
    return _truncate(full_output)


def _read_file(context: ToolContext, path: str) -> str:
    resolved = _resolve_guarded_path(context, path, prefer_work_dir=False)
    return resolved.read_text(encoding="utf-8")


def _write_file(context: ToolContext, path: str, content: str) -> str:
    resolved = _resolve_guarded_path(context, path, prefer_work_dir=True)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return f"wrote {resolved}"


def _run_verifier(context: ToolContext) -> str:
    context.verifier_called = True
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
