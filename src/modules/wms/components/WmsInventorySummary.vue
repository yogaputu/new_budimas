<script setup>
import {computed,ref} from 'vue';
import AppTable from '@/shared/components/AppTable.vue';
import AppModal from '@/shared/components/AppModal.vue';
import {groupInventoryLots,inventoryPcs,inventoryUom,inventoryDate} from '../inventorySummary';
const props=defineProps({rows:{type:Array,default:()=>[]},loading:Boolean,lotColumns:{type:Array,default:()=>[]},emptyMessage:{type:String,default:'Belum ada stok inventory pada filter ini.'}});
const selected=ref(''),groups=computed(()=>groupInventoryLots(props.rows));
const detail=computed(()=>groups.value.find(g=>g.group_key===selected.value));
const number=value=>Number(value||0).toLocaleString('id-ID');
const columns=[
  {key:'product_code',label:'Kode Produk'}, {key:'product_name',label:'Produk'},
  {key:'nama_cabang',label:'Cabang',render:r=>r.nama_cabang||r.kode_cabang||`Cabang #${r.id_cabang??'—'}`},
  {key:'qty_pcs',label:'Total (PCS)',render:r=>number(r.qty_pcs)},
  {key:'uom_label',label:'Rincian UOM'}, {key:'location_count',label:'Jumlah Lokasi'},
  {key:'nearest_expiry',label:'Expired Terdekat',render:r=>r.nearest_expiry||'—'},
  {key:'detail',label:'Detail Lot'}
];
const detailColumns=computed(()=>[
  {key:'location',label:'Rak'}, {key:'shelf_type',label:'Tipe Rak'},
  {key:'batch_number',label:'Batch'}, {key:'expiry_date',label:'Expired',render:r=>inventoryDate(r.expiry_date)||'—'},
  {key:'qty_pcs',label:'Jumlah (PCS)',render:r=>number(inventoryPcs(r))},
  {key:'uom',label:'Rincian UOM',render:r=>inventoryUom(r)},
  ...props.lotColumns.filter(c=>['wms_ready_status','tanggal_masuk_gudang','umur_barang_hari','fifo_label','fefo_label','status'].includes(c.key))
]);
</script>
<template>
  <div class="space-y-3">
    <p class="text-sm text-slate-500 dark:text-slate-400">{{ groups.length }} produk/cabang · {{ rows.length }} lot. Ringkasan mengikuti filter; buka detail untuk melihat rak, batch, expired, dan urutan FIFO/FEFO.</p>
    <AppTable :rows="groups" :columns="columns" :loading="loading" row-key="group_key" clickable-rows :empty-message="emptyMessage" @row-click="selected=$event.group_key">
      <template #cell-detail="{row}"><button class="btn-secondary" :aria-label="`Lihat lot ${row.product_code} cabang ${row.id_cabang}`" @click.stop="selected=row.group_key">Lihat {{ row.lot_count }} lot</button></template>
    </AppTable>
    <AppModal :open="Boolean(detail)" :title="`Detail Lot ${detail?.product_code || ''}`" size="6xl" @close="selected=''">
      <div v-if="detail" class="space-y-4">
        <p><b>{{ detail.product_name }}</b> · {{ detail.nama_cabang || `Cabang #${detail.id_cabang}` }}</p>
        <p class="rounded-xl border border-slate-400/30 p-3"><b>{{ number(detail.qty_pcs) }} PCS</b> · {{ detail.uom_label }} · {{ detail.location_count }} lokasi · {{ detail.lot_count }} lot</p>
        <p class="text-sm text-slate-500 dark:text-slate-400">Lot tetap terpisah meskipun produknya sama. Picking mengikuti FEFO; biaya/jurnal memakai FIFO. Tampilan ini tidak memindahkan atau menggabungkan stok.</p>
        <AppTable :rows="detail.lots" :columns="detailColumns" row-key="lot_key"/>
      </div>
    </AppModal>
  </div>
</template>
