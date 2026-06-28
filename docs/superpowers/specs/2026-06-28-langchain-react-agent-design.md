# LangChain ReAct Agent Design

## Summary

Add a real intelligent agent to the OpsBench demo while keeping the existing benchmark harness and deterministic baselines. The new agent lives at `agents/langchain-react-agent/` and uses LangChain's packaged ReAct/tool agent support rather than a hand-written reasoning loop.

The agent uses an OpenAI-compatible chat model endpoint for DeepSeek V4 Pro. Credentials and endpoint details come from environment variables so benchmark users can run the same code with their own model setup.

## Current State

The current agents are intentionally simple:

- `noop-agent`: Bash baseline that writes a trace and performs no repair.
- `oracle-agent`: Bash control agent that reads `hidden/oracle_fix.sql` and proves the harness can produce a passing result.

These are useful benchmark controls, but neither is an automated intelligent troubleshooting agent.

## Goals

- Add `agents/langchain-react-agent/` as a third CLI-compatible agent.
- Use LangChain's built-in ReAct/tool agent abstraction, not a custom ReAct loop.
- Call DeepSeek through an OpenAI-compatible API.
- Read model configuration from environment variables.
- Give the agent strong tool permissions through an unrestricted shell tool.
- Preserve the existing OpsBench CLI agent protocol.
- Keep `noop-agent` and `oracle-agent` as deterministic baselines.
- Ensure the agent never receives hidden labels or oracle SQL paths from the runner.

## Non-Goals

- Do not replace `oracle-agent`; it remains the stable success smoke test.
- Do not require an API key for unit tests.
- Do not guarantee that the LLM agent always passes the benchmark; its behavior depends on the model, prompt, and runtime.
- Do not sandbox shell commands in the first implementation. Strong permissions are an explicit requirement for this agent.

## Environment Configuration

The agent reads:

```text
DEEPSEEK_API_KEY       required
DEEPSEEK_BASE_URL      optional, default: https://api.deepseek.com
DEEPSEEK_MODEL         optional, default: deepseek-v4-pro
LANGCHAIN_MAX_STEPS    optional, default: 12
LANGCHAIN_TEMPERATURE  optional, default: 0
```

`DEEPSEEK_API_KEY` must be present before the agent starts. If it is missing, the agent exits non-zero with a clear error written to `trace.md`.

## Files

```text
agents/langchain-react-agent/
  run.sh
  agent.py
  tools.py
  prompts.py
  requirements.txt
```

`run.sh` parses the existing OpsBench CLI agent arguments and invokes `agent.py`.

`agent.py` builds the LangChain model and agent, loads the generated task, runs the agent, writes `trace.md`, and writes `final.json`.

`tools.py` defines the strong-permission tools exposed to LangChain.

`prompts.py` defines the system instructions and task template.

`requirements.txt` declares `langchain` and `langchain-openai`.

## LangChain Agent Shape

Use LangChain's packaged agent constructor. The implementation should prefer the current `langchain.agents.create_agent` API. If the installed LangChain version in the user's environment requires the legacy ReAct helper, the implementation can adapt inside `agent.py`, but it must keep the public behavior and tests the same.

Model construction:

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    temperature=float(os.environ.get("LANGCHAIN_TEMPERATURE", "0")),
)
```

The agent is initialized with:

- The DeepSeek-backed `ChatOpenAI` model.
- The tool list from `tools.py`.
- A system prompt that instructs it to diagnose and repair the public task without using hidden metadata.

## Strong-Permission Tools

Expose these tools to the LangChain agent:

### `shell(command: str) -> str`

Runs an arbitrary shell command.

Execution context:

- `cwd`: the case directory by default.
- Environment includes the runner-provided OpsBench variables.
- Command timeout is bounded per invocation.
- stdout/stderr are captured.
- Tool output is truncated for the model, while full logs are written to the trace directory.

This is intentionally powerful. It lets the model run `docker compose`, `psql`, inspect files, edit files, restart services, and invoke the verifier.

### `read_file(path: str) -> str`

Reads a text file from the case directory or work directory. It rejects paths that resolve outside those two roots.

### `write_file(path: str, content: str) -> str`

Writes a text file under the work directory or case directory. It rejects paths that resolve outside those two roots.

### `run_verifier() -> str`

Runs `OPSBENCH_VERIFY_CMD` and returns the verifier output. This lets the model test its repair before exiting.

## Prompt Contract

The system prompt tells the agent:

- It is operating inside an OpsBench fault scenario.
- It sees only public task context.
- Hidden labels and oracle fixes are not available and must not be searched for.
- It may use the shell tool freely to inspect and repair the environment.
- It should run the verifier before finalizing when possible.
- It should summarize the root cause, repair, and verification result.

The user prompt includes:

- Contents of generated `task.md`.
- Case directory.
- Work directory.
- Verify command.
- Available tools.

## Trace And Outputs

The agent writes:

```text
$OPSBENCH_TRACE_DIR/trace.md
$OPSBENCH_TRACE_DIR/final.json
$OPSBENCH_TRACE_DIR/tool-*.log
```

`trace.md` contains high-level run metadata, model configuration without the API key, and the final response. Full tool command logs are written separately.

`final.json` contains:

```json
{
  "agent": "langchain-react-agent",
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com",
  "status": "completed",
  "final_response": "...",
  "verifier_called": true
}
```

## Testing Strategy

Unit tests should not call DeepSeek or require LangChain to be installed globally unless the agent package dependencies are installed. The implementation should include tests that:

- Verify `run.sh` passes CLI arguments to `agent.py`.
- Verify environment parsing fails clearly when `DEEPSEEK_API_KEY` is missing.
- Verify tool path guards for `read_file` and `write_file`.
- Verify shell tool captures stdout, stderr, return code, and writes a log.
- Verify prompt construction includes task content and excludes hidden labels.

Optional integration smoke:

```bash
DEEPSEEK_API_KEY=... python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

This smoke is documented but not required for automated local tests because it depends on model credentials and network access.

## References

- LangChain Python agents documentation: `https://docs.langchain.com/oss/python/langchain/agents`
- LangChain ChatOpenAI integration documentation: `https://docs.langchain.com/oss/python/integrations/chat/openai`
- DeepSeek API documentation: `https://api-docs.deepseek.com/`
