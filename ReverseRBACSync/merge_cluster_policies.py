#!/usr/bin/env python3
"""
Merge per-cluster generated policies into one policy per group.

Each per-cluster pipeline run emits policies with the same name
(k8s-sync-group-<group>) scoped to that cluster. Applying those outputs
in sequence would overwrite the same policy repeatedly (last cluster wins).
This script merges them: one policy per group, carrying every cluster's
scope as statements/resource entries in a single policy.

Usage:
    python merge_cluster_policies.py \
        --inputs generated_policies/<account>/<cluster-a> generated_policies/<account>/<cluster-b> \
        --output generated_policies/<account>/merged
"""

import argparse
import json
import logging
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_policy_file(path: Path) -> Dict:
    """Load an all_policies.json file, accepting a directory containing one."""
    if path.is_dir():
        path = path / 'all_policies.json'
    with open(path) as f:
        return json.load(f)


def merge_policies(policy_sets: List[Dict]) -> Dict:
    """
    Merge multiple per-cluster policy sets into one set with one policy per name.

    Statements with identical action sets are combined into a single statement
    whose resources list carries one entry per cluster scope. Unscoped
    statements (no resources) are deduplicated by action set.
    """
    merged_policies: 'OrderedDict[str, Dict]' = OrderedDict()
    merged_roles: 'OrderedDict[str, Dict]' = OrderedDict()
    # policy name -> action-set key -> {'actions': [...], 'resources': OrderedDict or None}
    statement_index: Dict[str, 'OrderedDict[tuple, Dict]'] = {}
    policy_clusters: Dict[str, List[str]] = {}

    for pset in policy_sets:
        cluster = (pset.get('summary') or {}).get('cluster_name') or 'unknown'
        for policy in pset.get('policies', []):
            name = policy['name']
            if name not in merged_policies:
                merged_policies[name] = {
                    'name': name,
                    'description': policy.get('description', ''),
                    'type': policy.get('type', 'v2'),
                    'statements': [],  # filled in below
                    'tags': dict(policy.get('tags', {})),
                }
                statement_index[name] = OrderedDict()
                policy_clusters[name] = []
            if cluster not in policy_clusters[name]:
                policy_clusters[name].append(cluster)

            for stmt in policy.get('statements', []):
                key = tuple(sorted(stmt.get('actions', [])))
                entry = statement_index[name].get(key)
                if entry is None:
                    entry = {'actions': sorted(stmt.get('actions', [])), 'resources': None}
                    statement_index[name][key] = entry
                for res in stmt.get('resources') or []:
                    if entry['resources'] is None:
                        entry['resources'] = OrderedDict()
                    res_key = (res.get('cluster'), tuple(res.get('namespaces') or []))
                    if res_key not in entry['resources']:
                        entry['resources'][res_key] = {
                            'cluster': res.get('cluster'),
                            'namespaces': list(res.get('namespaces') or []),
                        }

        for role in pset.get('roles', []):
            merged_roles.setdefault(role['name'], role)

    # Materialize statements and annotate tags/descriptions
    for name, policy in merged_policies.items():
        statements = []
        for entry in statement_index[name].values():
            stmt = {'actions': entry['actions']}
            if entry['resources'] is not None:
                stmt['resources'] = list(entry['resources'].values())
            statements.append(stmt)
        policy['statements'] = statements

        clusters = sorted(policy_clusters[name])
        policy['tags']['clusters'] = clusters
        policy['tags']['sync_timestamp'] = datetime.now().isoformat()
        subject = policy['tags'].get('subject_name', name)
        policy['description'] = (
            f"Auto-generated policy for '{subject}' "
            f"(merged from {len(clusters)} cluster(s): {', '.join(clusters)}; synced from K8s RBAC)"
        )

    return {
        'policies': list(merged_policies.values()),
        'roles': list(merged_roles.values()),
        'summary': {
            'total_policies': len(merged_policies),
            'total_roles': len(merged_roles),
            'source_clusters': sorted({c for cl in policy_clusters.values() for c in cl}),
            'generated_at': datetime.now().isoformat(),
            'merged': True,
        },
    }


