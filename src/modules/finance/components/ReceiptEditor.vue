<script setup>
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import ReceiptReconciliation from './ReceiptReconciliation.vue';
import { allocationLimit, initialAllocationAmount, sourceMatchesInvoice } from '../receiptAllocation';
const props=defineProps({open:Boolean,busy:Boolean,form:Object,lp:Object,funds:Array,feeTypes:Array,lphs:Array,sales:Array,quote:Object,error:String});
defineEmits(['close','select-lph','preview','save']);
const names={CASH:'Tunai',TRANSFER:'Non Tunai',GIRO:'Giro',ADVANCE:'Uang Muka',RETURN:'Nota Retur'};
const money=v=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR'}).format(Number(v || 0));
const claims=i=>(props.lp?.claims || []).filter(c=>String(c.id_faktur)===String(i.id));
const max=(i,f)=>allocationLimit(i,f,props.form.invoices || [],props.funds || [],props.lp?.claims || []);
function unavailable(i,f) {
  if(f.approval!=='APPROVED') return 'Menunggu approval kasir';
  if(f.giro_status==='BOUNCED') return 'Giro ditolak';
  if(f.transaction_type==='CREDIT') return 'Mutasi dana keluar';
  if(!i.sources.some(a=>String(a.id_source)===String(f.id)) && max(i,f)<=0) return 'Sisa/batas klaim sudah dipakai';
  return '';
}
const sources=i=>(props.funds || []).filter(f=>sourceMatchesInvoice(f,i,props.lp));
function toggle(i,f,checked){
  if(!checked){i.sources=i.sources.filter(a=>String(a.id_source)!==String(f.id));return;}
  const amount=initialAllocationAmount(i,f,props.form.invoices || [],props.funds || [],props.lp?.claims || []);
  i.sources.push({id_source:f.id,amount:amount>0 ? String(amount) : ''});
}
const source=id=>props.funds?.find(f=>String(f.id)===String(id));
</script>
<template>
  <AppModal :open="open" title="Buat / Edit Kuitansi" size="6xl" :hide-close="busy" :close-on-backdrop="!busy" @close="$emit('close')">
    <div class="receipt-editor space-y-6">
      <h3 class="text-lg font-semibold">1. Informasi Kuitansi</h3>
      <fieldset :disabled="busy" class="grid gap-4 md:grid-cols-4">
        <label>Tanggal Pembayaran<input v-model="form.receipt_date" type="date" class="field-control"/></label>
        <label>No. Kuitansi<input v-model="form.number" :disabled="!!form.edit_id" class="field-control" maxlength="100" placeholder="Otomatis saat disimpan"/></label>
        <AppSearchSelect v-model="form.id_sales" label="Sales Penanggung Jawab" :options="sales || []" placeholder="Semua Sales" :disabled="!!form.edit_id"/>
        <AppSearchSelect v-model="form.id_lph" label="LPH Dikembalikan" :options="(lphs || []).map(l=>({value:String(l.id),label:`${l.kode_lph} — ${l.nama_sales}`}))" :disabled="!!form.edit_id" @update:model-value="$emit('select-lph')"/>
      </fieldset>
      <h3 class="text-lg font-semibold">2. Alokasi Pembayaran per Faktur</h3>
      <p class="text-sm">Pilih sumber dana lalu isi nominal yang dipakai pada setiap faktur. Satu setoran dapat dibagi ke beberapa faktur. Klaim Sales belum merupakan pembayaran final.</p>
      <p v-if="!lp" class="rounded-xl bg-slate-100 p-4 text-slate-700">Pilih LPH terlebih dahulu.</p>
      <article v-for="i in form.invoices || []" :key="i.id" class="rounded-xl border border-slate-400/30 p-4">
        <label class="flex items-center gap-3"><input v-model="i.selected" type="checkbox" :disabled="busy" :aria-label="`Pilih faktur ${i.no_faktur}`"/><span><b>{{ i.no_faktur }}</b> · {{ i.nama_customer }}<br/>Total {{ money(i.total) }} · Sisa Piutang {{ money(i.remaining) }}</span></label>
        <div v-if="i.selected" class="mt-4 grid gap-5 lg:grid-cols-2">
          <fieldset :disabled="busy" class="space-y-3"><legend class="font-semibold">Klaim Sales & Sumber Dana</legend>
            <div class="rounded-xl bg-blue-50 p-3 text-blue-950"><p v-for="c in claims(i)" :key="c.id">{{ names[c.method] }}: <b>{{ money(c.amount) }}</b><span v-if="c.giro_number"> · {{ c.giro_number }} · {{ c.bank }} · {{ c.due_date }}</span></p><p v-if="!claims(i).length">Belum ada klaim Sales pada faktur ini.</p></div>
            <label v-for="f in sources(i)" :key="f.id" class="flex gap-3 rounded-xl border border-slate-400/30 p-3"><input type="checkbox" :checked="i.sources.some(a=>String(a.id_source)===String(f.id))" :disabled="!!unavailable(i,f)" :aria-label="`${i.no_faktur} sumber ${f.reference}`" @change="toggle(i,f,$event.target.checked)"/><span><b>{{ names[f.kind] }} · {{ f.reference }}</b><br/>Sisa {{ money(f.remaining) }} · {{ f.bank || f.nama_customer || '' }}<br/><small v-if="f.due_date">Jatuh tempo {{ f.due_date }} · </small><small>{{ unavailable(i,f) || `Maks. ${money(max(i,f))}` }}</small></span></label>
            <p v-if="!sources(i).length">Belum ada sumber dana yang tersedia. Catat atau import setoran terlebih dahulu.</p>
          </fieldset>
          <fieldset :disabled="busy" class="space-y-4"><legend class="font-semibold">Nominal per Sumber Dana</legend>
            <label v-for="a in i.sources" :key="a.id_source" class="block">{{ source(a.id_source)?.reference }} — {{ names[source(a.id_source)?.kind] }}<input v-model="a.amount" type="number" min="0.01" step="0.01" :max="source(a.id_source) ? max(i,source(a.id_source)) : undefined" :aria-label="`${i.no_faktur} nominal ${source(a.id_source)?.reference}`" class="field-control"/><small>Nominal dapat diedit. Sisa dana yang tidak digunakan tetap tersedia.<template v-if="source(a.id_source)"> Maks. {{ money(max(i,source(a.id_source))) }}.</template></small></label>
            <div class="space-y-3 border-t border-slate-400/30 pt-3">
              <h4 class="font-semibold">Biaya Lain</h4>
              <div v-if="i.legacy_fee" class="space-y-2 rounded-xl bg-amber-50 p-3 text-amber-900">
                <p>Biaya dokumen lama tetap dipertahankan: {{ i.legacy_fee.name }} — {{ money(i.legacy_fee.amount) }}.</p>
                <p>Untuk menggunakan master biaya baru, hapus biaya lama ini lalu pilih penggantinya.</p>
                <button type="button" class="btn-secondary" @click="i.legacy_fee=null">Hapus Biaya Lama</button>
              </div>
              <div v-for="(fee,index) in i.fees" :key="index" class="grid gap-2 sm:grid-cols-[1fr_9rem_auto]">
                <label>Jenis biaya<select v-model="fee.id_fee_type" class="field-control"><option value="">Pilih biaya</option><option v-for="type in (feeTypes || []).filter(t=>t.is_active || String(t.id)===String(fee.id_fee_type))" :key="type.id" :value="type.id" :disabled="type.requires_approval || !type.is_active">{{ type.name }} — maks. {{ money(type.max_amount) }}{{ type.requires_approval ? ' (persetujuan khusus)' : !type.is_active ? ' (nonaktif)' : '' }}</option></select></label>
                <label>Nominal biaya<input v-model="fee.amount" type="number" min="0.01" step="0.01" class="field-control"/></label>
                <button type="button" class="btn-secondary self-end" @click="i.fees.splice(index,1)">Hapus</button>
              </div>
              <button type="button" class="btn-secondary" :disabled="!!i.legacy_fee" @click="i.fees.push({id_fee_type:'',amount:''})">Tambah Biaya</button>
            </div>
            <label class="block">Jika ada kelebihan<select v-model="i.excess_treatment" class="field-control"><option value="ADVANCE">Uang Muka Customer</option><option value="FEE">Biaya Lain</option></select></label>
          </fieldset>
        </div>
      </article>
      <button class="btn-secondary" :disabled="busy || !(form.invoices || []).some(i=>i.selected)" @click="$emit('preview')">Hitung & Tinjau Alokasi</button>
      <ReceiptReconciliation v-if="quote" :value="quote"/>
      <button v-if="quote" class="btn-primary" :disabled="busy" @click="$emit('save')">Simpan Draft</button>
      <p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
    </div>
  </AppModal>
</template>
<style scoped>
.receipt-editor .btn-secondary { color:inherit; }
.receipt-editor button:disabled { opacity:.5; cursor:not-allowed; }
</style>
