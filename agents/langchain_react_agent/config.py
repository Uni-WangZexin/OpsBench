from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    base_url: str
    model: str
    max_steps: int
    temperature: float


def load_config() -> AgentConfig:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for langchain-react-agent")
    return AgentConfig(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        max_steps=int(os.environ.get("LANGCHAIN_MAX_STEPS", "12")),
        temperature=float(os.environ.get("LANGCHAIN_TEMPERATURE", "0")),
    )
