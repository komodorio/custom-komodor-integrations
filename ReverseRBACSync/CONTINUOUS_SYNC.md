# Continuous Sync — Self-Hosted

This guide covers running Reverse RBAC Sync **continuously on your own infrastructure**, so Komodor policies track your Kubernetes RBAC automatically. Everything runs against Komodor's public API with your own API key — no Komodor-internal access is involved.

Each sync pass is one idempotent run of `sync_once.py`:

```
export RBAC (kubectl, read-only)
  → analyze → map → generate   (per cluster)
  → merge (one policy per group, all cluster scopes in one policy)
  → apply (create/update policies, create roles)
  → prune (optional: delete stale k8s-sync-* policies/roles)
```

## Deployment Topologies

**A. CronJob per cluster (recommended).** Each cluster runs the provided CronJob with a read-only ServiceAccount and syncs itself. No cross-cluster credentials exist anywhere.
In this topology each job performs a **statement-level merge against the live policy**: it replaces only its own cluster's resource entries and preserves every other cluster's, so jobs on different clusters converge instead of overwriting each other. Two details to know: legacy `cluster: "*"` scopes (from older one-shot imports) are progressively replaced by explicit per-cluster scopes as each cluster's job runs, and unscoped platform-view statements are unioned rather than removed (cleaning those up takes a central full pass or a manual edit). `--prune` is **not available** in this topology — a single cluster cannot know which groups are stale account-wide, and the CLI rejects the combination.

**B. Central runner.** One scheduled job (CI runner, management cluster) holds kubeconfig contexts for all clusters and syncs them in a single pass:

```bash
python3 sync_once.py --account <account> --contexts prod-east stage-east eu-prod --apply --prune
```

This topology gives prune the complete picture and produces exactly one merged policy set per pass — prefer it if cross-cluster kubeconfig access is acceptable to your security team.

## Setup (Topology A)

1. **Build and push the image:**

```bash
docker build -t <registry>/komodor-rbac-sync:latest .
docker push <registry>/komodor-rbac-sync:latest
```

2. **Create a Komodor API key** with permission to manage RBAC (the `manage:users` action), and install per cluster:

```bash
kubectl create namespace komodor-rbac-sync
kubectl -n komodor-rbac-sync create secret generic komodor-api-key --from-literal=apiKey=<key>
```

3. **Edit `deploy/rbac-sync-cronjob.yaml`:** set the image, the account name, and `CLUSTER_NAME` (must match the cluster's name in Komodor), then:

```bash
kubectl apply -f deploy/rbac-sync-cronjob.yaml
```

4. **Roll out safely.** The manifest ships in **dry-run mode** (no `--apply`). Watch 2–3 job runs' logs, review the planned creates/updates, then add `--apply` to the args. Run with `--apply` for a week or two before enabling `--prune`.

## Operational Conventions

- **Never hand-edit `k8s-sync-*` policies.** The sync overwrites them every pass. Additions that have no K8s equivalent (`exec:pod`, Helm actions, Klaudia, `manage:*`) belong in **separate, manually created policies** attached to the same roles — the sync never touches non-`k8s-sync-*` objects, and it does not modify existing roles' policy lists.
- **Change access in Kubernetes, not Komodor.** K8s RBAC is the source of truth; the sync propagates changes within one schedule interval.
- **System identities are filtered automatically.** Subjects like `system:masters`, `eks:*`, and `kubelet` are skipped at generation time (see `skipped_system_subjects` in the run summary); pass `--include-system-subjects` to restore them.
- **User-subject bindings:** add `--assign-user-roles` to the sync args to assign each generated user role to the matching Komodor user by email on every pass. The sync never creates or deletes Komodor user accounts.
- **Cadence:** RBAC changes are rare events. `*/10` minutes matches the common ask, but an hourly schedule plus a trigger from your GitOps pipeline (run the job whenever your RBAC manifests change) gives a tighter drift window at a fraction of the runs.

## Monitoring

- The job exits non-zero when any cluster export or the apply step fails — alert on CronJob failures (`kube_job_status_failed` or your operator's equivalent).
- Run artifacts (generated policies, merge output, prune results) are written under the job's workdir; they're ephemeral in the container but the logs carry the summary.
- In Komodor, synced objects are identifiable by the `k8s-sync-` name prefix (the generated JSON files also carry `tags.source: k8s-rbac-sync` for reference; tags are not transmitted by the API client).

## API Notes

- **Verified endpoints (August 2026, tested live):** authentication is the `x-api-key` header. Policies: `GET/POST/PUT https://api.komodor.com/api/v2/rbac/policies[/{name}]`. Roles: `GET/POST /api/v2/rbac/roles`. Link policy→role: `POST /mgmt/v1/rbac/roles/policies` `{roleId, policyId}`. Users: `GET/POST /api/v2/users`; assign role→user: `POST /mgmt/v1/rbac/users/roles` `{userId, roleId}`. Effective permissions (great for validation): `GET /api/v2/users/effective-permissions?email=...`.
- **Statement schema:** the current API uses `resourcesScope` (clusters/clustersPatterns/namespaces/namespacesPatterns/selectors) and requires a namespace scope on every statement. `apply_komodor_policies.py` translates generated statements automatically,

 drops unscoped platform actions (`view:audit`, `view:usage`, `view:nodecount`) with a warning, and auto-removes actions the API rejects for the requested scope (e.g. cilium add-on actions).
- **DELETE endpoints verified live (August 2026):** `DELETE /api/v2/rbac/policies/{name}` and `DELETE /api/v2/rbac/roles/{name}` both accept the object **name** and return success with an empty body. Deleting a role still attached to a user detaches it cleanly (no error; the user's other roles are untouched), and a role's policy links do not block deletion — so prune's roles-then-policies ordering is safe.
- The apply step rate-limits itself (0.5s between policy writes).
- Rotate the API key like any other secret; the job reads it from the `komodor-api-key` Secret at each run.

## Failure Semantics

- If a cluster's export fails, the pass continues for the remaining clusters, **skips prune entirely** (an incomplete generated set must not drive deletions), and exits non-zero so your alerting fires.
- If every cluster fails, nothing is written to Komodor.
- Policies for a failed cluster are simply left as they were — the next successful pass reconverges them.
