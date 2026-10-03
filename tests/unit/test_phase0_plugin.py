import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS_PATH = ROOT / "packages" / "hermes_plugin" / "brandpilot_phase0" / "tools.py"


def load_tools_module():
    spec = importlib.util.spec_from_file_location("brandpilot_phase0_tools", TOOLS_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Phase0PluginTests(unittest.TestCase):
    def test_probe_returns_structured_json(self):
        result = json.loads(load_tools_module().probe({"message": "phase-zero"}))
        self.assertEqual(
            result,
            {
                "echo": "phase-zero",
                "plugin": "brandpilot-phase0",
                "schema_version": 1,
                "status": "ok",
            },
        )

    def test_probe_returns_error_instead_of_raising(self):
        result = json.loads(load_tools_module().probe({"message": ""}))
        self.assertEqual(result, {"error": "message is required"})

    def test_probe_types_unexpected_tool_input(self):
        result = json.loads(load_tools_module().probe(None))
        self.assertIn("probe failed", result["error"])


if __name__ == "__main__":
    unittest.main()
