#!/usr/bin/env python3
"""
Run one complete reverse RBAC sync pass, suitable for a scheduler (CronJob).

Pipeline: export RBAC via kubectl -> analyze -> map -> generate (per cluster)
          -> merge into one policy per group -> apply via Komodor API
          -> optionally prune stale synced policies/roles.

The scheduling itself lives outside this script (Kubernetes CronJob, CI job,
or cron) — each invocation is one idempotent sync pass.

Modes:
    --in-cluster --cluster-name <name>   Export the cluster this pod runs in
                                         (kubectl falls back to the ServiceAccount)
    --contexts <ctx> [<ctx> ...]         Central runner: export each kubeconfig
                                         context (context name = cluster name)

Safety:
    Default is a dry run (nothing written to Komodor). Pass --apply to write.
    --prune deletes k8s-sync-* policies/roles that are no longer generated;
    it only deletes with --apply, and prints what it would delete otherwise.

Usage:
    # Preview from a laptop with kubeconfig contexts
    python sync_once.py --account acme --contexts prod-east stage-east

    # Real sync from inside a cluster (CronJob)
    python sync_once.py --account acme --in-cluster --cluster-name prod-east --apply

Environment:
    KOMODOR_API_KEY       required with --apply
    RBAC_SYNC_WORKDIR     working directory (default: ./sync_workspace)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent

# (kubectl resource, all-namespaces flag, output filename understood by analyze_k8s_rbac.py)
EXPORT_RESOURCES = [
    ('clusterroles', False, 'clusterrole.json'),
    ('clusterrolebindings', False, 'clusterrolebinding.json'),
    ('roles', True, 'role.json'),
    ('rolebindings', True, 'rolebinding.json'),
    ('serviceaccounts', True, 'serviceaccount.json'),
]


def run_step(cmd: List[str], step: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a pipeline step, raising with context on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"{step} failed (exit {result.returncode}): {result.stderr.strip()[:500]}")
    return result


def export_cluster_rbac(cluster: str, out_dir: Path, context: Optional[str] = None):
    """Export RBAC resources from one cluster via kubectl (read-only)."""
    cluster_dir = out_dir / cluster
    cluster_dir.mkdir(parents=True, exist_ok=True)

    for resource, all_ns, filename in EXPORT_RESOURCES:
        cmd = ['kubectl']
        if context:
            cmd += ['--context', context]
        cmd += ['get', resource, '-o', 'json']
        if all_ns:
            cmd.append('-A')

        result = run_step(cmd, f"kubectl get {resource} ({cluster})", timeout=120)
        items = json.loads(result.stdout).get('items', [])
        with open(cluster_dir / filename, 'w') as f:
            json.dump(items, f)
        logger.info(f"[{cluster}] exported {len(items)} {resource}")


def run_cluster_pipeline(account: str, cluster: str, workdir: Path) -> Path:
    """Run analyze -> map -> generate for one exported cluster. Returns policies dir."""
    data_dir = workdir / 'data' / cluster          # parent dir holding <cluster>/ subdir
    report_dir = workdir / 'reports' / cluster
    policies_dir = workdir / 'generated_policies' / cluster
    py = sys.executable

    run_step([py, str(SCRIPT_DIR / 'analyze_k8s_rbac.py'),
              '--input', str(data_dir), '--output', str(report_dir), '-a', account],
             f"analyze ({cluster})")
    run_step([py, str(SCRIPT_DIR / 'map_to_komodor.py'),
              '--input', str(report_dir / 'rbac_analysis.json'), '--cluster-name', cluster],
             f"map ({cluster})")
    run_step([py, str(SCRIPT_DIR / 'generate_komodor_policies.py'),
              '--input', str(report_dir / 'komodor_mapping.json'),
              '-o', str(policies_dir), '-a', account, '--cluster-name', cluster],
             f"generate ({cluster})")
    return policies_dir


def prune_stale(api_client, generated: Dict, apply_changes: bool) -> Dict:
    """
    Delete k8s-sync-* policies/roles in Komodor that are no longer generated.

    Only touches names starting with 'k8s-sync-' — manually created policies
    and Komodor defaults are never considered.
    """
    results = {'policies_deleted': [], 'roles_deleted': [], 'errors': []}
    generated_policy_names = {p['name'] for p in generated.get('policies', [])}
    generated_role_names = {r['name'] for r in generated.get('roles', [])}

    ok, existing_policies = api_client.get_policies()
    if not ok:
        results['errors'].append('could not list existing policies')
        return results
    ok, existing_roles = api_client.get_roles()
    if not ok:
        results['errors'].append('could not list existing roles')
        return results

    stale_roles = [r['name'] for r in existing_roles
                   if r.get('name', '').startswith('k8s-sync-') and r['name'] not in generated_role_names]
    stale_policies = [p['name'] for p in existing_policies
                      if p.get('name', '').startswith('k8s-sync-') and p['name'] not in generated_policy_names]

    # Roles first (they reference policies)
    for name in stale_roles:
        if not apply_changes:
            logger.info(f"[prune] would DELETE role: {name}")
            continue
        ok, res = api_client.delete_role(name)
        if ok:
            logger.info(f"[prune] deleted role: {name}")
            results['roles_deleted'].append(name)
        else:
            logger.error(f"[prune] failed to delete role {name}: {res.get('error')}")
            results['errors'].append(f"role {name}: {res.get('error')}")

    for name in stale_policies:
        if not apply_changes:
            logger.info(f"[prune] would DELETE policy: {name}")
            continue
        ok, res = api_client.delete_policy(name)
        if ok:
            logger.info(f"[prune] deleted policy: {name}")
            results['policies_deleted'].append(name)
        else:
            logger.error(f"[prune] failed to delete policy {name}: {res.get('error')}")
            results['errors'].append(f"policy {name}: {res.get('error')}")

    if not apply_changes:
        results['would_delete'] = {'roles': stale_roles, 'policies': stale_policies}
    return results


def assign_user_roles(api_client, merged: Dict, apply_changes: bool):
    """
    Assign each generated user-subject role to the matching Komodor user (by email).

    Only attaches roles to users that already exist in Komodor — user creation
    stays a human/SSO/API decision. Users without a Komodor account are logged.
    """
    ok, users = api_client.get_users()
    if not ok:
        logger.error("assign-user-roles: could not list Komodor users")
        return
    by_email = {u.get('email'): u for u in users if not u.get('deletedAt')}
    ok, roles = api_client.get_roles()
    role_by_name = {r.get('name'): r for r in roles} if ok else {}

    for policy in merged.get('policies', []):
        tags = policy.get('tags', {})
        if tags.get('subject_kind') != 'user':
            continue
        email = tags.get('subject_name', '')
        role_name = policy['name'].replace('k8s-sync-user-', 'k8s-sync-', 1)
        user = by_email.get(email)
        role = role_by_name.get(role_name)
        if not user:
            logger.info(f"assign-user-roles: no Komodor user for {email} — "
                        f"role {role_name} is ready to attach once the user exists (SSO login, UI invite, or POST /api/v2/users)")
            continue
        if not role:
            logger.warning(f"assign-user-roles: role {role_name} not found in Komodor; skipping {email}")
            continue
        already = {r.get('name') for r in user.get('roles') or []}
        if role_name in already:
            logger.info(f"assign-user-roles: {email} already has {role_name}")
            continue
        if not apply_changes:
            logger.info(f"[DRY RUN] would assign role {role_name} -> {email}")
            continue
        ok, res = api_client.attach_role_to_user(user['id'], role['id'])
        if ok:
            logger.info(f"Assigned role {role_name} -> {email}")
        else:
            logger.error(f"Failed to assign {role_name} -> {email}: {res.get('error')}")


def apply_per_cluster_merge(merged: Dict, cluster: str, api_key: str, apply_changes: bool) -> bool:
    """
    Apply one cluster's generated set by merging into the live Komodor policies.

    Used by the per-cluster CronJob topology: only this cluster's resource
    entries are replaced, so jobs on different clusters converge instead of
    overwriting each other's scope every run.
    """
    import time as _time
    from apply_komodor_policies import KomodorAPIClient
    from merge_cluster_policies import merge_statements_into_existing

    client = KomodorAPIClient(api_key)
    ok, existing = client.get_policies()
    if not ok:
        logger.error("Could not list existing policies from the Komodor API")
        return False
    existing_by_name = {pol.get('name'): pol for pol in existing}

    failures = 0
    for policy in merged.get('policies', []):
        name = policy['name']
        if name in existing_by_name:
            combined = merge_statements_into_existing(existing_by_name[name], policy, cluster)
            if not apply_changes:
                logger.info(f"[DRY RUN] would UPDATE policy {name} "
                            f"({len(combined['statements'])} statement(s) after merging this cluster's scope)")
                continue
            ok, res = client.update_policy(name, combined)
            action = 'UPDATED'
        else:
            if not apply_changes:
                logger.info(f"[DRY RUN] would CREATE policy {name}")
                continue
            ok, res = client.create_policy(policy)
            action = 'CREATED'
        if ok:
            logger.info(f"{action} policy: {name}")
        else:
            logger.error(f"Failed to write policy {name}: {res.get('error')}")
            failures += 1
        _time.sleep(0.5)

    for role in merged.get('roles', []):
        if not apply_changes:
            logger.info(f"[DRY RUN] would ensure role: {role['name']}")
            continue
        ok, res = client.create_role(role)
        if ok:
            logger.info(f"CREATED role: {role['name']}")
        elif res.get('status') == 409:
            logger.info(f"Role already exists (skipped): {role['name']}")
        else:
            logger.error(f"Failed to create role {role['name']}: {res.get('error')}")
            failures += 1
        _time.sleep(0.2)

    return failures == 0


def main():
    parser = argparse.ArgumentParser(
        description='Run one reverse RBAC sync pass (export -> generate -> merge -> apply)'
    )
    parser.add_argument('--account', '-a', required=True, help='Account name (used in paths/labels)')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--in-cluster', action='store_true',
                      help='Export the cluster this process runs in (requires --cluster-name)')
    mode.add_argument('--contexts', nargs='+',
                      help='Kubeconfig context names to export (context name is used as cluster name)')
    parser.add_argument('--cluster-name', help='Cluster name (required with --in-cluster)')
    parser.add_argument('--apply', action='store_true',
                        help='Write changes to Komodor (default: dry run, nothing written)')
    parser.add_argument('--prune', action='store_true',
                        help='Also delete stale k8s-sync-* policies/roles no longer generated')
    parser.add_argument('--assign-user-roles', action='store_true',
                        help='Assign generated user-subject roles to matching Komodor users (by email)')
    parser.add_argument('--workdir', type=Path,
                        default=Path(os.environ.get('RBAC_SYNC_WORKDIR', 'sync_workspace')),
                        help='Working directory for this run')

    args = parser.parse_args()

    if args.in_cluster and not args.cluster_name:
        parser.error('--in-cluster requires --cluster-name')
    if args.apply and not os.environ.get('KOMODOR_API_KEY'):
        parser.error('--apply requires the KOMODOR_API_KEY environment variable')
    if args.in_cluster and args.prune:
        parser.error('--prune requires the central-runner topology (--contexts): a single cluster '
                     'cannot safely decide which groups are stale account-wide')

    run_id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    workdir = args.workdir / run_id
    workdir.mkdir(parents=True, exist_ok=True)
    clusters = [args.cluster_name] if args.in_cluster else args.contexts

    logger.info(f"Sync pass starting: account={args.account} clusters={clusters} "
                f"mode={'APPLY' if args.apply else 'DRY RUN'} workdir={workdir}")

    # 1-2. Export + per-cluster pipeline
    policy_dirs = []
    failed = []
    for cluster in clusters:
        try:
            context = None if args.in_cluster else cluster
            export_cluster_rbac(cluster, workdir / 'data' / cluster, context=context)
            policy_dirs.append(run_cluster_pipeline(args.account, cluster, workdir))
            logger.info(f"[{cluster}] pipeline complete")
        except Exception as e:
            logger.error(f"[{cluster}] FAILED: {e}")
            failed.append(cluster)

    if not policy_dirs:
        logger.error("No cluster succeeded; aborting before touching Komodor.")
        sys.exit(1)
    if failed:
        logger.warning(f"Proceeding without failed clusters: {failed} "
                       f"(their existing policies are left untouched; prune is skipped)")

    # 3. Merge into one policy per group
    merged_dir = workdir / 'merged'
    run_step([sys.executable, str(SCRIPT_DIR / 'merge_cluster_policies.py'),
              '--inputs', *[str(d) for d in policy_dirs], '--output', str(merged_dir)],
             'merge')
    with open(merged_dir / 'all_policies.json') as f:
        merged = json.load(f)
    logger.info(f"Merged: {len(merged['policies'])} policies, {len(merged['roles'])} roles "
                f"across {len(policy_dirs)} cluster(s)")

    # 4. Apply
    api_key = os.environ.get('KOMODOR_API_KEY')
    if args.in_cluster and api_key:
        # Per-cluster topology: replace only this cluster's scope in the live policies
        apply_ok = apply_per_cluster_merge(merged, args.cluster_name, api_key, args.apply)
    else:
        if args.in_cluster:
            logger.info("No KOMODOR_API_KEY set: this preview shows only this cluster's scope. "
                        "Live runs merge into the existing policies without touching other clusters' scopes.")
        # Central-runner topology (full picture): wholesale create/update is correct
        apply_cmd = [sys.executable, str(SCRIPT_DIR / 'apply_komodor_policies.py'),
                     '--policies', str(merged_dir / 'all_policies.json'), '--include-roles']
        if not args.apply:
            apply_cmd.append('--dry-run')
        result = subprocess.run(apply_cmd, timeout=1800)
        apply_ok = result.returncode == 0

    # 4b. Assign user-subject roles to matching Komodor users
    if args.assign_user_roles:
        if not api_key:
            logger.info("assign-user-roles requires KOMODOR_API_KEY to look up users; skipping.")
        else:
            from apply_komodor_policies import KomodorAPIClient
            assign_user_roles(KomodorAPIClient(api_key), merged, apply_changes=args.apply)

    # 5. Prune stale synced policies/roles
    if args.prune:
        if failed:
            logger.warning("Skipping prune: one or more clusters failed to export, "
                           "so the generated set is incomplete and deletion would be unsafe.")
        elif not os.environ.get('KOMODOR_API_KEY'):
            logger.info("Prune preview requires KOMODOR_API_KEY to list existing policies; skipping.")
        else:
            from apply_komodor_policies import KomodorAPIClient
            client = KomodorAPIClient(os.environ['KOMODOR_API_KEY'])
            prune_results = prune_stale(client, merged, apply_changes=args.apply)
            with open(workdir / 'prune_results.json', 'w') as f:
                json.dump(prune_results, f, indent=2)

    print("\n" + "=" * 60)
    print(f"SYNC PASS {'COMPLETE' if apply_ok and not failed else 'FINISHED WITH ISSUES'} "
          f"{'' if args.apply else '(DRY RUN)'}")
    print("=" * 60)
    print(f"Clusters synced: {[c for c in clusters if c not in failed]}")
    if failed:
        print(f"Clusters failed: {failed}")
    print(f"Policies: {len(merged['policies'])} | Roles: {len(merged['roles'])}")
    print(f"Run artifacts: {workdir}")
    sys.exit(0 if apply_ok and not failed else 1)


if __name__ == '__main__':
    main()
