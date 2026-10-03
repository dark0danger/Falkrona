"""Exercise the pinned real Hermes loop and BrandPilot plugin without external calls."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from urllib import error, request


ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / ".dependencies" / "hermes-agent"
PLUGIN = ROOT / "packages" / "hermes_plugin" / "brandpilot_phase0"
RUNTIME = ROOT / ".runtime" / "hermes" / "spike"

sys.path.insert(0, str(HERMES))
from tests.fakes.fake_llm_provider import FakeLLMServer, Text, ToolCall, write_hermes_home  # noqa: E402


def selected_hermes_python() -> Path:
    bootstrap_home = Path(os.environ["HERMES_HOME"])
    install_key = hashlib.sha256(str(HERMES.resolve()).encode("utf-8")).hexdigest()[:16]
    facts = bootstrap_home / "installs" / install_key / "facts.json"
    data = json.loads(facts.read_text(encoding="utf-8"))
    environment = Path(data["packages"]["venv"]["environment"])
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError(f"Selected Hermes interpreter is missing: {python}")
    return python


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def http_response(
    url: str,
    key: str | None = None,
    *,
    method: str = "GET",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout_seconds: float = 5,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, method=method)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for name, value in (extra_headers or {}).items():
        req.add_header(name, value)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return response.status, response.read()
    except error.HTTPError as exc:
        return exc.code, exc.read()


def http_status(url: str, key: str | None = None) -> int:
    return http_response(url, key)[0]


def probe_script(marker: str) -> list:
    return [
        ToolCall("tool_search", {"queries": ["brandpilot phase0 probe"]}),
        ToolCall(
            "tool_call",
            {
                "calls": [
                    {
                        "name": "brandpilot_phase0_probe",
                        "arguments": {"message": marker},
                    }
                ]
            },
        ),
        Text(f"probe complete: {marker}"),
    ]


def probe_api_auth(home: Path, hermes_python: Path) -> dict:
    port = free_loopback_port()
    service_key = secrets.token_hex(32)
    marker = "api-run"
    with FakeLLMServer(probe_script(marker)) as provider:
        write_hermes_home(
            home,
            provider.base_url,
            extra_config=(
                "_config_version: 12\n"
                "plugins:\n"
                "  enabled:\n"
                "    - brandpilot-phase0\n"
            ),
        )
        env_file = home / ".env"
        existing = env_file.read_text(encoding="utf-8")
        env_file.write_text(
            existing
            + "API_SERVER_ENABLED=true\n"
            + "API_SERVER_HOST=127.0.0.1\n"
            + f"API_SERVER_PORT={port}\n"
            + f"API_SERVER_KEY={service_key}\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        env["HERMES_RUNTIME_DIR"] = str(ROOT / ".runtime" / "hermes" / "tools")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [str(hermes_python), "-m", "gateway.run"],
            cwd=HERMES,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Hermes API server exited before readiness")
                with contextlib.suppress(OSError, error.URLError):
                    if http_status(f"{base_url}/v1/capabilities", service_key) == 200:
                        break
                time.sleep(0.2)
            else:
                raise RuntimeError("Hermes API server did not become ready")

            missing_status = http_status(f"{base_url}/v1/capabilities")
            wrong_status = http_status(f"{base_url}/v1/capabilities", "wrong-service-key")
            correct_status = http_status(f"{base_url}/v1/capabilities", service_key)
            if missing_status != 401 or wrong_status != 401 or correct_status != 200:
                raise RuntimeError(
                    "Hermes API authentication contract failed: "
                    f"missing={missing_status}, wrong={wrong_status}, correct={correct_status}"
                )

            accepted_status, accepted_body = http_response(
                f"{base_url}/v1/runs",
                service_key,
                method="POST",
                body={"input": "Run the BrandPilot probe.", "session_id": "phase0-api"},
                extra_headers={"Idempotency-Key": "phase0-api-run"},
            )
            accepted = json.loads(accepted_body)
            run_id = accepted.get("run_id")
            if accepted_status != 202 or not isinstance(run_id, str):
                raise RuntimeError(f"Hermes API did not accept the probe run: {accepted}")

            deadline = time.monotonic() + 60
            run_status = {}
            while time.monotonic() < deadline:
                try:
                    status_code, status_body = http_response(
                        f"{base_url}/v1/runs/{run_id}", service_key
                    )
                except (OSError, TimeoutError, error.URLError):
                    time.sleep(0.2)
                    continue
                if status_code != 200:
                    raise RuntimeError(f"Hermes run status failed with HTTP {status_code}")
                run_status = json.loads(status_body)
                if run_status.get("status") in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("Hermes API probe run did not settle")
            if run_status.get("status") != "completed":
                raise RuntimeError(f"Hermes API probe did not complete: {run_status}")

            events_status, events_body = http_response(
                f"{base_url}/v1/runs/{run_id}/events", service_key
            )
            if events_status != 200:
                raise RuntimeError(f"Hermes event stream failed with HTTP {events_status}")
            events = []
            for line in events_body.decode("utf-8", "replace").splitlines():
                if not line.startswith("data:"):
                    continue
                with contextlib.suppress(json.JSONDecodeError):
                    event_payload = json.loads(line.removeprefix("data:").strip())
                    if isinstance(event_payload, dict) and event_payload.get("event"):
                        events.append(event_payload["event"])
            if "run.completed" not in events:
                raise RuntimeError(f"Hermes did not emit run.completed: {events}")
            usage = run_status.get("usage")
            if not isinstance(usage, dict):
                raise RuntimeError(f"Hermes did not return structured usage: {run_status}")
            return {
                "bind_host": "127.0.0.1",
                "missing_key_status": missing_status,
                "wrong_key_status": wrong_status,
                "correct_key_status": correct_status,
                "run_status": run_status["status"],
                "events": events,
                "usage": usage,
                "provider_requests": len(provider.main_requests()),
            }
        finally:
            subprocess.run(
                [str(hermes_python), str(HERMES / "hermes"), "gateway", "stop"],
                cwd=HERMES,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


def profile_message_state(home: Path) -> tuple[int, str]:
    state_db = home / "state.db"
    if not state_db.is_file():
        return 0, ""
    with sqlite3.connect(state_db) as connection:
        rows = connection.execute(
            "SELECT content, tool_calls FROM messages ORDER BY id"
        ).fetchall()
    corpus = "\n".join(
        value for row in rows for value in row if isinstance(value, str)
    )
    return len(rows), corpus


def run_profile(
    profile: str,
    marker: str,
    hermes_python: Path,
    *,
    reset: bool,
) -> dict:
    home = RUNTIME / profile
    if reset and home.exists():
        shutil.rmtree(home)
    plugin_target = home / "plugins" / "brandpilot_phase0"
    if reset:
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(PLUGIN, plugin_target)
    elif not plugin_target.is_dir():
        raise RuntimeError(f"Restart profile lost its plugin: {profile}")

    message_count_before, _ = profile_message_state(home)
    with FakeLLMServer(probe_script(marker)) as provider:
        write_hermes_home(
            home,
            provider.base_url,
            extra_config=(
                "_config_version: 12\n"
                "plugins:\n"
                "  enabled:\n"
                "    - brandpilot-phase0\n"
            ),
        )
        env = os.environ.copy()
        env["HERMES_HOME"] = str(home)
        env["HERMES_RUNTIME_DIR"] = str(ROOT / ".runtime" / "hermes" / "tools")
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("GOOGLE_API_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        env.pop("OPENAI_API_KEY", None)
        plugin_list = subprocess.run(
            [
                str(hermes_python),
                str(HERMES / "hermes"),
                "plugins",
                "list",
                "--plain",
                "--no-bundled",
            ],
            cwd=HERMES,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=60,
            check=False,
        )
        result = subprocess.run(
            [
                str(hermes_python),
                str(HERMES / "hermes"),
                "chat",
                "-q",
                "Run the BrandPilot probe.",
                "-Q",
            ],
            cwd=HERMES,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
            check=False,
        )
        requests = provider.main_requests()
    message_count_after, _ = profile_message_state(home)

    if result.returncode != 0:
        raise RuntimeError(
            f"Hermes failed for {profile}:\n{result.stdout}\n{result.stderr}\n"
            f"Plugin inventory:\n{plugin_list.stdout}\n{plugin_list.stderr}"
        )
    if len(requests) < 3:
        raise RuntimeError(f"Hermes did not complete a tool round trip for {profile}")
    tool_messages = [
        message
        for provider_request in requests[1:]
        for message in provider_request.get("messages", [])
        if message.get("role") == "tool"
    ]
    if not tool_messages:
        raise RuntimeError(f"Hermes did not send the plugin result back to the model for {profile}")
    payload = None
    for tool_message in reversed(tool_messages):
        try:
            candidate = json.loads(tool_message["content"])
        except json.JSONDecodeError:
            continue
        if candidate.get("plugin") == "brandpilot-phase0":
            payload = candidate
            break
    if payload is None:
        raise RuntimeError(
            f"Hermes did not return the BrandPilot probe payload for {profile}: "
            f"{[message.get('content') for message in tool_messages]!r}\n"
            f"Plugin inventory:\n{plugin_list.stdout}\n{plugin_list.stderr}"
        )
    if payload.get("echo") != marker or payload.get("status") != "ok":
        raise RuntimeError(f"Unexpected plugin result for {profile}: {payload}")

    state_files = sorted(str(path.relative_to(home)) for path in home.rglob("*.db"))
    return {
        "profile": profile,
        "home": str(home),
        "marker": marker,
        "tool_result": payload,
        "provider_requests": len(requests),
        "message_count_before": message_count_before,
        "message_count_after": message_count_after,
        "plugin_inventory": plugin_list.stdout[-2000:],
        "state_files": state_files,
        "stdout_tail": result.stdout[-1000:],
    }


def main() -> int:
    hermes_python = selected_hermes_python()
    first = run_profile("workspace-a", "alpha", hermes_python, reset=True)
    second = run_profile("workspace-b", "beta", hermes_python, reset=True)
    restarted = run_profile("workspace-a", "alpha-restart", hermes_python, reset=False)
    if first["home"] == second["home"]:
        raise RuntimeError("Hermes profiles are not isolated")
    if restarted["message_count_before"] != first["message_count_after"]:
        raise RuntimeError("Workspace A did not retain its state across restart")
    if restarted["message_count_after"] <= restarted["message_count_before"]:
        raise RuntimeError("Workspace A restart did not append its intended history")

    _, workspace_a_corpus = profile_message_state(Path(first["home"]))
    _, workspace_b_corpus = profile_message_state(Path(second["home"]))
    if "alpha" not in workspace_a_corpus or "alpha-restart" not in workspace_a_corpus:
        raise RuntimeError("Workspace A is missing its own history markers")
    if "beta" in workspace_a_corpus:
        raise RuntimeError("Workspace A contains Workspace B history")
    if "beta" not in workspace_b_corpus:
        raise RuntimeError("Workspace B is missing its own history marker")
    if "alpha" in workspace_b_corpus or "alpha-restart" in workspace_b_corpus:
        raise RuntimeError("Workspace B contains Workspace A history")
    report = {
        "passed": True,
        "mode": "offline_test",
        "hermes_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERMES, text=True
        ).strip(),
        "hermes_python": str(hermes_python),
        "profiles": [first, second],
        "restart": restarted,
        "profile_isolation": {
            "workspace_a_has_alpha": True,
            "workspace_a_has_beta": False,
            "workspace_b_has_beta": True,
            "workspace_b_has_alpha": False,
        },
        "api_auth": probe_api_auth(Path(first["home"]), hermes_python),
        "external_provider_calls": 0,
    }
    output = ROOT / "docs" / "evidence" / "generated" / "hermes-spike.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
