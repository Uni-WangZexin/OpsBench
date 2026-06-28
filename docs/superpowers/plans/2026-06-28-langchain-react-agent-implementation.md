# LangChain ReAct Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CLI-compatible LangChain ReAct/tool agent that can diagnose and repair OpsBench cases using a DeepSeek OpenAI-compatible model and strong shell tools.

**Architecture:** Keep the existing OpsBench runner unchanged because it already supports arbitrary CLI agents. Add `agents/langchain-react-agent/` as a self-contained Python package plus `run.sh`; unit tests cover configuration, tool behavior, prompt construction, and wrapper invocation without requiring a real API key. Optional integration smoke runs through `opsbench.cli` after the user sets `DEEPSEEK_API_KEY`.

**Tech Stack:** Python 3 standard library for tested support code, Bash wrapper, optional runtime dependencies `langchain` and `langchain-openai`, DeepSeek OpenAI-compatible Chat API.

---

### Task 1: Agent Configuration And Prompt

**Files:**
- Create: `agents/__init__.py`
- Create: `agents/langchain_react_agent/__init__.py`
- Create: `agents/langchain_react_agent/config.py`
- Create: `agents/langchain_react_agent/prompts.py`
- Create: `tests/test_langchain_agent_config.py`
- Create: `tests/test_langchain_agent_prompts.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_langchain_agent_config.py`:

```python
import os
import unittest
from unittest.mock import patch

from agents.langchain_react_agent.config import AgentConfig, load_config


class LangChainAgentConfigTests(unittest.TestCase):
    def test_load_config_reads_deepseek_defaults(self):
        env = {"DEEPSEEK_API_KEY": "secret"}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertEqual(config.max_steps, 12)
        self.assertEqual(config.temperature, 0.0)

    def test_load_config_allows_overrides(self):
        env = {
            "DEEPSEEK_API_KEY": "secret",
            "DEEPSEEK_BASE_URL": "https://example.test/v1",
            "DEEPSEEK_MODEL": "deepseek-test",
            "LANGCHAIN_MAX_STEPS": "5",
            "LANGCHAIN_TEMPERATURE": "0.2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(
            config,
            AgentConfig(
                api_key="secret",
                base_url="https://example.test/v1",
                model="deepseek-test",
                max_steps=5,
                temperature=0.2,
            ),
        )

    def test_missing_api_key_raises_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                load_config()
```

- [ ] **Step 2: Run config tests to verify RED**

Run: `python3 -m unittest tests.test_langchain_agent_config -v`

Expected: fails with `ModuleNotFoundError` for `agents.langchain_react_agent`.

- [ ] **Step 3: Implement config module**

Create importable package directory `agents/langchain_react_agent/` as a code package and keep executable files in `agents/langchain-react-agent/`. Add `agents/langchain_react_agent/config.py`:

```python
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
```

Create `agents/__init__.py` and `agents/langchain_react_agent/__init__.py` with short package docstrings.

- [ ] **Step 4: Run config tests to verify GREEN**

Run: `python3 -m unittest tests.test_langchain_agent_config -v`

Expected: passes.

- [ ] **Step 5: Write failing prompt tests**

Create `tests/test_langchain_agent_prompts.py`:

```python
import unittest

from agents.langchain_react_agent.prompts import build_system_prompt, build_user_prompt


class LangChainAgentPromptTests(unittest.TestCase):
    def test_system_prompt_declares_opsbench_and_hidden_data_rule(self):
        prompt = build_system_prompt()

        self.assertIn("OpsBench", prompt)
        self.assertIn("Do not inspect hidden", prompt)
        self.assertIn("run the verifier", prompt)

    def test_user_prompt_contains_public_context(self):
        prompt = build_user_prompt(
            task_text="The API is slow.",
            case_dir="/case",
            work_dir="/work",
            verify_cmd="/work/verify.sh",
        )

        self.assertIn("The API is slow.", prompt)
        self.assertIn("/case", prompt)
        self.assertIn("/work", prompt)
        self.assertIn("/work/verify.sh", prompt)
        self.assertNotIn("oracle_fix.sql", prompt)
```

- [ ] **Step 6: Run prompt tests to verify RED**

Run: `python3 -m unittest tests.test_langchain_agent_prompts -v`

Expected: fails because `prompts.py` does not exist.

- [ ] **Step 7: Implement prompt module**

Create `agents/langchain_react_agent/prompts.py` with `build_system_prompt()` and `build_user_prompt(...)` that match the tests and instruct the agent to use LangChain tools, avoid hidden data, repair the environment, call the verifier, and summarize the outcome.

- [ ] **Step 8: Run Task 1 tests to verify GREEN**

Run: `python3 -m unittest tests.test_langchain_agent_config tests.test_langchain_agent_prompts -v`

