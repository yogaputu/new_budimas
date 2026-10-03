<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getPrincipals, getSales } from '@/api/master';
import { getStockOpnameDetail, getStockOpnameList } from '@/api/stockOpname';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getRowCompanyId } from '@/utils/accessScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();

const filter = reactive({
  tanggal_so: '',
  status_so: '',
  id_cabang: '',
  id_perusahaan: '',
  id_user_input: '',
  id_principal: '',
  customer_code: '',
  search: ''
});

const statusOptions = [
  { value: '', label: '' },
  { value: 'done', label: 'Done Android' },
  { value: 'under review', label: 'Under Review' },
  { value: 'completed', label: 'Completed' },
  { value: 'rejected', label: 'Rejected' }
];

const loading = ref(false);
const detailLoading = ref(false);
const errorMessage = ref('');
const feedback = ref('');
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const salesRows = ref([]);
const rows = ref([]);
const optionRows = ref([]);
const detailRows = ref([]);
const selectedRow = ref(null);
const detailOpen = ref(false);

const fallbackBranchId = computed(() => auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
const fallbackCompanyId = computed(() => auth.user?.perusahaan?.id || auth.user?.perusahaan_id || auth.user?.company_id || auth.user?.id_perusahaan || '');
const companyOptions = computed(() => [
  { value: '', label: '' },
  ...companies.value.map((item) => ({ value: String(item.id), label: item.nama || item.kode || `Perusahaan #${item.id}` }))
]);
const branchOptions = computed(() => [
  { value: '', label: '' },
  ...branches.value
    .filter((item) => !filter.id_perusahaan || branchMatchesCompany(item, filter.id_perusahaan))
    .map((item) => ({ value: String(item.id), label: item.nama || item.kode || `Cabang #${item.id}` }))
]);
const principalOptions = computed(() => [
  { value: '', label: '' },
  ...principals.value
    .filter((item) => !filter.id_perusahaan || String(item.id_perusahaan) === String(filter.id_perusahaan))
    .map((item) => ({ value: String(item.id), label: item.nama || item.kode || `Principal #${item.id}` }))
]);
const salesOptions = computed(() => [
  { value: '', label: '' },
  ...salesRows.value
    .filter((item) => !filter.id_cabang || String(item.id_cabang || item.cabang_id || item.idCabang || '') === String(filter.id_cabang))
    .filter((item) => !filter.id_perusahaan || !item.id_perusahaan || String(item.id_perusahaan) === String(filter.id_perusahaan))
    .map((item) => ({
      value: String(item.id_user || item.user_id || item.id),
      label: `${item.kode_sales || '-'} - ${item.nama_sales || item.nama || item.username || 'Sales'}`
    }))
]);
const customerOptions = computed(() => [
  { value: '', label: '' },
  ...buildCustomerOptions(optionRows.value)
]);

const summary = computed(() => ({
  total: rows.value.length,
  done: rows.value.filter((item) => String(item.status_so || '').toLowerCase() === 'done').length,
  productCount: rows.value.reduce((total, item) => total + Number(item.produk_count || 0), 0),
  totalSelisih: rows.value.reduce((total, item) => total + Number(item.total_selisih || 0), 0)
}));

const detailSummary = computed(() => ({
  totalProduk: detailRows.value.length,
  stokFisik: detailRows.value.reduce((total, item) => total + Number(item.stok || 0), 0),
  stokSistem: detailRows.value.reduce((total, item) => total + Number(item.stok_sistem || 0), 0),
  selisih: detailRows.value.reduce((total, item) => total + Number(item.selisih || 0), 0)
}));

const tableColumns = [
  { key: 'kode_so', label: 'Kode SO', render: (row) => row.kode_so || `SO #${row.id_stock_opname || row.id || '-'}` },
  { key: 'tanggal_so', label: 'Tanggal', render: (row) => row.tanggal_so || '-' },
  { key: 'nama_sales_input', label: 'Sales', render: (row) => row.nama_sales_input || row.email_sales_input || '-' },
  { key: 'customer', label: 'Customer', render: (row) => formatCustomer(row) },
  { key: 'id_kunjungan_mobile', label: 'Kunjungan', render: (row) => row.id_kunjungan_mobile || '-' },
  { key: 'nama_principal', label: 'Principal', render: (row) => row.nama_principal || '-' },
  { key: 'produk_count', label: 'Produk', render: (row) => Number(row.produk_count || 0).toLocaleString('id-ID') },
  { key: 'status_so', label: 'Status', render: (row) => row.status_so || '-' },
  { key: 'total_selisih', label: 'Selisih Nilai', render: (row) => currency(row.total_selisih) }
];

const detailColumns = [
  { key: 'nama_produk', label: 'Produk', render: (row) => `${row.nama_produk || '-'}${row.kode_sku ? ` (${row.kode_sku})` : ''}` },
  { key: 'stok_sistem', label: 'Stok Sistem', render: (row) => numberLabel(row.stok_sistem) },
  { key: 'stok', label: 'Stok Android', render: (row) => numberLabel(row.stok) },
  { key: 'selisih', label: 'Selisih', render: (row) => numberLabel(row.selisih) },
  { key: 'bad_stock', label: 'Bad Stock', render: (row) => numberLabel(row.bad_stock) },
  { key: 'subtotal_selisih', label: 'Nilai Selisih', render: (row) => currency(row.subtotal_selisih) },
  { key: 'ket_produk', label: 'Catatan', render: (row) => row.ket_produk || '-' }
];

const selectedSummary = computed(() => {
  if (!selectedRow.value) return null;
  return {
    kode: selectedRow.value.kode_so || `SO #${selectedRow.value.id_stock_opname || selectedRow.value.id || '-'}`,
    tanggal: selectedRow.value.tanggal_so || '-',
    cabang: selectedRow.value.nama_cabang || '-',
    principal: selectedRow.value.nama_principal || '-',
    sales: selectedRow.value.nama_sales_input || selectedRow.value.email_sales_input || '-',
    customer: formatCustomer(selectedRow.value),
    kunjungan: selectedRow.value.id_kunjungan_mobile || '-',
    status: selectedRow.value.status_so || '-',
    catatan: selectedRow.value.ket_so || '-'
  };
});

function normalizeRows(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.pages)) return payload.pages;
  if (Array.isArray(payload?.pages?.result)) return payload.pages.result;
  if (Array.isArray(payload?.data?.pages)) return payload.data.pages;
  if (Array.isArray(payload?.data?.pages?.result)) return payload.data.pages.result;
  if (Array.isArray(payload?.result)) return payload.result;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.items)) return payload.items;
  return [];
}

