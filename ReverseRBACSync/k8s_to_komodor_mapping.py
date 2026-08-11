"""
Mapping constants from Kubernetes RBAC verbs and resources to Komodor actions.

This module provides the translation layer between K8s RBAC permissions
and Komodor's action-based permission system.

Reference: the Komodor RBAC actions catalog (Settings > Actions)
"""

from typing import Dict, List, Set, Tuple, Optional

# =============================================================================
# KOMODOR ACTION DEFINITIONS
# =============================================================================

# All available Komodor actions (from pkg/authorization/actions.go)
KOMODOR_ACTIONS = {
    # View actions (read-only)
    'view:all': 'View all kubernetes and komodor resources in the relevant scope',
    'view:pods': 'List pods',
    'view:deployments': 'List deployments',
    'view:statefulsets': 'List statefulsets',
    'view:daemonsets': 'List daemonsets',
    'view:replicasets': 'List replicasets',
    'view:jobs': 'List jobs',
    'view:cronjobs': 'List cronjobs',
    'view:services': 'List services',
    'view:ingresses': 'List ingresses',
    'view:configmaps': 'List configmaps',
    'view:secrets': 'List secrets',
    'view:persistentvolumeclaims': 'List PVCs',
    'view:persistentvolumes': 'List PVs',
    'view:storageclasses': 'List storage classes',
    'view:networkpolicies': 'List network policies',
    'view:horizontalpodautoscalers': 'List HPAs',
    'view:nodes': 'List nodes',
    'view:namespaces': 'List namespaces',
    'view:clusterroles': 'List cluster roles',
    'view:clusterrolesbinding': 'List cluster role bindings',
    'view:customresourcedefinitions': 'List CRDs',
    'view:rollouts': 'List Argo Rollouts',
    'view:autoscalers': 'Access autoscalers add-on page',
    'view:certmanager': 'Access cert manager add-on page',
    'view:externaldns': 'Access external DNS add-on page',
    'view:cost': 'Access cost optimization page',
    'view:gpu': 'Access GPU resources',
    'view:custom-resource': 'View custom resources',
    'view:cilium': 'View Cilium resources',
    'view:Keda': 'View KEDA resources',
    'view:Kyverno': 'View Kyverno resources',
    
    # Edit actions
    'edit:deployment': 'Edit deployment YAML',
    'edit:statefulset': 'Edit statefulset YAML',
    'edit:daemonset': 'Edit daemonset YAML',
    'edit:replicaset': 'Edit replicaset YAML',
    'edit:job': 'Edit job YAML',
    'edit:cronjob': 'Edit cronjob YAML',
    'edit:service': 'Edit service YAML',
    'edit:configmap': 'Edit configmap YAML',
    'edit:secret': 'Edit secret YAML',
    'edit:horizontalpodautoscaler': 'Edit HPA YAML',
    'edit:rollout': 'Edit Argo Rollout',
    'edit:custom-resource': 'Edit custom resources',
    'edit:cilium': 'Edit Cilium resources',
    'edit:Keda': 'Edit KEDA resources',
    'edit:Kyverno': 'Edit Kyverno resources',
    
    # Delete actions
    'delete:pod': 'Delete a pod',
    'delete:deployment': 'Delete a deployment',
    'delete:statefulset': 'Delete a statefulset',
    'delete:daemonset': 'Delete a daemonset',
    'delete:replicaset': 'Delete a replicaset',
    'delete:job': 'Delete a job',
    'delete:cronjob': 'Delete a cronjob',
    'delete:service': 'Delete a service',
    'delete:ingress': 'Delete an ingress',
    'delete:configmap': 'Delete a configmap',
    'delete:secret': 'Delete a secret',
    'delete:persistentvolumeclaim': 'Delete a PVC',
    'delete:persistentvolume': 'Delete a PV',
    'delete:storageclass': 'Delete a storage class',
    'delete:networkpolicy': 'Delete a network policy',
    'delete:namespace': 'Delete a namespace',
    'delete:rollout': 'Delete Argo Rollout',
    'delete:custom-resource': 'Delete custom resources',
    'delete:cilium': 'Delete Cilium resources',
    'delete:Keda': 'Delete KEDA resources',
    'delete:Kyverno': 'Delete Kyverno resources',
    
    # Special actions
    'restart:deployment': 'Restart a deployment',
    'restart:statefulset': 'Restart a statefulset',
    'restart:daemonset': 'Restart a daemonset',
    'restart:rollout': 'Restart Argo Rollout',
    'rollback:deployment': 'Rollback a deployment',
    'rollback:statefulset': 'Rollback a statefulset',
    'rollback:daemonset': 'Rollback a daemonset',
    'scale:deployment': 'Scale a deployment',
    'scale:statefulset': 'Scale a statefulset',
    'scale:rollout': 'Scale Argo Rollout',
    'run:cronjob': 'Run a cronjob',
    'rerun:job': 'Rerun a job',
    'exec:pod': 'Exec into a pod',
    'forward:port': 'Port forward to a pod',
    'get:deployment': 'Get deployment details',
    'get:statefulset': 'Get statefulset details',
    'get:daemonset': 'Get daemonset details',
    'get:kubeconfig': 'Get kubeconfig',
    
    # Node actions
    'cordon:node': 'Cordon a node',
    'uncordon:node': 'Uncordon a node',
    'drain:node': 'Drain a node',
    
    # Helm actions
    'read:helm-repo': 'Read helm repos',
    'update:helm-repo': 'Update helm repos',
    'add:helm-repo': 'Add helm repos',
    'remove:helm-repo': 'Remove helm repos',
    'manage:helm': 'Manage helm releases',
    'install:helm-chart': 'Install helm chart',
    'uninstall:helm-chart': 'Uninstall helm chart',
    'revert:helm-chart': 'Revert helm chart',
    
    # Komodor admin actions (unscoped)
    'manage:users': 'Manage users, roles, policies',
    'manage:account-access': 'Manage IP allowlist',
    'manage:monitors': 'Manage realtime monitors',
    'manage:integrations': 'Manage integrations',
    'manage:features': 'Enable/disable features',
    'manage:agents': 'Manage agents',
    'manage:workspaces': 'Manage workspaces',
    'manage:trackedkeys': 'Manage tracked keys',
    'manage:kubeconfig': 'Configure kubeconfig',
    'manage:reliability': 'Manage reliability settings',
    'manage:reliability-policies': 'Manage reliability policies',
    'manage:klaudia': 'Manage Klaudia settings',
    'manage:cost-policies': 'Manage cost policies',
    'manage:argoCD': 'Manage ArgoCD',
    'view:audit': 'View audit logs',
    'view:usage': 'View usage',
    'view:nodecount': 'View node count (deprecated)',
    'run:kubectl': 'Run kubectl commands',
    'impersonate:user': 'Impersonate user',
    'revert:source-control': 'Revert source control',
}

