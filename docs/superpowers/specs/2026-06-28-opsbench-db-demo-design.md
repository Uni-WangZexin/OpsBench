# OpsBench Database Demo Design

## Summary

Build a SWE-bench-like OpsBench demo for operations tasks. The first task package targets a PostgreSQL slow-query incident caused by a missing index. Each fault scenario is self-contained, reproducible through Docker Compose, and evaluated by a verifier after an external CLI agent attempts repair.

The demo prioritizes dataset/task-package shape over platform UI. Agents interact through a command-line protocol. Hidden fault labels are recorded for analysis and leaderboard slicing, but are never shown to the agent.

## Goals

- Provide one complete database fault package: `postgres-missing-index-001`.
- Model each scenario as an isolated case directory with manifest, environment, injection, injection check, public task text, hidden labels, oracle fix, and verifier.
- Run the lifecycle: start environment, inject fault, confirm fault, run agent, verify repair, record result, generate leaderboard data.
- Include two built-in CLI agents:
  - `noop-agent`: does no repair and demonstrates the failure path.
  - `oracle-agent`: follows a minimal ReAct-style trace and applies the hidden oracle fix to demonstrate the success path.
- Keep the interface extensible for user-defined agents, different models, and future non-database domains.

## Non-Goals

- No frontend React application in the first demo. "ReAct" refers to the reasoning/action agent pattern.
- No production-grade scheduler, distributed execution service, or hosted leaderboard.
- No LLM API integration in the first pass. A future `llm-react-agent` can reuse the same CLI contract.
- No attempt to prevent malicious agents. The demo assumes local trusted evaluation.

## Repository Shape

```text
opsbench-demo/
  opsbench/
    cli.py
    runner.py
    cases.py
    results.py
    leaderboard.py
  cases/
    postgres-missing-index-001/
      manifest.yaml
      docker-compose.yaml
      task.md
      app/
      db/
        schema.sql
        seed.sql
      scripts/
        inject.py
        check_injected.py
        verify.py
      hidden/
        labels.yaml
        oracle_fix.sql
  agents/
    noop-agent/
      run.sh
    oracle-agent/
      run.sh
  results/
    runs.jsonl
    traces/
  docs/
    superpowers/specs/
```

## Case Package Contract

Each case package owns all files needed to reproduce and verify one fault.

`manifest.yaml` defines:

- `id`: stable case id, such as `postgres-missing-index-001`.
- `domain`: public coarse domain, such as `database`.
- `environment`: Docker Compose file, services, exposed ports, health checks, and resource hints.
- `scripts`: relative paths for `inject`, `check_injected`, and `verify`.
- `task`: public task description path.
- `agent_context`: connection details and allowed command hints.
- `hidden_metadata`: path to labels used only by runner results and leaderboard analysis.

`task.md` is agent-visible. It describes symptoms, service endpoints, database connection details, available commands, success criteria, and the final verify command. It does not reveal the root cause or hidden label.

`hidden/labels.yaml` is not passed to agents. It records labels such as:

```yaml
domain: database
system: postgresql
fault_type: performance.missing_index
symptom: slow_query
root_cause: missing_index_on_orders_customer_id
expected_fix_type: schema_index
```

## Demo Fault Story

The demo service exposes an order-history API backed by PostgreSQL. The workload queries historical orders by `customer_id`. The injected incident makes the query path slow because the expected index on `orders.customer_id` is missing.

The agent only sees that the API is too slow under the expected workload. It may inspect logs, run SQL, execute `EXPLAIN`, edit application code, change database configuration, create indexes, and restart services. The verifier judges the final state by behavior rather than checking for one hard-coded patch.

## Runner Lifecycle

Primary command:

```bash
opsbench run --case cases/postgres-missing-index-001 --agent agents/oracle-agent/run.sh
```

Lifecycle:

```text
1. start          Build and start the case environment.
2. inject         Run the case injection script.
3. check-injected Confirm the fault is active.
4. agent          Invoke the configured CLI agent with public context.
5. verify         Run the case verifier after the agent exits.
6. record         Store result JSONL and trace artifacts.
7. leaderboard    Summarize results across runs.
```

