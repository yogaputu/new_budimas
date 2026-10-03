<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getPurchaseReadyOrders, getPurchaseReceiptDetail, getPurchaseReceipts } from '@/api/purchase';
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
const errorMessage = ref('');
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const rows = ref([]);
const readyOrders = ref([]);
const selectedRow = ref(null);
const selectedDetail = ref(null);
const detailModalOpen = ref(false);
const fallbackBranchId = computed(() => getPurchaseFallbackBranchId(authStore));
const fallbackCompanyId = computed(() => getPurchaseFallbackCompanyId(authStore));
const canAccessAllBranches = computed(() => canAccessAllPurchaseBranches(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

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
  const penerimaan = rows.value.filter((item) => Number(item.proses_id_berjalan || 0) === 1).length;
  const konfirmasi = rows.value.filter((item) => Number(item.proses_id_berjalan || 0) === 2).length;
  const tagihan = rows.value.filter((item) => Number(item.proses_id_berjalan || 0) === 3).length;
  const totalNominal = rows.value.reduce((sum, item) => sum + Number(item.total || 0), 0);
  return [
    { label: 'Total Transaksi', value: String(total) },
    { label: 'PO Siap Terima', value: String(readyOrders.value.length) },
    { label: 'Penerimaan', value: String(penerimaan) },
    { label: 'Butuh Konfirmasi', value: String(konfirmasi) },
    { label: 'Total Nominal', value: formatCurrency(totalNominal) },
    { label: 'Siap Tagihan', value: String(tagihan) }
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
      status_label: resolveReceiptStatus(item.proses_id_berjalan),
      total_label: formatCurrency(item.total || 0),
      subtotal_label: formatCurrency(item.subtotal || 0),
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      order_code_label: item.order_kode || '-'
    }))
);

