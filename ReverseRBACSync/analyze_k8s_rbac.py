#!/usr/bin/env python3
"""
Analyze Kubernetes RBAC data fetched from clusters.

This script parses ClusterRoles, ClusterRoleBindings, Roles, RoleBindings,
and ServiceAccounts to extract and summarize the permission model.

Usage:
    python analyze_k8s_rbac.py --input data/<account>/<timestamp>/
"""

import argparse
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Subject:
    """Represents a subject (User, Group, or ServiceAccount) in a RoleBinding."""
    kind: str  # User, Group, ServiceAccount
    name: str
    namespace: Optional[str] = None
    
    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RBACRule:
    """Represents a single RBAC rule from a Role/ClusterRole."""
    verbs: List[str]
    resources: List[str]
    api_groups: List[str]
    resource_names: Optional[List[str]] = None
    
    def to_dict(self):
        return asdict(self)


@dataclass
class RoleInfo:
    """Parsed information about a Role or ClusterRole."""
    name: str
    kind: str  # Role or ClusterRole
    namespace: Optional[str]  # None for ClusterRole
    rules: List[RBACRule]
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            'name': self.name,
            'kind': self.kind,
            'namespace': self.namespace,
            'rules': [r.to_dict() for r in self.rules],
            'labels': self.labels,
            'annotations': self.annotations
        }


@dataclass
class BindingInfo:
    """Parsed information about a RoleBinding or ClusterRoleBinding."""
    name: str
    kind: str  # RoleBinding or ClusterRoleBinding
    namespace: Optional[str]  # None for ClusterRoleBinding
    role_ref: str  # Name of the Role/ClusterRole
    role_ref_kind: str  # Role or ClusterRole
    subjects: List[Subject]
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            'name': self.name,
            'kind': self.kind,
            'namespace': self.namespace,
            'role_ref': self.role_ref,
            'role_ref_kind': self.role_ref_kind,
            'subjects': [s.to_dict() for s in self.subjects],
            'labels': self.labels,
            'annotations': self.annotations
        }


@dataclass
class ServiceAccountInfo:
    """Parsed information about a ServiceAccount."""
    name: str
    namespace: str
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self):
        return asdict(self)


