import api from './axios';

export function getFleetRoutes(params) {
  return api.get('/api/distribusi/get-rute-armada', { params });
}

export function getAllFleets(params) {
  return api.get('/api/distribusi/get-all-armada', { params });
}

export function getAllDrivers(params) {
  return api.get('/api/distribusi/get-all-driver', { params });
}

export function getPickingRoutes(params) {
  return api.get('/api/distribusi/get-rute-picking', { params });
}

export function getFleetRouteInfo(params) {
  return api.get('/api/distribusi/get-info-rute-armada', { params });
}

export function getPickingStores(params) {
  return api.get('/api/distribusi/daftar-picking-toko', { params });
}

export function getPickingProducts(params) {
  return api.get('/api/distribusi/get-add-picking', { params });
}

export function getDraftVariantPickingNote(params) {
  return api.get('/api/distribusi/get-nota-draft-variant', { params });
}

export function submitPickingProducts(payload) {
  return api.post('/api/distribusi/submit-produk-picking', payload);
}

export function getShippingRoutes(branchId, params) {
  return api.get(`/api/distribusi/get-list-rute-shipping/${branchId}`, { params });
}

export function getRealizationRoutes(branchId, params) {
  return api.get(`/api/distribusi/get-list-rute-realisasi/${branchId}`, { params });
}

export function getRevisionRoutes(params) {
  return api.get('/api/distribusi/get-list-rute-revisi-faktur', { params });
}

export function getShippingInvoices(params) {
  return api.get('/api/distribusi/get-list-faktur-shipping', { params });
}

export function getRealizationInvoices(params) {
  return api.get('/api/distribusi/get-list-faktur-realisasi', { params });
}

export function getDistributionHistory(params) {
  return api.get('/api/distribusi/get-list-history-distribusi', { params });
}

export function getRouteHistory(branchId, params) {
  return api.get(`/api/distribusi/get-list-rute-history/${branchId}`, { params });
}

export function getNotaHistory(params) {
  return api.get('/api/distribusi/get-list-nota-history', { params });
}

export function getRevisionInvoices(params) {
  return api.get('/api/distribusi/get-list-faktur-revisi-faktur', { params });
}

export function getRealizationDetail(params) {
  return api.get('/api/distribusi/get-realisasi-detail', { params });
}

export function confirmOrder(payload) {
  return api.patch('/api/distribusi/konfirmasi-order', payload);
}

export function rejectOrder(payload) {
  return api.patch('/api/distribusi/tolak-order', payload);
}

export function getInvoiceDetail(id, params) {
  return api.get(`/api/distribusi/get-detail-faktur/${id}`, { params });
}

export function recordInvoicePrint(idFaktur) {
  return api.post(`/api/distribusi/catat-cetak-faktur/${idFaktur}`);
}

export function getOrders(branchId, params) {
  return api.get(`/api/distribusi/get-list-order/${branchId}`, { params });
}

export function getVerificationOrders(params) {
  return api.get('/api/distribusi/get-list-verifikasi', { params });
}

export function getFleetSchedules(params) {
  return api.get('/api/distribusi/get-jadwal-armada', { params });
}

export function getShipmentDraftOrders(params) {
  return api.get('/api/distribusi/shipment-draft-orders', { params });
}

export function updateFleetSchedule(payload) {
  return api.post('/api/distribusi/edit-jadwal', payload);
}

export function createFleetScheduleFromSalesOrders(payload) {
  return api.post('/api/distribusi/update', payload);
}

export function submitPicking(payload) {
  return api.post('/api/distribusi/submit-picking', payload);
}

export function submitInvoices(payload) {
  return api.post('/api/distribusi/submit-faktur', payload);
}

export function submitRealization(payload) {
  return api.post('/api/distribusi/submit-realisasi-detail', payload);
}

export function submitInvoiceRevision(payload) {
  return api.post('/api/distribusi/submit-revisi-faktur', payload);
}

// Workflow pembatalan realisasi. Endpoint ini sengaja terpisah dari
// /batal-realisasi lama karena perubahan stok/status baru boleh terjadi setelah
// approval awal, revisi faktur, dan approval final selesai.
export function getCancelRealizationRequests(params) {
  return api.get('/api/distribusi/batal-realisasi/requests', { params });
}

export function getCancelRealizationCandidates(params) {
  return api.get('/api/distribusi/batal-realisasi/candidates', { params });
}

export function createCancelRealizationRequest(payload) {
  return api.post('/api/distribusi/batal-realisasi/requests', payload);
}

export function getCancelRealizationRequest(id) {
  return api.get(`/api/distribusi/batal-realisasi/requests/${id}`);
}

export function approveCancelRealizationRequest(id, payload) {
  return api.post(`/api/distribusi/batal-realisasi/requests/${id}/approve`, payload);
}

export function rejectCancelRealizationRequest(id, payload) {
  return api.post(`/api/distribusi/batal-realisasi/requests/${id}/reject`, payload);
}

export function submitCancelRealizationRevision(id, payload) {
  return api.post(`/api/distribusi/batal-realisasi/requests/${id}/revision`, payload);
}

export function finalApproveCancelRealizationRequest(id, payload) {
  return api.post(`/api/distribusi/batal-realisasi/requests/${id}/final-approve`, payload);
}

export function finalRejectCancelRealizationRequest(id, payload) {
  return api.post(`/api/distribusi/batal-realisasi/requests/${id}/final-reject`, payload);
}

export function getDriverExpenseList(params) {
  return api.get('/api/distribusi/get-pengeluaran-driver-list', { params });
}

export function getDriverExpenseInfo(id) {
  return api.get(`/api/distribusi/get-pengeluaran-driver-info-update/${id}`);
}

export function getDriverExpenseInvoices(id) {
  return api.get(`/api/distribusi/get-pengeluaran-driver-info-fakturs-update/${id}`);
}

export function getDriverExpenseInvoiceCandidates(driverId) {
  return api.get(`/api/distribusi/get-pengeluaran-driver-info-fakturs-add/${driverId}`);
}

export function createDriverExpense(payload) {
  return api.post('/api/distribusi/tambah-pengeluaran-driver', payload);
}

export function updateDriverExpense(payload) {
  return api.post('/api/distribusi/update-pengeluaran-driver', payload);
}

export function searchDriverExpense(params) {
  return api.get('/api/distribusi/search-driver', { params });
}
