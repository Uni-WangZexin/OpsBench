import tempfile
import unittest
from pathlib import Path

from opsbench.leaderboard import format_leaderboard, summarize_runs
from opsbench.results import append_run, load_runs


class ResultsTests(unittest.TestCase):
    def test_appends_and_loads_jsonl_run_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            results_file = Path(temp_dir) / "results" / "runs.jsonl"
            first = {
                "run_id": "run-1",
                "case_id": "postgres-missing-index-001",
                "agent": "agent-a",
                "duration_sec": 3.5,
                "verification_passed": False,
            }
            second = {
                "run_id": "run-2",
                "case_id": "postgres-missing-index-001",
                "agent": "agent-b",
                "duration_sec": 4.5,
                "verification_passed": True,
            }

            append_run(results_file, first)
            append_run(results_file, second)

            self.assertEqual(load_runs(results_file), [first, second])

    def test_summarizes_runs_by_model_and_agent(self):
        runs = [
            {
                "agent": "agent-a",
                "model": "model-1",
                "case_id": "case-1",
                "duration_sec": 5.0,
                "verification_passed": False,
            },
            {
                "agent": "agent-b",
                "model": "model-1",
                "case_id": "case-1",
                "duration_sec": 4.0,
                "verification_passed": True,
            },
            {
                "agent": "agent-b",
                "model": "model-1",
                "case_id": "case-2",
                "duration_sec": 6.0,
                "verification_passed": True,
            },
        ]

        summary = summarize_runs(runs)

        self.assertEqual(summary[("model-1", "agent-a")]["runs"], 1)
        self.assertEqual(summary[("model-1", "agent-a")]["passes"], 0)
        self.assertEqual(summary[("model-1", "agent-a")]["pass_rate"], 0.0)
        self.assertEqual(summary[("model-1", "agent-a")]["average_duration_sec"], 5.0)
        self.assertEqual(summary[("model-1", "agent-b")]["runs"], 2)
        self.assertEqual(summary[("model-1", "agent-b")]["passes"], 2)
        self.assertEqual(summary[("model-1", "agent-b")]["pass_rate"], 1.0)
        self.assertEqual(summary[("model-1", "agent-b")]["average_duration_sec"], 5.0)

    def test_summarizes_only_latest_attempt_per_model_agent_and_case(self):
        runs = [
            {
                "agent": "agent-a",
                "model": "model-1",
                "case_id": "case-1",
                "duration_sec": 9.0,
                "verification_passed": False,
            },
            {
                "agent": "agent-a",
                "model": "model-1",
                "case_id": "case-1",
                "duration_sec": 3.0,
                "verification_passed": True,
            },
        ]

        summary = summarize_runs(runs)

        self.assertEqual(summary[("model-1", "agent-a")]["runs"], 1)
        self.assertEqual(summary[("model-1", "agent-a")]["passes"], 1)
        self.assertEqual(
            summary[("model-1", "agent-a")]["average_duration_sec"], 3.0
        )

    def test_keeps_same_agent_and_case_separate_for_different_models(self):
        runs = [
            {
                "agent": "agent-a",
                "model": "model-1",
                "case_id": "case-1",
                "duration_sec": 3.0,
                "verification_passed": True,
            },
            {
                "agent": "agent-a",
                "model": "model-2",
                "case_id": "case-1",
                "duration_sec": 4.0,
                "verification_passed": False,
            },
        ]

        summary = summarize_runs(runs)

        self.assertEqual(summary[("model-1", "agent-a")]["passes"], 1)
        self.assertEqual(summary[("model-2", "agent-a")]["passes"], 0)

    def test_legacy_record_uses_raw_verifier_result_for_repair_credit(self):
        runs = [
            {
                "agent": "agent-a",
                "case_id": "case-1",
                "duration_sec": 3.0,
                "verification_passed": False,
                "verification": {"passed": True, "checks": []},
                "phases": {"agent": {"returncode": 1}},
            }
        ]

        summary = summarize_runs(runs)

        self.assertEqual(summary[("unknown", "agent-a")]["passes"], 1)
        self.assertEqual(summary[("unknown", "agent-a")]["pass_rate"], 1.0)

    def test_formats_leaderboard_table(self):
        table = format_leaderboard(
            {
                ("model-1", "agent-b"): {
                    "runs": 2,
                    "passes": 2,
                    "pass_rate": 1.0,
                    "average_duration_sec": 5.0,
                }
            }
        )

        self.assertIn("model", table)
        self.assertIn("model-1", table)
        self.assertIn("agent", table)
        self.assertIn("agent-b", table)
        self.assertIn("100.0%", table)


if __name__ == "__main__":
    unittest.main()
