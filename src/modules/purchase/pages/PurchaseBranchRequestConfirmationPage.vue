<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  approvePurchaseOrderRequest,
  getPurchaseOrderDetail,
  getPurchaseOrders,
  rejectPurchaseOrderRequest
} from '@/api/purchase';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  canAccessAllPurchaseBranches,
  getPurchaseBranchOptions,
  getPurchaseCompanyIdsForBranch,
  getPurchaseCompanyOptions,
  getPurchaseFallbackBranchId,
  getPurchaseFallbackCompanyId,
  getPurchasePrincipalOptions
} from '@/modules/purchase/utils/purchaseScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { useAuthStore } from '@/stores/auth';
import { canAccessRoleGroups, isCurrentUserPic } from '@/utils/roleAccess';

const authStore = useAuthStore();
const router = useRouter();

const filters = reactive({
  branchId: '',
  companyId: '',
  principalId: '',
  status: '1',
  search: ''
});

const rejectForm = reactive({
  reason: ''
});

const loading = ref(false);
const detailLoading = ref(false);
const submitLoading = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const rows = ref([]);
const selectedRow = ref(null);
const selectedDetail = ref(null);
const detailModalOpen = ref(false);
const fallbackBranchId = computed(() => getPurchaseFallbackBranchId(authStore));
const fallbackCompanyId = computed(() => getPurchaseFallbackCompanyId(authStore));
const canAccessAllBranches = computed(() => canAccessAllPurchaseBranches(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);
const canProcessPurchaseAction = computed(() => canAccessRoleGroups(authStore, ['purchase']));
const selectedRequestStatus = computed(() => Number(selectedDetail.value?.proses_id_berjalan || selectedRow.value?.proses_id_berjalan || 0));
const canProcessSelectedRequest = computed(() => canProcessPurchaseAction.value && selectedRequestStatus.value === 1);
const canReviseSelectedRequest = computed(() =>
  [1, 2].includes(selectedRequestStatus.value) &&
  (canProcessPurchaseAction.value || isCurrentUserPic(authStore, selectedRow.value, ['pic_order_nama']))
);

const statusOptions = [
  { value: '', label: 'Semua tahap / riwayat' },
  { value: '1', label: 'Request — menunggu approval cabang' },
  { value: '2', label: 'Need Confirm — sudah disetujui cabang' },
  { value: '3', label: 'In Transit — proses penerimaan' },
  { value: '4', label: 'Closed / ditolak' }
];

const filterFields = computed(() => [
  {
    key: 'companyId',
    label: 'Perusahaan',
    type: 'search-select',
    options: companyOptions.value,
    disabled: canUseLoginScope.value && !!fallbackCompanyId.value
  },
  {
    key: 'branchId',
    label: 'Cabang',
    type: 'search-select',
    options: branchOptions.value,
    disabled: (canUseLoginScope.value && !filters.companyId) || (!canAccessAllBranches.value && !!fallbackBranchId.value)
  },
  {
    key: 'principalId',
    label: 'Principal',
    type: 'search-select',
    options: principalOptions.value
  },
  {
    key: 'status',
    label: 'Tahap Request',
    type: 'search-select',
    options: statusOptions
  },
  {
    key: 'search',
    label: 'Cari',
    placeholder: 'Kode request / principal / cabang / catatan'
  }
]);

const companyOptions = computed(() =>
  getPurchaseCompanyOptions(companyRows.value, branchRows.value, filters.branchId, authStore)
);

const branchOptions = computed(() =>
  getPurchaseBranchOptions(branchRows.value, authStore, filters.companyId, companyRows.value)
);

const principalOptions = computed(() =>
  getPurchasePrincipalOptions(principalRows.value, filters.companyId)
);

const tableRows = computed(() =>
  rows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;
      return [item.kode, item.keterangan, item.principal_nama, item.cabang_nama, item.pic_order_nama]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      total_label: formatCurrency(item.total || 0),
      request_pic_label: item.pic_order_nama || '-',
      status_label: resolveRequestStatus(item.proses_id_berjalan)
    }))
);

const detailRows = computed(() =>
  normalizeList(selectedDetail.value?.detail).map((item, index) => {
    const qtyRows = normalizeList(item.jumlah);
    const subtotal = Number(item.subtotal || qtyRows.reduce((sum, qty) => sum + Number(qty.subtotal || 0), 0));
    return {
      ...item,
      row_key: `${item.id || item.produk_id || index}`,
      subtotal,
      subtotal_label: formatCurrency(subtotal),
      harga_label: formatCurrency(item.produk_harga_beli || 0),
      rincian_uom: qtyRows
        .filter((qty) => Number(qty.jumlah || 0) > 0)
        .map((qty) => `${qty.jumlah || 0} ${qty.uom_kode || qty.uom_nama || ''}`.trim())
        .join(', ') || '-'
    };
  })
);

