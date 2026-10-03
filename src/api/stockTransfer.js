import api from './axios';

export function getStockTransfers(params) {
  return api.get('/api/stock-transfer/pengiriman-stock-transfer', { params });
}

export function createStockTransfer(payload) {
  return api.post('/api/stock-transfer/add-stock-transfer', payload);
}

export function getStockTransferDetail(params) {
  return api.get('/api/stock-transfer/detail-stock-transfer', { params });
}

export function confirmStockTransfer(payload) {
  return api.post('/api/stock-transfer/konfirmasi-stock-transfer', payload);
}

export function adminConfirmStockTransfer(payload) {
  return api.post('/api/stock-transfer/konfirmasi-admin-stock-transfer', payload);
}

export function receiveStockTransfer(payload) {
  return api.post('/api/stock-transfer/penerimaan-stock-transfer', payload);
}

export function rejectStockTransfer(payload) {
  return api.post('/api/stock-transfer/tolak-stock-transfer', payload);
}

export function closeEscalatedStockTransfer(payload) {
  return api.post('/api/stock-transfer/close-eskalasi-penerimaan-stock-transfer', payload);
}
