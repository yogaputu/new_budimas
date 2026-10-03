import { defineStore } from 'pinia';
import { loginApi, logoutApi, meApi } from '@/api/auth';
import { clearAuthSession, getAuthSession, setAuthSession } from '@/utils/session';
import { unwrapResponse } from '@/utils/api';
import { navigationSections } from '@/shared/constants/navigation';
import { roleCanAccessPermission } from '@/utils/roleAccess';

function normalizeLoginData(payload) {
  return {
    access_token: payload?.access_token || payload?.token || payload?.accessToken || null,
    token_type: payload?.token_type || 'Bearer',
    expires_in: payload?.expires_in || null,
    user: payload?.user || payload?.data_user || payload?.detail_user || null,
    permissions: payload?.permissions || payload?.fitur || [],
    menus: payload?.menus || payload?.menu || []
  };
}

function normalizeProfile(payload) {
  if (!payload) {
    return { user: null, permissions: [], menus: [] };
  }

  if (payload.user || payload.permissions || payload.menus) {
    return {
      user: payload.user || payload.detail_user || payload,
      permissions: payload.permissions || payload.fitur || [],
      menus: payload.menus || payload.menu || []
    };
  }

  return {
    user: payload.detail_user || payload,
    permissions: payload.fitur || [],
    menus: payload.menu || []
  };
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    token: null,
    permissions: [],
    menus: [],
    isAuthenticated: false,
    loading: false
  }),
  getters: {
    userName: (state) => state.user?.nama || state.user?.username || 'User',
    branchName: (state) => state.user?.cabang?.nama || state.user?.nama_cabang || '-',
    roleLabel: (state) =>
      state.user?.jabatan?.nama || state.user?.nama_jabatan || state.user?.role_code || '-',
    roleScope: (state) => state.user?.jabatan?.scope || state.user?.role_code || 'general',
    homeRoute() {
      const requestedHome = this.user?.home_route;

      if (requestedHome && this.canAccessRoute(requestedHome)) {
        return requestedHome;
      }

      const firstAllowed = this.getFirstAllowedRoute();
      return firstAllowed || '/login';
    },
    focusPoints: (state) => state.user?.focus_points || [],
    moduleAccess: (state) => state.user?.module_access || []
  },
  actions: {
    getFirstAllowedRoute() {
      const firstAllowed = navigationSections
        .flatMap((section) => section.items)
        .find((item) => this.hasMenuAccess(item));

      return firstAllowed?.to || '';
    },

    canAccessRoute(path) {
      const item = navigationSections
        .flatMap((section) => section.items)
        .find((entry) => entry.to === path);

      if (!item) {
        return path === '/';
      }

      return this.hasMenuAccess(item);
    },

    async login(payload) {
      this.loading = true;

      try {
        const response = await loginApi(payload);
        const data = normalizeLoginData(unwrapResponse(response));

        this.user = data.user;
        this.token = data.access_token;
        this.permissions = Array.isArray(data.permissions) ? data.permissions : [];
        this.menus = Array.isArray(data.menus) ? data.menus : [];
        this.isAuthenticated = Boolean(data.access_token);

        if (!this.token) {
          this.resetState();
          throw new Error('Login berhasil, tetapi token user tidak tersedia dari API lama.');
        }

        setAuthSession(data);
        return data;
      } finally {
        this.loading = false;
      }
    },

    restoreSession() {
      const session = getAuthSession();

      if (!session?.access_token) {
        this.resetState();
        return false;
      }

      this.user = session.user || null;
      this.token = session.access_token;
      this.permissions = session.permissions || [];
      this.menus = session.menus || [];
      this.isAuthenticated = true;
      return true;
    },

    async fetchMe() {
      const activeToken = this.token || getAuthSession()?.access_token;

      if (!activeToken) {
        throw new Error('Token login tidak tersedia untuk mengambil profil user.');
      }

      const response = await meApi(activeToken);
      const payload = normalizeProfile(unwrapResponse(response));

      this.user = payload.user;
      this.token = activeToken;
      this.permissions = Array.isArray(payload.permissions) ? payload.permissions : this.permissions;
      this.menus = Array.isArray(payload.menus) ? payload.menus : this.menus;

      setAuthSession({
        access_token: this.token,
        token_type: 'Bearer',
        user: this.user,
        permissions: this.permissions,
        menus: this.menus
      });

      return this.user;
    },

    hasPermission(permission) {
      if (!permission) {
        return true;
      }

      const aliases = {
        'master.roles.view': [
          'master.users.view',
          'master_users.view',
          'master.user-features.view',
          'master_user_features.view',
          'master.position-features.view',
          'master_position_features.view'
        ],
        'master.roles.create': ['master.users.create', 'master_users.create'],
        'master.roles.update': ['master.users.update', 'master_users.update'],
        'master.roles.delete': ['master.users.delete', 'master_users.delete'],
        'master.plafons.view': ['master_plafons.view', 'master.customers.view', 'master_customers.view'],
        'master.principal-rules.view': ['master_principal_rules.view', 'master.products.view', 'master_products.view', 'distribution.orders.view'],
        'master.customer-product-rules.view': ['master_customer_product_rules.view', 'master.customers.view', 'master_customers.view', 'master.products.view', 'master_products.view'],
        'master.user-features.view': ['master_user_features.view', 'master.users.view', 'master_users.view'],
        'master.position-features.view': ['master_position_features.view', 'master.users.view', 'master_users.view'],
        'stock-opname.view': ['stock_opname.view', 'stock-opname', 'stock_opname', '/stock-opname'],
        'stock-opname.create': ['stock_opname.create', 'stock-opname.create', 'stock_opname', '/stock-opname'],
        'stock-transfer.view': ['stock_transfer.view', 'stock-transfer', 'stock_transfer', '/stock-transfer'],
        'stock-transfer.create': ['stock_transfer.create', 'stock_transfer', '/stock-transfer'],
        'wms.view': [
          'wms',
          '/wms',
          'stock-transfer.view',
          'stock_transfer.view',
          'stock-opname.view',
          'stock_opname.view',
          'distribution.picking.view',
          'm.operasional.wm.view',
          'm.operasional.st.view',
          'm.operasional.so.view',
          'm.distribusi.pk.view'
        ]
      };
      const normalizedPermission = permission.replace(/-/g, '_');
      const allowed = new Set([
        permission,
        normalizedPermission,
        ...(aliases[permission] || [])
      ]);

      return (
        this.permissions?.includes('*') ||
        this.permissions?.some((item) => allowed.has(item)) ||
        roleCanAccessPermission(this, permission)
      );
    },

    hasMenuAccess(item) {
      if (!item) {
        return false;
      }

      if (Array.isArray(item.permissionAliases) && item.permissionAliases.some((permission) => this.hasPermission(permission))) {
        return true;
      }

      if (item.menuPermission) {
        const usesMenuPermissions = this.permissions?.some((permission) => permission === '*' || String(permission).startsWith('m.'));
        return usesMenuPermissions ? this.hasPermission(item.menuPermission) : this.hasPermission(item.permission);
      }

      return this.hasPermission(item.permission);
    },

    hasAction(resource, action = 'view') {
      if (!resource) {
        return true;
      }

      return this.hasPermission(`${resource}.${action}`);
    },

    canView(resource) {
      return this.hasAction(resource, 'view');
    },

    canCreate(resource) {
      return this.hasAction(resource, 'create');
    },

    canUpdate(resource) {
      return this.hasAction(resource, 'update');
    },

    canDelete(resource) {
      return this.hasAction(resource, 'delete');
    },

    canApprove(resource) {
      return this.hasAction(resource, 'approve');
    },

    canPrint(resource) {
      return this.hasAction(resource, 'print');
    },

    canExport(resource) {
      return this.hasAction(resource, 'export');
    },

    hasAnyPermission(list = []) {
      if (!Array.isArray(list) || !list.length) {
        return true;
      }

      return list.some((permission) => this.hasPermission(permission));
    },

    async logout() {
      try {
        await logoutApi();
      } finally {
        this.resetState();
      }
    },

    resetState() {
      this.user = null;
      this.token = null;
      this.permissions = [];
      this.menus = [];
      this.isAuthenticated = false;
      clearAuthSession();
    }
  }
});