const summaryCards = computed(() => {
  const total = tableRows.value.length;
  const nominal = tableRows.value.reduce((sum, item) => sum + Number(item.total || 0), 0);
  const pending = tableRows.value.filter((item) => Number(item.proses_id_berjalan || 0) === 1).length;
  const needConfirm = tableRows.value.filter((item) => Number(item.proses_id_berjalan || 0) === 2).length;
  const sku = detailRows.value.length;
  const selectedNominal = Number(selectedDetail.value?.total || selectedRow.value?.total || 0);
  return [
    { label: 'PO pada Filter', value: String(total) },
    { label: 'Menunggu Approval', value: String(pending) },
    { label: 'Need Confirm', value: String(needConfirm) },
    { label: 'Nilai pada Filter', value: formatCurrency(nominal) },
    { label: 'SKU Dipilih', value: String(sku) },
    { label: 'Nilai Dipilih', value: formatCurrency(selectedNominal) }
  ];
});

const selectedStatusMessage = computed(() => {
  const map = {
    1: 'Request ini menunggu approval cabang. Anda dapat menyetujui, menolak, atau merevisi request.',
    2: 'Request ini sudah disetujui cabang dan sedang menunggu proses konfirmasi purchase order.',
    3: 'Purchase order sedang berada pada proses penerimaan barang.',
    4: 'Purchase order sudah ditutup atau request sebelumnya ditolak. Gunakan riwayat untuk melihat catatan prosesnya.'
  };
  return map[selectedRequestStatus.value] || 'Status request belum dikenali. Periksa riwayat purchase order.';
});

const tableEmptyMessage = computed(() =>
  filters.status
    ? 'Belum ada purchase order pada tahap yang dipilih.'
    : 'Belum ada riwayat request cabang pada filter ini.'
);

