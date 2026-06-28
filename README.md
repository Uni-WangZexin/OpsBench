# OpsBench Database Demo

This repository is a compact SWE-bench-like demo for operations incidents. The first case package, `postgres-missing-index-001`, reproduces a PostgreSQL slow-query incident caused by a missing index.

The benchmark shape is intentionally case-package first:

- Each incident lives under `cases/<case-id>/`.
- A runner starts the environment, injects the fault, checks injection, runs a CLI agent, verifies the final state, and records a result.
- Hidden labels are stored for leaderboard slicing and are not passed to agents.
- Agents are normal executables, so ReAct-style, model-backed, or custom scripts can all use the same protocol.

## Layout

```text
opsbench/                         # Python CLI and harness
cases/postgres-missing-index-001/ # Self-contained PostgreSQL case package
agents/noop-agent/run.sh          # Failure baseline
agents/oracle-agent/run.sh        # Minimal ReAct-style success baseline
agents/langchain-react-agent/     # LangChain ReAct/tool agent wrapper
results/runs.jsonl                # Generated run records
results/traces/                   # Generated phase and agent traces
```

## Commands

Validate the demo case:

```bash
python3 -m opsbench.cli validate --case cases/postgres-missing-index-001
```

Run the failure baseline:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/noop-agent/run.sh \
  --results-dir results
```

Run the oracle baseline:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/oracle-agent/run.sh \
  --results-dir results
```

Show the leaderboard:

```bash
python3 -m opsbench.cli leaderboard --results results/runs.jsonl
```

Run unit tests:

```bash
python3 -m unittest discover -v
```

## LangChain ReAct Agent

`agents/langchain-react-agent/run.sh` is a real model-backed agent. It uses LangChain's packaged agent API with strong shell tools and calls DeepSeek through an OpenAI-compatible endpoint.

Install the optional agent dependencies:

```bash
python3 -m pip install -r agents/langchain-react-agent/requirements.txt
```

Configure the model:

```bash
export DEEPSEEK_API_KEY=...
export DEEPSEEK_MODEL=deepseek-v4-pro
export DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Run it through the same OpsBench protocol:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

This agent has a strong `shell` tool and can run arbitrary commands in the case environment. Its pass/fail result depends on model behavior and network/API availability, so `oracle-agent` remains the deterministic success baseline for smoke testing.

## Agent Protocol

The runner invokes agents as:

```bash
agent/run.sh \
  --case-dir /abs/path/to/case \
  --task /abs/path/to/generated/task.md \
  --work-dir /abs/path/to/runtime/workspace \
  --timeout-sec 300
```

Useful environment variables:

```text
OPSBENCH_CASE_ID
OPSBENCH_RUN_ID
OPSBENCH_COMPOSE_PROJECT
OPSBENCH_TRACE_DIR
OPSBENCH_VERIFY_CMD
```

Agents can inspect logs, run `docker compose`, execute SQL, edit files, restart services, and write traces under `OPSBENCH_TRACE_DIR`. The final score always comes from the case verifier.

## Case Notes

`postgres-missing-index-001` starts from a healthy PostgreSQL database with an index on `orders.customer_id`. The injection script drops that index. The verifier checks that the workload still returns data and that PostgreSQL execution time for the target order-history query is below the configured thresholds.

`noop-agent` records a trace and makes no repair. `oracle-agent` writes a minimal ReAct-style trace and applies `hidden/oracle_fix.sql`, which recreates the expected index. Third-party agents do not receive hidden paths.
