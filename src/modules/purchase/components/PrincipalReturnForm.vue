<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, reactive, ref, watch, onMounted } from 'vue';
import { getCompanies,getBranches,getPrincipals } from '@/api/master';
import { principalClaims as api,claimMethod,rupiah } from '@/api/principalClaims';
import { normalizeError,normalizeList,unwrapResponse } from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
const emit=defineEmits(['saved','close']);
const masters=ref([[],[],[]]),sources=ref([]),lots=ref([]),selected=ref(null),lines=ref([]),busy=ref(false),error=ref(''),more=ref(false),expanded=ref(null),searched=ref(false);
const filters=reactive({id_perusahaan:'',id_cabang:'',id_principal:'',search:''});
const form=reactive({client_key:crypto.randomUUID(),kind:'RETURN',requested_method:'CREDIT',note:''});
const options=computed(()=>masters.value.map(rows=>rows.map(r=>({value:String(r.id),label:`${r.kode||''} ${r.nama}`}))));
function lineAmount(r){const price=form.kind==='RETURN'?Number(r.pricelist_price)/Number(r.pricelist_factor):Number(r.unit_cost);
  const dpp=Math.round(Number(r.qty_pcs)*price*100)/100;
  return dpp+(form.kind==='RETURN'?Math.round(dpp*Number(r.tax_rate||0))/100:0);}
