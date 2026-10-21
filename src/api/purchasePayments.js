import api from './axios';
const root='/api/purchase/payment-requests';
const data=r=>r.data.data;
export const purchasePayments={
  options:payload=>api.post(`${root}/options`,payload).then(data),
  create:payload=>api.post(root,payload).then(data),
  find:no_tagihan=>api.get(`${root}/by-bill`,{params:{no_tagihan}}).then(data),
  outgoing:id=>api.get(`${root}/${id}/outgoing-options`).then(data),
  pay:(id,payload)=>api.post(`${root}/${id}/pay`,payload).then(data),
  cancel:(id,payload)=>api.post(`${root}/${id}/cancel`,payload).then(data)
};
