# Webhook to Komodor RCA to Slack

Provider-neutral webhook service that:

1. Accepts an event at `POST /webhooks/rca`.
2. Maps its resource fields or labels into Komodor's `POST /api/v2/klaudia/rca/sessions`.
3. Polls `GET /api/v2/klaudia/rca/sessions/{id}` with bounded exponential backoff.
4. Posts the completed RCA to Slack.

The Komodor request and response types match the [Komodor Public API OpenAPI spec](https://api.komodor.com/api/docs/doc.json).

## Webhook contract

The recommended generic payload is:

```json
{
  "title": "Checkout API error rate",
  "status": "firing",
  "severity": "critical",
  "fingerprint": "unique-event-id",
  "issueId": "optional-external-issue-id",
  "metadata": {
    "monitorUrl": "https://monitoring.example/incidents/123",
    "team": "checkout",
    "runbook": "checkout-api-errors"
  },
  "resource": {
    "kind": "Deployment",
    "name": "checkout-api",
    "namespace": "production",
    "clusterName": "prod-eu"
  }
}
```

Alternatively, send a `labels` map:

```json
{
  "title": "Pods crashed",
  "status": "firing",
  "severity": "critical",
  "labels": {
    "kind": "Deployment",
    "workload_name": "checkout-api",
    "namespace": "production",
    "clusterId": "prod-eu"
  }
}
```

Accepted label aliases:

| Komodor field | Accepted labels, in priority order |
| --- | --- |
| `kind` | `kind`, `workload_kind`, `resource_kind`, then `DEFAULT_WORKLOAD_KIND` |
| `name` | `name`, `workload_name`, `workload`, `service_name`, `pod_name` |
| `namespace` | `namespace`, `k8s_namespace` |
| `clusterName` | `clusterName`, `cluster_name`, `cluster`, `clusterId`, `cluster_id` |
| `issueId` | event `issueId`, label `issueId`, label `issue_id` |

Nested `alert.labels` payloads and `POST /webhooks/groundcover` remain supported for backward compatibility.

Only `firing` events with severity `critical` are processed by default. This protects the Komodor RCA daily allowance. Events without a status are processed, but events without a severity are ignored under the default severity filter.

- Change `PROCESS_STATUSES` to a comma-separated status allowlist.
- Change `PROCESS_SEVERITIES` to a comma-separated severity allowlist, for example `critical,high`.
- Set `PUBLISH_CUSTOM_EVENT=false` to disable custom-event publication.

`metadata` accepts arbitrary JSON values. It is included in Slack details and converted to string-valued details when publishing the Komodor custom event.

After Komodor returns an RCA session ID, the service publishes a scoped `klaudia-rca-triggered` custom event using `POST /api/v2/services/k8s-events`. It includes the RCA session ID, session URL, fingerprint, issue ID, and supplied metadata. Custom-event publication is best-effort and does not interrupt the RCA workflow.

Webhook requests are authenticated using a constant-time bearer-token comparison. Send the token as either `Authorization: Bearer <token>` or `X-Webhook-Token: <token>`.

Both Terraform stacks generate a 48-character webhook token by default and store it in the platform secret manager. Generation uses an ephemeral Terraform value and a provider write-only secret field, so the token is not stored in Terraform plan or state.

Retrieve it after deployment and configure the webhook sender:

```bash
# Google Cloud
gcloud secrets versions access latest --secret=rca-webhook-token

# AWS
aws secretsmanager get-secret-value \
  --secret-id rca-webhook-token \
  --query SecretString \
  --output text
```

Increment `webhook_token_generation` to rotate it. Set `generate_webhook_token=false` to use an existing secret instead.

The generated token protects a public HTTPS endpoint with application-layer bearer authentication. Keep the endpoint behind TLS, rotate the token periodically, and avoid putting it in query strings. A static token does not provide replay protection; webhook providers that support signed timestamped requests can be integrated later for stronger authentication.

Platform request authentication is intentionally disabled:

- Cloud Run uses `invoker_iam_disabled = true`; there is no `allUsers` Invoker role binding.
- Lambda Function URL uses `authorization_type = "NONE"`. AWS still requires public `lambda:InvokeFunctionUrl` and `lambda:InvokeFunction` resource-policy permissions for a public Function URL; these permissions do not authenticate requests.

The Cloud Run service account and Lambda execution role are not request-authentication controls. They remain least-privilege runtime identities required to read secrets and write platform logs.

## Logging and auditing

The service writes one-line structured JSON logs to stdout for automatic ingestion by Google Cloud Logging and AWS CloudWatch Logs. Set `LOG_LEVEL` to `debug`, `info`, `warn`, or `error`; the default is `info`.

Audit records use stable `event` values and include applicable fields such as:

- `request_id`, returned to callers as `X-Request-ID`
- `fingerprint`, `issue_id`, event status and severity
- cluster, namespace, resource kind, and resource name
- RCA session ID, outcome, duration, poll attempt, and result counts
- Komodor endpoint category, HTTP status, and duration
- Slack delivery mode, message type, HTTP status, and duration

Useful event values include `webhook_received`, `webhook_rejected`, `webhook_ignored`, `webhook_accepted`, `rca_session_created`, `rca_polled`, `rca_investigation_completed`, `custom_event_published`, `slack_posted`, and their corresponding failure events.

Secrets, authorization headers, complete inbound payloads, Slack message bodies, RCA evidence content, and remediation content are intentionally excluded from logs.

Example Google Cloud Logging filter:

```text
resource.type="cloud_run_revision"
jsonPayload.service="webhook-komodor-rca"
jsonPayload.event="rca_investigation_completed"
```

Example CloudWatch Logs Insights query:

```text
fields @timestamp, event, request_id, session_id, resource_name, duration_ms
| filter service = "webhook-komodor-rca"
| sort @timestamp desc
```

## Slack

Configure either:

- `SLACK_BOT_TOKEN` plus `SLACK_CHANNEL_ID`: posts an initial “RCA triggered” parent message immediately, then posts the completed RCA summary, evidence, remediation, operations, and metadata in its thread.
- `SLACK_WEBHOOK_URI`: posts the completed RCA summary and details in one combined message.

Incoming Slack webhooks do not return the message timestamp required to create threaded replies.

For threaded delivery in either Terraform stack, configure:

```hcl
slack_delivery_mode       = "bot"
slack_bot_token_secret_id = "slack-bot-token"
slack_channel_id           = "C0123456789"
```

The Slack app needs the `chat:write` and `reactions:write` bot scopes and must be installed and invited to the target channel.

Bot mode adds `:hourglass_flowing_sand:` to the parent message while the RCA runs. It replaces that reaction with `:white_check_mark:` after the result and thread details are delivered, or `:x:` if the investigation or thread delivery fails. Reactions are best-effort and do not interrupt the RCA workflow.

Secrets can be supplied directly or through files. For each secret, the direct environment variable takes precedence:

- `KOMODOR_API_KEY` or `KOMODOR_API_KEY_FILE`
- `SLACK_WEBHOOK_URI` or `SLACK_WEBHOOK_URI_FILE`
- `SLACK_BOT_TOKEN` or `SLACK_BOT_TOKEN_FILE`
- `WEBHOOK_TOKEN` or `WEBHOOK_TOKEN_FILE`

## Run locally

```bash
cp .env.example .env
# Fill in .env, then:
set -a; source .env; set +a
go run .
```

Health check: `GET /healthz`

```bash
docker build -t webhook-komodor-rca .
docker run --env-file .env -p 8080:8080 webhook-komodor-rca
```

## Deploy to Google Cloud Run with Terraform

The application has no Google Cloud SDK dependencies. Google-specific configuration lives only in [`terraform/cloud-run/`](terraform/cloud-run/).

Terraform expects an existing container image and existing Secret Manager secrets. Secret values are not read into Terraform state. Cloud Run resolves the references and exposes them as normal environment variables:

- `KOMODOR_API_KEY`
- `SLACK_WEBHOOK_URI`
- `WEBHOOK_TOKEN`

Create the secrets and versions:

```bash
gcloud secrets create komodor-api-key --replication-policy=automatic
printf '%s' 'your-komodor-api-key' | gcloud secrets versions add komodor-api-key --data-file=-

gcloud secrets create slack-webhook-uri --replication-policy=automatic
printf '%s' 'https://hooks.slack.com/services/...' | gcloud secrets versions add slack-webhook-uri --data-file=-

```

For threaded Slack delivery, create a bot-token secret instead of the incoming-webhook secret:

```bash
gcloud secrets create slack-bot-token --replication-policy=automatic
printf '%s' 'xoxb-your-token' | gcloud secrets versions add slack-bot-token --data-file=-
```

Build and push the image, then deploy:

```bash
gcloud artifacts repositories create apps \
  --repository-format=docker \
  --location=europe-west2

gcloud builds submit \
  --tag europe-west2-docker.pkg.dev/PROJECT_ID/apps/webhook-komodor-rca:latest

cd terraform/cloud-run
cp terraform.tfvars.example terraform.tfvars
# Set project_id and container_image.
terraform init
terraform apply
terraform output -raw webhook_url
```

The Cloud Run service account receives Secret Manager access only to the configured secrets.

The service acknowledges webhooks with `202` and continues polling in the background. Terraform keeps one instance and always-allocated CPU by default, but the work remains in memory: instance termination can interrupt an investigation. For strict delivery guarantees, place a provider-neutral durable queue in front of the investigation worker.

## Deploy to AWS Lambda with Terraform

AWS-specific configuration lives only in [`terraform/lambda/`](terraform/lambda/). The Lambda image uses [AWS Lambda Web Adapter](https://github.com/awslabs/aws-lambda-web-adapter), so the application remains a normal portable HTTP server.

Lambda freezes background work after returning a response. The AWS stack therefore sets `SYNCHRONOUS_PROCESSING=true`; the webhook request remains open until the RCA investigation and Slack post finish. Lambda's maximum execution time is 15 minutes, so the stack uses a 14-minute investigation timeout.

Create the secrets:

```bash
aws secretsmanager create-secret \
  --name komodor-api-key \
  --secret-string 'your-komodor-api-key'

aws secretsmanager create-secret \
  --name slack-webhook-uri \
  --secret-string 'https://hooks.slack.com/services/...'

```

For threaded Slack delivery, create a bot-token secret instead of the incoming-webhook secret:

```bash
aws secretsmanager create-secret \
  --name slack-bot-token \
  --secret-string 'xoxb-your-token'
```

Build and push the Lambda-compatible ARM64 image:

```bash
aws ecr create-repository --repository-name webhook-komodor-rca
aws ecr get-login-password --region eu-west-2 |
  docker login --username AWS --password-stdin ACCOUNT_ID.dkr.ecr.eu-west-2.amazonaws.com

docker buildx build \
  --platform linux/arm64 \
  -f Dockerfile.lambda \
  -t ACCOUNT_ID.dkr.ecr.eu-west-2.amazonaws.com/webhook-komodor-rca:latest \
  --push .

cd terraform/lambda
cp terraform.tfvars.example terraform.tfvars
# Set container_image_uri.
terraform init
terraform apply
terraform output -raw webhook_url
```

The Lambda configuration contains only Secrets Manager ARNs. An AWS-only bootstrap binary fetches those values using the Lambda execution role, writes mode-`0600` files under Lambda's encrypted `/tmp` filesystem, and starts the portable application with `KOMODOR_API_KEY_FILE`, `SLACK_WEBHOOK_URI_FILE`, and `WEBHOOK_TOKEN_FILE`.

Secret values are not stored in Terraform state or Lambda environment variables. The Lambda execution role can read only the three configured secrets.

## Test

```bash
go test ./...
```