# =============================================================================
# ACTION SCOPE CATEGORIES
# =============================================================================

# Unscoped actions (account-level, not tied to clusters/namespaces)
UNSCOPED_ACTIONS = {
    'manage:kubeconfig',
    'manage:users',
    'manage:account-access',
    'manage:monitors',
    'manage:integrations',
    'view:usage',
    'manage:agents',
    'manage:features',
    'manage:klaudia',
    'manage:reliability',
    'manage:reliability-policies',
    'manage:workspaces',
    'view:nodecount',
    'view:audit',
    'manage:trackedkeys',
    'run:kubectl',
    'impersonate:user',
    'manage:cost-policies',
}

# Cluster-scoped actions (apply to entire cluster or tracked keys)
CLUSTER_SCOPED_ACTIONS = {
    'view:nodes',
    'view:namespaces',
    'view:persistentvolumes',
    'view:storageclasses',
    'view:clusterroles',
    'view:clusterrolesbinding',
    'view:customresourcedefinitions',
    'cordon:node',
    'uncordon:node',
    'drain:node',
    'delete:persistentvolume',
    'delete:storageclass',
    'get:kubeconfig',
    'view:cost',
    'view:autoscalers',
    'view:certmanager',
    'view:externaldns',
    'view:gpu',
}

# Namespace-scoped actions (can be restricted to specific namespaces)
NAMESPACE_SCOPED_ACTIONS = {
    'view:all',
    'view:pods',
    'view:deployments',
    'view:statefulsets',
    'view:daemonsets',
    'view:replicasets',
    'view:jobs',
    'view:cronjobs',
    'view:services',
    'view:ingresses',
    'view:configmaps',
    'view:secrets',
    'view:persistentvolumeclaims',
    'view:networkpolicies',
    'view:horizontalpodautoscalers',
    'view:rollouts',
    'edit:deployment',
    'edit:statefulset',
    'edit:daemonset',
    'edit:replicaset',
    'edit:job',
    'edit:cronjob',
    'edit:service',
    'edit:configmap',
    'edit:secret',
    'edit:horizontalpodautoscaler',
    'edit:rollout',
    'delete:pod',
    'delete:deployment',
    'delete:statefulset',
    'delete:daemonset',
    'delete:replicaset',
    'delete:job',
    'delete:cronjob',
    'delete:service',
    'delete:ingress',
    'delete:configmap',
    'delete:secret',
    'delete:persistentvolumeclaim',
    'delete:networkpolicy',
    'delete:namespace',
    'delete:rollout',
    'restart:deployment',
    'restart:statefulset',
    'restart:daemonset',
    'restart:rollout',
    'rollback:deployment',
    'rollback:statefulset',
    'rollback:daemonset',
    'scale:deployment',
    'scale:statefulset',
    'scale:rollout',
    'run:cronjob',
    'rerun:job',
    'exec:pod',
    'forward:port',
    'get:deployment',
    'get:statefulset',
    'get:daemonset',
}