The runner creates an isolated runtime directory per run. It copies or references the case package, writes generated public task context, captures stdout/stderr for every phase, and always attempts cleanup after the run.

## CLI Agent Protocol

Agents are normal executables. The runner invokes:

```bash
agent/run.sh \
  --case-dir /abs/path/to/case \
  --task /abs/path/to/generated/task.md \
  --work-dir /abs/path/to/runtime/workspace \
  --timeout-sec 300
```

Environment variables:

```text
OPSBENCH_CASE_ID
OPSBENCH_RUN_ID
OPSBENCH_COMPOSE_PROJECT
OPSBENCH_TRACE_DIR
OPSBENCH_VERIFY_CMD
```

Exit code semantics:

- `0`: agent completed its attempt. The verifier still decides pass or fail.
- Non-zero: agent execution failed. The runner still records logs and may run verify when the environment is healthy enough.

## Built-In Agents

`noop-agent` writes a short trace saying it performed no action and exits `0`. It should fail final verification.

`oracle-agent` exists to prove the harness can produce a successful result. It writes a minimal ReAct-style trace:

```text
Thought: inspect the symptom and determine likely database performance issue.
Action: run the oracle repair SQL for this benchmark control agent.
Observation: index creation completed.
Thought: verify that the benchmark now passes.
Action: run final verifier command.
```

The oracle agent may read `hidden/oracle_fix.sql`. Third-party agents and future LLM agents do not receive this path.

## Verifier Design

The verifier checks both correctness and performance.

Correctness checks:

- API endpoint returns expected order data for known customers.
- Database remains reachable.
- The service remains healthy after repair.

Performance checks:

- Warm up the API.
- Run a fixed number of order-history requests.
- Assert average latency and p95 latency fall below manifest-defined thresholds.
- Record the query plan as diagnostic evidence, but do not make a specific plan shape the only passing repair.

The verifier returns structured JSON with:

```json
{
  "passed": true,
  "checks": [
    {"name": "api_correctness", "passed": true},
    {"name": "latency_average_ms", "passed": true, "value": 24.2, "threshold": 100},
    {"name": "latency_p95_ms", "passed": true, "value": 45.8, "threshold": 200}
  ]
}
```

## Result Schema

Each run appends one line to `results/runs.jsonl`:

```json
{
  "run_id": "20260628T010203Z-postgres-missing-index-001-oracle-agent",
  "case_id": "postgres-missing-index-001",
  "agent": "oracle-agent",
  "started_at": "2026-06-28T01:02:03Z",
  "duration_sec": 42.1,
  "injection_passed": true,
  "verification_passed": true,
  "score": 1.0,
  "hidden_labels": {
    "domain": "database",
    "system": "postgresql",
    "fault_type": "performance.missing_index"
  },
  "trace_dir": "results/traces/20260628T010203Z-postgres-missing-index-001-oracle-agent"
}
```

The leaderboard command reads this file and reports pass rate, average duration, and per-label slices. A static HTML export can be added later from the same data, but the first demo only requires CLI output.

## Extensibility

New cases add another directory under `cases/` and follow the same manifest/script contract. New domains such as network, Linux host, Kubernetes, or cache incidents can reuse the runner as long as they provide start, inject, check, verify, and public task context.

New agents only need to implement the CLI protocol. Model-specific wrappers can translate the generated `task.md` into prompts and map tool calls back to shell commands.

## Testing Plan

- Unit-test manifest loading and validation.
- Unit-test result JSONL writing and leaderboard aggregation.
- Smoke-test `noop-agent`: injection succeeds, final verification fails, result is recorded.
- Smoke-test `oracle-agent`: injection succeeds, repair succeeds, final verification passes, result is recorded.
- Manually inspect trace files for both agents to ensure public and hidden data boundaries are respected.

## Open Decisions Resolved

- First scenario: PostgreSQL slow query caused by missing index.
- Agent permission: agent may modify the whole environment.
- Agent interface: command-line protocol.
- Fault labels: hidden from agents; used only for metadata, analysis, and leaderboard slicing.
- Built-in agents: include `noop-agent` and minimal ReAct-style `oracle-agent`.
- UI: no frontend React app in the first version.
