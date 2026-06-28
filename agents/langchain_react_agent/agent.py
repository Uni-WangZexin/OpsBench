from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agents.langchain_react_agent.config import AgentConfig, load_config
from agents.langchain_react_agent.prompts import build_system_prompt, build_user_prompt
from agents.langchain_react_agent.tools import ToolContext, create_langchain_tools


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="langchain-react-agent")
    parser.add_argument("--case-dir", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--timeout-sec", type=int, required=True)
    return parser.parse_args(argv)


def write_missing_key_error(trace_dir: Path, exc: Exception) -> None:
    trace_dir.mkdir(parents=True, exist_ok=True)
    message = str(exc)
    (trace_dir / "trace.md").write_text(
        "# langchain-react-agent trace\n\n"
        "Status: configuration_error\n\n"
        f"{message}\n",
        encoding="utf-8",
    )
    _write_final_json(
        trace_dir,
        {
            "agent": "langchain-react-agent",
            "status": "configuration_error",
            "error": message,
            "verifier_called": False,
        },
    )


def build_agent(config: AgentConfig, context: ToolContext) -> Any:
    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "langchain and langchain-openai are required. Install "
            "agents/langchain-react-agent/requirements.txt"
        ) from exc

    model = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
    )
    return create_agent(
        model=model,
        tools=create_langchain_tools(context),
        system_prompt=build_system_prompt(),
    )


def run_agent(args: argparse.Namespace) -> int:
    case_dir = Path(args.case_dir).resolve()
    task_file = Path(args.task).resolve()
    work_dir = Path(args.work_dir).resolve()
    trace_dir = Path(os.environ.get("OPSBENCH_TRACE_DIR", work_dir / "trace")).resolve()
    trace_dir.mkdir(parents=True, exist_ok=True)

    try:
        config = load_config()
    except RuntimeError as exc:
        write_missing_key_error(trace_dir, exc)
        return 2

    context = ToolContext(
        case_dir=case_dir,
        work_dir=work_dir,
        trace_dir=trace_dir,
        verify_cmd=os.environ.get("OPSBENCH_VERIFY_CMD", ""),
        command_timeout_sec=min(max(args.timeout_sec, 1), 120),
    )
    task_text = task_file.read_text(encoding="utf-8")
    user_prompt = build_user_prompt(
        task_text=task_text,
        case_dir=str(case_dir),
        work_dir=str(work_dir),
        verify_cmd=context.verify_cmd,
    )

    try:
        agent = build_agent(config, context)
        response = agent.invoke(
            {"messages": [{"role": "user", "content": user_prompt}]},
            config={"recursion_limit": config.max_steps},
        )
        final_response = _extract_final_response(response)
    except Exception as exc:  # noqa: BLE001 - agent failure is recorded for benchmark traces.
        _write_trace(trace_dir, config, "failed", str(exc))
        _write_final_json(
            trace_dir,
            {
                "agent": "langchain-react-agent",
                "model": config.model,
                "base_url": config.base_url,
                "status": "failed",
                "error": str(exc),
                "verifier_called": context.verifier_called,
            },
        )
        return 1

    _write_trace(trace_dir, config, "completed", final_response)
    _write_final_json(
        trace_dir,
        {
            "agent": "langchain-react-agent",
            "model": config.model,
            "base_url": config.base_url,
            "status": "completed",
            "final_response": final_response,
            "verifier_called": context.verifier_called,
        },
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_agent(parse_args(argv))


def _extract_final_response(response: Any) -> str:
    if isinstance(response, dict) and response.get("messages"):
        last_message = response["messages"][-1]
        content = getattr(last_message, "content", None)
        if content is None and isinstance(last_message, dict):
            content = last_message.get("content")
        return str(content)
    return str(response)


def _write_trace(
    trace_dir: Path,
    config: AgentConfig,
    status: str,
    final_response: str,
) -> None:
    (trace_dir / "trace.md").write_text(
        "# langchain-react-agent trace\n\n"
        f"Status: {status}\n\n"
        f"Model: {config.model}\n\n"
        f"Base URL: {config.base_url}\n\n"
        "Final response:\n\n"
        f"{final_response}\n",
        encoding="utf-8",
    )


def _write_final_json(trace_dir: Path, payload: dict[str, Any]) -> None:
    (trace_dir / "final.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
