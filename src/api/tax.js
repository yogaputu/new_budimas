import api from './axios';

export function getDraftTaxInvoices(params) {
  return api.get('/api/pajak/get-draf-list-faktur', { params });
}

export function getFinalTaxInvoices(params) {
  return api.get('/api/pajak/get-final-list-faktur', { params });
}

export function getDraftTaxInvoiceDetail(id) {
  return api.get(`/api/pajak/get-detail-draf-faktur/${id}`);
}

export function exportDraftTaxXml(ids) {
  return api.get('/api/pajak/export-xml-draf-pajak', {
    params: {
      id_faktur: ids.join(',')
    },
    responseType: 'blob'
  });
}

export function getTaxInvoicesByFile(noFakturArr) {
  return api.get('/api/pajak/get-faktur-by-file', {
    params: {
      no_faktur_arr: noFakturArr
    }
  });
}

export function addTaxData(payload) {
  return api.post('/api/pajak/add-data-to-pajak', payload);
}
