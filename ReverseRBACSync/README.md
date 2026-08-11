# Komodor Reverse RBAC Sync Toolkit

## Overview

This toolkit implements **Reverse RBAC Sync**: it reads the existing Kubernetes RBAC configuration from your clusters and automatically generates matching Komodor policies and roles.

**Problem solved:** Your Kubernetes clusters already have carefully designed RBAC (often managed through your identity provider and IAM). Without a sync mechanism, those permissions must be manually replicated in Komodor — a slow, error-prone process that creates two divergent permission systems. Reverse RBAC Sync keeps **Kubernetes as the source of truth** and mirrors it into Komodor, eliminating permission drift.

The result: when users log into Komodor via SSO, they receive access that matches their existing K8s permissions, with no manual policy configuration.

## How It Works

```
K8s RBAC (all clusters)
   │  1. Fetch      ClusterRoles, ClusterRoleBindings, Roles, RoleBindings, ServiceAccounts
   ▼
   │  2. Analyze    Build subject → role → permission graph; extract identity groups
   ▼
   │  3. Map        Translate K8s verbs × resources into Komodor actions
   ▼
   │  4. Generate   Emit Komodor policy JSON (one per group) + one Komodor role per policy
   ▼
   │  5. Compare    Diff generated policies against the account's existing Komodor config
   ▼
   │  6. Report     Per-cluster HTML reports + account-level executive report
   ▼
Apply via Komodor API  →  Users get matching permissions at SSO login (SAML `komodorRoles`)
```

## Package Contents

| Script | Purpose |
|--------|---------|
| `analyze_k8s_rbac.py` | Parses RBAC structure and extracts groups/permissions |
| `map_to_komodor.py` | Maps K8s verbs/resources to Komodor actions |
| `k8s_to_komodor_mapping.py` | Mapping constants and logic |
| `generate_komodor_policies.py` | Generates Komodor policy + role JSON files |
| `compare_and_report.py` | Compares generated policies with existing Komodor config |
| `generate_html_report.py` | Per-cluster HTML comparison report |
| `generate_executive_report.py` | Comprehensive tabbed executive HTML report |
| `apply_komodor_policies.py` | Applies policies/roles to Komodor via the public API |
| `merge_cluster_policies.py` | Merges per-cluster outputs into one policy per group |
| `sync_once.py` | One idempotent sync pass (export → generate → merge → apply → prune) for schedulers |
| `Dockerfile` + `deploy/rbac-sync-cronjob.yaml` | Container image and CronJob manifest for self-hosted continuous sync |

> **Important:** never commit exported RBAC data, generated policies, or API
> keys — the included `.gitignore` guards these paths. Review generated
> policies before applying; every write path defaults to dry-run.

## Prerequisites

- Python 3.7+
- `pip install requests`
- A Komodor API key (for applying policies): set `KOMODOR_API_KEY`

## Running the Pipeline

Export RBAC from each cluster with `kubectl`, then run the analysis locally. Everything runs on your infrastructure; the only external call is the optional apply step against Komodor's public API.

**1. Export RBAC per cluster** (requires `jq`):

```bash
CLUSTER=my-cluster
OUT=data/<account-name>/export-$CLUSTER/$CLUSTER
mkdir -p "$OUT"
kubectl get clusterroles -o json        | jq '.items' > "$OUT/clusterrole.json"
kubectl get clusterrolebindings -o json | jq '.items' > "$OUT/clusterrolebinding.json"
kubectl get roles -A -o json            | jq '.items' > "$OUT/role.json"
kubectl get rolebindings -A -o json     | jq '.items' > "$OUT/rolebinding.json"
kubectl get serviceaccounts -A -o json  | jq '.items' > "$OUT/serviceaccount.json"
```

Repeat the export for each cluster, keeping **one export directory per cluster** (analyzing a directory that contains several clusters merges their RBAC into a single union, which is usually not what you want).

**2. Analyze, map, and generate policies (per cluster):**

```bash
python3 analyze_k8s_rbac.py --input data/<account-name>/export-$CLUSTER/ \
    --output reports/<account-name>/$CLUSTER -a <account-name>

python3 map_to_komodor.py --input reports/<account-name>/$CLUSTER/rbac_analysis.json \
    --cluster-name $CLUSTER

python3 generate_komodor_policies.py \
    --input reports/<account-name>/$CLUSTER/groups_komodor_mapping.json \
    -o generated_policies/<account-name>/$CLUSTER -a <account-name> \
    --cluster-name $CLUSTER
```

