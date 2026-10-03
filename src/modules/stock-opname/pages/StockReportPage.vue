<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getStockReport } from '@/api/stockOpname';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { useAuthStore } from '@/stores/auth';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  search: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const stockRows = ref([]);
const loading = ref(false);
const errorMessage = ref('');
const feedback = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.companyId)
);

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth));

const principalOptions = computed(() =>
  principalRows.value
    .filter((item) => filters.companyId && String(item.id_perusahaan || item.company_id || '') === String(filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Principal'}`
    }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return stockRows.value.filter((item) => {
    const matchSearch =
      !query ||
      [item.kode_sku, item.nama_produk, item.nama_principal, item.nama_cabang, item.nama_perusahaan]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));

    return matchSearch;
  });
});

const summary = computed(() => {
  const rows = filteredRows.value;
  return {
    sku: rows.length,
    ready: rows.reduce((total, item) => total + Number(item.jumlah_ready || 0), 0),
    rackReady: rows.reduce((total, item) => total + Number(item.jumlah_rak_tetap || 0), 0),
    titipan: rows.reduce((total, item) => total + Number(item.jumlah_titipan || 0), 0),
    good: rows.reduce((total, item) => total + Number(item.jumlah_good || 0), 0),
    bad: rows.reduce((total, item) => total + Number(item.jumlah_bad || 0), 0),
    incoming: rows.reduce((total, item) => total + Number(item.jumlah_incoming || 0), 0)
  };
});

const columns = [
  { key: 'tanggal_update', label: 'Tanggal' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'kode_sku', label: 'Kode SKU' },
  { key: 'nama_produk', label: 'Produk' },
  { key: 'jumlah_ready', label: 'Ready' },
  { key: 'jumlah_rak_tetap', label: 'Rak Tetap (WMS)' },
  { key: 'selisih_rak_tetap', label: 'Selisih Rak' },
  { key: 'jumlah_titipan', label: 'Rak Titipan' },
  { key: 'jumlah_good', label: 'Good' },
  { key: 'jumlah_bad', label: 'Bad' },
  { key: 'jumlah_incoming', label: 'In Transit' },
  { key: 'uom', label: 'Satuan' }
];

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.principalId = '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
    filters.principalId = '';
  }
}

function syncPrincipalFromCompany() {
  if (filters.principalId && !principalOptions.value.some((item) => String(item.value) === String(filters.principalId))) {
    filters.principalId = '';
  }
}

