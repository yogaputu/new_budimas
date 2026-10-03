<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getDriverExpenseInfo, getDriverExpenseInvoices, getDriverExpenseList } from '@/api/distribution';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const today = new Date();
const monthAgo = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

const filters = reactive({
  branchId: '',
  companyId: '',
  periodeAwal: toDateInput(monthAgo),
  periodeAkhir: toDateInput(today),
  search: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const rows = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const errorMessage = ref('');
const detailError = ref('');
const selectedRow = ref(null);
const detailInfo = ref({});
const invoiceRows = ref([]);
const detailOpen = ref(false);

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));

function toDateInput(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(date);
}

function formatCurrency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function companyIdsForBranch(branchId) {
  if (!branchId) return [];
  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));
  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });
  return Array.from(ids);
}

const branchOptions = computed(() => getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId));

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const normalizedRows = computed(() =>
  rows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_info_driver || item.id || index}`,
    tanggal_label: formatDate(item.tanggal_berangkat || item.tanggal),
    uang_saku_label: formatCurrency(item.uang_saku),
    bbm_label: formatCurrency(item.isi_bbm_rupiah),
    total_pengeluaran_label: formatCurrency(item.total_pengeluaran ?? item.total_pengeluran),
    sisa_uang_label: formatCurrency(item.sisa_uang),
    cabang_label: item.nama_cabang || item.kode_cabang || '-',
    perusahaan_label: item.nama_perusahaan || '-'
  }))
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return normalizedRows.value;
  return normalizedRows.value.filter((item) =>
    [
      item.nama_driver,
      item.helper,
      item.tujuan,
      item.tanggal_label,
      item.cabang_label,
      item.perusahaan_label
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const summary = computed(() => ({
  totalTrip: filteredRows.value.length,
  uangSaku: filteredRows.value.reduce((sum, item) => sum + Number(item.uang_saku || 0), 0),
  totalBiaya: filteredRows.value.reduce((sum, item) => sum + Number(item.total_pengeluaran ?? item.total_pengeluran ?? 0), 0),
  sisa: filteredRows.value.reduce((sum, item) => sum + Number(item.sisa_uang || 0), 0)
}));

const detailCards = computed(() => [
  ['Driver', selectedRow.value?.nama_driver],
  ['Helper', detailInfo.value?.helper || selectedRow.value?.helper],
  ['Tujuan', detailInfo.value?.tujuan || selectedRow.value?.tujuan],
  ['Tanggal', formatDate(detailInfo.value?.tanggal || selectedRow.value?.tanggal_berangkat)],
  ['KM Berangkat', detailInfo.value?.km_berangkat || selectedRow.value?.km_berangkat],
  ['KM Pulang', detailInfo.value?.km_pulang || selectedRow.value?.km_pulang],
  ['BBM Liter', detailInfo.value?.isi_bbm_liter || selectedRow.value?.isi_bbm_liter],
  ['BBM Rupiah', formatCurrency(detailInfo.value?.isi_bbm_rupiah || selectedRow.value?.isi_bbm_rupiah)],
  ['Uang Saku', formatCurrency(detailInfo.value?.uang_saku || selectedRow.value?.uang_saku)],
  ['Total Pengeluaran', selectedRow.value?.total_pengeluaran_label],
  ['Sisa Uang', selectedRow.value?.sisa_uang_label]
]);

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) return;
  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadOptions() {
  const [branchesResponse, companiesResponse] = await Promise.all([getBranches(), getCompanies()]);
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  if (!filters.branchId && fallbackBranchId.value) filters.branchId = String(fallbackBranchId.value);
  syncBranchFromCompany();
}

async function loadRows() {
  loading.value = true;
  errorMessage.value = '';
  selectedRow.value = null;
  try {
    const response = await getDriverExpenseList({
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      periode_awal: filters.periodeAwal || undefined,
      periode_akhir: filters.periodeAkhir || undefined
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Pengeluaran driver belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  detailInfo.value = {};
  invoiceRows.value = [];
  detailError.value = '';
  detailOpen.value = true;
  detailLoading.value = true;

  try {
    const id = row.id_info_driver || row.id;
    const [infoResponse, invoiceResponse] = await Promise.all([
      getDriverExpenseInfo(id),
      getDriverExpenseInvoices(id)
    ]);
    detailInfo.value = unwrapResponse(infoResponse) || {};
    invoiceRows.value = normalizeList(unwrapResponse(invoiceResponse));
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail pengeluaran driver belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function reset() {
  filters.branchId = String(fallbackBranchId.value || '');
  syncBranchFromCompany();
  filters.periodeAwal = toDateInput(monthAgo);
  filters.periodeAkhir = toDateInput(today);
  filters.search = '';
  loadRows();
}

watch(() => filters.companyId, syncBranchFromCompany);

onMounted(async () => {
  await loadOptions();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Pengeluaran Driver"
      description="Monitoring uang saku, BBM, biaya faktur, dan sisa uang driver dengan filter Perusahaan -> Cabang."
    />

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!isSuperUser(authStore) && !!fallbackBranchId) },
        { key: 'periodeAwal', label: 'Dari Tanggal', type: 'date' },
        { key: 'periodeAkhir', label: 'Sampai Tanggal', type: 'date' },
        { key: 'search', label: 'Cari', placeholder: 'Driver, helper, tujuan, tanggal' }
      ]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="loadRows"
      @reset="reset"
    />

    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
      {{ errorMessage }}
    </div>

    <section class="grid gap-4 md:grid-cols-4">
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Trip Driver</p>
        <p class="mt-3 text-2xl font-black text-slate-900">{{ summary.totalTrip }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Uang Saku</p>
        <p class="mt-3 text-xl font-black text-slate-900">{{ formatCurrency(summary.uangSaku) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Total Biaya</p>
        <p class="mt-3 text-xl font-black text-rose-700">{{ formatCurrency(summary.totalBiaya) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-black uppercase tracking-[0.2em] text-slate-400">Sisa Uang</p>
        <p class="mt-3 text-xl font-black text-emerald-700">{{ formatCurrency(summary.sisa) }}</p>
      </div>
    </section>

    <AppTable
      :rows="filteredRows"
      :columns="[
        { key: 'tanggal_label', label: 'Tanggal' },
        { key: 'nama_driver', label: 'Driver' },
        { key: 'helper', label: 'Helper' },
        { key: 'tujuan', label: 'Tujuan' },
        { key: 'uang_saku_label', label: 'Uang Saku' },
        { key: 'bbm_label', label: 'BBM' },
        { key: 'total_pengeluaran_label', label: 'Total Biaya' },
        { key: 'sisa_uang_label', label: 'Sisa' }
      ]"
      :loading="loading"
      :clickable-rows="true"
      row-key="row_key"
      empty-message="Belum ada pengeluaran driver pada filter ini."
      @row-click="openDetail"
    />

    <AppModal :open="detailOpen" title="Detail Pengeluaran Driver" size="xl" @close="detailOpen = false">
      <div v-if="selectedRow" class="space-y-5">
        <div v-if="detailError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700">
          {{ detailError }}
        </div>

        <div class="grid gap-4 md:grid-cols-3">
          <div v-for="item in detailCards" :key="item[0]" class="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p class="text-xs font-bold uppercase tracking-[0.18em] text-slate-400">{{ item[0] }}</p>
            <p class="mt-2 font-semibold text-slate-900">{{ item[1] || '-' }}</p>
          </div>
        </div>

        <AppTable
          :rows="invoiceRows"
          :columns="[
            { key: 'nomor_faktur', label: 'No Faktur' },
            { key: 'nama_customer', label: 'Customer' },
            { key: 'kode_rute', label: 'Rute' },
            { key: 'tipe_pengeluaran', label: 'Tipe Biaya' },
            { key: 'nominal_pengeluran', label: 'Nominal' },
            { key: 'keterangan', label: 'Keterangan' }
          ]"
          :loading="detailLoading"
          empty-message="Belum ada rincian faktur biaya untuk driver ini."
        />
      </div>
    </AppModal>
  </div>
</template>
