# Alertmanager to Komodor Custom Events

This repository provides two supported ways to send Alertmanager alerts to Komodor as Custom Events:

1. **Native Alertmanager webhook** — Alertmanager sends directly to the Komodor API. (Requires Alertmanager 0.32.0 and above)
2. **Service-backed webhook middleware** — Alertmanager sends to a small middleware service, which then sends events to Komodor.

Both approaches create Komodor Custom Events using the `/mgmt/v1/events` API endpoint.

---

## Repository layout

```text
.
├── native-config.yaml          # Direct Alertmanager -> Komodor configuration
├── middleware-config.yaml      # Alertmanager -> middleware -> Komodor configuration
├── webhook-middleware.go       # Go middleware implementation
└── webhook-middleware.py       # Python middleware implementation
```

---

## Scope contract

Alerts sent to Komodor must include a `cluster` label.

This label is used to populate `scope.clusters` in Komodor custom events and is required for useful event correlation.

`namespace` and `service` are optional, but strongly recommended for better workload-level correlation.

### Minimum required labels

```yaml
labels:
  cluster: prod-eks-01
```

### Recommended labels

```yaml
labels:
  cluster: prod-eks-01
  namespace: payments
  service: checkout-api
  severity: warning
```

### Recommended Prometheus configuration

For multi-cluster environments, prefer setting `cluster` once using Prometheus `external_labels`:

```yaml
global:
  external_labels:
    cluster: prod-eks-01
```

This avoids having to add the label manually to every alerting rule.

---

## Option 1: Native Alertmanager webhook

The native webhook approach sends events directly from Alertmanager to Komodor.

```text
Alertmanager -> Komodor Custom Events API
```

Use the configuration in:

```text
native-config.yaml
```

This is the simplest deployment model because there is no additional service to run.

### When to use this option

Use the native webhook option when the customer's Alertmanager version supports:

* `webhook_configs[].payload`
* `webhook_configs[].max_alerts`
* `http_config.http_headers`

This allows Alertmanager to:

* Render the Komodor event body directly.
* Send only one alert per webhook request using `max_alerts: 1`.
* Add the required `x-api-key` header.
* Send directly to `https://api.komodor.com/mgmt/v1/events`.

### Benefits

* No additional service to deploy.
* Fewer moving parts.
* Lower operational overhead.
* Configuration lives entirely in Alertmanager.

### Trade-offs

* Requires a sufficiently recent Alertmanager version.
* Payload templating can become hard to maintain in YAML.
* Limited ability to validate, enrich, retry, or log individual events.
* Missing optional fields may result in empty values being sent unless carefully handled.

### Native webhook flow

```text
Alertmanager
  └── native-config.yaml
        └── webhook_configs[].payload
              └── POST https://api.komodor.com/mgmt/v1/events
```

### Example routing contract

The Komodor route should only match alerts that include a non-empty `cluster` label:

```yaml
routes:
  - receiver: komodor-custom-events
    matchers:
      - cluster=~".+"
    continue: true
```

This prevents incomplete alerts from being sent to Komodor.

---

## Option 2: Service-backed webhook middleware

The service-backed approach sends Alertmanager webhooks to a small middleware service. The middleware transforms each Alertmanager alert into a Komodor Custom Event and sends it to the Komodor API.

```text
Alertmanager -> Webhook Middleware -> Komodor Custom Events API
```

Use the Alertmanager and Kubernetes configuration in:

```text
middleware-config.yaml
```

Use one of the middleware implementations:

```text
webhook-middleware.go
webhook-middleware.py
```

The Go and Python implementations perform the same logical role. You only need to deploy one of them.

### When to use this option

Use the service-backed middleware option when:

* The customer's Alertmanager version is old or unknown.
* `webhook_configs[].payload` is not available.
* `http_config.http_headers` is not available or awkward to configure.
* You want better validation, logging, retries, or future enrichment.
* You want to keep the Komodor API key out of Alertmanager configuration.

### Benefits

* Works with older Alertmanager versions that support basic webhooks.
* Keeps Alertmanager configuration simple and stable.
* Allows proper validation of the required `cluster` label.
* Easier to add structured logging, metrics, retries, or dead-letter handling later.
* Easier to unit test than complex Alertmanager templates.

### Trade-offs

* Requires deploying and operating one small service.
* Adds another hop between Alertmanager and Komodor.
* Requires a Kubernetes Deployment, Service, and Secret if running in-cluster.

### Service-backed flow

```text
Alertmanager
  └── middleware-config.yaml
        └── webhook_configs[].url
              └── Webhook Middleware
                    └── POST https://api.komodor.com/mgmt/v1/events
```

The middleware expects Alertmanager's native webhook payload and handles the transformation to the Komodor event schema.

---

## Go middleware