const readyOrderRows = computed(() =>
  readyOrders.value
    .filter((item) => {
      const query = filters.search.trim().toLowerCase();
      if (!query) return true;
      return [
        item.kode,
        item.principal_nama,
        item.cabang_nama,
        item.keterangan
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      total_label: formatCurrency(item.total || 0)
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

const detailMetaCards = computed(() => {
  if (!selectedDetail.value && !selectedRow.value) return [];

  const source = selectedDetail.value || selectedRow.value;
  return [
    { label: 'Status', value: resolveReceiptStatus(source.proses_id_berjalan) },
    { label: 'Subtotal', value: formatCurrency(source.subtotal || 0) },
    { label: 'Total', value: formatCurrency(source.total || 0) },
    { label: 'Jumlah Detail', value: String(normalizeList(selectedDetail.value?.detail).length || 0) }
  ];
});

const nextActionHint = computed(() => {
  const status = Number(selectedDetail.value?.proses_id_berjalan || selectedRow.value?.proses_id_berjalan || 0);
  const map = {
    1: 'Transaksi baru selesai dicatat sebagai penerimaan barang. Berikutnya masuk ke tahap konfirmasi purchase.',
    2: 'Transaksi sedang menunggu konfirmasi purchase. Pastikan total, jatuh tempo, dan biaya tambahan sudah final.',
    3: 'Transaksi sudah siap dibundel ke tagihan purchase.',
    4: 'Transaksi sudah masuk proses pelunasan tagihan.',
    5: 'Transaksi purchase ini sudah lunas.'
  };
  return map[status] || 'Pilih transaksi penerimaan untuk melihat langkah operasional berikutnya.';
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function resolveReceiptStatus(value) {
  const key = Number(value || 0);
  const map = {
    1: { text: 'Penerimaan Brg.', className: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700' },
    2: { text: 'Konf. Purchase', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' },
    3: { text: 'Pem. Tagihan', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Pelunasan', className: 'inline-flex rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700' },
    5: { text: 'Lunas', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' }
  };
  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.search = '';
  syncBranchFromCompany();
  loadReceipts();
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

async function loadReceipts() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const params = {};
    if (filters.branchId) params.cabang_id = filters.branchId;
    if (filters.companyId) params.id_perusahaan = filters.companyId;
    if (filters.principalId) params.principal_id = filters.principalId;
    const [receiptResponse, readyResponse] = await Promise.all([
      getPurchaseReceipts(params),
      getPurchaseReadyOrders(params)
    ]);
    rows.value = normalizeList(unwrapResponse(receiptResponse));
    readyOrders.value = normalizeList(unwrapResponse(readyResponse));
  } catch (error) {
    rows.value = [];
    readyOrders.value = [];
    errorMessage.value = normalizeError(error, 'Daftar penerimaan barang belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function openReceiptCreate(order) {
  router.push({
    path: '/purchase/receipts/create',
    query: {
      branchId: order.cabang_id || filters.branchId || '',
      companyId: order.id_perusahaan || filters.companyId || '',
      orderId: order.id || ''
    }
  });
}

async function openDetail(row) {
  selectedRow.value = row;
  selectedDetail.value = null;
  detailModalOpen.value = true;
  detailLoading.value = true;
  errorMessage.value = '';
  try {
    const response = await getPurchaseReceiptDetail(row.id);
    selectedDetail.value = unwrapResponse(response);
  } catch (error) {
    selectedDetail.value = null;
    errorMessage.value = normalizeError(error, 'Detail penerimaan barang belum bisa dimuat.');
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

onMounted(async () => {
  await loadMeta();
  await loadReceipts();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Penerimaan Barang"
      description="Fase awal monitoring purchase transaksi untuk membaca histori penerimaan, progress konfirmasi, dan rincian batch barang dari API lama."
    />

    <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadReceipts" @reset="resetFilters" />

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section class="flex flex-wrap gap-3">
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="router.push('/purchase/receipts/create')">
        Input Penerimaan Barang
      </button>
      <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/confirmations')">
        Lanjut ke Finalisasi Purchase Order
      </button>
    </section>

    <section class="space-y-3">
      <div>
        <h3 class="text-lg font-semibold text-slate-900">PO Siap Diterima</h3>
        <p class="text-sm text-slate-500">
          PO yang sudah dikonfirmasi tampil di sini sebelum dibuatkan transaksi penerimaan barang.
        </p>
      </div>
      <AppTable
        :rows="readyOrderRows"
        :columns="[
          { key: 'kode', label: 'Kode PO' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'total_label', label: 'Nilai PO' },
          { key: 'aksi', label: 'Aksi', render: () => 'Klik baris untuk input penerimaan' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada PO yang siap diterima pada filter ini."
        @row-click="openReceiptCreate"
      />
    </section>

    <section class="space-y-3">
      <h3 class="text-lg font-semibold text-slate-900">Daftar Penerimaan Barang</h3>
      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'no_transaksi', label: 'No Transaksi' },
          { key: 'order_code_label', label: 'Kode Order' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'subtotal_label', label: 'Subtotal' },
          { key: 'total_label', label: 'Total' },
          { key: 'status_label', label: 'Status' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada transaksi penerimaan pada filter ini."
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.no_transaksi || 'Detail Penerimaan'"
      :description="selectedDetail?.keterangan || selectedRow?.keterangan || 'Header transaksi, log penerimaan, log konfirmasi, dan rincian barang.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail penerimaan...
      </div>

      <div v-else-if="!selectedDetail" class="rounded-2xl border border-dashed border-slate-200 px-4 py-6 text-sm text-slate-500">
        Detail penerimaan belum tersedia.
      </div>

      <div v-else class="space-y-5">
          <div class="rounded-2xl border border-brand-100 bg-brand-50 px-4 py-3 text-sm text-brand-700">
            {{ nextActionHint }}
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div v-for="card in detailMetaCards" :key="card.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">{{ card.label }}</p>
              <div class="mt-2 text-sm font-semibold text-slate-900">
                <span v-if="card.value && typeof card.value === 'object'" :class="card.value.className">{{ card.value.text }}</span>
                <span v-else>{{ card.value }}</span>
              </div>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Order Referensi</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.order_kode || selectedRow?.order_code_label || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Total Final</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(selectedDetail.total || selectedRow?.total || 0) }}</p>
            </div>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <div class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PIC Penerimaan</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.penerimaan_log?.user_nama || '-' }}</p>
              <p class="text-xs text-slate-500">{{ selectedDetail.penerimaan_log?.tanggal || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PIC Konfirmasi</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.konfirmasi_log?.user_nama || '-' }}</p>
              <p class="text-xs text-slate-500">{{ selectedDetail.konfirmasi_log?.tanggal || '-' }}</p>
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
                { key: 'tanggal_expired', label: 'Expired' },
                { key: 'subtotal_label', label: 'Subtotal' },
                { key: 'jumlah_ringkas', label: 'Rincian UOM' }
              ]"
              empty-message="Belum ada detail produk pada transaksi ini."
            />
          </div>
      </div>
    </AppModal>
  </div>
</template>