**3. Compare and report** (use `--skip-db` outside Komodor's network):

```bash
python3 compare_and_report.py \
    --generated generated_policies/<account-name>/$CLUSTER/all_policies.json \
    -a <account-name> --skip-db -o reports/<account-name>/comparison_$CLUSTER

python3 generate_html_report.py -c reports/<account-name>/comparison_$CLUSTER/comparison.json
```

## Applying Policies

**Always dry-run first** and review what will be created:

```bash
python3 apply_komodor_policies.py \
    --policies generated_policies/<account-name>/<run>/all_policies.json --dry-run
```

Then apply for real (policies, then roles):

```bash
export KOMODOR_API_KEY=<your-api-key>
python3 apply_komodor_policies.py \
    --policies generated_policies/<account-name>/<run>/all_policies.json --include-roles
```

Alternatively, import the per-policy files from `generated_policies/<account-name>/<run>/individual/` manually via the Komodor UI.

### Activating Permissions via SSO

Users receive the generated roles at login through the SAML `komodorRoles` attribute:

1. In your IdP (e.g., Okta, Entra ID), open the Komodor SAML application.
2. Add a SAML 2.0 attribute mapping for `komodorRoles`.
3. Map each identity group to its generated Komodor role name (e.g., group `platform-team` → role `k8s-sync-platform-team`). A group can be mapped to multiple roles.
4. Test with a sample user from each group and verify their effective permissions in Komodor.

## Known Limitations

Review these before applying generated policies:

1. **Per-cluster policies share names.** Each cluster's run generates policies named `k8s-sync-group-<group>` scoped to that cluster; applying several clusters' raw outputs in sequence would overwrite the same policy (last write wins). **Addressed:** run `merge_cluster_policies.py` over the per-cluster outputs before applying, or use `sync_once.py`, which merges automatically.
2. **Pod subresources are not auto-mapped.** K8s grants exec / port-forward / logs / scale via subresources (`pods/exec`, `deployments/scale`, …). The mapper matches base resources only, so `exec:pod` and `forward:port` are never granted automatically — add them manually where appropriate.
3. **`resourceNames` restrictions are dropped.** A K8s rule limited to specific named resources becomes a grant for the whole resource type within its scope.
4. **Wildcard rules map broadly.** `resources: ["*"]` maps to the full set of Komodor view/edit/delete actions, including some platform-level view actions (e.g., `view:audit`, `view:usage`). Review and trim these grants.
5. **Unmapped rules are recorded, not granted.** Resources without a Komodor equivalent (many CRDs, aggregated APIs) are listed under `unmapped_rules` in `komodor_mapping.json` — review that list to see what was left out.
6. **System identities are filtered by default.** Subjects like `system:*`, `eks:*`, and `kubelet` are K8s/cloud-managed identities, not IdP groups, so policy generation skips them (listed under `skipped_system_subjects` in the output summary). Pass `--include-system-subjects` to `generate_komodor_policies.py` if you need them.
7. **One-way, point-in-time sync.** The pipeline reflects RBAC at fetch time. Re-run it to pick up changes; manual edits to synced policies are overwritten on the next apply. Stale policies for removed groups can be cleaned with `sync_once.py --prune` (central-runner topology; see `CONTINUOUS_SYNC.md`).
8. **Prefer raw `kubectl` exports for fidelity.** When RBAC arrives via the Komodor agent in flattened form, binding subjects default to `Group` and RoleBinding→ClusterRole references may not resolve. The `kubectl` export path (Mode B) preserves full fidelity.
9. **Komodor-specific actions need decisions.** Capabilities with no K8s equivalent (Klaudia, cost optimization, Helm management, `manage:*` admin actions) are never granted by the sync — decide per group and add them manually.

## User-Subject Bindings

Both **Group** and **User** subjects are fully supported. Groups map to Komodor via your IdP's `komodorRoles` SAML attribute; for User subjects (e.g. `kind: User, name: jane@example.com` bound directly in a ClusterRoleBinding), the pipeline generates a policy *and* a role per user, and `sync_once.py --assign-user-roles` assigns each role to the matching Komodor user by email. Users that don't exist in Komodor yet are logged (create them via SSO login, UI invite, or `POST /api/v2/users`) — the sync never creates or deletes user accounts itself.

## Continuous Sync (Self-Hosted)

To keep Komodor permissions tracking K8s RBAC automatically, the toolkit includes a scheduler-ready sync pass (`sync_once.py`), a container image (`Dockerfile`), and a Kubernetes CronJob manifest (`deploy/rbac-sync-cronjob.yaml`). Everything runs on your infrastructure against the public API. See **`CONTINUOUS_SYNC.md`** for topologies, rollout guidance, and operational conventions.

## Outputs

| Artifact | Location |
|----------|----------|
| Policy JSON (all-in-one + per-policy) | `generated_policies/<account>/<run>/` |
| Komodor role definitions | `generated_policies/<account>/<run>/roles.json` |
| Analysis + mapping JSON | `reports/<account>/<run>/` |
| Per-cluster HTML comparison report | `reports/<account>/comparison_<run>/rbac_sync_report.html` |
| Account summary + executive report | `reports/<account>/` |

## Notes

- Generated policies are tagged `source: k8s-rbac-sync` so they are easy to identify and clean up.
- The toolkit performs **read-only** analysis; nothing changes in Komodor until you run `apply_komodor_policies.py` without `--dry-run`.
- No credentials, API keys, or customer data are included in this package.

---

**Provided by Komodor Solutions Engineering.** For questions about the analysis or implementation support, contact your Komodor account team.
