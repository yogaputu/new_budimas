<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals, getSales } from '@/api/master';
import { getSalesInvoiceDashboard } from '@/api/salesOrder';
import { getInvoiceDetail, recordInvoicePrint } from '@/api/distribution';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { buildSalesDocumentHtml, openPrintHtml, reservePrintWindow } from '@/utils/printTemplates';
import {
  getLoginBranchId,
  getLoginCompanyId,
  getLoginSalesUserId,
  getRowBranchIds,
  getRowCompanyId,
  isSuperUser,
  scopeSalesRowsByLogin,
  shouldLockToLoginSales
} from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { resolveDepositStageLabel } from '@/modules/finance/utils/statusLabels';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();

const filters = reactive({
  salesUserId: '',
  companyId: '',
  branchId: '',
  fakturStatus: '',
  paymentStatus: '',
  taxStatus: '',
  dateFrom: '',
  dateTo: '',
  search: ''
});

const items = ref([]);
const summary = ref({
  total_invoices: 0,
  belum_faktur: 0,
  belum_bayar: 0,
  sebagian: 0,
  lunas: 0,
  total_tagihan: 0,
  total_setoran_cash: 0,
  total_voucher_used: 0,
  total_setoran: 0,
  total_sisa_tagihan: 0
});
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const salesRows = ref([]);
const loading = ref(false);
const loadError = ref('');
const printError = ref('');
const printSubmitting = ref(false);
const selectedRow = ref(null);
const invoiceSummaryOpen = ref(false);

const fallbackUserId = computed(() => getLoginSalesUserId(auth.user));
const fallbackBranchId = computed(() => getLoginBranchId(auth.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(auth.user));
const canUseLoginScope = computed(() => shouldLockToLoginSales(auth));
const shouldLockBusinessScope = computed(() => !isSuperUser(auth));

function salesQuery() {
  return filters.salesUserId ? { sales_user_id: filters.salesUserId } : {};
}

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

function salesMatchesCompany(row, companyId) {
  if (!companyId) return true;

  const directCompanyId = getRowCompanyId(row);
  if (directCompanyId) {
    return String(directCompanyId) === String(companyId);
  }

  const principalIds = [
    row?.id_principal,
    row?.principal_id,
    row?.id_principals,
    row?.principal_ids
  ]
    .flatMap((value) => String(value || '').split(','))
    .map((value) => value.trim())
    .filter(Boolean);

  if (!principalIds.length) return false;

  return principalIds.some((principalId) => {
    const principal = principalRows.value.find((item) => String(item.id) === String(principalId));
    return String(getRowCompanyId(principal)) === String(companyId);
  });
}

const companyOptions = computed(() =>
  [
    { value: '', label: '' },
    ...getCompanyOptionsForScope(companyRows.value, auth)
  ]
);

const branchOptions = computed(() =>
  [
    { value: '', label: '' },
    ...getBranchOptionsForCompany(branchRows.value, auth, filters.companyId)
  ]
);

const salesOptions = computed(() =>
  [
    { value: '', label: '' },
    ...scopeSalesRowsByLogin(salesRows.value, auth)
    .filter((item) => !filters.branchId || String(item.id_cabang || item.cabang_id || item.idCabang || '') === String(filters.branchId))
    .filter((item) => !filters.companyId || salesMatchesCompany(item, filters.companyId))
    .map((item) => ({
    value: String(item.id_user || item.id),
    label: `${item.kode_sales || '-'} - ${item.nama || 'Sales'}`
    }))
  ]
);

const selectedSales = computed(() =>
  salesRows.value.find((item) =>
    [item.id_user, item.user_id, item.id, item.id_sales]
      .filter((value) => value !== null && value !== undefined && value !== '')
      .map(String)
      .includes(String(filters.salesUserId || ''))
  )
);

const fakturStatusOptions = [
  { value: '0', label: 'Draft' },
  { value: '1', label: 'Printed' },
  { value: '2', label: 'Unpaid' },
  { value: '3', label: 'Paid' },
  { value: '4', label: 'Canceled' }
];

const paymentStatusOptions = [
  { value: 'Belum Faktur', label: 'Belum Faktur' },
  { value: 'Belum Bayar', label: 'Belum Bayar' },
  { value: 'Sebagian', label: 'Sebagian' },
  { value: 'Lunas', label: 'Lunas' }
];

const taxStatusOptions = [
  { value: 'pkp', label: 'PKP' },
  { value: 'non_pkp', label: 'Non PKP' },
  { value: 'npwp', label: 'NPWP' },
  { value: 'lain_lain', label: 'Lain-lain' }
];

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan', emptyText: 'Perusahaan belum tersedia.', disabled: shouldLockBusinessScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: filters.companyId ? 'Pilih cabang' : 'Pilih perusahaan dahulu', emptyText: filters.companyId ? 'Cabang belum tersedia.' : 'Pilih perusahaan dahulu.', disabled: !filters.companyId || (!isSuperUser(auth) && !!fallbackBranchId.value) },
  { key: 'salesUserId', label: 'Sales', type: 'search-select', options: salesOptions.value, placeholder: filters.branchId ? 'Pilih sales' : 'Pilih cabang dahulu', emptyText: filters.branchId ? 'Sales belum tersedia.' : 'Pilih cabang dahulu.', disabled: !filters.branchId || (canUseLoginScope.value && !!fallbackUserId.value) },
  { key: 'fakturStatus', label: 'Status Faktur', type: 'select', options: fakturStatusOptions },
  { key: 'paymentStatus', label: 'Status Pembayaran', type: 'select', options: paymentStatusOptions },
  { key: 'taxStatus', label: 'Status Pajak / PKP', type: 'select', options: taxStatusOptions },
  { key: 'dateFrom', label: 'Dari Tanggal', type: 'date' },
  { key: 'dateTo', label: 'Sampai Tanggal', type: 'date' },
  { key: 'search', label: 'Cari', placeholder: 'No order, no faktur, customer, principal, sales' }
]);

