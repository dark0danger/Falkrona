import os
import unittest
from unittest.mock import patch

from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig


class RuntimeConfigTests(unittest.TestCase):
    def test_default_is_fully_offline(self):
        with patch.dict(os.environ, {}, clear=True):
            config = RuntimeConfig.from_env()
        self.assertEqual(config.execution_mode, ExecutionMode.OFFLINE_TEST)
        self.assertEqual(config.model_provider, ModelProvider.NONE)
        self.assertFalse(config.openai_paid_enabled)
        self.assertFalse(config.image_api_enabled)

    def test_offline_rejects_provider_even_when_key_might_exist(self):
        config = RuntimeConfig(model_provider=ModelProvider.OPENAI)
        with self.assertRaisesRegex(ValueError, "offline_test"):
            config.validate()

    def test_openai_requires_explicit_paid_flag(self):
        config = RuntimeConfig(
            execution_mode=ExecutionMode.PAID_OPT_IN,
            model_provider=ModelProvider.OPENAI,
        )
        with self.assertRaisesRegex(ValueError, "OPENAI_PAID_ENABLED"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
