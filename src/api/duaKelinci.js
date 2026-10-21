import api from './axios';

const base = '/api/extra/data-import/dua-kelinci';
export const previewDuaKelinci = (form) => api.post(`${base}/preview`, form);
export const getDuaKelinciBatch = (id) => api.get(`${base}/batches/${id}`);
export const revalidateDuaKelinci = (id) => api.post(`${base}/batches/${id}/revalidate`);
export const processDuaKelinci = (id) => api.post(`${base}/batches/${id}/process`);
export const searchDuaKelinciCustomers = (id, search = '') => api.get(`${base}/batches/${id}/customers`, { params: { search } });
export const mapDuaKelinciCustomer = (id, payload) => api.post(`${base}/batches/${id}/customer-mapping`, payload);
