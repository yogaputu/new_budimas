<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getBalanceSheet } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { toLocalDateInputValue } from '@/utils/date';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const numberFormatter = new Intl.NumberFormat('id-ID');
const today = toLocalDateInputValue();

const filters = reactive({
  branchId: '',
  companyId: '',
  to: today
});

const loading = reactive({
  refs: false,
  report: false
});

const branchRows = ref([]);
const companyRows = ref([]);
const sections = ref({
  aset: [],
  kewajiban: [],
  ekuitas: [],
  lainnya: []
});
const summary = ref({
  total_aset: 0,
  total_kewajiban: 0,
  total_ekuitas_murni: 0,
  laba_berjalan: 0,
  total_ekuitas: 0,
  total_kewajiban_ekuitas: 0,
  selisih: 0,
  total_lainnya: 0
});
const feedback = ref('');
const errorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

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
  { key: 'aset', title: 'Aset', rows: sections.value.aset || [], total: summary.value.total_aset, totalLabel: 'Total Aset' },
  { key: 'kewajiban', title: 'Kewajiban', rows: sections.value.kewajiban || [], total: summary.value.total_kewajiban, totalLabel: 'Total Kewajiban' },
  { key: 'ekuitas', title: 'Ekuitas', rows: sections.value.ekuitas || [], total: summary.value.total_ekuitas, totalLabel: 'Total Ekuitas' },
  { key: 'lainnya', title: 'Akun Belum Terklasifikasi', rows: sections.value.lainnya || [], total: summary.value.total_lainnya, totalLabel: 'Total Lainnya' }
]);

const isBalanced = computed(() => Math.abs(Number(summary.value.selisih || 0)) < 1);

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
    errorMessage.value = normalizeError(error, 'Referensi filter neraca belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadReport() {
  loading.report = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getBalanceSheet({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      tanggal_akhir: filters.to
    });
    const payload = unwrapResponse(response);
    const data = payload?.result || payload || {};

    sections.value = {
      aset: normalizeList(data.sections?.aset),
      kewajiban: normalizeList(data.sections?.kewajiban),
      ekuitas: normalizeList(data.sections?.ekuitas),
      lainnya: normalizeList(data.sections?.lainnya)
    };
    summary.value = {
      total_aset: Number(data.summary?.total_aset || 0),
      total_kewajiban: Number(data.summary?.total_kewajiban || 0),
      total_ekuitas_murni: Number(data.summary?.total_ekuitas_murni || 0),
      laba_berjalan: Number(data.summary?.laba_berjalan || 0),
      total_ekuitas: Number(data.summary?.total_ekuitas || 0),
      total_kewajiban_ekuitas: Number(data.summary?.total_kewajiban_ekuitas || 0),
      selisih: Number(data.summary?.selisih || 0),
      total_lainnya: Number(data.summary?.total_lainnya || 0)
    };

    const rowCount = reportSections.value.reduce((acc, section) => acc + section.rows.length, 0);
    if (!rowCount) {
      feedback.value = 'Belum ada jurnal neraca untuk filter ini.';
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Laporan neraca belum bisa dimuat.');
    sections.value = { aset: [], kewajiban: [], ekuitas: [], lainnya: [] };
  } finally {
    loading.report = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    companyId: canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '',
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    to: today
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
      title="Neraca"
      description="Laporan posisi keuangan berdasarkan jurnal sampai tanggal tertentu, lengkap dengan validasi Aset = Kewajiban + Ekuitas."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1.1fr_1.1fr_0.9fr_auto_auto]">
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
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Sampai Tanggal</span>
          <input v-model="filters.to" type="date" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
        </label>
        <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" :disabled="loading.report" @click="loadReport">
          {{ loading.report ? 'Memuat...' : 'Muat Neraca' }}
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Aset</p>
        <p class="mt-3 text-lg font-semibold text-emerald-700">{{ formatCurrency(summary.total_aset) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Kewajiban</p>
        <p class="mt-3 text-lg font-semibold text-amber-700">{{ formatCurrency(summary.total_kewajiban) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Ekuitas</p>
        <p class="mt-3 text-lg font-semibold text-sky-700">{{ formatCurrency(summary.total_ekuitas) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Kewajiban + Ekuitas</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ formatCurrency(summary.total_kewajiban_ekuitas) }}</p>
      </article>
      <article :class="['panel p-5', isBalanced ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-500/30 dark:bg-emerald-500/10' : 'border-rose-200 bg-rose-50 dark:border-rose-500/30 dark:bg-rose-500/10']">
        <p :class="['text-xs uppercase tracking-[0.25em]', isBalanced ? 'text-emerald-700 dark:text-emerald-200' : 'text-rose-700 dark:text-rose-200']">Selisih</p>
        <p :class="['mt-3 text-lg font-semibold', isBalanced ? 'text-emerald-900 dark:text-emerald-100' : 'text-rose-900 dark:text-rose-100']">{{ formatCurrency(summary.selisih) }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
      {{ feedback }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel overflow-hidden">
      <div class="border-b border-slate-100 px-5 py-4 dark:border-slate-800">
        <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Detail Neraca</h3>
        <p class="mt-1 text-sm text-slate-500">Laba berjalan dihitung otomatis dari akun pendapatan dan beban yang belum ditutup ke ekuitas.</p>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.report">
              <td colspan="4" class="px-4 py-10 text-center text-slate-500">Memuat laporan neraca...</td>
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
              <tr v-for="row in section.rows" :key="`${section.key}-${row.id_coa}`" :class="row.is_virtual ? 'bg-brand-50/70 dark:bg-brand-500/10' : ''">
                <td class="w-44 px-5 py-3 text-slate-500">{{ row.nomor_akun || '-' }}</td>
                <td class="px-5 py-3">
                  <p class="font-medium text-slate-900 dark:text-white">{{ row.nama_akun || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ row.nama_kategori || 'Tanpa kategori' }}</p>
                </td>
                <td class="px-5 py-3 text-right text-slate-500">D {{ formatCurrency(row.debit) }} / K {{ formatCurrency(row.kredit) }}</td>
                <td class="px-5 py-3 text-right font-semibold text-slate-900 dark:text-white">{{ formatCurrency(row.amount) }}</td>
              </tr>
            </template>
            <tr class="bg-brand-50 dark:bg-brand-500/10">
              <td colspan="3" class="px-5 py-4 text-base font-bold text-brand-900 dark:text-brand-100">Total Kewajiban + Ekuitas</td>
              <td class="px-5 py-4 text-right text-base font-bold text-brand-900 dark:text-brand-100">{{ formatCurrency(summary.total_kewajiban_ekuitas) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