# =============================================================================
# K8S RESOURCE TO KOMODOR ACTION MAPPING
# =============================================================================

# Maps K8s resources to Komodor resource names (singular form used in actions)
K8S_RESOURCE_TO_KOMODOR = {
    # Core resources
    'pods': 'pod',
    'services': 'service',
    'configmaps': 'configmap',
    'secrets': 'secret',
    'namespaces': 'namespace',
    'nodes': 'node',
    'persistentvolumeclaims': 'persistentvolumeclaim',
    'persistentvolumes': 'persistentvolume',
    'serviceaccounts': 'serviceaccount',
    'endpoints': 'endpoint',
    'events': 'event',
    
    # Apps resources
    'deployments': 'deployment',
    'statefulsets': 'statefulset',
    'daemonsets': 'daemonset',
    'replicasets': 'replicaset',
    
    # Batch resources
    'jobs': 'job',
    'cronjobs': 'cronjob',
    
    # Networking resources
    'ingresses': 'ingress',
    'networkpolicies': 'networkpolicy',
    
    # Storage resources
    'storageclasses': 'storageclass',
    
    # Autoscaling resources
    'horizontalpodautoscalers': 'horizontalpodautoscaler',
    
    # RBAC resources
    'clusterroles': 'clusterrole',
    'clusterrolebindings': 'clusterrolebinding',
    'roles': 'role',
    'rolebindings': 'rolebinding',
    
    # CRDs
    'customresourcedefinitions': 'customresourcedefinition',
    
    # Argo Rollouts
    'rollouts': 'rollout',
}

# Maps K8s verbs to Komodor action verbs
K8S_VERB_TO_KOMODOR_VERB = {
    # Read verbs -> view
    'get': 'view',
    'list': 'view',
    'watch': 'view',
    
    # Write verbs -> edit
    'create': 'edit',
    'update': 'edit',
    'patch': 'edit',
    
    # Delete verb -> delete
    'delete': 'delete',
    'deletecollection': 'delete',
    
    # Special verbs
    'exec': 'exec',
    'portforward': 'forward',
}

# Resources that have view actions in Komodor
VIEWABLE_RESOURCES = {
    'pods', 'deployments', 'statefulsets', 'daemonsets', 'replicasets',
    'jobs', 'cronjobs', 'services', 'ingresses', 'configmaps', 'secrets',
    'persistentvolumeclaims', 'persistentvolumes', 'storageclasses',
    'networkpolicies', 'horizontalpodautoscalers', 'nodes', 'namespaces',
    'clusterroles', 'clusterrolebindings', 'customresourcedefinitions',
    'rollouts', 'autoscalers', 'certmanager', 'externaldns',
}

# Resources that have edit actions in Komodor
EDITABLE_RESOURCES = {
    'deployments', 'statefulsets', 'daemonsets', 'replicasets',
    'jobs', 'cronjobs', 'services', 'configmaps', 'secrets',
    'horizontalpodautoscalers', 'rollouts',
}