Expected: passes.

- [ ] **Step 9: Commit**

Run:

```bash
git add agents/__init__.py agents/langchain_react_agent tests/test_langchain_agent_config.py tests/test_langchain_agent_prompts.py
git commit -m "feat: add LangChain agent config and prompts"
```

### Task 2: Strong-Permission Tool Layer

**Files:**
- Create: `agents/langchain_react_agent/tools.py`
- Create: `tests/test_langchain_agent_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/test_langchain_agent_tools.py`:

```python
import tempfile
import unittest
from pathlib import Path

from agents.langchain_react_agent.tools import ToolContext, create_tools


class LangChainAgentToolTests(unittest.TestCase):
    def test_read_and_write_file_are_root_guarded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            (case_dir / "task.md").write_text("hello", encoding="utf-8")
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            self.assertEqual(tools["read_file"]("task.md"), "hello")
            self.assertIn("wrote", tools["write_file"]("note.txt", "fixed"))
            self.assertEqual((work_dir / "note.txt").read_text(encoding="utf-8"), "fixed")
            with self.assertRaises(ValueError):
                tools["read_file"]("../outside.txt")

    def test_shell_captures_output_and_writes_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd="/bin/true",
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            output = tools["shell"]("printf hi")

            self.assertIn("returncode=0", output)
            self.assertIn("hi", output)
            self.assertTrue(list(trace_dir.glob("tool-shell-*.log")))

    def test_run_verifier_uses_verify_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            work_dir = root / "work"
            trace_dir = root / "trace"
            case_dir.mkdir()
            work_dir.mkdir()
            trace_dir.mkdir()
            verify = work_dir / "verify.sh"
            verify.write_text("#!/usr/bin/env bash\necho verified\n", encoding="utf-8")
            verify.chmod(0o755)
            context = ToolContext(
                case_dir=case_dir,
                work_dir=work_dir,
                trace_dir=trace_dir,
                verify_cmd=str(verify),
                command_timeout_sec=5,
            )
            tools = create_tools(context)

            output = tools["run_verifier"]()

            self.assertIn("verified", output)
            self.assertTrue(context.verifier_called)
```

- [ ] **Step 2: Run tool tests to verify RED**

Run: `python3 -m unittest tests.test_langchain_agent_tools -v`

Expected: fails because `tools.py` does not exist.

- [ ] **Step 3: Implement tool layer**

Create `agents/langchain_react_agent/tools.py` with:

- `ToolContext` dataclass.
- `create_tools(context)` returning dictionary callables for unit tests.
- `create_langchain_tools(context)` wrapping those callables with `langchain.tools.tool` when LangChain is installed.
- Guarded path resolution for `read_file` and `write_file`.
- `shell` using `subprocess.run(..., shell=True, cwd=context.case_dir)`, writing full logs to `$trace_dir/tool-shell-N.log`, and returning truncated output to the model.
- `run_verifier` calling `context.verify_cmd` and setting `context.verifier_called = True`.

- [ ] **Step 4: Run tool tests to verify GREEN**

Run: `python3 -m unittest tests.test_langchain_agent_tools -v`

Expected: passes.

- [ ] **Step 5: Commit**

Run:

```bash
git add agents/langchain_react_agent/tools.py tests/test_langchain_agent_tools.py
git commit -m "feat: add LangChain agent strong tools"
```

### Task 3: LangChain Agent Entrypoint And Wrapper

**Files:**
- Create: `agents/langchain_react_agent/agent.py`
- Create: `agents/langchain-react-agent/run.sh`
- Create: `agents/langchain-react-agent/requirements.txt`
- Create: `tests/test_langchain_agent_entrypoint.py`

- [ ] **Step 1: Write failing entrypoint tests**

Create `tests/test_langchain_agent_entrypoint.py`:

```python
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.langchain_react_agent.agent import parse_args, write_missing_key_error


class LangChainAgentEntrypointTests(unittest.TestCase):
    def test_parse_args_accepts_opsbench_agent_protocol(self):
        args = parse_args([
            "--case-dir", "/case",
            "--task", "/task.md",
            "--work-dir", "/work",
            "--timeout-sec", "300",
        ])

        self.assertEqual(args.case_dir, "/case")
        self.assertEqual(args.task, "/task.md")
        self.assertEqual(args.work_dir, "/work")
        self.assertEqual(args.timeout_sec, 300)

    def test_missing_key_error_writes_trace_and_final_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            trace_dir = Path(temp_dir) / "trace"
            trace_dir.mkdir()

            write_missing_key_error(trace_dir, RuntimeError("DEEPSEEK_API_KEY is required"))

            self.assertIn("DEEPSEEK_API_KEY", (trace_dir / "trace.md").read_text(encoding="utf-8"))
            final = json.loads((trace_dir / "final.json").read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "configuration_error")

    def test_run_sh_invokes_python_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_python = root / "python3"
            capture = root / "capture.txt"
            fake_python.write_text(
                "#!/usr/bin/env bash\n"
                f"printf '%s\\n' \"$@\" > {capture}\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{root}:{env['PATH']}"
            env["OPSBENCH_TRACE_DIR"] = str(root / "trace")

            result = subprocess.run(
                [
                    "agents/langchain-react-agent/run.sh",
                    "--case-dir", "/case",
                    "--task", "/task.md",
                    "--work-dir", "/work",
                    "--timeout-sec", "300",
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            captured = capture.read_text(encoding="utf-8")
            self.assertIn("-m", captured)
            self.assertIn("agents.langchain_react_agent.agent", captured)
            self.assertIn("--case-dir", captured)
```

