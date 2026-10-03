<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  confirmPurchaseReceipt,
  getPurchaseConfirmationQueue,
  getPurchaseReceiptDetail
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
import { canAccessRoleGroups } from '@/utils/roleAccess';

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const filters = reactive({
  companyId: '',
  branchId: '',
  principalId: '',
  search: ''
});

const form = reactive({
  jatuh_tempo: '',
  potongan: '',
  biaya_lainnya: ''
});

const loading = ref(false);
const detailLoading = ref(false);
const submitLoading = ref(false);
const errorMessage = ref('');
const successMessage = ref('');
const successToast = ref('');
let toastTimer = null;
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const rows = ref([]);
const selectedRow = ref(null);
const selectedDetail = ref(null);
const detailModalOpen = ref(false);
const lastConfirmedMeta = ref(null);
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
    placeholder: 'No transaksi / kode order / principal'
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
  const subtotal = rows.value.reduce((sum, item) => sum + Number(item.subtotal || 0), 0);
  return [
    { label: 'Butuh Konfirmasi', value: String(total) },
    { label: 'Total Subtotal', value: formatCurrency(subtotal) },
    { label: 'Cabang Aktif', value: filters.branchId || '-' }
  ];
});

const tableRows = computed(() =>
  rows.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;
      return [
        item.no_transaksi,
        item.order_kode,
        item.principal_nama,
        item.cabang_nama,
        item.keterangan
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      subtotal_label: formatCurrency(item.subtotal || 0),
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      order_code_label: item.order_kode || '-'
    }))
);

const detailRows = computed(() =>
  normalizeList(selectedDetail.value?.detail).map((item, index) => ({
    ...item,
    row_key: `${item.id || item.order_detail_id || index}`,
    subtotal_label: formatCurrency(item.subtotal || 0),
    jumlah_ringkas: normalizeList(item.jumlah)
      .map((qty) => `${qty.jumlah || 0} ${qty.uom_kode || qty.uom_nama || ''}`.trim())
      .join(', ')
  }))
);

const projectedTotal = computed(() => {
  const subtotal = Number(selectedDetail.value?.subtotal || selectedRow.value?.subtotal || 0);
  const potongan = Number(form.potongan || 0);
  const biayaLain = Number(form.biaya_lainnya || 0);
  const beforePpn = subtotal - potongan;
  const ppn = beforePpn * 0.11;
  return beforePpn + ppn + biayaLain;
});

const projectedBreakdown = computed(() => {
  const subtotal = Number(selectedDetail.value?.subtotal || selectedRow.value?.subtotal || 0);
  const potongan = Number(form.potongan || 0);
  const biayaLain = Number(form.biaya_lainnya || 0);
  const dpp = Math.max(0, subtotal - potongan);
  const ppn = dpp * 0.11;
  return {
    subtotal,
    potongan,
    biayaLain,
    dpp,
    ppn,
    total: dpp + ppn + biayaLain
  };
});

const canConfirm = computed(() => canProcessPurchaseAction.value && Number(selectedRow.value?.proses_id_berjalan || selectedDetail.value?.proses_id_berjalan || 0) === 2);

const statusHint = computed(() => {
  if (!selectedRow.value) {
    return 'Pilih transaksi di kiri untuk mengisi formulir konfirmasi purchase.';
  }
  return canConfirm.value
    ? 'Transaksi ini valid untuk dikonfirmasi. Pastikan jatuh tempo dan komponen biaya sudah sesuai sebelum dikirim.'
    : 'Transaksi ini tidak lagi berada di status konfirmasi purchase. Gunakan halaman receipt atau tagihan sesuai tahapnya.';
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function showToast(message) {
  successToast.value = message;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    successToast.value = '';
  }, 3200);
}

