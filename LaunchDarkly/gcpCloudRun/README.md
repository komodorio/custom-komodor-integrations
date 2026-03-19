# LaunchDarkly Event Puller (GCP Cloud Run)

This integration takes webhooks from LaunchDarkly and translates them into readable custom events in Komodor. You can deploy this Python script as a GCP Cloud Run function. LaunchDarkly sends webhook events to the Cloud Run URL, which translates them into Komodor custom events and POSTs them to the Komodor Events API.

## Architecture

```
LaunchDarkly Webhook → Cloud Run URL → Cloud Run Function → Komodor Events API
```

## Setup

1. Create a new GCP Cloud Run function with a Python 3.9+ runtime
2. Deploy `main.py` as the function source. The entry point function is `darkly_to_komodor`
3. Add `urllib3` to your `requirements.txt` (the script depends on it)
4. Set the `KOMODOR_API_KEY` environment variable in the Cloud Run configuration with your Komodor API key
5. Copy the Cloud Run service URL after deployment
6. In LaunchDarkly, configure a webhook pointing to the Cloud Run service URL

## Configuration

| Variable | Source | Description |
|---|---|---|
| `KOMODOR_API_KEY` | Environment variable | Your Komodor API key. Set this in the Cloud Run environment configuration or load from GCP Secret Manager |
| `KOMODOR_API_URL` | `main.py` line 10 | Komodor Events API endpoint. Defaults to `https://api.komodor.com/mgmt/v1/events` |

## How It Works

The Cloud Run function receives a LaunchDarkly webhook payload via HTTP POST. LaunchDarkly sometimes nests the real payload inside a `body` field as a JSON string, so the function handles both flat and nested payloads. It extracts the event type and alert name, wraps the full payload into a Komodor custom event format, and sends it to the Komodor Events API. Events then appear in the Events tab of the Komodor platform, giving you visibility into LaunchDarkly flag changes and alerts alongside your Kubernetes operational data.

## Dependencies

This function requires the `urllib3` library. Include it in your `requirements.txt` file when deploying to Cloud Run.

## Notes

Your Komodor API key can be found in the Komodor platform under Settings. For production use, set the `KOMODOR_API_KEY` as an environment variable in your Cloud Run service configuration or use GCP Secret Manager for secure key management. Avoid hardcoding the key in the source file.
