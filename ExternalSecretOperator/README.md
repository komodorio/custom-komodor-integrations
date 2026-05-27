# External Secrets Operator + Komodor Agent Demo

This repository demonstrates a simple end-to-end flow where the **External Secrets Operator (ESO)** syncs a value from a secret provider into a Kubernetes `Secret`, and the **Komodor Agent Helm chart** consumes that generated secret using the `apiKeySecret` value.

The example is intentionally lightweight and designed for demos, testing, and explaining the flow between:

```text
Secret Provider
      ↓
External Secrets Operator
      ↓
ExternalSecret
      ↓
Kubernetes Secret
      ↓
Komodor Agent Helm Chart
```

## ⚠️ Important warning

This setup is for **demonstration purposes only**.

The example uses the ESO `fake` provider to keep the demo self-contained. This is useful for proving the Kubernetes and Helmfile flow, but it should **not** be used for production or customer environments.

For any real deployment, strongly prefer a proper external key or secret management system such as:

- HashiCorp Vault
- AWS Secrets Manager
- Google Secret Manager
- Azure Key Vault
- 1Password Connect
- Doppler
- Any other supported enterprise secret backend

The Komodor API key should be managed outside Git, outside Helm values, and outside plain-text Kubernetes manifests.

## What this demo deploys

This demo uses Helmfile to deploy three logical pieces:

1. **External Secrets Operator**

   Installed from the upstream External Secrets Helm chart.

2. **Local demo chart**

   A small local Helm chart that creates:

   - `SecretStore`
   - `ExternalSecret`

   The `SecretStore` uses ESO’s fake provider for demo purposes.

3. **Komodor Agent**

   Installed from the Komodorio Helm chart.

   The Komodor Agent is configured to read its API key from the Kubernetes `Secret` created by ESO.

## Why this approach?

The goal is to avoid passing the Komodor API key directly into the Komodor Agent Helm release.

Instead of this:

```yaml
apiKey: my-plain-text-api-key
```

The chart is configured like this:

```yaml
apiKeySecret: komodor-agent-api-key
```

That means the Komodor Agent expects an existing Kubernetes `Secret` named:

```text
komodor-agent-api-key
```

ESO is responsible for creating and managing that secret.

This creates a cleaner ownership model:

```text
Platform team
  ├── Installs External Secrets Operator
  ├── Configures access to the organisation's secret store
  └── Controls how secrets enter the cluster

Application / integration team
  ├── Defines ExternalSecret resources
  ├── References synced Kubernetes Secrets
  └── Avoids committing sensitive values into Git
```

## Resource flow

The flow looks like this:

```text
1. Helmfile installs External Secrets Operator
2. Helmfile deploys the local eso-demo chart
3. The eso-demo chart creates a SecretStore
4. The eso-demo chart creates an ExternalSecret
5. ESO reconciles that ExternalSecret
6. ESO creates the Kubernetes Secret named komodor-agent-api-key
7. Helmfile deploys the Komodor Agent
8. The Komodor Agent reads the API key from the synced Kubernetes Secret
```

## Example Helmfile flow

The intended deployment order is:

```yaml
releases:
  - name: external-secrets
    namespace: external-secrets

  - name: eso-demo
    namespace: komodor
    needs:
      - external-secrets/external-secrets

  - name: komodor-agent
    namespace: komodor
    needs:
      - komodor/eso-demo
```

This ensures that:

1. ESO is installed first.
2. The demo `ExternalSecret` is created second.
3. The Komodor Agent is deployed after the expected Kubernetes `Secret` exists.

## Example SecretStore

For this demo, the `SecretStore` uses ESO’s fake provider:

```yaml
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata:
  name: demo-secret-store
  namespace: komodor
spec:
  provider:
    fake:
      data:
        - key: /demo/komodor
          value: replace-me-with-a-demo-api-key
```

The fake provider exposes a value at:

```text
/demo/komodor
```

In a real deployment, this would be replaced with a proper provider configuration such as Vault, AWS Secrets Manager, Google Secret Manager, or Azure Key Vault.

## Example ExternalSecret

The `ExternalSecret` reads the value from the `SecretStore` and writes it into a Kubernetes `Secret`:

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: demo-komodor-agent-secret
  namespace: komodor
