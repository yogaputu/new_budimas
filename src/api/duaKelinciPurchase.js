import api from './axios';

const base = '/api/extra/data-import/dua-kelinci/purchase';
export const previewDkPurchase = (form) => api.post(`${base}/preview`, form);
export const listDkPurchase = (params) => api.get(`${base}/batches`, { params });
export const getDkPurchase = (id) => api.get(`${base}/batches/${id}`);
export const searchDkPurchaseProducts = (id, search = '') => api.get(`${base}/batches/${id}/products`, { params: { search } });
export const reviewDkPurchase = (id, body) => api.post(`${base}/batches/${id}/review`, body);
export const processDkPurchase = (id, body) => api.post(`${base}/batches/${id}/process`, body);
