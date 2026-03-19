# LaunchDarkly Event Puller

This integration takes webhooks from LaunchDarkly and translates them into readable custom events in Komodor. You can deploy this Python script as an AWS Lambda function fronted by a Lambda Function URL. LaunchDarkly sends webhook events to the Lambda endpoint, which translates them into Komodor custom events and POSTs them to the Komodor Events API.

## Architecture

```
LaunchDarkly Webhook → Lambda Function URL → Lambda Function → Komodor Events API
```

## Setup

1. Create a new AWS Lambda function with a Python 3.9+ runtime
2. Add a `urllib3` Lambda layer or bundle it with the deployment package (the script depends on `urllib3`)
3. Copy the contents of `lambda_function.py` into the Lambda function code editor (or upload as a .zip)
4. Set your Komodor API key in the `KOMODOR_API_KEY` variable on line 14, or load it from AWS Secrets Manager, SSM Parameter Store, or environment variables
5. Create a Lambda Function URL to expose an HTTPS endpoint ([AWS docs](https://docs.aws.amazon.com/lambda/latest/dg/urls-configuration.html#create-url-console))
6. In LaunchDarkly, configure a webhook pointing to the Lambda Function URL

## Configuration

| Variable | Location | Description |
|---|---|---|
| `KOMODOR_API_KEY` | Line 14 in `lambda_function.py` | Your Komodor API key. Replace the placeholder value or load from a secrets manager |
| `KOMODOR_API_URL` | Line 15 in `lambda_function.py` | Komodor Events API endpoint. Defaults to `https://api.komodor.com/mgmt/v1/events` |

## How It Works

The Lambda function receives a LaunchDarkly webhook payload, extracts the event type and alert name, wraps the full payload into a Komodor custom event format, and sends it to the Komodor Events API. Events then appear in the Events tab of the Komodor platform, giving you visibility into LaunchDarkly flag changes and alerts alongside your Kubernetes operational data.

## Dependencies

This function requires the `urllib3` library. You can add it as a Lambda layer or include it in your deployment package. It is not included in the default Lambda Python runtime.

## Notes

Your Komodor API key can be found in the Komodor platform under Settings. For production use, avoid hardcoding the key in the script. Instead, use AWS Secrets Manager, SSM Parameter Store, or a Lambda environment variable to securely manage the key.
