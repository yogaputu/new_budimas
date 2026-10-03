<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { confirmOrder, getInvoiceDetail, getVerificationOrders, rejectOrder } from '@/api/distribution';
import { getBranches, getCompanies, getCustomersTable } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const route = useRoute();

const filters = reactive({
  companyId: '',
  branchId: '',
  taxStatus: '',
  search: ''
});

const actionForm = reactive({
  note: ''
});

const branchRows = ref([]);
const companyRows = ref([]);
const items = ref([]);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref('');
const actionMessage = ref('');
const actionError = ref('');
const detailError = ref('');
const selectedRow = ref(null);
const invoiceHeader = ref({});
const invoiceRows = ref([]);
const targetAutoOpenAttempted = ref(false);
const detailOpen = ref(false);
const customerTaxCache = ref({});

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser(authStore));
const targetSalesOrderId = computed(() => String(route.query.sales_order_id || route.query.id_sales_order || '').trim());

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);
  if (branchCompanyId) ids.add(String(branchCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId)
);

const taxStatusOptions = [
  { value: 'pkp', label: 'PKP' },
  { value: 'non_pkp', label: 'Non PKP' },
  { value: 'npwp', label: 'NPWP' },
  { value: 'lain_lain', label: 'Lain-lain' }
];

const normalizedRows = computed(() =>
  items.value.map((item, index) => {
    const salesOrderIds = Array.isArray(item.id_sales_order)
      ? item.id_sales_order.map((value) => String(value))
      : String(item.id_sales_order || '')
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean);

    const orderNumbers = Array.isArray(item.no_order)
      ? item.no_order
      : String(item.no_order || '')
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean);

    return {
      ...item,
      row_key: `${item.id_order_batch || 'single'}-${salesOrderIds.join('-') || index}`,
      sales_order_ids: salesOrderIds,
      sales_order_ids_label: salesOrderIds.join(', '),
      primary_sales_order_id: salesOrderIds[0] || '',
      no_order_label: orderNumbers.join(', ') || '-',
      principal_label: item.kode_principal || '-',
      tax_status_key: normalizeTaxStatus(item),
      total_bayar_label: Number(item.total_bayar || 0).toLocaleString('id-ID'),
      tipe_order_label: item.id_order_batch ? 'Batch Principal Campur' : 'Single Principal',
      target_label: targetSalesOrderId.value && salesOrderIds.includes(targetSalesOrderId.value) ? 'Target Verifikasi' : ''
    };
  })
);

const filteredRows = computed(() => {
  const query = filters.search.trim().toLowerCase();

  return normalizedRows.value.filter((item) =>
    (!filters.taxStatus || item.tax_status_key === filters.taxStatus) &&
    (!query ||
      [
        item.no_faktur,
        item.no_order_label,
        item.nama_customer,
        item.kode_customer,
        item.nama_sales,
        item.principal_label,
        item.sales_order_ids_label,
        item.tipe_order_label
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)))
  );
});

function orderUomName(item, level, fallback) {
  const keys = [`uom${level}_nama`, `uom_${level}_nama`, `puom${level}_nama`, `uom${level}Nama`, `nama_uom_${level}`, `uom${level}_name`];
  return keys.map((key) => String(item?.[key] || '').trim()).find(Boolean) || fallback;
}

function orderUomFactor(item, level, fallback) {
  const keys = [
    `uom${level}_pcs`,
    `uom_${level}_pcs`,
    `pcs_per_uom${level}`,
    `pcs_per_uom_${level}`,
    `uom${level}_factor`,
    `uom_${level}_factor`,
    `uom${level}Factor`,
    `faktor_uom_${level}`,
    `uom${level}_faktor_konversi`,
    `konversi_level${level}`
  ];
  return keys.map((key) => Number(item?.[key] || 0)).find((value) => value > 0) || fallback;
}

function orderBaseQty(item) {
  const canonicalFields = ['total_pieces_order', 'total_pcs', 'qty_pcs'];
  for (const field of canonicalFields) {
    const rawValue = item?.[field];
    if (rawValue === null || rawValue === undefined || rawValue === '') continue;
    const value = Number(rawValue);
    if (Number.isFinite(value) && value >= 0) return value;
  }

  return Number(item?.pieces_order || 0) * orderUomFactor(item, 1, 1)
    + Number(item?.box_order || 0) * orderUomFactor(item, 2, Number(item?.isiperbox || 1))
    + Number(item?.karton_order || 0) * orderUomFactor(item, 3, Number(item?.isiperkarton || item?.isiperbox || 1));
}

