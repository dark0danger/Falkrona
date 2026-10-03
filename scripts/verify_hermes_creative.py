"""Real pinned Hermes creative turn against an offline loopback model fixture."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import argparse
import base64
from io import BytesIO
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = ROOT / ".dependencies/hermes-agent"
sys.path.insert(0, str(CHECKOUT))
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, MODEL_ID


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--survey", action="store_true")
    args = parser.parse_args()
    key = hashlib.sha256(str(CHECKOUT.resolve()).encode()).hexdigest()[:16]
    facts = json.loads((ROOT / ".runtime/hermes/spike-bootstrap/installs" / key / "facts.json").read_text(encoding="utf-8"))
    python = Path(facts["packages"]["venv"]["environment"]) / "Scripts/python.exe"
    direction = {"design_idea": "Product photograph with space for the confirmed headline",
                 "image_prompt": "Natural light on the supplied product. Preserve its shape. Create a complete ad with the exact logo, headline and CTA.",
                 "layout": "editorial", "headline_align": "start", "missing_information": [],
                 "headline": "Fresh coffee. Good company.", "cta": "Discover your favorite",
                 "caption": "A fresh moment with our coffee.", "language": "en"}
    if args.survey:
        from brandpilot.branding import STARTER, BrandingSurvey
        direction = STARTER
        schema = BrandingSurvey.model_json_schema()
        images = []
    else:
        from brandpilot.design_direction import DesignDirection
        schema = DesignDirection.model_json_schema()
        fixture_image = BytesIO(); Image.new("RGB", (16, 16), "green").save(fixture_image, "PNG")
        images = [{"role": "reference", "data_url": "data:image/png;base64," + base64.b64encode(fixture_image.getvalue()).decode()}]
    runtime = ROOT / ".runtime/creative"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime) as directory, FakeLLMServer([Text(json.dumps(direction))], aux=lambda _: Text(json.dumps(direction))) as provider:
        home = Path(directory)
        (home / "config.yaml").write_text("_config_version: 12\nagent:\n  api_max_retries: 1\n", encoding="utf-8")
        output = home / "result.json"
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT"}}
        env.update(HERMES_HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home / "local"),
                   APPDATA=str(home / "roaming"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        completed = subprocess.run([str(python), str(ROOT / "scripts/hermes_creative_runner.py"), str(CHECKOUT),
            str(output), "--fixture-url", provider.base_url], cwd=home, env=env,
            input=json.dumps({"prompt": "Return the requested JSON.", "model": MODEL_ID, "schema": schema, "images": images}),
            text=True, capture_output=True, timeout=120)
        result = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
        try:
            valid = json.loads(result.get("text", "{}")) == direction
        except (ValueError, TypeError):
            valid = False
        image_sent = any(item.get("type") == "image_url" for request in provider.requests
            for message in request.get("body", request).get("messages", [])
            for item in (message.get("content") if isinstance(message.get("content"), list) else []) if isinstance(item, dict))
        passed = completed.returncode == 0 and valid and result.get("model_calls") == 1 and len(provider.requests) == 1 and (args.survey or image_sent)
        report = {"passed": passed, "runtime": "pinned_hermes_AIAgent", "mode": "offline_fixture",
                  "model_calls": result.get("model_calls"), "external_calls": 0, "result": result}
        report["transport_requests"] = len(provider.requests)
        report["native_image_context"] = image_sent
        if not passed:
            report["diagnostics"] = completed.stderr[-3000:]
        path = ROOT / ("docs/evidence/generated/branding-hermes.json" if args.survey else "docs/evidence/generated/creative-hermes.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
