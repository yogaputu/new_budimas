<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getValuedStockCard } from '@/api/finance';
import { getBranches, getCompanies, getPrincipals, getProductOptions } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { firstLocalDayOfMonth, toLocalDateInputValue } from '@/utils/date';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Date();
const defaultFrom = toLocalDateInputValue(firstLocalDayOfMonth(today));
const defaultTo = toLocalDateInputValue(today);
const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  productId: '',
  source: '',
  hppMethod: 'fifo',
  from: defaultFrom,
  to: defaultTo
});

const loading = reactive({
  refs: false,
  rows: false
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const productRows = ref([]);
const rows = ref([]);
const warnings = ref([]);
const errorMessage = ref('');
const summary = ref({
  total_qty_masuk: 0,
  total_nilai_masuk: 0,
  total_qty_keluar: 0,
  total_hpp: 0,
  saldo_akhir_qty: 0,
  saldo_akhir_nilai: 0
});

const sourceOptions = [
  { value: '', label: 'Semua Sumber' },
  { value: 'purchase', label: 'Purchase' },
  { value: 'sales', label: 'Sales' },
  { value: 'stock_transfer', label: 'Stok Transfer' },
  { value: 'stock_opname', label: 'Stok Opname' },
  { value: 'retur', label: 'Ajukan Retur' },
  { value: 'sales_canvas', label: 'Sales Canvas' },
  { value: 'adjustment', label: 'Adjustment' }
];

const hppMethodOptions = [
  { value: 'fifo', label: 'FIFO' },
  { value: 'moving_average', label: 'Moving Average' }
];

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const hppMethodLabel = computed(() => (filters.hppMethod === 'moving_average' ? 'Moving Average' : 'FIFO'));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
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

const companyOptions = computed(() =>
  companyRows.value
    .filter((item) => !filters.branchId || companyIdsForBranch(filters.branchId).includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

const principalOptions = computed(() =>
  principalRows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || item.nama_principal || `Principal ${item.id}`
  }))
);

const productOptions = computed(() =>
  productRows.value
    .map((item) => {
      const id = item.id || item.id_produk;
      return {
        value: id ? String(id) : '',
        label: [item.kode_sku || item.kode, item.nama || item.nama_produk].filter(Boolean).join(' - ') || `Produk ${id || '-'}`
      };
    })
    .filter((item) => item.value)
);

const summaryCards = computed(() => [
  { label: 'Total Qty Masuk', value: formatNumber(summary.value.total_qty_masuk) },
  { label: 'Total Nilai Masuk', value: formatCurrency(summary.value.total_nilai_masuk) },
  { label: 'Total Qty Keluar', value: formatNumber(summary.value.total_qty_keluar) },
  { label: 'Total HPP', value: formatCurrency(summary.value.total_hpp) },
  { label: 'Saldo Akhir Qty', value: formatNumber(summary.value.saldo_akhir_qty) },
  { label: 'Saldo Akhir Nilai', value: formatCurrency(summary.value.saldo_akhir_nilai) }
]);

function formatNumber(value) {
  return numberFormatter.format(Number(value || 0));
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  const prefix = amount < 0 ? '-Rp ' : 'Rp ';
  return `${prefix}${numberFormatter.format(Math.abs(amount))}`;
}

function sourceLabel(value) {
  return sourceOptions.find((item) => item.value === value)?.label || 'Semua Sumber';
}

async function loadReferences() {
  loading.refs = true;
  errorMessage.value = '';
  try {
    const [branchResponse, companyResponse, principalResponse, productResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getProductOptions({ limit: 500 })
    ]);
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    principalRows.value = normalizeList(unwrapResponse(principalResponse));
    productRows.value = normalizeList(unwrapResponse(productResponse));

    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi filter Kartu Stok Bernilai belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.rows = true;
  errorMessage.value = '';
  warnings.value = [];
  try {
    const response = await getValuedStockCard({
      periode_awal: filters.from,
      periode_akhir: filters.to,
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      id_principal: filters.principalId || undefined,
      id_produk: filters.productId || undefined,
      source_module: filters.source || undefined,
      hpp_method: filters.hppMethod,
      limit: 1000
    });
    const payload = unwrapResponse(response);
    const data = payload?.result || payload || {};
    rows.value = normalizeList(data.rows);
    summary.value = {
      total_qty_masuk: Number(data.summary?.total_qty_masuk || 0),
      total_nilai_masuk: Number(data.summary?.total_nilai_masuk || 0),
      total_qty_keluar: Number(data.summary?.total_qty_keluar || 0),
      total_hpp: Number(data.summary?.total_hpp || 0),
      saldo_akhir_qty: Number(data.summary?.saldo_akhir_qty || 0),
      saldo_akhir_nilai: Number(data.summary?.saldo_akhir_nilai || 0)
    };
    warnings.value = normalizeList(data.warnings);
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Kartu Stok Bernilai belum bisa dimuat.');
  } finally {
    loading.rows = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    branchId: !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    companyId: '',
    principalId: '',
    productId: '',
    source: '',
    hppMethod: 'fifo',
    from: defaultFrom,
    to: defaultTo
  });
  loadRows();
}

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    filters.companyId = '';
  }
);

