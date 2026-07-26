import json
import tempfile
import unittest
from pathlib import Path

from opsbench.cases import CaseManifestError, load_case


class LoadCaseTests(unittest.TestCase):
    def test_loads_json_compatible_manifest_and_resolves_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "cases" / "postgres-missing-index-001"
            case_dir.mkdir(parents=True)
            (case_dir / "manifest.yaml").write_text(
                json.dumps(
                    {
                        "id": "postgres-missing-index-001",
                        "domain": "database",
                        "environment": {
                            "compose_file": "docker-compose.yaml",
                            "services": ["db"],
                        },
                        "scripts": {
                            "inject": "scripts/inject.py",
                            "check_injected": "scripts/check_injected.py",
                            "verify": "scripts/verify.py",
                        },
                        "task": "task.md",
                        "hidden_metadata": "hidden/labels.yaml",
                        "tool_standard": {
                            "id": "postgres-ops-v1",
                            "tools": ["shell"],
                            "commands": ["psql"],
                        },
                        "timeouts": {"agent_sec": 123},
                    }
                ),
                encoding="utf-8",
            )

            case = load_case(case_dir)

            self.assertEqual(case.id, "postgres-missing-index-001")
            self.assertEqual(case.domain, "database")
            self.assertEqual(case.case_dir, case_dir.resolve())
            self.assertEqual(case.compose_file, case_dir.resolve() / "docker-compose.yaml")
            self.assertEqual(case.scripts["inject"], case_dir.resolve() / "scripts/inject.py")
            self.assertEqual(
                case.scripts["check_injected"],
                case_dir.resolve() / "scripts/check_injected.py",
            )
            self.assertEqual(case.scripts["verify"], case_dir.resolve() / "scripts/verify.py")
            self.assertEqual(case.task_file, case_dir.resolve() / "task.md")
            self.assertEqual(case.hidden_metadata, case_dir.resolve() / "hidden/labels.yaml")
            self.assertEqual(case.agent_timeout_sec, 123)
            self.assertEqual(case.environment_type, "compose")
            self.assertEqual(case.tool_standard["tools"], ["shell"])

    def test_all_generated_kubernetes_cases_load_with_uniform_tool_contract(self):
        root = Path(__file__).resolve().parents[1]
        case_dirs = sorted((root / "cases").glob("otel-k8s-tci*"))

        self.assertEqual(len(case_dirs), 55)
        loaded = [load_case(case_dir) for case_dir in case_dirs]

        self.assertEqual({case.environment_type for case in loaded}, {"kubernetes"})
        self.assertEqual(
            {case.tool_standard["id"] for case in loaded},
            {"kubernetes-observability-v1"},
        )
        expected_tools = [
            "shell",
            "kubectl_logs",
            "list_metrics",
            "query_metrics",
            "search_traces",
            "get_trace",
            "query_logs",
        ]
        self.assertTrue(
            all(case.tool_standard["tools"] == expected_tools for case in loaded)
        )
        self.assertTrue(
            all(case.compose_file == case.case_dir / "docker-compose.yaml" for case in loaded)
        )
        self.assertTrue(
            all(
                all(path.is_relative_to(case.case_dir) for path in case.scripts.values())
                for case in loaded
            )
        )
        expected_structure = {
            "docker-compose.yaml",
            "otel-values.yaml",
            "manifest.yaml",
            "task.md",
            "hidden/labels.yaml",
            "hidden/scenario.json",
            "scripts/common.py",
            "scripts/faults.py",
            "scripts/setup.py",
            "scripts/inject.py",
            "scripts/check_injected.py",
            "scripts/verify.py",
            "scripts/cleanup.py",
        }
        self.assertTrue(
            all(
                expected_structure.issubset(
                    {
                        str(path.relative_to(case.case_dir))
                        for path in case.case_dir.rglob("*")
                        if path.is_file()
                    }
                )
                for case in loaded
            )
        )
        self.assertEqual(
            {case.raw_manifest["environment"]["baseline"]["helm_chart"] for case in loaded},
            {"open-telemetry/opentelemetry-demo"},
        )

    def test_rejects_manifest_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "broken-case"
            case_dir.mkdir()
            (case_dir / "manifest.yaml").write_text(
                json.dumps({"id": "broken-case"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(CaseManifestError, "domain"):
                load_case(case_dir)

    def test_rejects_references_outside_the_case_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / "case"
            case_dir.mkdir()
            manifest = {
                "id": "external-reference",
                "domain": "kubernetes",
                "environment": {
                    "type": "kubernetes",
                    "compose_file": "../shared/docker-compose.yaml",
                    "services": [],
                },
                "scripts": {
                    "inject": "scripts/inject.py",
                    "check_injected": "scripts/check_injected.py",
                    "verify": "scripts/verify.py",
                },
                "task": "task.md",
                "hidden_metadata": "hidden/labels.yaml",
                "tool_standard": {
                    "id": "kubernetes-observability-v1",
                    "tools": [
                        "shell",
                        "kubectl_logs",
                        "list_metrics",
                        "query_metrics",
                        "search_traces",
                        "get_trace",
                        "query_logs",
                    ],
                    "commands": ["kubectl"],
                },
            }
            (case_dir / "manifest.yaml").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            with self.assertRaisesRegex(CaseManifestError, "inside the case directory"):
                load_case(case_dir)

    def test_postgres_case_initialization_creates_missing_index_once(self):
        root = Path(__file__).resolve().parents[1]
        case = load_case(root / "cases" / "postgres-missing-index-001")
        self.assertEqual(case.tool_standard["id"], "postgres-operations-v2")
        self.assertEqual(
            case.tool_standard["tools"],
            ["shell", "inspect_database", "query_database", "explain_query"],
        )
        db_dir = root / "cases" / "postgres-missing-index-001" / "db"
        init_sql = "\n".join(
            [
                (db_dir / "schema.sql").read_text(encoding="utf-8"),
                (db_dir / "seed.sql").read_text(encoding="utf-8"),
            ]
        ).upper()

        self.assertEqual(init_sql.count("IDX_ORDERS_CUSTOMER_ID"), 1)

    def test_lightweight_container_cases_are_uniform_real_and_resource_bounded(self):
        root = Path(__file__).resolve().parents[1]
        expected_ids = {
            f"{name}-{number:03d}"
            for number, name in [
                (2, "linux-cpu-runaway"),
                (3, "linux-memory-growth"),
                (4, "linux-fd-exhaustion"),
                (5, "linux-disk-full"),
                (6, "linux-inode-exhaustion"),
                (7, "linux-upload-permission"),
                (8, "http-wrong-port"),
                (9, "http-loopback-bind"),
                (10, "app-malformed-config"),
                (11, "app-stale-pid"),
                (12, "http-dependency-dns"),
                (13, "http-dependency-port"),
                (14, "http-downstream-500"),
                (15, "http-downstream-json"),
                (16, "http-upstream-timeout"),
                (17, "app-feature-flag"),
                (18, "linux-file-lock"),
                (19, "linux-temp-permission"),
                (20, "tls-hostname-mismatch"),
                (21, "app-env-override"),
            ]
        }
        case_dirs = [root / "cases" / case_id for case_id in sorted(expected_ids)]
        loaded = [load_case(case_dir) for case_dir in case_dirs]

        self.assertTrue(all(case.case_dir.is_dir() for case in loaded))
        self.assertEqual({case.id for case in loaded}, expected_ids)
        self.assertEqual({case.environment_type for case in loaded}, {"compose"})
        self.assertEqual({tuple(case.services) for case in loaded}, {("target",)})
        self.assertEqual({case.agent_service for case in loaded}, {"target"})
        self.assertEqual(
            {case.tool_standard["id"] for case in loaded}, {"linux-operations-v2"}
        )
        expected_tools = [
            "shell",
            "read_logs",
            "inspect_processes",
            "inspect_sockets",
            "query_host_metrics",
            "inspect_filesystem",
            "probe_http",
            "inspect_file",
            "edit_file",
            "manage_service",
        ]
        self.assertTrue(
            all(case.tool_standard["tools"] == expected_tools for case in loaded)
        )

        strategies = set()
        difficulties = set()
        for case in loaded:
            files = {
                str(path.relative_to(case.case_dir))
                for path in case.case_dir.rglob("*")
                if path.is_file()
            }
            self.assertTrue(
                {
                    "Dockerfile",
                    "docker-compose.yaml",
                    "manifest.yaml",
                    "task.md",
                    "runtime/app.py",
                    "runtime/config-reconciler.py",
                    "runtime/dependencyctl.sh",
                    "scripts/faults.py",
                    "scripts/inject.py",
                    "scripts/check_injected.py",
                    "scripts/verify.py",
                    "hidden/labels.yaml",
                    "hidden/scenario.json",
                }.issubset(files)
            )
            compose = (case.case_dir / "docker-compose.yaml").read_text(encoding="utf-8")
            dockerfile = (case.case_dir / "Dockerfile").read_text(encoding="utf-8")
            task = case.task_file.read_text(encoding="utf-8")
            entrypoint = (case.case_dir / "runtime" / "entrypoint.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn("cpus: 1.00", compose)
            self.assertIn("mem_limit: 384m", compose)
            self.assertIn("pids_limit: 128", compose)
            self.assertIn("/var/cache/demo:size=8m", compose)
            self.assertNotIn("agent-runner", compose)
            self.assertNotIn("sshpass", compose)
            self.assertIn("${OPSBENCH_AGENT_SOURCE}:/agent:ro", compose)
            self.assertIn("${OPSBENCH_TASK_SOURCE}:/task/task.md:ro", compose)
            self.assertIn("${OPSBENCH_AGENT_TRACE_DIR}:/trace", compose)
            self.assertNotIn("${OPSBENCH_TRACE_DIR}:/trace", compose)
            self.assertNotIn("DEEPSEEK_API_KEY", compose)
            self.assertNotIn("OPENAI_API_KEY", compose)
            self.assertNotIn("hidden", compose)
            self.assertIn("compileall", dockerfile)
            self.assertIn("iptables", dockerfile)
            self.assertIn("config-reconciler.py", dockerfile)
            self.assertIn("rm \\", dockerfile)
            self.assertIn("rm -f /opt/opsbench/runtime/default-config.json", entrypoint)
            self.assertIn("/data/.stores/upload-primary", entrypoint)
            self.assertIn("/var/cache/demo/jobs", entrypoint)
            self.assertIn("catalog.internal", entrypoint)
            self.assertIn("config-reconciler.pyc", entrypoint)
            self.assertIn("ulimit -n 64", (case.case_dir / "runtime" / "appctl.sh").read_text(encoding="utf-8"))
            app_source = (case.case_dir / "runtime" / "app.py").read_text(
                encoding="utf-8"
            )
            fault_source = (case.case_dir / "scripts" / "faults.py").read_text(
                encoding="utf-8"
            )
            self.assertIn('self.path == "/report-template"', app_source)
            self.assertNotIn('self.path == "/fd-test"', app_source)
            self.assertIn('catalog != "ready"', app_source)
            self.assertIn("type(items) is not int", app_source)
            self.assertIn("CONFIG_OVERLAY_PATH", app_source)
            self.assertIn("def _workload_pids", fault_source)
            self.assertNotIn("def _worker_pid", fault_source)
            self.assertIn("/run/system-report.enabled", fault_source)
            self.assertIn("dependency_delay_ms <= 250", fault_source)
            self.assertIn("mode in {600, 640}", fault_source)
            self.assertIn("/run/report-worker.enabled", fault_source)
            self.assertIn("CONTROL_PLANE_CONFIG", fault_source)
            self.assertIn("APP_CONFIG_OVERLAY", fault_source)
            self.assertIn("_peer_block_rule_present", fault_source)
            self.assertIn("dependencyctl.sh", fault_source)
            self.assertNotIn("/etc/opsbench", task)
            self.assertNotIn("/var/log/demo", task)
            self.assertNotIn("appctl.sh", task)
            scenario = json.loads(
                (case.case_dir / "hidden" / "scenario.json").read_text(encoding="utf-8")
            )
            strategies.add(scenario["implementation"]["strategy"])
            labels = json.loads(case.hidden_metadata.read_text(encoding="utf-8"))
            difficulties.add(labels["difficulty"])

        self.assertEqual(len(strategies), 20)
        self.assertEqual(difficulties, {"low", "medium", "hard"})
        document = (root / "Lightweight容器故障说明.md").read_text(encoding="utf-8")
        self.assertTrue(all(case_id in document for case_id in expected_ids))

    def test_kubernetes_fault_injection_document_covers_all_generated_cases(self):
        root = Path(__file__).resolve().parents[1]
        document = (root / "Kubernetes故障注入说明.md").read_text(encoding="utf-8")
        case_dirs = sorted((root / "cases").glob("otel-k8s-tci*"))

        self.assertEqual(document.count("\n### TCI"), 55)
        self.assertTrue(all(case_dir.name in document for case_dir in case_dirs))
        self.assertIn("故障判定不再依赖状态 ConfigMap", document)
        self.assertIn("真实负载", document)

    def test_kubernetes_cases_use_live_fault_engine_not_state_markers(self):
        root = Path(__file__).resolve().parents[1]
        case_dirs = sorted((root / "cases").glob("otel-k8s-tci*"))
        strategies = set()

        for case_dir in case_dirs:
            scenario = json.loads(
                (case_dir / "hidden" / "scenario.json").read_text(encoding="utf-8")
            )
            strategies.add(scenario["implementation"]["strategy"])
            scripts = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (case_dir / "scripts").glob("*.py")
            )
            self.assertNotIn("patch_state", scripts)
            self.assertNotIn("state_value", scripts)
            self.assertNotIn("STATE_CONFIG_MAP", scripts)
            self.assertIn("inject_real_fault", scripts)
            self.assertIn("fault_is_repaired", scripts)

        self.assertEqual(
            strategies,
            {
                "config_probe",
                "deployment",
                "ingress",
                "network_policy",
                "node",
                "pending",
                "proxy",
                "pull_secret",
                "quota",
                "service",
                "stress",
                "workload_stress",
            },
        )

    def test_readme_documents_architecture_and_agent_boundary(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("## Project Architecture", readme)
        self.assertIn("### Case Execution Flow", readme)
        self.assertIn("### Isolation and Information Boundaries", readme)
        self.assertIn("Kubernetes故障注入说明.md", readme)


if __name__ == "__main__":
    unittest.main()
