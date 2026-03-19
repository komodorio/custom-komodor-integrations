# Komodor Webhook to Prometheus Alertmanager

This integration receives Komodor monitor webhook payloads and forwards them as properly formatted alerts to Prometheus Alertmanager. You can deploy this Python script as an AWS Lambda function fronted by API Gateway or a Lambda Function URL. Komodor sends webhook events to the Lambda endpoint, which translates them into the Alertmanager alert format and POSTs them to your Alertmanager instance.

## Architecture

```
Komodor Monitor Webhook → API Gateway / Lambda Function URL → Lambda Function → Alertmanager
```

## Setup

1. Create a new AWS Lambda function with a Python 3.9+ runtime
2. Copy the contents of `lambda_function.py` into the Lambda function code editor (or upload as a .zip)
3. Configure the required environment variables (see below)
4. Create an API Gateway trigger or enable a Lambda Function URL to expose an HTTPS endpoint
5. In the Komodor platform, configure a webhook monitor pointing to the Lambda endpoint URL

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ALERTMANAGER_URL` | Yes | Full URL of your Alertmanager instance (e.g. `http://alertmanager.monitoring.svc:9093`) |
| `WEBHOOK_SECRET` | No | Shared secret for validating incoming requests. If set, Komodor must send it as a Bearer token in the Authorization header |

## Alert Mapping

The function translates Komodor webhook fields into Alertmanager alert format:

**Labels** (used for routing, grouping, deduplication): alertname, source, severity, cluster, namespace, resource kind, resource name, monitor type, status, plus any Kubernetes labels from the payload.

**Annotations** (human readable context): summary, description, Komodor issue URL, plus any Kubernetes annotations from the payload.

**Severity** is derived automatically based on monitor type: node issues and OOMKilled map to critical, availability/deploy/job failures map to warning, everything else maps to info.

**Auto resolve**: When Komodor reports an issue as closed (closeTime is set), the function sets endsAt on the alert so Alertmanager resolves it automatically.

## Notes

Please input your Alertmanager URL in the `ALERTMANAGER_URL` environment variable. If you want to secure the endpoint, set the `WEBHOOK_SECRET` variable and configure the same secret in your Komodor webhook settings. The function uses only Python standard library modules, so no additional dependencies or layers are needed.
