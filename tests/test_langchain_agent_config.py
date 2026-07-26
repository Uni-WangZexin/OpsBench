import os
import unittest
from unittest.mock import patch

from agents.langchain_react_agent.config import AgentConfig, load_config


class LangChainAgentConfigTests(unittest.TestCase):
    def test_load_config_reads_defaults(self):
        env = {"OPENAI_API_KEY": "secret"}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.base_url, "https://api.deepseek.com")
        self.assertEqual(config.model, "deepseek-v4-pro")
        self.assertEqual(config.max_steps, 60)
        self.assertEqual(config.temperature, 0.0)

    def test_load_config_allows_overrides(self):
        env = {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://example.test/v1",
            "OPENAI_MODEL": "provider-model",
            "LANGCHAIN_MAX_STEPS": "5",
            "LANGCHAIN_TEMPERATURE": "0.2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(
            config,
            AgentConfig(
                api_key="secret",
                base_url="https://example.test/v1",
                model="provider-model",
                max_steps=5,
                temperature=0.2,
            ),
        )

    def test_load_config_supports_legacy_deepseek_variables(self):
        env = {
            "DEEPSEEK_API_KEY": "legacy-secret",
            "DEEPSEEK_BASE_URL": "https://legacy.example.test/v1",
            "DEEPSEEK_MODEL": "legacy-model",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        self.assertEqual(config.api_key, "legacy-secret")
        self.assertEqual(config.base_url, "https://legacy.example.test/v1")
        self.assertEqual(config.model, "legacy-model")

    def test_missing_api_key_raises_clear_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                load_config()


if __name__ == "__main__":
    unittest.main()