class K8sRBACAnalyzer:
    """Analyzer for Kubernetes RBAC resources."""
    
    def __init__(self):
        self.roles: Dict[str, RoleInfo] = {}  # key: "namespace/name" or "cluster/name"
        self.bindings: List[BindingInfo] = []
        self.service_accounts: Dict[str, ServiceAccountInfo] = {}
        
        # Analysis results
        self.subjects_to_roles: Dict[str, Set[str]] = defaultdict(set)
        self.roles_to_subjects: Dict[str, Set[str]] = defaultdict(set)
        self.groups: Set[str] = set()
        self.users: Set[str] = set()
        self.sa_bindings: Set[str] = set()
    
    def parse_labels(self, labels_str: str) -> Dict[str, str]:
        """Parse labels string into dictionary."""
        if not labels_str or labels_str == '<none>':
            return {}
        
        result = {}
        for pair in labels_str.split(','):
            if '=' in pair:
                key, value = pair.split('=', 1)
                result[key.strip()] = value.strip()
        return result
    
    def load_cluster_roles(self, data: List[dict]):
        """Load ClusterRoles from fetched data."""
        for item in data:
            # The ATM returns parsed data, structure may vary
            # Handle both raw K8s format and ATM-parsed format
            if 'metadata' in item:
                # Raw K8s format
                name = item['metadata'].get('name', '')
                rules_data = item.get('rules', [])
                labels = item['metadata'].get('labels', {}) or {}
                annotations = item['metadata'].get('annotations', {}) or {}
            else:
                # ATM-parsed format
                name = item.get('name', '')
                rules_data = item.get('rules', [])
                labels = self.parse_labels(item.get('labels', ''))
                annotations = self.parse_labels(item.get('annotations', ''))
            
            if not name:
                continue
            
            rules = []
            if rules_data:
                for rule in rules_data:
                    rules.append(RBACRule(
                        verbs=rule.get('verbs', []),
                        resources=rule.get('resources', []),
                        api_groups=rule.get('apiGroups', []),
                        resource_names=rule.get('resourceNames')
                    ))
            
            role_key = f"cluster/{name}"
            self.roles[role_key] = RoleInfo(
                name=name,
                kind='ClusterRole',
                namespace=None,
                rules=rules,
                labels=labels,
                annotations=annotations
            )
        
        logger.info(f"Loaded {len([r for r in self.roles.values() if r.kind == 'ClusterRole'])} ClusterRoles")
    
    def load_roles(self, data: List[dict]):
        """Load Roles from fetched data."""
        for item in data:
            if 'metadata' in item:
                name = item['metadata'].get('name', '')
                namespace = item['metadata'].get('namespace', 'default')
                rules_data = item.get('rules', [])
                labels = item['metadata'].get('labels', {}) or {}
                annotations = item['metadata'].get('annotations', {}) or {}
            else:
                name = item.get('name', '')
                namespace = item.get('namespace', 'default')
                rules_data = item.get('rules', [])
                labels = self.parse_labels(item.get('labels', ''))
                annotations = self.parse_labels(item.get('annotations', ''))
            
            if not name:
                continue
            
            rules = []
            if rules_data:
                for rule in rules_data:
                    rules.append(RBACRule(
                        verbs=rule.get('verbs', []),
                        resources=rule.get('resources', []),
                        api_groups=rule.get('apiGroups', []),
                        resource_names=rule.get('resourceNames')
                    ))
            
            role_key = f"{namespace}/{name}"
            self.roles[role_key] = RoleInfo(
                name=name,
                kind='Role',
                namespace=namespace,
                rules=rules,
                labels=labels,
                annotations=annotations
            )
        
        logger.info(f"Loaded {len([r for r in self.roles.values() if r.kind == 'Role'])} Roles")
    
    def load_cluster_role_bindings(self, data: List[dict]):
        """Load ClusterRoleBindings from fetched data."""
        for item in data:
            if 'metadata' in item:
                name = item['metadata'].get('name', '')
                role_ref = item.get('roleRef', {})
                subjects_data = item.get('subjects', []) or []
                labels = item['metadata'].get('labels', {}) or {}
                annotations = item['metadata'].get('annotations', {}) or {}
            else:
                name = item.get('name', '')
                role_ref_name = item.get('roleRef', '')
                # ATM-parsed format has subjects as comma-separated string
                subjects_str = item.get('subjects', '')
                labels = self.parse_labels(item.get('labels', ''))
                annotations = self.parse_labels(item.get('annotations', ''))
                
                # Reconstruct role_ref
                role_ref = {'name': role_ref_name, 'kind': 'ClusterRole'}
                
                # Parse subjects string (ATM returns comma-separated names)
                subjects_data = []
                if subjects_str:
                    for subj_name in subjects_str.split(','):
                        subj_name = subj_name.strip()
                        if subj_name:
                            # Default to Group for ATM-parsed data (common case)
                            subjects_data.append({
                                'kind': 'Group',
                                'name': subj_name
                            })
            
            if not name:
                continue
            
            subjects = []
            for subj in subjects_data:
                subjects.append(Subject(
                    kind=subj.get('kind', 'Unknown'),
                    name=subj.get('name', ''),
                    namespace=subj.get('namespace')
                ))
            
            self.bindings.append(BindingInfo(
                name=name,
                kind='ClusterRoleBinding',
                namespace=None,
                role_ref=role_ref.get('name', '') if isinstance(role_ref, dict) else role_ref,
                role_ref_kind=role_ref.get('kind', 'ClusterRole') if isinstance(role_ref, dict) else 'ClusterRole',
                subjects=subjects,
                labels=labels,
                annotations=annotations
            ))
        
        logger.info(f"Loaded {len([b for b in self.bindings if b.kind == 'ClusterRoleBinding'])} ClusterRoleBindings")
    
    def load_role_bindings(self, data: List[dict]):
        """Load RoleBindings from fetched data."""
        for item in data:
            if 'metadata' in item:
                name = item['metadata'].get('name', '')
                namespace = item['metadata'].get('namespace', 'default')
                role_ref = item.get('roleRef', {})
                subjects_data = item.get('subjects', []) or []
                labels = item['metadata'].get('labels', {}) or {}
                annotations = item['metadata'].get('annotations', {}) or {}
            else:
                name = item.get('name', '')
                namespace = item.get('namespace', 'default')
                role_ref_name = item.get('roleRef', '')
                subjects_str = item.get('subjects', '')
                labels = self.parse_labels(item.get('labels', ''))
                annotations = self.parse_labels(item.get('annotations', ''))
                
                role_ref = {'name': role_ref_name, 'kind': 'Role'}
                
                subjects_data = []
                if subjects_str:
                    for subj_name in subjects_str.split(','):
                        subj_name = subj_name.strip()
                        if subj_name:
                            subjects_data.append({
                                'kind': 'Group',
                                'name': subj_name
                            })
            
            if not name:
                continue
            
            subjects = []
            for subj in subjects_data:
                subjects.append(Subject(
                    kind=subj.get('kind', 'Unknown'),
                    name=subj.get('name', ''),
                    namespace=subj.get('namespace')
                ))
            
            self.bindings.append(BindingInfo(
                name=name,
                kind='RoleBinding',
                namespace=namespace,
                role_ref=role_ref.get('name', '') if isinstance(role_ref, dict) else role_ref,
                role_ref_kind=role_ref.get('kind', 'Role') if isinstance(role_ref, dict) else 'Role',
                subjects=subjects,
                labels=labels,
                annotations=annotations
            ))
        
        logger.info(f"Loaded {len([b for b in self.bindings if b.kind == 'RoleBinding'])} RoleBindings")
    
    def load_service_accounts(self, data: List[dict]):
        """Load ServiceAccounts from fetched data."""
        for item in data:
            if 'metadata' in item:
                name = item['metadata'].get('name', '')
                namespace = item['metadata'].get('namespace', 'default')
                labels = item['metadata'].get('labels', {}) or {}
                annotations = item['metadata'].get('annotations', {}) or {}
            else:
                name = item.get('name', '')
                namespace = item.get('namespace', 'default')
                labels = self.parse_labels(item.get('labels', ''))
                annotations = self.parse_labels(item.get('annotations', ''))
            
            if not name:
                continue
            
            sa_key = f"{namespace}/{name}"
            self.service_accounts[sa_key] = ServiceAccountInfo(
                name=name,
                namespace=namespace,
                labels=labels,
                annotations=annotations
            )
        
        logger.info(f"Loaded {len(self.service_accounts)} ServiceAccounts")
    
    def analyze(self):
        """Perform analysis on loaded RBAC data."""
        logger.info("Analyzing RBAC relationships...")
        
        for binding in self.bindings:
            role_key = f"cluster/{binding.role_ref}" if binding.role_ref_kind == 'ClusterRole' else f"{binding.namespace}/{binding.role_ref}"
            
            for subject in binding.subjects:
                subject_key = f"{subject.kind}:{subject.name}"
                if subject.namespace:
                    subject_key += f":{subject.namespace}"
                
                self.subjects_to_roles[subject_key].add(role_key)
                self.roles_to_subjects[role_key].add(subject_key)
                
                # Track by type
                if subject.kind == 'Group':
                    self.groups.add(subject.name)
                elif subject.kind == 'User':
                    self.users.add(subject.name)
                elif subject.kind == 'ServiceAccount':
                    self.sa_bindings.add(f"{subject.namespace or 'default'}/{subject.name}")
        
        logger.info(f"Found {len(self.groups)} unique groups")
        logger.info(f"Found {len(self.users)} unique users")
        logger.info(f"Found {len(self.sa_bindings)} ServiceAccount bindings")
    
    def get_subject_permissions(self, subject_key: str) -> Dict:
        """Get all permissions for a specific subject."""
        role_keys = self.subjects_to_roles.get(subject_key, set())
        
        all_rules = []
        namespaces = set()
        
        for role_key in role_keys:
            role = self.roles.get(role_key)
            if role:
                for rule in role.rules:
                    all_rules.append({
                        'role': role.name,
                        'role_kind': role.kind,
                        'namespace': role.namespace,
                        'verbs': rule.verbs,
                        'resources': rule.resources,
                        'api_groups': rule.api_groups
                    })
                if role.namespace:
                    namespaces.add(role.namespace)
        
        return {
            'subject': subject_key,
            'roles': list(role_keys),
            'namespaces': list(namespaces) if namespaces else ['cluster-wide'],
            'rules': all_rules
        }
    
    def generate_report(self) -> Dict:
        """Generate a comprehensive analysis report."""
        report = {
            'summary': {
                'total_cluster_roles': len([r for r in self.roles.values() if r.kind == 'ClusterRole']),
                'total_roles': len([r for r in self.roles.values() if r.kind == 'Role']),
                'total_cluster_role_bindings': len([b for b in self.bindings if b.kind == 'ClusterRoleBinding']),
                'total_role_bindings': len([b for b in self.bindings if b.kind == 'RoleBinding']),
                'total_service_accounts': len(self.service_accounts),
                'unique_groups': len(self.groups),
                'unique_users': len(self.users),
                'sa_bindings': len(self.sa_bindings)
            },
            'groups': {},
            'users': {},
            'service_accounts': {},
            'roles': {},
            'bindings': []
        }
        
        # Group permissions
        for group in sorted(self.groups):
            report['groups'][group] = self.get_subject_permissions(f"Group:{group}")
        
        # User permissions
        for user in sorted(self.users):
            report['users'][user] = self.get_subject_permissions(f"User:{user}")
        
        # ServiceAccount permissions
        for sa in sorted(self.sa_bindings):
            report['service_accounts'][sa] = self.get_subject_permissions(f"ServiceAccount:{sa.split('/')[-1]}:{sa.split('/')[0]}")
        
        # Role details
        for role_key, role in self.roles.items():
            report['roles'][role_key] = role.to_dict()
        
        # Binding details
        for binding in self.bindings:
            report['bindings'].append(binding.to_dict())
        
        return report


