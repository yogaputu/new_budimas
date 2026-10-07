<script setup>
import { ref, watch } from 'vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { workflowPost } from '@/api/paymentWorkflow';
import { unwrapResponse, normalizeError } from '@/utils/api';
const props=defineProps({open:Boolean,form:Object,companies:Array,branches:Array});
const emit=defineEmits(['close','imported']);
const file=ref(null), preview=ref(null), busy=ref(false), error=ref('');
watch(()=>[props.open,props.form.id_perusahaan,props.form.id_cabang],()=>{preview.value=null;error.value='';if(!props.open)file.value=null;});
function choose(event){file.value=event.target.files?.[0] || null;preview.value=null;error.value='';}
async function upload(commit=false){
  busy.value=true;error.value='';
  try{
    const data=new FormData();data.append('file',file.value);data.append('id_perusahaan',props.form.id_perusahaan);data.append('id_cabang',props.form.id_cabang);
    if(commit)data.append('fingerprint',preview.value.fingerprint);
    const result=unwrapResponse(await workflowPost(`mutations/file/${commit?'import':'preview'}`,data));
    if(commit)emit('imported',result);else preview.value=result;
  }catch(e){error.value=normalizeError(e);if(!commit)preview.value=null;}
  finally{busy.value=false;}
}
function template(){
  const csv='\uFEFFtanggal,referensi,bank,nama_rekening,keterangan,debit,kredit\r\n2026-10-07,REF-CONTOH-001,BCA,PT Contoh,Penerimaan transfer contoh,150000,0\r\n';
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8;'})),a=document.createElement('a');
  a.href=url;a.download='template-mutasi-bank.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const money=v=>Number(v).toLocaleString('id-ID',{style:'currency',currency:'IDR'});
</script>
<template>
  <AppModal :open="open" title="Import Mutasi Bank CSV / XLSX" size="6xl" :hide-close="busy" :close-on-backdrop="!busy" @close="emit('close')">
    <fieldset :disabled="busy" class="space-y-4">
      <div class="grid gap-4 md:grid-cols-2"><AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companies"/><AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="branches"/></div>
      <p>Maksimal 500 baris, 5 MB, satu sheet. Gunakan kolom template; XLSX dapat dibuat dengan menyimpan template CSV sebagai Excel. Ganti data contoh dengan mutasi sebenarnya.</p>
      <button type="button" class="btn-secondary" @click="template">Unduh Template CSV</button>
      <label class="block">File CSV / XLSX<input :key="String(open)" type="file" accept=".csv,.xlsx" class="field-control" @change="choose"/></label>
      <button class="btn-secondary" :disabled="!file || !form.id_perusahaan || !form.id_cabang || busy" @click="upload(false)">Tinjau File</button>
      <template v-if="preview">
        <p>{{ preview.rows.length }} baris · {{ preview.skipped }} sudah diimpor (dilewati). Seluruh baris divalidasi sebelum disimpan. Hanya Debit menjadi sumber dana pembayaran.</p>
        <div class="max-h-80 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th>Baris</th><th>Tanggal</th><th>Referensi / Bank</th><th>Keterangan</th><th>Tipe</th><th>Nominal</th><th>Status</th></tr></thead><tbody><tr v-for="r in preview.rows" :key="r.row"><td>{{ r.row }}</td><td>{{ r.received_date }}</td><td>{{ r.reference }} · {{ r.bank }}</td><td>{{ r.description }}</td><td>{{ r.transaction_type }}</td><td>{{ money(r.amount) }}</td><td>{{ r.duplicate ? 'Sudah ada' : 'Baru' }}</td></tr></tbody></table></div>
        <button class="btn-primary" :disabled="busy || preview.skipped===preview.rows.length" @click="upload(true)">Simpan {{ preview.rows.length-preview.skipped }} Mutasi</button>
      </template>
      <p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
    </fieldset>
  </AppModal>
</template>
