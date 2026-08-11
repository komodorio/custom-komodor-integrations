#!/usr/bin/env python3
"""
Apply generated policies to Komodor.

This script creates or updates Komodor policies based on the generated
policy files from the K8s RBAC sync process.

Supports two modes:
1. API Mode (recommended): Uses Komodor Public API
2. Dry-Run Mode: Shows what would be done without making changes

Prerequisites:
    - Komodor API key (set KOMODOR_API_KEY environment variable)
    - Or use --dry-run to preview changes

Usage:
    # Dry run (preview changes)
    python apply_komodor_policies.py --policies generated_policies/<account>/<timestamp>/all_policies.json --dry-run
    
    # Apply via API
    python apply_komodor_policies.py --policies generated_policies/<account>/<timestamp>/all_policies.json
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:  # requests is only needed when applying via the API (not for --dry-run)
    requests = None

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KomodorAPIClient:
    """Client for Komodor's Public API."""
    
    def __init__(self, api_key: str, base_url: str = "https://api.komodor.com"):
        if requests is None:
            raise RuntimeError(
                "The 'requests' package is required to call the Komodor API; pip install requests"
            )
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json',
            'User-Agent': 'komodor-rbac-sync/1.0'
        }
    
    def _request(self, method: str, endpoint: str, data: dict = None) -> Tuple[bool, dict]:
        """Make an API request."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                timeout=30
            )
            
            if response.status_code in (200, 201, 204):
                return True, response.json() if response.text else {}
            elif response.status_code == 409:
                # Conflict - policy already exists
                return False, {'error': 'Policy already exists', 'status': 409}
            else:
                return False, {
                    'error': response.text,
                    'status': response.status_code
                }
        except Exception as e:
            return False, {'error': str(e)}
    
    @staticmethod
    def translate_statements(statements: List[dict]) -> Tuple[List[dict], List[str]]:
        """
        Translate generator-format statements (resources: [{cluster, namespaces}])
        into the current API schema (resourcesScope with clusters/namespacesPatterns).

        Returns (translated_statements, dropped_unscoped_actions). Unscoped
        statements (no resources) are dropped — the current API requires a
        namespace scope on every statement.
        """
        translated, dropped = [], []
        for stmt in statements:
            if 'resourcesScope' in stmt:
                translated.append(stmt)
                continue
            resources = stmt.get('resources')
            if not resources:
                dropped.extend(stmt.get('actions', []))
                continue
            for res in resources:
                cluster = res.get('cluster') or '*'
                namespaces = res.get('namespaces') or []
                scope = {
                    'clusters': [] if cluster == '*' else [cluster],
                    'clustersPatterns': [{'include': '*', 'exclude': ''}] if cluster == '*' else [],
                    'namespaces': [n for n in namespaces if n != '*'],
                    'namespacesPatterns': [],
                    'selectors': [],
                    'selectorsPatterns': [],
                }
                if '*' in namespaces or not namespaces:
                    scope['namespaces'] = []
                    scope['namespacesPatterns'] = [{'include': '*', 'exclude': ''}]
                translated.append({'actions': stmt.get('actions', []), 'resourcesScope': scope})
        return translated, dropped

    def attach_policy_to_role(self, role_id: str, policy_id: str) -> Tuple[bool, dict]:
        """Link a policy to a role (mgmt API)."""
        return self._request('POST', '/mgmt/v1/rbac/roles/policies',
                             {'roleId': role_id, 'policyId': policy_id})

    def get_users(self) -> Tuple[bool, List[dict]]:
        """Get all users in the account."""
        success, result = self._request('GET', '/api/v2/users')
        if success:
            return True, result if isinstance(result, list) else result.get('data', [])
        return False, []

    def attach_role_to_user(self, user_id: str, role_id: str) -> Tuple[bool, dict]:
        """Assign a role to a user (mgmt API)."""
        return self._request('POST', '/mgmt/v1/rbac/users/roles',
                             {'userId': user_id, 'roleId': role_id})

    def get_policies(self) -> Tuple[bool, List[dict]]:
        """Get all existing policies."""
        success, result = self._request('GET', '/api/v2/rbac/policies')
        if success:
            return True, result if isinstance(result, list) else result.get('data', [])
        return False, []
    
    def get_policy_by_name(self, name: str) -> Tuple[bool, Optional[dict]]:
        """Get a policy by name."""
        success, result = self._request('GET', f'/api/v2/rbac/policies/{name}')
        return success, result if success else None
    
    def create_policy(self, policy: dict) -> Tuple[bool, dict]:
        """Create a new policy."""
        # Format for API
        statements, dropped = self.translate_statements(policy.get('statements', []))
        if dropped:
            logger.warning(f"{policy['name']}: dropped unscoped actions not supported by the API: {sorted(set(dropped))}")
        api_policy = {
            'name': policy['name'],
            'description': policy.get('description', ''),
            'statements': statements
        }
        return self._request('POST', '/api/v2/rbac/policies', api_policy)
    
    def update_policy(self, name: str, policy: dict) -> Tuple[bool, dict]:
        """Update an existing policy."""
        statements, dropped = self.translate_statements(policy.get('statements', []))
        if dropped:
            logger.warning(f"{policy['name']}: dropped unscoped actions not supported by the API: {sorted(set(dropped))}")
        api_policy = {
            'name': policy['name'],
            'description': policy.get('description', ''),
            'statements': statements
        }
        return self._request('PUT', f'/api/v2/rbac/policies/{name}', api_policy)
    
    def get_roles(self) -> Tuple[bool, List[dict]]:
        """Get all existing roles."""
        success, result = self._request('GET', '/api/v2/rbac/roles')
        if success:
            return True, result if isinstance(result, list) else result.get('data', [])
        return False, []
    
    def create_role(self, role: dict) -> Tuple[bool, dict]:
        """Create a new role."""
        api_role = {
            'name': role['name'],
            'isDefault': role.get('isDefault', False),
            'policyNames': role.get('policyNames', [])
        }
        return self._request('POST', '/api/v2/rbac/roles', api_role)

    def delete_policy(self, name: str) -> Tuple[bool, dict]:
        """Delete a policy by name."""
        return self._request('DELETE', f'/api/v2/rbac/policies/{name}')

    def delete_role(self, name: str) -> Tuple[bool, dict]:
        """Delete a role by name."""
        return self._request('DELETE', f'/api/v2/rbac/roles/{name}')


class PolicyApplier:
    """Handles applying policies to Komodor."""
    
    def __init__(self, api_client: Optional[KomodorAPIClient] = None, dry_run: bool = True):
        self.api_client = api_client
        self.dry_run = dry_run
        self.results = {
            'created': [],
            'updated': [],
            'skipped': [],
            'failed': [],
            'timestamp': datetime.now().isoformat()
        }
    
    def apply_policies(self, policies: List[dict], comparison: dict = None) -> dict:
        """
        Apply policies to Komodor.
        
        Args:
            policies: List of policy dictionaries to apply
            comparison: Optional comparison data to determine create vs update
            
        Returns:
            Results dictionary
        """
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Applying {len(policies)} policies...")
        
        # Determine which policies to create vs update
        existing_policy_names = set()
        if comparison:
            # Use comparison data
            for policy_info in comparison.get('existing_to_update', []):
                existing_policy_names.add(policy_info['name'])
        elif self.api_client and not self.dry_run:
            # Fetch existing policies from API
            success, existing_policies = self.api_client.get_policies()
            if success:
                existing_policy_names = {p['name'] for p in existing_policies}
        
        for policy in policies:
            policy_name = policy['name']
            
            if policy_name in existing_policy_names:
                # Update existing policy
                self._update_policy(policy)
            else:
                # Create new policy
                self._create_policy(policy)
            
            # Rate limiting
            if not self.dry_run:
                time.sleep(0.5)
        
        return self.results
    
    def _write_with_action_retries(self, policy: dict, write):
        """
        Call write(policy), retrying without actions the API rejects for the
        requested scope (e.g. add-on actions that cannot be namespace-scoped).
        Returns (success, result, removed_actions).
        """
        import copy
        working = copy.deepcopy(policy)
        removed = []
        result = {}
        for _ in range(40):
            success, result = write(working)
            if success:
                return True, result, removed
            m = re.search(r"action '([^']+)' is not allowed", str(result.get('error', '')))
            if not m:
                return False, result, removed
            bad = m.group(1)
            removed.append(bad)
            for stmt in working.get('statements', []):
                if bad in stmt.get('actions', []):
                    stmt['actions'] = [a for a in stmt['actions'] if a != bad]
            working['statements'] = [s for s in working.get('statements', []) if s.get('actions')]
        return False, result, removed

    def _create_policy(self, policy: dict):
        """Create a new policy."""
        policy_name = policy['name']
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would CREATE policy: {policy_name}")
            self.results['created'].append({
                'name': policy_name,
                'actions_count': sum(len(s.get('actions', [])) for s in policy.get('statements', [])),
                'status': 'dry_run'
            })
            return
        
        if not self.api_client:
            logger.error(f"No API client - cannot create policy: {policy_name}")
            self.results['failed'].append({
                'name': policy_name,
                'error': 'No API client configured'
            })
            return
        
        success, result, removed = self._write_with_action_retries(policy, self.api_client.create_policy)
        if removed:
            logger.warning(f"{policy_name}: removed actions rejected by the API for this scope: {sorted(set(removed))}")
        
        if success:
            logger.info(f"CREATED policy: {policy_name}")
            self.results['created'].append({
                'name': policy_name,
                'status': 'success'
            })
        else:
            error = result.get('error', 'Unknown error')
            if result.get('status') == 409:
                logger.warning(f"Policy already exists: {policy_name}")
                self.results['skipped'].append({
                    'name': policy_name,
                    'reason': 'already_exists'
                })
            else:
                logger.error(f"Failed to create policy {policy_name}: {error}")
                self.results['failed'].append({
                    'name': policy_name,
                    'error': error
                })
    
    def _update_policy(self, policy: dict):
        """Update an existing policy."""
        policy_name = policy['name']
        
        if self.dry_run:
            logger.info(f"[DRY RUN] Would UPDATE policy: {policy_name}")
            self.results['updated'].append({
                'name': policy_name,
                'actions_count': sum(len(s.get('actions', [])) for s in policy.get('statements', [])),
                'status': 'dry_run'
            })
            return
        
        if not self.api_client:
            logger.error(f"No API client - cannot update policy: {policy_name}")
            self.results['failed'].append({
                'name': policy_name,
                'error': 'No API client configured'
            })
            return
        
        success, result, removed = self._write_with_action_retries(
            policy, lambda pol: self.api_client.update_policy(policy_name, pol))
        if removed:
            logger.warning(f"{policy_name}: removed actions rejected by the API for this scope: {sorted(set(removed))}")
        
        if success:
            logger.info(f"UPDATED policy: {policy_name}")
            self.results['updated'].append({
                'name': policy_name,
                'status': 'success'
            })
        else:
            error = result.get('error', 'Unknown error')
            logger.error(f"Failed to update policy {policy_name}: {error}")
            self.results['failed'].append({
                'name': policy_name,
                'error': error
            })
    
    def apply_roles(self, roles: List[dict]) -> dict:
        """Apply roles to Komodor."""
        logger.info(f"{'[DRY RUN] ' if self.dry_run else ''}Applying {len(roles)} roles...")
        
        # The API returns 500 (not 409) for duplicate role names, so check
        # existence up front instead of interpreting error codes.
        existing_role_names = set()
        if self.api_client and not self.dry_run:
            ok, existing = self.api_client.get_roles()
            if ok:
                existing_role_names = {r.get('name') for r in existing}
        
        for role in roles:
            role_name = role['name']
            
            if role_name in existing_role_names:
                logger.info(f"Role already exists (skipped): {role_name}")
                self.results['skipped'].append({
                    'type': 'role',
                    'name': role_name,
                    'reason': 'already_exists'
                })
                continue
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would CREATE role: {role_name}")
                self.results['created'].append({
                    'type': 'role',
                    'name': role_name,
                    'policies': role.get('policyNames', []),
                    'status': 'dry_run'
                })
                continue
            
            if self.api_client:
                success, result = self.api_client.create_role(role)
                if success:
                    logger.info(f"CREATED role: {role_name}")
                elif result.get('status') == 409:
                    logger.info(f"Role already exists (skipped): {role_name}")
                    self.results['skipped'].append({
                        'type': 'role',
                        'name': role_name,
                        'reason': 'already_exists'
                    })
                else:
                    logger.error(f"Failed to create role {role_name}: {result.get('error')}")
                    self.results['failed'].append({
                        'type': 'role',
                        'name': role_name,
                        'error': result.get('error')
                    })
        
        # Ensure role -> policy links; role creation does not reliably attach
        # policies (especially when the role pre-existed the policy).
        if self.api_client and not self.dry_run and roles:
            ok_p, policies = self.api_client.get_policies()
            ok_r, existing_roles = self.api_client.get_roles()
            if ok_p and ok_r:
                pid = {p.get('name'): p.get('id') for p in policies}
                rmap = {r.get('name'): r for r in existing_roles}
                for role in roles:
                    rec = rmap.get(role['name'])
                    if not rec:
                        continue
                    linked = {pl.get('name') for pl in rec.get('policies') or []}
                    for pol_name in role.get('policyNames', []):
                        if pol_name in linked or pol_name not in pid:
                            continue
                        ok, res = self.api_client.attach_policy_to_role(rec['id'], pid[pol_name])
                        if ok:
                            logger.info(f"Linked policy {pol_name} -> role {role['name']}")
                        else:
                            logger.warning(f"Could not link {pol_name} -> role {role['name']}: {res.get('error')}")
        
        return self.results


def print_results(results: dict, dry_run: bool):
    """Print apply results."""
    print("\n" + "=" * 60)
    print(f"APPLY RESULTS {'(DRY RUN)' if dry_run else ''}")
    print("=" * 60)
    
    print(f"\nCreated: {len(results['created'])}")
    for item in results['created'][:5]:
        print(f"  + {item['name']}")
    if len(results['created']) > 5:
        print(f"  ... and {len(results['created']) - 5} more")
    
    print(f"\nUpdated: {len(results['updated'])}")
    for item in results['updated'][:5]:
        print(f"  ~ {item['name']}")
    if len(results['updated']) > 5:
        print(f"  ... and {len(results['updated']) - 5} more")
    
    if results['skipped']:
        print(f"\nSkipped: {len(results['skipped'])}")
        for item in results['skipped'][:3]:
            print(f"  - {item['name']}: {item.get('reason', 'unknown')}")
    
    if results['failed']:
        print(f"\nFailed: {len(results['failed'])}")
        for item in results['failed'][:5]:
            print(f"  ! {item['name']}: {item.get('error', 'unknown')}")
    
    print("=" * 60)
    
    if dry_run:
        print("\nThis was a DRY RUN. No changes were made.")
        print("Remove --dry-run to apply changes.")


def main():
    parser = argparse.ArgumentParser(
        description='Apply generated policies to Komodor'
    )
    parser.add_argument(
        '--policies', '-p',
        type=Path,
        required=True,
        help='Generated policies file (all_policies.json)'
    )
    parser.add_argument(
        '--comparison', '-c',
        type=Path,
        help='Comparison file to determine create vs update'
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Preview changes without applying'
    )
    parser.add_argument(
        '--api-key',
        help='Komodor API key (or set KOMODOR_API_KEY env var)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output file for results JSON'
    )
    parser.add_argument(
        '--include-roles',
        action='store_true',
        help='Also create roles that reference the policies'
    )
    
    args = parser.parse_args()
    
    # Load policies
    logger.info(f"Loading policies from: {args.policies}")
    with open(args.policies) as f:
        policy_data = json.load(f)
    
    policies = policy_data.get('policies', [])
    roles = policy_data.get('roles', [])
    logger.info(f"Loaded {len(policies)} policies, {len(roles)} roles")
    
    # Load comparison if provided
    comparison = None
    if args.comparison:
        with open(args.comparison) as f:
            comparison = json.load(f)
    
    # Setup API client
    api_client = None
    api_key = args.api_key or os.getenv('KOMODOR_API_KEY')
    
    if not args.dry_run:
        if not api_key:
            logger.error("API key required for non-dry-run mode")
            logger.info("Set KOMODOR_API_KEY environment variable or use --api-key")
            logger.info("Or use --dry-run to preview changes")
            sys.exit(1)
        api_client = KomodorAPIClient(api_key)
    
    # Apply policies
    applier = PolicyApplier(api_client=api_client, dry_run=args.dry_run)
    results = applier.apply_policies(policies, comparison)
    
    # Apply roles if requested
    if args.include_roles and roles:
        applier.apply_roles(roles)
    
    # Save results
    if args.output:
        output_path = args.output
    else:
        output_path = args.policies.parent / f'apply_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to: {output_path}")
    
    # Print summary
    print_results(results, args.dry_run)
    
    if not args.dry_run and not results['failed']:
        print("\nPolicies applied successfully!")
        print("Users with matching identity groups will now have these permissions in Komodor.")


if __name__ == '__main__':
    main()
