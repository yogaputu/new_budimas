<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getStockOpnameDetail, getStockOpnameList } from '@/api/stockOpname';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();

const filter = reactive({
  tanggal_so: '',
  status_so: '',
  id_cabang: '',
  id_perusahaan: '',
  id_principal: ''
});

const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: 'under review', label: 'Under Review' },
  { value: 'eskalasi', label: 'Eskalasi' },
  { value: 'completed', label: 'Completed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'eskalasi closed', label: 'Eskalasi Closed' }
];

const loading = ref(false);
const detailLoading = ref(false);
const error = ref('');
const feedback = ref('');
const principals = ref([]);
const companies = ref([]);
const branches = ref([]);
const rows = ref([]);
const detailRows = ref([]);
const selectedRow = ref(null);
const detailOpen = ref(false);

const fallbackBranchId = computed(() => auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
const companyOptions = computed(() => getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true));
const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, true, filter.id_perusahaan, companies.value));
const principalOptions = computed(() => getSupervisorPrincipalOptions(principals.value, filter.id_perusahaan, true));

const summary = computed(() => {
  const items = rows.value;
  return {
    total: items.length,
    underReview: items.filter((item) => String(item.status_so || '').toLowerCase() === 'under review').length,
    escalation: items.filter((item) => String(item.status_so || '').toLowerCase() === 'eskalasi').length,
    completed: items.filter((item) => String(item.status_so || '').toLowerCase() === 'completed').length
  };
});

const detailSummary = computed(() => ({
  totalProduk: detailRows.value.length,
  totalSelisih: detailRows.value.reduce((total, item) => total + Number(item.selisih || 0), 0),
  totalNominalSelisih: detailRows.value.reduce((total, item) => total + Number(item.subtotal_selisih || 0), 0)
}));

const tableColumns = [
  {
    key: 'kode_so',
    label: 'Kode',
    render: (row) => row.kode_so || `SO #${row.id_stock_opname || row.id || '-'}`
  },
  {
    key: 'tanggal_so',
    label: 'Tanggal',
    render: (row) => row.tanggal_so || '-'
  },
  {
    key: 'nama_cabang',
    label: 'Cabang',
    render: (row) => row.nama_cabang || (row.id_cabang ? `Cabang #${row.id_cabang}` : '-')
  },
  {
    key: 'nama_principal',
    label: 'Principal',
    render: (row) => row.nama_principal || '-'
  },
  {
    key: 'produk_count',
    label: 'Produk',
    render: (row) => Number(row.produk_count || 0)
  },
  {
    key: 'status_so',
    label: 'Status',
    render: (row) => row.status_so || '-'
  },
  {
    key: 'total_selisih',
    label: 'Selisih Nilai',
    render: (row) => `Rp ${Number(row.total_selisih || 0).toLocaleString('id-ID')}`
  }
];

const detailColumns = [
  {
    key: 'nama_produk',
    label: 'Produk',
    render: (row) => `${row.nama_produk || '-'}${row.kode_sku ? ` (${row.kode_sku})` : ''}`
  },
  {
    key: 'stok_sistem',
    label: 'Stok Sistem',
    render: (row) => Number(row.stok_sistem || 0)
  },
  {
    key: 'stok',
    label: 'Stok Fisik',
    render: (row) => Number(row.stok || 0)
  },
  {
    key: 'selisih',
    label: 'Selisih',
    render: (row) => Number(row.selisih || 0)
  },
  {
    key: 'bad_stock',
    label: 'Bad Stock',
    render: (row) => Number(row.bad_stock || 0)
  },
  {
    key: 'subtotal_selisih',
    label: 'Nominal Selisih',
    render: (row) => `Rp ${Number(row.subtotal_selisih || 0).toLocaleString('id-ID')}`
  }
];

const selectedSummary = computed(() => {
  if (!selectedRow.value) return null;

  return {
    kode: selectedRow.value.kode_so || `SO #${selectedRow.value.id_stock_opname || selectedRow.value.id || '-'}`,
    tanggal: selectedRow.value.tanggal_so || '-',
    cabang: selectedRow.value.nama_cabang || '-',
    principal: selectedRow.value.nama_principal || '-',
    status: selectedRow.value.status_so || '-',
    catatan: selectedRow.value.ket_so || '-'
  };
});

function normalizeStockOpnamePayload(payload) {
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.pages)) return payload.pages;
  if (Array.isArray(payload?.pages?.result)) return payload.pages.result;
  if (Array.isArray(payload?.data?.pages)) return payload.data.pages;
  if (Array.isArray(payload?.data?.pages?.result)) return payload.data.pages.result;
  if (Array.isArray(payload?.result)) return payload.result;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.items)) return payload.items;
  if (Array.isArray(payload?.rows)) return payload.rows;
  return [];
}

async function loadReferences() {
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    if (!filter.id_cabang && fallbackBranchId.value) filter.id_cabang = String(fallbackBranchId.value);
    syncSupervisorCompanyFromBranch(filter, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  } catch (err) {
    error.value = normalizeError(err, 'Referensi cabang dan principal belum bisa dimuat.');
  }
}

