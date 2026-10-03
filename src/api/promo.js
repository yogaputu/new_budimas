import api from './axios';

export function getVouchers(params) {
  return api.get('/api/voucher', { params });
}

export function getVoucherDetail(type, idVoucher) {
  return api.get(`/api/voucher/get-voucher-by-id/${type}`, {
    params: {
      id_voucher: idVoucher
    }
  });
}

export function getVoucherV1Regular() {
  return api.get('/api/voucher/get-v1-regular');
}

export function getVoucherV2Regular() {
  return api.get('/api/voucher/get-v2-regular');
}

export function getVoucherV3Regular() {
  return api.get('/api/voucher/get-v3-regular');
}

export function createVoucher(type, payload) {
  return api.post(`/api/voucher/${type}`, payload);
}

export function updateVoucher(type, payload) {
  return api.put(`/api/voucher/${type}`, payload);
}

export function deleteVoucher(type, idVoucher) {
  return api.delete(`/api/voucher/${type}`, {
    params: {
      id_voucher: idVoucher
    }
  });
}

export function getVoucherUsageMonitoring(params) {
  return api.get('/api/voucher/usage-monitoring', { params });
}

export function getVoucherUsageByProduct(params) {
  return api.get('/api/voucher/usage-monitoring/by-product', { params });
}

export function getVoucherUsageDetail(usageKind, usageId) {
  return api.get(`/api/voucher/usage-monitoring/${usageKind}/${usageId}`);
}

export function approveVoucherUsage(payload) {
  return api.post('/api/voucher/usage-monitoring/approve', payload);
}

export function rejectVoucherUsage(payload) {
  return api.post('/api/voucher/usage-monitoring/reject', payload);
}

export function getPromoDropdownData(params) {
  return api.get('/api/promo/dropdown-data', { params });
}

export function getPromoClaimDropdownData(params) {
  return api.get('/api/promo/dropdown-data-klaim', { params });
}

export function getPromoClaimReadyDropdownData(params) {
  return api.get('/api/promo/dropdown-data-klaim-ready', { params });
}

export function generatePromoClaimCode(payload) {
  return api.post('/api/promo/generate-code', payload);
}

export function getPromoClaimCategories(params) {
  return api.get('/api/promo/klaim-kategori', { params });
}

export function createPromoClaimCategory(payload) {
  return api.post('/api/promo/klaim-kategori', payload);
}

export function updatePromoClaimCategory(id, payload) {
  return api.put(`/api/promo/klaim-kategori/${id}`, payload);
}

export function deletePromoClaimCategory(id) {
  return api.delete(`/api/promo/klaim-kategori/${id}`);
}

export function getPromoClaimInvoiceList(params) {
  return api.get('/api/promo/list-faktur', { params });
}

export function createPromoClaim(payload) {
  return api.post('/api/promo/ajukan-klaim', payload);
}

export function resubmitPromoClaim(payload) {
  return api.put('/api/promo/ajukan-ulang-klaim', payload);
}

export function getPromoClaims(params) {
  return api.get('/api/promo/klaim-promo', { params });
}

export function getRejectedPromoClaims(params) {
  return api.get('/api/promo/klaim-promo/ditolak', { params });
}

export function getPromoClaimDetail(id) {
  return api.get(`/api/promo/klaim-promo/detail/${id}`);
}

export function updatePromoClaimStatus(id, payload) {
  return api.put(`/api/promo/klaim-promo/update-status/${id}`, payload);
}

export function createKasbonClaim(payload) {
  return api.post('/api/promo/kasbon-klaim/ajukan', payload);
}

export function getKasbonClaims(params) {
  return api.get('/api/promo/kasbon-klaim', { params });
}

export function getKasbonClaimDetail(idKasbon) {
  return api.get(`/api/promo/kasbon-klaim/${idKasbon}`);
}

export function getKasbonClaimItems(idKasbon, params) {
  return api.get(`/api/promo/kasbon-klaim/${idKasbon}/klaim`, { params });
}

export function confirmKasbonClaim(idKasbon, payload) {
  return api.post(`/api/promo/kasbon-klaim/${idKasbon}/konfirmasi`, payload);
}

export function previewTradePromoSalesOrder(payload) {
  return api.post('/api/promo/trade/preview-sales-order', payload);
}

export function getTradePromoMonitoring(params) {
  return api.get('/api/promo/trade/monitoring', { params });
}

export function getUnifiedPromos(params) {
  return api.get('/api/promo/unified', { params });
}

export function createUnifiedPromo(payload) {
  return api.post('/api/promo/unified', payload);
}

export function updateUnifiedPromo(id, payload) {
  return api.put(`/api/promo/unified/${id}`, payload);
}

export function deleteUnifiedPromo(id) {
  return api.delete(`/api/promo/unified/${id}`);
}

export function setUnifiedPromoStatus(id, payload) {
  return api.patch(`/api/promo/unified/${id}/status`, payload);
}

export function getUnifiedPromoRuleUomOptions(payload) {
  return api.post('/api/promo/unified/rule-uom-options', payload);
}

export function previewUnifiedPromoSalesOrder(payload) {
  return api.post('/api/promo/unified/preview-sales-order', payload);
}

export function getUnifiedPromoMonitoring(params) {
  return api.get('/api/promo/unified/monitoring', { params });
}
