#!/usr/bin/env python3
"""
Compare generated Komodor policies with current Komodor configuration.

This script queries the Komodor database to fetch existing policies and
compares them with the policies generated from K8s RBAC.

Note:
    This distribution compares against an empty baseline: all generated
    policies are reported as new. Review your existing Komodor policies in
    the UI or via the public API.

Usage:
    python compare_and_report.py --generated generated_policies/<account>/<timestamp>/all_policies.json
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def extract_actions_from_policy(policy: Dict) -> Set[str]:
    """Extract all actions from a Komodor policy."""
    actions = set()
    statements = policy.get('statements', [])
    
    if isinstance(statements, str):
        statements = json.loads(statements)
    
    for statement in statements:
        stmt_actions = statement.get('actions', [])
        if stmt_actions:
            actions.update(stmt_actions)
    
    return actions


def compare_policies(
    generated_policies: List[Dict],
    existing_policies: List[Dict]
) -> Dict:
    """
    Compare generated policies with existing Komodor policies.
    
    Returns:
        Comparison report dictionary
    """
    # Build lookup for existing policies
    existing_by_name = {p['name']: p for p in existing_policies}
    generated_by_name = {p['name']: p for p in generated_policies}
    
    # Collect all actions from each set
    generated_actions = set()
    for policy in generated_policies:
        generated_actions.update(extract_actions_from_policy(policy))
    
    existing_actions = set()
    for policy in existing_policies:
        existing_actions.update(extract_actions_from_policy(policy))
    
    # Find differences
    comparison = {
        'summary': {
            'generated_policies_count': len(generated_policies),
            'existing_policies_count': len(existing_policies),
            'generated_unique_actions': len(generated_actions),
            'existing_unique_actions': len(existing_actions),
            'common_actions': len(generated_actions.intersection(existing_actions)),
            'actions_in_generated_only': len(generated_actions - existing_actions),
            'actions_in_existing_only': len(existing_actions - generated_actions)
        },
        'new_policies': [],  # Policies to create
        'existing_to_update': [],  # Policies that might need updates
        'existing_only': [],  # Policies only in Komodor (not from K8s)
        'action_diff': {
            'in_k8s_not_komodor': sorted(list(generated_actions - existing_actions)),
            'in_komodor_not_k8s': sorted(list(existing_actions - generated_actions)),
            'common': sorted(list(generated_actions.intersection(existing_actions)))
        }
    }
    
    # Categorize policies
    for name, policy in generated_by_name.items():
        if name in existing_by_name:
            # Compare actions
            gen_actions = extract_actions_from_policy(policy)
            exist_actions = extract_actions_from_policy(existing_by_name[name])
            
            if gen_actions != exist_actions:
                comparison['existing_to_update'].append({
                    'name': name,
                    'generated_actions': sorted(list(gen_actions)),
                    'existing_actions': sorted(list(exist_actions)),
                    'actions_to_add': sorted(list(gen_actions - exist_actions)),
                    'actions_to_remove': sorted(list(exist_actions - gen_actions))
                })
        else:
            comparison['new_policies'].append({
                'name': name,
                'actions': sorted(list(extract_actions_from_policy(policy))),
                'policy': policy
            })
    
    for name, policy in existing_by_name.items():
        if name not in generated_by_name:
            comparison['existing_only'].append({
                'name': name,
                'actions': sorted(list(extract_actions_from_policy(policy)))
            })
    
    return comparison


def generate_diff_report(comparison: Dict, generated_data: Dict) -> str:
    """Generate a human-readable diff report."""
    lines = []
    lines.append("=" * 70)
    lines.append("KOMODOR RBAC COMPARISON REPORT")
    lines.append("=" * 70)
    lines.append(f"\nGenerated: {datetime.now().isoformat()}")
    
    # Summary
    lines.append("\n" + "-" * 70)
    lines.append("SUMMARY")
    lines.append("-" * 70)
    
    summary = comparison['summary']
    lines.append(f"\nPolicies:")
    lines.append(f"  Generated from K8s: {summary['generated_policies_count']}")
    lines.append(f"  Existing in Komodor: {summary['existing_policies_count']}")
    lines.append(f"  New to create: {len(comparison['new_policies'])}")
    lines.append(f"  Need update: {len(comparison['existing_to_update'])}")
    lines.append(f"  Komodor-only: {len(comparison['existing_only'])}")
    
    lines.append(f"\nActions:")
    lines.append(f"  Unique in generated: {summary['generated_unique_actions']}")
    lines.append(f"  Unique in existing: {summary['existing_unique_actions']}")
    lines.append(f"  Common: {summary['common_actions']}")
    lines.append(f"  In K8s, not Komodor: {summary['actions_in_generated_only']}")
    lines.append(f"  In Komodor, not K8s: {summary['actions_in_existing_only']}")
    
    # New policies to create
    if comparison['new_policies']:
        lines.append("\n" + "-" * 70)
        lines.append("NEW POLICIES TO CREATE")
        lines.append("-" * 70)
        
        for policy_info in comparison['new_policies'][:10]:
            lines.append(f"\n  {policy_info['name']}:")
            lines.append(f"    Actions ({len(policy_info['actions'])}):")
            for action in policy_info['actions'][:5]:
                lines.append(f"      - {action}")
            if len(policy_info['actions']) > 5:
                lines.append(f"      ... and {len(policy_info['actions']) - 5} more")
        
        if len(comparison['new_policies']) > 10:
            lines.append(f"\n  ... and {len(comparison['new_policies']) - 10} more policies")
    
    # Policies needing updates
    if comparison['existing_to_update']:
        lines.append("\n" + "-" * 70)
        lines.append("POLICIES NEEDING UPDATES")
        lines.append("-" * 70)
        
        for update_info in comparison['existing_to_update'][:5]:
            lines.append(f"\n  {update_info['name']}:")
            if update_info['actions_to_add']:
                lines.append(f"    + Actions to add ({len(update_info['actions_to_add'])}):")
                for action in update_info['actions_to_add'][:3]:
                    lines.append(f"        {action}")
            if update_info['actions_to_remove']:
                lines.append(f"    - Actions to remove ({len(update_info['actions_to_remove'])}):")
                for action in update_info['actions_to_remove'][:3]:
                    lines.append(f"        {action}")
    
    # Action differences
    lines.append("\n" + "-" * 70)
    lines.append("ACTION DIFFERENCES")
    lines.append("-" * 70)
    
    if comparison['action_diff']['in_k8s_not_komodor']:
        lines.append(f"\nActions in K8s RBAC but NOT in Komodor ({len(comparison['action_diff']['in_k8s_not_komodor'])}):")
        for action in comparison['action_diff']['in_k8s_not_komodor'][:10]:
            lines.append(f"  + {action}")
        if len(comparison['action_diff']['in_k8s_not_komodor']) > 10:
            lines.append(f"  ... and {len(comparison['action_diff']['in_k8s_not_komodor']) - 10} more")
    
    if comparison['action_diff']['in_komodor_not_k8s']:
        lines.append(f"\nActions in Komodor but NOT in K8s RBAC ({len(comparison['action_diff']['in_komodor_not_k8s'])}):")
        for action in comparison['action_diff']['in_komodor_not_k8s'][:10]:
            lines.append(f"  - {action}")
        if len(comparison['action_diff']['in_komodor_not_k8s']) > 10:
            lines.append(f"  ... and {len(comparison['action_diff']['in_komodor_not_k8s']) - 10} more")
    
    # Recommendations
    lines.append("\n" + "-" * 70)
    lines.append("RECOMMENDATIONS")
    lines.append("-" * 70)
    
    if comparison['new_policies']:
        lines.append(f"\n1. Create {len(comparison['new_policies'])} new policies to match K8s RBAC")
    
    if comparison['existing_to_update']:
        lines.append(f"2. Review and update {len(comparison['existing_to_update'])} existing policies")
    
    if comparison['existing_only']:
        lines.append(f"3. Review {len(comparison['existing_only'])} Komodor-only policies (may be intentional)")
    
    lines.append("\n" + "=" * 70)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='Compare generated policies with Komodor configuration'
    )
    parser.add_argument(
        '--generated', '-g',
        type=Path,
        required=True,
        help='Generated policies file (all_policies.json)'
    )
    parser.add_argument(
        '--account-name', '-a',
        required=True,
        help='Account name in Komodor'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output directory for comparison report'
    )
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip database query (use if DB is not accessible)'
    )
    
    args = parser.parse_args()
    
    # Load generated policies
    logger.info(f"Loading generated policies from: {args.generated}")
    with open(args.generated) as f:
        generated_data = json.load(f)
    
    generated_policies = generated_data.get('policies', [])
    logger.info(f"Loaded {len(generated_policies)} generated policies")
    
    # Fetch existing policies from Komodor
    existing_policies = []
    existing_roles = []
    existing_users = []
    
    if not args.skip_db:
        logger.info("This distribution compares against an empty baseline (no direct DB access); "
                    "all generated policies are reported as new. "
                    "Review existing policies in the Komodor UI or via the public API.")

    # Compare
    comparison = compare_policies(generated_policies, existing_policies)
    
    # Generate human-readable report
    report_text = generate_diff_report(comparison, generated_data)
    
    # Setup output directory
    if args.output:
        output_dir = args.output
    else:
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_dir = Path(__file__).parent / 'reports' / args.account_name / f'comparison_{timestamp}'
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save comparison JSON
    comparison_file = output_dir / 'comparison.json'
    with open(comparison_file, 'w') as f:
        json.dump(comparison, f, indent=2, default=str)
    logger.info(f"Saved comparison to: {comparison_file}")
    
    # Save human-readable report
    report_file = output_dir / 'comparison_report.txt'
    with open(report_file, 'w') as f:
        f.write(report_text)
    logger.info(f"Saved report to: {report_file}")
    
    # Save existing policies for reference
    if existing_policies:
        existing_file = output_dir / 'existing_policies.json'
        with open(existing_file, 'w') as f:
            json.dump(existing_policies, f, indent=2, default=str)
    
    # Save existing roles for reference
    if existing_roles:
        roles_file = output_dir / 'existing_roles.json'
        with open(roles_file, 'w') as f:
            json.dump(existing_roles, f, indent=2, default=str)
    
    # Print the report
    print(report_text)
    
    print(f"\nFull report saved to: {output_dir}")


if __name__ == '__main__':
    main()
