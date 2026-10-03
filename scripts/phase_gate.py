"""Run implemented phase gates and emit a machine-readable result."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]


def run_step(
    name: str,
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> dict:
    started = time.monotonic()
    env = os.environ.copy()
    env.update(environment or {})
    env.setdefault("UV_CACHE_DIR", str(ROOT / ".runtime" / "uv-cache"))
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "name": name,
        "command": command,
        "passed": result.returncode == 0,
        "exit_code": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def postgres_config_command() -> list[str]:
    for runtime in ("podman", "docker"):
        executable = shutil.which(runtime)
        if executable:
            return [
                executable,
                "compose",
                "-f",
                "infra/postgres/compose.yaml",
                "config",
            ]
    return [
        sys.executable,
        "-c",
        "import sys; print('Podman or Docker is required'); sys.exit(1)",
    ]


def postgres_start_command() -> list[str]:
    command = postgres_config_command()
    if command[0] == sys.executable:
        return command
    return command[:2] + [
        "-f",
        "infra/postgres/compose.yaml",
        "up",
        "-d",
        "--wait",
        "postgres",
    ]


def postgres_test_url() -> str:
    application = make_url(os.environ.get(
        "BRANDPILOT_DATABASE_URL",
        "postgresql+psycopg://brandpilot:brandpilot@127.0.0.1:5432/brandpilot",
    ))
    candidate = make_url(os.environ.get(
        "BRANDPILOT_TEST_DATABASE_URL",
        application.set(database=f"{application.database}_phase_gate").render_as_string(hide_password=False),
    ))
    if (candidate.drivername != "postgresql+psycopg" or candidate.host not in {"127.0.0.1", "localhost"}
        or not candidate.database or candidate.database == application.database
        or not candidate.database.endswith("_phase_gate")
        or candidate.set(database=application.database) != application):
        raise ValueError("Phase gate tests require a separate local PostgreSQL database ending in _phase_gate")
    return candidate.render_as_string(hide_password=False)


def existing_postgres_step(database_url: str) -> dict | None:
    import psycopg

    started = time.monotonic()
    url = make_url(database_url)
    try:
        with psycopg.connect(
            host=url.host, port=url.port or 5432, user=url.username,
            password=url.password, dbname="postgres", connect_timeout=2,
        ):
            pass
    except psycopg.Error:
        return None
    return {
        "name": "postgres_ready",
        "command": ["check existing local PostgreSQL connection"],
        "passed": True,
        "exit_code": 0,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": "Local PostgreSQL is already reachable.",
        "stderr": "",
    }


def ensure_postgres_test_database(database_url: str) -> dict:
    import psycopg
    from psycopg import sql

    started = time.monotonic()
    url = make_url(database_url)
    try:
        with psycopg.connect(
            host=url.host, port=url.port or 5432, user=url.username,
            password=url.password, dbname="postgres", autocommit=True,
        ) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,),
            ).fetchone()
            if exists is None:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(url.database)))
        passed = True
    except psycopg.Error:
        passed = False
    return {
        "name": "postgres_test_database",
        "command": ["create or reuse isolated local phase-gate database"],
        "passed": passed,
        "exit_code": 0 if passed else 1,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout": f"Dedicated test database ready: {url.database}" if passed else "",
        "stderr": "Unable to prepare the dedicated PostgreSQL test database." if not passed else "",
    }


def meta_live_evidence() -> dict:
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from brandpilot.database import build_engine, set_workspace_context
    from brandpilot.models import Job, SocialConnection, SocialPost

    workspace_id = os.environ.get("BRANDPILOT_WORKSPACE_ID", "").strip()
    database_url = os.environ.get("BRANDPILOT_DATABASE_URL", "").strip()
    graph_version = os.environ.get("BRANDPILOT_META_GRAPH_VERSION", "").strip()
    if not workspace_id or not database_url or not graph_version:
        return {"verified": False, "reason": "live_workspace_configuration_missing"}
    engine = build_engine(database_url, role="brandpilot_app")
    try:
        with Session(engine) as session, session.begin():
            set_workspace_context(session, workspace_id)
            connections = session.scalars(select(SocialConnection).where(
                SocialConnection.workspace_id == workspace_id,
                SocialConnection.provider == "meta",
                SocialConnection.account_id.is_not(None),
            )).all()
            for connection in connections:
                scopes = set(connection.granted_scopes or [])
                if (connection.status != "connected_partial" or not connection.capabilities.get("posts")
                    or not {"pages_show_list", "pages_read_engagement"}.issubset(scopes)
                    or connection.last_synced_at is None):
                    continue
                jobs = session.scalars(select(Job).where(
                    Job.workspace_id == workspace_id,
                    Job.kind == "social.meta.sync",
                    Job.status == "completed",
                )).all()
                completed = [job for job in jobs if job.payload.get("connection_id") == connection.id
                             and int(job.checkpoint.get("pages_done", 0)) >= 1]
                count = session.scalar(select(func.count()).select_from(SocialPost).where(
                    SocialPost.workspace_id == workspace_id,
                    SocialPost.provider == "facebook_pages",
                    SocialPost.account_id == connection.account_id,
                    SocialPost.provenance == "meta_api",
                )) or 0
                if completed and count:
                    return {
                        "verified": True,
                        "workspace_id": workspace_id,
                        "account_name": connection.account_name,
                        "graph_version": graph_version,
                        "granted_scopes": sorted(scopes),
                        "verified_capabilities": ["identity", "account_list", "posts"],
                        "completed_sync_jobs": len(completed),
                        "imported_meta_posts": count,
                        "last_synced_at": connection.last_synced_at.isoformat(),
                    }
        return {"verified": False, "reason": "no_completed_authorized_meta_post_sync"}
    except Exception:
        return {"verified": False, "reason": "live_evidence_query_failed"}
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--include-hermes", action="store_true")
    args = parser.parse_args()
    if args.phase not in {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}:
        parser.error("only Phases 0 through 11 are implemented")
    if not args.offline:
        parser.error("implemented phase gates currently require --offline")

    steps = [run_step("environment", [sys.executable, "scripts/check_environment.py"])]
    if args.phase == 0:
        steps.extend(
            [
                run_step("postgres_config", postgres_config_command()),
                run_step(
                    "unit_contracts",
                    [
                        sys.executable,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tests/unit",
                        "-t",
                        ".",
                        "-v",
                    ],
                ),
            ]
        )
    else:
        postgres_url = postgres_test_url()
        npm = shutil.which("npm") or "npm"
        postgres_start = existing_postgres_step(postgres_url) or run_step("postgres_start", postgres_start_command())
        steps.append(postgres_start)
        if postgres_start["passed"]:
            test_database = ensure_postgres_test_database(postgres_url)
            steps.append(test_database)
        if postgres_start["passed"] and test_database["passed"]:
            steps.append(run_step(
                    "backend_tests",
                    [
                        sys.executable,
                        "-m",
                        "unittest",
                        "discover",
                        "-s",
                        "tests",
                        "-t",
                        ".",
                        "-v",
                    ],
                    environment={
                        "BRANDPILOT_TEST_DATABASE_URL": postgres_url,
                        "BRANDPILOT_DATABASE_URL": "",
                    },
                ))
        steps.extend(
            [
                run_step("web_tests", [npm, "test"]),
                run_step("web_build", [npm, "run", "build"]),
                run_step(
                    "dependency_inventory",
                    [sys.executable, "scripts/dependency_inventory.py"],
                ),
            ]
        )
    if args.include_hermes or args.phase == 4:
        steps.append(
            run_step(
                "real_hermes_phase4" if args.phase == 4 else "real_hermes_spike",
                [
                    "powershell",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    "scripts/run_hermes_phase4.ps1" if args.phase == 4 else "scripts/run_hermes_spike.ps1",
                ],
            )
        )
    report = {
        "phase": args.phase,
        "mode": "offline_test",
        "passed": all(step["passed"] for step in steps),
        "steps": steps,
        "live_provider_status": {
            "gemini": "blocked_no_key",
            "openai": "blocked_cost_policy",
        },
    }
    if args.phase == 5:
        live = meta_live_evidence()
        report["meta_live_evidence"] = live
        report["gate_passed"] = report["passed"] and live["verified"]
        report["meta_live_status"] = "verified_posts_read" if live["verified"] else "unverified"
        report["gate_note"] = (
            "Meta Page post reads are verified; other platform adapters remain unavailable."
            if live["verified"] else "Offline contracts pass separately; a live Meta post-read record is still required."
        )
    if args.phase == 6:
        report["gate_passed"] = report["passed"]
        report["gate_note"] = (
            "Offline audit fixtures, source-linked calculations, workspace isolation, migrations, web tests, and build passed. "
            "Live Meta metrics and Instagram connector remain unverified."
            if report["passed"] else "Phase 6 regression gate did not pass."
        )
    if args.phase == 7:
        report["gate_passed"] = report["passed"]
        report["gate_note"] = (
            "Offline strategy fixtures, versioned calendar API, PostgreSQL isolation, earlier regressions, "
            "web tests, and build passed. Live Instagram access and model-written strategies remain unverified."
            if report["passed"] else "Phase 7 regression gate did not pass."
        )
    if args.phase == 8:
        report["gate_passed"] = False
        report["human_review_status"] = "pending"
        report["gate_note"] = (
            "Automated creative contracts and regressions passed. Thirty scene fixtures are validated; "
            "browser-rendered fixture review, exact copy/asset visual checks, and David's 80% human rubric sign-off remain pending."
            if report["passed"] else "Phase 8 automated regression gate did not pass."
        )
    if args.phase == 9:
        report["gate_passed"] = report["passed"]
        report["gate_note"] = (
            "Offline scoped feedback, owner approval, conflict, rollback, persistent retrieval, "
            "PostgreSQL isolation, earlier regressions, web tests, and build passed. "
            "Phase 8 design approval and live Instagram access remain open."
            if report["passed"] else "Phase 9 regression gate did not pass."
        )
    if args.phase == 10:
        report["gate_passed"] = False
        report["live_publication_status"] = "blocked_no_verified_write_capability"
        report["gate_note"] = (
            "Offline approval, manual export, recovery contracts, workspace isolation, and prior regressions passed. "
            "No live connector write, public media delivery, or owner-verified remote post was attempted. "
            "Phase 8 design sign-off and Meta publish permissions remain open."
            if report["passed"] else "Phase 10 offline regression checks did not pass."
        )
    if args.phase == 11:
        report["gate_passed"] = report["passed"]
        report["gate_note"] = ("Required branding, survey/image-context contracts, recurring weekly reports, daily engagement, "
            "linked Instagram read fixtures, evidence dates, migrations, workspace isolation, and regressions verified offline. "
            "Live Gemini access, live Meta OAuth/measurements, and live publication remain unverified."
            if report["passed"] else "Phase 11 verification is incomplete; inspect the failed steps and preserve live blockers.")
    output = (
        ROOT
        / "docs"
        / "evidence"
        / "generated"
        / f"phase-{args.phase:02d}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