# Resources that have delete actions in Komodor
DELETABLE_RESOURCES = {
    'pods', 'deployments', 'statefulsets', 'daemonsets', 'replicasets',
    'jobs', 'cronjobs', 'services', 'ingresses', 'configmaps', 'secrets',
    'persistentvolumeclaims', 'persistentvolumes', 'storageclasses',
    'networkpolicies', 'namespaces', 'rollouts',
}

# Resources that have special actions
SPECIAL_RESOURCE_ACTIONS = {
    'deployments': ['restart:deployment', 'rollback:deployment', 'scale:deployment', 'get:deployment'],
    'statefulsets': ['restart:statefulset', 'rollback:statefulset', 'scale:statefulset', 'get:statefulset'],
    'daemonsets': ['restart:daemonset', 'rollback:daemonset', 'get:daemonset'],
    'cronjobs': ['run:cronjob'],
    'jobs': ['rerun:job'],
    'pods': ['exec:pod', 'forward:port'],
    'nodes': ['cordon:node', 'uncordon:node', 'drain:node'],
    'rollouts': ['restart:rollout', 'scale:rollout'],
}


def map_k8s_rule_to_komodor_actions(
    verbs: List[str],
    resources: List[str],
    api_groups: List[str] = None
) -> Set[str]:
    """
    Map a K8s RBAC rule to Komodor actions.
    
    Args:
        verbs: List of K8s verbs (e.g., ['get', 'list', 'watch'])
        resources: List of K8s resources (e.g., ['pods', 'deployments'])
        api_groups: List of API groups (e.g., ['', 'apps'])
        
    Returns:
        Set of Komodor action strings
    """
    komodor_actions = set()
    
    # Handle wildcard verbs
    if '*' in verbs:
        verbs = ['get', 'list', 'watch', 'create', 'update', 'patch', 'delete']
    
    # Handle wildcard resources
    if '*' in resources:
        # If wildcard resources, grant view:all and potentially all other actions
        if any(v in verbs for v in ['get', 'list', 'watch']):
            komodor_actions.add('view:all')
        
        # Add all possible actions for the verbs
        for verb in verbs:
            if verb in ['get', 'list', 'watch']:
                # Add all view actions
                for action in KOMODOR_ACTIONS:
                    if action.startswith('view:'):
                        komodor_actions.add(action)
            elif verb in ['create', 'update', 'patch']:
                # Add all edit actions
                for action in KOMODOR_ACTIONS:
                    if action.startswith('edit:'):
                        komodor_actions.add(action)
            elif verb == 'delete':
                # Add all delete actions
                for action in KOMODOR_ACTIONS:
                    if action.startswith('delete:'):
                        komodor_actions.add(action)
        
        return komodor_actions
    
    # Map specific resources
    for resource in resources:
        resource_lower = resource.lower()
        komodor_resource = K8S_RESOURCE_TO_KOMODOR.get(resource_lower)
        
        if not komodor_resource:
            # Try removing trailing 's' for singular form
            if resource_lower.endswith('s'):
                komodor_resource = K8S_RESOURCE_TO_KOMODOR.get(resource_lower[:-1] + 's', resource_lower[:-1])
            else:
                komodor_resource = resource_lower
        
        for verb in verbs:
            verb_lower = verb.lower()
            
            # Map verb to Komodor action verb
            if verb_lower in ['get', 'list', 'watch']:
                # Check if resource has a view action
                plural_resource = resource_lower if resource_lower.endswith('s') else resource_lower + 's'
                view_action = f'view:{plural_resource}'
                if view_action in KOMODOR_ACTIONS:
                    komodor_actions.add(view_action)
                elif f'view:{komodor_resource}s' in KOMODOR_ACTIONS:
                    komodor_actions.add(f'view:{komodor_resource}s')
                    
            elif verb_lower in ['create', 'update', 'patch']:
                # Check if resource has an edit action
                edit_action = f'edit:{komodor_resource}'
                if edit_action in KOMODOR_ACTIONS:
                    komodor_actions.add(edit_action)
                    
            elif verb_lower in ['delete', 'deletecollection']:
                # Check if resource has a delete action
                delete_action = f'delete:{komodor_resource}'
                if delete_action in KOMODOR_ACTIONS:
                    komodor_actions.add(delete_action)
        
        # Add special actions if the resource has any and verbs allow
        if resource_lower in SPECIAL_RESOURCE_ACTIONS:
            for special_action in SPECIAL_RESOURCE_ACTIONS[resource_lower]:
                action_verb = special_action.split(':')[0]
                # Map special actions based on verbs
                if action_verb in ['restart', 'rollback', 'scale'] and any(v in verbs for v in ['update', 'patch', '*']):
                    komodor_actions.add(special_action)
                elif action_verb in ['run', 'rerun'] and any(v in verbs for v in ['create', '*']):
                    komodor_actions.add(special_action)
                elif action_verb == 'exec' and 'exec' in [v.lower() for v in verbs]:
                    komodor_actions.add(special_action)
                elif action_verb == 'forward' and 'portforward' in [v.lower() for v in verbs]:
                    komodor_actions.add(special_action)
                elif action_verb == 'get' and any(v in verbs for v in ['get', 'list', 'watch', '*']):
                    komodor_actions.add(special_action)
                elif action_verb in ['cordon', 'uncordon', 'drain'] and any(v in verbs for v in ['update', 'patch', '*']):
                    komodor_actions.add(special_action)
    
    return komodor_actions