- [ ] **Step 2: Run entrypoint tests to verify RED**

Run: `python3 -m unittest tests.test_langchain_agent_entrypoint -v`

Expected: fails because `agent.py` and wrapper do not exist.

- [ ] **Step 3: Implement entrypoint**

Create `agents/langchain_react_agent/agent.py` with:

- `parse_args(argv=None)`.
- `write_missing_key_error(trace_dir, exc)`.
- `build_agent(config, context)`: imports `ChatOpenAI`, `create_agent`, and `create_langchain_tools` lazily.
- `run_agent(args)`: loads config, task text, prompt, tools, invokes LangChain `create_agent(...).invoke({"messages": [...]})`, writes `trace.md` and `final.json`.
- `main(argv=None)` returning `0` for completed invocation and non-zero for configuration/import failures.

The LangChain import must be lazy so unit tests can run without installed dependencies.

- [ ] **Step 4: Implement wrapper and requirements**

Create `agents/langchain-react-agent/run.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
exec python3 -m agents.langchain_react_agent.agent "$@"
```

Create `agents/langchain-react-agent/requirements.txt`:

```text
langchain>=1.0
langchain-openai>=1.0
```

Make `run.sh` executable.

- [ ] **Step 5: Run entrypoint tests to verify GREEN**

Run: `python3 -m unittest tests.test_langchain_agent_entrypoint -v`

Expected: passes.

- [ ] **Step 6: Commit**

Run:

```bash
git add agents/langchain_react_agent/agent.py agents/langchain-react-agent tests/test_langchain_agent_entrypoint.py
git commit -m "feat: add LangChain ReAct agent entrypoint"
```

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-06-28-langchain-react-agent-implementation.md`

- [ ] **Step 1: Update README**

Add a section `LangChain ReAct agent` that documents:

```bash
python3 -m pip install -r agents/langchain-react-agent/requirements.txt
export DEEPSEEK_API_KEY=...
export DEEPSEEK_MODEL=deepseek-v4-pro
export DEEPSEEK_BASE_URL=https://api.deepseek.com
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

State that this agent has strong shell permissions and depends on network/model behavior, while `oracle-agent` remains the deterministic success baseline.

- [ ] **Step 2: Run full unit tests**

Run: `python3 -m unittest discover -v`

Expected: all tests pass.

- [ ] **Step 3: Run deterministic benchmark smoke tests**

Run:

```bash
python3 -m opsbench.cli run --case cases/postgres-missing-index-001 --agent agents/noop-agent/run.sh --results-dir /private/tmp/opsbench-langchain-agent-smoke
python3 -m opsbench.cli run --case cases/postgres-missing-index-001 --agent agents/oracle-agent/run.sh --results-dir /private/tmp/opsbench-langchain-agent-smoke
python3 -m opsbench.cli leaderboard --results /private/tmp/opsbench-langchain-agent-smoke/runs.jsonl
```

Expected: `noop-agent` records failure, `oracle-agent` records success, leaderboard shows both.

- [ ] **Step 4: Document optional LangChain smoke**

Do not run this unless `DEEPSEEK_API_KEY` is present:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

Expected with a valid model setup: the agent writes `trace.md`, `final.json`, and tool logs. Passing the benchmark depends on model behavior.

- [ ] **Step 5: Commit**

Run:

```bash
git add README.md docs/superpowers/plans/2026-06-28-langchain-react-agent-implementation.md
git commit -m "docs: add LangChain ReAct agent usage"
```

## Self-Review

- Spec coverage: the tasks cover the LangChain packaged agent, DeepSeek OpenAI-compatible configuration, strong shell tool, trace outputs, existing CLI protocol, deterministic baselines, and optional model-backed smoke test.
- Planning marker scan: no unresolved planning markers remain outside checkbox syntax.
- Type consistency: module names use `agents.langchain_react_agent` for Python imports and `agents/langchain-react-agent` for executable agent files.
