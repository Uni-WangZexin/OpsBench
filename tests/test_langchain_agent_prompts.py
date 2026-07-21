import unittest

from agents.langchain_react_agent.prompts import build_system_prompt, build_user_prompt


class LangChainAgentPromptTests(unittest.TestCase):
    def test_system_prompt_declares_container_and_benchmark_tool_boundary(self):
        prompt = build_system_prompt()

        self.assertIn("OpsBench", prompt)
        self.assertIn("isolated container", prompt)
        self.assertIn("standard tool contract", prompt)
        self.assertIn("Observability", prompt)
        self.assertIn("not agent tools", prompt)
        self.assertNotIn("read_file", prompt)
        self.assertNotIn("write_file", prompt)
        self.assertNotIn("run_verifier", prompt)

    def test_user_prompt_contains_public_context(self):
        prompt = build_user_prompt(
            task_text="The API is slow.",
            shell_service="db",
        )

        self.assertIn("The API is slow.", prompt)
        self.assertIn("db", prompt)
        self.assertNotIn("Verifier command", prompt)
        self.assertNotIn("Case directory", prompt)
        self.assertNotIn("Work directory", prompt)


if __name__ == "__main__":
    unittest.main()
