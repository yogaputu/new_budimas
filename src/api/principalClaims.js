import axios from 'axios';
import api from './axios';

const base = '/api/purchase/principal-claims';
const data = (response) => response.data.data;
export const principalClaims = {
  list: (params) => api.get(base, { params }).then(data),
  creditOptions: (no_tagihan) => api.get(`${base}/credit-options`, { params: { no_tagihan } }).then(data),
  payableBills: (id) => api.get(`${base}/${id}/payable-bills`).then(data),
  settle: (payload) => api.post(`${base}/settlements`, payload).then(data),
  settlementHistory: (no_tagihan) => api.get(`${base}/settlements`, { params: { no_tagihan } }).then(data),
  candidates: (params) => api.get(`${base}/candidates`, { params }).then(data),
  returnSources: (params) => api.get(`${base}/return-sources`, { params }).then(data),
  returnLots: (id) => api.get(`${base}/return-sources/${id}/lots`).then(data),
  submitReturn: (payload) => api.post(`${base}/returns`, payload).then(data),
  returnDetail: (id) => api.get(`${base}/returns/${id}`).then(data),
  dispatchReturn: (id,payload) => api.post(`${base}/returns/${id}/dispatch`, payload).then(data),
  returnProof: (id) => api.get(`${base}/returns/${id}/proof`, {responseType:'blob'}),
  submit: (payload) => api.post(base, payload).then(data),
  detail: (id) => api.get(`${base}/${id}`).then(data),
  fulfilments: (id) => api.get(`${base}/${id}/fulfilments`).then(data),
  receive: (id, payload) => api.post(`${base}/${id}/fulfilments`, payload).then(data),
  resubmit: (id, payload) => api.post(`${base}/${id}/resubmit`, payload).then(data),
  accounts: () => api.get(`${base}/accounts`).then(data),
  saveAccount: (payload, id) => (id ? api.put(`${base}/accounts/${id}`, payload) : api.post(`${base}/accounts`, payload)).then(data)
};

// A principal session must never replace or inherit an ERP session.
const portal = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL || '', timeout: 30000 });
const sessionKey = 'budimas.principal.portal.token';
portal.interceptors.request.use((config) => {
  const token = sessionStorage.getItem(sessionKey);
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});
export const principalPortal = {
  hasSession: () => !!sessionStorage.getItem(sessionKey),
  clearSession: () => sessionStorage.removeItem(sessionKey),
  async login(payload) {
    const result = data(await portal.post('/api/principal-portal/login', payload));
    sessionStorage.setItem(sessionKey, result.token);
    return result.user;
  },
  me: () => portal.get('/api/principal-portal/me').then(data),
  logout: () => portal.post('/api/principal-portal/logout').then(data),
  list: (params) => portal.get('/api/principal-portal/claims', { params }).then(data),
  detail: (id) => portal.get(`/api/principal-portal/claims/${id}`).then(data),
  products: () => portal.get('/api/principal-portal/products').then(data),
  decide: (id, payload) => portal.post(`/api/principal-portal/claims/${id}/decision`, payload).then(data)
};

export const claimStatus = { SUBMITTED: 'Menunggu principal', REVISION: 'Perlu revisi', APPROVED: 'Disetujui', REJECTED: 'Ditolak', SETTLED: 'Selesai' };
export const claimMethod = { CREDIT: 'Potongan tagihan', GOODS: 'Barang pengganti', TRANSFER: 'Transfer uang' };
export const rupiah = (value) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 2 }).format(Number(value || 0));