def load_rbac_data(input_dir: Path) -> Dict[str, List[dict]]:
    """Load RBAC data from directory."""
    data = {}
    
    # Try loading complete file first
    complete_file = list(input_dir.glob('*_rbac_complete.json'))
    if complete_file:
        with open(complete_file[0]) as f:
            raw_data = json.load(f)
        
        # Extract per-cluster data
        for account_name, clusters in raw_data.items():
            for cluster_name, resources in clusters.items():
                for resource_type, items in resources.items():
                    if resource_type not in data:
                        data[resource_type] = []
                    data[resource_type].extend(items)
        
        return data
    
    # Otherwise load from individual files
    for cluster_dir in input_dir.iterdir():
        if cluster_dir.is_dir():
            for resource_file in cluster_dir.glob('*.json'):
                resource_type = resource_file.stem
                # Normalize resource type names
                type_map = {
                    'clusterrole': 'ClusterRole',
                    'clusterrolebinding': 'ClusterRoleBinding',
                    'role': 'Role',
                    'rolebinding': 'RoleBinding',
                    'serviceaccount': 'ServiceAccount'
                }
                normalized_type = type_map.get(resource_type.lower(), resource_type)
                
                with open(resource_file) as f:
                    items = json.load(f)
                
                if normalized_type not in data:
                    data[normalized_type] = []
                data[normalized_type].extend(items)
    
    return data


