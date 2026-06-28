import unittest

from agents.langchain_react_agent.prompts import build_system_prompt, build_user_prompt


class LangChainAgentPromptTests(unittest.TestCase):
    def test_system_prompt_declares_opsbench_and_hidden_data_rule(self):
        prompt = build_system_prompt()

        self.assertIn("OpsBench", prompt)
        self.assertIn("Do not inspect hidden", prompt)
        self.assertIn("run the verifier", prompt)

    def test_user_prompt_contains_public_context(self):
        prompt = build_user_prompt(
            task_text="The API is slow.",
            case_dir="/case",
            work_dir="/work",
            verify_cmd="/work/verify.sh",
        )

        self.assertIn("The API is slow.", prompt)
        self.assertIn("/case", prompt)
        self.assertIn("/work", prompt)
        self.assertIn("/work/verify.sh", prompt)
        self.assertNotIn("oracle_fix.sql", prompt)


if __name__ == "__main__":
    unittest.main()
