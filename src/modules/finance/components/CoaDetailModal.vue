<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { getCoaActivity, getCoaCashAccounts, linkCoaCashAccount, unlinkCoaCashAccount } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError } from '@/utils/api';
import { toLocalDateInputValue, firstLocalDayOfMonth } from '@/utils/date';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';

const props = defineProps({ account: { type: Object, default: null }, branches: { type: Array, default: () => [] }, initialDate: { type: String, default: '' }, initialBranch: { type: String, default: '' } });
const emit = defineEmits(['close', 'edit']);
const auth = useAuthStore();
const canEdit = computed(() => ['finance.coa.update', 'finance.accounting-config.update', 'm.finance.ca.update'].some(key => auth.hasPermission(key)));
const tab = ref('journal'), error = ref(''), feedback = ref(''), busy = ref(false), saving = ref(false);
const journal = ref(null), cash = ref(null), bankId = ref('');
const filters = reactive({ from: '', to: '', branch: '', children: false, page: 1 });
const limit = 25;
let sequence = 0;
const money = value => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 2 }).format(Number(value || 0));
const date = value => value ? new Date(value).toLocaleDateString('id-ID') : '-';
const total = computed(() => Number(tab.value === 'journal' ? journal.value?.summary?.total : cash.value?.total) || 0);
const linked = computed(() => (cash.value?.accounts || []).filter(row => String(row.id_coa) === String(props.account?.id_coa)));
const bankOptions = computed(() => (cash.value?.accounts || []).filter(row => !row.id_coa && row.is_aktif).map(row => ({ value: String(row.id_rekening_perusahaan), label: `${row.nama_bank} · ${row.nomor_rekening} · ${row.nama_cabang || '-'}` })));
const branchOptions = computed(() => {
  const ids = String(props.account?.id_cabang_list || '').split(',').map(value => value.trim()).filter(Boolean);
  return props.branches.filter(row => !ids.length || ids.includes(String(row.value)));
});
const journalColumns = [
  { key: 'tanggal', label: 'Tanggal', render: row => date(row.tanggal) }, { key: 'kode_jurnal', label: 'No. Jurnal' },
  { key: 'nomor_akun', label: 'Kode Akun' }, { key: 'nama_akun', label: 'Akun' }, { key: 'nama_cabang', label: 'Cabang' },
  { key: 'keterangan', label: 'Keterangan' }, { key: 'debit', label: 'Debit', render: row => money(row.debit) }, { key: 'kredit', label: 'Kredit', render: row => money(row.kredit) }
];
const cashColumns = [
  { key: 'tanggal_mutasi', label: 'Tanggal', render: row => date(row.tanggal_mutasi) }, { key: 'kode_mutasi', label: 'No. Mutasi' },
  { key: 'rekening', label: 'Rekening', render: row => `${row.nama_bank} · ${row.nomor_rekening}` },
  { key: 'tipe', label: 'Tipe Bank', render: row => Number(row.tipe) === 1 ? 'CR' : Number(row.tipe) === 2 ? 'DB' : '-' },
  { key: 'nominal_mutasi', label: 'Nominal', render: row => money(row.nominal_mutasi) },
  { key: 'sisa', label: 'Sisa Belum Dialokasikan', render: row => row.sisa == null ? '-' : money(row.sisa) }, { key: 'keterangan', label: 'Keterangan' }
];

async function load(page = 1) {
  const id = props.account?.id_coa;
  if (!id) return;
  const current = ++sequence, requestedTab = tab.value;
  error.value = ''; filters.page = page; busy.value = true;
  if (requestedTab === 'journal') journal.value = null; else cash.value = null;
  try {
    if (!filters.from || !filters.to || filters.from > filters.to) throw new Error('Lengkapi periode tanggal dengan urutan yang benar.');
    const params = { periode_awal: filters.from, periode_akhir: filters.to, page, limit };
    const response = requestedTab === 'journal'
      ? await getCoaActivity(id, { ...params, id_cabang: filters.branch || undefined, include_children: filters.children })
      : await getCoaCashAccounts(id, params);
    if (current !== sequence) return;
    if (requestedTab === 'journal') journal.value = response.data;
    else cash.value = response.data;
  } catch (reason) { if (current === sequence) error.value = normalizeError(reason); }
  finally { if (current === sequence) busy.value = false; }
}

