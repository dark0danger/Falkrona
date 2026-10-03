import json
import unittest

from brandpilot.hermes_client import HermesClient, HttpResponse
from brandpilot.outcomes import OutcomeCode


class StubTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def send(self, method, url, headers, body, timeout_seconds):
        self.calls.append((method, url, headers, body, timeout_seconds))
        if self.error:
            raise self.error
        return self.response


class HermesClientTests(unittest.TestCase):
    def test_requires_loopback_endpoint(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            HermesClient("https://example.com", "secret")

    def test_missing_key_never_calls_transport(self):
        transport = StubTransport()
        client = HermesClient("http://127.0.0.1:8642", "", transport=transport)
        outcome = client.start_run("hello", session_id="s1", idempotency_key="k1")
        self.assertEqual(outcome.code, OutcomeCode.MISSING_KEY)
        self.assertEqual(transport.calls, [])

    def test_accepted_run_preserves_session_and_idempotency(self):
        transport = StubTransport(HttpResponse(202, b'{"run_id":"run_123","status":"started"}'))
        client = HermesClient("http://localhost:8642", "secret", transport=transport)
        outcome = client.start_run("hello", session_id="workspace-a", idempotency_key="job-1")
        self.assertEqual(outcome.code, OutcomeCode.OK)
        self.assertEqual(outcome.run_id, "run_123")
        _, _, headers, body, _ = transport.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(headers["Idempotency-Key"], "job-1")
        self.assertEqual(json.loads(body), {"input": "hello", "session_id": "workspace-a"})

    def test_wrong_service_key_is_typed(self):
        transport = StubTransport(HttpResponse(401, b'{"error":"unauthorized"}'))
        client = HermesClient("http://127.0.0.1:8642", "wrong", transport=transport)
        outcome = client.start_run("hello", session_id="s1", idempotency_key="k1")
        self.assertEqual(outcome.code, OutcomeCode.UNAUTHORIZED)

    def test_quota_and_malformed_output_are_typed(self):
        quota = StubTransport(HttpResponse(429, b"{}"))
        malformed = StubTransport(HttpResponse(202, b"not-json"))
        quota_outcome = HermesClient(
            "http://127.0.0.1:8642", "key", transport=quota
        ).start_run("hello", session_id="s1", idempotency_key="k1")
        malformed_outcome = HermesClient(
            "http://127.0.0.1:8642", "key", transport=malformed
        ).start_run("hello", session_id="s1", idempotency_key="k1")
        self.assertEqual(quota_outcome.code, OutcomeCode.QUOTA_EXHAUSTED)
        self.assertEqual(malformed_outcome.code, OutcomeCode.MALFORMED_OUTPUT)

    def test_cancelled_run_is_typed(self):
        transport = StubTransport(
            HttpResponse(200, b'{"run_id":"run_123","status":"cancelled"}')
        )
        outcome = HermesClient(
            "http://127.0.0.1:8642", "key", transport=transport
        ).get_run("run_123")
        self.assertEqual(outcome.code, OutcomeCode.CANCELLED)
        self.assertEqual(outcome.run_id, "run_123")

    def test_failed_run_is_a_typed_tool_error(self):
        transport = StubTransport(
            HttpResponse(
                200,
                b'{"run_id":"run_123","status":"failed","error":"tool failed"}',
            )
        )
        outcome = HermesClient(
            "http://127.0.0.1:8642", "key", transport=transport
        ).get_run("run_123")
        self.assertEqual(outcome.code, OutcomeCode.TOOL_ERROR)
        self.assertEqual(outcome.message, "tool failed")

    def test_cancel_posts_only_to_the_scoped_hermes_stop_endpoint(self):
        transport = StubTransport(HttpResponse(202, b'{"status":"stopping"}'))
        outcome = HermesClient("http://127.0.0.1:8642", "key", transport=transport).cancel_run("run_123")
        self.assertEqual(outcome.code, OutcomeCode.CANCELLED)
        method, url, headers, body, _ = transport.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/v1/runs/run_123/stop"))
        self.assertEqual(headers["Authorization"], "Bearer key")
        self.assertEqual(body, b"{}")


if __name__ == "__main__":
    unittest.main()
