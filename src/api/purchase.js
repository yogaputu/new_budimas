import api from './axios';

export function getPurchaseOrders(params) {
  return api.get('/api/extra/purchase-order/daftar-laporan', { params });
}

export function getPurchaseOrdersPaged(params) {
  return api.get('/api/extra/purchase-order/daftar-laporan-paged', { params });
}

export function getPurchaseOrderDetail(id) {
  return api.get(`/api/extra/purchase-order/detail-purchase-laporan/${id}`);
}

export function getPurchaseOrderProducts(id) {
  return api.get(`/api/extra/purchase-order/daftar-produk/${id}`);
}

export function generatePurchaseOrderCode(branchId, principalId) {
  if (principalId) {
    return api.get(`/api/extra/purchase-order/gen-kode/${branchId}/${principalId}`);
  }
  return api.get(`/api/extra/purchase-order/gen-kode/${branchId}`);
}

export function createPurchaseOrder(payload) {
  return api.post('/api/extra/purchase-order/proses/request', payload);
}

export function importPurchaseOrderTemplate(formData) {
  return api.post('/api/extra/purchase-order/import-template', formData, {
    headers: {
      'Content-Type': 'multipart/form-data'
    },
    timeout: 120000
  });
}

export function updatePurchaseOrder(payload) {
  return api.post('/api/extra/purchase-order/proses/revisi', payload);
}

export function confirmPurchaseOrder(payload) {
  return api.post('/api/extra/purchase-order/proses/konfirmasi', payload);
}

export function approvePurchaseOrderRequest(payload) {
  return api.post('/api/extra/purchase-order/proses/approve-request', payload);
}

export function rejectPurchaseOrderRequest(payload) {
  return api.post('/api/extra/purchase-order/proses/reject-request', payload);
}

export function getPurchaseOrderConfirmationQueue(params) {
  return api.get('/api/extra/purchase-order/daftar-konfirmasi', { params });
}

export function closePurchaseOrder(payload) {
  return api.post('/api/extra/purchase-order/proses/closed', payload);
}

export function getPurchaseReceipts(params) {
  return api.get('/api/extra/purchase-transaksi/daftar-laporan', { params });
}

export function getPurchaseReceiptDetail(id) {
  return api.get(`/api/extra/purchase-transaksi/detail-riwayat/${id}`);
}

export function getPurchaseReadyOrders(params) {
  return api.get('/api/extra/purchase-order/daftar-purchase', { params });
}

export function createPurchaseReceipt(payload) {
  return api.post('/api/extra/purchase-transaksi/proses/penerimaan-barang', payload);
}

export function getPurchaseConfirmationQueue(params) {
  return api.get('/api/extra/purchase-transaksi/daftar-konfirmasi', { params });
}

export function confirmPurchaseReceipt(payload) {
  return api.post('/api/extra/purchase-transaksi/proses/konfirmasi', payload);
}

export function getPurchaseBillingQueue(params) {
  return api.get('/api/extra/purchase-transaksi/show/table/list-proses-tagihan', { params });
}

export function getPurchasePayables(params) {
  return api.get('/api/akuntansi/get-hutang', { params });
}

export function getPurchaseBillCandidateTransactions(params) {
  return api.get('/api/akuntansi/get-add-tagihan-purchase', { params });
}

export function createPurchaseBill(payload) {
  return api.post('/api/akuntansi/create-tagihan-purchase', payload);
}

export function getPurchaseBillDetail(noTagihan) {
  return api.get('/api/akuntansi/detail-tagihan-purchase', {
    params: { no_tagihan: noTagihan }
  });
}

export function createPurchaseBillPayment(payload) {
  return api.post('/api/finance/purchase-bill-payments', payload, {
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  });
}
