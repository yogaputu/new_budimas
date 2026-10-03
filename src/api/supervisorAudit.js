import api from './axios';

export function getSupervisorAuditLogs(params) {
  return api.get('/api/supervisor-audit/logs', { params });
}

export function getSupervisorAuditOptions(params) {
  return api.get('/api/supervisor-audit/options', { params });
}
