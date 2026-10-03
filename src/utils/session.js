const AUTH_KEY = 'budimas_internal_auth';
const LEGACY_AUTH_KEYS = [
  'auth',
  'token',
  'access_token',
  'user',
  'permissions',
  'menus',
  'budimas_auth',
  'budimas_user',
  'budimas_token',
  'budimas_internal_user',
  'budimas_internal_permissions',
  'budimas_internal_menus'
];
const USER_STATE_PREFIXES = ['budimas.salesOrder.'];

function removeAuthKeys(storage) {
  if (!storage) {
    return;
  }

  [AUTH_KEY, ...LEGACY_AUTH_KEYS].forEach((key) => storage.removeItem(key));

  for (let index = storage.length - 1; index >= 0; index -= 1) {
    const key = storage.key(index);
    if (USER_STATE_PREFIXES.some((prefix) => key?.startsWith(prefix))) {
      storage.removeItem(key);
    }
  }
}

export function setAuthSession(payload) {
  localStorage.setItem(AUTH_KEY, JSON.stringify(payload));
  sessionStorage.removeItem(AUTH_KEY);
}

export function getAuthSession() {
  try {
    const raw = localStorage.getItem(AUTH_KEY) || sessionStorage.getItem(AUTH_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (error) {
    clearAuthSession();
    return null;
  }
}

export function clearAuthSession() {
  removeAuthKeys(localStorage);
  removeAuthKeys(sessionStorage);
}

export function getAccessToken() {
  return getAuthSession()?.access_token || null;
}
