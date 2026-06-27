# OpsBench Database Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved SWE-bench-like OpsBench database demo with a self-contained PostgreSQL missing-index case, CLI runner, result recording, leaderboard, and two CLI agents.

**Architecture:** Use a small Python standard-library CLI as the harness. Case packages provide JSON-compatible `manifest.yaml` metadata, Docker Compose environment files, Python injection/check/verify scripts, hidden labels, and oracle SQL. Agents are ordinary executables invoked through the CLI protocol.

**Tech Stack:** Python 3 standard library, `unittest`, Bash, Docker Compose, PostgreSQL official image.

---

### Task 1: Core Case And Result Model

**Files:**
- Create: `tests/test_cases.py`
- Create: `tests/test_results.py`
- Create: `opsbench/__init__.py`
- Create: `opsbench/cases.py`
- Create: `opsbench/results.py`
- Create: `opsbench/leaderboard.py`

- [ ] **Step 1: Write failing tests for case loading**

Create `tests/test_cases.py` with tests that write a temporary JSON-compatible `manifest.yaml`, load it through `load_case`, and assert resolved paths, public fields, scripts, and hidden metadata.

- [ ] **Step 2: Run case tests and verify RED**

Run: `python3 -m unittest tests.test_cases -v`
Expected: fails because `opsbench.cases` does not exist.

- [ ] **Step 3: Implement case loading**

Create `opsbench/cases.py` with `Case` dataclass and `load_case(path)` that parses JSON-compatible YAML with `json.loads`, validates required keys, and resolves relative paths against the case directory.

- [ ] **Step 4: Run case tests and verify GREEN**

Run: `python3 -m unittest tests.test_cases -v`
Expected: passes.

- [ ] **Step 5: Write failing tests for results and leaderboard aggregation**

Create `tests/test_results.py` with tests for appending JSONL result records, reading them back, and aggregating per-agent pass rate, run count, and average duration.

- [ ] **Step 6: Run result tests and verify RED**

Run: `python3 -m unittest tests.test_results -v`
Expected: fails because `opsbench.results` and `opsbench.leaderboard` are incomplete.

- [ ] **Step 7: Implement result storage and aggregation**

Create `opsbench/results.py` with `append_run(path, record)` and `load_runs(path)`. Create `opsbench/leaderboard.py` with `summarize_runs(runs)` and `format_leaderboard(summary)`.

- [ ] **Step 8: Run result tests and verify GREEN**

Run: `python3 -m unittest tests.test_cases tests.test_results -v`
Expected: passes.

- [ ] **Step 9: Commit**

Run:

```bash
git add opsbench tests docs/superpowers/plans/2026-06-28-opsbench-db-demo-implementation.md
git commit -m "feat: add OpsBench core models"
```

### Task 2: Runner And CLI Lifecycle

**Files:**
- Create: `tests/test_runner.py`
- Create: `opsbench/runner.py`
- Create: `opsbench/cli.py`
- Create: `opsbench/__main__.py`
- Create: `bin/opsbench`

- [ ] **Step 1: Write failing runner tests**

Create `tests/test_runner.py` with a temporary local case package whose inject/check/verify scripts emit JSON and whose fake agent writes a trace. Run the runner with `use_docker=False` and assert lifecycle phases, generated task file, verification result, hidden labels in the recorded JSONL, and trace directory creation.

- [ ] **Step 2: Run runner tests and verify RED**

Run: `python3 -m unittest tests.test_runner -v`
Expected: fails because `opsbench.runner` does not exist.

- [ ] **Step 3: Implement runner**

Create `opsbench/runner.py` with `OpsBenchRunner.run(case_dir, agent_path, results_dir, timeout_sec, use_docker=True)`. It loads the case, starts Docker Compose when enabled, runs inject/check/agent/verify, records logs and result JSONL, writes `task.md` and a generated `verify.sh`, includes hidden labels in result records, and cleans up Docker Compose when enabled.

- [ ] **Step 4: Implement CLI**

Create `opsbench/cli.py` with `run` and `leaderboard` subcommands. Create `opsbench/__main__.py` and `bin/opsbench` wrappers.

