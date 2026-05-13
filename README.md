# Custom Komodor Integrations

This repository contains custom integrations that enable third-party tools to send data and events into the Komodor platform.

These integrations are unofficial, built for specific use cases, and may require modification to work in different environments. They are not part of Komodor’s supported product offering and are subject to change without notice.

## Directory Overview

Below is a summary of each integration and example directory. For technical details, see the respective subdirectory's README.

### KlaudiaKBSync
**What:** Syncs knowledge base articles and runbooks from external sources into Komodor.
**Why:** Automates the import of operational knowledge, making it accessible within Komodor. Implemented as a standalone tool, runnable locally or via GitHub Actions. See [klaudia-sync repo](https://github.com/davidcollom/komodor-klaudia-sync).

### LaunchDarkly
**What:** Translates LaunchDarkly webhook events into Komodor custom events.
**Why:** Provides visibility into feature flag changes and alerts within Komodor. Includes AWS Lambda and GCP Cloud Run deployment options.

### PrometheusAlertmanager
**What:** Forwards Komodor monitor webhooks as Prometheus Alertmanager alerts.
**Why:** Enables Komodor to trigger Alertmanager workflows based on platform events. Deployable as an AWS Lambda function.

### PrometheusToKomodor
**What:** Sends Prometheus Alertmanager alerts to Komodor as custom events, either directly or via a middleware service (Go or Python).
**Why:** Correlates Prometheus alerts with Kubernetes events in Komodor for unified incident visibility. Supports both direct and service-backed integration patterns.

---

When adding a new directory, update this section with a summary of what it is and why you would use it.
