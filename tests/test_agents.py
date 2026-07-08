import unittest
from pathlib import Path


class BuiltInAgentTests(unittest.TestCase):
    def test_only_langchain_react_agent_entrypoint_exists(self):
        root = Path(__file__).resolve().parents[1]
        run_scripts = sorted(
            path.relative_to(root).as_posix()
            for path in (root / "agents").glob("*/run.sh")
        )

        self.assertEqual(run_scripts, ["agents/langchain-react-agent/run.sh"])


if __name__ == "__main__":
    unittest.main()
