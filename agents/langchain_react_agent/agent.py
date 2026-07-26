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
        },
    )


def build_agent(config: AgentConfig, context: ToolContext) -> Any:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError(
            "langchain-openai is required. Install "
            "agents/langchain-react-agent/requirements.txt"
        ) from exc

    model = ChatOpenAI(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
    )
    tools = create_langchain_tools(context)
    system_prompt = build_system_prompt()
    try:
        from langchain.agents import create_agent

        return create_agent(model=model, tools=tools, system_prompt=system_prompt)
    except ImportError:
        pass

    try:
        from langgraph.prebuilt import create_react_agent
    except ImportError as exc:
        raise RuntimeError(
            "langchain packaged agent support is required. Install "
            "agents/langchain-react-agent/requirements.txt"
        ) from exc

    return create_react_agent(model=model, tools=tools, prompt=system_prompt)


def run_agent(args: argparse.Namespace) -> int:
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
        execution_dir=Path.cwd(),
        trace_dir=trace_dir,
        command_timeout_sec=min(max(args.timeout_sec, 1), 120),
        tool_standard=os.environ.get("OPSBENCH_TOOL_STANDARD", "shell-v1"),
        namespace=os.environ.get("OPSBENCH_NAMESPACE", ""),
    )
    task_text = task_file.read_text(encoding="utf-8")
    user_prompt = build_user_prompt(
        task_text=task_text,
        shell_service=os.environ.get("OPSBENCH_SHELL_SERVICE", ""),
        namespace=os.environ.get("OPSBENCH_NAMESPACE", ""),
        tool_standard=os.environ.get("OPSBENCH_TOOL_STANDARD", "shell-v1"),
        tool_commands=os.environ.get("OPSBENCH_TOOL_COMMANDS", ""),
    )

    try:
        agent = build_agent(config, context)
        response = _stream_agent_with_trace(
            agent,
            {"messages": [{"role": "user", "content": user_prompt}]},
            {"recursion_limit": config.max_steps},
            trace_dir,
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
        },
    )
    return 0


def _stream_agent_with_trace(
    agent: Any,
    inputs: dict[str, Any],
    config: dict[str, Any],
    trace_dir: Path,
) -> dict[str, Any]:
    """Persist the latest graph state so recursion/timeout failures remain auditable."""

    latest: dict[str, Any] | None = None
    for state in agent.stream(inputs, config=config, stream_mode="values"):
        if not isinstance(state, dict):
            continue
        latest = state
        _write_react_trace(trace_dir, latest)
    if latest is None:
        raise RuntimeError("agent completed without producing a graph state")
    return latest


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


def _write_react_trace(trace_dir: Path, response: Any) -> None:
    messages = _extract_response_messages(response)
    serialized_messages = [
        _serialize_message(index, message)
        for index, message in enumerate(messages, start=1)
    ]
    (trace_dir / "react-trace.json").write_text(
        json.dumps({"messages": serialized_messages}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (trace_dir / "react-trace.md").write_text(
        _format_react_trace_markdown(serialized_messages),
        encoding="utf-8",
    )


def _extract_response_messages(response: Any) -> list[Any]:
    if isinstance(response, dict):
        messages = response.get("messages", [])
        if isinstance(messages, list):
            return messages
    return []


def _serialize_message(index: int, message: Any) -> dict[str, Any]:
    role = _message_value(message, "role") or _message_value(message, "type") or "message"
    serialized: dict[str, Any] = {
        "index": index,
        "role": _normalize_role(str(role)),
        "content": _json_safe(_message_value(message, "content") or ""),
        "actions": _extract_actions(message),
    }
    name = _message_value(message, "name")
    if name:
        serialized["name"] = str(name)
    tool_call_id = _message_value(message, "tool_call_id")
    if tool_call_id:
        serialized["tool_call_id"] = str(tool_call_id)
    return serialized


def _message_value(message: Any, key: str) -> Any:
    if isinstance(message, dict):
        return message.get(key)
    return getattr(message, key, None)


def _normalize_role(role: str) -> str:
    lowered = role.lower()
    if lowered in {"human", "user"}:
        return "user"
    if lowered in {"ai", "assistant"}:
        return "assistant"
    if lowered in {"tool", "function"}:
        return "tool"
    return lowered


def _extract_actions(message: Any) -> list[dict[str, Any]]:
    raw_tool_calls = _message_value(message, "tool_calls") or []
    additional_kwargs = _message_value(message, "additional_kwargs") or {}
    if not raw_tool_calls and isinstance(additional_kwargs, dict):
        raw_tool_calls = additional_kwargs.get("tool_calls") or []
    if not isinstance(raw_tool_calls, list):
        return []
    return [_serialize_tool_call(tool_call) for tool_call in raw_tool_calls]


def _serialize_tool_call(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        function = tool_call.get("function") or {}
        raw_args = tool_call.get("args")
        if raw_args is None and isinstance(function, dict):
            raw_args = function.get("arguments")
        return {
            "id": _string_or_empty(tool_call.get("id")),
            "name": _string_or_empty(tool_call.get("name") or function.get("name")),
            "args": _parse_tool_args(raw_args),
        }
    function = getattr(tool_call, "function", None)
    raw_args = getattr(tool_call, "args", None)
    if raw_args is None and function is not None:
        raw_args = getattr(function, "arguments", None)
    return {
        "id": _string_or_empty(getattr(tool_call, "id", "")),
        "name": _string_or_empty(
            getattr(tool_call, "name", "") or getattr(function, "name", "")
        ),
        "args": _parse_tool_args(raw_args),
    }


def _parse_tool_args(raw_args: Any) -> Any:
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            return raw_args
    return _json_safe(raw_args)


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _string_or_empty(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_react_trace_markdown(messages: list[dict[str, Any]]) -> str:
    lines = ["# LangChain ReAct Trace", ""]
    for message in messages:
        role = message["role"]
        heading = {
            "user": "User",
            "assistant": "Assistant",
            "tool": "Observation",
        }.get(role, role.title())
        lines.extend([f"## {message['index']}. {heading}", ""])
        name = message.get("name")
        if name:
            lines.extend([f"- Name: `{name}`", ""])
        tool_call_id = message.get("tool_call_id")
        if tool_call_id:
            lines.extend([f"- Tool call id: `{tool_call_id}`", ""])
        content = _markdown_content(message["content"])
        if content:
            lines.extend([content, ""])
        for action_index, action in enumerate(message["actions"], start=1):
            lines.extend(
                [
                    f"### Action {action_index}",
                    "",
                    f"- Tool: `{action['name']}`",
                ]
            )
            if action["id"]:
                lines.append(f"- Call id: `{action['id']}`")
            lines.extend(["", "```json", json.dumps(action["args"], indent=2), "```", ""])
    return "\n".join(lines)


def _markdown_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "```json\n" + json.dumps(content, indent=2) + "\n```"


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
