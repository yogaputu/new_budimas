<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import {
  acceptStockOpname,
  closeEscalatedStockOpname,
  escalateStockOpname,
  getStockOpnameDetail,
  getStockOpnameList,
  rejectStockOpname
} from '@/api/stockOpname';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { exportRowsToCsv } from '@/utils/exportCsv';
import { toLocalDateInputValue } from '@/utils/date';
import { useAuthStore } from '@/stores/auth';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { buildStockOpnameDetailPayload, normalizeStockOpnameDetail, updateStockOpnameDetail } from '../detailQuantities';

const actionForm = reactive({ id_stock_opname: '', keterangan: '' });
const auth = useAuthStore();
const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  search: ''
});
const feedback = ref('');
const errorMessage = ref('');
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const { items, loading, error: loadError, load } = useRemoteCollection((params) => getStockOpnameList(params), {
  transform: normalizeStockOpnameRows,
  errorMessage: 'Daftar stok opname belum bisa dimuat.'
});

const selectedRow = ref(null);
const detailRows = ref([]);
const detailLoading = ref(false);
const detailOpen = ref(false);
const editMode = ref(false);
const actionLoading = ref('');
const detailEditPage = ref(1);
const detailEditPageSize = ref(15);
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const canAccessAllBranches = computed(() => isSuperUser(auth));

const totalOpname = computed(() =>
  detailRows.value.reduce((total, item) => total + Number(item.subtotal || 0), 0)
);

const totalSelisih = computed(() =>
  detailRows.value.reduce((total, item) => total + Number(item.subtotal_selisih || 0), 0)
);

const detailTableRows = computed(() =>
  detailRows.value.map((item) => ({
    ...item,
    selisih_label: Number(item.selisih || 0),
    subtotal_label: item.subtotal !== null && item.subtotal !== undefined ? `Rp ${Number(item.subtotal).toLocaleString('id-ID')}` : '-',
    subtotal_selisih_label:
      item.subtotal_selisih !== null && item.subtotal_selisih !== undefined
        ? `Rp ${Number(item.subtotal_selisih).toLocaleString('id-ID')}`
        : '-'
  }))
);

const detailEditTotalPages = computed(() => Math.max(1, Math.ceil(detailRows.value.length / detailEditPageSize.value)));
const paginatedDetailRows = computed(() => {
  const start = (detailEditPage.value - 1) * detailEditPageSize.value;
  return detailRows.value.slice(start, start + detailEditPageSize.value).map((item, index) => ({
    item,
    originalIndex: start + index
  }));
});
const detailEditStartRow = computed(() => (detailEditPage.value - 1) * detailEditPageSize.value);
const detailEditEndRow = computed(() => Math.min(detailEditStartRow.value + detailEditPageSize.value, detailRows.value.length));

const selectedStatus = computed(() =>
  String(selectedRow.value?.status_so || selectedRow.value?.status || '').toLowerCase()
);

const finalStatuses = ['completed', 'done', 'rejected', 'eskalasi closed'];
const isFinalStatus = computed(() => selectedRow.value && finalStatuses.includes(selectedStatus.value));
const reviewStatuses = ['under review', 'under_review', 'review'];
const canApproveReject = computed(() => selectedRow.value && reviewStatuses.includes(selectedStatus.value));
const canEscalate = computed(() => selectedRow.value && reviewStatuses.includes(selectedStatus.value));
const canCloseEscalation = computed(() => selectedRow.value && selectedStatus.value === 'eskalasi');
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);

  if (branchCompanyId) ids.add(String(branchCompanyId));

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

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return items.value.filter((item) => {
    const matchBranch = !filters.branchId || String(item.id_cabang || item.cabang_id || '') === String(filters.branchId);
    const matchPrincipal = !filters.principalId || String(item.id_principal || item.principal_id || '') === String(filters.principalId);
    const matchSearch =
      !query ||
      [
        item.id_stock_opname,
        item.kode_so,
        item.no_so,
        item.nama_cabang,
        item.nama_principal,
        item.status_so,
        item.ket_so,
        item.keterangan
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));

    return matchBranch && matchPrincipal && matchSearch;
  });
});

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
  if (filters.principalId && !principalOptions.value.some((item) => item.value === String(filters.principalId))) {
    filters.principalId = '';
  }
}

function loadStockOpnames() {
  return load({
    'no-paginate': 'true',
    order: 'desc',
    field: 'id_stock_opname',
    id_cabang: filters.branchId || (!canAccessAllBranches.value ? fallbackBranchId.value : undefined),
    id_perusahaan: filters.companyId || undefined,
    id_principal: filters.principalId || undefined
  });
}

