import json
import logging
import unittest

from brandpilot.logging_utils import RedactingJsonFormatter, redact


class RedactedLoggingTests(unittest.TestCase):
    def test_nested_secrets_and_message_values_are_redacted(self):
        self.assertEqual(
            redact({"api_key": "secret-value", "safe": "token=abc123"}),
            {"api_key": "[REDACTED]", "safe": "token=[REDACTED]"},
        )
        record = logging.LogRecord(
            "test", logging.INFO, __file__, 1, "Authorization: Bearer-secret", (), None
        )
        payload = json.loads(RedactingJsonFormatter().format(record))
        self.assertNotIn("Bearer-secret", payload["message"])
        callback = logging.LogRecord(
            "test", logging.INFO, __file__, 1,
            "GET /callback?state=secret-state&code=secret-code", (), None,
        )
        message = json.loads(RedactingJsonFormatter().format(callback))["message"]
        self.assertNotIn("secret-state", message)
        self.assertNotIn("secret-code", message)


if __name__ == "__main__":
    unittest.main()