function selectTab(value) {
  if (saving.value || tab.value === value) return;
  tab.value = value; feedback.value = ''; bankId.value = ''; load();
}

async function changeMapping(bank, unlink = false) {
  if (!canEdit.value || saving.value || !bank) return;
  if (unlink && !window.confirm('Lepaskan hubungan rekening ini dengan COA? Mutasi dan jurnal tidak dihapus.')) return;
  saving.value = true; error.value = ''; feedback.value = '';
  try {
    const response = await (unlink ? unlinkCoaCashAccount : linkCoaCashAccount)(props.account.id_coa, bank);
    bankId.value = ''; feedback.value = response.data?.message || 'Pemetaan tersimpan.';
    await load();
  } catch (reason) { error.value = normalizeError(reason); }
  finally { saving.value = false; }
}

watch(() => props.account?.id_coa, id => {
  sequence += 1; journal.value = null; cash.value = null; error.value = ''; feedback.value = ''; bankId.value = ''; tab.value = 'journal';
  if (!id) return;
  const end = props.initialDate || toLocalDateInputValue();
  filters.to = end; filters.from = toLocalDateInputValue(firstLocalDayOfMonth(new Date(`${end}T12:00:00`)));
  filters.branch = branchOptions.value.some(row => String(row.value) === props.initialBranch) ? props.initialBranch : '';
  filters.children = false; load();
}, { immediate: true });
</script>

