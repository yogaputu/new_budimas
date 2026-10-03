import api from './axios';

export function getWmsInventory(params) {
  return api.get('/api/inventory/inventory/inventory', { params });
}

export function getWmsInventoryBarcode(productCode) {
  return api.get(`/api/inventory/inventory/barcode/${encodeURIComponent(productCode)}`);
}

export function getWmsRacks(params, config = {}) {
  return api.get('/api/wms/racks', { ...config, params });
}

export function getWmsPrincipalGroups(params) {
  return api.get('/api/wms/principal-groups', { params });
}

export function createWmsPrincipalGroup(payload) {
  return api.post('/api/wms/principal-groups', payload);
}

export function updateWmsPrincipalGroup(id, payload) {
  return api.put(`/api/wms/principal-groups/${encodeURIComponent(id)}`, payload);
}

export function deleteWmsPrincipalGroup(id) {
  return api.delete(`/api/wms/principal-groups/${encodeURIComponent(id)}`);
}

export function getWmsNextRackCode(params) {
  return api.get('/api/wms/racks/next-code', { params });
}

export function createWmsRack(payload) {
  return api.post('/api/wms/racks', payload);
}

export function updateWmsRack(id, payload) {
  return api.put(`/api/wms/racks/${encodeURIComponent(id)}`, payload);
}

export function deleteWmsRack(id, params) {
  return api.delete(`/api/wms/racks/${encodeURIComponent(id)}`, { params });
}

export function getWmsPallets(params) {
  return api.get('/api/wms/pallets', { params });
}

export function getWmsProductOptions(params) {
  return api.get('/api/wms/products/options', { params });
}

export function getWmsNextPalletCode(params) {
  return api.get('/api/wms/pallets/next-code', { params });
}

export function createWmsPallet(payload) {
  return api.post('/api/wms/pallets', payload);
}

export function updateWmsPallet(id, payload) {
  return api.put(`/api/wms/pallets/${encodeURIComponent(id)}`, payload);
}

export function deleteWmsPallet(id) {
  return api.delete(`/api/wms/pallets/${encodeURIComponent(id)}`);
}

export function getWmsPlacements(params, config = {}) {
  return api.get('/api/wms/placements', { ...config, params });
}

export function createWmsPlacement(payload) {
  return api.post('/api/wms/placements', payload);
}

export function updateWmsPlacement(id, payload) {
  return api.put(`/api/wms/placements/${encodeURIComponent(id)}`, payload);
}

export function deleteWmsPlacement(id) {
  return api.delete(`/api/wms/placements/${encodeURIComponent(id)}`);
}

export function getWmsTransactions(params) {
  return api.get('/api/transactions/transactions', { params });
}

export function getWmsReadyToLoad(params) {
  return api.get('/api/loading/loading/ready-to-load', { params });
}

export function getWmsCheckerPending(params) {
  return api.get('/api/checker/checker/pending', { params });
}

export function confirmWmsChecker(payload) {
  return api.post('/api/checker/checker/confirm', payload);
}

export function processWmsLoading(payload) {
  return api.post('/api/loading/loading/process', payload);
}

export function searchWmsManifest(params) {
  return api.get('/api/droping/droping/search-manifest', { params });
}

export function dropWmsManifestToQuarantine(payload) {
  return api.post('/api/droping/droping/drop-in-karantina', payload);
}

export function completeWmsDelivery(payload) {
  return api.post('/api/loading/loading/complete-delivery', payload);
}

export function getWmsQuarantineOpen(params) {
  return api.get('/api/quarantine/quarantine/open', { params });
}

export function processWmsQuarantineQc(payload) {
  return api.post('/api/quarantine/quarantine/qc', payload);
}

export function getWmsDistributionEvents(params) {
  return api.get('/api/distribution/events', { params });
}

export function getWmsTemporaryStocks(params) {
  return api.get('/api/transfer/transfer/temporary-stocks', { params });
}

export function confirmWmsTransfer(payload) {
  return api.post('/api/transfer/transfer/confirm', payload);
}

export function getWmsLowStockAlerts(params) {
  return api.get('/api/transfer/transfer/alerts/low-stock', { params });
}

export function getWmsIncomingNoteDetails(params, legacyParams) {
  // Keep the long-standing exact-note contract for callers that need the
  // document/task object.  The new searchable, paged list uses an object.
  if (typeof params === 'string' && params.trim()) {
    return api.get(`/api/incoming/incoming/note-details/${encodeURIComponent(params.trim())}`);
  }
  const query = params && typeof params === 'object' ? params : legacyParams;
  return api.get('/api/incoming/incoming/note-details', { params: query });
}

export function processWmsIncomingPallet(payload) {
  return api.post('/api/incoming/incoming/process-single-pallet', payload);
}

export function getWmsPickingDraftDetail(nota, params) {
  if (!String(nota || '').trim()) {
    return api.get('/api/picking/picking/draft-detail', { params });
  }
  return api.get(`/api/picking/picking/draft-detail/${encodeURIComponent(nota)}`);
}

export function scanWmsPickingRack(payload) {
  return api.post('/api/picking/picking/scan-rak', payload);
}

export function finalizeWmsPicking(payload) {
  return api.post('/api/picking/picking/finalize', payload);
}
export function getPickingIncidents() {
  return api.get('/api/picking/incidents');
}

export function resolvePickingIncident(id, note) {
  return api.post(`/api/picking/incidents/${id}/resolve`, { note });
}
