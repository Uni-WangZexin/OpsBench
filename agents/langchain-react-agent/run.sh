#!/usr/bin/env bash
set -euo pipefail

exec python3 -m agents.langchain_react_agent.agent "$@"