<template>
  <AppModal :open="!!account" :title="`Detail COA · ${account?.nomor_akun || ''} — ${account?.nama_akun || ''}`" :description="`${account?.nama_perusahaan || ''} · ${account?.nama_kategori || ''}`" size="6xl" :hide-close="saving" :close-on-backdrop="!saving" @close="!saving && emit('close')">
    <div class="space-y-5">
      <div role="tablist" aria-label="Detail akun" class="flex gap-2 border-b border-slate-300/50">
        <button id="coa-journal-tab" role="tab" aria-controls="coa-journal-panel" :aria-selected="tab === 'journal'" :disabled="saving" :class="tab === 'journal' ? 'border-brand-600 text-brand-600' : 'border-transparent'" class="border-b-2 px-4 py-3 font-bold" @click="selectTab('journal')">Transaksi Jurnal</button>
        <button id="coa-cash-tab" role="tab" aria-controls="coa-cash-panel" :aria-selected="tab === 'cash'" :disabled="saving" :class="tab === 'cash' ? 'border-brand-600 text-brand-600' : 'border-transparent'" class="border-b-2 px-4 py-3 font-bold" @click="selectTab('cash')">Pemetaan Kas</button>
      </div>
      <form class="grid items-end gap-4 md:grid-cols-4" @submit.prevent="load()">
        <label class="field-label">Dari tanggal<input v-model="filters.from" type="date" class="field-control mt-1" :disabled="saving" required /></label>
        <label class="field-label">Sampai tanggal<input v-model="filters.to" type="date" class="field-control mt-1" :disabled="saving" required /></label>
        <AppSearchSelect v-if="tab === 'journal'" v-model="filters.branch" label="Cabang" :options="branchOptions" placeholder="Semua cabang yang diizinkan" />
        <button class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" :disabled="busy || saving">Tampilkan</button>
        <label v-if="tab === 'journal'" class="flex gap-2 text-sm md:col-span-4"><input v-model="filters.children" type="checkbox" /> Sertakan transaksi subakun</label>
      </form>
      <p v-if="feedback" role="status" class="rounded-xl bg-emerald-50 p-3 text-emerald-700">{{ feedback }}</p>
      <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-3 text-rose-700">{{ error }}</p>
      <section v-if="tab === 'journal'" id="coa-journal-panel" role="tabpanel" aria-labelledby="coa-journal-tab" class="space-y-4">
        <div v-if="journal && !busy" class="grid gap-4 md:grid-cols-2"><article class="rounded-xl bg-emerald-50 p-4 text-emerald-800"><p class="text-sm">Total Debit</p><strong class="text-xl">{{ money(journal.summary?.total_debit) }}</strong></article><article class="rounded-xl bg-rose-50 p-4 text-rose-800"><p class="text-sm">Total Kredit</p><strong class="text-xl">{{ money(journal.summary?.total_kredit) }}</strong></article></div>
        <AppTable :columns="journalColumns" :rows="journal?.data || []" :loading="busy" :paginated="false" row-key="id_jurnal_detail" empty-message="Tidak ada transaksi jurnal pada periode dan cakupan akun ini." />
      </section>
      <section v-else id="coa-cash-panel" role="tabpanel" aria-labelledby="coa-cash-tab" class="space-y-4">
        <p class="rounded-xl bg-sky-50 p-3 text-sm text-sky-900">Hubungkan rekening kas/bank ke akun COA ini untuk meninjau mutasinya. Pemetaan rekening tidak mengalokasikan pembayaran, merekonsiliasi mutasi, atau membuat jurnal secara otomatis.</p>
        <div v-if="cash && !busy" class="space-y-3">
          <h4 class="font-bold">Rekening Terhubung</h4>
          <p v-if="!linked.length" class="text-sm text-slate-500">Belum ada rekening yang dipetakan ke akun ini.</p>
          <div v-for="bank in linked" :key="bank.id_rekening_perusahaan" class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-300/50 p-3"><div><strong>{{ bank.nama_bank }} · {{ bank.nomor_rekening }}</strong><p class="text-sm text-slate-500">{{ bank.nama_pemilik }} · {{ bank.nama_cabang }}{{ bank.is_aktif ? '' : ' · Nonaktif' }}</p></div><button v-if="canEdit" :disabled="saving" class="rounded-lg border border-rose-300 px-3 py-2 text-sm text-rose-700 disabled:opacity-50" @click="changeMapping(bank.id_rekening_perusahaan, true)">Lepaskan Pemetaan</button></div>
          <div v-if="canEdit" class="grid items-end gap-3 md:grid-cols-[1fr_auto]"><AppSearchSelect v-model="bankId" label="Rekening belum dipetakan" :options="bankOptions" :disabled="saving" placeholder="Pilih rekening perusahaan yang sama" empty-text="Tidak ada rekening aktif yang belum dipetakan dalam cakupan COA ini." /><button class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" :disabled="saving || !bankId || !account?.is_active" @click="changeMapping(bankId)">{{ saving ? 'Menyimpan…' : 'Hubungkan Rekening' }}</button></div>
        </div>
        <h4 class="font-bold">Mutasi Rekening pada Periode Terpilih</h4>
        <AppTable :columns="cashColumns" :rows="cash?.data || []" :loading="busy" :paginated="false" row-key="id_mutasi" empty-message="Tidak ada mutasi rekening terhubung pada periode ini." />
      </section>
      <div class="flex flex-wrap items-center justify-end gap-3 text-sm"><span>{{ total }} transaksi · Hal {{ filters.page }}</span><button :disabled="busy || saving || filters.page <= 1" class="rounded-lg border px-3 py-2 disabled:opacity-40" @click="load(filters.page - 1)">Sebelumnya</button><button :disabled="busy || saving || filters.page * limit >= total" class="rounded-lg border px-3 py-2 disabled:opacity-40" @click="load(filters.page + 1)">Berikutnya</button></div>
    </div>
    <template #footer><div class="flex justify-end gap-3"><button :disabled="saving" class="rounded-xl border px-4 py-3" @click="emit('close')">Tutup</button><button v-if="canEdit" :disabled="saving" class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white" @click="emit('edit', account)">Edit COA</button></div></template>
  </AppModal>
</template>
