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


@pytest.mark.parametrize("transport", ["_interruptible_streaming_api_call", "_interruptible_api_call"])
@pytest.mark.parametrize("complete", [True, False])
def test_length_finish_preserves_complete_structured_response(monkeypatch, tmp_path, transport, complete):
    brief = json.dumps({"headline": "حان وقت العصير"}, ensure_ascii=False)
    content = brief if complete else brief[:-1]

    class StubAgent:
        tools = []
        session_api_calls = session_input_tokens = session_output_tokens = 0

        def __init__(self, **kwargs):
            pass

        def _provider_response(self):
            return SimpleNamespace(choices=[
                SimpleNamespace(finish_reason="length", message=SimpleNamespace(content=content))
            ])

        _interruptible_streaming_api_call = _interruptible_api_call = _provider_response

        def run_conversation(self, message):
            response = getattr(self, transport)()
            if response.choices[0].finish_reason == "stop":
                self.session_api_calls = 1
                self.session_input_tokens = 100
                self.session_output_tokens = 4000
                return {"final_response": content}
            return {"final_response": self._handle_max_iterations([], 1)}

        def close(self):
            pass

    output = tmp_path / "result.json"
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=StubAgent))
    monkeypatch.setattr(sys, "argv", ["runner", str(tmp_path), str(output)])
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "Return JSON.", "model": "test-model"})))

    main()

    result = json.loads(output.read_text(encoding="utf-8"))
    if complete:
        assert result == {"text": brief, "model_calls": 1, "usage": {"input_tokens": 100, "output_tokens": 4000}}
    else:
        assert result == {"error": "gemini_incomplete_response"}
