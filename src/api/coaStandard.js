import api from './axios';
export const getStandardCategories = () => api.get('/api/coa-standard/categories');
export const readCoaXlsx = file => {
  const data = new FormData(); data.append('file', file);
  return api.post('/api/coa-standard/read-xlsx', data);
};
export const previewCoaStandard = payload => api.post('/api/coa-standard/preview', payload);
export const applyCoaStandard = payload => api.post('/api/coa-standard/apply', payload);