- [ ] **Step 5: Run runner tests and verify GREEN**

Run: `python3 -m unittest tests.test_cases tests.test_results tests.test_runner -v`
Expected: passes.

- [ ] **Step 6: Commit**

Run:

```bash
git add opsbench tests bin
git commit -m "feat: add OpsBench runner CLI"
```

### Task 3: PostgreSQL Missing-Index Case Package

**Files:**
- Create: `cases/postgres-missing-index-001/manifest.yaml`
- Create: `cases/postgres-missing-index-001/docker-compose.yaml`
- Create: `cases/postgres-missing-index-001/task.md`
- Create: `cases/postgres-missing-index-001/db/schema.sql`
- Create: `cases/postgres-missing-index-001/db/seed.sql`
- Create: `cases/postgres-missing-index-001/scripts/common.py`
- Create: `cases/postgres-missing-index-001/scripts/inject.py`
- Create: `cases/postgres-missing-index-001/scripts/check_injected.py`
- Create: `cases/postgres-missing-index-001/scripts/verify.py`
- Create: `cases/postgres-missing-index-001/hidden/labels.yaml`
- Create: `cases/postgres-missing-index-001/hidden/oracle_fix.sql`

- [ ] **Step 1: Add case package files**

Create a PostgreSQL Compose environment with a single `db` service. Initialize an `orders` table with deterministic generated data and a healthy `idx_orders_customer_id` index. The injection script drops that index. The injection check confirms the index is absent. The verifier measures PostgreSQL `EXPLAIN (ANALYZE, FORMAT JSON)` execution time for the target workload and checks thresholds from the manifest.

- [ ] **Step 2: Validate manifest through the existing testable loader**

Run: `python3 -m opsbench.cli validate --case cases/postgres-missing-index-001`
Expected: prints the case id and exits `0`.

- [ ] **Step 3: Commit**

Run:

```bash
git add cases
git commit -m "feat: add PostgreSQL missing index case"
```

### Task 4: Built-In CLI Agents

**Files:**
- Create: `agents/noop-agent/run.sh`
- Create: `agents/oracle-agent/run.sh`

- [ ] **Step 1: Add `noop-agent`**

Create a Bash executable that parses runner arguments, writes `trace.md` under `OPSBENCH_TRACE_DIR`, records that no repair was attempted, and exits `0`.

- [ ] **Step 2: Add `oracle-agent`**

Create a Bash executable that writes a minimal ReAct-style trace, applies `hidden/oracle_fix.sql` through Docker Compose, optionally runs `OPSBENCH_VERIFY_CMD`, and exits `0`.

- [ ] **Step 3: Commit**

Run:

```bash
git add agents
git commit -m "feat: add built-in OpsBench agents"
```

### Task 5: Documentation And Verification

**Files:**
- Create: `README.md`

- [ ] **Step 1: Add README**

Document the goal, repository layout, commands for `noop-agent`, `oracle-agent`, leaderboard usage, and how third-party agents integrate through the CLI protocol.

- [ ] **Step 2: Run unit tests**

Run: `python3 -m unittest discover -v`
Expected: all tests pass.

- [ ] **Step 3: Run Docker smoke tests**

Run:

```bash
python3 -m opsbench.cli run --case cases/postgres-missing-index-001 --agent agents/noop-agent/run.sh --results-dir results
python3 -m opsbench.cli run --case cases/postgres-missing-index-001 --agent agents/oracle-agent/run.sh --results-dir results
python3 -m opsbench.cli leaderboard --results results/runs.jsonl
```

Expected: `noop-agent` records `verification_passed=false`, `oracle-agent` records `verification_passed=true`, and leaderboard shows both agents.

- [ ] **Step 4: Commit**

Run:

```bash
git add README.md results/runs.jsonl
git commit -m "docs: add OpsBench demo usage"
```

## Self-Review

- Spec coverage: tasks cover the CLI runner, task package contract, hidden labels, built-in agents, verifier, results JSONL, leaderboard, and documentation.
- Placeholder scan: no unresolved planning markers remain.
- Type consistency: case ids, manifest fields, result keys, and CLI names match the approved design spec.
