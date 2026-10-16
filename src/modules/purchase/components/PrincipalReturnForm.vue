<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, reactive, ref, watch, onMounted } from 'vue';
import { getCompanies,getBranches,getPrincipals } from '@/api/master';
import { principalClaims as api,claimMethod,rupiah } from '@/api/principalClaims';
import { normalizeError,normalizeList,unwrapResponse } from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
const emit=defineEmits(['saved','close']);
const masters=ref([[],[],[]]),sources=ref([]),lots=ref([]),selected=ref(null),lines=ref([]),busy=ref(false),error=ref(''),more=ref(false);
const filters=reactive({id_perusahaan:'',id_cabang:'',id_principal:'',search:''});
const form=reactive({client_key:crypto.randomUUID(),kind:'RETURN',requested_method:'CREDIT',note:''});
const options=computed(()=>masters.value.map(rows=>rows.map(r=>({value:String(r.id),label:`${r.kode||''} ${r.nama}`}))));
const total=computed(()=>lines.value.reduce((sum,r)=>sum+Number(r.qty_pcs)*Number(r.unit_cost),0));
async function run(fn){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
function find(){run(async()=>{selected.value=null;lots.value=[];const result=await api.returnSources(filters);sources.value=result.rows;more.value=result.has_more;});}
function choose(r){run(async()=>{const result=await api.returnLots(r.id);selected.value=result.receipt;lots.value=result.rows.map(l=>({...l,qty_pcs:0}));});}
function addLots(){
  for(const l of lots.value.filter(r=>Number(r.qty_pcs)>0)){
    if(lines.value.some(r=>r.stock_kind===l.stock_kind&&r.stock_id===l.stock_id)){error.value='Lot ini sudah dipilih. Hapus baris lama untuk mengganti jumlah.';return;}
    if(l.qty_pcs>l.available_qty || !Number.isInteger(Number(l.qty_pcs))){error.value='Jumlah harus PCS bulat dan tidak melebihi sisa lot.';return;}
    if(form.kind==='DESTRUCTION'&&l.stock_kind!=='QC_BAD'){error.value='Pemusnahan hanya untuk hasil QC BAD.';return;}
  }
  lines.value.push(...lots.value.filter(r=>Number(r.qty_pcs)>0).map(l=>({...l,receipt_ledger_id:selected.value.id,unit_cost:selected.value.unit_cost,kode_sku:selected.value.kode_sku,product_name:selected.value.product_name,purchase_order_id:selected.value.purchase_order_id})));
  selected.value=null;lots.value=[];
}
function submit(){run(async()=>{const result=await api.submitReturn({...form,lines:lines.value.map(({receipt_ledger_id,stock_kind,stock_id,qty_pcs})=>({receipt_ledger_id,stock_kind,stock_id,qty_pcs}))});emit('saved',result);});}
watch(()=>JSON.stringify([form.kind,form.requested_method,form.note,lines.value]),()=>{form.client_key=crypto.randomUUID();});
watch(()=>JSON.stringify([filters.id_perusahaan,filters.id_cabang,filters.id_principal]),()=>{sources.value=[];selected.value=null;lots.value=[];lines.value=[];});
onMounted(()=>run(async()=>{masters.value=(await Promise.all([getCompanies(),getBranches(),getPrincipals()])).map(r=>normalizeList(unwrapResponse(r)));}));
</script>
<template>
  <section class="space-y-4 rounded-xl border border-slate-500/40 p-5 workflow-ui workflow-card">
    <div class="flex justify-between flex-wrap items-center gap-3"><h2 class="text-xl font-bold">Ajukan Retur PO / Pemusnahan</h2><button class="workflow-btn" :disabled="busy" @click="emit('close')">Tutup</button></div>
    <p class="text-sm">Nilai dihitung dari penerimaan PO asal, bukan harga jual. Pengajuan belum mengurangi stok. Setelah approval principal, catat pengiriman retur atau berita acara pemusnahan.</p>
    <p v-if="error" role="alert" class="text-red-500 workflow-notice workflow-notice-error">{{error}}</p>
    <fieldset :disabled="busy" class="space-y-4">
      <form class="grid gap-3 sm:grid-cols-3" @submit.prevent="find">
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="options[0]" />
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="options[1]" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="options[2]" />
        <label class="workflow-label">Cari SKU / produk / ID PO<input v-model="filters.search" class="field-control workflow-input"></label>
        <button class="workflow-btn" :disabled="!filters.id_perusahaan||!filters.id_cabang||!filters.id_principal">Cari Penerimaan PO</button>
      </form>
      <p v-if="more" class="text-amber-500">200 penerimaan pertama. Persempit pencarian jika belum ditemukan.</p>
      <div class="max-h-72 overflow-auto workflow-table-wrap"><table class="w-full text-left workflow-table"><thead><tr><th>PO / Penerimaan</th><th>Produk</th><th>Sisa PCS untuk retur</th><th></th></tr></thead><tbody><tr v-for="r in sources" :key="r.id"><td>#{{r.purchase_order_id}} / #{{r.purchase_transaksi_id}} · {{r.movement_date}}</td><td>{{r.kode_sku}} · {{r.product_name}}</td><td>{{r.available_qty}}</td><td><button class="workflow-btn" :disabled="Number(r.available_qty)<=0" @click="choose(r)">Pilih Lot</button></td></tr></tbody></table></div>
      <section v-if="selected" class="space-y-3 rounded-xl border p-3 workflow-inset">
        <h3>{{selected.kode_sku}} · Nilai PO {{rupiah(selected.unit_cost)}}/PCS</h3>
        <p v-if="!lots.length">Tidak ada lot rak/hasil QC BAD yang cocok dengan penerimaan PO ini.</p>
        <div v-for="l in lots" :key="l.stock_kind+l.stock_id" class="grid gap-3 sm:grid-cols-2"><p>{{l.kode_rak}} · {{l.stock_kind==='QC_BAD'?'BAD':'GOOD'}} · Batch {{l.batch_number||'—'}} · Exp {{l.expired_date||'—'}} · Sisa {{l.available_qty}} PCS</p><input v-model.number="l.qty_pcs" class="field-control workflow-input" aria-label="Jumlah retur PCS" type="number" min="0" :max="l.available_qty" step="1"></div>
        <button class="workflow-btn" @click="addLots">Tambahkan Lot</button>
      </section>
      <form class="space-y-4" @submit.prevent="submit">
        <div class="grid gap-4 sm:grid-cols-2"><label class="workflow-label">Jenis pengajuan<AppSelect2 aria-label="Jenis pengajuan" v-model="form.kind" ><option value="RETURN">Retur ke principal</option><option value="DESTRUCTION">Pemusnahan barang BAD</option></AppSelect2></label><label class="workflow-label">Penyelesaian yang diminta<AppSelect2 aria-label="Penyelesaian yang diminta" v-model="form.requested_method" ><option v-for="(label,key) in claimMethod" :key="key" :value="key">{{label}}</option></AppSelect2></label></div>
        <div v-for="(l,i) in lines" :key="l.stock_kind+l.stock_id" class="flex justify-between border-t py-2 flex-wrap items-center gap-3"><span>PO #{{l.purchase_order_id}} · {{l.kode_sku}} · {{l.kode_rak}} · {{l.qty_pcs}} PCS × {{rupiah(l.unit_cost)}}</span><button class="workflow-btn" type="button" @click="lines.splice(i,1)">Hapus</button></div>
        <p class="font-bold">Estimasi nilai pengajuan {{rupiah(total)}} · Total final dihitung server</p>
        <label class="workflow-label">Alasan retur / pemusnahan<textarea v-model="form.note" class="field-control workflow-input" required maxlength="2000" /></label>
        <button class="rounded-xl bg-blue-600 px-4 py-3 text-white workflow-btn workflow-btn-primary" :disabled="busy||!lines.length">Ajukan ke Principal</button>
      </form>
    </fieldset>
  </section>
</template>