function exportStockOpnames() {
  exportRowsToCsv(
    `stock-opname-${toLocalDateInputValue()}.csv`,
    [
      { label: 'ID', value: (row) => row.id_stock_opname || row.id || '-' },
      { label: 'Tanggal Dibuat', value: (row) => row.tanggal_so || row.tanggal || row.created_at || '-' },
      { label: 'Tanggal Pelaksanaan', value: (row) => row.tanggal_pelaksanaan || '-' },
      { label: 'Cabang', value: (row) => row.nama_cabang || row.cabang || row.branch_name || '-' },
      { label: 'Principal', value: (row) => row.nama_principal || row.principal || '-' },
      { label: 'Status', value: (row) => row.status_so || row.status || row.status_stock_opname || row.keterangan_status || '-' },
      { label: 'Catatan', value: (row) => row.ket_so || row.keterangan || row.catatan || '-' }
    ],
    filteredItems.value
  );
}

function exportStockOpnameDetail() {
  exportRowsToCsv(
    `stock-opname-detail-${actionForm.id_stock_opname || 'data'}.csv`,
    [
      { label: 'SKU', key: 'kode_sku' },
      { label: 'Produk', key: 'nama_produk' },
      { label: 'Stok Sistem', key: 'stok_sistem' },
      { label: 'Stok Fisik', key: 'stok_fisik' },
      { label: 'Good', key: 'good_stock' },
      { label: 'Bad', key: 'bad_stock' },
      { label: 'Selisih', key: 'selisih' },
      { label: 'Subtotal', key: 'subtotal' },
      { label: 'Nilai Selisih', key: 'subtotal_selisih' }
    ],
    detailTableRows.value
  );
}

function normalizeStockOpnameRows(payload) {
  if (Array.isArray(payload)) {
    return payload;
  }

  if (Array.isArray(payload?.pages)) {
    return payload.pages;
  }

  if (Array.isArray(payload?.pages?.result)) {
    return payload.pages.result;
  }

  if (Array.isArray(payload?.data?.pages)) {
    return payload.data.pages;
  }

  if (Array.isArray(payload?.data?.pages?.result)) {
    return payload.data.pages.result;
  }

  if (Array.isArray(payload?.result)) {
    return payload.result;
  }

  if (Array.isArray(payload?.data)) {
    return payload.data;
  }

  if (Array.isArray(payload?.items)) {
    return payload.items;
  }

  if (Array.isArray(payload?.rows)) {
    return payload.rows;
  }

  return [];
}

const tableColumns = [
  {
    key: 'id_stock_opname',
    label: 'ID',
    render: (row) => row.id_stock_opname || row.id || '-'
  },
  {
    key: 'tanggal_so',
    label: 'Dibuat',
    render: (row) => row.tanggal_so || row.tanggal || row.created_at || '-'
  },
  {
    key: 'tanggal_pelaksanaan',
    label: 'Pelaksanaan',
    render: (row) => row.tanggal_pelaksanaan || '-'
  },
  {
    key: 'cabang',
    label: 'Cabang',
    render: (row) => row.nama_cabang || row.cabang || row.branch_name || (row.id_cabang ? `Cabang #${row.id_cabang}` : '-')
  },
  {
    key: 'principal',
    label: 'Principal',
    render: (row) => row.nama_principal || row.principal || '-'
  },
  {
    key: 'status',
    label: 'Status',
    render: (row) => row.status_so || row.status || row.status_stock_opname || row.keterangan_status || '-'
  },
  {
    key: 'produk_count',
    label: 'Produk',
    render: (row) => row.produk_count ?? '-'
  },
  {
    key: 'ket_so',
    label: 'Catatan',
    render: (row) => row.ket_so || row.keterangan || row.catatan || '-'
  }
];

const selectedSummary = computed(() => {
  if (!selectedRow.value) {
    return null;
  }

  const row = selectedRow.value;
  return {
    id: row.id_stock_opname || row.id || '-',
    branch: row.nama_cabang || row.cabang || row.branch_name || '-',
    executionDate: row.tanggal_pelaksanaan || '-',
    startedAt: row.started_at || '-',
    finishedAt: row.finished_at || '-',
    status: row.status_so || row.status || row.status_stock_opname || row.keterangan_status || '-',
    note: row.ket_so || row.keterangan || row.catatan || '-'
  };
});

async function selectRow(row) {
  selectedRow.value = row;
  actionForm.id_stock_opname = row?.id_stock_opname || row?.id || '';
  feedback.value = '';
  errorMessage.value = '';
  detailOpen.value = true;
  editMode.value = String(row?.status_so || row?.status || '').toLowerCase() === 'eskalasi';
  await loadDetail(actionForm.id_stock_opname);
}

