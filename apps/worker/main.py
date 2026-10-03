"""Restartable worker process bootstrap."""

from __future__ import annotations

import argparse
import logging
import socket
import time

from brandpilot.database import build_engine, build_session_factory
from brandpilot.jobs import JobStore
from brandpilot.logging_utils import configure_logging
from brandpilot.security import CredentialCipher
from brandpilot.settings import AppSettings
from brandpilot.social import MetaConfig, SocialSyncHandler, SocialService
from brandpilot.scheduled_publishing import ScheduledPublishing, FacebookPublicationHandler
from brandpilot.storage import LocalStorage
from brandpilot.worker import Worker
from brandpilot.accounts import AccountService
from brandpilot.phase4 import Phase4Service
from brandpilot.creative_worker import CreativeDirectionHandler, HermesCreativeExecutor
from brandpilot.engagement import EngagementHandler
from brandpilot.planning import PlanningService
from brandpilot.creative import CreativeService
from brandpilot.publication import PublicationService
from brandpilot.results import ResultsService
from brandpilot.weekly import WeeklyScheduler, WeeklyReportHandler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--publishing-only", action="store_true", help="Keep scheduled posts independent of slow image-planning jobs")
    parser.add_argument("--worker-id", default=f"{socket.gethostname()}-{time.time_ns()}")
    args = parser.parse_args()

    settings = AppSettings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger("brandpilot.worker")
    if not settings.worker_workspace_id:
        raise SystemExit("BRANDPILOT_WORKSPACE_ID is required for the Phase 2 worker")
    engine = build_engine(settings.database_url, role="brandpilot_app")
    sessions = build_session_factory(engine)
    store = JobStore(
        sessions,
        lease_seconds=settings.job_lease_seconds,
        workspace_id=settings.worker_workspace_id,
        allowed_kinds=("publication.facebook",) if args.publishing_only else None,
    )
    social_handler = SocialSyncHandler(
        sessions, store,
        CredentialCipher({1: settings.credential_encryption_key}, current_version=1),
        MetaConfig(
            app_id=settings.meta_app_id, app_secret=settings.meta_app_secret,
            callback_url=settings.meta_callback_url, graph_version=settings.meta_graph_version,
        ),
        offline=settings.runtime.execution_mode.value == "offline_test",
    )
    storage = LocalStorage(settings.storage_root)
    accounts = AccountService(sessions, app_secret_key=settings.app_secret_key,
        credential_cipher=CredentialCipher({1: settings.credential_encryption_key}, current_version=1),
        session_ttl_seconds=settings.session_ttl_seconds,
        login_window_seconds=settings.login_window_seconds, login_max_attempts=settings.login_max_attempts)
    phase4 = Phase4Service(sessions, accounts, storage, settings.runtime, gemini_model=settings.gemini_model,
        openai_model=settings.openai_model, max_model_calls=settings.agent_max_model_calls,
        max_input_tokens=settings.agent_max_input_tokens, max_output_tokens=settings.agent_max_output_tokens)
    creative_handler = CreativeDirectionHandler(sessions, store, phase4, settings.runtime,
        HermesCreativeExecutor(api_key=settings.gemini_api_key, python_path=settings.hermes_python))
    planning = PlanningService(sessions, accounts)
    publication = PublicationService(sessions, accounts, CreativeService(sessions, accounts, storage), storage)
    results = ResultsService(sessions, accounts, planning, publication)
    social = SocialService(sessions, accounts, social_handler._cipher, social_handler._config, storage,
        offline=settings.runtime.execution_mode.value == "offline_test")
    publishing = ScheduledPublishing(sessions, accounts, planning, publication, social,
        enabled=settings.runtime.execution_mode.value != "offline_test" and social.meta_read_available)
    engagement_handler = EngagementHandler(sessions, store, social_handler._cipher, social_handler._transport,
        offline=settings.runtime.execution_mode.value == "offline_test")
    worker = Worker(args.worker_id, store, storage, social_handler, creative_handler,
        engagement_handler, WeeklyReportHandler(sessions, store, results), FacebookPublicationHandler(publishing, store))
    scheduler = WeeklyScheduler(sessions, store, settings.worker_workspace_id)
    next_tick = 0.0
    logger.info("Worker started as %s", args.worker_id)
    try:
        while True:
            if not args.publishing_only and time.monotonic() >= next_tick:
                scheduler.tick()
                next_tick = time.monotonic() + 60
            worked = worker.process_one()
            if args.once:
                return 0
            if not worked:
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