async function loadMasterData() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branchRows.value = normalizeList(unwrapResponse(branchResponse));
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  principalRows.value = normalizeList(unwrapResponse(principalResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!canAccessAllBranches.value && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

async function loadReport() {
  errorMessage.value = '';
  feedback.value = '';
  loading.value = true;
  try {
    const response = await getStockReport({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      id_principal: filters.principalId || undefined,
      all_branches: canAccessAllBranches.value && !filters.branchId ? 'true' : undefined
    });
    stockRows.value = normalizeList(unwrapResponse(response));
    feedback.value = `Laporan stock berhasil dimuat: ${stockRows.value.length.toLocaleString('id-ID')} baris.`;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Laporan stock belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.principalId = '';
  filters.search = '';
  syncBranchFromCompany();
  loadReport();
}

function exportReport() {
  exportRowsToCsv(
    `laporan-stock-${toLocalDateInputValue()}.csv`,
    [
      { label: 'Tanggal', key: 'tanggal_update' },
      { label: 'Cabang', key: 'nama_cabang' },
      { label: 'Perusahaan', key: 'nama_perusahaan' },
      { label: 'Principal', key: 'nama_principal' },
      { label: 'Kode SKU', key: 'kode_sku' },
      { label: 'Produk', key: 'nama_produk' },
      { label: 'Ready', key: 'jumlah_ready' },
      { label: 'Rak Tetap (WMS)', key: 'jumlah_rak_tetap' },
      { label: 'Selisih Rak', key: 'selisih_rak_tetap' },
      { label: 'Rak Titipan', key: 'jumlah_titipan' },
      { label: 'Good', key: 'jumlah_good' },
      { label: 'Bad', key: 'jumlah_bad' },
      { label: 'Booked', key: 'jumlah_booked' },
      { label: 'Delivery', key: 'jumlah_delivery' },
      { label: 'Incoming', key: 'jumlah_incoming' },
      { label: 'Gudang', key: 'jumlah_gudang' },
      { label: 'Canvas', key: 'jumlah_canvas' },
      { label: 'Picked', key: 'jumlah_picked' },
      { label: 'Transfer Out', key: 'transfer_out' },
      { label: 'Transfer In', key: 'transfer_in' },
      { label: 'Satuan', key: 'uom' }
    ],
    filteredRows.value
  );
}

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (String(companyId || '') === String(previousCompanyId || '')) return;
    syncBranchFromCompany();
    syncPrincipalFromCompany();
  }
);

watch(
  () => filters.branchId,
  () => {
    syncPrincipalFromCompany();
  }
);

onMounted(async () => {
  await loadMasterData();
  await loadReport();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Laporan Stok Gudang"
      description="Ready mengikuti stok transaksi cabang (sama dengan Sales Order dan Request Canvas); Rak Tetap (WMS) ditampilkan untuk audit fisik."
    />

    <section class="panel p-4">
      <div class="grid gap-4 lg:grid-cols-4">
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
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
        <AppSearchSelect
          v-model="filters.principalId"
          label="Principal"
          :placeholder="filters.companyId ? 'Semua principal' : 'Pilih perusahaan dulu'"
          :options="principalOptions"
          :disabled="!filters.companyId"
          empty-text="Principal belum tersedia."
        />
        <label class="block">
          <span class="mb-1 block text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Cari</span>
          <input
            v-model="filters.search"
            class="input"
            placeholder="SKU, produk, principal"
          />
        </label>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button class="btn-primary" type="button" :disabled="loading" @click="loadReport">
          {{ loading ? 'Memuat...' : 'Terapkan' }}
        </button>
        <button class="btn-secondary" type="button" @click="resetFilters">Reset</button>
        <button class="btn-secondary" type="button" :disabled="!filteredRows.length" @click="exportReport">
          Export CSV
        </button>
      </div>
      <p v-if="feedback" class="mt-3 text-sm text-emerald-300">{{ feedback }}</p>
      <p v-if="errorMessage" class="mt-3 text-sm text-rose-300">{{ errorMessage }}</p>
    </section>

    <section class="grid gap-4 md:grid-cols-3 xl:grid-cols-7">
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Total SKU</p>
        <p class="mt-3 text-2xl font-black text-white">{{ numberLabel(summary.sku) }}</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Ready</p>
        <p class="mt-3 text-2xl font-black text-emerald-300">{{ numberLabel(summary.ready) }}</p>
        <p class="mt-1 text-xs text-slate-500">Stok transaksi cabang</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Rak Tetap</p>
        <p class="mt-3 text-2xl font-black text-cyan-300">{{ numberLabel(summary.rackReady) }}</p>
        <p class="mt-1 text-xs text-slate-500">Fisik WMS (audit)</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Rak Titipan</p>
        <p class="mt-3 text-2xl font-black text-violet-300">{{ numberLabel(summary.titipan) }}</p>
        <p class="mt-1 text-xs text-slate-500">Belum siap picking</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Good</p>
        <p class="mt-3 text-2xl font-black text-sky-300">{{ numberLabel(summary.good) }}</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">Bad</p>
        <p class="mt-3 text-2xl font-black text-rose-300">{{ numberLabel(summary.bad) }}</p>
      </div>
      <div class="panel p-4">
        <p class="text-xs font-semibold uppercase tracking-[0.28em] text-slate-500">In Transit</p>
        <p class="mt-3 text-2xl font-black text-amber-300">{{ numberLabel(summary.incoming) }}</p>
      </div>
    </section>

    <section class="space-y-3">
      <div>
        <h2 class="text-xl font-black text-white">Daftar Stock Cabang</h2>
        <p class="text-sm text-slate-400">Tampil {{ filteredRows.length.toLocaleString('id-ID') }} dari {{ stockRows.length.toLocaleString('id-ID') }} baris.</p>
      </div>
      <AppTable
        :columns="columns"
        :rows="filteredRows"
        :loading="loading"
        row-key="id"
        empty-message="Belum ada data stock untuk filter ini."
      />
    </section>
  </div>
</template>
