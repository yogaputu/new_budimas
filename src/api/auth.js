import api from './axios';

export function loginApi(payload) {
  return api.post('/api/auth/login', payload);
}

export function logoutApi() {
  return Promise.resolve({ data: { success: true } });
}

export function meApi(token) {
  const headers = token
    ? {
        Authorization: `Bearer ${token}`
      }
    : undefined;

  return api.get('/api/extra/user/detail-login', { headers });
}

export function permissionsApi() {
  return Promise.resolve({ data: { data: { permissions: [] } } });
}

export function tokenApi() {
  return api.post('/api/auth/token');
}

export function userTokenApi() {
  return api.get('/api/extra/getUserToken');
}
