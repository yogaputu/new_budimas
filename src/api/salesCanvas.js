import api from './axios';

const BASE_URL = '/api/sales-canvas';

function withUser(params = {}, userId) {
  return {
    ...params,
    id: userId,
    id_user: userId
  };
}

export function getCanvasRequests(userId, params = {}) {
  return api.get(`${BASE_URL}/all-canvas-request`, {
    params: withUser(params, userId)
  });
}

export function getCanvasSalesList(params = {}) {
  return api.get(`${BASE_URL}/sales-list`, { params });
}

export function getCanvasCustomers(params = {}) {
  return api.get(`${BASE_URL}/customers`, { params });
}

export function getCanvasRequestDetail(userId, idCanvas, tanggalRequest, params = {}) {
  return api.get(`${BASE_URL}/detail-canvas-request`, {
    params: withUser({ ...params, id_canvas: idCanvas, tanggal_request: tanggalRequest }, userId)
  });
}

export function getCanvasRequestProducts(userId, params = {}) {
  return api.get(`${BASE_URL}/list-product-canvas`, {
    params: withUser(params, userId)
  });
}

export function createCanvasRequest(payload) {
  return api.post(`${BASE_URL}/create-canvas-request`, payload);
}

export function updateCanvasRequest(payload) {
  return api.post(`${BASE_URL}/edit-canvas-request`, payload);
}

export function confirmCanvasRequest(payload) {
  return api.post(`${BASE_URL}/confirm-edit-canvas-request`, payload);
}

/**
 * Reject a pending Canvas Request before it reserves or moves any warehouse
 * stock.  The server derives the approver from the bearer token; never trust
 * an approver id sent by the client.
 */
export function rejectCanvasRequest(payload) {
  return api.post(`${BASE_URL}/reject-canvas-request`, payload);
}

export function getCanvasOrders(userId, params = {}) {
  return api.get(`${BASE_URL}/all-canvas-order`, {
    params: withUser(params, userId)
  });
}

export function getCanvasOrderDetail(idCanvasOrder, params = {}) {
  return api.get(`${BASE_URL}/detail-canvas-order`, {
    params: { ...params, id_canvas_order: idCanvasOrder }
  });
}

export function getCanvasVoucherUsages(idCanvasOrder, params = {}) {
  return api.get(`${BASE_URL}/voucher-usages`, {
    params: { ...params, id_canvas_order: idCanvasOrder }
  });
}

export function getCanvasOrderProducts(userId, params = {}) {
  return api.get(`${BASE_URL}/list-order-canvas`, {
    params: withUser(params, userId)
  });
}

/**
 * Preview voucher Canvas from the same source of truth used when an order is
 * saved.  `list_items` intentionally travels as JSON because the endpoint is
 * read-only and must receive the exact UOM quantities currently entered.
 */
export function getCanvasEligibleVouchers(params = {}) {
  const { list_items, items_json, voucher_selections, voucherSelections, ...rest } = params || {};
  const encodedItems = typeof list_items === 'string'
    ? list_items
    : JSON.stringify(Array.isArray(list_items) ? list_items : items_json || []);
  const selections = voucher_selections ?? voucherSelections ?? [];
  const encodedSelections = typeof selections === 'string'
    ? selections
    : JSON.stringify(Array.isArray(selections) ? selections : []);

  return api.get(`${BASE_URL}/eligible-vouchers`, {
    params: {
      ...rest,
      list_items: encodedItems,
      items_json: encodedItems,
      voucher_selections: encodedSelections
    }
  });
}

export function createCanvasOrder(payload) {
  return api.post(`${BASE_URL}/create-canvas-order`, payload);
}

export function returnCanvasStock(payload) {
  return api.post(`${BASE_URL}/return-stock-canvas`, payload);
}

export function approveCanvasReturn(payload) {
  return api.post(`${BASE_URL}/return-stock-canvas/approve`, payload);
}

export function rejectCanvasReturn(payload) {
  return api.post(`${BASE_URL}/return-stock-canvas/reject`, payload);
}

export function getCanvasReturnHistory(userId, params = {}) {
  return api.get(`${BASE_URL}/return-stock-canvas/history`, {
    params: withUser(params, userId)
  });
}

export function getCanvasPaymentHistory(idCanvasOrder, params = {}) {
  return api.get(`${BASE_URL}/tagihan-pembayaran`, {
    params: { ...params, id_canvas_order: idCanvasOrder }
  });
}

export function getCanvasPaymentRecap(userId, params = {}) {
  return api.get(`${BASE_URL}/riwayat-pembayaran`, {
    params: withUser(params, userId)
  });
}

export function submitCanvasPayment(payload) {
  return api.post(`${BASE_URL}/submit-tagihan-pembayaran`, payload);
}
