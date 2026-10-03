import { useAuthStore } from '@/stores/auth';
import { navigationSections } from '@/shared/constants/navigation';

function findNavigationItem(path) {
  const items = navigationSections
    .flatMap((section) => section.items)
    .filter((item) => item.to);

  const exact = items.find((item) => item.to === path);
  if (exact) {
    return exact;
  }

  return items
    .filter((item) => item.to !== '/')
    .filter((item) => path.startsWith(`${item.to}/`))
    .sort((left, right) => right.to.length - left.to.length)[0];
}

export function setupAuthGuard(router) {
  router.beforeEach(async (to) => {
    const auth = useAuthStore();
    const fallbackRoute = () => auth.getFirstAllowedRoute() || '/login';

    if (!auth.isAuthenticated) {
      auth.restoreSession();
    }

    if (to.meta?.requiresGuest && auth.isAuthenticated) {
      if (!auth.user || !Array.isArray(auth.permissions) || !auth.permissions.length) {
        try {
          await auth.fetchMe();
        } catch (error) {
          auth.resetState();
          return true;
        }
      }

      const target = fallbackRoute();
      if (target === '/login') {
        auth.resetState();
        return true;
      }
      if (to.path !== target) {
        return { path: target };
      }
      return true;
    }

    if (to.meta?.requiresAuth && !auth.isAuthenticated) {
      return { path: '/login', query: { redirect: to.fullPath } };
    }

    if (
      to.meta?.requiresAuth &&
      auth.isAuthenticated &&
      (!auth.user || !Array.isArray(auth.permissions) || !auth.permissions.length)
    ) {
      try {
        await auth.fetchMe();
      } catch (error) {
        auth.resetState();
        return { path: '/login' };
      }
    }

    const navItem = findNavigationItem(to.path);
    const hasMenuPermission = navItem ? auth.hasMenuAccess(navItem) : false;
    const hasRouteAlias = Array.isArray(to.meta?.permissionAliases)
      && to.meta.permissionAliases.some((permission) => auth.hasPermission(permission));

    if (to.meta?.permission && !auth.hasPermission(to.meta.permission) && !hasRouteAlias && !hasMenuPermission) {
      const target = fallbackRoute();
      if (to.path !== target) {
        return { path: target };
      }
      return false;
    }

    return true;
  });
}
