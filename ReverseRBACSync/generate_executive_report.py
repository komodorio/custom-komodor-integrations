#!/usr/bin/env python3
"""
Generate comprehensive executive HTML report for the customer's account owner.

This script creates a detailed, presentation-ready report explaining:
- The business problem and current state
- K8s RBAC concepts with illustrative examples
- Complete analysis of all clusters and groups
- Policies to create with full details
- Implementation roadmap
- Remaining gaps

Usage:
    python generate_executive_report.py --summary reports/<account>/full_account_summary_<timestamp>.json
"""

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def normalize_group_name(name: str) -> str:
    """Normalize group name by converting colons to hyphens for matching.
    
    Handles both formats: "team-spaces:Owner" -> "team-spaces-owner"
    """
    return name.replace(':', '-').lower()


def denormalize_group_name(normalized: str, original_list: List[str]) -> str:
    """Find the original group name format from a normalized name.
    
    Returns the first matching original name from the list, or the normalized name if not found.
    """
    normalized_lower = normalized.lower()
    for orig in original_list:
        if normalize_group_name(orig) == normalized_lower:
            return orig
    return normalized


def load_summary_data(summary_file: Path) -> Dict:
    """Load the full account summary JSON."""
    with open(summary_file) as f:
        return json.load(f)


def load_cluster_groups_data(reports_dir: Path, timestamp: str) -> Dict[str, Dict]:
    """Load groups data from all cluster reports."""
    groups_data = {}
    
    for cluster_dir in reports_dir.glob(f"{timestamp}_*"):
        if not cluster_dir.is_dir():
            continue
        
        cluster_name = cluster_dir.name.replace(f"{timestamp}_", "")
        groups_file = cluster_dir / 'groups_permissions.json'
        
        if groups_file.exists():
            with open(groups_file) as f:
                cluster_groups = json.load(f)
                groups_data[cluster_name] = cluster_groups
    
    return groups_data


def load_cluster_mapping_data(reports_dir: Path, timestamp: str) -> Dict[str, List]:
    """Load Komodor mapping data from cluster reports."""
    mapping_data = {}
    
    for cluster_dir in reports_dir.glob(f"{timestamp}_*"):
        if not cluster_dir.is_dir():
            continue
        
        cluster_name = cluster_dir.name.replace(f"{timestamp}_", "")
        mapping_file = cluster_dir / 'groups_komodor_mapping.json'
        
        if mapping_file.exists():
            with open(mapping_file) as f:
                mapping = json.load(f)
                mapping_data[cluster_name] = mapping
    
    return mapping_data


def load_comparison_data(reports_dir: Path, timestamp: str) -> Dict[str, Dict]:
    """Load comparison data from cluster comparison reports."""
    comparison_data = {}
    
    for comp_dir in reports_dir.glob(f"comparison_{timestamp}_*"):
        if not comp_dir.is_dir():
            continue
        
        cluster_name = comp_dir.name.replace(f"comparison_{timestamp}_", "")
        comp_file = comp_dir / 'comparison.json'
        
        if comp_file.exists():
            with open(comp_file) as f:
                comp = json.load(f)
                comparison_data[cluster_name] = comp
    
    return comparison_data


def load_raw_rbac_data(data_dir: Path, timestamp: str) -> Dict[str, Dict]:
    """Load raw RBAC data files (ClusterRole, ClusterRoleBinding, Role, RoleBinding, ServiceAccount).
    
    Returns dict mapping cluster_name -> {
        'clusterroles': [...],
        'clusterrolebindings': [...],
        'roles': [...],
        'rolebindings': [...],
        'serviceaccounts': [...]
    }
    """
    rbac_data = {}
    
    # Find all cluster data directories
    for cluster_data_dir in data_dir.glob(f"{timestamp}_*"):
        if not cluster_data_dir.is_dir():
            continue
        
        cluster_name = cluster_data_dir.name.replace(f"{timestamp}_", "")
        cluster_subdir = cluster_data_dir / cluster_name
        
        if not cluster_subdir.exists():
            continue
        
        cluster_rbac = {
            'clusterroles': [],
            'clusterrolebindings': [],
            'roles': [],
            'rolebindings': [],
            'serviceaccounts': []
        }
        
        # Load each resource type
        for resource_type in ['clusterrole', 'clusterrolebinding', 'role', 'rolebinding', 'serviceaccount']:
            resource_file = cluster_subdir / f"{resource_type}.json"
            if resource_file.exists():
                try:
                    with open(resource_file) as f:
                        data = json.load(f)
                        # Handle both list and dict formats
                        if isinstance(data, list):
                            cluster_rbac[f"{resource_type}s"] = data
                        elif isinstance(data, dict):
                            cluster_rbac[f"{resource_type}s"] = [data]
                except Exception as e:
                    logger.warning(f"Failed to load {resource_file}: {e}")
        
        rbac_data[cluster_name] = cluster_rbac
    
    return rbac_data


def get_group_cluster_mapping(summary_data: Dict) -> Dict[str, List[str]]:
    """Map each group to clusters where it appears."""
    group_clusters = defaultdict(list)
    
    for result in summary_data.get('cluster_results', []):
        if result['status'] != 'completed':
            continue
        
        cluster = result['cluster']
        policy_names = result.get('summary', {}).get('new_policy_names', [])
        
        for policy_name in policy_names:
            if policy_name.startswith('k8s-sync-group-'):
                group_name = policy_name[15:]  # Remove prefix
                group_clusters[group_name].append(cluster)
    
    return dict(group_clusters)


def get_region_from_cluster(cluster_name: str) -> str:
    """Extract region from cluster name."""
    if cluster_name.startswith('us-east-'):
        return 'US East'
    elif cluster_name.startswith('us-west-'):
        return 'US West'
    elif cluster_name.startswith('ca-central-'):
        return 'Canada'
    elif cluster_name.startswith('eu-north-'):
        return 'EU'
    elif cluster_name.startswith('eu-west-'):
        return 'EU'
    elif cluster_name.startswith('eu-central-'):
        return 'EU'
    else:
        return 'Unknown'


def generate_html_report(summary_data: Dict, groups_data: Dict, mapping_data: Dict,
                        comparison_data: Dict, output_path: Path, data_dir: Path = None):
    """Generate the comprehensive executive HTML report."""
    
    # Extract key metrics
    account_display = str(summary_data.get('account_name', 'Account')).replace('-', ' ').replace('_', ' ').title()
    total_clusters = summary_data['total_clusters']
    successful = summary_data['successful_clusters']
    unique_groups = len(summary_data['unique_groups'])
    unique_policies = len(summary_data['unique_policies_needed'])
    timestamp = summary_data['timestamp']
    
    # Build group-to-cluster mapping
    group_clusters = get_group_cluster_mapping(summary_data)
    
    # Aggregate cluster statistics
    cluster_stats = []
    for result in summary_data.get('cluster_results', []):
        if result['status'] != 'completed':
            continue
        
        cluster = result['cluster']
        analysis = result.get('summary', {}).get('analysis', {})
        comparison = result.get('summary', {}).get('comparison', {})
        
        cluster_stats.append({
            'name': cluster,
            'region': get_region_from_cluster(cluster),
            'cluster_roles': analysis.get('total_cluster_roles', 0),
            'roles': analysis.get('total_roles', 0),
            'cluster_role_bindings': analysis.get('total_cluster_role_bindings', 0),
            'role_bindings': analysis.get('total_role_bindings', 0),
            'groups': analysis.get('unique_groups', 0),
            'policies': result.get('summary', {}).get('new_policies', 0),
            'html_report': result.get('html_report', '')
        })
    
    # Get action gaps from first comparison
    action_gaps = {'k8s_only': [], 'komodor_only': []}
    if comparison_data:
        first_comp = list(comparison_data.values())[0]
        action_diff = first_comp.get('action_diff', {})
        action_gaps['k8s_only'] = action_diff.get('in_k8s_not_komodor', [])
        action_gaps['komodor_only'] = action_diff.get('in_komodor_not_k8s', [])
    
    # Load raw RBAC data if data_dir is provided
    raw_rbac_data = {}
    if data_dir:
        raw_rbac_data = load_raw_rbac_data(data_dir, timestamp)
    
    # Generate HTML
    html = generate_html_content(
        summary_data=summary_data,
        cluster_stats=cluster_stats,
        groups_data=groups_data,
        mapping_data=mapping_data,
        comparison_data=comparison_data,
        raw_rbac_data=raw_rbac_data,
        group_clusters=group_clusters,
        action_gaps=action_gaps,
        timestamp=timestamp
    )
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    logger.info(f"Generated executive report: {output_path}")


