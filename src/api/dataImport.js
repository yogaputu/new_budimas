import api from './axios';

export function uploadSalesOrderImportPreview(formData) {
  return api.post('/api/extra/data-import/sales-order/preview', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
}

export function getSalesOrderImportBatches() {
  return api.get('/api/extra/data-import/sales-order/batches');
}

export function getSalesOrderImportBatch(batchId) {
  return api.get(`/api/extra/data-import/sales-order/batches/${batchId}`);
}

export function processSalesOrderImportBatch(batchId) {
  return api.post(`/api/extra/data-import/sales-order/process/${batchId}`);
}

export function revalidateSalesOrderImportBatch(batchId) {
  return api.post(`/api/extra/data-import/sales-order/revalidate/${batchId}`);
}

export function saveProductExternalMapping(payload) {
  return api.post('/api/extra/data-import/product-mapping', payload);
}

export function saveCustomerExternalMapping(payload) {
  return api.post('/api/extra/data-import/customer-mapping', payload);
}

export function getLegacySyncStatus() {
  return api.get('/api/extra/legacy-sync/status');
}
