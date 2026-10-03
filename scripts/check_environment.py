"""Report Phase 0 host capabilities without installing or mutating anything."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "infra" / "hermes" / "pin.json"
HERMES_CHECKOUT = ROOT / ".dependencies" / "hermes-agent"


def command_version(command: str, *args: str) -> dict:
    executable = shutil.which(command)
    if not executable:
        return {"available": False, "version": None}
    result = subprocess.run(
        [executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    text = (result.stdout or result.stderr).strip().splitlines()
    return {
        "available": result.returncode == 0,
        "version": text[0] if text else None,
    }


def hermes_pin_status() -> dict:
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if not (HERMES_CHECKOUT / ".git").exists():
        return {"available": False, "expected": pin["commit"], "actual": None}
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=HERMES_CHECKOUT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    actual = result.stdout.strip() if result.returncode == 0 else None
    return {
        "available": actual == pin["commit"],
        "expected": pin["commit"],
        "actual": actual,
    }


def main() -> int:
    lockfiles = {
        "brandpilot_python": (ROOT / "uv.lock").is_file(),
        "brandpilot_node": (ROOT / "package-lock.json").is_file(),
        "hermes_python": (HERMES_CHECKOUT / "uv.lock").is_file(),
        "hermes_runtime": (HERMES_CHECKOUT / "pm" / "lock.json").is_file(),
    }
    report = {
        "python": {
            "available": sys.version_info[:2] == (3, 13),
            "version": sys.version.split()[0],
        },
        "node": command_version("node", "--version"),
        "npm": command_version("npm", "--version"),
        "uv": command_version("uv", "--version"),
        "git": command_version("git", "--version"),
        "container": command_version("podman", "--version"),
        "docker_fallback": command_version("docker", "--version"),
        "postgres_client": command_version("psql", "--version"),
        "hermes_pin": hermes_pin_status(),
        "lockfiles": lockfiles,
    }
    required = ["python", "node", "npm", "uv", "git", "hermes_pin"]
    report["postgres_runtime_ready"] = (
        report["container"]["available"] or report["docker_fallback"]["available"]
    )
    report["required_ready"] = (
        all(report[item]["available"] for item in required)
        and all(lockfiles.values())
        and report["postgres_runtime_ready"]
    )
    print(json.dumps(report, indent=2))
    return 0 if report["required_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
