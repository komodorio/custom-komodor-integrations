#!/usr/bin/env python3
"""
Map Kubernetes RBAC permissions to Komodor actions.

This script takes the analyzed K8s RBAC data and maps it to equivalent
Komodor actions, preparing for policy generation.

Usage:
    python map_to_komodor.py --input reports/<account>/<timestamp>/rbac_analysis.json
"""

import argparse
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional

from k8s_to_komodor_mapping import (
    map_k8s_rule_to_komodor_actions,
    categorize_actions,
    get_action_scope,
    KOMODOR_ACTIONS,
    UNSCOPED_ACTIONS,
    CLUSTER_SCOPED_ACTIONS,
    NAMESPACE_SCOPED_ACTIONS
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class MappedPermission:
    """A K8s permission mapped to Komodor actions."""
    subject: str
    subject_kind: str  # Group, User, ServiceAccount
    subject_name: str
    komodor_actions: Set[str]
    cluster_scope: bool  # True if cluster-wide, False if namespace-scoped
    namespaces: List[str]  # Empty list means cluster-wide
    source_roles: List[str]  # K8s roles that granted these permissions
    
    def to_dict(self):
        return {
            'subject': self.subject,
            'subject_kind': self.subject_kind,
            'subject_name': self.subject_name,
            'komodor_actions': sorted(list(self.komodor_actions)),
            'cluster_scope': self.cluster_scope,
            'namespaces': self.namespaces,
            'source_roles': self.source_roles
        }


class K8sToKomodorMapper:
    """Maps K8s RBAC permissions to Komodor actions."""
    
    def __init__(self):
        self.mappings: Dict[str, MappedPermission] = {}
        self.unmapped_rules: List[Dict] = []
        self.mapping_stats = {
            'total_rules_processed': 0,
            'rules_with_mappings': 0,
            'rules_without_mappings': 0,
            'total_komodor_actions_mapped': 0
        }
    
    def map_analysis(self, analysis: Dict, cluster_name: str = None) -> Dict[str, MappedPermission]:
        """
        Map analyzed RBAC data to Komodor actions.
        
        Args:
            analysis: The output from analyze_k8s_rbac.py
            cluster_name: Optional cluster name for scoping
            
        Returns:
            Dictionary of subject -> MappedPermission
        """
        # Process groups
        for group_name, group_data in analysis.get('groups', {}).items():
            self._process_subject(
                subject_key=f"Group:{group_name}",
                subject_kind='Group',
                subject_name=group_name,
                subject_data=group_data,
                cluster_name=cluster_name
            )
        
        # Process users
        for user_name, user_data in analysis.get('users', {}).items():
            self._process_subject(
                subject_key=f"User:{user_name}",
                subject_kind='User',
                subject_name=user_name,
                subject_data=user_data,
                cluster_name=cluster_name
            )
        
        # Process service accounts
        for sa_key, sa_data in analysis.get('service_accounts', {}).items():
            sa_name = sa_key.split('/')[-1] if '/' in sa_key else sa_key
            self._process_subject(
                subject_key=f"ServiceAccount:{sa_key}",
                subject_kind='ServiceAccount',
                subject_name=sa_name,
                subject_data=sa_data,
                cluster_name=cluster_name
            )
        
        return self.mappings
    
    def _process_subject(
        self,
        subject_key: str,
        subject_kind: str,
        subject_name: str,
        subject_data: Dict,
        cluster_name: str = None
    ):
        """Process a single subject's permissions."""
        all_actions = set()
        namespaces = set()
        source_roles = []
        is_cluster_wide = False
        
        for rule in subject_data.get('rules', []):
            self.mapping_stats['total_rules_processed'] += 1
            
            verbs = rule.get('verbs', [])
            resources = rule.get('resources', [])
            api_groups = rule.get('api_groups', [])
            namespace = rule.get('namespace')
            role_kind = rule.get('role_kind', 'Role')
            role_name = rule.get('role', '')
            
            # Map to Komodor actions
            komodor_actions = map_k8s_rule_to_komodor_actions(verbs, resources, api_groups)
            
            if komodor_actions:
                self.mapping_stats['rules_with_mappings'] += 1
                all_actions.update(komodor_actions)
                self.mapping_stats['total_komodor_actions_mapped'] += len(komodor_actions)
            else:
                self.mapping_stats['rules_without_mappings'] += 1
                self.unmapped_rules.append({
                    'subject': subject_key,
                    'role': role_name,
                    'verbs': verbs,
                    'resources': resources,
                    'api_groups': api_groups
                })
            
            # Track scope
            if role_kind == 'ClusterRole' and namespace is None:
                is_cluster_wide = True
            elif namespace:
                namespaces.add(namespace)
            
            # Track source roles
            if role_name and role_name not in source_roles:
                source_roles.append(role_name)
        
        if all_actions:
            self.mappings[subject_key] = MappedPermission(
                subject=subject_key,
                subject_kind=subject_kind,
                subject_name=subject_name,
                komodor_actions=all_actions,
                cluster_scope=is_cluster_wide,
                namespaces=sorted(list(namespaces)),
                source_roles=source_roles
            )
    
    def generate_mapping_report(self) -> Dict:
        """Generate a comprehensive mapping report."""
        report = {
            'statistics': self.mapping_stats,
            'subjects_by_kind': {
                'groups': [],
                'users': [],
                'service_accounts': []
            },
            'mappings': {},
            'unmapped_rules': self.unmapped_rules,
            'action_summary': defaultdict(int)
        }
        
        for subject_key, mapping in self.mappings.items():
            mapping_dict = mapping.to_dict()
            report['mappings'][subject_key] = mapping_dict
            
            # Categorize by kind
            if mapping.subject_kind == 'Group':
                report['subjects_by_kind']['groups'].append(mapping_dict)
            elif mapping.subject_kind == 'User':
                report['subjects_by_kind']['users'].append(mapping_dict)
            elif mapping.subject_kind == 'ServiceAccount':
                report['subjects_by_kind']['service_accounts'].append(mapping_dict)
            
            # Count action usage
            for action in mapping.komodor_actions:
                report['action_summary'][action] += 1
        
        # Convert action_summary to regular dict for JSON serialization
        report['action_summary'] = dict(report['action_summary'])
        
        return report
    
    def get_subjects_needing_actions(self, actions: Set[str]) -> List[str]:
        """Find subjects that need specific actions."""
        matching_subjects = []
        for subject_key, mapping in self.mappings.items():
            if mapping.komodor_actions.intersection(actions):
                matching_subjects.append(subject_key)
        return matching_subjects


def load_analysis(input_path: Path) -> Dict:
    """Load analysis data from file."""
    with open(input_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description='Map K8s RBAC permissions to Komodor actions'
    )
    parser.add_argument(
        '--input', '-i',
        type=Path,
        required=True,
        help='Input file (rbac_analysis.json from analyze_k8s_rbac.py)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output directory (default: same as input directory)'
    )
    parser.add_argument(
        '--cluster-name', '-c',
        help='Cluster name for scoping'
    )
    
    args = parser.parse_args()
    
    # Load analysis
    logger.info(f"Loading analysis from: {args.input}")
    analysis = load_analysis(args.input)
    
    # Create mapper and process
    mapper = K8sToKomodorMapper()
    mapper.map_analysis(analysis, args.cluster_name)
    
    # Generate report
    report = mapper.generate_mapping_report()
    
    # Setup output directory
    if args.output:
        output_dir = args.output
    else:
        output_dir = args.input.parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save mapping report
    mapping_file = output_dir / 'komodor_mapping.json'
    with open(mapping_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Saved mapping report to: {mapping_file}")
    
    # Save groups mapping (most relevant for IdP integration)
    groups_mapping_file = output_dir / 'groups_komodor_mapping.json'
    with open(groups_mapping_file, 'w') as f:
        json.dump(report['subjects_by_kind']['groups'], f, indent=2)
    logger.info(f"Saved groups mapping to: {groups_mapping_file}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("K8S TO KOMODOR MAPPING COMPLETE")
    print("=" * 60)
    
    print(f"\nStatistics:")
    for key, value in report['statistics'].items():
        print(f"  {key}: {value}")
    
    print(f"\nSubjects mapped:")
    print(f"  Groups: {len(report['subjects_by_kind']['groups'])}")
    print(f"  Users: {len(report['subjects_by_kind']['users'])}")
    print(f"  ServiceAccounts: {len(report['subjects_by_kind']['service_accounts'])}")
    
    print(f"\nTop Komodor actions mapped:")
    sorted_actions = sorted(report['action_summary'].items(), key=lambda x: x[1], reverse=True)
    for action, count in sorted_actions[:15]:
        print(f"  {action}: {count} subject(s)")
    
    if report['unmapped_rules']:
        print(f"\nWarning: {len(report['unmapped_rules'])} rules could not be mapped")
        print("  (See unmapped_rules in komodor_mapping.json for details)")
    
    print(f"\nOutput directory: {output_dir}")
    print("=" * 60)
    
    # Show sample group mapping
    if report['subjects_by_kind']['groups']:
        print("\nSample Group Mapping:")
        sample = report['subjects_by_kind']['groups'][0]
        print(f"  Group: {sample['subject_name']}")
        print(f"  Cluster-wide: {sample['cluster_scope']}")
        print(f"  Namespaces: {sample['namespaces'] or 'all'}")
        print(f"  Actions ({len(sample['komodor_actions'])}):")
        for action in sorted(sample['komodor_actions'])[:10]:
            print(f"    - {action}")
        if len(sample['komodor_actions']) > 10:
            print(f"    ... and {len(sample['komodor_actions']) - 10} more")


if __name__ == '__main__':
    main()