def generate_rbac_resources_section(raw_rbac_data: Dict, cluster_stats: List[Dict]) -> str:
    """Generate section showing complete K8s RBAC resources."""
    if not raw_rbac_data:
        return '<p>Raw RBAC data not available. Run with --data-dir option.</p>'
    
    section_html = ""
    
    # Organize by cluster
    for stat in sorted(cluster_stats, key=lambda x: x['name']):
        cluster_name = stat['name']
        if cluster_name not in raw_rbac_data:
            continue
        
        cluster_rbac = raw_rbac_data[cluster_name]
        
        section_html += f'''
        <div class="cluster-rbac-section">
            <h3 style="margin-top: 2rem; margin-bottom: 1rem; color: var(--primary);">{cluster_name}</h3>
        '''
        
        # ClusterRoles
        clusterroles = cluster_rbac.get('clusterroles', [])
        if clusterroles:
            section_html += f'''
            <div class="rbac-resource-type">
                <h4>ClusterRoles ({len(clusterroles)})</h4>
                <div class="rbac-resource-list">
            '''
            # Show first 50, rest in expandable section
            for cr in clusterroles[:50]:
                name = cr.get('metadata', {}).get('name', cr.get('name', 'Unknown'))
                rules = cr.get('rules', []) or []
                section_html += f'''
                <div class="rbac-resource-card">
                    <div class="rbac-resource-header">
                        <strong>{name}</strong>
                    </div>
                    <div class="rbac-resource-body">
                        <strong>Rules ({len(rules)}):</strong>
                        <ul>
                '''
                for rule in rules:
                    verbs = ', '.join(rule.get('verbs', []))
                    resources = ', '.join(rule.get('resources', []))
                    api_groups = ', '.join(rule.get('apiGroups', []))
                    section_html += f'<li>Verbs: {verbs} | Resources: {resources} | API Groups: {api_groups}</li>'
                section_html += '''
                        </ul>
                    </div>
                </div>
                '''
            # Add expandable section for remaining items
            if len(clusterroles) > 50:
                section_html += f'''
                <div class="expandable-section">
                    <button class="expand-btn" onclick="toggleExpand(this, 'clusterroles-{cluster_name}')">
                        Show {len(clusterroles) - 50} more ClusterRoles
                    </button>
                    <div id="clusterroles-{cluster_name}" class="expandable-content" style="display: none;">
                '''
                for cr in clusterroles[50:]:
                    name = cr.get('metadata', {}).get('name', cr.get('name', 'Unknown'))
                    rules = cr.get('rules', []) or []
                    section_html += f'''
                    <div class="rbac-resource-card">
                        <div class="rbac-resource-header">
                            <strong>{name}</strong>
                        </div>
                        <div class="rbac-resource-body">
                            <strong>Rules ({len(rules)}):</strong>
                            <ul>
                    '''
                    for rule in rules:
                        verbs = ', '.join(rule.get('verbs', []))
                        resources = ', '.join(rule.get('resources', []))
                        api_groups = ', '.join(rule.get('apiGroups', []))
                        section_html += f'<li>Verbs: {verbs} | Resources: {resources} | API Groups: {api_groups}</li>'
                    section_html += '''
                            </ul>
                        </div>
                    </div>
                    '''
                section_html += '</div></div>'
            section_html += '</div></div>'
        
        # ClusterRoleBindings
        clusterrolebindings = cluster_rbac.get('clusterrolebindings', [])
        if clusterrolebindings:
            section_html += f'''
            <div class="rbac-resource-type">
                <h4>ClusterRoleBindings ({len(clusterrolebindings)})</h4>
                <div class="rbac-resource-list">
            '''
            for crb in clusterrolebindings[:50]:
                name = crb.get('metadata', {}).get('name', crb.get('name', 'Unknown'))
                role_ref = crb.get('roleRef', {})
                role_name = role_ref.get('name', 'Unknown') if isinstance(role_ref, dict) else role_ref
                subjects = crb.get('subjects', []) or []
                section_html += f'''
                <div class="rbac-resource-card">
                    <div class="rbac-resource-header">
                        <strong>{name}</strong> → <code>{role_name}</code>
                    </div>
                    <div class="rbac-resource-body">
                        <strong>Subjects ({len(subjects)}):</strong>
                        <ul>
                '''
                for subj in subjects:
                    if isinstance(subj, dict):
                        kind = subj.get('kind', 'Unknown')
                        subj_name = subj.get('name', 'Unknown')
                        section_html += f'<li>{kind}: {subj_name}</li>'
                    else:
                        section_html += f'<li>{subj}</li>'
                section_html += '''
                        </ul>
                    </div>
                </div>
                '''
            if len(clusterrolebindings) > 50:
                section_html += f'''
                <div class="expandable-section">
                    <button class="expand-btn" onclick="toggleExpand(this, 'clusterrolebindings-{cluster_name}')">
                        Show {len(clusterrolebindings) - 50} more ClusterRoleBindings
                    </button>
                    <div id="clusterrolebindings-{cluster_name}" class="expandable-content" style="display: none;">
                '''
                for crb in clusterrolebindings[50:]:
                    name = crb.get('metadata', {}).get('name', crb.get('name', 'Unknown'))
                    role_ref = crb.get('roleRef', {})
                    role_name = role_ref.get('name', 'Unknown') if isinstance(role_ref, dict) else role_ref
                    subjects = crb.get('subjects', []) or []
                    section_html += f'''
                    <div class="rbac-resource-card">
                        <div class="rbac-resource-header">
                            <strong>{name}</strong> → <code>{role_name}</code>
                        </div>
                        <div class="rbac-resource-body">
                            <strong>Subjects ({len(subjects)}):</strong>
                            <ul>
                    '''
                    for subj in subjects:
                        if isinstance(subj, dict):
                            kind = subj.get('kind', 'Unknown')
                            subj_name = subj.get('name', 'Unknown')
                            section_html += f'<li>{kind}: {subj_name}</li>'
                        else:
                            section_html += f'<li>{subj}</li>'
                    section_html += '''
                            </ul>
                        </div>
                    </div>
                    '''
                section_html += '</div></div>'
            section_html += '</div></div>'
        
        # Roles (namespace-scoped)
        roles = cluster_rbac.get('roles', [])
        if roles:
            section_html += f'''
            <div class="rbac-resource-type">
                <h4>Roles ({len(roles)})</h4>
                <div class="rbac-resource-list">
            '''
            for role in roles[:50]:
                name = role.get('metadata', {}).get('name', role.get('name', 'Unknown'))
                namespace = role.get('metadata', {}).get('namespace', role.get('namespace', 'default'))
                rules = role.get('rules', []) or []
                section_html += f'''
                <div class="rbac-resource-card">
                    <div class="rbac-resource-header">
                        <strong>{name}</strong> (namespace: <code>{namespace}</code>)
                    </div>
                    <div class="rbac-resource-body">
                        <strong>Rules ({len(rules)}):</strong>
                        <ul>
                '''
                for rule in rules:
                    verbs = ', '.join(rule.get('verbs', []))
                    resources = ', '.join(rule.get('resources', []))
                    api_groups = ', '.join(rule.get('apiGroups', []))
                    section_html += f'<li>Verbs: {verbs} | Resources: {resources} | API Groups: {api_groups}</li>'
                section_html += '''
                        </ul>
                    </div>
                </div>
                '''
            if len(roles) > 50:
                section_html += f'''
                <div class="expandable-section">
                    <button class="expand-btn" onclick="toggleExpand(this, 'roles-{cluster_name}')">
                        Show {len(roles) - 50} more Roles
                    </button>
                    <div id="roles-{cluster_name}" class="expandable-content" style="display: none;">
                '''
                for role in roles[50:]:
                    name = role.get('metadata', {}).get('name', role.get('name', 'Unknown'))
                    namespace = role.get('metadata', {}).get('namespace', role.get('namespace', 'default'))
                    rules = role.get('rules', []) or []
                    section_html += f'''
                    <div class="rbac-resource-card">
                        <div class="rbac-resource-header">
                            <strong>{name}</strong> (namespace: <code>{namespace}</code>)
                        </div>
                        <div class="rbac-resource-body">
                            <strong>Rules ({len(rules)}):</strong>
                            <ul>
                    '''
                    for rule in rules:
                        verbs = ', '.join(rule.get('verbs', []))
                        resources = ', '.join(rule.get('resources', []))
                        api_groups = ', '.join(rule.get('apiGroups', []))
                        section_html += f'<li>Verbs: {verbs} | Resources: {resources} | API Groups: {api_groups}</li>'
                    section_html += '''
                            </ul>
                        </div>
                    </div>
                    '''
                section_html += '</div></div>'
            section_html += '</div></div>'
        
        # RoleBindings
        rolebindings = cluster_rbac.get('rolebindings', [])
        if rolebindings:
            section_html += f'''
            <div class="rbac-resource-type">
                <h4>RoleBindings ({len(rolebindings)})</h4>
                <div class="rbac-resource-list">
            '''
            for rb in rolebindings[:50]:
                name = rb.get('metadata', {}).get('name', rb.get('name', 'Unknown'))
                namespace = rb.get('metadata', {}).get('namespace', rb.get('namespace', 'default'))
                role_ref = rb.get('roleRef', {})
                role_name = role_ref.get('name', 'Unknown') if isinstance(role_ref, dict) else role_ref
                subjects = rb.get('subjects', []) or []
                section_html += f'''
                <div class="rbac-resource-card">
                    <div class="rbac-resource-header">
                        <strong>{name}</strong> (namespace: <code>{namespace}</code>) → <code>{role_name}</code>
                    </div>
                    <div class="rbac-resource-body">
                        <strong>Subjects ({len(subjects)}):</strong>
                        <ul>
                '''
                for subj in subjects:
                    if isinstance(subj, dict):
                        kind = subj.get('kind', 'Unknown')
                        subj_name = subj.get('name', 'Unknown')
                        section_html += f'<li>{kind}: {subj_name}</li>'
                    else:
                        section_html += f'<li>{subj}</li>'
                section_html += '''
                        </ul>
                    </div>
                </div>
                '''
            if len(rolebindings) > 50:
                section_html += f'''
                <div class="expandable-section">
                    <button class="expand-btn" onclick="toggleExpand(this, 'rolebindings-{cluster_name}')">
                        Show {len(rolebindings) - 50} more RoleBindings
                    </button>
                    <div id="rolebindings-{cluster_name}" class="expandable-content" style="display: none;">
                '''
                for rb in rolebindings[50:]:
                    name = rb.get('metadata', {}).get('name', rb.get('name', 'Unknown'))
                    namespace = rb.get('metadata', {}).get('namespace', rb.get('namespace', 'default'))
                    role_ref = rb.get('roleRef', {})
                    role_name = role_ref.get('name', 'Unknown') if isinstance(role_ref, dict) else role_ref
                    subjects = rb.get('subjects', []) or []
                    section_html += f'''
                    <div class="rbac-resource-card">
                        <div class="rbac-resource-header">
                            <strong>{name}</strong> (namespace: <code>{namespace}</code>) → <code>{role_name}</code>
                        </div>
                        <div class="rbac-resource-body">
                            <strong>Subjects ({len(subjects)}):</strong>
                            <ul>
                    '''
                    for subj in subjects:
                        if isinstance(subj, dict):
                            kind = subj.get('kind', 'Unknown')
                            subj_name = subj.get('name', 'Unknown')
                            section_html += f'<li>{kind}: {subj_name}</li>'
                        else:
                            section_html += f'<li>{subj}</li>'
                    section_html += '''
                            </ul>
                        </div>
                    </div>
                    '''
                section_html += '</div></div>'
            section_html += '</div></div>'
        
        # ServiceAccounts
        serviceaccounts = cluster_rbac.get('serviceaccounts', [])
        if serviceaccounts:
            section_html += f'''
            <div class="rbac-resource-type">
                <h4>ServiceAccounts ({len(serviceaccounts)})</h4>
                <div class="rbac-resource-list">
            '''
            for sa in serviceaccounts[:50]:
                name = sa.get('metadata', {}).get('name', sa.get('name', 'Unknown'))
                namespace = sa.get('metadata', {}).get('namespace', sa.get('namespace', 'default'))
                section_html += f'''
                <div class="rbac-resource-card">
                    <div class="rbac-resource-header">
                        <strong>{name}</strong> (namespace: <code>{namespace}</code>)
                    </div>
                </div>
                '''
            if len(serviceaccounts) > 50:
                section_html += f'''
                <div class="expandable-section">
                    <button class="expand-btn" onclick="toggleExpand(this, 'serviceaccounts-{cluster_name}')">
                        Show {len(serviceaccounts) - 50} more ServiceAccounts
                    </button>
                    <div id="serviceaccounts-{cluster_name}" class="expandable-content" style="display: none;">
                '''
                for sa in serviceaccounts[50:]:
                    name = sa.get('metadata', {}).get('name', sa.get('name', 'Unknown'))
                    namespace = sa.get('metadata', {}).get('namespace', sa.get('namespace', 'default'))
                    section_html += f'''
                    <div class="rbac-resource-card">
                        <div class="rbac-resource-header">
                            <strong>{name}</strong> (namespace: <code>{namespace}</code>)
                        </div>
                    </div>
                    '''
                section_html += '</div></div>'
            section_html += '</div></div>'
        
        section_html += '</div>'
    
    return section_html


