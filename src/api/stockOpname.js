import api from './axios';

export function getStockOpnameList(params) {
  return api.get('/api/stock-opname/stock-opname', { params });
}

export function getStockOpnameDetail(id, params) {
  return api.get(`/api/stock-opname/stock-opname-detail/${id}`, { params });
}

export function getStockReport(params) {
  return api.get('/api/stock-opname/laporan-stock', { params });
}

export function getStockOpnameProducts(params) {
  return api.get('/api/stock-opname/get-produks-stock-opname', { params });
}

export function createStockOpname(payload) {
  return api.post('/api/stock-opname/create-stock-opname', payload);
}

export function createStockOpnameSchedule(payload) {
  return api.post('/api/stock-opname/create-stock-opname-schedule', payload);
}

export function getStockOpnameSchedules(params) {
  return api.get('/api/stock-opname/stock-opname-schedules', { params });
}

export function updateStockOpnameSchedule(id, payload) {
  return api.put(`/api/stock-opname/stock-opname-schedules/${id}`, payload);
}

export function deleteStockOpnameSchedule(id) {
  return api.delete(`/api/stock-opname/stock-opname-schedules/${id}`);
}

export function acceptStockOpname(payload) {
  return api.put('/api/stock-opname/stock-opname-diterima', payload);
}

export function rejectStockOpname(payload) {
  return api.put('/api/stock-opname/stock-opname-ditolak', payload);
}

export function escalateStockOpname(payload) {
  return api.put('/api/stock-opname/stock-opname-eskalasi', payload);
}

export function closeEscalatedStockOpname(payload) {
  return api.put('/api/stock-opname/stock-opname-eskalasi-closed', payload);
}
