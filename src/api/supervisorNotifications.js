import api from './axios';

export function pollSupervisorNotifications(params) {
  return api.get('/api/supervisor-notifications/poll', { params });
}

export function markSupervisorNotificationsRead(payload) {
  return api.post('/api/supervisor-notifications/read', payload);
}
