<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  confirmPurchaseOrder,
  getPurchaseOrderConfirmationQueue,
  getPurchaseOrderDetail
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
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import { useAuthStore } from '@/stores/auth';
import { canAccessRoleGroups } from '@/utils/roleAccess';

const authStore = useAuthStore();
const router = useRouter();

const filters = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  search: ''
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
    options: filteredPrincipalOptions.value
  },
  {
    key: 'search',
    label: 'Cari',
    placeholder: 'Kode PO / principal / cabang'
  }
]);

const companyOptions = computed(() =>
  getPurchaseCompanyOptions(companyRows.value, branchRows.value, filters.branchId, authStore)
);

const branchOptions = computed(() =>
  getPurchaseBranchOptions(branchRows.value, authStore, filters.companyId, companyRows.value)
);

const filteredPrincipalOptions = computed(() =>
  getPurchasePrincipalOptions(principalRows.value, filters.companyId)
);

const summaryCards = computed(() => {
  const total = rows.value.length;
  const totalNominal = rows.value.reduce((sum, item) => sum + Number(item.total_derived || 0), 0);
  return [
    { label: 'Need Confirm', value: String(total) },
    { label: 'Cabang Aktif', value: filters.branchId || '-' },
    { label: 'Estimasi Nilai', value: formatCurrency(totalNominal) }
  ];
});

const tableRows = computed(() =>
  rows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;
      return [item.kode, item.principal_nama, item.cabang_nama, item.keterangan, item.pic_order_nama]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      total_label: formatCurrency(item.total_derived || 0)
    }))
);

const detailRows = computed(() =>
  normalizeList(selectedDetail.value?.detail).map((item, index) => {
    const qtyRows = normalizeList(item.jumlah);
    const derivedSubtotal = qtyRows.reduce((sum, qty) => sum + Number(qty.subtotal || 0), 0);

    return {
      ...item,
      row_key: `${item.id || item.produk_kode || index}`,
      subtotal_label: formatCurrency(item.subtotal ?? derivedSubtotal),
      jumlah_ringkas: qtyRows
        .map((qty) => `${qty.jumlah || 0} ${qty.uom_kode || qty.uom_nama || ''}`.trim())
        .join(', '),
      qty_rows: qtyRows
    };
  })
);

const derivedDetailTotal = computed(() =>
  detailRows.value.reduce((sum, item) => sum + Number(item.subtotal ?? 0) + 0, 0)
);

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function normalizeNullableNumber(value) {
  if (value === '' || value === null || value === undefined) {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildDerivedTotal(orderDetail) {
  return normalizeList(orderDetail?.detail).reduce((sum, item) => {
    const qtyRows = normalizeList(item.jumlah);
    return sum + qtyRows.reduce((lineSum, qty) => lineSum + Number(qty.subtotal || 0), 0);
  }, 0);
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.search = '';
  syncBranchFromCompany();
  loadQueue();
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
  if (filters.principalId && !filteredPrincipalOptions.value.some((item) => item.value === String(filters.principalId))) {
    filters.principalId = '';
  }
}

async function loadQueue() {
  loading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  selectedRow.value = null;
  selectedDetail.value = null;
  detailModalOpen.value = false;
  try {
    const params = {};
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    const response = await getPurchaseOrderConfirmationQueue(params);
    const baseRows = normalizeList(unwrapResponse(response));

    rows.value = await Promise.all(
      baseRows.map(async (item) => {
        try {
          const detailResponse = await getPurchaseOrderDetail(item.id);
          const detail = unwrapResponse(detailResponse);
          return {
            ...item,
            total_derived: buildDerivedTotal(detail)
          };
        } catch {
          return {
            ...item,
            total_derived: 0
          };
        }
      })
    );
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Daftar konfirmasi PO belum bisa dimuat.');
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
  try {
    const response = await getPurchaseOrderDetail(row.id);
    selectedDetail.value = unwrapResponse(response);
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = normalizeError(error, 'Detail purchase order belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
}

async function submitConfirmation() {
  if (!selectedRow.value || !selectedDetail.value) {
    errorMessage.value = 'Pilih PO yang ingin dikonfirmasi terlebih dahulu.';
    return;
  }

  submitLoading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await confirmPurchaseOrder({
      order_id: selectedRow.value.id,
      user_id: normalizeNullableNumber(authStore.user?.id ?? authStore.user?.id_user),
      user_jabatan_id: normalizeNullableNumber(authStore.user?.id_jabatan ?? authStore.user?.jabatan_id),
      total: derivedDetailTotal.value
    });

    successMessage.value = `PO ${selectedRow.value.kode} berhasil dikonfirmasi. Lanjutkan ke input penerimaan barang.`;
    const confirmedCode = selectedRow.value.kode;
    await loadQueue();
    router.push({
      path: '/purchase/receipts/create',
      query: {
        branchId: filters.branchId || '',
        companyId: filters.companyId || '',
        principalId: filters.principalId || '',
        orderCode: confirmedCode
      }
    });
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Approval Purchase Order belum berhasil diproses.');
  } finally {
    submitLoading.value = false;
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
  await loadQueue();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Approval Purchase Order"
      description="Tahap approval purchase order sebelum order diproses ke penerimaan barang. Cocok untuk PO status Need Confirm seperti 0095."
    />

    <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadQueue" @reset="resetFilters" />

    <section v-if="successMessage" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ successMessage }}
    </section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-3">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold text-slate-900">Antrian Approval Purchase Order</h3>
      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'kode', label: 'Kode PO' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'pic_order_nama', label: 'PIC Request' },
          { key: 'total_label', label: 'Estimasi Nilai' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada purchase order yang menunggu konfirmasi."
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.kode || 'Detail Approval Purchase Order'"
      :description="selectedDetail?.keterangan || selectedRow?.keterangan || 'Detail produk dan rincian UOM sebelum PO dikonfirmasi.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail purchase order...
      </div>

      <div v-else-if="!selectedDetail" class="rounded-2xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
        Detail PO belum tersedia.
      </div>

      <div v-else class="space-y-5">
          <div class="rounded-2xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-700">
            Setelah dikonfirmasi, PO akan lanjut ke tahap input penerimaan barang.
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Cabang</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow?.cabang_nama || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Principal</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow?.principal_nama || '-' }}</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PIC Request</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow?.pic_order_nama || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Estimasi Total</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(derivedDetailTotal) }}</p>
            </div>
          </div>

          <div>
            <p class="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Rincian Produk</p>
            <AppTable
              :rows="detailRows"
              :columns="[
                { key: 'produk_kode', label: 'Kode Produk' },
                { key: 'produk_nama', label: 'Nama Produk' },
                { key: 'total_order', label: 'Total Order' },
                { key: 'total_tersisa', label: 'Sisa' },
                { key: 'subtotal_label', label: 'Subtotal' },
                { key: 'jumlah_ringkas', label: 'Rincian UOM' }
              ]"
              empty-message="Belum ada rincian produk."
            />
          </div>

          <div class="flex flex-wrap gap-3">
            <button
              v-if="canProcessPurchaseAction"
              class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white"
              :disabled="submitLoading"
              @click="submitConfirmation"
            >
              {{ submitLoading ? 'Memproses...' : 'Approval Purchase Order' }}
            </button>
            <button
              v-if="canProcessPurchaseAction"
              class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700"
              @click="router.push('/purchase/receipts/create')"
            >
              Buka Input Receipt
            </button>
          </div>
      </div>
    </AppModal>
  </div>
</template>