function resolveRequestStatus(value) {
  const status = Number(value || 0);
  const map = {
    1: { text: 'Request', className: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700' },
    2: { text: 'Need Confirm', className: 'inline-flex rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-700' },
    3: { text: 'In Transit', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Closed / Ditolak', className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700' }
  };
  return map[status] || { text: `Status ${status || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function normalizeNullableNumber(value) {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildUserPayload() {
  return {
    user_id: normalizeNullableNumber(authStore.user?.id ?? authStore.user?.id_user),
    user_jabatan_id: normalizeNullableNumber(authStore.user?.id_jabatan ?? authStore.user?.jabatan_id)
  };
}

async function loadMeta() {
  const [companies, branches, principals] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
  companyRows.value = normalizeList(unwrapResponse(companies));
  branchRows.value = normalizeList(unwrapResponse(branches));
  principalRows.value = normalizeList(unwrapResponse(principals));
  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

async function loadRows() {
  loading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  selectedRow.value = null;
  selectedDetail.value = null;
  detailModalOpen.value = false;
  rejectForm.reason = '';
  try {
    const params = {};
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    if (filters.status) params.status = filters.status;
    const response = await getPurchaseOrders(params);
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Daftar request cabang belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  selectedDetail.value = null;
  detailModalOpen.value = true;
  detailLoading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  rejectForm.reason = '';
  try {
    const response = await getPurchaseOrderDetail(row.id);
    selectedDetail.value = unwrapResponse(response);
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = normalizeError(error, 'Detail request cabang belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
}

async function approveSelected() {
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih request cabang terlebih dahulu.';
    return;
  }
  submitLoading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await approvePurchaseOrderRequest({
      order_id: selectedRow.value.id,
      ...buildUserPayload()
    });
    successMessage.value = `Request ${selectedRow.value.kode} berhasil disetujui.`;
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Request cabang belum berhasil disetujui.');
  } finally {
    submitLoading.value = false;
  }
}

async function rejectSelected() {
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih request cabang terlebih dahulu.';
    return;
  }
  if (!rejectForm.reason.trim()) {
    errorMessage.value = 'Catatan penolakan wajib diisi.';
    return;
  }
  submitLoading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await rejectPurchaseOrderRequest({
      order_id: selectedRow.value.id,
      keterangan: rejectForm.reason.trim(),
      ...buildUserPayload()
    });
    successMessage.value = `Request ${selectedRow.value.kode} berhasil ditolak.`;
    await loadRows();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Request cabang belum berhasil ditolak.');
  } finally {
    submitLoading.value = false;
  }
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.status = '1';
  filters.search = '';
  syncBranchFromCompany();
  loadRows();
}

function showAllHistory() {
  filters.status = '';
  loadRows();
}

function updateFilters(nextFilters) {
  Object.assign(filters, nextFilters || {});
  syncBranchFromCompany();
  syncPrincipalFromCompany();
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (canAccessAllBranches.value) filters.branchId = '';
    filters.principalId = '';
    return;
  }

  if (
    filters.branchId &&
    !getPurchaseCompanyIdsForBranch(filters.branchId, branchRows.value, companyRows.value).includes(String(filters.companyId))
  ) {
    filters.branchId = '';
    filters.principalId = '';
  }
}

function syncPrincipalFromCompany() {
  if (filters.principalId && !principalOptions.value.some((item) => item.value === String(filters.principalId))) {
    filters.principalId = '';
  }
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
  (branchId, previousBranchId) => {
    if (String(branchId || '') !== String(previousBranchId || '')) {
      filters.principalId = '';
    }
  }
);

onMounted(async () => {
  await loadMeta();
  await loadRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Request Cabang & Approval Purchase"
      description="Buat request cabang, validasi tahap Request, lalu telusuri riwayat hingga penerimaan barang tanpa membuat alur API baru."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white hover:bg-brand-700" @click="router.push({ name: 'purchase-branch-requests-create' })">
          Buat Request Cabang
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/orders')">
          Monitoring PO
        </button>
      </div>
    </PageHeader>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadRows" @reset="resetFilters" />

    <section v-if="successMessage" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ successMessage }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
      <article v-for="card in summaryCards" :key="card.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ card.value }}</p>
      </article>
    </section>

    <section class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Daftar Request & Riwayat</h3>
          <p class="text-sm text-slate-500">Pilih tahap untuk melihat request yang menunggu approval maupun riwayat prosesnya.</p>
        </div>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="showAllHistory">
          Lihat Semua Riwayat
        </button>
      </div>

      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'kode', label: 'Kode Request' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'status_label', label: 'Status' },
          { key: 'total_label', label: 'Nilai' },
          { key: 'request_pic_label', label: 'PIC Request' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        :empty-message="tableEmptyMessage"
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.kode || 'Detail Request Cabang'"
      :description="selectedRow?.keterangan || 'Rincian request dan aksi approve/reject.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail request...
      </div>

      <div v-else-if="!selectedRow" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500">
        Detail request belum tersedia.
      </div>

      <div v-else class="space-y-5">
          <div class="rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-700">
            {{ selectedStatusMessage }}
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Cabang</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow.cabang_nama || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Principal</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow.principal_nama || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Total</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(selectedRow.total || selectedDetail?.total || 0) }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PIC Request</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail?.request_log?.user_nama || selectedRow.pic_order_nama || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Tahap Saat Ini</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ resolveRequestStatus(selectedRequestStatus).text }}</p>
            </article>
          </div>

          <div>
            <p class="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Rincian Produk</p>
            <AppTable
              :rows="detailRows"
              :columns="[
                { key: 'produk_kode', label: 'Kode Produk' },
                { key: 'produk_nama', label: 'Nama Produk' },
                { key: 'harga_label', label: 'Harga' },
                { key: 'total_order', label: 'Total' },
                { key: 'rincian_uom', label: 'Rincian UOM' },
                { key: 'subtotal_label', label: 'Subtotal' }
              ]"
              empty-message="Belum ada detail produk pada request ini."
            />
          </div>

          <div class="rounded-2xl border border-slate-200 p-4">
            <AppFormField v-if="canProcessSelectedRequest" v-model="rejectForm.reason" label="Catatan Penolakan" placeholder="Wajib diisi jika request ditolak" />
            <div class="mt-4 flex flex-wrap gap-3">
              <button v-if="canProcessSelectedRequest" class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" :disabled="submitLoading" @click="approveSelected">
                {{ submitLoading ? 'Memproses...' : 'Setujui Request' }}
              </button>
              <button v-if="canProcessSelectedRequest" class="rounded-xl border border-rose-200 px-4 py-3 text-sm font-medium text-rose-700" :disabled="submitLoading" @click="rejectSelected">
                Tolak Request
              </button>
              <button v-if="canReviseSelectedRequest" class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push(`/purchase/orders/edit/${selectedRow.id}`)">
                Edit/Revisi
              </button>
              <p v-if="!canProcessSelectedRequest && !canReviseSelectedRequest" class="py-3 text-sm text-slate-500">
                Tidak ada aksi approval pada tahap ini. Riwayat tetap dapat dibaca dari detail purchase order.
              </p>
            </div>
          </div>
      </div>
    </AppModal>
  </div>
</template>
