<script setup>
import { ref, watch } from 'vue';
import { claimMethod, claimStatus, rupiah, principalClaims } from '@/api/principalClaims';
import { normalizeError } from '@/utils/api';
const props=defineProps({ claim: { type: Object, required: true }, showPayables: Boolean });
const bills=ref(null),busy=ref(false),error=ref('');
let sequence=0;
watch(()=>props.claim.id,()=>{sequence++;bills.value=null;error.value='';busy.value=false;});
async function loadBills() {
  const current=++sequence;busy.value=true;error.value='';
  try {const result=await principalClaims.payableBills(props.claim.id);if(current===sequence)bills.value=result;}
  catch(e){if(current===sequence)error.value=normalizeError(e);}
  finally{if(current===sequence)busy.value=false;}
}
</script>

<template>
  <section class="space-y-5 workflow-ui">
    <section v-if="showPayables && claim.status==='APPROVED' && claim.approved_method==='CREDIT'" class="space-y-3 rounded-xl border p-3 workflow-inset">
      <button type="button" class="rounded-lg border px-3 py-2 workflow-btn" :disabled="busy" @click="loadBills">{{busy ? 'Mencari tagihan…' : 'Cari tagihan PO yang sesuai'}}</button>
      <p v-if="error" role="alert" class="text-red-500 workflow-notice workflow-notice-error">{{error}}</p>
      <template v-if="bills">
        <p>Sisa potongan {{rupiah(bills.remaining)}}. {{bills.message}}</p>
        <p v-if="!bills.rows.length">Tidak ada tagihan PO yang siap dibayar untuk klaim ini. Saldo tidak hilang; tagihan yang sudah lunas tidak dapat dipotong kembali.</p>
        <div v-for="bill in bills.rows" :key="bill.id" class="border-t border-slate-200 pt-2">
          <RouterLink class="workflow-link underline" :to="{path:'/purchase/bills',query:{companyId:bill.id_perusahaan,principalId:bill.id_principal,branchId:bill.id_cabang,search:bill.no_tagihan}}">{{bill.no_tagihan}}</RouterLink>
          <p>{{bill.nama_cabang}} · Total {{rupiah(bill.total)}}</p>
        </div>
        <p v-if="bills.has_more">Menampilkan 100 tagihan pertama. Gunakan menu Tagihan Purchase untuk daftar lainnya.</p>
      </template>
    </section>
    <div class="grid gap-4 sm:grid-cols-3">
      <div class="workflow-inset"><small class="workflow-caption">Status</small><p class="mt-2 font-semibold">{{ claimStatus[claim.status] || claim.status }}</p></div>
      <div class="workflow-inset"><small class="workflow-caption">Diajukan</small><p class="mt-2 text-lg font-semibold tabular-nums">{{ rupiah(claim.requested_amount) }}</p><small class="workflow-caption">{{ claimMethod[claim.requested_method] }}</small></div>
      <div class="workflow-inset"><small class="workflow-caption">Disetujui</small><p class="mt-2 text-lg font-semibold tabular-nums">{{ rupiah(claim.approved_amount) }}</p><small class="workflow-caption">{{ claimMethod[claim.approved_method] || 'Belum ada keputusan' }}</small></div>
    </div>
    <p v-if="claim.status === 'APPROVED'" class="workflow-notice workflow-notice-warning">{{ claim.settlement_status === 'SEBAGIAN_DIPAKAI' ? 'Sebagian saldo klaim sudah dipakai.' : 'Approval bukan bukti pelunasan atau penerimaan stok.' }} {{ claim.approved_method === 'CREDIT' ? 'Gunakan saldo melalui pembayaran Tagihan Purchase Order.' : 'Catat penerimaan aktual melalui Klaim Principal. Barang pengganti masuk Titipan sebelum penempatan WMS.' }}</p>
    <section v-if="claim.approved_method === 'CREDIT' && claim.credit_remaining !== undefined"><h3 class="font-semibold">Sisa potongan: {{ rupiah(claim.credit_remaining) }}</h3><p v-for="(use, i) in claim.credit_uses" :key="i" class="mt-2 text-sm">{{ use.no_tagihan }} · {{ rupiah(use.amount) }} · {{ use.payment_date }} · Jurnal #{{ use.id_jurnal }}</p></section>
    <p>Catatan pengajuan: {{ claim.note || '—' }}</p>
    <p v-if="claim.decision_note">Keputusan principal: {{ claim.decision_note }} · Referensi {{ claim.approval_reference || '—' }}</p>
    <div v-if="claim.kind==='PROMO'" class="overflow-x-auto workflow-table-wrap"><table class="w-full text-left text-sm workflow-table">
      <thead><tr><th class="p-2">Promo</th><th class="p-2">Faktur</th><th class="p-2 text-right">Pemakaian</th></tr></thead>
      <tbody><tr v-for="line in claim.lines" :key="line.id" class="border-t border-slate-500/20"><td class="p-2">{{ line.snapshot.kode_promo }}<br><small>{{ line.snapshot.nama_promo }}</small></td><td class="p-2">{{ line.snapshot.no_faktur }}</td><td class="p-2 text-right">{{ rupiah(line.amount) }}</td></tr></tbody>
    </table></div>
    <div v-else class="overflow-x-auto workflow-table-wrap"><table class="w-full text-left text-sm workflow-table"><thead><tr><th>PO / Produk</th><th>Lot / Kondisi</th><th>Jumlah</th><th>Nilai PO</th></tr></thead><tbody><tr v-for="line in claim.lines" :key="line.id" class="border-t"><td>PO #{{line.snapshot.purchase_order_id}} · {{line.snapshot.kode_sku}}<br>{{line.snapshot.product_name}}</td><td>{{line.snapshot.batch_number||'—'}} · {{line.snapshot.expired_date||'—'}}<br>{{line.snapshot.stock_kind==='QC_BAD'?'BAD':'GOOD'}}</td><td>{{line.snapshot.qty_pcs}} PCS</td><td>{{rupiah(line.amount)}}</td></tr></tbody></table></div>
    <div v-if="claim.goods?.length"><h3 class="font-semibold">Barang pengganti yang disetujui</h3><p v-for="g in claim.goods" :key="g.id">{{ g.kode_sku }} · {{ g.product_name }} — {{ g.qty_pcs }} PCS × {{ rupiah(g.unit_value) }}</p></div>
    <details><summary class="cursor-pointer">Riwayat keputusan</summary><p v-for="(event, i) in claim.history" :key="i" class="mt-2 text-sm">{{ event.created_at }} · {{ event.actor_kind }} · {{ event.action }}<br>{{ event.details.note || '' }}</p></details>
  </section>
</template>
