import unittest

from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.phase4 import classify_and_redact
from brandpilot.provider_policy import ModelRequest, admit_model_request


class Phase4PolicyTests(unittest.TestCase):
    def test_redaction_classifies_sensitive_text_before_any_provider_request(self):
        classified = classify_and_redact("Use api_key=super-secret and email owner@example.test")
        self.assertTrue(classified.contains_private_data)
        self.assertNotIn("super-secret", classified.redacted_text)
        self.assertNotIn("owner@example.test", classified.redacted_text)

    def test_same_public_contract_is_admitted_for_selected_gemini_and_openai_paths(self):
        gemini = RuntimeConfig(execution_mode=ExecutionMode.GEMINI_FREE, model_provider=ModelProvider.GEMINI)
        openai = RuntimeConfig(execution_mode=ExecutionMode.PAID_OPT_IN, model_provider=ModelProvider.OPENAI, openai_paid_enabled=True)
        task = "Draft a public launch caption from approved public facts."
        self.assertTrue(admit_model_request(gemini, ModelRequest(provider=ModelProvider.GEMINI)).ok, task)
        self.assertTrue(admit_model_request(openai, ModelRequest(provider=ModelProvider.OPENAI)).ok, task)

    def test_openai_image_capability_stays_fail_closed_without_its_separate_flag(self):
        config = RuntimeConfig(execution_mode=ExecutionMode.PAID_OPT_IN, model_provider=ModelProvider.OPENAI, openai_paid_enabled=True)
        outcome = admit_model_request(config, ModelRequest(provider=ModelProvider.OPENAI, image_generation=True))
        self.assertFalse(outcome.ok)


if __name__ == "__main__":
    unittest.main()