function orderQtyLabel(item) {
  const parts = [];
  const uom3 = Number(item?.karton_order || 0);
  const uom2 = Number(item?.box_order || 0);
  const pcs = Number(item?.pieces_order || 0);
  if (uom3) parts.push(`${uom3.toLocaleString('id-ID')} ${orderUomName(item, 3, 'Karton')}`);
  if (uom2) parts.push(`${uom2.toLocaleString('id-ID')} ${orderUomName(item, 2, 'CT')}`);
  if (pcs || parts.length === 0) parts.push(`${pcs.toLocaleString('id-ID')} ${orderUomName(item, 1, 'PCS')}`);
  return parts.join(' | ');
}

const detailRows = computed(() =>
  invoiceRows.value.map((item, index) => ({
    ...item,
    detail_key: `${item.id_order_detail || item.id_produk || index}`,
    qty_label: orderQtyLabel(item),
    qty_base_label: `${orderBaseQty(item).toLocaleString('id-ID')} PCS`,
    subtotal_label: Number(item.subtotalorder || 0).toLocaleString('id-ID')
  }))
);

const detailSummary = computed(() => {
  const subtotal = invoiceRows.value.reduce((total, item) => total + Number(item.subtotalorder || 0), 0);
  const discount = getDiscountTotal(invoiceRows.value);
  const tax = getTaxTotal(invoiceRows.value);
  return {
    rows: invoiceRows.value.length,
    subtotal,
    discount,
    tax,
    total: Number(selectedRow.value?.total_bayar || invoiceHeader.value?.total_penjualan || subtotal + tax)
  };
});

function getActiveBranchId() {
  return filters.branchId || String(fallbackBranchId.value || '');
}

function resetSelection() {
  selectedRow.value = null;
  invoiceHeader.value = {};
  invoiceRows.value = [];
  actionForm.note = '';
  detailError.value = '';
  detailOpen.value = false;
}

function syncRouteContext() {
  if (route.query.id_cabang) {
    filters.branchId = String(route.query.id_cabang);
  }

  if (route.query.no_order && !filters.search) {
    filters.search = String(route.query.no_order);
  }
}

function getDiscountTotal(rows = []) {
  return rows.reduce(
    (total, item) =>
      total +
      Number(item.v1r_diskon || 0) +
      Number(item.v2p_diskon || 0) +
      Number(item.v2r_diskon || 0) +
      Number(item.v3r_diskon || 0) +
      Number(item.v3p_diskon || 0),
    0
  );
}

function getTaxTotal(rows = []) {
  return rows.reduce((total, item) => total + Number(item.subtotalorder || 0) * (Number(item.ppn || 0) / 100), 0);
}

function firstFilled(...values) {
  return values.find((value) => value !== undefined && value !== null && String(value).trim() !== '') || '';
}

function normalizeTaxStatus(row = {}) {
  const rawStatus = String(firstFilled(row.status_pajak, row.customer_status_pajak, row.status_pkp)).trim().toLowerCase();
  if (['pkp', 'non_pkp', 'npwp', 'lain_lain'].includes(rawStatus)) return rawStatus;
  if (String(firstFilled(row.is_ppn, row.customer_is_ppn)).trim() === '1') return 'pkp';
  return 'non_pkp';
}

function taxIdentityLabel(row = {}) {
  const rawType = String(firstFilled(row.jenis_identitas_pajak, row.tipe_identitas_pajak)).trim().toLowerCase();
  if (rawType === 'nik') return 'NIK';
  if (rawType === 'lain_lain') return 'NPWP/NIK';
  const status = normalizeTaxStatus(row);
  return status === 'non_pkp' ? 'NIK' : 'NPWP';
}

function getCustomerIdentityNumber(row = {}) {
  const value = String(firstFilled(row.npwp, row.nik, row.no_npwp, row.no_nik, row.nomor_identitas_pajak)).trim();
  return ['', '-', '0', 'null', 'none', 'n/a', 'na'].includes(value.toLowerCase()) ? '' : value;
}