function closeDetailModal() {
  detailOpen.value = false;
}

async function loadDetail(id) {
  if (!id) {
    detailRows.value = [];
    return;
  }

  detailLoading.value = true;

  try {
    const response = await getStockOpnameDetail(id);
    detailRows.value = normalizeList(unwrapResponse(response)).map(normalizeStockOpnameDetail);
    detailEditPage.value = 1;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail stok opname belum bisa dimuat.');
    detailRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

function previousDetailEditPage() {
  detailEditPage.value = Math.max(1, detailEditPage.value - 1);
}

function nextDetailEditPage() {
  detailEditPage.value = Math.min(detailEditTotalPages.value, detailEditPage.value + 1);
}

function updateDetailRow(index, field, value) {
  const next = [...detailRows.value];
  next[index] = updateStockOpnameDetail(next[index], field, value);
  detailRows.value = next;
}

function buildDetailPayload() {
  return buildStockOpnameDetailPayload(detailRows.value);
}

async function runAction(type) {
  feedback.value = '';
  errorMessage.value = '';

  if (!actionForm.id_stock_opname) {
    errorMessage.value = 'Pilih data stok opname dari tabel atau isi ID terlebih dahulu.';
    return;
  }

  if (['accept', 'reject', 'escalate'].includes(type) && !canApproveReject.value) {
    errorMessage.value = 'Approval hanya dapat dilakukan setelah proses WMS selesai dan berstatus under review.';
    return;
  }

  try {
    actionLoading.value = type;
    if (type === 'accept') {
      await acceptStockOpname({
        ...actionForm,
        id_user: auth.user?.id,
        id_cabang: selectedRow.value?.id_cabang || auth.user?.id_cabang
      });
      feedback.value = 'Stock opname berhasil di-approve.';
    } else if (type === 'reject') {
      await rejectStockOpname({
        ...actionForm,
        id_user: auth.user?.id
      });
      feedback.value = 'Stock opname berhasil ditolak.';
    } else if (type === 'escalate') {
      await escalateStockOpname({
        ...actionForm,
        id_user: auth.user?.id
      });
      feedback.value = 'Stock opname berhasil dinaikkan ke eskalasi.';
    } else if (type === 'close-escalation') {
      await closeEscalatedStockOpname({
        ...actionForm,
        id_user: auth.user?.id,
        id_cabang: selectedRow.value?.id_cabang || auth.user?.id_cabang,
        total: totalOpname.value,
        total_selisih: totalSelisih.value,
        data_produks: buildDetailPayload()
      });
      feedback.value = 'Eskalasi stok opname berhasil ditutup.';
    }
    actionForm.keterangan = '';
    if (type === 'escalate') {
      selectedRow.value = {
        ...selectedRow.value,
        status_so: 'eskalasi'
      };
      editMode.value = true;
      await loadStockOpnames();
      return;
    }

    selectedRow.value = null;
    detailRows.value = [];
    detailOpen.value = false;
    editMode.value = false;
    await loadStockOpnames();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Aksi stok opname gagal.');
  } finally {
    actionLoading.value = '';
  }
}

async function loadFilterOptions() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getPrincipals()
  ]);
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

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = !canAccessAllBranches.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.principalId = '';
  filters.search = '';
  selectedRow.value = null;
  detailRows.value = [];
  detailOpen.value = false;
  editMode.value = false;
  syncBranchFromCompany();
  loadStockOpnames();
}

function updateFilters(next) {
  const previousBranch = filters.branchId;
  const previousCompany = filters.companyId;
  Object.assign(filters, next);

  if (String(previousCompany || '') !== String(filters.companyId || '')) {
    syncBranchFromCompany();
    filters.principalId = '';
  } else if (String(previousBranch || '') !== String(filters.branchId || '')) {
    filters.principalId = '';
  }

  syncPrincipalFromCompany();
}

