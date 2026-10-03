<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getPurchaseOrderDetail, getPurchaseOrders } from '@/api/purchase';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { exportRowsToCsv } from '@/utils/exportCsv';
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
  branchId: '',
  companyId: '',
  principalId: '',
  status: '',
  search: ''
});

const loading = ref(false);
const detailLoading = ref(false);
const errorMessage = ref('');
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

const statusOptions = [
  { value: '1', label: 'Request' },
  { value: '2', label: 'Need Confirm' },
  { value: '3', label: 'In Transit' },
  { value: '4', label: 'Closed' }
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
    label: 'Status PO',
    type: 'search-select',
    options: statusOptions
  },
  {
    key: 'search',
    label: 'Cari',
    placeholder: 'Kode PO / principal / PIC / catatan'
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
      return [
        item.kode,
        item.keterangan,
        item.principal_nama,
        item.cabang_nama,
        item.pic_order_nama,
        item.pic_konfirmasi_nama
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    })
    .map((item) => ({
      ...item,
      status_label: resolveOrderStatus(item.proses_id_berjalan),
      total_label: formatCurrency(item.total || 0),
      branch_label: item.cabang_nama || '-',
      principal_label: item.principal_nama || '-',
      request_pic_label: item.pic_order_nama || '-',
      confirm_pic_label: item.pic_konfirmasi_nama || '-'
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
  const totalPo = tableRows.value.length;
  const totalSku = detailRows.value.length;
  const totalQty = detailRows.value.reduce((sum, item) => sum + Number(item.total_order || 0), 0);
  const totalNominal = tableRows.value.reduce((sum, item) => sum + Number(item.total || 0), 0);
  const selectedNominal = Number(selectedDetail.value?.total || selectedRow.value?.total || 0);

  return [
    { label: 'PO Tampil', value: String(totalPo) },
    { label: 'Nilai Filter', value: formatCurrency(totalNominal) },
    { label: 'SKU Dipilih', value: String(totalSku) },
    { label: 'Qty Konversi', value: Number(totalQty || 0).toLocaleString('id-ID') },
    { label: 'Nilai PO Dipilih', value: formatCurrency(selectedNominal) }
  ];
});

function formatCurrency(value) {
  return `Rp ${new Intl.NumberFormat('id-ID').format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'long', year: 'numeric' }).format(parsed);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function resolveOrderStatus(value) {
  const key = Number(value || 0);
  const map = {
    1: { text: 'Request', className: 'inline-flex rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700' },
    2: { text: 'Need Confirm', className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' },
    3: { text: 'In Transit', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' },
    4: { text: 'Closed', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' }
  };
  return map[key] || { text: `Status ${key || '-'}`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
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
  selectedRow.value = null;
  selectedDetail.value = null;
  detailModalOpen.value = false;
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
    errorMessage.value = normalizeError(error, 'Laporan purchase order belum bisa dimuat.');
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

function resetFilters() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  filters.principalId = '';
  filters.status = '';
  filters.search = '';
  syncBranchFromCompany();
  loadRows();
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

function exportDetail() {
  if (!selectedRow.value || !detailRows.value.length) {
    errorMessage.value = 'Pilih PO yang memiliki detail produk terlebih dahulu.';
    return;
  }
  exportRowsToCsv(`laporan-po-detail-${selectedRow.value.kode || selectedRow.value.id}`, [
    { label: 'Kode PO', value: () => selectedRow.value.kode },
    { label: 'Cabang', value: () => selectedRow.value.cabang_nama || selectedRow.value.branch_label },
    { label: 'Principal', value: () => selectedRow.value.principal_nama || selectedRow.value.principal_label },
    { label: 'Kode Produk', key: 'produk_kode' },
    { label: 'Nama Produk', key: 'produk_nama' },
    { label: 'Harga Beli', key: 'produk_harga_beli' },
    { label: 'Total Order', key: 'total_order' },
    { label: 'Total Tersisa', key: 'total_tersisa' },
    { label: 'Rincian UOM', key: 'rincian_uom' },
    { label: 'Subtotal', key: 'subtotal' }
  ], detailRows.value);
}

function printDetail() {
  if (!selectedRow.value) {
    errorMessage.value = 'Pilih PO terlebih dahulu sebelum cetak laporan.';
    return;
  }

  const status = resolveOrderStatus(selectedRow.value.proses_id_berjalan).text;
  const productRows = detailRows.value.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${escapeHtml(item.produk_kode || '-')}</td>
      <td>${escapeHtml(item.produk_nama || '-')}</td>
      <td class="right">${Number(item.total_order || 0).toLocaleString('id-ID')}</td>
      <td>${escapeHtml(item.rincian_uom || '-')}</td>
      <td class="right">${escapeHtml(item.subtotal_label)}</td>
    </tr>
  `).join('');

  const html = `
    <html>
      <head>
        <title>Laporan PO ${escapeHtml(selectedRow.value.kode || '')}</title>
        <style>
          body { font-family: Arial, sans-serif; color: #111827; padding: 28px; }
          h1 { margin: 0 0 6px; font-size: 22px; }
          p { margin: 0; color: #4b5563; }
          .meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 22px 0; }
          .box { border: 1px solid #d1d5db; border-radius: 10px; padding: 10px; }
          .label { font-size: 10px; text-transform: uppercase; color: #6b7280; letter-spacing: .12em; }
          .value { margin-top: 6px; font-weight: 700; }
          table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 12px; }
          th, td { border: 1px solid #d1d5db; padding: 8px; text-align: left; vertical-align: top; }
          th { background: #f3f4f6; }
          .right { text-align: right; }
          .footer { margin-top: 32px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; text-align: center; font-size: 12px; }
          .sign { margin-top: 54px; border-top: 1px solid #111827; padding-top: 6px; }
        </style>
      </head>
      <body>
        <h1>Laporan Detail Purchase Order</h1>
        <p>${escapeHtml(selectedRow.value.kode || '-')} - ${escapeHtml(status)}</p>
        <div class="meta">
          <div class="box"><div class="label">Cabang</div><div class="value">${escapeHtml(selectedRow.value.cabang_nama || '-')}</div></div>
          <div class="box"><div class="label">Principal</div><div class="value">${escapeHtml(selectedRow.value.principal_nama || '-')}</div></div>
          <div class="box"><div class="label">Total PO</div><div class="value">${escapeHtml(formatCurrency(selectedRow.value.total || 0))}</div></div>
          <div class="box"><div class="label">PIC Request</div><div class="value">${escapeHtml(selectedRow.value.pic_order_nama || '-')}</div></div>
          <div class="box"><div class="label">PIC Confirm</div><div class="value">${escapeHtml(selectedRow.value.pic_konfirmasi_nama || '-')}</div></div>
          <div class="box"><div class="label">Tanggal Log</div><div class="value">${escapeHtml(formatDate(selectedRow.value.tanggal))}</div></div>
        </div>
        <table>
          <thead>
            <tr><th>No</th><th>Kode Produk</th><th>Nama Produk</th><th>Total</th><th>Rincian UOM</th><th>Subtotal</th></tr>
          </thead>
          <tbody>${productRows || '<tr><td colspan="6">Belum ada detail produk.</td></tr>'}</tbody>
        </table>
        <div class="footer">
          <div><div>Request</div><div class="sign">${escapeHtml(selectedRow.value.pic_order_nama || '')}</div></div>
          <div><div>Approval</div><div class="sign">${escapeHtml(selectedRow.value.pic_konfirmasi_nama || '')}</div></div>
          <div><div>Purchase</div><div class="sign">&nbsp;</div></div>
        </div>
      </body>
    </html>
  `;

  const popup = window.open('', '_blank', 'width=1100,height=800');
  if (!popup) {
    errorMessage.value = 'Popup cetak diblokir browser.';
    return;
  }
  popup.document.write(html);
  popup.document.close();
  popup.focus();
  popup.print();
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
      title="Laporan Purchase Order"
      description="Laporan detail purchase order per cabang, perusahaan, principal, status, dan rincian produk/UOM."
    />

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="Object.assign(filters, $event || {}); syncBranchFromCompany(); syncPrincipalFromCompany()" @submit="loadRows" @reset="resetFilters" />

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article v-for="card in summaryCards" :key="card.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ card.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ card.value }}</p>
      </article>
    </section>

    <section class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Daftar PO</h3>
          <p class="text-sm text-slate-500">Klik baris untuk membuka laporan detail PO.</p>
        </div>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="router.push('/purchase/orders')">
          Monitoring PO
        </button>
      </div>

      <AppTable
        :rows="tableRows"
        :columns="[
          { key: 'kode', label: 'Kode PO' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'branch_label', label: 'Cabang' },
          { key: 'status_label', label: 'Status' },
          { key: 'total_label', label: 'Total' },
          { key: 'request_pic_label', label: 'PIC Request' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        empty-message="Belum ada PO pada filter laporan ini."
        @row-click="openDetail"
      />
    </section>

    <AppModal
      :open="detailModalOpen"
      :title="selectedRow?.kode || 'Detail Laporan PO'"
      :description="selectedRow?.keterangan || 'Detail produk, rincian UOM, subtotal, dan informasi proses PO.'"
      size="6xl"
      @close="closeDetailModal"
    >
      <div class="mb-4 flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700" :disabled="!selectedRow" @click="exportDetail">
          Export CSV
        </button>
        <button class="rounded-xl bg-slate-900 px-3 py-2 text-xs font-medium text-white" :disabled="!selectedRow" @click="printDetail">
          Cetak
        </button>
      </div>

      <div v-if="detailLoading" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        Memuat detail PO...
      </div>

      <div v-else-if="!selectedRow" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500">
        Detail laporan belum tersedia.
      </div>

      <div v-else class="space-y-5">
          <div class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Status</p>
              <p class="mt-2"><span :class="resolveOrderStatus(selectedRow.proses_id_berjalan).className">{{ resolveOrderStatus(selectedRow.proses_id_berjalan).text }}</span></p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Total PO</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatCurrency(selectedRow.total || selectedDetail?.total || 0) }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Cabang</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow.cabang_nama || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Principal</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedRow.principal_nama || '-' }}</p>
            </article>
          </div>

          <div class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Request</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail?.request_log?.user_nama || selectedRow.pic_order_nama || '-' }}</p>
              <p class="text-xs text-slate-500">{{ formatDate(selectedDetail?.request_log?.tanggal || selectedRow.tanggal) }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 px-4 py-3">
              <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Konfirmasi</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail?.konfirmasi_log?.user_nama || selectedRow.pic_konfirmasi_nama || '-' }}</p>
              <p class="text-xs text-slate-500">{{ formatDate(selectedDetail?.konfirmasi_log?.tanggal) }}</p>
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
                { key: 'total_tersisa', label: 'Sisa' },
                { key: 'rincian_uom', label: 'Rincian UOM' },
                { key: 'subtotal_label', label: 'Subtotal' }
              ]"
              empty-message="Belum ada detail produk pada PO ini."
            />
          </div>
      </div>
    </AppModal>
  </div>
</template>
