import api from './axios';

export function getMonthlySalesTargets(params) {
  return api.get('/api/sales/targets-monthly', { params });
}

export function saveMonthlySalesTargets(payload) {
  return api.put('/api/sales/targets-monthly', payload, { timeout: 120000 });
}

export function getSalesDoiAnalysis(params) {
  return api.get('/api/sales/doi-analysis', { params });
}

export function exportSalesDoiAnalysis(params, format = 'xlsx') {
  return api.get('/api/sales/doi-analysis/export', {
    params: { ...params, format },
    responseType: 'blob',
    timeout: 120000
  });
}

export function getSalesSupervisorScope() {
  return api.get('/api/sales/supervisor-scope');
}

export function getSalesSupervisorMappings(params) {
  return api.get('/api/sales/supervisor-map', { params });
}

export function getSupervisorCustomerMap(params) {
  return api.get('/api/sales-kunjungan/supervisor-customer-map', { params });
}

export function saveSalesSupervisorMapping(payload) {
  return api.post('/api/sales/supervisor-map', payload);
}

export function deleteSalesSupervisorMapping(id, params) {
  return api.delete(`/api/sales/supervisor-map/${id}`, { params });
}