async function resolveCustomerTaxData(row = {}) {
  const directIdentity = getCustomerIdentityNumber(row) || getCustomerIdentityNumber(invoiceHeader.value);
  if (directIdentity) {
    return { ...row, ...invoiceHeader.value, npwp: directIdentity };
  }

  const customerKey = firstFilled(row.id_customer, invoiceHeader.value.id_customer, row.kode_customer, invoiceHeader.value.kode_customer);
  if (!customerKey) return { ...row, ...invoiceHeader.value };
  if (customerTaxCache.value[customerKey]) return customerTaxCache.value[customerKey];

  const search = firstFilled(row.kode_customer, invoiceHeader.value.kode_customer, row.nama_customer, invoiceHeader.value.nama_customer);
  if (!search) return { ...row, ...invoiceHeader.value };

  const response = await getCustomersTable({ search });
  const payload = unwrapResponse(response);
  const candidates = normalizeList(payload?.data || payload);
  const matched = candidates.find((item) =>
    (row.id_customer && String(item.id) === String(row.id_customer)) ||
    (row.kode_customer && String(item.kode || '').toLowerCase() === String(row.kode_customer).toLowerCase())
  ) || {};

  const result = { ...row, ...invoiceHeader.value, ...matched };
  customerTaxCache.value[customerKey] = result;
  return result;
}

async function validateCustomerTaxBeforeConfirm(row) {
  const customerData = await resolveCustomerTaxData(row);
  const identityNumber = getCustomerIdentityNumber(customerData);
  if (identityNumber) return '';

  const customerLabel = [firstFilled(customerData.kode_customer, customerData.kode), firstFilled(customerData.nama_customer, customerData.nama)]
    .filter(Boolean)
    .join(' - ') || 'customer ini';
  return `${taxIdentityLabel(customerData)} customer ${customerLabel} masih kosong. Lengkapi dulu di Master Customer sebelum konfirmasi order.`;
}

function buildConfirmPayload(row) {
  const branchId = getActiveBranchId();
  const subtotal = invoiceRows.value.reduce((total, item) => total + Number(item.subtotalorder || 0), 0);
  const subtotalDiskon = getDiscountTotal(invoiceRows.value);
  const pajak = getTaxTotal(invoiceRows.value);
  const totalPenjualan = Number(row?.total_bayar || invoiceHeader.value?.total_penjualan || subtotal + pajak);
  const dpp = Number(invoiceHeader.value?.dpp || totalPenjualan - pajak);

  const payload = {
    id_cabang: branchId,
    total_penjualan: totalPenjualan,
    subtotal_diskon: Number(invoiceHeader.value?.subtotal_diskon || subtotalDiskon),
    dpp,
    pajak: Number(invoiceHeader.value?.pajak || pajak)
  };

  if (row?.id_order_batch) {
    payload.id_order_batch = row.id_order_batch;
    payload.products = invoiceRows.value.map((item) => ({
      id_sales_order: Number(item.id_sales_order),
      id_order_detail: Number(item.id_order_detail),
      id_produk: Number(item.id_produk),
      subtotalorder: Number(item.subtotalorder || 0),
      ppn: Number(item.ppn || 0),
      v1r_diskon: Number(item.v1r_diskon || 0),
      v2p_diskon: Number(item.v2p_diskon || 0),
      v2r_diskon: Number(item.v2r_diskon || 0),
      v3r_diskon: Number(item.v3r_diskon || 0),
      v3p_diskon: Number(item.v3p_diskon || 0)
    }));
  } else {
    payload.id_sales_order = row?.primary_sales_order_id;
  }

  return payload;
}

function buildRejectPayload(row) {
  const payload = {
    keterangan: actionForm.note
  };

  if (row?.id_order_batch) {
    payload.id_order_batch = row.id_order_batch;
  } else {
    payload.id_sales_order = row?.primary_sales_order_id;
  }

  return payload;
}

