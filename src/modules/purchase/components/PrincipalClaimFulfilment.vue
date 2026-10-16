<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, reactive, ref, watch } from 'vue';
import { principalClaims as api, rupiah } from '@/api/principalClaims';
import { getCoaCatalog } from '@/api/finance';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
const props=defineProps({claim:{type:Object,required:true}}),emit=defineEmits(['updated']);
const auth=useAuthStore(),state=ref(null),accounts=ref([]),busy=ref(false),error=ref(''),success=ref('');
const allowed=computed(()=>auth.hasPermission('purchase.principal-claims.settle')||auth.hasPermission('m.purchase.kpr.approve'));
const options=computed(()=>accounts.value.map(a=>({value:String(a.id_coa),label:`${a.nomor_akun} — ${a.nama_akun}`})));
const form=reactive({client_key:'',received_date:'',reference:'',note:'',amount:'',destination_coa_id:'',recovery_coa_id:'',goods:[]});
let sequence=0;
async function load(){
  const current=++sequence;state.value=null;error.value='';busy.value=true;
  Object.assign(form,{client_key:crypto.randomUUID(),received_date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta'}).format(new Date()),reference:'',note:'',amount:'',destination_coa_id:'',recovery_coa_id:'',goods:[]});
  try {
    const [summary,coa]=await Promise.all([api.fulfilments(props.claim.id),getCoaCatalog({id_perusahaan:props.claim.id_perusahaan,id_cabang:props.claim.id_cabang,is_active:'true','no-paginate':'true'})]);
    if(current!==sequence)return;
    state.value=summary;accounts.value=normalizeList(unwrapResponse(coa));
    form.goods=summary.goods.filter(g=>Number(g.remaining_qty)>0).map(g=>({...g,claim_goods_id:g.id,qty_pcs:0,kode_rak:'',batch_number:'',expired_date:''}));
  }catch(e){if(current===sequence)error.value=normalizeError(e);}finally{if(current===sequence)busy.value=false;}
}
async function save(){
  if(busy.value)return;
  if(!window.confirm('Catat penerimaan yang benar-benar sudah diterima? Transaksi ini memposting jurnal dan, untuk barang, stok Titipan.'))return;
  busy.value=true;error.value='';success.value='';
  try{
    await api.receive(props.claim.id,{...form,goods:form.goods.filter(g=>Number(g.qty_pcs)>0).map(({claim_goods_id,qty_pcs,kode_rak,batch_number,expired_date})=>({claim_goods_id,qty_pcs,kode_rak,batch_number,expired_date}))});
    success.value='Penerimaan dan jurnal tersimpan.';emit('updated');
  }catch(e){error.value=normalizeError(e);}finally{busy.value=false;}
}
watch(()=>[props.claim.id,props.claim.status],load,{immediate:true});
</script>
<template>
  <section class="space-y-4 rounded-xl border border-slate-500/40 p-4 workflow-ui workflow-card">
    <div class="flex justify-between flex-wrap items-center gap-3"><h3 class="font-bold">Penerimaan {{claim.approved_method==='GOODS'?'Barang Pengganti':'Transfer Principal'}}</h3><button class="workflow-btn" :disabled="busy" @click="load">Muat ulang</button></div>
    <p v-if="error" role="alert" class="text-red-500 workflow-notice workflow-notice-error">{{error}}</p><p v-if="success" class="text-emerald-500">{{success}}</p>
    <p v-if="busy">Memproses…</p>
    <template v-if="state">
      <p class="font-semibold">Sisa yang belum diterima: {{rupiah(state.remaining)}}</p>
      <p v-for="row in state.history" :key="row.id" class="text-sm">{{row.received_date}} · {{row.reference}} · {{rupiah(row.amount)}} · Jurnal #{{row.id_jurnal}}</p>
      <form v-if="allowed && claim.status==='APPROVED'" class="space-y-4" @submit.prevent="save">
        <fieldset :disabled="busy" class="space-y-4">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="workflow-label">Tanggal penerimaan<input v-model="form.received_date" class="field-control workflow-input" type="date" required></label>
            <label class="workflow-label">Referensi bank / surat jalan<input v-model="form.reference" class="field-control workflow-input" maxlength="200" required></label>
            <AppSearchSelect v-model="form.destination_coa_id" :label="claim.approved_method==='GOODS'?'COA Persediaan (debit)':'COA Kas/Bank (debit)'" :options="options" />
            <AppSearchSelect v-model="form.recovery_coa_id" label="COA Pemulihan Klaim (kredit)" :options="options" />
          </div>
          <label class="workflow-label" v-if="claim.approved_method==='TRANSFER'">Nominal diterima<input v-model="form.amount" class="field-control workflow-input" type="number" min="0.01" step="0.01" :max="state.remaining" required></label>
          <template v-else>
            <p class="text-sm text-amber-500">Catat jumlah aktual. Barang masuk Titipan (belum ready), lalu lakukan penempatan di WMS. Isi 0 untuk barang yang belum diterima.</p>
            <div v-for="g in form.goods" :key="g.id" class="space-y-3 rounded-xl border border-slate-500/40 p-3 workflow-inset">
              <p>{{g.kode_sku}} — {{g.product_name}} · Sisa {{g.remaining_qty}} PCS · Nilai {{rupiah(g.unit_value)}}/PCS</p>
              <div class="grid gap-3 sm:grid-cols-4">
                <label class="workflow-label">Jumlah diterima (PCS)<input v-model.number="g.qty_pcs" class="field-control workflow-input" type="number" min="0" step="1" :max="g.remaining_qty"></label>
                <label class="workflow-label">Rak Titipan<AppSelect2 aria-label="Rak Titipan" v-model="g.kode_rak"  :required="g.qty_pcs>0"><option value="">Pilih rak</option><option v-for="r in state.racks" :key="r.kode_rak" :value="r.kode_rak">{{r.kode_rak}}</option></AppSelect2></label>
                <label class="workflow-label">Batch<input v-model="g.batch_number" class="field-control workflow-input" maxlength="80" :required="g.qty_pcs>0"></label>
                <label class="workflow-label">Expired (jika ada)<input v-model="g.expired_date" class="field-control workflow-input" type="date"></label>
              </div>
            </div>
          </template>
          <label class="workflow-label">Catatan<textarea v-model="form.note" class="field-control workflow-input" maxlength="2000" /></label>
          <button class="rounded-xl bg-blue-600 px-4 py-3 text-white disabled:opacity-50 workflow-btn workflow-btn-primary" :disabled="busy || !form.destination_coa_id || !form.recovery_coa_id">Catat Penerimaan &amp; Posting Jurnal</button>
        </fieldset>
      </form>
    </template>
  </section>
</template>
