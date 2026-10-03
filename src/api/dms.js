import api from './axios';

export function insertDmsImport(payload) {
  return api.post('/api/dms/insert-dms', payload);
}

export function previewDmsImport(formData) {
  return api.post('/api/dms/preview-dms', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  });
}
