<script setup>
import { computed, ref, watch } from 'vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { workflowPost } from '@/api/paymentWorkflow';
import { unwrapResponse, normalizeError } from '@/utils/api';
import { normalizeList } from '@/utils/api';
import { getCompanyBankAccounts } from '@/api/finance';
const props=defineProps({open:Boolean,form:Object,companies:Array,branches:Array});
const emit=defineEmits(['close','imported']);
const file=ref(null), preview=ref(null), busy=ref(false), error=ref('');
const importFormat=ref('MANUAL'),bankAccount=ref(''),banks=ref([]),banksLoading=ref(false);
const pendingDate=ref(''),statementPeriod=ref(null);
const bankOptions=computed(()=>banks.value.map(b=>({value:String(b.id_rekening_perusahaan||b.id),label:`${b.nama_bank} · ${b.nomor_rekening}`})));
let bankVersion=0;
watch(()=>[props.open,props.form.id_perusahaan,props.form.id_cabang],async()=>{
  const version=++bankVersion;bankAccount.value='';banks.value=[];banksLoading.value=false;
  if(!props.open||!props.form.id_perusahaan||!props.form.id_cabang)return;
  banksLoading.value=true;
  try{const rows=normalizeList(unwrapResponse(await getCompanyBankAccounts({id_perusahaan:props.form.id_perusahaan,id_cabang:props.form.id_cabang})));
    if(version===bankVersion)banks.value=rows.filter(b=>String(b.id_perusahaan)===String(props.form.id_perusahaan)&&(!b.id_cabang||String(b.id_cabang)===String(props.form.id_cabang))&&b.is_aktif!==false);
  }catch(e){if(version===bankVersion)error.value=normalizeError(e);}finally{if(version===bankVersion)banksLoading.value=false;}
},{immediate:true});
watch(()=>[importFormat.value,bankAccount.value],()=>{preview.value=null;statementPeriod.value=null;pendingDate.value='';error.value='';});
watch(pendingDate,()=>{preview.value=null;error.value='';});
watch(()=>[props.open,props.form.id_perusahaan,props.form.id_cabang],()=>{preview.value=null;statementPeriod.value=null;pendingDate.value='';error.value='';if(!props.open)file.value=null;});
function choose(event){file.value=event.target.files?.[0] || null;preview.value=null;statementPeriod.value=null;pendingDate.value='';error.value='';}
async function upload(commit=false){
  busy.value=true;error.value='';
  try{
    const data=new FormData();data.append('file',file.value);data.append('id_perusahaan',props.form.id_perusahaan);data.append('id_cabang',props.form.id_cabang);
    data.append('import_format',importFormat.value);if(importFormat.value==='BCA')data.append('bank_account_id',bankAccount.value);
    if(importFormat.value==='BCA'&&pendingDate.value)data.append('pending_date',pendingDate.value);
    if(commit)data.append('fingerprint',preview.value.fingerprint);
    const result=unwrapResponse(await workflowPost(`mutations/file/${commit?'import':'preview'}`,data));
    if(commit)emit('imported',result);else {preview.value=result;statementPeriod.value=result.period||null;}
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
    <fieldset :disabled="busy" class="min-w-0 space-y-4">
      <div class="grid gap-4 md:grid-cols-2"><AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companies"/><AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="branches"/></div>
      <AppSearchSelect v-model="importFormat" label="Format import" :clearable="false" :clear-search-on-open="true" :options="[{value:'MANUAL',label:'Manual / Non-BCA (template CSV / XLSX)'},{value:'BCA',label:'BCA (CSV mutasi rekening asli)'}]"/>
      <p>Maksimal 500 transaksi, 5 MB. Tinjau arah dan nominal sebelum disimpan.</p>
      <template v-if="importFormat==='MANUAL'"><p>Gunakan kolom template. Debit = dana masuk, Kredit = dana keluar. Nama bank harus sesuai rekening perusahaan. XLSX menggunakan satu sheet.</p><button type="button" class="btn-secondary" @click="template">Unduh Template Manual / Non-BCA</button></template>
      <template v-else><AppSearchSelect v-model="bankAccount" label="Rekening perusahaan pada file BCA" :options="bankOptions" :loading="banksLoading" :clear-search-on-open="true" placeholder="Pilih rekening yang sama dengan file"/><p>Unggah CSV asli BCA tanpa menghapus header atau ringkasan. CR = dana masuk, DB = dana keluar. Nomor rekening akan diperiksa.</p>
      </template>
      <label class="block">File CSV / XLSX<input :key="String(open)" type="file" :accept="importFormat==='BCA'?'.csv':'.csv,.xlsx'" class="field-control" @change="choose"/></label>
      <div v-if="importFormat==='BCA'" class="space-y-2">
        <label class="block">Tanggal pembukuan PEND (opsional)<input v-model="pendingDate" type="date" :min="statementPeriod?.start" :max="statementPeriod?.end" class="field-control"/></label>
        <p class="text-sm">Isi tanggal yang sudah Anda pastikan untuk menyertakan transaksi PEND. Jika kosong, PEND dilewati. Perubahan tanggal wajib ditinjau ulang sebelum disimpan.</p>
      </div>
      <button class="btn-secondary" :disabled="!file || !form.id_perusahaan || !form.id_cabang || busy || (importFormat==='BCA'&&!bankAccount)" @click="upload(false)">Tinjau File</button>
      <template v-if="preview">
        <p>{{ preview.rows.length }} baris bertanggal · {{ preview.skipped }} sudah diimpor (dilewati). Debit / dana masuk untuk penerimaan customer; Kredit / dana keluar untuk KU pembayaran PO.</p>
        <p v-if="preview.account_masked">Rekening {{preview.account_masked}} · Periode {{preview.period.start}} – {{preview.period.end}}</p>
        <p v-if="preview.totals">Dana masuk {{money(preview.totals.DEBIT)}} · Dana keluar {{money(preview.totals.CREDIT)}}</p>
        <div v-if="preview.setup && !preview.setup.ready" role="alert" class="workflow-notice workflow-notice-error space-y-2">
          <p>File berhasil dibaca. Pengaturan akun perusahaan/cabang ini belum siap untuk disimpan.</p>
          <ul class="list-disc pl-5"><li v-for="issue in preview.setup.issues" :key="issue.purpose">{{issue.message}}</li></ul>
          <p>Lengkapi akun pada <RouterLink class="underline" to="/finance/payment-workflow-settings">Pengaturan Workflow Pembayaran</RouterLink>, lalu kembali dan tinjau ulang file. Jangan memakai akun milik perusahaan lain.</p>
        </div>
        <p v-for="warning in preview.warnings" :key="warning" class="workflow-notice" role="status">{{warning}}</p>
        <p v-for="r in preview.pending" :key="r.row" class="text-sm">Baris {{r.row}} · {{r.reason}} · {{money(r.amount)}}</p>
        <button v-if="preview.pending?.length&&preview.period?.end" type="button" class="btn-secondary" @click="pendingDate=preview.period.end">Gunakan tanggal akhir periode {{preview.period.end}} untuk PEND</button>
        <div class="max-h-80 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th>Baris</th><th>Tanggal</th><th>Referensi / Bank</th><th>Keterangan</th><th>Tipe</th><th>Nominal</th><th>Status</th></tr></thead><tbody><tr v-for="r in preview.rows" :key="r.row"><td>{{ r.row }}</td><td>{{ r.received_date }}<span v-if="r.was_pending" class="block text-xs">Asal PEND · tanggal pilihan</span></td><td>{{ r.reference }} · {{ r.bank }}</td><td>{{ r.description }}</td><td>{{ r.transaction_type }}</td><td>{{ money(r.amount) }}</td><td>{{ r.duplicate ? 'Sudah ada' : 'Baru' }}</td></tr></tbody></table></div>
        <button class="btn-primary" :disabled="busy || preview.skipped===preview.rows.length || preview.setup?.ready===false" @click="upload(true)">Simpan {{ preview.rows.length-preview.skipped }} Mutasi</button>
      </template>
      <p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
    </fieldset>
  </AppModal>
</template>
