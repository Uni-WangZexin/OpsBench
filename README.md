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
cases/otel-k8s-tci*/              # TCI038-TCI092 Kubernetes incident cases
cases/_kubernetes_otel/           # Shared OpenTelemetry Demo lifecycle scripts
agents/langchain-react-agent/     # LangChain ReAct/tool agent wrapper
results/runs.jsonl                # Generated run records
results/traces/                   # Generated phase and agent traces
```

## Commands

Validate the demo case:

```bash
python3 -m opsbench.cli validate --case cases/postgres-missing-index-001
```

Run the LangChain ReAct agent:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
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

`agents/langchain-react-agent/run.sh` is a real model-backed agent. It runs inside the `agent-runner` container, adapts the case's benchmark-owned tool standard to LangChain, and calls DeepSeek through an OpenAI-compatible endpoint.

Install the optional agent dependencies:

```bash
python3 -m pip install -r agents/langchain-react-agent/requirements.txt
```

Configure the model:

```bash
export DEEPSEEK_API_KEY=...
export DEEPSEEK_MODEL=deepseek-v4-pro
export DEEPSEEK_BASE_URL=https://api.deepseek.com
export LANGCHAIN_MAX_STEPS=30
```

Run it through the same OpsBench protocol:

```bash
python3 -m opsbench.cli run \
  --case cases/postgres-missing-index-001 \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

The agent process runs in the `agent-runner` container. Its tools therefore execute in that container and can reach only the runtime resources exposed to it. Its pass/fail result depends on model behavior and network/API availability.

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
OPSBENCH_AGENT_CONTAINER
OPSBENCH_COMPOSE_PROJECT
OPSBENCH_SHELL_SERVICE
OPSBENCH_TRACE_DIR
```

With Docker enabled, the runner launches agents through `docker compose run --rm --build agent-runner ...`. Agent actions execute inside that container and reach case services only through the container environment and Compose network. The runner performs injection, scoring, and final verification outside the agent after it exits.

## Standard Tool Contract

Every ranked agent receives the same benchmark-owned tool surface:

- `shell(command)` runs a command inside the agent container and returns its exit code, stdout, and stderr.

Agent frameworks and reasoning-loop designs may differ, but their adapters must expose exactly this tool contract. Database diagnosis and repair use command-line clients available in the container, for example `psql -h db -U opsbench -d opsbench`. File reader/writer tools and verifier tools are not part of the contract.

The verifier is bench infrastructure, not an agent action. Agents do not receive its command or output; OpsBench runs it once after the agent process finishes.

## Kubernetes OpenTelemetry Cases

The repository includes 55 Kubernetes cases generated from `故障.md`, covering
TCI038 through TCI092. Every fault has its own `cases/otel-k8s-tci*/` directory.
Each generated directory is self-contained and follows the same case layout:

```text
manifest.yaml
docker-compose.yaml
task.md
scripts/{common,setup,inject,check_injected,verify,cleanup}.py
hidden/{labels.yaml,scenario.json}
```

`cases/_kubernetes_otel/` is only the canonical generation source; runtime
manifests do not reference files outside their own case directory.
All cases use the baseline from `基准环境.md`:

- Kubernetes 1.24 or newer.
- At least 6 GiB of available application memory.
- OpenTelemetry Demo installed from
  `open-telemetry/opentelemetry-demo` with Helm Chart 0.11.0 by default.
- A dedicated namespace for each run, followed by automatic cleanup.

Huawei Cloud-specific concepts such as CCE node state, EVS, OBS, security
groups, ACLs, ELB, and EIP are represented as namespace-scoped Kubernetes
resources, labels, observations, and Events. This preserves the diagnostic
state transition without modifying real cloud resources or cluster nodes.

The Kubernetes cases use the uniform `kubernetes-observability-v1` standard.
Every competing agent receives the same benchmark-owned tools for every
Kubernetes case:

- `shell`: inspect and repair resources with the installed command-line clients.
- `kubectl_logs`: read current or previous Pod logs in the case namespace.
- `list_metrics`: discover Prometheus metric names with optional filtering.
- `query_metrics`: run instant PromQL queries against Demo Prometheus.
- `search_traces` and `get_trace`: search and retrieve traces from Jaeger.
- `query_logs`: search the Demo OpenSearch log backend.

The observability tools discover Services in the current namespace and use the
Kubernetes API Service Proxy. They are read-only and do not expose arbitrary
network destinations. Scenario-appropriate clients are also installed in the
agent container and declared per case:

- Workload, node, scheduling, storage: `kubectl`, `helm`, `jq`.
- Network and ingress: `kubectl`, `helm`, `curl`, `jq`.
- DNS: `kubectl`, `helm`, `dig`, `nslookup`, `jq`.

During setup, the runner creates a short-lived ServiceAccount and namespace-only
Role for the run. Only that restricted kubeconfig is mounted read-only into the
isolated agent container; the host/admin kubeconfig, case directory, generated
work directory, and hidden benchmark controls are not mounted.

This tool surface follows the official
[OpenTelemetry Demo Helm deployment](https://opentelemetry.io/docs/platforms/kubernetes/helm/demo/)
and its Prometheus, Jaeger, and OpenSearch backends.

Run a case with an existing cluster context:

```bash
python3 -m opsbench.cli run \
  --case cases/otel-k8s-tci061-image-reference \
  --agent agents/langchain-react-agent/run.sh \
  --results-dir results
```

Useful environment overrides:

```text
KUBECONFIG
OPSBENCH_OTEL_CHART_VERSION
OPSBENCH_OTEL_SKIP_INSTALL
```

`OPSBENCH_OTEL_SKIP_INSTALL=1` is intended only for development against a
namespace where the baseline application lifecycle is managed separately.
Regenerate the case directories after editing `故障.md` or the scenario catalog:

```bash
python3 tools/generate_kubernetes_cases.py
```

## Case Notes

`postgres-missing-index-001` starts from a healthy PostgreSQL database with an index on `orders.customer_id`. The injection script drops that index. The verifier checks that the workload still returns data and that PostgreSQL execution time for the target order-history query is below the configured thresholds.
