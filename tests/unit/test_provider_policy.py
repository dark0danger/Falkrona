import unittest

from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.outcomes import OutcomeCode
from brandpilot.provider_policy import ModelRequest, admit_model_request


class ProviderPolicyTests(unittest.TestCase):
    def test_offline_mode_blocks_all_external_transports(self):
        outcome = admit_model_request(
            RuntimeConfig(),
            ModelRequest(provider=ModelProvider.GEMINI),
        )
        self.assertEqual(outcome.code, OutcomeCode.BLOCKED_COST_POLICY)

    def test_free_gemini_blocks_private_payload(self):
        config = RuntimeConfig(
            execution_mode=ExecutionMode.GEMINI_FREE,
            model_provider=ModelProvider.GEMINI,
        )
        outcome = admit_model_request(
            config,
            ModelRequest(provider=ModelProvider.GEMINI, contains_private_data=True),
        )
        self.assertEqual(outcome.code, OutcomeCode.BLOCKED_DATA_POLICY)

    def test_paid_openai_still_blocks_image_without_separate_flag(self):
        config = RuntimeConfig(
            execution_mode=ExecutionMode.PAID_OPT_IN,
            model_provider=ModelProvider.OPENAI,
            openai_paid_enabled=True,
        )
        outcome = admit_model_request(
            config,
            ModelRequest(provider=ModelProvider.OPENAI, image_generation=True),
        )
        self.assertEqual(outcome.code, OutcomeCode.BLOCKED_COST_POLICY)


if __name__ == "__main__":
    unittest.main()