spec:
  refreshInterval: 30s
  secretStoreRef:
    kind: SecretStore
    name: demo-secret-store
  target:
    name: komodor-agent-api-key
    creationPolicy: Owner
    deletionPolicy: Retain
  data:
    - secretKey: apiKey
      remoteRef:
        key: /demo/komodor
```

This creates a Kubernetes `Secret` named:

```text
komodor-agent-api-key
```

With a key called:

```text
apiKey
```

The resulting secret shape is:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: komodor-agent-api-key
  namespace: komodor
type: Opaque
data:
  apiKey: <base64 encoded value>
```

## Komodor Agent configuration

The Komodor Agent release is configured to use the secret created by ESO:

```yaml
apiKeySecret: komodor-agent-api-key
```

This means the API key does not need to be provided directly to the Komodor Agent Helm chart.

## Deploying the demo

Apply the full stack with:

```bash
helmfile apply
```

## Validating the deployment

Check that ESO is running:

```bash
kubectl get pods -n external-secrets
```

Check that the `SecretStore` exists:

```bash
kubectl get secretstore -n komodor
```

Check that the `ExternalSecret` is ready:

```bash
kubectl get externalsecret -n komodor
kubectl describe externalsecret demo-komodor-agent-secret -n komodor
```

Check that the Kubernetes `Secret` was created:

```bash
kubectl get secret komodor-agent-api-key -n komodor
```

Optionally decode the demo value:

```bash
kubectl get secret komodor-agent-api-key -n komodor \
  -o jsonpath='{.data.apiKey}' | base64 -d

echo
```

Check the Komodor Agent release:

```bash
helm status komodor-agent -n komodor
kubectl get pods -n komodor
```

## Common issue: `could not get secret data from provider`

If the `ExternalSecret` reports:

```text
could not get secret data from provider
```

Check whether the `ExternalSecret` is using `dataFrom.extract` against a single string value.

For example, this is incorrect when the fake provider uses `value`:

```yaml
dataFrom:
  - extract:
      key: /demo/komodor
```

`dataFrom.extract` is intended for extracting multiple fields from a structured value.

For a single string value, use `data` with `remoteRef` instead:

```yaml
data:
  - secretKey: apiKey
    remoteRef:
      key: /demo/komodor
```

Alternatively, if you want to use `dataFrom.extract`, the fake provider value should be shaped as a map/object using `valueMap`.

## Production guidance

For production-like usage, replace the fake provider with a real external secret backend.

The recommended production pattern is:

```text
External secret backend
  └── Stores the real Komodor API key

External Secrets Operator
  └── Authenticates to the backend using cloud/workload identity or tightly-scoped credentials

ExternalSecret
  └── Selects only the required secret value

Kubernetes Secret
  └── Created automatically by ESO

Komodor Agent
  └── References the generated Kubernetes Secret using apiKeySecret
```

Avoid:

- Committing API keys to Git
- Storing API keys directly in Helm values
- Using plain-text Kubernetes `Secret` manifests
- Using the fake provider outside demos
- Sharing the same API key across unrelated environments
- Giving ESO broader secret-store access than required

Prefer:

- Separate API keys per environment
- Short-lived or rotatable credentials where supported
- Namespace-scoped `SecretStore` resources where appropriate
- Least-privilege access to the external secret backend
- GitOps-friendly manifests that reference secrets but do not contain secret values
- Clear ownership between platform-managed secret access and application-owned `ExternalSecret` definitions

## Cleaning up

Remove the deployed resources with:

```bash
helmfile destroy
```

You may also want to remove namespaces if they are no longer needed:

```bash
kubectl delete namespace komodor --ignore-not-found
kubectl delete namespace external-secrets --ignore-not-found
```

## Summary

This demo shows how to keep the Komodor Agent API key out of Helm values by allowing External Secrets Operator to create the Kubernetes `Secret` first.

The key idea is:

```text
Do not pass the secret value to the Komodor Agent chart.
Pass the name of a Kubernetes Secret that ESO manages.
```

For demos, the fake provider keeps the setup simple.

For real environments, use a proper secret backend such as Vault, AWS Secrets Manager, Google Secret Manager, or Azure Key Vault.
