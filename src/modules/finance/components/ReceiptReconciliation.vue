<script setup>
import { computed } from 'vue';
const props = defineProps({ value:{type:Object,default:null} });
const summary = computed(() => props.value?.summary);
const money = value => new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR'}).format(Number(value || 0));
const methods = { CASH:'Tunai', TRANSFER:'Non Tunai', GIRO:'Giro' };
</script>
<template>
  <section v-if="summary" class="space-y-4" aria-label="Rekonsiliasi tiga arah">
    <h3 class="text-lg font-semibold">Ringkasan & Rekonsiliasi Tiga Arah</h3>
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <div v-for="(label,key) in {remaining_before:'Sisa Piutang Sebelum',total_funds:'Total Dana Terpilih',paid:'Alokasi ke Faktur',remaining_after:'Sisa Piutang Sesudah',excess:'Kelebihan Dana'}" :key="key" class="rounded-xl border border-slate-400/30 p-3"><p class="text-sm">{{ label }}</p><b class="mt-1 block">{{ money(summary[key]) }}</b></div>
    </div>
    <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th class="p-2">Komponen</th><th class="p-2">Klaim Sales</th><th class="p-2">Dana Riil</th><th class="p-2">Selisih</th></tr></thead><tbody>
      <tr v-for="(label,key) in methods" :key="key" class="border-t border-slate-400/30"><td class="p-2">{{ label }}</td><td class="p-2">{{ money(summary.claims?.[key]) }}</td><td class="p-2">{{ money(summary.real?.[key]) }}</td><td class="p-2">{{ money(Number(summary.real?.[key] || 0)-Number(summary.claims?.[key] || 0)) }}</td></tr>
      <tr class="border-t border-slate-400/30 font-bold"><td class="p-2">Subtotal Dana Riil</td><td class="p-2">{{ money(summary.total_claim) }}</td><td class="p-2">{{ money(summary.total_real) }}</td><td class="p-2">{{ money(summary.difference) }}</td></tr>
      <tr><td class="p-2">Uang Muka / Retur / Biaya Lain</td><td class="p-2">—</td><td colspan="2" class="p-2">{{ money(summary.other?.ADVANCE) }} / {{ money(summary.other?.RETURN) }} / {{ money(summary.other?.FEE) }}</td></tr>
    </tbody></table></div>
    <div :class="summary.matched ? 'bg-emerald-50 text-emerald-900' : 'bg-amber-50 text-amber-900'" class="rounded-xl p-4" role="status"><b>{{ summary.matched ? 'SEIMBANG (COCOK)' : 'ADA SELISIH KLAIM — periksa setiap faktur sebelum finalisasi' }}</b><p>Kelebihan menjadi uang muka {{ money(summary.advance_excess) }} · biaya lain {{ money(summary.fee_excess) }}.</p><p class="mt-1 text-sm">Selisih klaim membandingkan dana riil dengan klaim sales, bukan kelebihan terhadap piutang. Uang muka hanya berasal dari dana yang melebihi sisa piutang per faktur dan baru tercatat di menu Uang Muka Customer setelah approval kuitansi.</p><p class="mt-1 text-sm">Tunai yang ditransfer Sales dapat menyebabkan perbedaan antar-metode. Cocokkan jumlah total dan sumber dana yang benar.</p></div>
    <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th class="p-2">Faktur / Customer</th><th class="p-2">Piutang Sebelum</th><th class="p-2">Klaim</th><th class="p-2">Dana Riil</th><th class="p-2">Selisih</th><th class="p-2">Alokasi</th><th class="p-2">Piutang Sesudah</th></tr></thead><tbody><tr v-for="i in value.invoices" :key="i.id_faktur" class="border-t border-slate-400/30"><td class="p-2"><b>{{ i.no_faktur }}</b><p>{{ i.nama_customer }}</p></td><td class="p-2">{{ money(i.remaining_before) }}</td><td class="p-2">{{ money(i.total_claim) }}</td><td class="p-2">{{ money(i.total_real) }}</td><td class="p-2" :class="Number(i.difference) ? 'text-amber-700' : ''">{{ money(i.difference) }}</td><td class="p-2">{{ money(i.paid) }}</td><td class="p-2">{{ money(i.remaining_after) }}</td></tr></tbody></table></div>
  </section>
  <p v-else class="rounded-xl bg-amber-50 p-3 text-amber-900">Dokumen lama belum memiliki snapshot rekonsiliasi. Periksa rincian alokasi dan saldo sebelum melanjutkan.</p>
</template>