onMounted(async () => {
  await loadFilterOptions();
  loadStockOpnames();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Stok Opname" description="Pantau jadwal dari ERP, pelaksanaan per rak di WMS, lalu verifikasi hasil hitung fisik.">
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="exportStockOpnames">
        Export CSV
      </button>
      <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="loadStockOpnames()">
        Refresh daftar
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions, disabled: canUseLoginScope && !!fallbackCompanyId },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!canAccessAllBranches && !!fallbackBranchId) },
        { key: 'principalId', label: 'Principal', type: 'search-select', options: principalOptions, disabled: !filters.companyId },
        { key: 'search', label: 'Cari', placeholder: 'Kode, cabang, principal, status' }
      ]"
      @update:model-value="updateFilters"
      @submit="loadStockOpnames"
      @reset="resetFilters"
    />

    <div class="space-y-4">
      <div v-if="loadError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ loadError }}
      </div>
      <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ feedback }}
      </div>
      <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ errorMessage }}
      </div>

      <AppTable
        :rows="filteredItems"
        :columns="tableColumns"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada data stok opname yang bisa ditampilkan."
        @row-click="selectRow"
      />
    </div>

    <AppModal
      :open="detailOpen"
      :title="selectedSummary ? `Detail stok opname #${selectedSummary.id}` : 'Detail stok opname'"
      :description="selectedSummary ? `${selectedSummary.branch} | ${selectedSummary.status}` : 'Detail produk dan aksi approval stok opname.'"
      size="7xl"
      @close="closeDetailModal"
    >
      <section>
        <h3 class="text-lg font-semibold text-slate-900">Status pelaksanaan</h3>
        <p class="mt-1 text-sm text-slate-500">Jadwal dibuat di ERP, proses start dan finish dilakukan petugas melalui WMS mobile.</p>

        <div v-if="selectedSummary" class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
          <p><span class="font-medium text-slate-900">ID:</span> {{ selectedSummary.id }}</p>
          <p class="mt-1"><span class="font-medium text-slate-900">Cabang:</span> {{ selectedSummary.branch }}</p>
          <p class="mt-1"><span class="font-medium text-slate-900">Tanggal pelaksanaan:</span> {{ selectedSummary.executionDate }}</p>
          <p class="mt-1"><span class="font-medium text-slate-900">Status:</span> {{ selectedSummary.status }}</p>
          <p v-if="selectedSummary.startedAt !== '-'" class="mt-1"><span class="font-medium text-slate-900">Mulai:</span> {{ selectedSummary.startedAt }}</p>
          <p v-if="selectedSummary.finishedAt !== '-'" class="mt-1"><span class="font-medium text-slate-900">Selesai:</span> {{ selectedSummary.finishedAt }}</p>
          <p class="mt-1"><span class="font-medium text-slate-900">Catatan:</span> {{ selectedSummary.note }}</p>
        </div>

        <div class="mt-4">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h4 class="text-sm font-semibold uppercase tracking-[0.18em] text-slate-500">Detail Produk</h4>
              <p class="mt-1 text-xs text-slate-500">
                Koreksi fisik dilakukan pada proses eskalasi; approval memakai snapshot hasil hitung WMS.
              </p>
            </div>
            <button
              class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50"
              :disabled="!detailRows.length || isFinalStatus || canApproveReject"
              @click="editMode = !editMode"
            >
              {{ editMode ? 'Kunci Detail' : 'Edit Detail Eskalasi' }}
            </button>
            <button
              class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
              :disabled="!detailRows.length"
              @click="exportStockOpnameDetail"
            >
              Export Detail
            </button>
          </div>
          <div class="mt-3">
            <div v-if="editMode && detailRows.length" class="max-h-[48vh] overflow-auto rounded-2xl border border-slate-200">
              <table class="min-w-full divide-y divide-slate-200 text-sm">
                <thead class="sticky top-0 bg-slate-50 text-left text-xs uppercase tracking-[0.18em] text-slate-500">
                  <tr>
                    <th class="px-4 py-3">Produk</th>
                    <th class="px-4 py-3">Sistem</th>
                    <th class="px-4 py-3">Fisik</th>
                    <th class="px-4 py-3">Good</th>
                    <th class="px-4 py-3">Bad</th>
                    <th class="px-4 py-3">Harga</th>
                    <th class="px-4 py-3">Selisih</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white">
                  <tr v-for="{ item, originalIndex } in paginatedDetailRows" :key="`${item.id_produk}-${originalIndex}`">
                    <td class="px-4 py-3 align-top">
                      <p class="font-medium text-slate-900">{{ item.nama_produk || '-' }}</p>
                      <p class="mt-1 text-xs text-slate-500">{{ item.kode_sku || `Produk #${item.id_produk}` }}</p>
                    </td>
                    <td class="px-4 py-3 align-top text-slate-700">{{ item.stok_sistem || 0 }}</td>
                    <td class="px-4 py-3 align-top">
                      <input
                        type="number"
                        :value="item.stok"
                        class="w-24 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
                        @input="updateDetailRow(originalIndex, 'stok', $event.target.value)"
                      />
                    </td>
                    <td class="px-4 py-3 align-top text-slate-700">{{ item.good_stock || 0 }}</td>
                    <td class="px-4 py-3 align-top">
                      <input
                        type="number"
                        :value="item.bad_stock"
                        class="w-24 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
                        @input="updateDetailRow(originalIndex, 'bad_stock', $event.target.value)"
                      />
                    </td>
                    <td class="px-4 py-3 align-top">
                      <input
                        type="number"
                        :value="item.harga"
                        class="w-28 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400"
                        @input="updateDetailRow(originalIndex, 'harga', $event.target.value)"
                      />
                    </td>
                    <td class="px-4 py-3 align-top">
                      <p class="font-medium text-slate-900">{{ Number(item.selisih || 0).toLocaleString('id-ID') }}</p>
                      <p class="mt-1 text-xs text-slate-500">Rp {{ Number(item.subtotal_selisih || 0).toLocaleString('id-ID') }}</p>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="editMode && detailRows.length > detailEditPageSize" class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              <div>
                Menampilkan <span class="font-semibold text-slate-900">{{ detailEditStartRow + 1 }}</span>-<span class="font-semibold text-slate-900">{{ detailEditEndRow }}</span>
                dari <span class="font-semibold text-slate-900">{{ detailRows.length }}</span> produk
              </div>
              <div class="flex items-center gap-2">
                <select v-model.number="detailEditPageSize" class="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none" @change="detailEditPage = 1">
                  <option :value="10">10</option>
                  <option :value="15">15</option>
                  <option :value="25">25</option>
                  <option :value="50">50</option>
                </select>
                <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50" :disabled="detailEditPage <= 1" @click="previousDetailEditPage">Sebelumnya</button>
                <span>Hal {{ detailEditPage }} / {{ detailEditTotalPages }}</span>
                <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50" :disabled="detailEditPage >= detailEditTotalPages" @click="nextDetailEditPage">Berikutnya</button>
              </div>
            </div>

            <AppTable
              v-else
              :rows="detailTableRows"
              :columns="[
                { key: 'kode_sku', label: 'SKU' },
                { key: 'nama_produk', label: 'Produk' },
                { key: 'stok_sistem', label: 'Stok Sistem' },
                { key: 'stok_fisik', label: 'Stok Fisik' },
                { key: 'good_stock', label: 'Good' },
                { key: 'bad_stock', label: 'Bad' },
                { key: 'selisih_label', label: 'Selisih' },
                { key: 'subtotal_label', label: 'Subtotal' },
                { key: 'subtotal_selisih_label', label: 'Nilai Selisih' }
              ]"
              :loading="detailLoading"
              empty-message="Klik baris stok opname untuk melihat detail produk."
            />
          </div>

          <div v-if="detailRows.length" class="mt-3 grid gap-3 sm:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Opname</p>
              <p class="mt-2 text-lg font-semibold text-slate-900">Rp {{ Number(totalOpname).toLocaleString('id-ID') }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Selisih</p>
              <p class="mt-2 text-lg font-semibold text-slate-900">Rp {{ Number(totalSelisih).toLocaleString('id-ID') }}</p>
            </div>
          </div>
        </div>

        <div class="mt-4 space-y-3">
          <AppFormField v-model="actionForm.id_stock_opname" label="ID Stok Opname" />
          <AppFormField v-model="actionForm.keterangan" label="Keterangan Approval" placeholder="Opsional: isi alasan approve / reject" />
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            :disabled="!!actionLoading || !canApproveReject"
            @click="runAction('accept')"
          >
            {{ actionLoading === 'accept' ? 'Approve...' : 'Approve' }}
          </button>
          <button
            class="rounded-xl border border-amber-200 px-4 py-2 text-sm font-medium text-amber-700 disabled:opacity-60"
            :disabled="!!actionLoading || !canEscalate"
            @click="runAction('escalate')"
          >
            {{ actionLoading === 'escalate' ? 'Eskalasi...' : 'Eskalasi' }}
          </button>
          <button
            class="rounded-xl border border-emerald-200 px-4 py-2 text-sm font-medium text-emerald-700 disabled:opacity-60"
            :disabled="!!actionLoading || !canCloseEscalation"
            @click="runAction('close-escalation')"
          >
            {{ actionLoading === 'close-escalation' ? 'Menutup...' : 'Tutup Eskalasi' }}
          </button>
          <button
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60"
            :disabled="!!actionLoading || !canApproveReject"
            @click="runAction('reject')"
          >
            {{ actionLoading === 'reject' ? 'Reject...' : 'Reject' }}
          </button>
        </div>

      </section>
    </AppModal>
  </div>
</template>
