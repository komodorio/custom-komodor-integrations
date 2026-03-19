"""
Komodor Webhook → Prometheus Alertmanager Translator
=====================================================
AWS Lambda function that receives Komodor monitor webhook payloads
and forwards them as properly formatted alerts to Alertmanager.

Architecture:
  Komodor webhook → API Gateway / Lambda Function URL → this Lambda → Alertmanager

Environment Variables:
  ALERTMANAGER_URL  - e.g. http://alertmanager.monitoring.svc:9093
  WEBHOOK_SECRET    - (optional) shared secret sent by Komodor in the Authorization header
"""

import json
import os
import re
import logging
from urllib import request, error

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://alertmanager.monitoring.svc:9093")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def lambda_handler(event, context):
    """Main Lambda entry point."""

    # --- Parse incoming request ---
    body = event.get("body", "{}")
    if event.get("isBase64Encoded"):
        import base64
        body = base64.b64decode(body).decode("utf-8")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON payload")
        return response(400, {"error": "Invalid JSON"})

    # --- Optional: validate shared secret ---
    if WEBHOOK_SECRET:
        headers = event.get("headers", {})
        auth = headers.get("authorization", headers.get("Authorization", ""))
        if auth != f"Bearer {WEBHOOK_SECRET}":
            logger.warning("Unauthorized request")
            return response(401, {"error": "Unauthorized"})

    # --- Ignore test pings ---
    if payload.get("type") == "Test!":
        logger.info("Test ping received — ignoring")
        return response(200, {"message": "Test ping acknowledged"})

    # --- Map Komodor payload → Alertmanager alert ---
    alert = build_alert(payload)
    logger.info(f"Forwarding alert: {json.dumps(alert, indent=2)}")

    # --- POST to Alertmanager ---
    try:
        forward_to_alertmanager(alert)
    except Exception as e:
        logger.error(f"Failed to forward alert: {e}")
        return response(502, {"error": f"Alertmanager forward failed: {str(e)}"})

    return response(200, {"message": "Alert forwarded to Alertmanager"})


def build_alert(payload: dict) -> dict:
    """
    Translate Komodor webhook payload into Alertmanager alert format.

    Komodor payload fields (observed):
        closeTime, cluster, conditions[], details{annotations, labels},
        issueDetails[], issueURL, monitorType, namespace, resourceKind,
        resourceName, serviceName, startTime, status

    Alertmanager expects:
        labels (dict), annotations (dict), startsAt, endsAt, generatorURL
    """

    # -- Labels: used by Alertmanager for routing, grouping, deduplication --
    labels = {
        "alertname": f"Komodor_{payload.get('monitorType', 'unknown')}",
        "source": "komodor",
        "severity": determine_severity(payload),
    }

    optional_label_fields = {
        "cluster": "cluster",
        "namespace": "namespace",
        "resourceKind": "resource_kind",
        "resourceName": "resource_name",
        "monitorType": "monitor_type",
        "status": "status",
    }
    for komodor_key, alertmanager_key in optional_label_fields.items():
        value = payload.get(komodor_key)
        if value:
            labels[alertmanager_key] = str(value)

    k8s_labels = payload.get("details", {}).get("labels", {})
    for key, value in k8s_labels.items():
        safe_key = _sanitize_label_name(key)
        if safe_key not in labels and value:
            labels[safe_key] = str(value)

    # -- Annotations: human-readable detail, not used for routing --
    conditions = payload.get("conditions") or []
    issue_details = payload.get("issueDetails") or []

    annotations = {
        "summary": (
            f"Komodor {payload.get('monitorType', '')} alert: "
            f"{payload.get('resourceKind', '')}/{payload.get('resourceName', '')} "
            f"in {payload.get('namespace', '')} ({payload.get('cluster', '')})"
        ),
        "description": (
            f"Conditions: {', '.join(conditions)}\n"
            f"Issue Details: {', '.join(issue_details)}\n"
            f"Service: {payload.get('serviceName', 'N/A')}"
        ),
        "komodor_url": payload.get("issueURL", ""),
    }

    k8s_annotations = payload.get("details", {}).get("annotations", {})
    for key, value in k8s_annotations.items():
        safe_key = f"k8s_{_sanitize_label_name(key)}"
        if safe_key not in annotations and value:
            annotations[safe_key] = str(value)

    # -- Timestamps --
    alert = {
        "labels": labels,
        "annotations": annotations,
        "generatorURL": payload.get("issueURL", ""),
    }

    start_time = payload.get("startTime")
    if start_time:
        alert["startsAt"] = start_time

    close_time = payload.get("closeTime")
    if close_time:
        alert["endsAt"] = close_time

    return alert


_LABEL_RE = re.compile(r"[^a-zA-Z0-9_]")


def _sanitize_label_name(name: str) -> str:
    """
    Alertmanager label names must match [a-zA-Z_][a-zA-Z0-9_]*.
    Replace invalid chars (dots, slashes, hyphens) with underscores.
    e.g. 'app.kubernetes.io/name' → 'app_kubernetes_io_name'
    """
    sanitized = _LABEL_RE.sub("_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = f"_{sanitized}"
    return sanitized


def determine_severity(payload: dict) -> str:
    """
    Map Komodor alert context to a severity level.
    Customize this logic based on your team's conventions.
    """
    monitor_type = payload.get("monitorType", "").lower()
    issue_details = [d.lower() for d in (payload.get("issueDetails") or [])]

    if monitor_type == "node":
        return "critical"
    if any(kw in detail for detail in issue_details for kw in ["oomkilled", "nodenotready"]):
        return "critical"

    if monitor_type in ("availability", "deploy", "job", "cronjob"):
        return "warning"

    return "info"


def forward_to_alertmanager(alert: dict):
    """POST the alert to Alertmanager's v2 API."""
    url = f"{ALERTMANAGER_URL.rstrip('/')}/api/v2/alerts"
    data = json.dumps([alert]).encode("utf-8")

    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=10) as resp:
            logger.info(f"Alertmanager responded: {resp.status}")
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {body}")
    except error.URLError as e:
        raise RuntimeError(f"Connection error: {e.reason}")


def response(status_code: int, body: dict) -> dict:
    """Format Lambda proxy response."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
