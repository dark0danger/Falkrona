"""Small application-side client for Hermes's private run API."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol
from urllib import error, parse, request

from .outcomes import OutcomeCode, RunOutcome


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes


class Transport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> HttpResponse:
        req = request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                return HttpResponse(response.status, response.read())
        except error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read())


class HermesClient:
    def __init__(
        self,
        base_url: str,
        service_key: str,
        *,
        transport: Transport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        parsed = parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Hermes must use a loopback HTTP endpoint in Phase 0")
        self._base_url = base_url.rstrip("/")
        self._service_key = service_key.strip()
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = timeout_seconds

    def start_run(
        self,
        prompt: str,
        *,
        session_id: str,
        idempotency_key: str,
    ) -> RunOutcome:
        if not self._service_key:
            return RunOutcome(OutcomeCode.MISSING_KEY, "Hermes service key is missing.")
        if not prompt.strip():
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Run input cannot be empty.")

        payload = json.dumps({"input": prompt, "session_id": session_id}).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._service_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        try:
            response = self._transport.send(
                "POST",
                f"{self._base_url}/v1/runs",
                headers,
                payload,
                self._timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, str(exc))

        if response.status in {401, 403}:
            return RunOutcome(OutcomeCode.UNAUTHORIZED, "Hermes rejected the service key.")
        if response.status == 429:
            return RunOutcome(OutcomeCode.QUOTA_EXHAUSTED, "Hermes or its provider is rate limited.")
        if response.status >= 500:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, "Hermes service failed.")

        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Hermes returned invalid JSON.")

        run_id = data.get("run_id") if isinstance(data, dict) else None
        if response.status != 202 or not isinstance(run_id, str) or not run_id:
            return RunOutcome(
                OutcomeCode.MALFORMED_OUTPUT,
                "Hermes did not return a valid accepted run.",
                data=data if isinstance(data, dict) else {},
            )
        return RunOutcome(OutcomeCode.OK, "Hermes run accepted.", run_id=run_id, data=data)

    def get_run(self, run_id: str) -> RunOutcome:
        """Read a run and translate Hermes terminal states into application outcomes."""
        if not self._service_key:
            return RunOutcome(OutcomeCode.MISSING_KEY, "Hermes service key is missing.")
        if not run_id.strip():
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Run ID cannot be empty.")

        headers = {"Authorization": f"Bearer {self._service_key}"}
        try:
            response = self._transport.send(
                "GET",
                f"{self._base_url}/v1/runs/{parse.quote(run_id, safe='')}",
                headers,
                None,
                self._timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, str(exc), run_id=run_id)

        if response.status in {401, 403}:
            return RunOutcome(OutcomeCode.UNAUTHORIZED, "Hermes rejected the service key.")
        if response.status == 429:
            return RunOutcome(OutcomeCode.QUOTA_EXHAUSTED, "Hermes or its provider is rate limited.")
        if response.status >= 500:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, "Hermes service failed.")

        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Hermes returned invalid JSON.")
        if response.status != 200 or not isinstance(data, dict):
            return RunOutcome(
                OutcomeCode.MALFORMED_OUTPUT,
                "Hermes did not return a valid run status.",
                run_id=run_id,
                data=data if isinstance(data, dict) else {},
            )

        status = data.get("status")
        if status in {"cancelled", "interrupted"}:
            return RunOutcome(
                OutcomeCode.CANCELLED,
                data.get("error") or "Hermes run was cancelled.",
                run_id=run_id,
                data=data,
            )
        if status == "failed":
            return RunOutcome(
                OutcomeCode.TOOL_ERROR,
                data.get("error") or "Hermes run failed.",
                run_id=run_id,
                data=data,
            )
        if status not in {
            "queued",
            "running",
            "stopping",
            "waiting_for_approval",
            "completed",
        }:
            return RunOutcome(
                OutcomeCode.MALFORMED_OUTPUT,
                "Hermes returned an unknown run status.",
                run_id=run_id,
                data=data,
            )
        return RunOutcome(OutcomeCode.OK, f"Hermes run is {status}.", run_id=run_id, data=data)

    def cancel_run(self, run_id: str) -> RunOutcome:
        """Ask Hermes to cooperatively stop one run without retrying it elsewhere."""
        if not self._service_key:
            return RunOutcome(OutcomeCode.MISSING_KEY, "Hermes service key is missing.")
        if not run_id.strip():
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Run ID cannot be empty.")
        try:
            response = self._transport.send(
                "POST",
                f"{self._base_url}/v1/runs/{parse.quote(run_id, safe='')}/stop",
                {"Authorization": f"Bearer {self._service_key}", "Content-Type": "application/json"},
                b"{}",
                self._timeout_seconds,
            )
        except (OSError, TimeoutError) as exc:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, str(exc), run_id=run_id)
        if response.status in {401, 403}:
            return RunOutcome(OutcomeCode.UNAUTHORIZED, "Hermes rejected the service key.", run_id=run_id)
        if response.status == 429:
            return RunOutcome(OutcomeCode.QUOTA_EXHAUSTED, "Hermes is rate limited.", run_id=run_id)
        if response.status >= 500:
            return RunOutcome(OutcomeCode.TRANSPORT_ERROR, "Hermes service failed.", run_id=run_id)
        if response.status not in {200, 202}:
            return RunOutcome(OutcomeCode.MALFORMED_OUTPUT, "Hermes rejected the cancellation request.", run_id=run_id)
        return RunOutcome(OutcomeCode.CANCELLED, "Hermes stop was requested.", run_id=run_id)