async function loadBranches() {
  const [companiesResponse, branchesResponse] = await Promise.all([getCompanies(), getBranches()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
}

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) {
    return;
  }

  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadOrders() {
  loading.value = true;
  actionMessage.value = '';
  actionError.value = '';

  try {
    const branchId = getActiveBranchId();
    const response = await getVerificationOrders({
      ...(branchId ? { id_cabang: branchId } : {}),
      ...(filters.companyId ? { id_perusahaan: filters.companyId } : {})
    });
    items.value = normalizeList(unwrapResponse(response));

    if (targetSalesOrderId.value && !targetAutoOpenAttempted.value) {
      targetAutoOpenAttempted.value = true;
      const targetRow = normalizedRows.value.find((item) => item.sales_order_ids.includes(targetSalesOrderId.value));
      if (targetRow) {
        await openRow(targetRow);
        return;
      }
      actionError.value = `Order ${targetSalesOrderId.value} belum ditemukan di daftar verifikasi cabang ini. Cek status order, cabang, atau filter backend.`;
    }

    if (selectedRow.value) {
      const refreshed = normalizeList(unwrapResponse(response)).find((item) => {
        const currentIds = Array.isArray(item.id_sales_order) ? item.id_sales_order.map(String) : [String(item.id_sales_order)];
        return (
          String(item.id_order_batch || '') === String(selectedRow.value?.id_order_batch || '') &&
          currentIds.join(',') === (selectedRow.value?.sales_order_ids || []).join(',')
        );
      });

      if (!refreshed) {
        resetSelection();
      }
    }
  } catch (error) {
    actionError.value = normalizeError(error, 'Daftar verifikasi order belum bisa dimuat.');
    items.value = [];
    resetSelection();
  } finally {
    loading.value = false;
  }
}

async function openRow(row) {
  selectedRow.value = row;
  invoiceHeader.value = {};
  invoiceRows.value = [];
  detailError.value = '';
  actionMessage.value = '';
  actionError.value = '';
  detailOpen.value = true;
  detailLoading.value = true;

  try {
    const params = row.id_order_batch
      ? {
          id_order_batch: row.id_order_batch,
          id_sales_orders: row.sales_order_ids.join(',')
        }
      : {};

    const response = await getInvoiceDetail(row.primary_sales_order_id, params);
    const payload = unwrapResponse(response) || {};
    invoiceHeader.value = payload.detail_faktur || {};
    invoiceRows.value = normalizeList(payload.list_detail_order || payload);
  } catch (error) {
    detailError.value = normalizeError(error, 'Detail order tidak bisa dimuat.');
    invoiceHeader.value = {};
    invoiceRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

async function runAction(type) {
  actionMessage.value = '';
  actionError.value = '';

  if (!selectedRow.value) {
    actionError.value = 'Klik salah satu baris order terlebih dahulu.';
    return;
  }

  if (type === 'confirm' && !getActiveBranchId()) {
    actionError.value = 'Cabang aktif belum tersedia. Pilih cabang terlebih dahulu sebelum konfirmasi.';
    return;
  }

  if (type === 'confirm' && !invoiceRows.value.length) {
    actionError.value = 'Detail produk belum dimuat. Klik ulang baris order atau tunggu detail selesai dimuat sebelum konfirmasi.';
    return;
  }

  if (type === 'confirm') {
    const taxValidationError = await validateCustomerTaxBeforeConfirm(selectedRow.value);
    if (taxValidationError) {
      actionError.value = taxValidationError;
      return;
    }
  }

  actionLoading.value = type;

  try {
    if (type === 'confirm') {
      await confirmOrder(buildConfirmPayload(selectedRow.value));
      actionMessage.value = 'Order berhasil dikonfirmasi.';
    } else {
      await rejectOrder(buildRejectPayload(selectedRow.value));
      actionMessage.value = 'Order berhasil ditolak.';
    }

    const nextSelection = selectedRow.value;
    await loadOrders();

    const refreshedRow = normalizedRows.value.find(
      (item) =>
        String(item.id_order_batch || '') === String(nextSelection?.id_order_batch || '') &&
        item.sales_order_ids.join(',') === (nextSelection?.sales_order_ids || []).join(',')
    );

    if (refreshedRow) {
      await openRow(refreshedRow);
    } else {
      resetSelection();
    }
  } catch (error) {
    actionError.value = normalizeError(error, 'Aksi order gagal diproses.');
  } finally {
    actionLoading.value = '';
  }
}

function submit() {
  loadOrders();
}

function reset() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = String(fallbackBranchId.value || '');
  syncBranchFromCompany();
  filters.taxStatus = '';
  filters.search = '';
  resetSelection();
  loadOrders();
}

watch(
  () => filters.companyId,
  () => syncBranchFromCompany()
);

onMounted(async () => {
  syncRouteContext();
  await loadBranches();
  syncRouteContext();
  await loadOrders();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Distribusi Order"
      description="Halaman verifikasi order saya naikkan ke mode operasional: pilih perusahaan dan cabang, klik baris order untuk buka detail faktur, lalu konfirmasi atau tolak tanpa isi ID manual."
    />

    <AppFilterBar
      :model-value="filters"
      :fields="[
        { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions, disabled: canUseLoginScope && !!fallbackCompanyId },
        { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions, disabled: !filters.companyId || (!isSuperUser(authStore) && !!fallbackBranchId) },
        { key: 'taxStatus', label: 'Status Pajak / PKP', type: 'search-select', options: taxStatusOptions },
        { key: 'search', label: 'Cari order', placeholder: 'Faktur, order, customer, sales, principal' }
      ]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <div>
      <AppTable
        :rows="filteredRows"
        :columns="[
          { key: 'target_label', label: 'Target' },
          { key: 'no_faktur', label: 'No Faktur' },
          { key: 'no_order_label', label: 'No Order' },
          { key: 'nama_customer', label: 'Customer' },
          { key: 'principal_label', label: 'Principal' },
          { key: 'nama_sales', label: 'Sales' },
          { key: 'total_bayar_label', label: 'Total' },
          { key: 'tipe_order_label', label: 'Tipe' }
        ]"
        :loading="loading"
        :clickable-rows="true"
        row-key="row_key"
        :selected-key="selectedRow?.row_key || ''"
        empty-message="Belum ada order yang menunggu verifikasi untuk cabang ini."
        @row-click="openRow"
      />
    </div>

    <AppModal
      :open="detailOpen"
      title="Detail Verifikasi Order"
      :description="selectedRow ? 'Validasi header, produk, nominal, lalu konfirmasi atau tolak order.' : 'Pilih salah satu order untuk membuka detail verifikasi.'"
      size="7xl"
      @close="detailOpen = false"
    >
      <div v-if="selectedRow" class="space-y-5">
        <section class="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">Sales Order</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.sales_order_ids_label || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">Order Batch</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.id_order_batch || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">No Faktur</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.no_faktur || invoiceHeader.nomor_faktur || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.nama_customer || invoiceHeader.nama_customer || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.principal_label || invoiceHeader.nama_principal || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
            <p class="text-xs uppercase tracking-wide text-slate-400">Total Bayar</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow?.total_bayar_label || '-' }}</p>
          </div>
        </section>

        <section>
          <AppFormField v-model="actionForm.note" label="Catatan" placeholder="Catatan reject atau catatan internal" />
        </section>

        <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Detail Produk</p>
            <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{{ detailSummary.rows }} baris</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Estimasi Total</p>
            <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">Rp {{ Number(detailSummary.total || 0).toLocaleString('id-ID') }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Diskon</p>
            <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">Rp {{ Number(detailSummary.discount || 0).toLocaleString('id-ID') }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Pajak</p>
            <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">Rp {{ Number(detailSummary.tax || 0).toLocaleString('id-ID') }}</p>
          </div>
        </section>

        <div v-if="detailError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          {{ detailError }}
        </div>
        <div v-if="actionMessage" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">
          {{ actionMessage }}
        </div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
          {{ actionError }}
        </div>

        <section class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <AppTable
            :rows="detailRows"
            :columns="[
              { key: 'kode_sku', label: 'SKU' },
              { key: 'nama_produk', label: 'Produk' },
              { key: 'qty_label', label: 'Rincian UOM' },
              { key: 'qty_base_label', label: 'Total (PCS)' },
              { key: 'subtotal_label', label: 'Subtotal' }
            ]"
            :loading="detailLoading"
            empty-message="Klik order terlebih dahulu untuk melihat detail produk."
          />
        </section>
      </div>

      <div v-else class="rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-400">
        Belum ada order dipilih.
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="detailOpen = false">
            Tutup
          </button>
          <button
            class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60 dark:border-rose-500/40 dark:text-rose-200"
            :disabled="!!actionLoading || detailLoading || !selectedRow"
            @click="runAction('reject')"
          >
            {{ actionLoading === 'reject' ? 'Menolak...' : 'Tolak' }}
          </button>
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            :disabled="!!actionLoading || detailLoading || !selectedRow"
            @click="runAction('confirm')"
          >
            {{ actionLoading === 'confirm' ? 'Konfirmasi...' : 'Konfirmasi Order' }}
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