async function loadStockOpnames() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getStockOpnameList({
      'no-paginate': 'true',
      order: 'desc',
      field: 'id_stock_opname',
      id_cabang: filter.id_cabang || fallbackBranchId.value || undefined,
      id_perusahaan: filter.id_perusahaan || undefined,
      status_so: filter.status_so || undefined,
      tanggal_so: filter.tanggal_so || undefined,
      id_principal: filter.id_principal || undefined
    });

    rows.value = normalizeStockOpnamePayload(unwrapResponse(response));

    if (selectedRow.value) {
      const refreshed = rows.value.find((item) => String(item.id_stock_opname || item.id) === String(selectedRow.value.id_stock_opname || selectedRow.value.id));
      if (refreshed) {
        selectedRow.value = refreshed;
      } else {
        selectedRow.value = null;
        detailRows.value = [];
        detailOpen.value = false;
      }
    }

    feedback.value = `Monitor stok opname memuat ${rows.value.length} data untuk cabang aktif.`;
  } catch (err) {
    error.value = normalizeError(err, 'Daftar stok opname supervisor belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function selectRow(row) {
  selectedRow.value = row;
  detailOpen.value = true;
  detailLoading.value = true;
  error.value = '';

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
  } catch (err) {
    error.value = normalizeError(err, 'Detail stok opname belum bisa dimuat.');
    detailRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailOpen.value = false;
}

function resetFilters() {
  filter.tanggal_so = '';
  filter.status_so = '';
  filter.id_cabang = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filter.id_perusahaan = '';
  filter.id_principal = '';
  selectedRow.value = null;
  detailRows.value = [];
  detailOpen.value = false;
  syncSupervisorCompanyFromBranch(filter, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  loadStockOpnames();
}

onMounted(async () => {
  await loadReferences();
  await loadStockOpnames();
});

function handleCompanyChange() {
  if (resetSupervisorBranchWhenCompanyChanges(filter, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value)) {
    selectedRow.value = null;
    detailRows.value = [];
    detailOpen.value = false;
  }
  filter.id_principal = '';
}

function handleBranchChange() {
  selectedRow.value = null;
  detailRows.value = [];
  detailOpen.value = false;
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Monitoring Stok Opname"
      description="Halaman supervisor untuk memantau dokumen stok opname sales, melihat status verifikasi, dan membaca detail selisih stok per produk."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadStockOpnames">
          Refresh
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-5">
        <AppFormField v-model="filter.tanggal_so" label="Tanggal Opname" type="date" />
        <AppSearchSelect v-model="filter.id_perusahaan" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" @update:model-value="handleCompanyChange" />
        <AppSearchSelect v-model="filter.id_cabang" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." @update:model-value="handleBranchChange" />
        <AppSearchSelect v-model="filter.id_principal" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filter.status_so" label="Status" placeholder="Semua status" :options="statusOptions" />
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-4">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Dokumen</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ summary.total }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Under Review</p>
        <p class="mt-3 text-3xl font-bold text-amber-600">{{ summary.underReview }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Eskalasi</p>
        <p class="mt-3 text-3xl font-bold text-rose-600">{{ summary.escalation }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Completed</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">{{ summary.completed }}</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Daftar Stok Opname</h3>
          <p class="mt-1 text-sm text-slate-500">Klik salah satu dokumen untuk membuka detail produk dan selisih stoknya.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ rows.length }} Dokumen
        </div>
      </div>

      <AppTable
        :rows="rows"
        :columns="tableColumns"
        :loading="loading"
        :clickable-rows="true"
        :selected-key="selectedRow?.id_stock_opname || selectedRow?.id || ''"
        row-key="id_stock_opname"
        empty-message="Belum ada data stok opname untuk filter supervisor yang dipilih."
        @row-click="selectRow"
      />
    </section>

    <AppModal
      :open="detailOpen"
      :title="selectedSummary ? `Detail Stok Opname ${selectedSummary.kode}` : 'Detail Stok Opname'"
      :description="selectedSummary ? `${selectedSummary.cabang} | ${selectedSummary.status}` : 'Ringkasan dokumen dan detail produk stok opname.'"
      size="7xl"
      @close="closeDetailModal"
    >
      <div class="space-y-5">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Detail Stok Opname</h3>
          <p class="mt-1 text-sm text-slate-500">Ringkasan dokumen dan daftar produk yang dihitung pada opname terpilih.</p>
        </div>

        <div v-if="selectedSummary" class="grid gap-3 md:grid-cols-2">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Kode Dokumen</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.kode }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <p class="text-slate-500">Tanggal</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.tanggal }}</p>
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
            <p class="text-slate-500">Status</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.status }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm md:col-span-2">
            <p class="text-slate-500">Catatan</p>
            <p class="mt-1 font-semibold text-slate-950">{{ selectedSummary.catatan }}</p>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-3">
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Total Produk</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">{{ detailSummary.totalProduk }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Total Selisih Unit</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">{{ detailSummary.totalSelisih }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3 text-sm">
            <p class="text-slate-500">Total Selisih Nilai</p>
            <p class="mt-1 text-2xl font-bold text-slate-950">Rp {{ detailSummary.totalNominalSelisih.toLocaleString('id-ID') }}</p>
          </div>
        </div>

        <AppTable
          :rows="detailRows"
          :columns="detailColumns"
          :loading="detailLoading"
          :paginated="true"
          :default-page-size="10"
          empty-message="Detail produk stok opname belum tersedia."
        />
      </div>
    </AppModal>
  </div>
</template>
