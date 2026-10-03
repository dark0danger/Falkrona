import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOLS_PATH = ROOT / "packages" / "hermes_plugin" / "falkrona" / "tools.py"


def load_tools_module():
    spec = importlib.util.spec_from_file_location("falkrona_phase4_tools", TOOLS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Phase4PluginTests(unittest.TestCase):
    def test_plugin_fails_closed_without_a_scoped_runtime_environment(self):
        tools = load_tools_module()
        result = tools.get_brand_context({})
        self.assertIn("not configured", result)

    def test_plugin_rejects_unstructured_artifact_input_locally(self):
        tools = load_tools_module()
        result = tools.store_artifact({"title": "only-title"})
        self.assertIn("required", result)


if __name__ == "__main__":
    unittest.main()