watch(
  () => filters.companyId,
  (value) => {
    if (value && filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(value))) {
      filters.companyId = '';
    }
  }
);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Kartu Stok Bernilai"
      description="Histori stok masuk dan keluar bernilai sebagai sumber HPP FIFO atau moving average."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[1fr_1fr_1fr_1fr_0.9fr_0.9fr_0.9fr_auto_auto]">
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
          empty-text="Daftar cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="!!filters.branchId && !companyOptions.length"
          empty-text="Perusahaan belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.principalId"
          label="Principal"
          placeholder="Pilih principal"
          :options="principalOptions"
          empty-text="Principal belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.productId"
          label="Produk"
          placeholder="Pilih produk"
          :options="productOptions"
          empty-text="Produk belum tersedia."
        />
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Metode HPP</span>
          <select v-model="filters.hppMethod" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
            <option v-for="option in hppMethodOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Sumber</span>
          <select v-model="filters.source" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
            <option v-for="option in sourceOptions" :key="option.value || 'all'" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Periode</span>
          <div class="grid grid-cols-2 gap-2">
            <input v-model="filters.from" type="date" class="min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
            <input v-model="filters.to" type="date" class="min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" />
          </div>
        </label>
        <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white disabled:opacity-60" :disabled="loading.rows" @click="loadRows">
          {{ loading.rows ? 'Memuat...' : 'Muat' }}
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
      <article v-for="card in summaryCards" :key="card.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.2em] text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ card.value }}</p>
      </article>
    </section>

    <section v-if="warnings.length" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
      {{ warnings.join(' ') }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel overflow-hidden">
      <div class="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Histori Mutasi Bernilai</h3>
          <p class="mt-1 text-sm text-slate-500">Saldo dihitung dari histori sebelum periode sampai tanggal akhir filter.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
            Metode HPP: {{ hppMethodLabel }}
          </span>
          <span class="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200">
            Sumber: {{ sourceLabel(filters.source) }}
          </span>
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-[1200px] divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead class="bg-slate-100 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-900">
            <tr>
              <th class="px-4 py-3 text-left">Tanggal</th>
              <th class="px-4 py-3 text-left">Cabang</th>
              <th class="px-4 py-3 text-left">Produk</th>
              <th class="px-4 py-3 text-left">Dokumen Sumber</th>
              <th class="px-4 py-3 text-right">Stok Masuk</th>
              <th class="px-4 py-3 text-right">Nilai Masuk</th>
              <th class="px-4 py-3 text-right">Stok Keluar</th>
              <th class="px-4 py-3 text-right">Nilai HPP Keluar</th>
              <th class="px-4 py-3 text-right">Saldo Qty</th>
              <th class="px-4 py-3 text-right">Saldo Nilai</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.rows">
              <td colspan="10" class="px-4 py-10 text-center text-slate-500">Memuat Kartu Stok Bernilai...</td>
            </tr>
            <tr v-else-if="!rows.length">
              <td colspan="10" class="px-4 py-10 text-center text-slate-500">Belum ada mutasi bernilai pada filter ini.</td>
            </tr>
            <template v-else>
              <tr v-for="row in rows" :key="row.id">
                <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.tanggal || '-' }}</td>
                <td class="px-4 py-3 text-slate-600 dark:text-slate-300">{{ row.cabang || '-' }}</td>
                <td class="px-4 py-3">
                  <p class="font-medium text-slate-900 dark:text-white">{{ row.produk || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ row.kode_sku || '-' }} · {{ row.principal || '-' }}</p>
                </td>
                <td class="px-4 py-3">
                  <p class="font-medium text-slate-900 dark:text-white">{{ row.dokumen_sumber || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ row.source_type || '-' }}</p>
                </td>
                <td class="px-4 py-3 text-right text-emerald-700">{{ formatNumber(row.stok_masuk) }}</td>
                <td class="px-4 py-3 text-right text-emerald-700">{{ formatCurrency(row.nilai_masuk) }}</td>
                <td class="px-4 py-3 text-right text-rose-700">{{ formatNumber(row.stok_keluar) }}</td>
                <td class="px-4 py-3 text-right text-rose-700">{{ formatCurrency(row.nilai_hpp_keluar) }}</td>
                <td class="px-4 py-3 text-right font-semibold text-slate-900 dark:text-white">{{ formatNumber(row.saldo_qty) }}</td>
                <td class="px-4 py-3 text-right font-semibold text-slate-900 dark:text-white">{{ formatCurrency(row.saldo_nilai) }}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>