const normalizedRows = computed(() =>
  items.value.map((item) => ({
    ...item,
    row_key: String(item.id),
    total_penjualan_label: `Rp ${Number(item.total_penjualan || 0).toLocaleString('id-ID')}`,
    total_voucher_used_label: `Rp ${Number(item.total_voucher_used || 0).toLocaleString('id-ID')}`,
    total_setoran_label: `Rp ${Number(item.total_setoran || 0).toLocaleString('id-ID')}`,
    sisa_tagihan_label: `Rp ${Number(item.sisa_tagihan || 0).toLocaleString('id-ID')}`,
    payment_badge: item.payment_status_label || '-',
    faktur_label: item.no_faktur || '-',
    operasional_label: resolveOperationalLabel(item)
  }))
);

const selectedKey = computed(() => selectedRow.value?.id || '');

const tableColumns = [
  { key: 'no_order', label: 'No Order' },
  { key: 'faktur_label', label: 'No Faktur' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'tanggal_order', label: 'Tanggal Order' },
  { key: 'tanggal_jatuh_tempo', label: 'Jatuh Tempo' },
  { key: 'status_order_label', label: 'Status Order' },
  { key: 'status_faktur_label', label: 'Status Faktur' },
  { key: 'payment_badge', label: 'Status Pembayaran' },
  { key: 'total_penjualan_label', label: 'Nilai Faktur' },
  { key: 'total_voucher_used_label', label: 'Voucher/Promo' },
  { key: 'total_setoran_label', label: 'Sudah Bayar' },
  { key: 'sisa_tagihan_label', label: 'Sisa Tagihan' }
];

