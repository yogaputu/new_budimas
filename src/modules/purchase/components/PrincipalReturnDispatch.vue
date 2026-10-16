<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { principalClaims as api,rupiah } from '@/api/principalClaims';
import { getCoaCatalog } from '@/api/finance';
import { normalizeError,normalizeList,unwrapResponse } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
const props=defineProps({claim:{type:Object,required:true}}),emit=defineEmits(['updated']);
const auth=useAuthStore(),detail=ref(null),accounts=ref([]),busy=ref(false),error=ref('');
const allowed=computed(()=>auth.hasPermission('purchase.principal-claims.approve')||auth.hasPermission('m.purchase.kpr.approve'));
const options=computed(()=>accounts.value.map(r=>({value:String(r.id_coa),label:`${r.nomor_akun} — ${r.nama_akun}`})));
const form=reactive({client_key:'',movement_date:'',reference:'',proof:null,inventory_coa_id:'',claim_coa_id:'',loss_coa_id:''});
let seq=0;
async function load(){const current=++seq;busy.value=true;error.value='';detail.value=null;
  Object.assign(form,{client_key:crypto.randomUUID(),movement_date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta'}).format(new Date()),reference:'',proof:null,inventory_coa_id:'',claim_coa_id:'',loss_coa_id:''});
  try{const [d,c]=await Promise.all([api.returnDetail(props.claim.id),getCoaCatalog({id_perusahaan:props.claim.id_perusahaan,id_cabang:props.claim.id_cabang,is_active:'true','no-paginate':'true'})]);if(current===seq){detail.value=d;accounts.value=normalizeList(unwrapResponse(c));}}
  catch(e){if(current===seq)error.value=normalizeError(e);}finally{if(current===seq)busy.value=false;}}
async function file(event){const value=event.target.files?.[0];form.proof=null;if(!value)return;if(value.size>5242880||!['application/pdf','image/png','image/jpeg'].includes(value.type)){error.value='Bukti PDF/PNG/JPEG maksimal 5 MB.';event.target.value='';return;}
  try{const result=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result);r.onerror=reject;r.readAsDataURL(value);});form.proof={name:value.name,base64:String(result).split(',')[1]};}catch{error.value='Gagal membaca bukti.';}}
async function save(){if(busy.value||!window.confirm('Pastikan barang sudah dikirim/dimusnahkan sesuai persetujuan. Konfirmasi ini mengurangi stok dan memposting jurnal.'))return;busy.value=true;error.value='';
  try{await api.dispatchReturn(props.claim.id,{...form});emit('updated');await load();}catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
async function download(){try{const result=await api.returnProof(props.claim.id);const url=URL.createObjectURL(result.data);const link=document.createElement('a');link.href=url;link.download=detail.value.dispatch.proof_name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){error.value=normalizeError(e);}}
watch(()=>props.claim.id,load,{immediate:true});
</script>
<template><section class="space-y-4 rounded-xl border border-slate-500/40 p-4 workflow-ui workflow-card">
  <h3 class="font-bold">{{claim.kind==='DESTRUCTION'?'Catat Pemusnahan Aktual':'Konfirmasi Pengiriman Retur'}}</h3>
  <p v-if="error" role="alert" class="text-red-500 workflow-notice workflow-notice-error">{{error}}</p>
  <p v-if="detail?.dispatch">Sudah dicatat {{detail.dispatch.movement_date}} · {{detail.dispatch.reference}} · Jurnal #{{detail.dispatch.id_jurnal}} · COA piutang klaim #{{detail.dispatch.claim_coa_id}}. Gunakan COA ini sebagai akun kredit pada penerimaan/potongan PO.</p>
  <button class="workflow-btn" v-if="detail?.dispatch?.proof_name" @click="download">Unduh {{detail.dispatch.proof_name}}</button>
  <form v-if="detail && !detail.dispatch && allowed && claim.status==='APPROVED'" class="space-y-4" @submit.prevent="save"><fieldset :disabled="busy" class="space-y-4">
    <p>Nilai persediaan {{rupiah(claim.requested_amount)}} · Disetujui {{rupiah(claim.approved_amount)}}. Stok berkurang satu kali setelah konfirmasi.</p>
    <div class="grid gap-4 sm:grid-cols-2">
      <label class="workflow-label">Tanggal aktual<input v-model="form.movement_date" class="field-control workflow-input" type="date" required></label><label class="workflow-label">Nomor surat jalan / berita acara<input v-model="form.reference" class="field-control workflow-input" maxlength="200" required></label>
      <AppSearchSelect v-model="form.inventory_coa_id" label="COA Persediaan (kredit)" :options="options" /><AppSearchSelect v-model="form.claim_coa_id" label="COA Piutang Klaim Principal (debit)" :options="options" />
      <AppSearchSelect v-if="Number(claim.requested_amount)>Number(claim.approved_amount)" v-model="form.loss_coa_id" label="COA Kerugian / Selisih Tidak Disetujui" :options="options" />
      <label class="workflow-label">Bukti PDF / PNG / JPEG, maksimal 5 MB<input :key="form.client_key" type="file" class="field-control" accept="application/pdf,image/png,image/jpeg" :required="claim.kind==='DESTRUCTION'" @change="file"></label>
    </div><button class="rounded-xl bg-blue-600 px-4 py-3 text-white workflow-btn workflow-btn-primary" :disabled="busy||!form.inventory_coa_id||!form.claim_coa_id">Konfirmasi Mutasi Stok &amp; Jurnal</button>
  </fieldset></form>
  <p v-else-if="detail && !detail.dispatch">Menunggu approval principal atau hak Approve untuk mencatat mutasi aktual.</p>
</section></template>
