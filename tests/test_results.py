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
                "agent": "noop-agent",
                "duration_sec": 3.5,
                "verification_passed": False,
            }
            second = {
                "run_id": "run-2",
                "case_id": "postgres-missing-index-001",
                "agent": "oracle-agent",
                "duration_sec": 4.5,
                "verification_passed": True,
            }

            append_run(results_file, first)
            append_run(results_file, second)

            self.assertEqual(load_runs(results_file), [first, second])

    def test_summarizes_runs_by_agent(self):
        runs = [
            {
                "agent": "noop-agent",
                "duration_sec": 5.0,
                "verification_passed": False,
            },
            {
                "agent": "oracle-agent",
                "duration_sec": 4.0,
                "verification_passed": True,
            },
            {
                "agent": "oracle-agent",
                "duration_sec": 6.0,
                "verification_passed": True,
            },
        ]

        summary = summarize_runs(runs)

        self.assertEqual(summary["noop-agent"]["runs"], 1)
        self.assertEqual(summary["noop-agent"]["passes"], 0)
        self.assertEqual(summary["noop-agent"]["pass_rate"], 0.0)
        self.assertEqual(summary["noop-agent"]["average_duration_sec"], 5.0)
        self.assertEqual(summary["oracle-agent"]["runs"], 2)
        self.assertEqual(summary["oracle-agent"]["passes"], 2)
        self.assertEqual(summary["oracle-agent"]["pass_rate"], 1.0)
        self.assertEqual(summary["oracle-agent"]["average_duration_sec"], 5.0)

    def test_formats_leaderboard_table(self):
        table = format_leaderboard(
            {
                "oracle-agent": {
                    "runs": 2,
                    "passes": 2,
                    "pass_rate": 1.0,
                    "average_duration_sec": 5.0,
                }
            }
        )

        self.assertIn("agent", table)
        self.assertIn("oracle-agent", table)
        self.assertIn("100.0%", table)


if __name__ == "__main__":
    unittest.main()
