#!/usr/bin/env python3
"""
Generate Komodor policies from mapped K8s RBAC permissions.

This script takes the K8s-to-Komodor mapping and generates Komodor policy
JSON files that can be imported or created via API.

Usage:
    python generate_komodor_policies.py --input reports/<account>/<timestamp>/komodor_mapping.json
"""

import argparse
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional

from k8s_to_komodor_mapping import (
    UNSCOPED_ACTIONS,
    CLUSTER_SCOPED_ACTIONS,
    NAMESPACE_SCOPED_ACTIONS,
    categorize_actions
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KomodorPolicyGenerator:
    """Generates Komodor policies from mapped permissions."""
    
    def __init__(self, cluster_name: str = None, account_name: str = None,
                 include_system_subjects: bool = False):
        self.cluster_name = cluster_name
        self.account_name = account_name
        self.include_system_subjects = include_system_subjects
        self.policies: List[Dict] = []
        self.roles: List[Dict] = []
        self.skipped_system_subjects: List[str] = []

    @staticmethod
    def is_system_subject(name: str) -> bool:
        """K8s/cloud-managed identities that should not become IdP-facing policies."""
        return name.startswith(('system:', 'eks:', 'gke:')) or name == 'kubelet'
    
    def sanitize_name(self, name: str) -> str:
        """Convert a name to a valid Komodor policy/role name."""
        # Replace special characters with hyphens
        sanitized = re.sub(r'[^a-zA-Z0-9-_]', '-', name)
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        # Lowercase
        return sanitized.lower()
    
    def generate_policy_from_mapping(
        self,
        subject_name: str,
        subject_kind: str,
        komodor_actions: List[str],
        cluster_scope: bool,
        namespaces: List[str],
        source_roles: List[str]
    ) -> Dict:
        """
        Generate a Komodor policy from a mapped subject.
        
        Args:
            subject_name: Name of the subject (group/user)
            subject_kind: Type of subject (Group/User/ServiceAccount)
            komodor_actions: List of Komodor actions
            cluster_scope: Whether this is cluster-wide access
            namespaces: List of namespaces (empty for cluster-wide)
            source_roles: K8s roles that granted these permissions
            
        Returns:
            Komodor policy dictionary
        """
        # Categorize actions by scope
        action_set = set(komodor_actions)
        categorized = categorize_actions(action_set)
        
        statements = []
        
        # Generate statements based on action scopes
        # Namespace-scoped actions
        if categorized['namespace']:
            if cluster_scope or not namespaces:
                # Full cluster access
                statements.append({
                    'actions': sorted(list(categorized['namespace'])),
                    'resources': [{'cluster': self.cluster_name or '*', 'namespaces': ['*']}],
                    'resourcesScope': None
                })
            else:
                # Namespace-specific access
                statements.append({
                    'actions': sorted(list(categorized['namespace'])),
                    'resources': [{'cluster': self.cluster_name or '*', 'namespaces': namespaces}],
                    'resourcesScope': None
                })
        
        # Cluster-scoped actions (e.g., node operations)
        if categorized['cluster']:
            statements.append({
                'actions': sorted(list(categorized['cluster'])),
                'resources': [{'cluster': self.cluster_name or '*', 'namespaces': []}],
                'resourcesScope': None
            })
        
        # Unscoped actions (Komodor admin)
        if categorized['unscoped']:
            statements.append({
                'actions': sorted(list(categorized['unscoped'])),
                'resources': None,  # Unscoped actions don't have resource restrictions
                'resourcesScope': None
            })
        
        # Clean up empty resourcesScope
        for stmt in statements:
            if stmt.get('resourcesScope') is None:
                del stmt['resourcesScope']
            if stmt.get('resources') is None:
                del stmt['resources']
        
        policy_name = f"k8s-sync-{self.sanitize_name(subject_kind)}-{self.sanitize_name(subject_name)}"
        
        policy = {
            'name': policy_name,
            'description': f"Auto-generated policy for {subject_kind} '{subject_name}' (synced from K8s RBAC: {', '.join(source_roles[:3])}{'...' if len(source_roles) > 3 else ''})",
            'type': 'v2',  # Using v2 policy format
            'statements': statements,
            'tags': {
                'source': 'k8s-rbac-sync',
                'subject_kind': subject_kind.lower(),
                'subject_name': subject_name,
                'sync_timestamp': datetime.now().isoformat()
            }
        }
        
        return policy
    
    def generate_role_from_policy(self, policy: Dict, subject_name: str) -> Dict:
        """
        Generate a Komodor role that references a policy.
        
        Args:
            policy: The Komodor policy dictionary
            subject_name: Name of the subject for the role
            
        Returns:
            Komodor role dictionary
        """
        role_name = f"k8s-sync-{self.sanitize_name(subject_name)}"
        
        role = {
            'name': role_name,
            'isDefault': False,
            'policyNames': [policy['name']],
            'description': f"Auto-generated role for '{subject_name}' (synced from K8s RBAC)"
        }
        
        return role
    
    def generate_from_mapping_report(self, mapping_report) -> Dict:
        """
        Generate policies and roles from a full mapping report.
        
        Args:
            mapping_report: Output from map_to_komodor.py (can be list or dict)
            
        Returns:
            Dictionary with policies and roles
        """
        # Handle both list format (groups_komodor_mapping.json) and dict format
        if isinstance(mapping_report, list):
            # Direct list of mappings
            mappings = mapping_report
        elif isinstance(mapping_report, dict):
            # Nested structure with subjects_by_kind
            mappings = []
            for group_mapping in mapping_report.get('subjects_by_kind', {}).get('groups', []):
                mappings.append(group_mapping)
            for user_mapping in mapping_report.get('subjects_by_kind', {}).get('users', []):
                mappings.append(user_mapping)
        else:
            mappings = []
        
        # Process all mappings
        for mapping in mappings:
            subject_kind = mapping.get('subject_kind', 'Group')
            subject_name = mapping.get('subject_name', '')
            
            # Skip cluster/cloud system identities unless explicitly included
            if not self.include_system_subjects and self.is_system_subject(subject_name):
                self.skipped_system_subjects.append(subject_name)
                continue
            komodor_actions = mapping.get('komodor_actions', [])
            cluster_scope = mapping.get('cluster_scope', True)
            namespaces = mapping.get('namespaces', [])
            source_roles = mapping.get('source_roles', [])
            
            # Skip if no actions
            if not komodor_actions:
                continue
            
            policy = self.generate_policy_from_mapping(
                subject_name=subject_name,
                subject_kind=subject_kind,
                komodor_actions=komodor_actions,
                cluster_scope=cluster_scope,
                namespaces=namespaces,
                source_roles=source_roles
            )
            self.policies.append(policy)
            
            # Generate a role per subject: groups are assigned via IdP/SAML
            # (komodorRoles attribute); users can be assigned directly to the
            # matching Komodor user (see sync_once.py --assign-user-roles).
            if subject_kind in ('Group', 'User'):
                role = self.generate_role_from_policy(policy, subject_name)
                self.roles.append(role)
        
        return {
            'policies': self.policies,
            'roles': self.roles,
            'summary': {
                'total_policies': len(self.policies),
                'total_roles': len(self.roles),
                'skipped_system_subjects': sorted(set(self.skipped_system_subjects)),
                'generated_at': datetime.now().isoformat(),
                'cluster_name': self.cluster_name,
                'account_name': self.account_name
            }
        }
    
    def generate_consolidated_policies(self, mapping_report: Dict) -> Dict:
        """
        Generate consolidated policies grouped by similar permission sets.
        
        This reduces the number of policies by combining subjects with
        identical permissions into shared policies.
        
        Args:
            mapping_report: Output from map_to_komodor.py
            
        Returns:
            Dictionary with consolidated policies
        """
        # Group mappings by their action signature
        action_groups = defaultdict(list)
        
        for group_mapping in mapping_report.get('subjects_by_kind', {}).get('groups', []):
            # Create a signature from actions and scope
            action_sig = (
                tuple(sorted(group_mapping['komodor_actions'])),
                group_mapping['cluster_scope'],
                tuple(sorted(group_mapping['namespaces']))
            )
            action_groups[action_sig].append(group_mapping)
        
        consolidated_policies = []
        group_to_policy_map = {}
        
        for idx, (action_sig, mappings) in enumerate(action_groups.items()):
            actions, cluster_scope, namespaces = action_sig
            
            # Determine policy name based on the permission type
            if len(mappings) == 1:
                policy_name = f"k8s-sync-{self.sanitize_name(mappings[0]['subject_name'])}"
            else:
                # Name based on permission level
                if 'view:all' in actions and len(actions) > 20:
                    policy_name = f"k8s-sync-full-access-{idx + 1}"
                elif all(a.startswith('view:') for a in actions):
                    policy_name = f"k8s-sync-read-only-{idx + 1}"
                elif any(a.startswith('edit:') or a.startswith('delete:') for a in actions):
                    policy_name = f"k8s-sync-read-write-{idx + 1}"
                else:
                    policy_name = f"k8s-sync-custom-{idx + 1}"
            
            # Generate policy
            policy = self.generate_policy_from_mapping(
                subject_name=mappings[0]['subject_name'],  # Use first subject as reference
                subject_kind='Group',
                komodor_actions=list(actions),
                cluster_scope=cluster_scope,
                namespaces=list(namespaces),
                source_roles=mappings[0]['source_roles']
            )
            policy['name'] = policy_name
            policy['description'] = f"Shared policy for groups: {', '.join([m['subject_name'] for m in mappings[:5]])}{'...' if len(mappings) > 5 else ''}"
            policy['tags']['shared_by_groups'] = [m['subject_name'] for m in mappings]
            
            consolidated_policies.append(policy)
            
            # Map each group to this policy
            for mapping in mappings:
                group_to_policy_map[mapping['subject_name']] = policy_name
        
        return {
            'policies': consolidated_policies,
            'group_to_policy_map': group_to_policy_map,
            'summary': {
                'original_groups': sum(len(v) for v in action_groups.values()),
                'consolidated_policies': len(consolidated_policies),
                'reduction_ratio': f"{(1 - len(consolidated_policies) / max(1, sum(len(v) for v in action_groups.values()))) * 100:.1f}%"
            }
        }


def load_mapping(input_path: Path) -> Dict:
    """Load mapping report from file."""
    with open(input_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Komodor policies from K8s RBAC mapping'
    )
    parser.add_argument(
        '--input', '-i',
        type=Path,
        required=True,
        help='Input file (komodor_mapping.json from map_to_komodor.py)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output directory (default: generated_policies/<account>/<timestamp>)'
    )
    parser.add_argument(
        '--cluster-name', '-c',
        help='Cluster name for policy scoping'
    )
    parser.add_argument(
        '--account-name', '-a',
        default='account',
        help='Account name for organization'
    )
    parser.add_argument(
        '--consolidate',
        action='store_true',
        help='Consolidate similar policies to reduce count'
    )
    parser.add_argument(
        '--include-system-subjects',
        action='store_true',
        help='Also generate policies for system identities (system:*, eks:*, kubelet); skipped by default'
    )
    
    args = parser.parse_args()
    
    # Load mapping
    logger.info(f"Loading mapping from: {args.input}")
    mapping_report = load_mapping(args.input)
    
    # Create generator
    generator = KomodorPolicyGenerator(
        cluster_name=args.cluster_name,
        account_name=args.account_name,
        include_system_subjects=args.include_system_subjects
    )
    
    # Generate policies
    if args.consolidate:
        logger.info("Generating consolidated policies...")
        result = generator.generate_consolidated_policies(mapping_report)
        policies = result['policies']
    else:
        logger.info("Generating individual policies...")
        result = generator.generate_from_mapping_report(mapping_report)
        policies = result['policies']
    
    # Setup output directory
    if args.output:
        output_dir = args.output
    else:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_dir = Path(__file__).parent / 'generated_policies' / args.account_name / timestamp
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save all policies in one file
    all_policies_file = output_dir / 'all_policies.json'
    with open(all_policies_file, 'w') as f:
        json.dump(result, f, indent=2)
    logger.info(f"Saved all policies to: {all_policies_file}")
    
    # Save individual policy files
    policies_dir = output_dir / 'individual'
    policies_dir.mkdir(exist_ok=True)
    
    for policy in policies:
        policy_file = policies_dir / f"{policy['name']}.json"
        with open(policy_file, 'w') as f:
            json.dump(policy, f, indent=2)
    logger.info(f"Saved {len(policies)} individual policies to: {policies_dir}")
    
    # Save roles if generated
    if 'roles' in result and result['roles']:
        roles_file = output_dir / 'roles.json'
        with open(roles_file, 'w') as f:
            json.dump(result['roles'], f, indent=2)
        logger.info(f"Saved {len(result['roles'])} roles to: {roles_file}")
    
    # Save mapping (group -> policy) for reference
    if 'group_to_policy_map' in result:
        mapping_file = output_dir / 'group_to_policy_map.json'
        with open(mapping_file, 'w') as f:
            json.dump(result['group_to_policy_map'], f, indent=2)
        logger.info(f"Saved group mapping to: {mapping_file}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("KOMODOR POLICY GENERATION COMPLETE")
    print("=" * 60)
    
    if 'summary' in result:
        print("\nSummary:")
        for key, value in result['summary'].items():
            print(f"  {key}: {value}")
    
    print(f"\nGenerated {len(policies)} policies")
    
    if args.consolidate and 'original_groups' in result.get('summary', {}):
        print(f"  (Consolidated from {result['summary']['original_groups']} groups)")
        print(f"  Reduction: {result['summary']['reduction_ratio']}")
    
    print("\nSample policy structure:")
    if policies:
        sample = policies[0]
        print(f"  Name: {sample['name']}")
        print(f"  Statements: {len(sample['statements'])}")
        for idx, stmt in enumerate(sample['statements'][:2]):
            print(f"    Statement {idx + 1}:")
            print(f"      Actions: {len(stmt.get('actions', []))} action(s)")
            if 'resources' in stmt and stmt['resources']:
                res = stmt['resources'][0]
                print(f"      Cluster: {res.get('cluster', 'N/A')}")
                print(f"      Namespaces: {res.get('namespaces', [])}")
    
    print(f"\nOutput directory: {output_dir}")
    print("=" * 60)
    
    # Usage instructions
    print("\nNext steps:")
    print("  1. Review generated policies in:", output_dir)
    print("  2. Run compare_and_report.py to see diff with current Komodor config")
    print("  3. Import policies via Komodor API or manually in UI")


if __name__ == '__main__':
    main()
