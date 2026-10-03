import api from './axios';

export function getHelperDriverDashboard(params) {
  return api.get('/api/helper-driver/dashboard', { params });
}

export function getHelperDriverAssignments(params) {
  return api.get('/api/helper-driver/assignments', { params });
}

export function createHelperDriverAssignment(payload) {
  return api.post('/api/helper-driver/assignments', payload);
}

export function updateHelperDriverAssignmentStatus(id, payload) {
  return api.post(`/api/helper-driver/assignments/${id}/status`, payload);
}

export function getHelperDriverLatestTracking(params) {
  return api.get('/api/helper-driver/tracking/latest', { params });
}