function normalizeNullableNumber(value) {
  if (value === '' || value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.search = '';
  syncBranchFromCompany();
  loadQueue();
}

function resetForm() {
  form.jatuh_tempo = '';
  form.potongan = '';
  form.biaya_lainnya = '';
}

function hydrateFormFromDetail() {
  form.jatuh_tempo = selectedDetail.value?.jatuh_tempo || '';
  form.potongan = Number(selectedDetail.value?.potongan || 0) ? String(selectedDetail.value.potongan) : '';
  form.biaya_lainnya = Number(selectedDetail.value?.biaya_lainnya || 0) ? String(selectedDetail.value.biaya_lainnya) : '';
}

async function loadMeta() {
  const [companies, branches, principals] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
  companyRows.value = normalizeList(unwrapResponse(companies));
  branchRows.value = normalizeList(unwrapResponse(branches));
  principalRows.value = normalizeList(unwrapResponse(principals));

  if (!filters.branchId && route.query.branchId) {
    filters.branchId = String(route.query.branchId);
  } else if (!filters.branchId && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  if (!filters.companyId && route.query.companyId) {
    filters.companyId = String(route.query.companyId);
  } else if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.principalId && route.query.principalId) {
    filters.principalId = String(route.query.principalId);
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
  try {
    const params = {};
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    const response = await getPurchaseConfirmationQueue(params);
    rows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    rows.value = [];
    errorMessage.value = normalizeError(error, 'Daftar konfirmasi purchase belum bisa dimuat.');
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
  resetForm();
  try {
    const response = await getPurchaseReceiptDetail(row.id);
    selectedDetail.value = unwrapResponse(response);
    hydrateFormFromDetail();
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = normalizeError(error, 'Detail transaksi purchase belum bisa dimuat.');
  } finally {
    detailLoading.value = false;
  }
}

function closeDetailModal() {
  detailModalOpen.value = false;
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

async function submitConfirmation() {
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih transaksi yang ingin dikonfirmasi terlebih dahulu.';
    return;
  }
  if (!canConfirm.value) {
    errorMessage.value = 'Status transaksi ini tidak lagi valid untuk konfirmasi purchase.';
    return;
  }
  if (!form.jatuh_tempo) {
    errorMessage.value = 'Jatuh tempo wajib diisi sebelum konfirmasi purchase.';
    return;
  }
  if (Number(form.potongan || 0) < 0 || Number(form.biaya_lainnya || 0) < 0) {
    errorMessage.value = 'Potongan dan biaya lainnya tidak boleh bernilai negatif.';
    return;
  }
  if (Number(form.potongan || 0) > Number(selectedDetail.value?.subtotal || selectedRow.value?.subtotal || 0)) {
    errorMessage.value = 'Potongan tidak boleh lebih besar dari subtotal transaksi.';
    return;
  }

  submitLoading.value = true;
  errorMessage.value = '';
  successMessage.value = '';
  try {
    await confirmPurchaseReceipt({
      order_id: selectedRow.value.id,
      user_id: normalizeNullableNumber(authStore.user?.id ?? authStore.user?.id_user),
      user_jabatan_id: normalizeNullableNumber(authStore.user?.id_jabatan ?? authStore.user?.jabatan_id),
      jatuh_tempo: form.jatuh_tempo || undefined,
      potongan: Number(form.potongan || 0),
      biaya_lainnya: Number(form.biaya_lainnya || 0)
    });
    successMessage.value = `Transaksi ${selectedRow.value.no_transaksi || selectedRow.value.id} berhasil dikonfirmasi purchase.`;
    showToast(successMessage.value);
    lastConfirmedMeta.value = {
      principalId: selectedRow.value.principal_id || selectedDetail.value?.principal_id || filters.principalId || '',
      companyId: selectedRow.value.id_perusahaan || selectedDetail.value?.id_perusahaan || filters.companyId || '',
      branchId: selectedRow.value.cabang_id || selectedDetail.value?.cabang_id || filters.branchId || ''
    };
    await loadQueue();
    selectedDetail.value = null;
    selectedRow.value = null;
    detailModalOpen.value = false;
    resetForm();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Konfirmasi purchase belum berhasil diproses.');
  } finally {
    submitLoading.value = false;
  }
}

function openBillsPage() {
  router.push({
    path: '/purchase/bills',
    query: {
      principalId: lastConfirmedMeta.value?.principalId || '',
      companyId: lastConfirmedMeta.value?.companyId || '',
      branchId: lastConfirmedMeta.value?.branchId || ''
    }
  });
}

onMounted(async () => {
  await loadMeta();
  await loadQueue();
});
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>

    <PageHeader
      title="Finalisasi Purchase Order"
      description="Supervisor/admin purchase meninjau hasil penerimaan barang, menambahkan jatuh tempo, potongan, dan biaya lain sebelum transaksi masuk tahap tagihan."
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
      <h3 class="text-lg font-semibold text-slate-900">Antrian Konfirmasi</h3>
      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'no_transaksi', label: 'No Transaksi' },
          { key: 'order_code_label', label: 'Kode Order' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'subtotal_label', label: 'Subtotal' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada transaksi yang menunggu konfirmasi purchase."
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.no_transaksi || 'Form Finalisasi Purchase Order'"
      :description="selectedDetail?.keterangan || selectedRow?.keterangan || 'Periksa detail produk dan kirim konfirmasi purchase.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail transaksi...
      </div>

      <div v-else-if="!selectedDetail" class="rounded-2xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
        Detail transaksi belum tersedia.
      </div>

      <div v-else class="space-y-5">
          <div
            :class="[
              'rounded-2xl border px-4 py-3 text-sm',
              canConfirm
                ? 'border-brand-100 bg-brand-50 text-brand-700'
                : 'border-amber-200 bg-amber-50 text-amber-700'
            ]"
          >
            {{ statusHint }}
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Subtotal</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.subtotal) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Estimasi Total</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.total) }}</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-3">
            <AppFormField v-model="form.jatuh_tempo" label="Jatuh Tempo" type="date" :readonly="!canProcessPurchaseAction" />
            <AppFormField v-model="form.potongan" label="Potongan" type="number" min="0" :readonly="!canProcessPurchaseAction" />
            <AppFormField v-model="form.biaya_lainnya" label="Biaya Lainnya" type="number" min="0" :readonly="!canProcessPurchaseAction" />
          </div>

          <div class="grid gap-3 md:grid-cols-4">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">DPP</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.dpp) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PPN 11%</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.ppn) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Potongan</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.potongan) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Biaya Lainnya</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(projectedBreakdown.biayaLain) }}</p>
            </div>
          </div>

          <div>
            <p class="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Rincian Barang</p>
            <AppTable
              :rows="detailRows"
              :columns="[
                { key: 'produk_kode', label: 'Kode Produk' },
                { key: 'produk_nama', label: 'Nama Produk' },
                { key: 'batch_number', label: 'Batch' },
                { key: 'subtotal_label', label: 'Subtotal' },
                { key: 'jumlah_ringkas', label: 'Rincian UOM' }
              ]"
              empty-message="Belum ada rincian barang."
            />
          </div>

          <div class="flex flex-wrap gap-3">
            <button
              v-if="canConfirm"
              class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white"
              :disabled="submitLoading"
              @click="submitConfirmation"
            >
              {{ submitLoading ? 'Memproses...' : 'Finalisasi Purchase Order' }}
            </button>
            <button
              v-if="lastConfirmedMeta"
              class="rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm font-medium text-brand-700"
              @click="openBillsPage"
            >
              Lanjut ke Tagihan Purchase Order
            </button>
            <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="resetForm">
              Reset Form
            </button>
          </div>
      </div>
    </AppModal>
  </div>
</template>
