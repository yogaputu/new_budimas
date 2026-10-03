<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getProfitLoss } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { firstLocalDayOfMonth, toLocalDateInputValue } from '@/utils/date';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID');
const today = new Date();
const defaultFrom = toLocalDateInputValue(firstLocalDayOfMonth(today));
const defaultTo = toLocalDateInputValue(today);

const filters = reactive({
  branchId: '',
  companyId: '',
  from: defaultFrom,
  to: defaultTo,
  hppMethod: 'journal'
});

const loading = reactive({
  refs: false,
  report: false
});

const branchRows = ref([]);
const companyRows = ref([]);
const sections = ref({
  pendapatan: [],
  hpp: [],
  beban: [],
  lainnya: []
});
const summary = ref({
  total_pendapatan: 0,
  total_hpp: 0,
  laba_kotor: 0,
  total_beban: 0,
  laba_bersih: 0,
  total_lainnya: 0
});
const feedback = ref('');
const errorMessage = ref('');
const reportMeta = ref({
  hppMethod: 'journal',
  hppSource: 'journal',
  warnings: []
});

const hppMethodOptions = [
  { value: 'journal', label: 'Jurnal / COA' },
  { value: 'moving_average', label: 'Moving Average' },
  { value: 'fifo', label: 'FIFO' }
];

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);
const hppMethodLabel = computed(() => {
  if (reportMeta.value.hppMethod === 'fifo') return 'FIFO';
  if (reportMeta.value.hppMethod === 'moving_average') return 'Moving Average';
  return 'Jurnal / COA';
});
const hppSourceLabel = computed(() => reportMeta.value.hppSource === 'inventory_ledger' ? 'Kartu Stok Bernilai' : 'Jurnal');
const isLedgerHpp = computed(() => reportMeta.value.hppSource === 'inventory_ledger');

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId)
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const reportSections = computed(() => [
  { key: 'pendapatan', title: 'Pendapatan / Penjualan', rows: sections.value.pendapatan || [], total: summary.value.total_pendapatan, totalLabel: 'Total Pendapatan' },
  { key: 'hpp', title: 'Harga Pokok Penjualan', rows: sections.value.hpp || [], total: summary.value.total_hpp, totalLabel: 'Total HPP' },
  { key: 'beban', title: 'Beban / Biaya Operasional', rows: sections.value.beban || [], total: summary.value.total_beban, totalLabel: 'Total Beban' },
  { key: 'lainnya', title: 'Akun Lainnya Belum Terklasifikasi', rows: sections.value.lainnya || [], total: summary.value.total_lainnya, totalLabel: 'Total Lainnya' }
]);

function formatCurrency(value) {
  const amount = Number(value || 0);
  const prefix = amount < 0 ? '-Rp ' : 'Rp ';
  return `${prefix}${numberFormatter.format(Math.abs(amount))}`;
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
      filters.companyId = String(fallbackCompanyId.value);
    }
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
    syncBranchFromCompany();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi filter laporan belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadReport() {
  loading.report = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getProfitLoss({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      periode_awal: filters.from,
      periode_akhir: filters.to,
      hpp_method: filters.hppMethod
    });
    const payload = unwrapResponse(response);
    const data = payload?.result || payload || {};

    sections.value = {
      pendapatan: normalizeList(data.sections?.pendapatan),
      hpp: normalizeList(data.sections?.hpp),
      beban: normalizeList(data.sections?.beban),
      lainnya: normalizeList(data.sections?.lainnya)
    };
    summary.value = {
      total_pendapatan: Number(data.summary?.total_pendapatan || 0),
      total_hpp: Number(data.summary?.total_hpp || 0),
      laba_kotor: Number(data.summary?.laba_kotor || 0),
      total_beban: Number(data.summary?.total_beban || 0),
      laba_bersih: Number(data.summary?.laba_bersih || 0),
      total_lainnya: Number(data.summary?.total_lainnya || 0)
    };
    reportMeta.value = {
      hppMethod: data.hpp_method || filters.hppMethod,
      hppSource: data.hpp_source || 'journal',
      warnings: normalizeList(data.warnings)
    };

    const rowCount = reportSections.value.reduce((acc, section) => acc + section.rows.length, 0);
    if (!rowCount) {
      feedback.value = 'Belum ada jurnal laba rugi untuk filter periode ini.';
    } else if (reportMeta.value.warnings.length) {
      const ledgerWarning = reportMeta.value.hppMethod !== 'journal' && reportMeta.value.hppSource !== 'inventory_ledger';
      feedback.value = ledgerWarning
        ? `Data Kartu Stok Bernilai belum lengkap, hasil HPP dapat berbeda dari jurnal. ${reportMeta.value.warnings.join(' ')}`
        : reportMeta.value.warnings.join(' ');
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Laporan laba rugi belum bisa dimuat.');
    sections.value = { pendapatan: [], hpp: [], beban: [], lainnya: [] };
    reportMeta.value = { hppMethod: filters.hppMethod, hppSource: 'journal', warnings: [] };
  } finally {
    loading.report = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    companyId: canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '',
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    from: defaultFrom,
    to: defaultTo,
    hppMethod: 'journal'
  });
  syncBranchFromCompany();
  loadReport();
}

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    syncBranchFromCompany();
  }
);

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