def main():
    parser = argparse.ArgumentParser(
        description='Analyze Kubernetes RBAC data'
    )
    parser.add_argument(
        '--input', '-i',
        type=Path,
        required=True,
        help='Input directory containing fetched RBAC data'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output directory for analysis reports (default: reports/<account>/<timestamp>)'
    )
    parser.add_argument(
        '--account-name', '-a',
        default='account',
        help='Account name for output organization'
    )
    
    args = parser.parse_args()
    
    # Load data
    logger.info(f"Loading RBAC data from: {args.input}")
    data = load_rbac_data(args.input)
    
    if not data:
        logger.error("No RBAC data found in input directory")
        return
    
    # Create analyzer and load data
    analyzer = K8sRBACAnalyzer()
    
    if 'ClusterRole' in data:
        analyzer.load_cluster_roles(data['ClusterRole'])
    if 'Role' in data:
        analyzer.load_roles(data['Role'])
    if 'ClusterRoleBinding' in data:
        analyzer.load_cluster_role_bindings(data['ClusterRoleBinding'])
    if 'RoleBinding' in data:
        analyzer.load_role_bindings(data['RoleBinding'])
    if 'ServiceAccount' in data:
        analyzer.load_service_accounts(data['ServiceAccount'])
    
    # Analyze
    analyzer.analyze()
    
    # Generate report
    report = analyzer.generate_report()
    
    # Setup output directory
    if args.output:
        output_dir = args.output
    else:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_dir = Path(__file__).parent / 'reports' / args.account_name / timestamp
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save full report
    report_file = output_dir / 'rbac_analysis.json'
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    logger.info(f"Saved full analysis to: {report_file}")
    
    # Save summary
    summary_file = output_dir / 'summary.json'
    with open(summary_file, 'w') as f:
        json.dump(report['summary'], f, indent=2)
    logger.info(f"Saved summary to: {summary_file}")
    
    # Save groups analysis
    groups_file = output_dir / 'groups_permissions.json'
    with open(groups_file, 'w') as f:
        json.dump(report['groups'], f, indent=2)
    logger.info(f"Saved groups analysis to: {groups_file}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("RBAC ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"\nSummary:")
    for key, value in report['summary'].items():
        print(f"  {key}: {value}")
    
    print(f"\nGroups found ({len(report['groups'])}):")
    for group in sorted(report['groups'].keys())[:20]:  # Show first 20
        roles = report['groups'][group]['roles']
        print(f"  - {group}: {len(roles)} role(s)")
    if len(report['groups']) > 20:
        print(f"  ... and {len(report['groups']) - 20} more")
    
    print(f"\nOutput directory: {output_dir}")
    print("=" * 60)


if __name__ == '__main__':
    main()
