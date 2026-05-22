from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field


KOMODOR_API_URL = os.getenv(
    "KOMODOR_API_URL",
    "https://api.komodor.com/mgmt/v1/events",
)
KOMODOR_API_KEY = os.getenv("KOMODOR_API_KEY", "")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "10"))

app = FastAPI(title="Alertmanager Komodor Adapter")


class KomodorScope(BaseModel):
    clusters: list[str]
    namespaces: list[str] | None = None
    servicesNames: list[str] | None = None  # Komodor schema spelling


class KomodorEvent(BaseModel):
    eventType: str = Field(..., max_length=30)
    summary: str
    scope: KomodorScope
    severity: str = "information"
    details: dict[str, str] | None = None


def first_value(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if value:
            return str(value)

    return None


def optional_list(value: str | None) -> list[str] | None:
    if value is None or value.strip() == "":
        return None

    return [value]


def map_severity(labels: dict[str, Any], status: str) -> str:
    if status == "resolved":
        return "information"

    severity = str(labels.get("severity", "")).lower()

    if severity in {"critical", "error", "page"}:
        return "error"

    if severity in {"warning", "warn"}:
        return "warning"

    return "information"


def build_event(alert: dict[str, Any]) -> KomodorEvent | None:
    labels = alert.get("labels", {})
    annotations = alert.get("annotations", {})
    status = str(alert.get("status", "firing"))

    cluster = first_value(labels, "cluster")
    if not cluster:
        return None

    alert_name = str(labels.get("alertname", "AlertmanagerAlert"))
    event_type = alert_name[:30]

    summary = (
        annotations.get("summary")
        or annotations.get("description")
        or f"{status.title()}: {alert_name}"
    )

    namespace = first_value(labels, "namespace", "kubernetes_namespace")
    service = first_value(
        labels,
        "service",
        "service_name",
        "app",
        "app_kubernetes_io_name",
        "deployment",
        "statefulset",
        "daemonset",
    )

    scope = KomodorScope(
        clusters=[cluster],
        namespaces=optional_list(namespace),
        servicesNames=optional_list(service),
    )

    details = {
        "status": status,
        "startsAt": str(alert.get("startsAt", "")),
        "endsAt": str(alert.get("endsAt", "")),
        "generatorURL": str(alert.get("generatorURL", "")),
        "fingerprint": str(alert.get("fingerprint", "")),
        **{f"{key}": str(value) for key, value in labels.items()},
    }
    # We want annotations to be included, but we want labels to take precedence in case of key conflicts.
    # so we add annotations after labels with a prefix (if needed).
    [details.update({f"annotation_{key}" if key in details else key: str(value)}) for key, value in annotations.items()]

    return KomodorEvent(
        eventType=event_type,
        summary=str(summary),
        scope=scope,
        severity=map_severity(labels, status),
        details=details,
    )


async def send_to_komodor(event: KomodorEvent) -> None:
    if not KOMODOR_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="KOMODOR_API_KEY environment variable is not set",
        )

    headers = {
        "x-api-key": KOMODOR_API_KEY,
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            KOMODOR_API_URL,
            headers=headers,
            json=event.model_dump(exclude_none=True),
        )

    if response.status_code != 201:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Komodor API request failed",
                "status_code": response.status_code,
                "body": response.text,
            },
        )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/alertmanager")
async def alertmanager_webhook(request: Request) -> dict[str, int]:
    payload = await request.json()
    alerts = payload.get("alerts", [])

    sent = 0
    skipped = 0

    for alert in alerts:
        event = build_event(alert)
        if event is None:
            skipped += 1
            continue

        await send_to_komodor(event)
        sent += 1

    return {"received": len(alerts), "sent": sent, "skipped": skipped}