The Go implementation is in:

```text
webhook-middleware.go
```

Use this when you want a small compiled binary with simple runtime dependencies.

Expected environment variables:

| Variable          | Required | Default                                  | Description                                     |
| ----------------- | -------: | ---------------------------------------- | ----------------------------------------------- |
| `KOMODOR_API_KEY` |      Yes | -                                        | Komodor API key used as the `x-api-key` header. |
| `KOMODOR_API_URL` |       No | `https://api.komodor.com/mgmt/v1/events` | Komodor Custom Events endpoint.                 |
| `LISTEN_ADDR`     |       No | `:8080`                                  | HTTP listen address for the middleware.         |
| `REQUEST_TIMEOUT` |       No | `10s`                                    | Timeout for requests to Komodor.                |

Run locally:

```bash
export KOMODOR_API_KEY="your-komodor-api-key"
go run webhook-middleware.go
```

---

## Python middleware

The Python implementation is in:

```text
webhook-middleware.py
```

Use this when you want a quick-to-read implementation for testing, demonstration, or customer-side customisation.

Expected environment variables:

| Variable                  | Required | Default                                  | Description                                     |
| ------------------------- | -------: | ---------------------------------------- | ----------------------------------------------- |
| `KOMODOR_API_KEY`         |      Yes | -                                        | Komodor API key used as the `x-api-key` header. |
| `KOMODOR_API_URL`         |       No | `https://api.komodor.com/mgmt/v1/events` | Komodor Custom Events endpoint.                 |
| `REQUEST_TIMEOUT_SECONDS` |       No | `10`                                     | Timeout for requests to Komodor.                |

Example dependencies:

```text
fastapi
uvicorn[standard]
httpx
pydantic
```

Run locally:

```bash
export KOMODOR_API_KEY="your-komodor-api-key"
uvicorn webhook-middleware:app --host 0.0.0.0 --port 8080
```

> Note: because the filename contains a hyphen, Python module execution may require renaming the file to `webhook_middleware.py` or running it with an import-safe module path depending on how it is packaged.

---

## Mapping Alertmanager alerts to Komodor events

Each Alertmanager alert is mapped to one Komodor Custom Event.

`max_alerts: 1` is recommended so that each webhook request contains a single alert, making the event mapping deterministic.

| Alertmanager value        | Komodor field           | Notes                                                       |
| ------------------------- | ----------------------- | ----------------------------------------------------------- |
| `labels.alertname`        | `eventType`             | Truncated to 30 characters.                                 |
| `annotations.summary`     | `summary`               | Preferred summary source.                                   |
| `annotations.description` | `summary`               | Fallback if `summary` is not set.                           |
| `labels.cluster`          | `scope.clusters[]`      | Required.                                                   |
| `labels.namespace`        | `scope.namespaces[]`    | Optional, recommended.                                      |
| `labels.service`          | `scope.servicesNames[]` | Optional, recommended.                                      |
| `labels.severity`         | `severity`              | Mapped to `information`, `warning`, or `error`.             |
| alert metadata            | `details`               | Useful labels, annotations, fingerprint, and generator URL. |

---

## Severity mapping

Suggested severity mapping:

| Alertmanager severity | Komodor severity |
| --------------------- | ---------------- |
| `critical`            | `error`          |
| `error`               | `error`          |
| `page`                | `error`          |
| `warning`             | `warning`        |
| `warn`                | `warning`        |
| anything else         | `information`    |
| resolved alerts       | `information`    |

---

## Choosing between the two options

Use this as the decision rule:

| Requirement                                   | Recommended option        | Files                                                        |
| --------------------------------------------- | ------------------------- | ------------------------------------------------------------ |
| Alertmanager is recent and supports `payload` | Native webhook            | `native-config.yaml`                                         |
| Alertmanager version is old or unknown        | Service-backed middleware | `middleware-config.yaml`, plus one middleware implementation |
| Lowest number of moving parts                 | Native webhook            | `native-config.yaml`                                         |
| Strong validation and observability           | Service-backed middleware | `webhook-middleware.go` or `webhook-middleware.py`           |
| Easier long-term extensibility                | Service-backed middleware | `webhook-middleware.go` or `webhook-middleware.py`           |
| No custom code allowed                        | Native webhook            | `native-config.yaml`                                         |
| Customer allows a tiny internal service       | Service-backed middleware | `middleware-config.yaml`                                     |

---

## Recommendation

Start with the **native webhook** approach if the customer's Alertmanager version supports `payload`, `max_alerts`, and custom HTTP headers.

Use the **service-backed webhook middleware** approach when Alertmanager support is uncertain, when the customer needs stronger validation, or when this integration may grow over time.

In both cases, make `labels.cluster` a hard requirement for any alert sent to Komodor.