function currency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function formatCustomer(row) {
  const code = row?.kode_customer_mobile || '';
  const name = row?.nama_customer_mobile || '';
  if (code && name) return `${code} - ${name}`;
  return name || code || '-';
}

function firstFilled(row, keys = []) {
  for (const key of keys) {
    const value = row?.[key];
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      return String(value).trim();
    }
  }
  return '';
}

function matchesCustomerOptionScope(row) {
  if (filter.id_perusahaan && String(row?.id_perusahaan || '') !== String(filter.id_perusahaan)) return false;
  if (filter.id_cabang && String(row?.id_cabang || '') !== String(filter.id_cabang)) return false;
  if (filter.id_user_input && String(row?.id_user_input || '') !== String(filter.id_user_input)) return false;
  if (filter.id_principal && String(row?.id_principal || '') !== String(filter.id_principal)) return false;
  return true;
}

function buildCustomerOptions(sourceRows = []) {
  const map = new Map();

  sourceRows
    .filter(matchesCustomerOptionScope)
    .forEach((row) => {
      const code = firstFilled(row, ['kode_customer_mobile', 'kode_customer', 'customer_code']);
      if (!code) return;
      const key = code.toLowerCase();
      if (!map.has(key)) {
        map.set(key, {
          value: code,
          label: formatCustomer(row)
        });
      }
    });

  return Array.from(map.values()).sort((left, right) => left.label.localeCompare(right.label));
}

