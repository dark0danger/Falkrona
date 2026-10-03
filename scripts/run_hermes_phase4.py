"""Phase 4 proof: a real Hermes gateway invokes only Falkrona's app tools."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib import error, request

import uvicorn
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.app import create_app
from brandpilot.accounts import Principal
from brandpilot.config import ExecutionMode, ModelProvider, RuntimeConfig
from brandpilot.database import Base, build_engine, build_session_factory
from brandpilot.hermes_client import HermesClient
from brandpilot.models import WorkspaceAsset
from brandpilot.outcomes import OutcomeCode
from brandpilot.settings import AppSettings


HERMES = ROOT / ".dependencies" / "hermes-agent"
PLUGIN = ROOT / "packages" / "hermes_plugin" / "falkrona"
RUNTIME = ROOT / ".runtime" / "hermes" / "phase4"
GATEWAY_PORT = 8642
sys.path.insert(0, str(HERMES))
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home  # noqa: E402


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def hermes_python() -> Path:
    bootstrap = Path(os.environ["HERMES_HOME"])
    install_key = hashlib.sha256(str(HERMES.resolve()).encode("utf-8")).hexdigest()[:16]
    facts = json.loads((bootstrap / "installs" / install_key / "facts.json").read_text(encoding="utf-8"))
    environment = Path(facts["packages"]["venv"]["environment"])
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError(f"Pinned Hermes interpreter is missing: {python}")
    return python


def http_status(url: str, key: str) -> int:
    req = request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with request.urlopen(req, timeout=3) as response:
            return response.status
    except error.HTTPError as exc:
        return exc.code


def scripted_turns() -> list:
    return [
        ToolCall("tool_search", {"queries": ["Falkrona brand context and artifact tools"]}),
        ToolCall("tool_call", {"calls": [{"name": "falkrona_get_brand_context", "arguments": {}}]}),
        ToolCall("tool_call", {"calls": [{"name": "falkrona_store_artifact", "arguments": {"title": "launch-caption", "content": "A public launch caption."}}]}),
        Text("The approved caption was stored."),
    ]


def wait_ready(server: uvicorn.Server) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if server.started:
            return
        time.sleep(0.05)
    raise RuntimeError("Falkrona API did not become ready")


def wait_gateway(process: subprocess.Popen[bytes], service_key: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Hermes gateway exited before readiness")
        with contextlib.suppress(OSError, error.URLError):
            if http_status(f"http://127.0.0.1:{GATEWAY_PORT}/v1/capabilities", service_key) == 200:
                return
        time.sleep(0.2)
    raise RuntimeError("Hermes gateway did not become ready")


def main() -> int:
    if not HERMES.is_dir():
        raise RuntimeError("Hermes checkout is missing. Run scripts/prepare_hermes.ps1 first.")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    home = RUNTIME / "workspace-a"
    if home.exists():
        shutil.rmtree(home)
    plugin_target = home / "plugins" / "falkrona"
    plugin_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PLUGIN, plugin_target)
    shutil.copytree(ROOT / "infra" / "hermes" / "skills", home / "skills", dirs_exist_ok=True)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        engine = build_engine(f"sqlite+pysqlite:///{root / 'phase4.db'}")
        Base.metadata.create_all(engine)
        settings = AppSettings(
            database_url="sqlite+pysqlite:///:memory:", storage_root=root / "storage",
            runtime=RuntimeConfig(execution_mode=ExecutionMode.GEMINI_FREE, model_provider=ModelProvider.GEMINI),
            app_secret_key=b"a" * 32, credential_encryption_key=b"b" * 32,
            owner_setup_token="owner-setup-token-with-20-chars", session_cookie_secure=False,
            gemini_model="fixture-hermes-model",
        )
        app = create_app(settings, engine=engine)
        user_id, workspace_id = app.state.accounts.setup_owner(
            "owner@example.test", "owner-password-long", "Falkrona",
            supplied_token=settings.owner_setup_token, expected_token=settings.owner_setup_token,
        )
        run = app.state.phase4.create_run(
            Principal(user_id, "owner@example.test", "phase4-proof"), workspace_id,
            "Draft a public launch caption.", "real-hermes-proof",
        )
        credential = app.state.run_credentials.issue(
            workspace_id, run["job_id"], ["brand.read", "artifact.write"], expires_at=2_000_000_000
        )
        app_port = free_port()
        app_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=app_port, log_level="error"))
        app_thread = threading.Thread(target=app_server.run, daemon=True)
        app_thread.start()
        wait_ready(app_server)
        process: subprocess.Popen[bytes] | None = None
        env: dict[str, str] = {}
        try:
            service_key = "phase4-local-gateway-key"
            with FakeLLMServer(scripted_turns()) as provider:
                write_hermes_home(home, provider.base_url, extra_config="_config_version: 12\nplugins:\n  enabled:\n    - falkrona\n")
                env_file = home / ".env"
                env_file.write_text(
                    env_file.read_text(encoding="utf-8") + "API_SERVER_ENABLED=true\n"
                    + "API_SERVER_HOST=127.0.0.1\n" + f"API_SERVER_PORT={GATEWAY_PORT}\n"
                    + f"API_SERVER_KEY={service_key}\n", encoding="utf-8",
                )
                env = os.environ.copy()
                env.update({
                    "HERMES_HOME": str(home), "HERMES_RUNTIME_DIR": str(ROOT / ".runtime" / "hermes" / "tools"),
                    "FALKRONA_APP_URL": f"http://127.0.0.1:{app_port}", "FALKRONA_RUN_CREDENTIAL": credential,
                    "FALKRONA_WORKSPACE_ID": workspace_id, "FALKRONA_JOB_ID": run["job_id"],
                    "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
                })
                env.pop("VIRTUAL_ENV", None)
                env.pop("PYTHONHOME", None)
                env.pop("PYTHONPATH", None)
                process = subprocess.Popen(
                    [str(hermes_python()), "-m", "gateway.run"], cwd=HERMES, env=env,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                wait_gateway(process, service_key)
                client = HermesClient(f"http://127.0.0.1:{GATEWAY_PORT}", service_key, timeout_seconds=10)
                accepted = client.start_run("Create the approved launch artifact.", session_id=workspace_id, idempotency_key=run["job_id"])
                if not accepted.ok or not accepted.run_id:
                    raise RuntimeError(f"Hermes did not accept the Phase 4 run: {accepted}")
                deadline = time.monotonic() + 90
                final = None
                while time.monotonic() < deadline:
                    final = client.get_run(accepted.run_id)
                    if final.code is not OutcomeCode.OK:
                        raise RuntimeError(f"Hermes Phase 4 run failed: {final}")
                    if final.data.get("status") == "completed":
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"Hermes Phase 4 timed out; stop outcome: {client.cancel_run(accepted.run_id)}")
                if len(provider.main_requests()) < 4:
                    raise RuntimeError("Hermes did not execute all modeled tool workflow turns")
                sessions = build_session_factory(engine)
                with sessions() as session:
                    asset = session.scalar(select(WorkspaceAsset).where(WorkspaceAsset.workspace_id == workspace_id, WorkspaceAsset.source == "hermes"))
                if asset is None:
                    raise RuntimeError("Hermes did not store an artifact through Falkrona app tools")
                stored = app.state.storage.read_bytes(asset.storage_key)
                if not stored:
                    raise RuntimeError("Hermes stored an empty artifact through Falkrona app tools")
                report = {"passed": True, "mode": "offline_test", "gateway": f"http://127.0.0.1:{GATEWAY_PORT}", "hermes_run_id": accepted.run_id, "run_status": final.data.get("status"), "provider_requests": len(provider.main_requests()), "artifact_id": asset.id, "external_provider_calls": 0}
                output = ROOT / "docs" / "evidence" / "generated" / "phase-04-hermes.json"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps(report, indent=2))
                return 0
        finally:
            if process is not None:
                subprocess.run([str(hermes_python()), str(HERMES / "hermes"), "gateway", "stop"], cwd=HERMES, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30, check=False)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
            app_server.should_exit = True
            app_thread.join(timeout=15)
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