const total=computed(()=>lines.value.reduce((sum,r)=>sum+lineAmount(r),0));
async function run(fn){if(busy.value)return;busy.value=true;error.value='';try{await fn();}catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
function find(){run(async()=>{selected.value=null;lots.value=[];expanded.value=null;sources.value=[];searched.value=false;more.value=false;
  const result=await api.returnSources({...filters,group_by:'receipt'});sources.value=result.rows;more.value=result.has_more;searched.value=true;});}
const quantity=value=>new Intl.NumberFormat('id-ID',{maximumFractionDigits:4}).format(Number(value||0));
function sourceUom(r){const factor=Number(r.uom_factor);return factor>0?`${quantity(Number(r.qty)/factor)} ${r.uom_code||r.uom_name||'UOM'} × ${quantity(factor)} PCS`:'UOM asal tidak tersedia';}
function toggleReceipt(r){expanded.value=expanded.value===r.receipt_key?null:r.receipt_key;selected.value=null;lots.value=[];error.value='';}
function choose(r){run(async()=>{const result=await api.returnLots(r.id);selected.value=result.receipt;lots.value=result.rows.map(l=>({...l,qty_pcs:0}));});}
function addLots(){
  for(const l of lots.value.filter(r=>Number(r.qty_pcs)>0)){
    if(lines.value.some(r=>r.stock_kind===l.stock_kind&&r.stock_id===l.stock_id)){error.value='Lot ini sudah dipilih. Hapus baris lama untuk mengganti jumlah.';return;}
    if(l.qty_pcs>l.available_qty || !Number.isInteger(Number(l.qty_pcs))){error.value='Jumlah harus PCS bulat dan tidak melebihi sisa lot.';return;}
    if(form.kind==='DESTRUCTION'&&l.stock_kind!=='QC_BAD'){error.value='Pemusnahan hanya untuk hasil QC BAD.';return;}
  }
  lines.value.push(...lots.value.filter(r=>Number(r.qty_pcs)>0).map(l=>({...l,receipt_ledger_id:selected.value.id,unit_cost:selected.value.unit_cost,
    pricelist_price:selected.value.pricelist_price,pricelist_factor:selected.value.pricelist_factor,tax_rate:selected.value.tax_rate,
    kode_sku:selected.value.kode_sku,product_name:selected.value.product_name,purchase_order_id:selected.value.purchase_order_id})));
  selected.value=null;lots.value=[];
}
function submit(){run(async()=>{const result=await api.submitReturn({...form,lines:lines.value.map(({receipt_ledger_id,stock_kind,stock_id,qty_pcs})=>({receipt_ledger_id,stock_kind,stock_id,qty_pcs}))});emit('saved',result);});}
watch(()=>JSON.stringify([form.kind,form.requested_method,form.note,lines.value]),()=>{form.client_key=crypto.randomUUID();});
watch(()=>JSON.stringify([filters.id_perusahaan,filters.id_cabang,filters.id_principal]),()=>{sources.value=[];selected.value=null;lots.value=[];lines.value=[];expanded.value=null;searched.value=false;more.value=false;});
onMounted(()=>run(async()=>{masters.value=(await Promise.all([getCompanies(),getBranches(),getPrincipals()])).map(r=>normalizeList(unwrapResponse(r)));}));
</script>
<template>
  <section class="space-y-4 rounded-xl border border-slate-500/40 p-5 workflow-ui workflow-card">
    <div class="flex justify-between flex-wrap items-center gap-3"><h2 class="text-xl font-bold">Ajukan Retur PO / Pemusnahan</h2><button class="workflow-btn" :disabled="busy" @click="emit('close')">Tutup</button></div>
    <p class="text-sm">Retur dihitung dari harga pricelist DPP PO asal sebelum diskon + PPN. Jurnal Retur Beli / Persediaan / PPN dicatat saat pengajuan. Stok fisik berkurang saat pengiriman; jurnal Persediaan tidak diulang. Penolakan membalik jurnal, approval sebagian memerlukan akun kerugian Finance.</p>
    <p v-if="error" role="alert" class="text-red-500 workflow-notice workflow-notice-error">{{error}}</p>
    <fieldset :disabled="busy" class="space-y-4">
      <form class="grid gap-3 sm:grid-cols-3" @submit.prevent="find">
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="options[0]" />
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="options[1]" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="options[2]" />
        <label class="workflow-label">Cari nota / SKU / produk / ID PO<input v-model="filters.search" class="field-control workflow-input"></label>
        <button class="workflow-btn" :disabled="!filters.id_perusahaan||!filters.id_cabang||!filters.id_principal">Cari Penerimaan PO</button>
      </form>
      <p class="text-sm">Satu nota penerimaan ditampilkan satu baris. Buka rincian untuk memilih sumber UOM dan lot asal; penerimaan bertahap tetap terpisah.</p>
      <p v-if="more" class="text-amber-500">200 nota penerimaan pertama beserta seluruh rinciannya. Persempit pencarian jika belum ditemukan.</p>
      <div class="max-h-80 overflow-auto workflow-table-wrap"><table aria-label="Nota penerimaan PO" class="w-full text-left workflow-table"><thead><tr><th>Nota / PO</th><th>Produk</th><th>Total diterima</th><th>Sisa untuk retur</th><th></th></tr></thead><tbody>
        <tr v-for="r in sources" :key="r.receipt_key">
          <td><strong>{{r.receipt_number||`Penerimaan #${r.purchase_transaksi_id||'—'}`}}</strong><br><small>PO {{r.purchase_order_ids.map(id=>`#${id}`).join(', ')}} · {{r.movement_date||'—'}}</small></td>
          <td>{{r.product_count}} produk<br><small>{{r.source_count}} rincian UOM</small></td>
          <td>{{quantity(r.qty)}} PCS</td><td>{{quantity(r.available_qty)}} PCS</td>
          <td><button class="workflow-btn" :aria-expanded="expanded===r.receipt_key" aria-controls="return-receipt-details" @click="toggleReceipt(r)">{{expanded===r.receipt_key?'Tutup Rincian':'Lihat Rincian'}}</button></td>
        </tr>
        <tr v-if="!sources.length"><td colspan="5">{{searched?'Nota penerimaan tidak ditemukan pada filter ini.':'Pilih perusahaan, cabang, dan principal, lalu cari nota penerimaan.'}}</td></tr>
      </tbody></table></div>
      <template v-for="r in sources" :key="r.receipt_key">
        <section v-if="expanded===r.receipt_key" id="return-receipt-details" class="space-y-3 rounded-xl border p-3 workflow-inset" :aria-label="`Rincian ${r.receipt_number||r.purchase_transaksi_id}`">
          <div class="flex flex-wrap items-center justify-between gap-2"><h3 class="font-semibold">Rincian {{r.receipt_number||`Penerimaan #${r.purchase_transaksi_id||'—'}`}}</h3><span>{{quantity(r.qty)}} PCS · Sisa {{quantity(r.available_qty)}} PCS</span></div>
          <p class="text-sm">Seluruh rincian nota ditampilkan, termasuk produk lain bila pencarian memakai SKU. Jumlah retur tetap dalam PCS dan mengikuti sumber penerimaan yang dipilih.</p>
          <div class="grid gap-3 lg:grid-cols-2">
            <article v-for="item in r.items" :key="item.id" class="min-w-0 space-y-2 rounded-xl border p-3 workflow-card">
              <h4 class="font-semibold break-words">{{item.kode_sku}} · {{item.product_name}}</h4>
              <p>{{sourceUom(item)}} = <strong>{{quantity(item.qty)}} PCS</strong></p>
              <p class="text-sm">Batch {{item.batch_number||'—'}} · Exp {{item.expired_date||'—'}}</p>
              <div class="flex flex-wrap items-center justify-between gap-2"><span>Sisa {{quantity(item.available_qty)}} PCS</span><button class="workflow-btn" :aria-label="`Pilih lot ${item.kode_sku}, ${sourceUom(item)}, sumber ${item.id}`" :disabled="Number(item.available_qty)<=0" @click="choose(item)">Pilih Lot</button></div>
            </article>
          </div>
        </section>
      </template>
      <section v-if="selected" class="space-y-3 rounded-xl border p-3 workflow-inset">
        <h3>{{selected.kode_sku}} · DPP pricelist {{rupiah(selected.return_unit_dpp)}}/PCS · PPN {{selected.tax_rate}}%</h3>
        <p class="text-sm">Penerimaan #{{selected.purchase_transaksi_id}} · Sisa sumber {{quantity(selected.available_qty)}} PCS</p>
        <p v-if="!lots.length">Tidak ada lot rak/hasil QC BAD yang cocok dengan penerimaan PO ini.</p>
        <div v-for="l in lots" :key="l.stock_kind+l.stock_id" class="grid gap-3 sm:grid-cols-2"><p>{{l.kode_rak}} · {{l.stock_kind==='QC_BAD'?'BAD':'GOOD'}} · Batch {{l.batch_number||'—'}} · Exp {{l.expired_date||'—'}} · Sisa {{l.available_qty}} PCS</p><input v-model.number="l.qty_pcs" class="field-control workflow-input" aria-label="Jumlah retur PCS" type="number" min="0" :max="l.available_qty" step="1"></div>
        <button class="workflow-btn" @click="addLots">Tambahkan Lot</button>
      </section>
      <form class="space-y-4" @submit.prevent="submit">
        <div class="grid gap-4 sm:grid-cols-2"><label class="workflow-label">Jenis pengajuan<AppSelect2 aria-label="Jenis pengajuan" v-model="form.kind" ><option value="RETURN">Retur ke principal</option><option value="DESTRUCTION">Pemusnahan barang BAD</option></AppSelect2></label><label class="workflow-label">Penyelesaian yang diminta<AppSelect2 aria-label="Penyelesaian yang diminta" v-model="form.requested_method" ><option v-for="(label,key) in claimMethod" :key="key" :value="key">{{label}}</option></AppSelect2></label></div>
        <div v-for="(l,i) in lines" :key="l.stock_kind+l.stock_id" class="flex justify-between border-t py-2 flex-wrap items-center gap-3"><span>PO #{{l.purchase_order_id}} · {{l.kode_sku}} · {{l.kode_rak}} · {{l.qty_pcs}} PCS · {{rupiah(lineAmount(l))}}{{form.kind==='RETURN'?' (termasuk PPN)':''}}</span><button class="workflow-btn" type="button" @click="lines.splice(i,1)">Hapus</button></div>
        <p class="font-bold">Estimasi nilai pengajuan {{rupiah(total)}} · Total final dihitung server</p>
        <label class="workflow-label">Alasan retur / pemusnahan<textarea v-model="form.note" class="field-control workflow-input" required maxlength="2000" /></label>
        <button class="rounded-xl bg-blue-600 px-4 py-3 text-white workflow-btn workflow-btn-primary" :disabled="busy||!lines.length">Ajukan ke Principal</button>
      </form>
    </fieldset>
  </section>
</template>
