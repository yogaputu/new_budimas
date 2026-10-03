import api from './axios';

export function getSalesCustomers(userId) {
  return api.get(`/api/customer/list-sales-customer/${userId}`);
}

export function getCustomerPlafons(params) {
  return api.get('/api/customer/sisa-plafon', { params });
}

export function getSalesOrderProducts(params) {
  return api.get('/api/produk/get-produk-so', { params });
}

export function createSalesOrder(payload) {
  return api.post('/api/sales/sales-request', payload);
}

export function getEditableSalesOrder(id) {
  return api.get(`/api/sales/order-edit/${id}`);
}

export function updateSalesOrder(id, payload) {
  return api.put(`/api/sales/order-edit/${id}`, payload, { timeout: 120000 });
}

export function getSalesOrderList(params) {
  return api.get('/api/sales/list-orders', { params });
}

export function getSalesReturList(params) {
  return api.get('/api/sales/retur-tracking', { params });
}

export function getSalesInvoiceDashboard(params) {
  return api.get('/api/sales/invoice-dashboard', { params });
}

export function searchSalesInvoices(params) {
  return api.get('/api/sales/search-invoice', { params });
}

export function checkSalesRetur(params) {
  return api.get('/api/sales/check-retur', { params });
}

export function createSalesRetur(payload) {
  return api.post('/api/sales/sales-retur', payload);
}

export function getReturDetail(idRequest) {
  return api.get(`/api/retur/get-detail-retur/${idRequest}`);
}

export function printReturKpr(idRequest, payload) {
  return api.post(`/api/retur/cetak-kpr/${idRequest}`, payload);
}

export function approveReturBySpv(idRequest, payload) {
  return api.post(`/api/retur/approve-spv/${idRequest}`, payload);
}

export function submitReturStock(idRequest, payload) {
  return api.post(`/api/retur/insert-retur-stock/${idRequest}`, payload);
}

export function cancelReturBySpv(idRequest, payload) {
  return api.post(`/api/retur/batal-spv/${idRequest}`, payload);
}

export function cancelReturByDriver(idRequest, payload) {
  return api.post(`/api/retur/batal-driver/${idRequest}`, payload);
}

export function getSalesMonthlyInfo(params) {
  return api.get('/api/sales/get-user-info-month', { params });
}

export function getSalesOmset(params) {
  return api.get('/api/sales/get-omset', { params });
}
