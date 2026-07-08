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

    def test_postgres_case_initialization_creates_missing_index_once(self):
        root = Path(__file__).resolve().parents[1]
        db_dir = root / "cases" / "postgres-missing-index-001" / "db"
        init_sql = "\n".join(
            [
                (db_dir / "schema.sql").read_text(encoding="utf-8"),
                (db_dir / "seed.sql").read_text(encoding="utf-8"),
            ]
        ).upper()

        self.assertEqual(init_sql.count("IDX_ORDERS_CUSTOMER_ID"), 1)


if __name__ == "__main__":
    unittest.main()
