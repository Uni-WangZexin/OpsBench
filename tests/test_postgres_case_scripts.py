import importlib.util
import subprocess
import unittest
from pathlib import Path


def _load_case_common():
    root = Path(__file__).resolve().parents[1]
    common_path = root / "cases" / "postgres-missing-index-001" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("postgres_missing_index_common", common_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class PostgresCaseScriptTests(unittest.TestCase):
    def test_wait_for_db_requires_stable_successes(self):
        common = _load_case_common()
        calls = []
        results = iter(
            [
                subprocess.CompletedProcess([], 0, "1\n", ""),
                subprocess.CompletedProcess([], 1, "", "database system is shutting down"),
                subprocess.CompletedProcess([], 0, "1\n", ""),
                subprocess.CompletedProcess([], 0, "1\n", ""),
            ]
        )

        def fake_psql(case_dir, sql, timeout=120):
            calls.append(sql)
            return next(results)

        common.psql = fake_psql
        common.time.sleep = lambda _: None

        common.wait_for_db(Path("/case"), timeout=5)

        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()