async function loadReferences() {
  try {
    const [branchResponse, companyResponse, principalResponse, salesResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getSales()
    ]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    if (!filter.id_perusahaan && fallbackCompanyId.value) filter.id_perusahaan = String(fallbackCompanyId.value);
    if (!filter.id_cabang && fallbackBranchId.value) filter.id_cabang = String(fallbackBranchId.value);
    if (!filter.id_perusahaan && filter.id_cabang) {
      const branch = branches.value.find((item) => String(item.id) === String(filter.id_cabang));
      const branchCompanyId = getRowCompanyId(branch);
      if (branchCompanyId) filter.id_perusahaan = String(branchCompanyId);
    }
    resetBranchIfOutsideCompany();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi filter stok opname sales belum bisa dimuat.');
  }
}

async function loadRows() {
  loading.value = true;
  errorMessage.value = '';

  try {
    const response = await getStockOpnameList({
      source: 'mobile',
      fast: 1,
      limit: 75,
      order: 'desc',
      field: 'id_stock_opname',
      id_cabang: filter.id_cabang || undefined,
      id_perusahaan: filter.id_perusahaan || undefined,
      id_user_input: filter.id_user_input || undefined,
      id_principal: filter.id_principal || undefined,
      tanggal_so: filter.tanggal_so || undefined,
      status_so: filter.status_so || undefined,
      customer_code: filter.customer_code || undefined,
      search: filter.search || undefined
    });

    rows.value = normalizeRows(unwrapResponse(response));
    if (!filter.customer_code) {
      optionRows.value = rows.value;
    }
    feedback.value = `Stok opname sales dari Android memuat ${rows.value.length} dokumen.`;

    if (selectedRow.value) {
      const currentId = selectedRow.value.id_stock_opname || selectedRow.value.id;
      selectedRow.value = rows.value.find((item) => String(item.id_stock_opname || item.id) === String(currentId)) || null;
      if (!selectedRow.value) detailRows.value = [];
    }
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Data stok opname sales dari Android belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function selectRow(row) {
  selectedRow.value = row;
  detailOpen.value = true;
  detailLoading.value = true;
  errorMessage.value = '';

  try {
    const response = await getStockOpnameDetail(row.id_stock_opname || row.id);
    detailRows.value = normalizeList(unwrapResponse(response)).map((item) => ({
      ...item,
      stok: Number(item.stok || 0),
      stok_sistem: Number(item.stok_sistem || 0),
      selisih: Number(item.selisih || 0),
      bad_stock: Number(item.bad_stock || 0),
      subtotal_selisih: Number(item.subtotal_selisih || 0)
    }));
  } catch (error) {
    detailRows.value = [];
    errorMessage.value = normalizeError(error, 'Detail stok opname sales belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function resetFilters() {
  filter.tanggal_so = '';
  filter.status_so = '';
  filter.id_perusahaan = fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filter.id_cabang = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  if (!filter.id_perusahaan && filter.id_cabang) {
    const branch = branches.value.find((item) => String(item.id) === String(filter.id_cabang));
    const branchCompanyId = getRowCompanyId(branch);
    if (branchCompanyId) filter.id_perusahaan = String(branchCompanyId);
  }
  resetBranchIfOutsideCompany();
  filter.id_user_input = '';
  filter.id_principal = '';
  filter.customer_code = '';
  filter.search = '';
  selectedRow.value = null;
  detailRows.value = [];
  detailOpen.value = false;
  loadRows();
}

function resetBranchIfOutsideCompany() {
  if (!filter.id_perusahaan) {
    filter.id_cabang = '';
    return;
  }

  if (!filter.id_cabang) return;

  const currentBranch = branches.value.find((item) => String(item.id) === String(filter.id_cabang));
  if (!branchMatchesCompany(currentBranch, filter.id_perusahaan)) {
    filter.id_cabang = '';
  }
}

watch(
  () => filter.id_perusahaan,
  () => {
    resetBranchIfOutsideCompany();
    filter.id_user_input = '';
    filter.customer_code = '';
    filter.id_principal = '';
  }
);

watch(
  () => filter.id_cabang,
  () => {
    filter.id_user_input = '';
    filter.customer_code = '';
    filter.id_principal = '';
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
      title="Stok Opname Sales"
      description="Pantau hasil stok opname yang dikirim dari aplikasi Android sales."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60" :disabled="loading" @click="loadRows">
          {{ loading ? 'Memuat...' : 'Refresh' }}
        </button>
      </div>
    </PageHeader>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <AppSearchSelect
          v-model="filter.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
        />
        <AppSearchSelect
          v-model="filter.id_cabang"
          label="Cabang"
          :placeholder="filter.id_perusahaan ? 'Semua cabang' : 'Pilih perusahaan dahulu'"
          :options="branchOptions"
          :disabled="!filter.id_perusahaan"
          :empty-text="filter.id_perusahaan ? 'Cabang belum tersedia.' : 'Pilih perusahaan dahulu.'"
        />
        <AppSearchSelect
          v-model="filter.id_user_input"
          label="Sales"
          :placeholder="filter.id_cabang ? 'Semua sales' : 'Pilih cabang dahulu'"
          :options="salesOptions"
          :disabled="!filter.id_cabang"
          :empty-text="filter.id_cabang ? 'Sales belum tersedia.' : 'Pilih cabang dahulu.'"
        />
        <AppSearchSelect
          v-model="filter.customer_code"
          label="Customer"
          placeholder="Semua customer"
          :options="customerOptions"
        />
        <AppSearchSelect
          v-model="filter.id_principal"
          label="Principal"
          placeholder="Semua principal"
          :options="principalOptions"
        />
      </div>

      <div class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <AppFormField v-model="filter.tanggal_so" label="Tanggal" type="date" />
        <AppSearchSelect v-model="filter.status_so" label="Status" placeholder="Semua status" :options="statusOptions" />
      </div>

      <div class="mt-4 flex flex-wrap items-center gap-3">
        <button class="rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800" @click="loadRows">
          Terapkan Filter
        </button>
        <span v-if="feedback" class="text-sm text-slate-500">{{ feedback }}</span>
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-4">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Dokumen Android</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ numberLabel(summary.total) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Done</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">{{ numberLabel(summary.done) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Produk</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ numberLabel(summary.productCount) }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Selisih Nilai</p>
        <p class="mt-3 text-2xl font-bold text-amber-600">{{ currency(summary.totalSelisih) }}</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Daftar Stok Opname Sales</h3>
          <p class="mt-1 text-sm text-slate-500">Klik dokumen untuk melihat detail produk yang dihitung sales di Android.</p>
        </div>
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">Sumber: Android</span>
      </div>

      <AppTable
        :rows="rows"
        :columns="tableColumns"
        :loading="loading"
        :clickable-rows="true"
        :selected-key="selectedRow?.id_stock_opname || selectedRow?.id || ''"
        row-key="id_stock_opname"
        empty-message="Belum ada stok opname sales dari Android untuk filter ini."
        @row-click="selectRow"
      />
    </section>

    <AppModal
      :open="detailOpen"
      :title="selectedSummary ? `Detail ${selectedSummary.kode}` : 'Detail Stok Opname Sales'"
      :description="selectedSummary ? `${selectedSummary.sales} | ${selectedSummary.customer}` : 'Detail produk stok opname dari Android.'"
      size="7xl"
      @close="detailOpen = false"
    >
      <div class="space-y-5">
        <div v-if="selectedSummary" class="grid gap-3 md:grid-cols-3">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Kode</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.kode }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Tanggal</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.tanggal }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Status</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.status }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Sales</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.sales }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Customer</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.customer }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">ID Kunjungan</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.kunjungan }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Cabang</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.cabang }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Principal</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.principal }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Catatan Sistem</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.catatan }}</p>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Total Produk</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">{{ numberLabel(detailSummary.totalProduk) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Stok Sistem</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">{{ numberLabel(detailSummary.stokSistem) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Stok Android</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">{{ numberLabel(detailSummary.stokFisik) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Selisih Unit</p>
            <p class="mt-1 text-2xl font-bold text-amber-600">{{ numberLabel(detailSummary.selisih) }}</p>
          </div>
        </div>

        <AppTable
          :rows="detailRows"
          :columns="detailColumns"
          :loading="detailLoading"
          :paginated="true"
          :default-page-size="10"
          empty-message="Detail produk stok opname sales belum tersedia."
        />
      </div>
    </AppModal>
  </div>
</template>