def generate_inline_cluster_report(cluster_name: str, comparison: Dict, cluster_stats: Dict) -> str:
    """Generate inline cluster report HTML without truncation.
    
    Based on generate_html_report.py logic but shows ALL data without limits.
    """
    summary = comparison.get('summary', {})
    new_policies = comparison.get('new_policies', [])
    update_policies = comparison.get('existing_to_update', [])
    action_diff = comparison.get('action_diff', {})
    existing_only = comparison.get('existing_only', [])
    
    # Generate new policies section - NO TRUNCATION
    new_policies_html = ''
    if not new_policies:
        new_policies_html = '''
        <div class="section">
            <div class="section-header">
                <h2>New Policies to Create</h2>
                <span class="badge badge-success">0</span>
            </div>
            <div class="section-content empty-state">
                No new policies needed - all K8s groups are already covered.
            </div>
        </div>
        '''
    else:
        policies_cards = ''
        for policy_info in new_policies:  # NO LIMIT - show ALL
            actions = policy_info.get('actions', [])
            # Show ALL actions - NO TRUNCATION
            actions_display = ''.join([f'<span class="action-tag add">{a}</span>' for a in actions])
            
            policies_cards += f'''
            <div class="policy-card">
                <div class="policy-header">
                    <span>{policy_info['name']}</span>
                    <span class="badge badge-success">NEW</span>
                </div>
                <div class="policy-body">
                    <div class="action-list">{actions_display}</div>
                </div>
            </div>
            '''
        
        new_policies_html = f'''
        <div class="section">
            <div class="section-header">
                <h2>New Policies to Create</h2>
                <span class="badge badge-success">{len(new_policies)}</span>
            </div>
            <div class="section-content">
                {policies_cards}
            </div>
        </div>
        '''
    
    # Generate update policies section - NO TRUNCATION
    update_policies_html = ''
    if not update_policies:
        update_policies_html = '''
        <div class="section">
            <div class="section-header">
                <h2>Policies Needing Updates</h2>
                <span class="badge badge-warning">0</span>
            </div>
            <div class="section-content empty-state">
                No existing policies need updates.
            </div>
        </div>
        '''
    else:
        policies_cards = ''
        for policy_info in update_policies:  # NO LIMIT - show ALL
            add_actions = policy_info.get('actions_to_add', [])
            remove_actions = policy_info.get('actions_to_remove', [])
            
            # Show ALL actions - NO TRUNCATION
            add_display = ''.join([f'<span class="action-tag add">+ {a}</span>' for a in add_actions])
            remove_display = ''.join([f'<span class="action-tag remove">- {a}</span>' for a in remove_actions])
            
            policies_cards += f'''
            <div class="policy-card">
                <div class="policy-header">
                    <span>{policy_info['name']}</span>
                    <span class="badge badge-warning">UPDATE</span>
                </div>
                <div class="policy-body">
                    {"<div class='diff-section'><h4>Actions to Add:</h4><div class='action-list'>" + add_display + "</div></div>" if add_actions else ""}
                    {"<div class='diff-section'><h4>Actions to Remove:</h4><div class='action-list'>" + remove_display + "</div></div>" if remove_actions else ""}
                </div>
            </div>
            '''
        
        update_policies_html = f'''
        <div class="section">
            <div class="section-header">
                <h2>Policies Needing Updates</h2>
                <span class="badge badge-warning">{len(update_policies)}</span>
            </div>
            <div class="section-content">
                {policies_cards}
            </div>
        </div>
        '''
    
    # Generate action diff section - NO TRUNCATION
    in_k8s_not_komodor = action_diff.get('in_k8s_not_komodor', [])
    in_komodor_not_k8s = action_diff.get('in_komodor_not_k8s', [])
    
    # Show ALL actions - NO TRUNCATION
    k8s_only_display = ''.join([f'<span class="action-tag add">{a}</span>' for a in in_k8s_not_komodor])
    komodor_only_display = ''.join([f'<span class="action-tag remove">{a}</span>' for a in in_komodor_not_k8s])
    
    action_diff_html = f'''
    <div class="section">
        <div class="section-header">
            <h2>Action Coverage Differences</h2>
        </div>
        <div class="section-content">
            <div class="diff-section">
                <h4 class="collapsible">Actions in K8s RBAC, not in Komodor ({len(in_k8s_not_komodor)})</h4>
                <div class="collapse-content">
                    <div class="action-list" style="margin-top: 0.5rem;">{k8s_only_display if k8s_only_display else '<span class="empty-state">None</span>'}</div>
                </div>
            </div>
            <div class="diff-section" style="margin-top: 1.5rem;">
                <h4 class="collapsible">Actions in Komodor, not in K8s RBAC ({len(in_komodor_not_k8s)})</h4>
                <div class="collapse-content">
                    <div class="action-list" style="margin-top: 0.5rem;">{komodor_only_display if komodor_only_display else '<span class="empty-state">None</span>'}</div>
                </div>
            </div>
        </div>
    </div>
    '''
    
    # Generate existing only section - NO TRUNCATION
    existing_only_html = ''
    if existing_only:
        policies_cards = ''
        for policy_info in existing_only:  # NO LIMIT - show ALL
            policies_cards += f'''
            <div class="policy-card">
                <div class="policy-header">
                    <span>{policy_info['name']}</span>
                    <span class="badge badge-primary">KOMODOR ONLY</span>
                </div>
            </div>
            '''
        
        existing_only_html = f'''
        <div class="section">
            <div class="section-header">
                <h2>Komodor-Only Policies (Not from K8s)</h2>
                <span class="badge badge-primary">{len(existing_only)}</span>
            </div>
            <div class="section-content">
                <p style="color: var(--gray-600); margin-bottom: 1rem;">
                    These policies exist in Komodor but don't correspond to K8s RBAC. 
                    This may be intentional (Komodor-specific policies).
                </p>
                {policies_cards}
            </div>
        </div>
        '''
    
    # Generate recommendations
    recommendations = []
    if len(new_policies) > 0:
        recommendations.append(f"<li><strong>Create {len(new_policies)} new policies</strong> to match K8s RBAC groups. Use the generated policy files or the apply script.</li>")
    if len(update_policies) > 0:
        recommendations.append(f"<li><strong>Review and update {len(update_policies)} existing policies</strong> - their actions differ from K8s RBAC.</li>")
    if len(existing_only) > 0:
        recommendations.append(f"<li><strong>Review {len(existing_only)} Komodor-only policies</strong> - decide if they should remain or be removed.</li>")
    if not recommendations:
        recommendations.append("<li><strong>No changes needed!</strong> Komodor policies match K8s RBAC.</li>")
    recommendations.append("<li>Run <code>python apply_komodor_policies.py</code> to apply the changes via API.</li>")
    
    recommendations_html = '\n'.join(recommendations)
    
    # Summary cards
    summary_html = f'''
    <div class="summary-grid">
        <div class="summary-card primary">
            <div class="label">K8s Policies Generated</div>
            <div class="value">{summary.get('generated_policies_count', 0)}</div>
        </div>
        <div class="summary-card">
            <div class="label">Existing Komodor Policies</div>
            <div class="value">{summary.get('existing_policies_count', 0)}</div>
        </div>
        <div class="summary-card success">
            <div class="label">New to Create</div>
            <div class="value">{len(new_policies)}</div>
        </div>
        <div class="summary-card warning">
            <div class="label">Need Updates</div>
            <div class="value">{len(update_policies)}</div>
        </div>
    </div>
    '''
    
    # Combine all sections
    report_html = f'''
    <div class="inline-cluster-report" style="margin-top: 1rem; padding: 1rem; background: var(--gray-50); border-radius: 8px;">
        <h3 style="margin-top: 0; margin-bottom: 1rem; color: var(--primary);">{cluster_name}</h3>
        {summary_html}
        <div class="section">
            <div class="section-header">
                <h2>Recommendations</h2>
            </div>
            <div class="section-content recommendations">
                <ol>
                    {recommendations_html}
                </ol>
            </div>
        </div>
        {new_policies_html}
        {update_policies_html}
        {action_diff_html}
        {existing_only_html}
    </div>
    '''
    
    return report_html


