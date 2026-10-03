<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getCustomers, getPrincipals, getSales } from '@/api/master';
import { getSalesBillingLetterDetail, getSalesBillingLetters } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getLoginSalesId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  salesId: '',
  customerId: '',
  dueDate: '',
  search: ''
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const customers = ref([]);
const detailHeader = ref(null);
const detailRows = ref([]);
const selected = ref(null);
const detailOpen = ref(false);
const loading = reactive({ refs: false, list: false, detail: false });
const errorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value);
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() => {
  const allowed = companyIdsForBranch(filters.branchId);
  return companies.value
    .filter((item) => allowed.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
    }));
});

const principalOptions = computed(() =>
  principals.value
    .filter((item) => !filters.companyId || String(item.id_perusahaan || item.perusahaan_id || '') === String(filters.companyId))
    .map((item) => ({ value: String(item.id), label: item.nama || `Principal ${item.id}` }))
);

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, authStore)
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || '') === String(filters.branchId))
    .map((item) => ({ value: String(item.id_sales || item.id), label: item.nama_sales || item.nama || 'Sales' }))
);

const customerOptions = computed(() =>
  customers.value
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || '') === String(filters.branchId))
    .map((item) => ({ value: String(item.id), label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || 'Customer'}` }))
);

const totalTagihan = computed(() => rows.value.reduce((sum, item) => sum + Number(item.total_penjualan || 0), 0));

const columns = [
  { key: 'nota_tagihan', label: 'Surat Tagihan' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_pj', label: 'PJ / Sales' },
  { key: 'total_penjualan', label: 'Total Tagihan', render: (row) => formatCurrency(row.total_penjualan) },
  { key: 'jumlah_faktur', label: 'Faktur' },
  { key: 'status_kirim', label: 'Status Kirim' },
  { key: 'status_bayar', label: 'Status Bayar' }
];

const detailColumns = [
  { key: 'no_faktur', label: 'No Faktur' },
  { key: 'tanggal_faktur', label: 'Tgl Faktur', render: (row) => formatDate(row.tanggal_faktur) },
  { key: 'tanggal_jatuh_tempo', label: 'Jatuh Tempo', render: (row) => formatDate(row.tanggal_jatuh_tempo) },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'total_penjualan', label: 'Total', render: (row) => formatCurrency(row.total_penjualan) },
  { key: 'jumlah_setoran', label: 'Setoran', render: (row) => formatCurrency(row.jumlah_setoran) },
  { key: 'sisa', label: 'Sisa', render: (row) => formatCurrency(Number(row.total_penjualan || 0) - Number(row.jumlah_setoran || 0) - Number(row.nominal_retur || 0)) }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value));
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, principalResponse, salesResponse, customerResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getSales(),
      getCustomers()
    ]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    customers.value = normalizeList(unwrapResponse(customerResponse));
    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) {
      filters.companyId = String(fallbackCompanyId.value);
    }
    if (canUseLoginScope.value && fallbackSalesId.value) {
      filters.salesId = String(fallbackSalesId.value);
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi surat tagihan belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  errorMessage.value = '';
  try {
    const response = await getSalesBillingLetters({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      principal: filters.principalId || undefined,
      sales: filters.salesId || undefined,
      customer: filters.customerId || undefined,
      jatuh_tempo: filters.dueDate || undefined,
      search: filters.search || undefined
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Surat tagihan sales belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openDetail(row) {
  selected.value = row;
  detailHeader.value = null;
  detailRows.value = [];
  detailOpen.value = true;
  loading.detail = true;
  try {
    const response = await getSalesBillingLetterDetail({ no_tagihan: row.nota_tagihan });
    const payload = unwrapResponse(response);
    detailHeader.value = payload?.header || {};
    detailRows.value = normalizeList(payload?.detail || payload);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail surat tagihan belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

watch(
  () => filters.branchId,
  () => {
    filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    filters.principalId = '';
    filters.salesId = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    filters.customerId = '';
  }
);

watch(
  () => filters.companyId,
  () => {
    filters.principalId = '';
  }
);

onMounted(async () => {
  await loadReferences();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Surat Tagihan Sales"
      description="Monitoring surat tagihan sales lengkap dengan filter cabang, perusahaan, principal, sales, customer, dan jatuh tempo."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-4">
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="shouldLockBusinessScope && !!fallbackBranchId" />
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="!filters.branchId || (shouldLockBusinessScope && !!fallbackCompanyId)" empty-text="Pilih cabang terlebih dahulu." />
        <AppSearchSelect v-model="filters.principalId" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filters.companyId" />
        <AppSearchSelect v-model="filters.salesId" label="Sales" placeholder="Semua sales" :options="salesOptions" :disabled="canUseLoginScope && !!fallbackSalesId" />
        <AppSearchSelect v-model="filters.customerId" label="Customer" placeholder="Semua customer" :options="customerOptions" />
        <div>
          <label class="field-label">Jatuh Tempo</label>
          <input v-model="filters.dueDate" type="date" class="field-control" />
        </div>
        <div>
          <label class="field-label">Cari</label>
          <input v-model="filters.search" type="text" placeholder="No tagihan, customer, principal" class="field-control" />
        </div>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="loadRows">
          Cari Data
        </button>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Surat Tagihan</p>
        <p class="mt-3 text-xl font-bold">{{ rows.length }}</p>
      </article>
      <article class="panel p-5 md:col-span-2">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Tagihan</p>
        <p class="mt-3 text-xl font-bold">{{ formatCurrency(totalTagihan) }}</p>
      </article>
    </section>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">{{ errorMessage }}</section>

    <AppTable
      :columns="columns"
      :rows="rows"
      :loading="loading.list"
      clickable-rows
      row-key="nota_tagihan"
      empty-message="Belum ada surat tagihan sales pada filter ini."
      @row-click="openDetail"
    />

    <AppModal
      :open="detailOpen"
      title="Detail Surat Tagihan Sales"
      :description="selected?.nota_tagihan || '-'"
      size="7xl"
      @close="detailOpen = false"
    >
      <div class="mb-4 grid gap-3 md:grid-cols-4">
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Customer</p>
          <p class="mt-2 text-base font-bold">{{ detailHeader?.kode_customer || '-' }} / {{ detailHeader?.nama_customer || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Principal</p>
          <p class="mt-2 text-base font-bold">{{ detailHeader?.kode_principal || '-' }} / {{ detailHeader?.nama_principal || '-' }}</p>
        </div>
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Tagihan</p>
          <p class="mt-2 text-base font-bold">{{ formatCurrency(detailHeader?.total_penjualan) }}</p>
        </div>
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Setoran</p>
          <p class="mt-2 text-base font-bold">{{ formatCurrency(detailHeader?.jumlah_setoran) }}</p>
        </div>
      </div>
      <AppTable :columns="detailColumns" :rows="detailRows" :loading="loading.detail" :paginated="false" />
    </AppModal>
  </div>
</template>