const primaryInvoiceAction = computed(() => {
  if (!selectedRow.value) {
    return null;
  }

  const status = Number(selectedRow.value.status_order ?? -999);

  if (!selectedRow.value.no_faktur) {
    return { label: 'Masih Menunggu Faktur', route: { name: 'sales-order-list' } };
  }

  if (status === 3) {
    return {
      label: 'Buka Shipping',
      route: {
        name: 'distribution-invoices',
        query: {
          stage: 'shipping',
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  if (status === 5) {
    return {
      label: 'Buka Revisi Faktur',
      route: {
        name: 'distribution-invoice-revisions',
        query: {
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  if ([4, 11].includes(status)) {
    return {
      label: 'Buka Realisasi',
      route: {
        name: 'distribution-invoices',
        query: {
          stage: 'realisasi',
          id_cabang: selectedRow.value.id_cabang,
          sales_order_id: selectedRow.value.id
        }
      }
    };
  }

  // Invoice dengan distribusi selesai cukup menyediakan aksi faktur,
  // pembayaran, dan retur. Tidak perlu membuka realisasi lagi.
  if (status === 6) {
    return null;
  }

  return {
    label: 'Buka Detail Faktur',
    route: {
      name: 'distribution-invoices',
      query: {
        stage: 'shipping',
        id_cabang: selectedRow.value.id_cabang,
        sales_order_id: selectedRow.value.id
      }
    }
  };
});

function resolveOperationalLabel(item) {
  if (!item.no_faktur) return 'Masih di distribusi';
  if (item.payment_status_label === 'Lunas') return 'Selesai finance';
  if (Number(item.status_order) === 3) return 'Buka shipping';
  if (Number(item.status_order) === 5) return 'Perlu revisi faktur / realisasi';
  if ([4, 11].includes(Number(item.status_order))) return 'Buka realisasi menuju delivered';
  if (Number(item.status_order) === 6) return 'Distribusi selesai / delivered';
  return 'Pantau faktur dan pembayaran';
}

function resolveSetoranStage(item) {
  return item?.setoran_stage_label || resolveDepositStageLabel(item);
}

function resetFilters() {
  filters.salesUserId = route.query.sales_user_id ? String(route.query.sales_user_id) : canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
  filters.branchId = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.fakturStatus = '';
  filters.paymentStatus = '';
  filters.taxStatus = '';
  filters.dateFrom = '';
  filters.dateTo = '';
  filters.search = '';
  items.value = [];
  selectedRow.value = null;
  invoiceSummaryOpen.value = false;
  loadInvoices();
}

async function loadReferenceData() {
  const [companiesResponse, branchesResponse, principalsResponse, salesResponse] = await Promise.all([getCompanies(), getBranches(), getPrincipals(), getSales()]);
  companyRows.value = normalizeList(unwrapResponse(companiesResponse));
  branchRows.value = normalizeList(unwrapResponse(branchesResponse));
  principalRows.value = normalizeList(unwrapResponse(principalsResponse));
  salesRows.value = normalizeList(unwrapResponse(salesResponse));
  if (shouldLockBusinessScope.value && fallbackBranchId.value) filters.branchId = String(fallbackBranchId.value);
  if (shouldLockBusinessScope.value && fallbackCompanyId.value) filters.companyId = String(fallbackCompanyId.value);
  if (canUseLoginScope.value && fallbackUserId.value && !filters.salesUserId) filters.salesUserId = String(fallbackUserId.value);
  syncBranchFromCompany();
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    syncBranchFromCompany();
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
    invoiceSummaryOpen.value = false;
    return;
  }

  if (filters.branchId !== previousBranchId) {
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
    invoiceSummaryOpen.value = false;
  }
}

function syncBranchFromCompany() {
  if (!filters.companyId) {
    if (!shouldLockBusinessScope.value) filters.branchId = '';
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    return;
  }

  if (filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

function openInvoiceSummary(row) {
  selectedRow.value = row;
  printError.value = '';
  invoiceSummaryOpen.value = true;
}

function firstId(value) {
  if (Array.isArray(value)) return firstId(value[0]);
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .find(Boolean) || '';
}

function buildInvoicePrintHeader(row, detail, detailRows) {
  const activeCompany = companyRows.value.find((item) =>
    String(item.id) === String(detail?.id_perusahaan || row?.id_perusahaan || filters.companyId || fallbackCompanyId.value)
  );
  const activeBranch = branchRows.value.find((item) =>
    String(item.id) === String(detail?.id_cabang || row?.id_cabang || filters.branchId || fallbackBranchId.value)
  );
  const subtotal = detailRows.reduce((total, item) =>
    total + Number(item.subtotalorder || item.subtotal || item.total_harga || 0), 0
  );
  const taxTotal = Number(
    detail?.pajak || detail?.ppn || detailRows.reduce((total, item) => total + Number(item.ppn || 0), 0)
  );

  return {
    idFaktur: detail?.id_faktur || firstId(row?.id_faktur),
    noFaktur: detail?.nomor_faktur || detail?.no_faktur || row?.no_faktur || '-',
    noOrder: detail?.no_order || row?.no_order || '-',
    date: detail?.tanggal_faktur || detail?.tanggal_order || row?.tanggal_order || new Date().toISOString().slice(0, 10),
    dueDate: detail?.tanggal_jatuh_tempo || row?.tanggal_jatuh_tempo || '',
    customer: detail?.nama_customer || row?.nama_customer || '-',
    kodeCustomer: detail?.kode_customer || row?.kode_customer || '-',
    address: detail?.alamat_customer || detail?.alamat || row?.alamat || '-',
    sales: detail?.nama_sales_order || detail?.nama_sales || row?.nama_sales || '-',
    fakturist: auth.user?.nama || auth.user?.name || auth.user?.nama_user || '-',
    routeCode: detail?.kode_rute || detail?.kode_principal || '-',
    po: detail?.po || detail?.no_po || row?.po || row?.no_po || '',
    companyName: detail?.nama_perusahaan || activeCompany?.nama || 'PT. BUDIMAS MAKMUR MULIA',
    companyAddress: detail?.alamat_perusahaan || activeBranch?.alamat || '',
    companyPhone: detail?.telepon_perusahaan || activeBranch?.telepon || activeCompany?.telepon || '',
    companyBank: detail?.rekening_perusahaan || '',
    printTime: new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }),
    subtotal,
    taxTotal,
    grandTotal: Number(detail?.total_penjualan || detail?.total_bayar || row?.total_penjualan || subtotal + taxTotal),
    printCount: Number(detail?.jumlah_cetak || row?.jumlah_cetak || 0)
  };
}

async function printSelectedInvoice() {
  if (printSubmitting.value || !selectedRow.value?.no_faktur) return;

  printError.value = '';
  const printWindow = reservePrintWindow({ width: 1280, height: 760 });
  if (!printWindow) {
    printError.value = 'Popup cetak diblokir browser. Izinkan popup untuk mencetak faktur.';
    return;
  }

  printSubmitting.value = true;
  try {
    printWindow.document.write('<!doctype html><title>Menyiapkan cetakan</title><p style="font-family:Arial,sans-serif;padding:24px">Menyiapkan faktur…</p>');
    printWindow.document.close();

    const response = await getInvoiceDetail(Number(selectedRow.value.id));
    const payload = unwrapResponse(response) || {};
    const detailRows = normalizeList(payload?.list_detail_order || payload).filter((item) => item && typeof item === 'object');
    const detail = payload?.detail_faktur || {};
    if (!detailRows.length) {
      throw new Error('Detail faktur belum tersedia sehingga belum dapat dicetak.');
    }

    const header = buildInvoicePrintHeader(selectedRow.value, detail, detailRows);
    const idFaktur = Number(header.idFaktur || 0);
    if (!idFaktur) {
      throw new Error('ID faktur belum tersedia. Muat ulang data lalu coba cetak kembali.');
    }

    const printResponse = await recordInvoicePrint(idFaktur);
    const printResult = unwrapResponse(printResponse) || {};
    header.printCount = Number(printResult?.jumlah_cetak || header.printCount + 1);
    selectedRow.value = { ...selectedRow.value, jumlah_cetak: header.printCount };

    const html = buildSalesDocumentHtml({
      type: 'invoice',
      title: 'Faktur Penjualan',
      header,
      rows: detailRows,
      company: {
        name: header.companyName,
        address: header.companyAddress,
        phone: header.companyPhone
      }
    });
    if (!openPrintHtml(`Faktur Penjualan - ${header.noFaktur}`, html, { printWindow, width: 1280, height: 760 })) {
      throw new Error('Popup cetak diblokir browser. Izinkan popup untuk mencetak faktur.');
    }
  } catch (error) {
    if (!printWindow.closed) printWindow.close();
    printError.value = normalizeError(error, 'Faktur belum dapat disiapkan untuk dicetak.');
  } finally {
    printSubmitting.value = false;
  }
}

async function navigateToInvoiceAction(targetRoute = primaryInvoiceAction.value?.route) {
  if (!targetRoute) return;

  invoiceSummaryOpen.value = false;
  await nextTick();
  router.push(targetRoute);
}

async function loadInvoices() {
  loading.value = true;
  loadError.value = '';
  selectedRow.value = null;
  invoiceSummaryOpen.value = false;

  try {
    const response = await getSalesInvoiceDashboard({
      user_id: filters.salesUserId || (canUseLoginScope.value ? fallbackUserId.value : undefined),
      id_sales: selectedSales.value?.id_sales || selectedSales.value?.id || undefined,
      id_cabang: filters.branchId || (shouldLockBusinessScope.value ? fallbackBranchId.value : undefined),
      id_perusahaan: filters.companyId || undefined,
      faktur_status: filters.fakturStatus || undefined,
      payment_status: filters.paymentStatus || undefined,
      status_pajak: filters.taxStatus || undefined,
      date_from: filters.dateFrom || undefined,
      date_to: filters.dateTo || undefined,
      search: filters.search || undefined
    });
    const payload = unwrapResponse(response) || {};
    items.value = normalizeList(payload);
    summary.value = {
      total_invoices: Number(payload?.summary?.total_invoices || items.value.length || 0),
      belum_faktur: Number(payload?.summary?.belum_faktur || 0),
      belum_bayar: Number(payload?.summary?.belum_bayar || 0),
      sebagian: Number(payload?.summary?.sebagian || 0),
      lunas: Number(payload?.summary?.lunas || 0),
      total_tagihan: Number(payload?.summary?.total_tagihan || 0),
      total_setoran_cash: Number(payload?.summary?.total_setoran_cash || 0),
      total_voucher_used: Number(payload?.summary?.total_voucher_used || 0),
      total_setoran: Number(payload?.summary?.total_setoran || 0),
      total_sisa_tagihan: Number(payload?.summary?.total_sisa_tagihan || 0)
    };
  } catch (error) {
    loadError.value = normalizeError(error, 'Dashboard invoice sales belum bisa dimuat.');
    items.value = [];
    summary.value = {
      total_invoices: 0,
      belum_faktur: 0,
      belum_bayar: 0,
      sebagian: 0,
      lunas: 0,
      total_tagihan: 0,
      total_setoran_cash: 0,
      total_voucher_used: 0,
      total_setoran: 0,
      total_sisa_tagihan: 0
    };
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  filters.salesUserId = route.query.sales_user_id ? String(route.query.sales_user_id) : canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
  filters.branchId = shouldLockBusinessScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';

  try {
    await loadReferenceData();
  } catch (error) {
    loadError.value = normalizeError(error, 'Referensi sales dan cabang belum bisa dimuat.');
  }

  await loadInvoices();
});

watch(
  () => filters.companyId,
  (companyId, previousCompanyId) => {
    if (companyId === previousCompanyId) return;
    syncBranchFromCompany();
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
    invoiceSummaryOpen.value = false;
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;
    filters.salesUserId = canUseLoginScope.value && fallbackUserId.value ? String(fallbackUserId.value) : '';
    items.value = [];
    selectedRow.value = null;
    invoiceSummaryOpen.value = false;
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Invoice Order"
      description="Pantau invoice yang sudah terbentuk dari order sales, cek status operasional dan pembayaran, lalu lompat cepat ke detail faktur atau finance."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="loadInvoices">
          Refresh Data
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'sales-order-list', query: salesQuery() })">
          Buka Order Sales
        </button>
        <button
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          @click="
            router.push({
              name: 'finance-payments',
              query: selectedRow
                ? {
                    ...salesQuery(),
                    id_plafon: selectedRow.id_plafon,
                    id_sales: selectedRow.id_sales || filters.salesUserId || fallbackUserId,
                    id_sales_order: selectedRow.id,
                    no_faktur: selectedRow.no_faktur || '',
                    customer_name: selectedRow.nama_customer || ''
                  }
                : salesQuery()
            })
          "
        >
          Buka Pembayaran
        </button>
        <button
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
          :disabled="!selectedRow || !primaryInvoiceAction"
          @click="selectedRow && primaryInvoiceAction ? navigateToInvoiceAction(primaryInvoiceAction.route) : null"
        >
          {{ primaryInvoiceAction?.label || 'Buka/Cetak Faktur' }}
        </button>
        <button
          class="rounded-xl border border-brand-200 bg-white px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="!selectedRow?.no_faktur || printSubmitting"
          @click="printSelectedInvoice"
        >
          {{ printSubmitting ? 'Menyiapkan Faktur...' : 'Cetak Faktur' }}
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Invoice</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total_invoices.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Belum Bayar</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.belum_bayar.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sebagian</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.sebagian.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Lunas</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.lunas.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <section class="grid gap-4 md:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Tagihan</p>
        <p class="mt-3 text-xl font-semibold text-slate-900">Rp {{ Number(summary.total_tagihan || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Voucher/Promo</p>
        <p class="mt-3 text-xl font-semibold text-slate-900">Rp {{ Number(summary.total_voucher_used || 0).toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sudah Dibayar</p>
        <p class="mt-3 text-xl font-semibold text-slate-900">Rp {{ Number(summary.total_setoran || 0).toLocaleString('id-ID') }}</p>
        <p v-if="Number(summary.total_voucher_used || 0) > 0" class="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Tunai/non tunai Rp {{ Number(summary.total_setoran_cash || 0).toLocaleString('id-ID') }} + voucher/promo.
        </p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sisa Tagihan</p>
        <p class="mt-3 text-xl font-semibold text-slate-900">Rp {{ Number(summary.total_sisa_tagihan || 0).toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadInvoices"
      @reset="resetFilters"
    />

    <div v-if="loadError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ loadError }}
    </div>

    <div v-if="printError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ printError }}
    </div>

    <section>
      <article class="panel p-5">
        <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Daftar Invoice / Faktur Sales</h3>
            <p class="mt-1 text-sm text-slate-500">Klik baris untuk membuka ringkasan invoice dalam modal.</p>
          </div>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="normalizedRows"
          :loading="loading"
          row-key="row_key"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada invoice sales yang cocok dengan filter."
          @row-click="openInvoiceSummary"
        />
      </article>
    </section>

    <AppModal
      :open="invoiceSummaryOpen"
      title="Ringkasan Invoice"
      :description="selectedRow ? 'Status, nilai, dan aksi invoice terpilih.' : 'Pilih invoice dari tabel.'"
      size="4xl"
      @close="invoiceSummaryOpen = false"
    >
      <div v-if="selectedRow" class="space-y-4">
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
          <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
          <div class="mt-2 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p class="font-semibold text-slate-900 dark:text-white">{{ selectedRow.nama_customer || '-' }}</p>
              <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ selectedRow.no_faktur || selectedRow.no_order || '-' }}</p>
            </div>
            <p class="rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-200">
              {{ selectedRow.operasional_label || '-' }}
            </p>
          </div>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Status Pembayaran</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.payment_status_label || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Status Faktur</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ selectedRow.status_faktur_label || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Tahap Setoran</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ resolveSetoranStage(selectedRow) }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Sisa Tagihan</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">Rp {{ Number(selectedRow.sisa_tagihan || 0).toLocaleString('id-ID') }}</p>
          </article>
        </div>

        <div class="grid gap-3 sm:grid-cols-3">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Pembayaran Tunai/Non Tunai</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">Rp {{ Number(selectedRow.total_setoran_cash || 0).toLocaleString('id-ID') }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Voucher/Promo Terpakai</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">Rp {{ Number(selectedRow.total_voucher_used || 0).toLocaleString('id-ID') }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-wide text-slate-400">Total Diakui Bayar</p>
            <p class="mt-2 font-semibold text-slate-900 dark:text-white">Rp {{ Number(selectedRow.total_setoran || 0).toLocaleString('id-ID') }}</p>
          </article>
        </div>

        <div class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
          <p class="font-semibold">Langkah berikutnya</p>
          <p class="mt-1">
            <span v-if="Number(selectedRow.status_order) === 3">Order sudah final picking, lanjut shipping.</span>
            <span v-else-if="Number(selectedRow.status_order) === 5">Order perlu revisi faktur sebelum selesai.</span>
            <span v-else-if="[4, 11].includes(Number(selectedRow.status_order))">Order dalam pengiriman, lanjut realisasi.</span>
            <span v-else-if="Number(selectedRow.status_order) === 6">Distribusi selesai, pantau pembayaran atau retur.</span>
            <span v-else>{{ selectedRow.operasional_label || 'Pantau status order.' }}</span>
          </p>
        </div>

        <div
          class="grid gap-2"
          :class="primaryInvoiceAction ? 'sm:grid-cols-4' : 'sm:grid-cols-3'"
        >
          <button
            v-if="primaryInvoiceAction"
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
            @click="navigateToInvoiceAction()"
          >
            {{ primaryInvoiceAction?.label || 'Buka/Cetak Faktur' }}
          </button>
          <button
            class="rounded-xl border border-brand-200 bg-white px-4 py-2 text-sm font-medium text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="!selectedRow.no_faktur || printSubmitting"
            @click="printSelectedInvoice"
          >
            {{ printSubmitting ? 'Menyiapkan...' : 'Cetak Faktur' }}
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            @click="
              router.push({
                name: 'finance-payments',
                query: {
                  ...salesQuery(),
                  id_plafon: selectedRow.id_plafon,
                  id_sales: selectedRow.id_sales || filters.salesUserId || fallbackUserId,
                  id_sales_order: selectedRow.id,
                  no_faktur: selectedRow.no_faktur || '',
                  customer_name: selectedRow.nama_customer || ''
                }
              })
            "
          >
            Buka Pembayaran
          </button>
          <button
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
            :disabled="!selectedRow.no_faktur"
            @click="
              router.push({
                name: 'sales-order-retur',
                query: {
                  ...salesQuery(),
                  id_sales_order: selectedRow.id,
                  id_sales: selectedRow.id_sales || filters.salesUserId || fallbackUserId,
                  id_plafon: selectedRow.id_plafon,
                  no_order: selectedRow.no_order,
                  no_faktur: selectedRow.no_faktur,
                  customer_name: selectedRow.nama_customer
                }
              })
            "
          >
            Ajukan Retur
          </button>
        </div>
      </div>

      <div v-else class="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-400">
        Belum ada invoice dipilih.
      </div>

      <template #footer>
        <div class="flex flex-wrap justify-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800" @click="invoiceSummaryOpen = false">
            Tutup
          </button>
        </div>
      </template>
    </AppModal>
  </div>
</template>
