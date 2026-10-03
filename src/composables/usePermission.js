import { computed } from 'vue';
import { useAuthStore } from '@/stores/auth';

export function usePermission() {
  const auth = useAuthStore();

  const permissions = computed(() => auth.permissions || []);

  const hasPermission = (permission) => {
    return auth.hasPermission(permission);
  };

  const hasAnyPermission = (list = []) => {
    return auth.hasAnyPermission(list);
  };

  const hasAction = (resource, action = 'view') => auth.hasAction(resource, action);

  return {
    permissions,
    hasPermission,
    hasAnyPermission,
    hasAction,
    canView: (resource) => auth.canView(resource),
    canCreate: (resource) => auth.canCreate(resource),
    canUpdate: (resource) => auth.canUpdate(resource),
    canDelete: (resource) => auth.canDelete(resource),
    canApprove: (resource) => auth.canApprove(resource),
    canPrint: (resource) => auth.canPrint(resource),
    canExport: (resource) => auth.canExport(resource)
  };
}
