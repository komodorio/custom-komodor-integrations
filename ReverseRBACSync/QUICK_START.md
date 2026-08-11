# Quick Start — Komodor Reverse RBAC Sync

## 1. Install dependencies

```bash
pip install requests
```

## 2. Get RBAC data

Export RBAC from each cluster (requires `kubectl` + `jq`):

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

## 3. Analyze and generate policies

> **Multi-cluster accounts:** keep one export directory per cluster and repeat steps 3-4 for each cluster. Pointing `analyze_k8s_rbac.py` at a directory containing several clusters merges their RBAC into one analysis (a union of permissions), which you usually do not want.

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

## 4. Review

```bash
python3 compare_and_report.py \
    --generated generated_policies/<account-name>/$CLUSTER/all_policies.json \
    -a <account-name> --skip-db -o reports/<account-name>/comparison_$CLUSTER

python3 generate_html_report.py -c reports/<account-name>/comparison_$CLUSTER/comparison.json
open reports/<account-name>/comparison_$CLUSTER/rbac_sync_report.html
```

Also review the **Known Limitations** section in `README.md` — in particular, filter out
system identities (`system:*`, `eks:*`) and check the `unmapped_rules` list in
`komodor_mapping.json`.

## 5. Apply (dry-run first!)

```bash
python3 apply_komodor_policies.py \
    --policies generated_policies/<account-name>/$CLUSTER/all_policies.json --dry-run

export KOMODOR_API_KEY=<your-api-key>
python3 apply_komodor_policies.py \
    --policies generated_policies/<account-name>/$CLUSTER/all_policies.json --include-roles
```

## 6. Continuous sync (optional)

To run this on a schedule so Komodor tracks RBAC changes automatically, see
`CONTINUOUS_SYNC.md` — it covers `sync_once.py`, the container image, and the
ready-to-apply CronJob manifest in `deploy/`.

## 7. Wire up SSO

In your IdP's Komodor SAML app, map identity groups to the generated role names via the
`komodorRoles` attribute (e.g., group `platform-team` → role `k8s-sync-platform-team`),
then verify with a test user from each group.
