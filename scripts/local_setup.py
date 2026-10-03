"""Explicit local setup steps; never replaces an existing .env or rotates its keys."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            if name in values:
                raise ValueError(f"Duplicate setting in the env file: {name}")
            values[name] = value
    return values


def update_env(path: Path, updates: dict[str, str]) -> None:
    env_values(path)  # Reject ambiguous duplicate settings before writing.
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise ValueError("An environment setting cannot contain a newline")
    remaining = dict(updates)
    lines = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        name = line.strip().split("=", 1)[0]
        if name in remaining:
            line = f"{name}={remaining.pop(name)}"
        lines.append(line)
    lines.extend(f"{name}={value}" for name, value in remaining.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def initialize(path: Path, *, https: bool = False) -> None:
    if path.exists():
        raise ValueError("The env file already exists; it was left unchanged.")
    updates = {
        "BRANDPILOT_APP_SECRET_KEY": secrets.token_urlsafe(32),
        "BRANDPILOT_CREDENTIAL_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "BRANDPILOT_OWNER_SETUP_TOKEN": secrets.token_urlsafe(32),
        "BRANDPILOT_HERMES_SERVICE_KEY": secrets.token_urlsafe(32),
        "BRANDPILOT_SESSION_COOKIE_SECURE": "true" if https else "false",
    }
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    lines = []
    for line in template.splitlines():
        name = line.split("=", 1)[0]
        lines.append(f"{name}={updates[name]}" if name in updates else line)
    with path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def hermes_python(root: Path) -> Path:
    checkout = root / ".dependencies" / "hermes-agent"
    if not (checkout / ".git").exists():
        raise ValueError("Prepare Hermes with scripts/prepare_hermes.ps1 first.")
    pin = json.loads((root / "infra/hermes/pin.json").read_text(encoding="utf-8"))
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout,
                            capture_output=True, text=True, check=True).stdout.strip()
    if actual != pin["commit"]:
        raise ValueError("The Hermes checkout does not match infra/hermes/pin.json.")
    install_key = hashlib.sha256(str(checkout.resolve()).encode("utf-8")).hexdigest()[:16]
    for home in ("bootstrap", "spike-bootstrap"):
        facts = root / ".runtime/hermes" / home / "installs" / install_key / "facts.json"
        if not facts.is_file():
            continue
        data = json.loads(facts.read_text(encoding="utf-8"))
        environment = Path(data["packages"]["venv"]["environment"])
        for suffix in ("Scripts/python.exe", "bin/python"):
            candidate = environment / suffix
            if candidate.is_file():
                return candidate.resolve()
    raise ValueError("No prepared Hermes interpreter was found. Run scripts/prepare_hermes.ps1.")


def choose_workspace(ids: list[str], requested: str | None) -> str:
    if requested:
        requested = str(UUID(requested))
        if requested not in ids:
            raise ValueError("That workspace is not in the configured local database.")
        return requested
    if len(ids) != 1:
        raise ValueError("Expected one workspace. Create the owner account first, or use --workspace-id for an existing workspace.")
    return ids[0]


def workspace_id(path: Path, requested: str | None) -> str:
    from sqlalchemy import create_engine, text

    url = env_values(path).get("BRANDPILOT_DATABASE_URL", "")
    if not url:
        raise ValueError("BRANDPILOT_DATABASE_URL is missing from the env file.")
    engine = None
    try:
        engine = create_engine(url)
        with engine.connect() as connection:
            ids = list(connection.execute(text("SELECT id FROM workspaces ORDER BY id")).scalars())
    except Exception:
        raise ValueError("Could not read workspaces. Start PostgreSQL, run migrations, and create the owner account first.") from None
    finally:
        if engine is not None:
            engine.dispose()
    return choose_workspace(ids, requested)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "hermes", "workspace"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--https", action="store_true", help="Create secure cookies for an HTTPS setup")
    parser.add_argument("--workspace-id", help="Choose explicitly when the database has several workspaces")
    args = parser.parse_args()
    path = args.env_file.resolve()
    try:
        if args.command == "init":
            initialize(path, https=args.https)
            print("Created the local env file with unique security values. Provider keys remain blank.")
            print("Open it locally to configure Gemini and copy the owner setup token into the first-account form.")
        elif args.command == "hermes":
            update_env(path, {"BRANDPILOT_HERMES_PYTHON": str(hermes_python(ROOT))})
            print("Configured the prepared Hermes interpreter. Restart the API and worker if they are running.")
        else:
            update_env(path, {"BRANDPILOT_WORKSPACE_ID": workspace_id(path, args.workspace_id)})
            print("Configured the selected worker workspace. Restart the worker if it is running.")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, KeyError, subprocess.CalledProcessError):
        print("Setup did not complete. Check the local env file and prepared runtime.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