def get_action_scope(action: str) -> str:
    """
    Determine the scope of a Komodor action.
    
    Args:
        action: Komodor action string
        
    Returns:
        'unscoped', 'cluster', or 'namespace'
    """
    if action in UNSCOPED_ACTIONS:
        return 'unscoped'
    elif action in CLUSTER_SCOPED_ACTIONS:
        return 'cluster'
    elif action in NAMESPACE_SCOPED_ACTIONS:
        return 'namespace'
    else:
        # Default to namespace-scoped for unknown actions
        return 'namespace'


def categorize_actions(actions: Set[str]) -> Dict[str, Set[str]]:
    """
    Categorize a set of actions by their scope.
    
    Args:
        actions: Set of Komodor action strings
        
    Returns:
        Dictionary with keys 'unscoped', 'cluster', 'namespace'
    """
    categorized = {
        'unscoped': set(),
        'cluster': set(),
        'namespace': set()
    }
    
    for action in actions:
        scope = get_action_scope(action)
        categorized[scope].add(action)
    
    return categorized


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_all_view_actions() -> Set[str]:
    """Get all view actions."""
    return {a for a in KOMODOR_ACTIONS if a.startswith('view:')}


def get_all_edit_actions() -> Set[str]:
    """Get all edit actions."""
    return {a for a in KOMODOR_ACTIONS if a.startswith('edit:')}


def get_all_delete_actions() -> Set[str]:
    """Get all delete actions."""
    return {a for a in KOMODOR_ACTIONS if a.startswith('delete:')}


def get_admin_actions() -> Set[str]:
    """Get all admin/management actions."""
    return {a for a in KOMODOR_ACTIONS if a.startswith('manage:')}


def is_valid_action(action: str) -> bool:
    """Check if an action is valid."""
    return action in KOMODOR_ACTIONS


if __name__ == '__main__':
    # Test the mapping
    print("Testing K8s to Komodor action mapping:")
    print("=" * 50)
    
    # Test case 1: Read pods
    result = map_k8s_rule_to_komodor_actions(['get', 'list', 'watch'], ['pods'])
    print(f"get/list/watch pods -> {result}")
    
    # Test case 2: Full access to deployments
    result = map_k8s_rule_to_komodor_actions(['*'], ['deployments'])
    print(f"* deployments -> {result}")
    
    # Test case 3: Delete pods
    result = map_k8s_rule_to_komodor_actions(['delete'], ['pods'])
    print(f"delete pods -> {result}")
    
    # Test case 4: Wildcard everything
    result = map_k8s_rule_to_komodor_actions(['*'], ['*'])
    print(f"* * -> {len(result)} actions")
    
    # Test case 5: Node operations
    result = map_k8s_rule_to_komodor_actions(['get', 'list', 'update', 'patch'], ['nodes'])
    print(f"get/list/update/patch nodes -> {result}")