onMounted(async () => {
  await loadReferences();
  await loadReport();
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Laba Rugi"
      description="Ringkasan pendapatan, HPP, beban, dan laba bersih dengan pilihan metode HPP jurnal, FIFO, atau moving average."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1.1fr_1.1fr_0.9fr_0.9fr_1fr_auto_auto]">
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="canUseLoginScope && !!fallbackCompanyId"
          empty-text="Perusahaan belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!filters.companyId || (!canAccessAllBranches && !!fallbackBranchId)"
          empty-text="Pilih perusahaan terlebih dahulu."
        />
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Awal</span>
          <input v-model="filters.from" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode Akhir</span>
          <input v-model="filters.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Metode HPP</span>
          <select v-model="filters.hppMethod" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
            <option v-for="option in hppMethodOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" :disabled="loading.report" @click="loadReport">
          {{ loading.report ? 'Memuat...' : 'Muat Laporan' }}
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Pendapatan</p>
        <p class="mt-3 text-lg font-semibold text-emerald-700">{{ formatCurrency(summary.total_pendapatan) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">HPP</p>
        <p class="mt-3 text-lg font-semibold text-amber-700">{{ formatCurrency(summary.total_hpp) }}</p>
        <p class="mt-1 text-xs text-slate-500">
          {{ hppMethodLabel }} - {{ hppSourceLabel }}
        </p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Laba Kotor</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ formatCurrency(summary.laba_kotor) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Beban</p>
        <p class="mt-3 text-lg font-semibold text-rose-700">{{ formatCurrency(summary.total_beban) }}</p>
      </article>
      <article class="panel border-brand-200 bg-brand-50 p-5 dark:border-brand-500/30 dark:bg-brand-500/10">
        <p class="text-xs uppercase tracking-[0.25em] text-brand-700 dark:text-brand-200">Laba Bersih</p>
        <p class="mt-3 text-lg font-semibold text-brand-900 dark:text-brand-100">{{ formatCurrency(summary.laba_bersih) }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Detail Laba Rugi</h3>
          <p class="mt-1 text-sm text-slate-500">Akun diklasifikasikan otomatis dari kategori/nama COA. HPP dapat memakai jurnal, FIFO, atau moving average jika Kartu Stok Bernilai sudah tersedia.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            Metode HPP: {{ hppMethodLabel }}
          </span>
          <span class="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200">
            Sumber: {{ hppSourceLabel }}
          </span>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.report">
              <td colspan="4" class="px-4 py-10 text-center text-slate-500">Memuat laporan laba rugi...</td>
            </tr>
            <template v-else v-for="section in reportSections" :key="section.key">
              <tr class="bg-slate-100 dark:bg-slate-900">
                <td colspan="3" class="px-5 py-3 text-sm font-bold uppercase tracking-[0.18em] text-slate-700 dark:text-slate-200">
                  {{ section.title }}
                </td>
                <td class="px-5 py-3 text-right text-sm font-bold text-slate-900 dark:text-white">{{ formatCurrency(section.total) }}</td>
              </tr>
              <tr v-if="!section.rows.length">
                <td colspan="4" class="px-5 py-4 text-sm text-slate-400">Tidak ada akun pada bagian ini.</td>
              </tr>
              <template v-if="section.key === 'hpp' && isLedgerHpp">
                <tr v-if="section.rows.length" class="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/70">
                  <td class="px-5 py-2">Produk</td>
                  <td class="px-5 py-2">Cabang</td>
                  <td class="px-5 py-2 text-right">Qty Keluar</td>
                  <td class="px-5 py-2 text-right">Total HPP</td>
                </tr>
                <tr v-for="row in section.rows" :key="`${section.key}-${row.id_coa}`">
                  <td class="px-5 py-3">
                    <p class="font-medium text-slate-900 dark:text-white">{{ String(row.nama_akun || '-').split(' - ')[0] }}</p>
                    <p class="text-xs text-slate-500">{{ row.nomor_akun || 'HPP Ledger' }}</p>
                  </td>
                  <td class="px-5 py-3 text-slate-600 dark:text-slate-300">{{ String(row.nama_akun || '-').split(' - ').slice(1).join(' - ') || '-' }}</td>
                  <td class="px-5 py-3 text-right text-slate-500">{{ numberFormatter.format(Number(row.qty_keluar || 0)) }}</td>
                  <td class="px-5 py-3 text-right font-semibold text-slate-900 dark:text-white">{{ formatCurrency(row.amount) }}</td>
                </tr>
              </template>
              <template v-else>
                <tr v-for="row in section.rows" :key="`${section.key}-${row.id_coa}`">
                  <td class="w-44 px-5 py-3 text-slate-500">{{ row.nomor_akun || '-' }}</td>
                  <td class="px-5 py-3">
                    <p class="font-medium text-slate-900 dark:text-white">{{ row.nama_akun || '-' }}</p>
                    <p class="text-xs text-slate-500">{{ row.nama_kategori || 'Tanpa kategori' }}</p>
                  </td>
                  <td class="px-5 py-3 text-right text-slate-500">D {{ formatCurrency(row.debit) }} / K {{ formatCurrency(row.kredit) }}</td>
                  <td class="px-5 py-3 text-right font-semibold text-slate-900 dark:text-white">{{ formatCurrency(row.amount) }}</td>
                </tr>
              </template>
            </template>
            <tr class="bg-brand-50 dark:bg-brand-500/10">
              <td colspan="3" class="px-5 py-4 text-base font-bold text-brand-900 dark:text-brand-100">Laba Bersih</td>
              <td class="px-5 py-4 text-right text-base font-bold text-brand-900 dark:text-brand-100">{{ formatCurrency(summary.laba_bersih) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
