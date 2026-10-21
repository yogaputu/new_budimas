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
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { purchasePricing } from '../utils/purchasePricing';
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
  discount_type: 'AMOUNT',
  discount_value: '',
  biaya_lainnya: ''
});
const lineDiscounts = reactive({});

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

const projectedBreakdown = computed(() => purchasePricing(detailRows.value, form, lineDiscounts));
const pricedRows = computed(() => detailRows.value.map(row => ({ ...row,
  pricing: projectedBreakdown.value.lines.find(p => p.detail_id === Number(row.detail_id ?? row.id)) || {}
})));
const totalCards = computed(() => {
  const p = projectedBreakdown.value;
  return [
    ['DPP sebelum diskon', p.dpp_gross], ['Diskon produk', p.product_discount_total],
    ['Diskon keseluruhan', p.header_discount_amount], ['Total diskon', p.discount_total],
    ['DPP bersih', p.dpp_net], ['PPN setelah diskon', p.ppn], ['Biaya lainnya', p.other_cost],
    ['Total tagihan', p.total]
  ].map(([label, value]) => ({ label, value: formatCurrency(value) }));
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
  form.discount_type = 'AMOUNT';
  form.discount_value = '';
  form.biaya_lainnya = '';
  for (const key of Object.keys(lineDiscounts)) delete lineDiscounts[key];
  for (const row of detailRows.value) lineDiscounts[row.detail_id ?? row.id] = { discount_type: 'AMOUNT', discount_value: '' };
}

function hydrateFormFromDetail() {
  form.jatuh_tempo = selectedDetail.value?.jatuh_tempo || '';
  form.discount_type = selectedDetail.value?.financials?.discount_type || 'AMOUNT';
  form.discount_value = selectedDetail.value?.financials?.discount_value || '';
  form.biaya_lainnya = Number(selectedDetail.value?.biaya_lainnya || 0) ? String(selectedDetail.value.biaya_lainnya) : '';
  for (const row of detailRows.value) lineDiscounts[row.detail_id ?? row.id] = {
    discount_type: row.discount_type || 'AMOUNT', discount_value: row.discount_value || ''
  };
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
  if (projectedBreakdown.value.error) {
    errorMessage.value = projectedBreakdown.value.error;
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
      discount_type: form.discount_type,
      discount_value: String(form.discount_value || 0),
      line_discounts: Object.entries(lineDiscounts).map(([id, value]) => ({ detail_id: Number(id),
        discount_type: value.discount_type, discount_value: String(value.discount_value || 0) })),
      biaya_lainnya: String(form.biaya_lainnya || 0)
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

      <div v-else class="purchase-finalization-detail space-y-5">
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

          <div class="rounded-2xl border border-brand-200 bg-brand-50 p-4 text-sm text-brand-800 dark:border-brand-800 dark:bg-brand-950 dark:text-brand-100">
            Diskon produk dihitung lebih dahulu. Diskon keseluruhan dihitung dari sisa DPP setelah diskon produk,
            lalu dialokasikan proporsional. PPN mengikuti tarif tiap produk dari DPP bersih.
            Diskon rupiah produk adalah total potongan baris tersebut, bukan potongan per PCS.
            Jumlah dan harga penerimaan diverifikasi ulang oleh server saat finalisasi.
          </div>
          <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <AppFormField v-model="form.jatuh_tempo" label="Jatuh Tempo" type="date" :readonly="!canConfirm" />
            <label class="block text-sm font-medium text-slate-700 dark:text-slate-300">Jenis diskon keseluruhan
              <AppSelect2 v-model="form.discount_type" class="mt-1.5" aria-label="Jenis diskon keseluruhan" :disabled="!canConfirm">
                <option value="AMOUNT">Rupiah (Rp)</option><option value="PERCENT">Persen (%)</option>
              </AppSelect2>
            </label>
            <AppFormField v-model="form.discount_value" :label="form.discount_type === 'PERCENT' ? 'Diskon keseluruhan (%)' : 'Diskon keseluruhan (Rp)'"
              type="number" min="0" :max="form.discount_type === 'PERCENT' ? 100 : undefined" step="0.01" :readonly="!canConfirm" />
            <AppFormField v-model="form.biaya_lainnya" label="Biaya Lainnya (Rp)" type="number" min="0" step="0.01" :readonly="!canConfirm" />
          </div>
          <p v-if="errorMessage || projectedBreakdown.error" role="alert" class="rounded-xl bg-rose-50 p-3 text-sm text-rose-800 dark:bg-rose-950 dark:text-rose-200">
            {{ projectedBreakdown.error || errorMessage }}
          </p>

          <section aria-label="Rincian diskon per produk" class="space-y-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <h3 class="font-semibold text-slate-900 dark:text-slate-100">Rincian barang dan diskon produk</h3>
              <span class="rounded-full bg-brand-100 px-3 py-1 text-sm font-bold text-brand-800 dark:bg-brand-950 dark:text-brand-100" data-testid="total-pcs">
                Total {{ Number(projectedBreakdown.total_pcs || 0).toLocaleString('id-ID') }} PCS
              </span>
            </div>
            <p class="text-xs text-slate-500 dark:text-slate-400">Geser tabel ke samping untuk melihat seluruh kolom, termasuk Harga Bersih.</p>
            <div class="overflow-x-auto rounded-2xl border border-slate-200 dark:border-slate-700">
              <table class="min-w-[1400px] w-full text-left text-sm" aria-label="Tabel finalisasi produk">
                <thead class="bg-slate-100 text-xs uppercase text-slate-600 dark:bg-slate-800 dark:text-slate-300"><tr>
                  <th class="p-3">Kode Produk</th><th class="p-3">Nama Produk</th><th class="p-3">Batch</th>
                  <th class="p-3">Expired</th><th class="p-3">Rincian UOM</th><th class="p-3 text-right">TOTAL (PCS)</th>
                  <th class="p-3 text-right">Harga Pricelist</th><th class="p-3 min-w-[240px]">Diskon</th><th class="p-3 text-right">Harga Bersih</th>
                </tr></thead>
                <tbody class="divide-y divide-slate-200 bg-white dark:divide-slate-700 dark:bg-slate-900">
                  <tr v-for="(row,index) in pricedRows" :key="row.row_key" :data-testid="'discount-line-' + row.id">
                    <td class="p-3 align-top font-semibold">{{ row.produk_kode }}</td>
                    <td class="p-3 align-top min-w-[170px]">{{ row.produk_nama }}</td>
                    <td class="p-3 align-top">{{ row.batch_number || '-' }}</td>
                    <td class="p-3 align-top whitespace-nowrap">{{ String(row.tanggal_expired || '-').slice(0,10) }}</td>
                    <td class="p-3 align-top min-w-[150px]"><p v-for="(uom,u) in normalizeList(row.jumlah)" :key="u" class="whitespace-nowrap">
                      {{ Number(uom.jumlah || 0).toLocaleString('id-ID') }} {{ uom.uom_kode || uom.uom_nama }}
                      <span class="text-xs text-slate-500">× {{ uom.uom_faktor_konversi || 1 }} PCS</span>
                    </p></td>
                    <td class="p-3 align-top text-right font-semibold">{{ Number(row.quantity_pcs || 0).toLocaleString('id-ID') }}</td>
                    <td class="p-3 align-top text-right whitespace-nowrap"><p v-for="(uom,u) in normalizeList(row.jumlah)" :key="u">{{formatCurrency(uom.uom_harga_beli)}}<span class="text-xs text-slate-500"> / {{uom.uom_kode||uom.uom_nama}} · DPP</span></p>
                      <p class="mt-2 text-xs">Total {{ formatCurrency(row.pricing.dpp_gross) }}</p></td>
                    <td class="p-3 align-top space-y-2">
                      <AppSelect2 v-model="lineDiscounts[row.detail_id ?? row.id].discount_type" :aria-label="'Jenis diskon produk ' + (index + 1)" :disabled="!canConfirm">
                        <option value="AMOUNT">Rupiah (Rp)</option><option value="PERCENT">Persen (%)</option>
                      </AppSelect2>
                      <AppFormField v-model="lineDiscounts[row.detail_id ?? row.id].discount_value"
                        :label="'Diskon produk ' + (index + 1) + (lineDiscounts[row.detail_id ?? row.id].discount_type === 'PERCENT' ? ' (%)' : ' (Rp/baris)')"
                        type="number" min="0" step="0.01" :max="lineDiscounts[row.detail_id ?? row.id].discount_type === 'PERCENT' ? 100 : undefined" :readonly="!canConfirm" />
                      <p class="text-xs text-emerald-700 dark:text-emerald-300">Produk {{ formatCurrency(row.pricing.product_discount) }}<br>Global {{ formatCurrency(row.pricing.header_discount_allocated) }}</p>
                    </td>
                    <td class="p-3 align-top text-right whitespace-nowrap font-semibold">{{ formatCurrency(row.pricing.unit_dpp_net) }}<p class="text-xs font-normal text-slate-500">/ PCS · sebelum PPN</p>
                      <p class="mt-2">{{ formatCurrency(row.pricing.dpp_net) }}</p><p class="text-xs font-normal">Total DPP bersih</p>
                      <p class="mt-2 text-xs font-normal text-slate-500">PPN {{ Number(row.tax_rate || 0) }}%: {{ formatCurrency(row.pricing.ppn) }}<br>Total {{ formatCurrency(row.pricing.total) }}</p>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
          <section aria-label="Total finalisasi" class="rounded-2xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-700 dark:bg-slate-950">
            <h3 class="mb-4 font-semibold text-slate-900 dark:text-slate-100">Total seluruh barang</h3>
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div v-for="card in totalCards" :key="card.label"><p class="text-xs text-slate-500 dark:text-slate-400">{{ card.label }}</p>
                <p class="mt-1 font-semibold text-slate-900 dark:text-slate-100">{{ card.value }}</p></div>
            </div>
            <p class="mt-4 border-t border-slate-200 pt-3 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
              Jurnal: debit Pembelian (DPP awal) dan PPN; kredit Diskon Produk, Diskon Global, dan Hutang Usaha.
              Biaya lainnya dibukukan terpisah ke Biaya Pembelian dan menambah hutang.
            </p>
          </section>

          <div class="flex flex-wrap gap-3">
            <button
              v-if="canConfirm"
              class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white"
              :disabled="submitLoading || !!projectedBreakdown.error || detailLoading"
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

<style>
/* Theme follows the ERP's explicit setting, independent of OS color scheme. */
[data-theme='dark'] .purchase-finalization-detail .text-brand-700 { color: #b2cb9d; }
[data-theme='dark'] .purchase-finalization-detail .bg-brand-50 { background: #182111; color: #d4e1c7; border-color: #3c5124; }
[data-theme='dark'] .purchase-finalization-detail .bg-brand-100 { background: #29371a; color: #d4e1c7; }
</style>
