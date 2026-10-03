<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getCashierReportDetail, getCashierReports } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Date().toISOString().slice(0, 10);

const filters = reactive({
  branchId: '',
  companyId: '',
  from: today,
  to: today
});

const rows = ref([]);
const detailRows = ref([]);
const detailInfo = ref(null);
const selectedRow = ref(null);
const branches = ref([]);
const companies = ref([]);
const loading = reactive({ refs: false, list: false, detail: false });
const pageError = ref('');
const detailError = ref('');
const detailOpen = ref(false);

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));

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

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() =>
  companies.value
    .filter((item) => companyIdsForBranch(filters.branchId).includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`}`
    }))
);

const columns = [
  { key: 'tanggal', label: 'Tanggal', render: (row) => formatDate(row.tanggal) },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'total_pemasukan', label: 'Pemasukan', render: (row) => formatCurrency(row.total_pemasukan) },
  { key: 'total_pengeluaran', label: 'Pengeluaran', render: (row) => formatCurrency(row.total_pengeluaran) },
  { key: 'saldo_akhir', label: 'Saldo Akhir', render: (row) => formatCurrency(row.saldo_akhir) }
];

const detailColumns = [
  { key: 'jenis', label: 'Jenis', render: (row) => capitalize(row.jenis) },
  { key: 'tanggal', label: 'Tanggal', render: (row) => formatDate(row.tanggal) },
  { key: 'pic', label: 'PIC' },
  { key: 'nominal', label: 'Nominal', render: (row) => formatCurrency(row.nominal) }
];

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return '-';
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value));
}

function capitalize(value) {
  const text = String(value || '-');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse] = await Promise.all([getBranches(), getCompanies()]);
    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    if (!canAccessAllBranches.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi cabang dan perusahaan belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getCashierReports({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      periode_awal: filters.from,
      periode_akhir: filters.to
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Laporan kasir belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  detailRows.value = [];
  detailInfo.value = null;
  detailError.value = '';
  detailOpen.value = true;
  loading.detail = true;

  try {
    const response = await getCashierReportDetail({
      tanggal: String(row.tanggal || '').slice(0, 10),
      id_cabang: row.id_cabang || filters.branchId,
      id_perusahaan: row.id_perusahaan || filters.companyId || undefined
    });
    const payload = unwrapResponse(response);
    detailRows.value = normalizeList(payload?.detailLaporan || payload?.detail || payload);
    detailInfo.value = payload?.laporanInfo || null;
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail laporan kasir belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') !== String(previousBranchId || '')) {
      filters.companyId = '';
    }
    rows.value = [];
  }
);

watch(
  () => filters.companyId,
  (companyId) => {
    if (companyId && filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(companyId))) {
      filters.companyId = '';
    }
    rows.value = [];
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
      title="Laporan Kasir"
      description="Ringkasan pemasukan, pengeluaran, dan saldo kasir harian per cabang."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-5">
        <AppSearchSelect
          v-model="filters.branchId"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!canAccessAllBranches && !!fallbackBranchId"
          empty-text="Cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.companyId"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="!filters.branchId"
          empty-text="Pilih cabang terlebih dahulu."
        />
        <div>
          <label class="field-label">Dari Tanggal</label>
          <input v-model="filters.from" type="date" class="field-control" />
        </div>
        <div>
          <label class="field-label">Sampai Tanggal</label>
          <input v-model="filters.to" type="date" class="field-control" />
        </div>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-bold text-white" @click="loadRows">
          Muat Laporan
        </button>
      </div>
    </section>

    <section v-if="pageError" class="rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      {{ pageError }}
    </section>

    <AppTable
      :columns="columns"
      :rows="rows"
      :loading="loading.list"
      clickable-rows
      row-key="id"
      empty-message="Belum ada laporan kasir pada periode ini."
      @row-click="openDetail"
    />

    <AppModal
      :open="detailOpen"
      title="Detail Laporan Kasir"
      :description="`${selectedRow?.nama_cabang || '-'} / ${formatDate(selectedRow?.tanggal)}`"
      size="4xl"
      @close="detailOpen = false"
    >
      <section v-if="detailError" class="mb-4 rounded-2xl border border-rose-300/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
        {{ detailError }}
      </section>
      <div class="mb-4 grid gap-3 md:grid-cols-3">
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Pemasukan</p>
          <p class="mt-2 text-lg font-bold">{{ formatCurrency(detailInfo?.total_pemasukan) }}</p>
        </div>
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Pengeluaran</p>
          <p class="mt-2 text-lg font-bold">{{ formatCurrency(detailInfo?.total_pengeluaran) }}</p>
        </div>
        <div class="rounded-2xl border border-slate-700 p-4">
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Sisa Saldo</p>
          <p class="mt-2 text-lg font-bold">{{ formatCurrency(detailInfo?.sisa_saldo) }}</p>
        </div>
      </div>
      <AppTable
        :columns="detailColumns"
        :rows="detailRows"
        :loading="loading.detail"
        :paginated="false"
        empty-message="Detail laporan belum tersedia."
      />
    </AppModal>
  </div>
</template>