def merge_statements_into_existing(existing_policy: Dict, new_policy: Dict, cluster: str) -> Dict:
    """
    Merge one cluster's freshly generated policy into the live policy from Komodor,
    touching only this cluster's scope.

    Used by per-cluster sync jobs so concurrent clusters converge instead of
    overwriting each other:
      - resource entries for `cluster` are replaced with the new generation
      - resource entries for '*' (legacy unscoped-cluster grants) are dropped,
        so wildcard policies tighten to explicit per-cluster scopes as each
        cluster syncs
      - resource entries for other clusters are preserved untouched
      - unscoped statements (no resources) are unioned: kept if present in either
        the existing policy or the new generation (view-only over-retention is
        possible; a central full pass or manual cleanup removes them)
      - statements left with no resource entries and no unscoped standing are dropped
    """
    stmt_index: 'OrderedDict[tuple, Dict]' = OrderedDict()

    def statements_of(policy):
        stmts = policy.get('statements', [])
        if isinstance(stmts, str):
            stmts = json.loads(stmts)
        normalized = []
        for stmt in stmts:
            if 'resourcesScope' in stmt and 'resources' not in stmt:
                # Live-API schema -> internal shape
                rs = stmt.get('resourcesScope') or {}
                clusters = list(rs.get('clusters') or [])
                if any((pat or {}).get('include') == '*' for pat in rs.get('clustersPatterns') or []):
                    clusters.append('*')
                namespaces = list(rs.get('namespaces') or [])
                if any((pat or {}).get('include') == '*' for pat in rs.get('namespacesPatterns') or []):
                    namespaces = ['*']
                if clusters:
                    normalized.append({'actions': stmt.get('actions', []),
                                       'resources': [{'cluster': c, 'namespaces': namespaces} for c in clusters]})
                else:
                    normalized.append({'actions': stmt.get('actions', [])})
            else:
                normalized.append(stmt)
        return normalized

    # Existing statements: keep other clusters' resource entries only
    for stmt in statements_of(existing_policy):
        key = tuple(sorted(stmt.get('actions', [])))
        entry = stmt_index.setdefault(key, {'actions': sorted(stmt.get('actions', [])),
                                            'resources': OrderedDict(), 'unscoped': False})
        resources = stmt.get('resources')
        if not resources:
            entry['unscoped'] = True
            continue
        for res in resources:
            if res.get('cluster') in (cluster, '*'):
                continue  # this cluster's (and legacy wildcard) scope is being regenerated
            res_key = (res.get('cluster'), tuple(res.get('namespaces') or []))
            entry['resources'].setdefault(res_key, {
                'cluster': res.get('cluster'),
                'namespaces': list(res.get('namespaces') or []),
            })

    # New statements: add this cluster's scope
    for stmt in statements_of(new_policy):
        key = tuple(sorted(stmt.get('actions', [])))
        entry = stmt_index.setdefault(key, {'actions': sorted(stmt.get('actions', [])),
                                            'resources': OrderedDict(), 'unscoped': False})
        resources = stmt.get('resources')
        if not resources:
            entry['unscoped'] = True
            continue
        for res in resources:
            res_key = (res.get('cluster'), tuple(res.get('namespaces') or []))
            entry['resources'].setdefault(res_key, {
                'cluster': res.get('cluster'),
                'namespaces': list(res.get('namespaces') or []),
            })

    statements = []
    for entry in stmt_index.values():
        if entry['resources']:
            statements.append({'actions': entry['actions'],
                               'resources': list(entry['resources'].values())})
        elif entry['unscoped']:
            statements.append({'actions': entry['actions']})
        # else: statement lost its last resource entry -> dropped (access removed)

    merged = {
        'name': new_policy['name'],
        'description': new_policy.get('description', existing_policy.get('description', '')),
        'type': new_policy.get('type', 'v2'),
        'statements': statements,
        'tags': dict(new_policy.get('tags', {})),
    }
    return merged


def main():
    parser = argparse.ArgumentParser(
        description='Merge per-cluster generated policies into one policy per group'
    )
    parser.add_argument(
        '--inputs', '-i',
        type=Path,
        nargs='+',
        required=True,
        help='Per-cluster policy outputs: all_policies.json files or directories containing one'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        required=True,
        help='Output directory for the merged policy set'
    )

    args = parser.parse_args()

    policy_sets = []
    for path in args.inputs:
        logger.info(f"Loading policy set: {path}")
        policy_sets.append(load_policy_file(path))

    result = merge_policies(policy_sets)

    args.output.mkdir(parents=True, exist_ok=True)
    all_file = args.output / 'all_policies.json'
    with open(all_file, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved merged policies to: {all_file}")

    individual = args.output / 'individual'
    individual.mkdir(exist_ok=True)
    for policy in result['policies']:
        with open(individual / f"{policy['name']}.json", 'w') as f:
            json.dump(policy, f, indent=2)

    if result['roles']:
        with open(args.output / 'roles.json', 'w') as f:
            json.dump(result['roles'], f, indent=2)

    print("\n" + "=" * 60)
    print("POLICY MERGE COMPLETE")
    print("=" * 60)
    print(f"Source clusters: {', '.join(result['summary']['source_clusters'])}")
    print(f"Merged policies: {result['summary']['total_policies']}")
    print(f"Merged roles:    {result['summary']['total_roles']}")
    print(f"Output: {args.output}")


if __name__ == '__main__':
    main()