def generate_html_content(summary_data: Dict, cluster_stats: List[Dict],
                         groups_data: Dict, mapping_data: Dict,
                         comparison_data: Dict,
                         raw_rbac_data: Dict,
                         group_clusters: Dict[str, List[str]],
                         action_gaps: Dict, timestamp: str) -> str:
    """Generate the HTML content."""
    
    account_display = str(summary_data.get('account_name', 'Account')).replace('-', ' ').replace('_', ' ').title()
    
    # Extract key metrics
    unique_groups = len(summary_data['unique_groups'])
    unique_policies = len(summary_data['unique_policies_needed'])
    
    # Build cluster table rows with expand buttons
    cluster_rows = ""
    cluster_expandable_sections = ""
    for stat in sorted(cluster_stats, key=lambda x: x['name']):
        cluster_name_safe = stat['name'].replace('.', '-').replace('_', '-')
        cluster_comparison = comparison_data.get(stat['name'], {})
        
        # Generate inline report HTML if comparison data exists
        inline_report_html = ""
        if cluster_comparison:
            inline_report_html = generate_inline_cluster_report(stat['name'], cluster_comparison, stat)
        
        cluster_rows += f'''
        <tr>
            <td><code>{stat['name']}</code></td>
            <td class="center">{stat['region']}</td>
            <td class="center">{stat['cluster_roles']}</td>
            <td class="center">{stat['cluster_role_bindings']}</td>
            <td class="center">{stat['roles']}</td>
            <td class="center">{stat['role_bindings']}</td>
            <td class="center highlight">{stat['groups']}</td>
            <td class="center highlight">{stat['policies']}</td>
            <td class="center">
                <button class="expand-cluster-btn" onclick="toggleClusterReport('{cluster_name_safe}')" id="btn-{cluster_name_safe}">
                    Expand
                </button>
            </td>
        </tr>
        '''
        
        # Add expandable section below table
        cluster_expandable_sections += f'''
        <tr id="expandable-{cluster_name_safe}" class="cluster-expandable-row" style="display: none;">
            <td colspan="9" style="padding: 0;">
                {inline_report_html if inline_report_html else '<p style="padding: 1rem; color: var(--gray-600);">Comparison data not available for this cluster.</p>'}
            </td>
        </tr>
        '''
    
    # Build groups deep dive - AGGREGATE FROM ALL CLUSTERS
    groups_section = ""
    for group_name_normalized in sorted(summary_data['unique_groups']):
        # Find original group name format (may have colon)
        group_name_original = denormalize_group_name(group_name_normalized, summary_data['unique_groups'])
        
        # Aggregate data from ALL clusters (not just first match)
        all_komodor_actions = set()
        all_source_roles = set()
        all_namespaces = set()
        all_k8s_rules = []
        all_clusters_with_group = []
        is_cluster_wide = False
        
        # Collect from mapping_data (Komodor actions)
        for cluster_name, mapping_list in mapping_data.items():
            for mapping in mapping_list:
                mapping_subject = mapping.get('subject_name', '')
                # Match normalized names
                if normalize_group_name(mapping_subject) == normalize_group_name(group_name_original):
                    all_komodor_actions.update(mapping.get('komodor_actions', []))
                    all_source_roles.update(mapping.get('source_roles', []))
                    all_namespaces.update(mapping.get('namespaces', []))
                    if mapping.get('cluster_scope'):
                        is_cluster_wide = True
                    if cluster_name not in all_clusters_with_group:
                        all_clusters_with_group.append(cluster_name)
        
        # Collect from groups_data (K8s rules)
        for cluster_name, cluster_groups in groups_data.items():
            # Try both normalized and original name
            group_key = None
            if group_name_original in cluster_groups:
                group_key = group_name_original
            else:
                # Try normalized match
                for key in cluster_groups.keys():
                    if normalize_group_name(key) == normalize_group_name(group_name_original):
                        group_key = key
                        break
            
            if group_key and group_key in cluster_groups:
                group_data = cluster_groups[group_key]
                all_k8s_rules.extend(group_data.get('rules', []))
                if cluster_name not in all_clusters_with_group:
                    all_clusters_with_group.append(cluster_name)
        
        # Get clusters from group_clusters mapping (fallback)
        clusters_from_mapping = group_clusters.get(group_name_normalized, [])
        for cluster in clusters_from_mapping:
            if cluster not in all_clusters_with_group:
                all_clusters_with_group.append(cluster)
        
        # Fallback: If no Komodor actions found in mapping_data, try to get them from generated policies
        if not all_komodor_actions:
            policy_name = f"k8s-sync-group-{group_name_normalized}"
            for comp in comparison_data.values():
                for new_policy in comp.get('new_policies', []):
                    if new_policy.get('name') == policy_name:
                        policy_actions = new_policy.get('actions', [])
                        if policy_actions:
                            all_komodor_actions.update(policy_actions)
                            break
                if all_komodor_actions:
                    break
        
        # Build K8s permissions summary - ALL verbs and resources
        verbs_set = set()
        resources_set = set()
        api_groups_set = set()
        for rule in all_k8s_rules:
            verbs_set.update(rule.get('verbs', []))
            resources_set.update(rule.get('resources', []))
            api_groups_set.update(rule.get('api_groups', []))
        
        # Show ALL data - no truncation
        verbs_str = ', '.join(sorted(verbs_set)) if verbs_set else 'N/A'
        resources_str = ', '.join(sorted(resources_set)) if resources_set else 'N/A'
        api_groups_str = ', '.join(sorted(api_groups_set)) if api_groups_set else 'N/A'
        namespaces_str = ', '.join(sorted(all_namespaces)) if all_namespaces else ('* (cluster-wide)' if is_cluster_wide else 'N/A')
        
        groups_section += f'''
        <div class="group-card">
            <div class="group-header">
                <h3>{group_name_original}</h3>
                <span class="badge badge-primary">{len(all_clusters_with_group)} clusters</span>
            </div>
            <div class="group-body">
                <div class="group-details">
                    <div class="detail-row">
                        <strong>Source K8s Roles:</strong> {', '.join(sorted(all_source_roles)) if all_source_roles else 'N/A'}
                    </div>
                    <div class="detail-row">
                        <strong>K8s API Groups:</strong> {api_groups_str}
                    </div>
                    <div class="detail-row">
                        <strong>K8s Verbs:</strong> {verbs_str}
                    </div>
                    <div class="detail-row">
                        <strong>K8s Resources:</strong> {resources_str}
                    </div>
                    <div class="detail-row">
                        <strong>Scope:</strong> {"cluster-wide" if is_cluster_wide else "namespace-scoped"}
                        <br><strong>Namespaces:</strong> {namespaces_str}
                    </div>
                    <div class="detail-row">
                        <strong>Komodor Actions ({len(all_komodor_actions)}):</strong>
                        <div class="action-list">
                            {''.join([f'<span class="action-tag">{a}</span>' for a in sorted(all_komodor_actions)])}
                        </div>
                    </div>
                    <div class="detail-row">
                        <strong>Clusters ({len(all_clusters_with_group)}):</strong> {', '.join(sorted(all_clusters_with_group))}
                    </div>
                </div>
            </div>
        </div>
        '''
    
    # Build policies section - NO TRUNCATION
    policies_section = ""
    for policy_name in sorted(summary_data['unique_policies_needed']):
        group_name_normalized = policy_name.replace('k8s-sync-group-', '')
        
        # Find original group name format
        group_name_original = denormalize_group_name(group_name_normalized, summary_data['unique_groups'])
        
        # Find policy details from comparison data
        policy_details = None
        for comp in comparison_data.values():
            for new_policy in comp.get('new_policies', []):
                if new_policy['name'] == policy_name:
                    policy_details = new_policy
                    break
            if policy_details:
                break
        
        if policy_details:
            actions = policy_details.get('actions', [])
            statements = policy_details.get('policy', {}).get('statements', [])
            
            # Get source roles from mapping data - aggregate from ALL clusters
            policy_source_roles = set()
            for cluster_name, mapping_list in mapping_data.items():
                for mapping in mapping_list:
                    mapping_subject = mapping.get('subject_name', '')
                    if normalize_group_name(mapping_subject) == normalize_group_name(group_name_original):
                        policy_source_roles.update(mapping.get('source_roles', []))
            
            # Build full statements list
            statements_html = ""
            for i, stmt in enumerate(statements):
                stmt_actions = stmt.get('actions', [])
                stmt_resources = stmt.get('resources', [])
                cluster_scope = stmt_resources[0].get('cluster', '*') if stmt_resources else '*'
                namespace_scope = ', '.join(stmt_resources[0].get('namespaces', ['*'])) if stmt_resources else '*'
                statements_html += f'<li><strong>Statement {i+1}:</strong> {len(stmt_actions)} actions, cluster: {cluster_scope}, namespaces: {namespace_scope}</li>'
            
            policies_section += f'''
            <div class="policy-card">
                <div class="policy-header">
                    <h3>{policy_name}</h3>
                    <span class="badge badge-success">NEW</span>
                </div>
                <div class="policy-body">
                    <div class="detail-row">
                        <strong>Target Identity Group:</strong> {group_name_original}
                    </div>
                    <div class="detail-row">
                        <strong>Source K8s Roles:</strong> {', '.join(sorted(policy_source_roles)) if policy_source_roles else 'N/A'}
                    </div>
                    <div class="detail-row">
                        <strong>Actions ({len(actions)}):</strong>
                        <div class="action-list">
                            {''.join([f'<span class="action-tag">{a}</span>' for a in sorted(actions)])}
                        </div>
                    </div>
                    <div class="detail-row">
                        <strong>Statements ({len(statements)}):</strong>
                        <ul>
                            {statements_html}
                        </ul>
                    </div>
                </div>
            </div>
            '''
    
    # Build action gaps - NO TRUNCATION
    k8s_only_actions = ''.join([f'<span class="action-tag add">{a}</span>' for a in sorted(action_gaps['k8s_only'])])
    komodor_only_actions = ''.join([f'<span class="action-tag remove">{a}</span>' for a in sorted(action_gaps['komodor_only'])])
    
    # Generate RBAC resources section
    rbac_resources_section = generate_rbac_resources_section(raw_rbac_data, cluster_stats)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{account_display} RBAC Sync - Executive Report</title>
    <style>
        :root {{
            --primary: #2563eb;
            --primary-dark: #1d4ed8;
            --success: #16a34a;
            --warning: #ca8a04;
            --danger: #dc2626;
            --info: #0891b2;
            --gray-50: #f9fafb;
            --gray-100: #f3f4f6;
            --gray-200: #e5e7eb;
            --gray-300: #d1d5db;
            --gray-500: #6b7280;
            --gray-600: #4b5563;
            --gray-700: #374151;
            --gray-800: #1f2937;
            --gray-900: #111827;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--gray-50);
            color: var(--gray-800);
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        header {{
            background: linear-gradient(135deg, #7c3aed, #5b21b6);
            color: white;
            padding: 3rem 2rem;
            margin-bottom: 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        header h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            font-weight: 700;
        }}
        
        header .subtitle {{
            opacity: 0.9;
            font-size: 1.2rem;
            margin-bottom: 1rem;
        }}
        
        header .meta {{
            margin-top: 1rem;
            font-size: 0.9rem;
            opacity: 0.8;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .stat-card {{
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            text-align: center;
        }}
        
        .stat-card .value {{
            font-size: 2.5rem;
            font-weight: 700;
            margin-bottom: 0.25rem;
        }}
        
        .stat-card .label {{
            font-size: 0.85rem;
            color: var(--gray-600);
        }}
        
        .stat-card.primary .value {{ color: var(--primary); }}
        .stat-card.success .value {{ color: var(--success); }}
        .stat-card.warning .value {{ color: var(--warning); }}
        .stat-card.danger .value {{ color: var(--danger); }}
        .stat-card.info .value {{ color: var(--info); }}
        .stat-card.purple .value {{ color: #7c3aed; }}
        
        .section {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            margin-bottom: 2rem;
            overflow: hidden;
        }}
        
        .section-header {{
            background: var(--gray-100);
            padding: 1.5rem;
            border-bottom: 1px solid var(--gray-200);
        }}
        
        .section-header h2 {{
            font-size: 1.5rem;
            font-weight: 600;
            color: var(--gray-800);
        }}
        
        .section-content {{
            padding: 2rem;
        }}
        
        .highlight-box {{
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }}
        
        .highlight-box.info {{
            background: #eff6ff;
            border-left: 4px solid var(--primary);
        }}
        
        .highlight-box.success {{
            background: #f0fdf4;
            border-left: 4px solid var(--success);
        }}
        
        .highlight-box.warning {{
            background: #fffbeb;
            border-left: 4px solid var(--warning);
        }}
        
        .highlight-box.danger {{
            background: #fef2f2;
            border-left: 4px solid var(--danger);
        }}
        
        .highlight-box h3 {{
            margin-bottom: 0.75rem;
            font-size: 1.1rem;
            font-weight: 600;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
        }}
        
        th, td {{
            padding: 0.75rem 1rem;
            text-align: left;
            border-bottom: 1px solid var(--gray-200);
        }}
        
        th {{
            background: var(--gray-50);
            font-weight: 600;
            color: var(--gray-700);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }}
        
        tr:hover {{
            background: var(--gray-50);
        }}
        
        .center {{
            text-align: center;
        }}
        
        .highlight {{
            font-weight: 600;
            color: var(--primary);
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        .badge-success {{ background: #dcfce7; color: var(--success); }}
        .badge-warning {{ background: #fef3c7; color: var(--warning); }}
        .badge-danger {{ background: #fee2e2; color: var(--danger); }}
        .badge-info {{ background: #cffafe; color: var(--info); }}
        .badge-primary {{ background: #dbeafe; color: var(--primary); }}
        
        .group-card, .policy-card {{
            border: 1px solid var(--gray-200);
            border-radius: 8px;
            margin-bottom: 1rem;
            overflow: hidden;
        }}
        
        .group-header, .policy-header {{
            background: var(--gray-50);
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--gray-200);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .group-header h3, .policy-header h3 {{
            font-size: 1.1rem;
            font-weight: 600;
            margin: 0;
        }}
        
        .group-body, .policy-body {{
            padding: 1.5rem;
        }}
        
        .group-details {{
            display: grid;
            gap: 1rem;
        }}
        
        .detail-row {{
            margin-bottom: 1rem;
        }}
        
        .detail-row strong {{
            display: block;
            margin-bottom: 0.5rem;
            color: var(--gray-700);
        }}
        
        .action-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.5rem;
        }}
        
        .action-tag {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            background: var(--gray-100);
            border-radius: 4px;
            font-size: 0.8rem;
            font-family: monospace;
        }}
        
        .action-tag.add {{
            background: #dcfce7;
            color: var(--success);
        }}
        
        .action-tag.remove {{
            background: #fee2e2;
            color: var(--danger);
        }}
        
        .concept-box {{
            background: var(--gray-50);
            border-left: 4px solid var(--primary);
            padding: 1.5rem;
            margin-bottom: 1rem;
        }}
        
        .concept-box h4 {{
            color: var(--primary);
            margin-bottom: 0.5rem;
            font-size: 1rem;
        }}
        
        .concept-box .example {{
            background: white;
            padding: 0.75rem;
            border-radius: 4px;
            margin-top: 0.5rem;
            font-size: 0.9rem;
            font-family: monospace;
        }}
        
        .roadmap-phase {{
            border-left: 4px solid var(--primary);
            padding-left: 1.5rem;
            margin-bottom: 1.5rem;
        }}
        
        .roadmap-phase h4 {{
            color: var(--primary);
            margin-bottom: 0.5rem;
        }}
        
        .roadmap-phase ul {{
            margin-left: 1.5rem;
        }}
        
        .roadmap-phase li {{
            margin-bottom: 0.5rem;
        }}
        
        .collapsible {{
            cursor: pointer;
            user-select: none;
        }}
        
        .collapsible::after {{
            content: " [+]";
            font-size: 0.85em;
            color: var(--gray-600);
        }}
        
        .collapsible.expanded::after {{
            content: " [-]";
        }}
        
        .collapse-content {{
            display: none;
            margin-top: 1rem;
        }}
        
        .collapse-content.show {{
            display: block;
        }}
        
        footer {{
            text-align: center;
            padding: 2rem;
            color: var(--gray-500);
            font-size: 0.85rem;
        }}
        
        .cluster-rbac-section {{
            margin-bottom: 3rem;
            padding: 1.5rem;
            background: var(--gray-50);
            border-radius: 8px;
        }}
        
        .rbac-resource-type {{
            margin-bottom: 2rem;
        }}
        
        .rbac-resource-type h4 {{
            color: var(--primary);
            margin-bottom: 1rem;
            font-size: 1.1rem;
        }}
        
        .rbac-resource-list {{
            display: grid;
            gap: 1rem;
        }}
        
        .rbac-resource-card {{
            background: white;
            border: 1px solid var(--gray-200);
            border-radius: 6px;
            overflow: hidden;
        }}
        
        .rbac-resource-header {{
            background: var(--gray-100);
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--gray-200);
            font-size: 0.95rem;
        }}
        
        .rbac-resource-body {{
            padding: 1rem;
        }}
        
        .rbac-resource-body ul {{
            margin-top: 0.5rem;
            margin-left: 1.5rem;
        }}
        
        .rbac-resource-body li {{
            margin-bottom: 0.25rem;
            font-size: 0.9rem;
            font-family: monospace;
        }}
        
        .expandable-section {{
            margin: 1rem 0;
        }}
        
        .expand-btn {{
            background: var(--primary);
            color: white;
            border: none;
            padding: 0.75rem 1.5rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 600;
            transition: background 0.2s;
        }}
        
        .expand-btn:hover {{
            background: var(--primary-dark);
        }}
        
        .expandable-content {{
            margin-top: 1rem;
        }}
        
        /* Tab Styles */
        .tabs-container {{
            margin-bottom: 2rem;
        }}
        
        .tabs-nav {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            border-bottom: 2px solid var(--gray-200);
            margin-bottom: 2rem;
            background: white;
            padding: 0 1rem;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
        }}
        
        .tab-button {{
            background: transparent;
            border: none;
            padding: 0.75rem 1.25rem;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            color: var(--gray-600);
            border-bottom: 3px solid transparent;
            transition: all 0.2s;
            white-space: nowrap;
        }}
        
        .tab-button:hover {{
            color: var(--primary);
            background: var(--gray-50);
        }}
        
        .tab-button.active {{
            color: var(--primary);
            border-bottom-color: var(--primary);
            font-weight: 600;
        }}
        
        .tab-content {{
            display: none;
        }}
        
        .tab-content.active {{
            display: block;
        }}
        
        .expand-cluster-btn {{
            background: var(--primary);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 500;
            transition: background 0.2s;
        }}
        
        .expand-cluster-btn:hover {{
            background: var(--primary-dark);
        }}
        
        .expand-cluster-btn.expanded {{
            background: var(--success);
        }}
        
        .cluster-expandable-row {{
            background: var(--gray-50);
        }}
        
        .cluster-expandable-row td {{
            border-top: 2px solid var(--gray-300);
        }}
        
        .inline-cluster-report {{
            margin: 0;
            padding: 1.5rem;
        }}
        
        .inline-cluster-report .summary-grid {{
            margin-bottom: 1.5rem;
        }}
        
        .inline-cluster-report .section {{
            margin-bottom: 1.5rem;
        }}
        
        .summary-card {{
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .summary-card .label {{
            font-size: 0.85rem;
            color: var(--gray-600);
            margin-bottom: 0.25rem;
        }}
        
        .summary-card .value {{
            font-size: 2rem;
            font-weight: 700;
        }}
        
        .summary-card.success .value {{ color: var(--success); }}
        .summary-card.warning .value {{ color: var(--warning); }}
        .summary-card.danger .value {{ color: var(--danger); }}
        .summary-card.primary .value {{ color: var(--primary); }}
        
        .policy-card {{
            border: 1px solid var(--gray-200);
            border-radius: 6px;
            margin-bottom: 1rem;
            overflow: hidden;
        }}
        
        .policy-card:last-child {{
            margin-bottom: 0;
        }}
        
        .policy-header {{
            background: var(--gray-50);
            padding: 0.75rem 1rem;
            border-bottom: 1px solid var(--gray-200);
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .policy-body {{
            padding: 1rem;
        }}
        
        .diff-section {{
            margin-top: 1rem;
        }}
        
        .diff-section h4 {{
            font-size: 0.9rem;
            color: var(--gray-600);
            margin-bottom: 0.5rem;
        }}
        
        .recommendations {{
            background: #eff6ff;
            border-left: 4px solid var(--primary);
            padding: 1rem 1.5rem;
        }}
        
        .recommendations h3 {{
            color: var(--primary);
            margin-bottom: 0.75rem;
        }}
        
        .recommendations ol {{
            margin-left: 1.25rem;
        }}
        
        .recommendations li {{
            margin-bottom: 0.5rem;
        }}
        
        .empty-state {{
            text-align: center;
            padding: 2rem;
            color: var(--gray-600);
        }}
        
        @media print {{
            body {{
                background: white;
            }}
            
            .section {{
                break-inside: avoid;
            }}
            
            .tabs-nav {{
                display: none;
            }}
            
            .tab-content {{
                display: block !important;
            }}
            
            .cluster-expandable-row {{
                display: table-row !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>{account_display} RBAC Sync - Executive Report</h1>
            <p class="subtitle">Complete Kubernetes to Komodor Permission Analysis</p>
            <p class="meta">
                <strong>Account:</strong> {account_display} &nbsp;|&nbsp;
                <strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp;
                <strong>Analysis ID:</strong> {timestamp}
            </p>
        </header>
        
        <!-- Key Metrics -->
        <div class="stats-grid">
            <div class="stat-card purple">
                <div class="value">{summary_data['total_clusters']}</div>
                <div class="label">Total Clusters</div>
            </div>
            <div class="stat-card success">
                <div class="value">{summary_data['successful_clusters']}</div>
                <div class="label">Successfully Analyzed</div>
            </div>
            <div class="stat-card primary">
                <div class="value">{unique_groups}</div>
                <div class="label">Unique Identity Groups</div>
            </div>
            <div class="stat-card warning">
                <div class="value">{unique_policies}</div>
                <div class="label">Policies to Create</div>
            </div>
        </div>
        
        <!-- Tabs Navigation -->
        <div class="tabs-container">
            <div class="tabs-nav">
                <button class="tab-button active" onclick="switchTab('tab-1', this)">1. Executive Summary</button>
                <button class="tab-button" onclick="switchTab('tab-2', this)">2. Background</button>
                <button class="tab-button" onclick="switchTab('tab-3', this)">3. K8s RBAC Concepts</button>
                <button class="tab-button" onclick="switchTab('tab-4', this)">4. Current State</button>
                <button class="tab-button" onclick="switchTab('tab-5', this)">5. Per-Cluster Analysis</button>
                <button class="tab-button" onclick="switchTab('tab-6', this)">6. Identity Groups</button>
                <button class="tab-button" onclick="switchTab('tab-7', this)">7. Policies to Create</button>
                <button class="tab-button" onclick="switchTab('tab-8', this)">8. K8s RBAC Resources</button>
                <button class="tab-button" onclick="switchTab('tab-9', this)">9. Permission Gaps</button>
                <button class="tab-button" onclick="switchTab('tab-10', this)">10. Implementation</button>
                <button class="tab-button" onclick="switchTab('tab-11', this)">11. Remaining Gaps</button>
                <button class="tab-button" onclick="switchTab('tab-12', this)">12. Appendix</button>
            </div>
            
            <!-- Tab 1: Executive Summary -->
            <div id="tab-1" class="tab-content active">
        <div class="section">
            <div class="section-header">
                <h2>Executive Summary</h2>
            </div>
            <div class="section-content">
                <div class="highlight-box info">
                    <h3>The Business Problem</h3>
                    <p>
                        {account_display} manages Kubernetes RBAC through their identity provider (IdP) integration, ensuring consistent access control 
                        across their {summary_data['total_clusters']} clusters. However, Komodor currently has no mapping between the IdP groups 
                        and Komodor policies, creating a "permission drift" risk where Komodor access may not match 
                        their actual K8s permissions.
                    </p>
                </div>
                
                <div class="highlight-box success">
                    <h3>Key Findings</h3>
                    <ul>
                        <li><strong>{summary_data['total_clusters']} clusters</strong> analyzed</li>
                        <li><strong>{unique_groups} unique identity groups</strong> discovered with K8s RBAC permissions</li>
                        <li><strong>{unique_policies} Komodor policies</strong> need to be created to match K8s RBAC</li>
                        <li>Existing Komodor policies are generic rather than group-specific (see Current State)</li>
                    </ul>
                </div>
                
                <div class="highlight-box warning">
                    <h3>Recommendation</h3>
                    <p>
                        Create {unique_policies} group-specific Komodor policies that mirror the existing K8s RBAC structure. 
                        This will ensure users have appropriate Komodor access matching their Kubernetes permissions, 
                        eliminating permission drift and maintaining consistency with their IAM-managed access model.
                    </p>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 2: Background -->
            <div id="tab-2" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Request Background</h2>
            </div>
            <div class="section-content">
                <p>
                    {account_display} requested a "Reverse RBAC Sync" solution to address their concern about permission drift. 
                    Instead of using Komodor as the source of truth for RBAC (which would require manual configuration), 
                    they want Komodor to automatically read and mirror their existing Kubernetes RBAC configuration.
                </p>
                
                <div class="highlight-box info">
                    <h3>Why "Reverse RBAC Sync"?</h3>
                    <p>
                        Traditional RBAC sync pushes Komodor policies to Kubernetes. This approach reverses it:
                    </p>
                    <ul>
                        <li><strong>Source of Truth:</strong> Kubernetes RBAC (managed via the IdP/IAM integration)</li>
                        <li><strong>Target:</strong> Komodor policies (automatically generated from K8s)</li>
                        <li><strong>Benefit:</strong> No manual configuration needed, always in sync with IAM</li>
                    </ul>
                </div>
                
                <div class="highlight-box success">
                    <h3>Goal</h3>
                    <p>
                        Automatically align Komodor user permissions with their Kubernetes RBAC permissions, 
                        ensuring that when users log into Komodor via SAML, they receive access that matches 
                        their existing K8s permissions without any manual policy configuration.
                    </p>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 3: K8s RBAC Concepts -->
            <div id="tab-3" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Understanding Kubernetes RBAC</h2>
            </div>
            <div class="section-content">
                <p style="margin-bottom: 1.5rem;">
                    Kubernetes RBAC uses five key resource types to define and assign permissions. 
                    Here's how they work, with illustrative examples:
                </p>
                
                <div class="concept-box">
                    <h4>ClusterRole - Permission Template</h4>
                    <p>
                        Defines <strong>WHAT</strong> permissions exist. A ClusterRole specifies verbs (actions like get, list, watch, create, update, delete) 
                        and resources (like pods, deployments, secrets) that can be accessed.
                    </p>
                    <div class="example">
                        Example: "platform-readonly" ClusterRole<br>
                        - Verbs: get, list, watch (read-only)<br>
                        - Resources: * (all resources)<br>
                        - Result: Read-only access to everything in the cluster
                    </div>
                </div>
                
                <div class="concept-box">
                    <h4>ClusterRoleBinding - Links Roles to Groups</h4>
                    <p>
                        Defines <strong>WHO</strong> has cluster-wide permissions. A ClusterRoleBinding connects a ClusterRole 
                        to subjects (users, groups, or service accounts).
                    </p>
                    <div class="example">
                        Example: ClusterRoleBinding "platform-team-binding"<br>
                        - ClusterRole: "platform-readonly"<br>
                        - Subject: Group "platform-team"<br>
                        - Result: All members of the "platform-team" identity group get read-only access cluster-wide
                    </div>
                </div>
                
                <div class="concept-box">
                    <h4>Role - Namespace-Scoped Permission Template</h4>
                    <p>
                        Same as ClusterRole but limited to a specific namespace. Defines permissions that only apply 
                        within that namespace.
                    </p>
                    <div class="example">
                        Example: Role "app-team-editor" in namespace "payments"<br>
                        - Verbs: get, list, watch, create, update<br>
                        - Resources: pods, deployments, services<br>
                        - Result: Read/write access to pods, deployments, and services, but only in the "payments" namespace
                    </div>
                </div>
                
                <div class="concept-box">
                    <h4>RoleBinding - Links Roles to Groups in Namespace</h4>
                    <p>
                        Connects a Role to subjects within a specific namespace. Users/groups get the Role's permissions 
                        only in that namespace.
                    </p>
                    <div class="example">
                        Example: RoleBinding in namespace "payments"<br>
                        - Role: "app-team-editor"<br>
                        - Subject: Group "app-team"<br>
                        - Result: Members of "app-team" group can manage resources in the "payments" namespace only
                    </div>
                </div>
                
                <div class="concept-box">
                    <h4>ServiceAccount - Machine Identities</h4>
                    <p>
                        Service accounts are used by pods and automation tools, not human users. They're not relevant 
                        for mapping identity groups to Komodor policies (which is for human users).
                    </p>
                </div>
                
                <div class="highlight-box info" style="margin-top: 1.5rem;">
                    <h3>How We Analyzed the RBAC</h3>
                    <p>
                        We scanned all ClusterRoleBindings and RoleBindings to find which <strong>identity groups</strong> are bound to which roles. 
                        Then we examined the ClusterRoles and Roles to understand what permissions those groups have. 
                        Finally, we mapped those K8s permissions to Komodor actions to generate matching policies.
                    </p>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 4: Current State -->
            <div id="tab-4" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Current State</h2>
            </div>
            <div class="section-content">
                <h3 style="margin-bottom: 1rem;">Kubernetes RBAC Infrastructure</h3>
                <ul style="margin-bottom: 1.5rem;">
                    <li><strong>{summary_data['total_clusters']} clusters</strong> analyzed across the account</li>
                    <li><strong>{unique_groups} unique identity groups</strong> with K8s access permissions</li>
                    <li>RBAC managed via <strong>IdP/IAM integration</strong> - groups are automatically synced</li>
                    <li>Mix of <strong>cluster-wide</strong> (ClusterRole) and <strong>namespace-scoped</strong> (Role) permissions</li>
                </ul>
                
                <h3 style="margin-bottom: 1rem;">Komodor Current Configuration</h3>
                <p style="margin-bottom: 1rem;">The account currently has only <strong>generic, non-group-specific policies</strong> in Komodor, typically the defaults:</p>
                <ul style="margin-bottom: 1.5rem;">
                    <li><code>default-allow-all</code> - Full admin access (all actions)</li>
                    <li><code>default-read-only</code> - View-only access (view:all)</li>
                    <li><code>default-basic-actions</code> - Basic operations (restart, scale, exec)</li>
                    <li><code>default-allow-get-kubeconfig</code> - Kubeconfig download only</li>
                </ul>
                
                <div class="highlight-box danger">
                    <h3>The Gap</h3>
                    <p>
                        <strong>No mapping exists between identity groups and Komodor policies.</strong> This means:
                    </p>
                    <ul>
                        <li>Users either get too much access (if assigned to <code>default-allow-all</code>)</li>
                        <li>Or too little access (if assigned to restrictive defaults)</li>
                        <li>Komodor permissions don't match their actual K8s RBAC permissions</li>
                        <li>Permission drift occurs when K8s RBAC changes but Komodor doesn't</li>
                    </ul>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 5: Per-Cluster Analysis -->
            <div id="tab-5" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Per-Cluster Analysis</h2>
            </div>
            <div class="section-content" style="overflow-x: auto;">
                <p style="margin-bottom: 1rem;">
                    Complete breakdown of all {summary_data['total_clusters']} clusters analyzed:
                </p>
                <table>
                    <thead>
                        <tr>
                            <th>Cluster Name</th>
                            <th class="center">Region</th>
                            <th class="center">ClusterRoles</th>
                            <th class="center">ClusterRoleBindings</th>
                            <th class="center">Roles</th>
                            <th class="center">RoleBindings</th>
                            <th class="center">Groups Found</th>
                            <th class="center">Policies Needed</th>
                            <th class="center">Report</th>
                        </tr>
                    </thead>
                    <tbody>
                        {cluster_rows}
                        {cluster_expandable_sections}
                    </tbody>
                </table>
            </div>
        </div>
            </div>
            
            <!-- Tab 6: Identity Groups Deep Dive -->
            <div id="tab-6" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Identity Groups Deep Dive</h2>
            </div>
            <div class="section-content">
                <p style="margin-bottom: 1.5rem;">
                    Detailed breakdown of all {unique_groups} identity groups, their K8s permissions, and mapped Komodor actions:
                </p>
                {groups_section}
            </div>
        </div>
            </div>
            
            <!-- Tab 7: Policies to Create -->
            <div id="tab-7" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Policies to Create</h2>
            </div>
            <div class="section-content">
                <p style="margin-bottom: 1.5rem;">
                    Complete list of {unique_policies} Komodor policies that need to be created:
                </p>
                {policies_section}
            </div>
        </div>
            </div>
            
            <!-- Tab 8: Complete K8s RBAC Resources -->
            <div id="tab-8" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Complete K8s RBAC Resources</h2>
            </div>
            <div class="section-content">
                <p style="margin-bottom: 1.5rem;">
                    Complete breakdown of all ClusterRoles, ClusterRoleBindings, Roles, RoleBindings, and ServiceAccounts across all clusters:
                </p>
                {rbac_resources_section}
            </div>
        </div>
            </div>
            
            <!-- Tab 9: Permission Gaps -->
            <div id="tab-9" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Permission Gaps Analysis</h2>
            </div>
            <div class="section-content">
                <h3 style="margin-bottom: 1rem;">Actions in K8s RBAC but NOT in Komodor ({len(action_gaps['k8s_only'])})</h3>
                <p style="margin-bottom: 0.75rem; color: var(--gray-600);">
                    These K8s permissions exist but haven't been enabled in Komodor yet:
                </p>
                <div class="action-list" style="margin-bottom: 2rem;">
                    {k8s_only_actions}
                </div>
                
                <h3 style="margin-bottom: 1rem;">Actions in Komodor but NOT in K8s RBAC ({len(action_gaps['komodor_only'])})</h3>
                <p style="margin-bottom: 0.75rem; color: var(--gray-600);">
                    These Komodor-specific actions don't have direct K8s RBAC equivalents:
                </p>
                <div class="action-list" style="margin-bottom: 2rem;">
                    {komodor_only_actions}
                </div>
                
                <div class="highlight-box warning">
                    <h3>Decision Required</h3>
                    <p>
                        Komodor-specific actions (like <code>exec:pod</code>, <code>manage:users</code>, <code>manage:klaudia</code>, 
                        Helm actions) need to be manually added to policies based on business requirements. 
                        These don't exist in K8s RBAC, so the account owner needs to decide which groups should have these capabilities.
                    </p>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 10: Implementation Roadmap -->
            <div id="tab-10" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Implementation Roadmap</h2>
            </div>
            <div class="section-content">
                <div class="roadmap-phase">
                    <h4>Phase 1: Create {unique_policies} Komodor Policies (Immediate - 1-2 hours)</h4>
                    <ul>
                        <li>Import the {unique_policies} generated policy JSON files into Komodor</li>
                        <li>Options: Use Komodor API (<code>apply_komodor_policies.py</code>) or manual UI import</li>
                        <li>Each policy maps to one identity group with matching K8s permissions</li>
                    </ul>
                </div>
                
                <div class="roadmap-phase">
                    <h4>Phase 2: Create Roles and Configure IdP SAML Mapping (Same Day - 1 hour)</h4>
                    <ul>
                        <li><strong>Step 2a:</strong> Create {unique_groups} Komodor roles using <code>apply_komodor_policies.py --include-roles</code></li>
                        <li>Roles are already generated by <code>generate_komodor_policies.py</code> and included in <code>all_policies.json</code></li>
                        <li><strong>Step 2b:</strong> Configure the IdP (e.g., Okta) to pass the <code>komodorRoles</code> attribute in SAML assertions</li>
                        <li>In the IdP: Add SAML 2.0 attribute mapping with the generated role names (e.g., "k8s-sync-&lt;group-name&gt;")</li>
                        <li>When users log in via SSO, they automatically get assigned roles based on their group membership</li>
                        <li><strong>Note:</strong> Komodor does not have a UI for group-to-role mapping; this is done via IdP SAML attributes</li>
                    </ul>
                </div>
                
                <div class="roadmap-phase">
                    <h4>Phase 3: Add Komodor-Specific Actions (Decision Required - Timing TBD)</h4>
                    <ul>
                        <li>Identify which groups need <code>exec:pod</code> (shell into pods)</li>
                        <li>Identify which groups need Helm actions (install/uninstall charts)</li>
                        <li>Identify which groups need <code>manage:*</code> actions (admin capabilities)</li>
                        <li>Manually update policies to add these actions</li>
                    </ul>
                </div>
                
                <div class="roadmap-phase">
                    <h4>Phase 4: Validation (Next Day - 2-3 hours)</h4>
                    <ul>
                        <li>Test with sample users from each identity group</li>
                        <li>Verify Komodor permissions match K8s RBAC expectations</li>
                        <li>Adjust policies as needed based on feedback</li>
                        <li>Document any exceptions or special cases</li>
                    </ul>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 11: Remaining Gaps -->
            <div id="tab-11" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Remaining Gaps and Limitations</h2>
            </div>
            <div class="section-content">
                <div class="highlight-box warning">
                    <h3>No Automatic Sync Capability</h3>
                    <p>
                        Currently, this is a one-time analysis. If K8s RBAC changes (new groups, modified permissions), 
                        the pipeline must be re-run manually. A future product feature could provide continuous automatic sync.
                    </p>
                </div>
                
                <div class="highlight-box info">
                    <h3>Komodor-Specific Actions Require Manual Decision</h3>
                    <p>
                        Actions like <code>exec:pod</code>, <code>manage:klaudia</code>, Helm management, and user administration 
                        don't have K8s RBAC equivalents. These must be manually added to policies based on business requirements.
                    </p>
                </div>
                
                <div class="highlight-box info">
                    <h3>ServiceAccount Permissions Not Mapped</h3>
                    <p>
                        ServiceAccount bindings were analyzed but not included in policy generation, as they represent 
                        machine identities rather than human user access.
                    </p>
                </div>
                
                <div class="highlight-box info">
                    <h3>Custom Resources May Have Limited Support</h3>
                    <p>
                        Some Kubernetes Custom Resource Definitions (CRDs) may not have direct Komodor action equivalents. 
                        These are mapped to <code>view:custom-resource</code> or <code>edit:custom-resource</code> where possible.
                    </p>
                </div>
                
                <div class="highlight-box warning">
                    <h3>Pod Subresources Are Not Auto-Mapped</h3>
                    <p>
                        K8s grants exec, port-forward, log access, and scale via subresources (e.g., <code>pods/exec</code>, 
                        <code>deployments/scale</code>). The mapper matches base resources only, so actions like 
                        <code>exec:pod</code> and <code>forward:port</code> are never granted automatically and must be 
                        added to policies manually where appropriate.
                    </p>
                </div>
                
                <div class="highlight-box warning">
                    <h3>Rule Granularity Caveats</h3>
                    <p>
                        <code>resourceNames</code> restrictions in K8s rules are not carried over (the generated grant covers the 
                        whole resource type in scope), and wildcard rules (<code>resources: ["*"]</code>) map to the full set of 
                        Komodor view/edit/delete actions, including some platform-level view actions. Review generated policies 
                        before applying.
                    </p>
                </div>
            </div>
        </div>
            </div>
            
            <!-- Tab 12: Appendix -->
            <div id="tab-12" class="tab-content">
        <div class="section">
            <div class="section-header">
                <h2>Appendix</h2>
            </div>
            <div class="section-content">
                <h3 style="margin-bottom: 1rem;">Generated Files</h3>
                <ul style="margin-bottom: 1.5rem;">
                    <li><strong>Policy JSON Files:</strong> <code>generated_policies/&lt;account&gt;/{timestamp}_*/all_policies.json</code></li>
                    <li><strong>Per-Cluster Reports:</strong> <code>reports/&lt;account&gt;/comparison_{timestamp}_*/rbac_sync_report.html</code></li>
                    <li><strong>Full Account Summary:</strong> <code>reports/&lt;account&gt;/full_account_summary_{timestamp}.json</code></li>
                </ul>
                
                <h3 style="margin-bottom: 1rem;">Scripts Used</h3>
                <ul style="margin-bottom: 1.5rem;">
                    <li><code>sync_once.py</code> - Orchestrates export → analyze → map → generate → apply</li>
                    <li><code>analyze_k8s_rbac.py</code> - Parses and analyzes RBAC structure</li>
                    <li><code>map_to_komodor.py</code> - Maps K8s permissions to Komodor actions</li>
                    <li><code>generate_komodor_policies.py</code> - Generates Komodor policy JSON</li>
                    <li><code>compare_and_report.py</code> - Compares with existing Komodor config</li>
                    <li><code>apply_komodor_policies.py</code> - Applies policies via Komodor API</li>
                </ul>
                
                <h3 style="margin-bottom: 1rem;">K8s to Komodor Action Mapping</h3>
                <p>
                    K8s verbs map to Komodor actions as follows:
                </p>
                <ul>
                    <li><code>get, list, watch</code> → <code>view:*</code> actions</li>
                    <li><code>create, update, patch</code> → <code>edit:*</code> actions (plus restart/rollback/scale for workloads)</li>
                    <li><code>delete</code> → <code>delete:*</code> actions</li>
                    <li>Pod subresources (<code>pods/exec</code>, <code>pods/portforward</code>) are <strong>not</strong> auto-mapped — grant <code>exec:pod</code> / <code>forward:port</code> manually where needed</li>
                </ul>
            </div>
        </div>
            </div>
        </div>
        
        <footer>
            <p>
                Generated by Komodor RBAC Sync Pipeline | Komodor Solutions Engineering<br>
                Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Analysis ID: {timestamp}
            </p>
        </footer>
    </div>
    
    <script>
        // Tab switching function
        function switchTab(tabId, button) {{
            // Hide all tab contents
            document.querySelectorAll('.tab-content').forEach(tab => {{
                tab.classList.remove('active');
            }});
            
            // Remove active class from all buttons
            document.querySelectorAll('.tab-button').forEach(btn => {{
                btn.classList.remove('active');
            }});
            
            // Show selected tab
            document.getElementById(tabId).classList.add('active');
            
            // Add active class to clicked button
            if (button) {{
                button.classList.add('active');
            }}
        }}
        
        // Expand/collapse function
        function toggleExpand(btn, contentId) {{
            const content = document.getElementById(contentId);
            if (content.style.display === 'none') {{
                content.style.display = 'block';
                btn.textContent = btn.textContent.replace('Show', 'Hide');
            }} else {{
                content.style.display = 'none';
                btn.textContent = btn.textContent.replace('Hide', 'Show');
            }}
        }}
        
        // Toggle cluster report expand/collapse
        function toggleClusterReport(clusterNameSafe) {{
            const expandableRow = document.getElementById('expandable-' + clusterNameSafe);
            const button = document.getElementById('btn-' + clusterNameSafe);
            
            if (expandableRow.style.display === 'none' || expandableRow.style.display === '') {{
                expandableRow.style.display = 'table-row';
                button.textContent = 'Collapse';
                button.classList.add('expanded');
            }} else {{
                expandableRow.style.display = 'none';
                button.textContent = 'Expand';
                button.classList.remove('expanded');
            }}
        }}
        
        // Legacy collapsible support
        document.querySelectorAll('.collapsible').forEach(el => {{
            el.addEventListener('click', () => {{
                el.classList.toggle('expanded');
                const content = el.nextElementSibling;
                if (content && content.classList.contains('collapse-content')) {{
                    content.classList.toggle('show');
                }}
            }});
        }});
    </script>
</body>
</html>'''
    
    return html


def main():
    parser = argparse.ArgumentParser(
        description='Generate comprehensive executive HTML report for a customer account'
    )
    parser.add_argument(
        '--summary', '-s',
        type=Path,
        help='Full account summary JSON file (default: find latest)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output HTML file path'
    )
    parser.add_argument(
        '--account-name', '-a',
        default='account',
        help='Account name (used to locate default reports/data directories)'
    )
    parser.add_argument(
        '--reports-dir', '-r',
        type=Path,
        default=None,
        help='Reports directory (default: reports/<account-name>)'
    )
    parser.add_argument(
        '--data-dir', '-d',
        type=Path,
        default=None,
        help='Data directory containing raw RBAC JSON files (default: data/<account-name>)'
    )
    
    args = parser.parse_args()
    
    if args.reports_dir is None:
        args.reports_dir = Path(__file__).parent / 'reports' / args.account_name
    if args.data_dir is None:
        args.data_dir = Path(__file__).parent / 'data' / args.account_name
    
    # Find latest summary if not provided
    if not args.summary:
        summary_files = list(args.reports_dir.glob('full_account_summary_*.json'))
        if not summary_files:
            logger.error("No summary file found. Pass --summary explicitly (see README).")
            return
        
        args.summary = max(summary_files, key=lambda p: p.stat().st_mtime)
        logger.info(f"Using latest summary: {args.summary}")
    
    # Load summary data
    logger.info(f"Loading summary from: {args.summary}")
    summary_data = load_summary_data(args.summary)
    timestamp = summary_data['timestamp']
    
    # Load cluster data
    logger.info("Loading cluster groups data...")
    groups_data = load_cluster_groups_data(args.reports_dir, timestamp)
    
    logger.info("Loading cluster mapping data...")
    mapping_data = load_cluster_mapping_data(args.reports_dir, timestamp)
    
    logger.info("Loading comparison data...")
    comparison_data = load_comparison_data(args.reports_dir, timestamp)
    
    # Generate output path
    if args.output:
        output_path = args.output
    else:
        output_path = args.reports_dir / f'ACCOUNT_OWNER_REPORT_{timestamp}.html'
    
    # Generate report
    logger.info("Generating executive report...")
    generate_html_report(
        summary_data=summary_data,
        groups_data=groups_data,
        mapping_data=mapping_data,
        comparison_data=comparison_data,
        output_path=output_path,
        data_dir=args.data_dir if args.data_dir.exists() else None
    )
    
    print(f"\nExecutive report generated: {output_path}")
    print("Open in browser to view the comprehensive report.")


if __name__ == '__main__':
    main()
