"""Restartable Phase 1 worker and deterministic local artifact handler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from .jobs import JobClaim, JobStore
from .social import SocialError, SocialSyncHandler
from .storage import LocalStorage


class WorkerTerminated(RuntimeError):
    """Testable stand-in for termination after a durable checkpoint."""


@dataclass(slots=True)
class ArtifactJobHandler:
    store: JobStore
    storage: LocalStorage

    def run(
        self,
        claim: JobClaim,
        *,
        terminate_after_checkpoint: bool = False,
    ) -> None:
        artifact_key = claim.checkpoint.get("artifact_key")
        if not artifact_key:
            prefix = f"workspaces/{claim.workspace_id}/" if claim.workspace_id else ""
            artifact_key = f"{prefix}jobs/{claim.id}/result.json"
            content = json.dumps(
                {"job_id": claim.id, "payload": claim.payload},
                ensure_ascii=True,
                sort_keys=True,
            ).encode("utf-8")
            self.storage.put_bytes(artifact_key, content)
            self.store.checkpoint(
                claim.id,
                claim.lease_owner,
                {"artifact_key": artifact_key, "artifact_written": True},
            )
            if terminate_after_checkpoint:
                raise WorkerTerminated("Worker terminated after artifact checkpoint")
        self.store.complete(
            claim.id,
            claim.lease_owner,
            output_ref=artifact_key,
        )


class Worker:
    def __init__(
        self, worker_id: str, store: JobStore, storage: LocalStorage,
        social_handler: SocialSyncHandler | None = None,
        creative_handler=None,
        engagement_handler=None, weekly_handler=None,
        publication_handler=None,
    ) -> None:
        self.worker_id = worker_id
        self.store = store
        self.handler = ArtifactJobHandler(store, storage)
        self.social_handler = social_handler
        self.creative_handler = creative_handler
        self.engagement_handler, self.weekly_handler = engagement_handler, weekly_handler
        self.publication_handler = publication_handler

    def process_one(self, *, terminate_after_checkpoint: bool = False) -> bool:
        claim = self.store.claim_next(self.worker_id)
        if claim is None:
            return False
        if claim.kind == "publication.facebook" and self.publication_handler is not None:
            self.publication_handler.run(claim)
            return True
        if claim.kind in {"creative.direction", "branding.survey", "planning.week"} and self.creative_handler is not None:
            self.creative_handler.run(claim)
            return True
        if claim.kind == "results.weekly" and self.weekly_handler is not None:
            self.weekly_handler.run(claim)
            return True
        if claim.kind == "social.engagement" and self.engagement_handler is not None:
            self.engagement_handler.run(claim)
            return True
        if claim.kind == "social.meta.sync" and self.social_handler is not None:
            try:
                self.social_handler.run(claim)
            except SocialError as exc:
                self.social_handler.record_error(claim, exc.code)
                retryable = exc.code in {"provider_unavailable", "rate_limited", "pagination_limit"}
                self.store.fail(
                    claim.id, self.worker_id, exc.code, retryable=retryable,
                    retry_at=(
                        datetime.now(timezone.utc)
                        + timedelta(seconds=min(300, 30 * claim.attempts))
                    ) if retryable else None,
                )
            return True
        if claim.kind != "fixture.artifact":
            self.store.fail(
                claim.id,
                self.worker_id,
                f"Unsupported job kind: {claim.kind}",
                retryable=False,
            )
            return True
        self.handler.run(
            claim,
            terminate_after_checkpoint=terminate_after_checkpoint,
        )
        return True
