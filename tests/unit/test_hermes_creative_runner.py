import io
import json
import sys
from types import SimpleNamespace

import pytest

from scripts.hermes_creative_runner import main


@pytest.mark.parametrize(
    ("status", "expected"),
    [(403, "gemini_access_denied"), (404, "gemini_model_not_found"), (429, "gemini_rate_limited")],
)
def test_failed_hermes_turn_returns_only_an_allowlisted_error(monkeypatch, tmp_path, status, expected):
    class StubAgent:
        tools = []

        def __init__(self, **kwargs):
            pass

        def run_conversation(self, message):
            self._invoke_api_request_error_hook(status_code=status, error_message="private upstream details")
            return {"failed": True, "error": "private upstream details"}

        def close(self):
            pass

    output = tmp_path / "result.json"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=StubAgent))
    monkeypatch.setattr(sys, "argv", ["runner", str(tmp_path), str(output)])
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "Return JSON.", "model": "test-model"})))

    main()

    assert json.loads(output.read_text(encoding="utf-8")) == {"error": expected}
