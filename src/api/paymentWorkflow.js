import api from './axios';
const base = '/api/finance/workflow';
export const workflowGet = (path, params) => api.get(`${base}/${path}`, { params });
export const workflowPost = (path, data = {}) => api.post(`${base}/${path}`, data);
export const workflowPut = (path, data) => api.put(`${base}/${path}`, data);
export const workflowDelete = path => api.delete(`${base}/${path}`);
export const mobileWorkflow = (method, path, data) => api.request({ method, url: `/api/mobile/workflow/${path}`, data });
