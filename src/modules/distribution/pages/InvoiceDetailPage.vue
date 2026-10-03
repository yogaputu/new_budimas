<script setup>
import { computed, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { getInvoiceDetail, getRealizationDetail, getRealizationInvoices, getRealizationRoutes, getShippingInvoices, getShippingRoutes, recordInvoicePrint, submitInvoices, submitRealization } from '@/api/distribution';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { toLocalDateInputValue } from '@/utils/date';
import { buildSalesDocumentHtml, openPrintHtml, reservePrintWindow } from '@/utils/printTemplates';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const salesOrderId = ref('');
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  stage: 'shipping'
});
const shippingForm = reactive({
  namaFakturist: ''
});
const realizationForm = reactive({
  namaUser: '',
  pembayaranViaDropper: '',
  rows: []
});
const companies = ref([]);
const branches = ref([]);
const routeRows = ref([]);
const invoiceListRows = ref([]);
const selectedRoute = ref(null);
const selectedInvoice = ref(null);
const invoiceRows = ref([]);
const invoiceHeader = ref({});
const invoiceModalOpen = ref(false);
const loading = ref(false);
const routeLoading = ref(false);
const invoiceLoading = ref(false);
const shippingSubmitting = ref(false);
const realizationSubmitting = ref(false);
const printSubmitting = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const successToast = ref('');
let toastTimer = null;
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser(authStore));

const stageOptions = [
  { value: 'shipping', label: 'Shipping' },
  { value: 'realisasi', label: 'Realisasi' }
];

const invoiceFlowSteps = [
  { number: '1', title: 'Pilih Tahap', note: 'Gunakan Shipping atau Realisasi sesuai status order.' },
  { number: '2', title: 'Pilih Rute', note: 'Rute membawa armada, driver, dan tanggal kirim.' },
  { number: '3', title: 'Pilih Faktur', note: 'Detail produk akan tampil dari faktur terpilih.' },
  { number: '4', title: 'Proses Dokumen', note: 'Cetak, submit shipping, atau input realisasi.' }
];

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);

  if (branchCompanyId) ids.add(String(branchCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, authStore));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, authStore, filters.id_perusahaan)
);

const isCompletedInvoiceView = computed(() => String(route.query.view || '').toLowerCase() === 'completed');
const isRealisasiMode = computed(() => filters.stage === 'realisasi');
const pageTitle = computed(() => {
  if (isCompletedInvoiceView.value) return 'Faktur Selesai';
  return isRealisasiMode.value ? 'Detail Faktur Realisasi' : 'Detail Faktur Distribusi';
});
const pageDescription = computed(() =>
  isCompletedInvoiceView.value
    ? 'Tampilan baca-saja untuk faktur pada sales order yang sudah selesai, termasuk seluruh principal dalam satu invoice batch.'
    : isRealisasiMode.value
    ? 'Browse rute realisasi, klik faktur, lalu cek detail produk tanpa input ID manual.'
    : 'Browse rute shipping, klik faktur, lalu cek detail produk tanpa input ID manual.'
);
const routeSectionTitle = computed(() => (isRealisasiMode.value ? 'Rute Realisasi' : 'Rute Shipping'));
const routeSectionDescription = computed(() =>
  isRealisasiMode.value
    ? 'Klik rute untuk memuat daftar faktur sesuai armada, driver, dan tanggal realisasi.'
    : 'Klik rute untuk memuat daftar faktur sesuai armada, driver, dan tanggal kirim.'
);
const invoiceSectionTitle = computed(() => {
  if (isCompletedInvoiceView.value) return 'Faktur Selesai';
  return isRealisasiMode.value ? 'Faktur Realisasi' : 'Faktur Shipping';
});
const routeEmptyMessage = computed(() => (isRealisasiMode.value ? 'Belum ada rute realisasi.' : 'Belum ada rute shipping.'));
const invoiceEmptyMessage = computed(() => (isRealisasiMode.value ? 'Belum ada faktur realisasi untuk rute ini.' : 'Belum ada faktur untuk rute ini.'));

const routeTableRows = computed(() =>
  routeRows.value.map((item) => ({
    ...item,
    route_label: `${item.kode || item.kode_rute || '-'} - ${item.nama_rute || 'Rute'}`,
    armada_label: item.nama_armada || item.no_pelat || item.id_armada || '-',
    driver_label: item.nama_driver || item.nama || item.id_driver || '-',
    total_label: item.total_penjualan ? `Rp ${Number(item.total_penjualan).toLocaleString('id-ID')}` : '-'
  }))
);
const selectedRouteKey = computed(() =>
  selectedRoute.value
    ? `${selectedRoute.value.id_rute || ''}-${selectedRoute.value.id_armada || ''}-${selectedRoute.value.id_driver || ''}-${selectedRoute.value.delivering_date || ''}`
    : ''
);
const selectedInvoiceKey = computed(() =>
  selectedInvoice.value
    ? `${selectedInvoice.value.no_faktur || ''}-${firstSalesOrderId(selectedInvoice.value.id_sales_order) || ''}`
    : ''
);

const canSubmitShipping = computed(() =>
  !isRealisasiMode.value &&
  !!selectedRoute.value &&
  !!selectedInvoice.value &&
  !!invoiceRows.value.length &&
  !!filters.id_cabang &&
  !shippingSubmitting.value
);

const canSubmitRealization = computed(() =>
  isRealisasiMode.value &&
  !!selectedRoute.value &&
  !!selectedInvoice.value &&
  realizationForm.rows.some((item) => Number(item.realisasi || 0) > 0) &&
  !realizationSubmitting.value
);

const hasPrintedInvoice = computed(() =>
  Number(invoiceHeader.value.jumlah_cetak || selectedInvoice.value?.jumlah_cetak || 0) > 0
);

const invoiceTableRows = computed(() =>
  invoiceListRows.value.map((item) => ({
    ...item,
    sales_order_label: Array.isArray(item.id_sales_order) ? item.id_sales_order.join(', ') : item.id_sales_order,
    customer_label: `${item.kode_customer || '-'} - ${item.nama_customer || '-'}`,
    total_label: item.total_bayar || item.total_penjualan ? `Rp ${Number(item.total_bayar || item.total_penjualan).toLocaleString('id-ID')}` : '-'
  }))
);

const detailRows = computed(() =>
  invoiceRows.value.map((item) => ({
    ...item,
    subtotal_label: formatCurrency(item.subtotalorder),
    total_order_label: Number(item.subtotalorder || 0),
    qty_uom_label: formatDetailUomQuantity(item),
    qty_pcs_label: formatDetailCanonicalQuantity(item)
  }))
);

const detailSummary = computed(() => {
  const totalItems = invoiceRows.value.length;
  const totalQty = invoiceRows.value.reduce((acc, item) => acc + detailCanonicalPieces(item), 0);
  const totalSubtotal = invoiceRows.value.reduce((acc, item) => acc + Number(item.subtotalorder || 0), 0);

  return [
    { label: 'Baris Produk', value: totalItems.toLocaleString('id-ID') },
    { label: 'Total PCS', value: totalQty.toLocaleString('id-ID') },
    { label: 'Subtotal', value: formatCurrency(totalSubtotal) }
  ];
});

function formatCurrency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function numericValue(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function detailUomName(row, level) {
  const names = {
    1: ['puom1_nama', 'uom1_nama', 'uom_1_nama', 'uom1', 'satuan'],
    2: ['puom2_nama', 'uom2_nama', 'uom_2_nama', 'uom2'],
    3: ['puom3_nama', 'uom3_nama', 'uom_3_nama', 'uom3']
  };
  const codes = {
    1: ['puom1_kode', 'uom1_kode', 'uom_1_kode'],
    2: ['puom2_kode', 'uom2_kode', 'uom_2_kode'],
    3: ['puom3_kode', 'uom3_kode', 'uom_3_kode']
  };

  const value = [...(names[level] || []), ...(codes[level] || [])]
    .map((key) => row?.[key])
    .find((item) => item !== undefined && item !== null && String(item).trim() !== '');

  return String(value || (level === 1 ? 'PCS' : '')).trim();
}

function detailUomConversion(row, level) {
  const value = row?.[`konversi_level${level}`] ?? row?.[`konversi${level}`];
  const conversion = numericValue(value, level === 1 ? 1 : 0);
  return conversion > 0 ? conversion : (level === 1 ? 1 : 0);
}

function isDetailUomEnabled(row, level) {
  // Level 1 is the base quantity and remains visible even on old products
  // whose UOM name was never filled. Higher levels must exist in the master
  // *and* carry a positive conversion factor.
  if (level === 1) return true;
  return Boolean(detailUomName(row, level)) && detailUomConversion(row, level) > 0;
}

function detailCanonicalPieces(row) {
  const suppliedTotal = row?.qty_order_pcs;
  if (suppliedTotal !== undefined && suppliedTotal !== null && String(suppliedTotal).trim() !== '') {
    return Math.max(0, Math.floor(numericValue(suppliedTotal)));
  }

  return Math.max(0, Math.floor(
    numericValue(row?.pieces_order) * detailUomConversion(row, 1) +
    numericValue(row?.box_order) * detailUomConversion(row, 2) +
    numericValue(row?.karton_order) * detailUomConversion(row, 3)
  ));
}

function formatDetailUomQuantity(row) {
  const fields = [
    { level: 3, key: 'karton_order' },
    { level: 2, key: 'box_order' },
    { level: 1, key: 'pieces_order' }
  ];
  const parts = fields
    .filter(({ level }) => isDetailUomEnabled(row, level))
    .map(({ level, key }) => ({ level, value: Math.max(0, numericValue(row?.[key])) }))
    .filter(({ value }) => value > 0)
    .map(({ level, value }) => `${value.toLocaleString('id-ID')} ${detailUomName(row, level)}`);

  if (parts.length) return parts.join(' | ');
  return `0 ${detailUomName(row, 1)}`;
}

function formatDetailCanonicalQuantity(row) {
  return `${detailCanonicalPieces(row).toLocaleString('id-ID')} ${detailUomName(row, 1)}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatDate(value) {
  if (!value) {
    return '-';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }

  return date.toLocaleDateString('id-ID', {
    day: '2-digit',
    month: 'long',
    year: 'numeric'
  });
}

function firstFilledValue(...values) {
  return values.find((value) => value !== undefined && value !== null && String(value).trim() !== '') || '';
}

function normalizePrintCodeSegment(value) {
  return String(value || '')
    .split('#')[0]
    .trim();
}

function buildRoutePrincipalPrintCode() {
  // Header faktur adalah sumber utama.  Data rute yang sedang dipilih dapat
  // berasal dari daftar lama yang sebelumnya menyimpan format RUTE#CUSTOMER.
  const routeCode = normalizePrintCodeSegment(firstFilledValue(
    invoiceHeader.value.kode_rute,
    selectedInvoice.value?.kode_rute,
    selectedRoute.value?.kode_rute,
    selectedRoute.value?.kode
  ));
  const principalCode = normalizePrintCodeSegment(firstFilledValue(
    invoiceHeader.value.kode_principal,
    selectedInvoice.value?.kode_principal,
    selectedRoute.value?.kode_principal
  ));

  if (routeCode && principalCode) return `${routeCode}#${principalCode}`;
  if (routeCode) return routeCode;
  if (principalCode) return principalCode;
  return '-';
}

function firstStatusValue(...values) {
  return values.find((value) => value !== undefined && value !== null && String(value).trim() !== '');
}

function hasStatusLabel(value, labels) {
  const normalized = String(value || '').trim().toLowerCase();
  return labels.includes(normalized);
}

function buildInvoiceWatermark() {
  const invoiceStatus = firstStatusValue(
    invoiceHeader.value.status_faktur,
    selectedInvoice.value?.status_faktur
  );
  const orderStatus = firstStatusValue(
    invoiceHeader.value.status_order,
    selectedInvoice.value?.status_order
  );
  const invoiceStatusNumber = Number(invoiceStatus);
  const orderStatusNumber = Number(orderStatus);
  const invoiceStatusLabel = firstStatusValue(
    invoiceHeader.value.status_faktur_label,
    selectedInvoice.value?.status_faktur_label
  );
  const orderStatusLabel = firstStatusValue(
    invoiceHeader.value.status_order_str,
    selectedInvoice.value?.status_order_str
  );

  if (
    [-1, 4].includes(invoiceStatusNumber) ||
    [-1, 7].includes(orderStatusNumber) ||
    hasStatusLabel(invoiceStatusLabel, ['denied', 'canceled', 'cancelled', 'batal']) ||
    hasStatusLabel(orderStatusLabel, ['denied', 'canceled', 'cancelled', 'batal'])
  ) {
    return 'BATAL';
  }

  if (
    [3, 6].includes(invoiceStatusNumber) ||
    hasStatusLabel(invoiceStatusLabel, ['paid', 'lunas'])
  ) {
    return 'PAID';
  }

  return '';
}

function resolveTempoDays() {
  const numericTempo = [
    invoiceHeader.value.top,
    invoiceHeader.value.tempo_hari,
    selectedInvoice.value?.top,
    selectedInvoice.value?.tempo_hari
  ]
    .map((value) => Number(value))
    .find((value) => Number.isFinite(value) && value > 0);

  if (numericTempo) {
    return numericTempo;
  }

  const tempoLabel = firstFilledValue(
    invoiceHeader.value.tempo_label,
    selectedInvoice.value?.tempo_label,
    selectedInvoice.value?.terms
  );
  const labelDays = String(tempoLabel).match(/\d+/)?.[0];
  return labelDays ? Number(labelDays) : 0;
}

function addDaysToDate(dateValue, days) {
  if (!dateValue) return '';

  const dateText = String(dateValue).slice(0, 10);
  const match = dateText.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(dateValue);

  if (Number.isNaN(date.getTime())) return '';

  date.setDate(date.getDate() + Number(days || 0));
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0')
  ].join('-');
}

function resolvePrintDueDate() {
  const persistedDueDate = firstFilledValue(
    invoiceHeader.value.tanggal_jatuh_tempo,
    invoiceHeader.value.tanggal_cetak_jatuh_tempo,
    selectedInvoice.value?.tanggal_jatuh_tempo,
    selectedInvoice.value?.jatuh_tempo
  );
  if (persistedDueDate) {
    return persistedDueDate;
  }

  const shippingDate = firstFilledValue(
    selectedRoute.value?.delivering_date,
    invoiceHeader.value.tanggal_faktur,
    selectedInvoice.value?.delivering_date,
    selectedInvoice.value?.tanggal_faktur,
    invoiceHeader.value.tanggal_order,
    selectedInvoice.value?.tanggal_order
  );
  return addDaysToDate(shippingDate, resolveTempoDays());
}

function getPrintableHeader() {
  const now = new Date();
  const activeCompany = companies.value.find((item) => String(item.id) === String(filters.id_perusahaan || fallbackCompanyId.value));
  const activeBranch = branches.value.find((item) => String(item.id) === String(filters.id_cabang || fallbackBranchId.value));
  const subtotal = invoiceRows.value.reduce((acc, item) => acc + Number(item.subtotalorder || item.subtotal || item.total_harga || 0), 0);
  const discountTotal = invoiceRows.value.reduce((acc, item) => acc + Number(item.total_nilai_discount || item.total_diskon || item.diskon_total || 0), 0);
  const taxTotal = Number(invoiceHeader.value.pajak || invoiceHeader.value.ppn || invoiceRows.value.reduce((acc, item) => acc + Number(item.ppn || 0), 0));
  const grandTotal = Number(invoiceHeader.value.total_penjualan || invoiceHeader.value.total_bayar || subtotal + taxTotal);

  return {
    idFaktur: invoiceHeader.value.id_faktur || selectedInvoice.value?.id_faktur || '',
    noFaktur: invoiceHeader.value.nomor_faktur || invoiceHeader.value.no_faktur || selectedInvoice.value?.no_faktur || '-',
    noOrder: invoiceHeader.value.no_order || selectedInvoice.value?.no_order || selectedInvoice.value?.sales_order_label || salesOrderId.value || '-',
    tanggal: invoiceHeader.value.tanggal_faktur || invoiceHeader.value.tanggal_order || selectedInvoice.value?.tanggal_order || toLocalDateInputValue(),
    date: invoiceHeader.value.tanggal_faktur || invoiceHeader.value.tanggal_order || selectedInvoice.value?.tanggal_order || toLocalDateInputValue(),
    dueDate: resolvePrintDueDate(),
    customer: invoiceHeader.value.nama_customer || selectedInvoice.value?.nama_customer || '-',
    kodeCustomer: invoiceHeader.value.kode_customer || selectedInvoice.value?.kode_customer || '-',
    address: invoiceHeader.value.alamat_customer || invoiceHeader.value.alamat || selectedInvoice.value?.alamat || '-',
    principal: invoiceHeader.value.nama_principal || selectedInvoice.value?.nama_principal || '-',
    driver: invoiceHeader.value.nama_driver || selectedRoute.value?.nama_driver || '-',
    armada: invoiceHeader.value.nama_armada || selectedRoute.value?.nama_armada || '-',
    rute: selectedRoute.value?.nama_rute || invoiceHeader.value.nama_rute || '-',
    routeCode: buildRoutePrincipalPrintCode(),
    alamat: invoiceHeader.value.alamat_customer || invoiceHeader.value.alamat || selectedInvoice.value?.alamat || '-',
    companyName: invoiceHeader.value.nama_perusahaan || activeCompany?.nama || 'PT. BUDIMAS MAKMUR MULIA',
    companyAddress: invoiceHeader.value.alamat_perusahaan || activeBranch?.alamat,
    companyPhone: invoiceHeader.value.telepon_perusahaan || activeBranch?.telepon || activeCompany?.telepon,
    companyBank: invoiceHeader.value.rekening_perusahaan || '',
    sales: invoiceHeader.value.nama_sales_order || invoiceHeader.value.nama_sales || selectedInvoice.value?.nama_sales || selectedRoute.value?.nama_sales || '-',
    fakturist: shippingForm.namaFakturist || authStore.user?.nama || '-',
    printTime: now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' }),
    po: invoiceHeader.value.po || invoiceHeader.value.no_po || selectedInvoice.value?.po || selectedInvoice.value?.no_po || '',
    subtotal,
    discountTotal,
    taxTotal,
    grandTotal,
    printCount: Number(invoiceHeader.value.jumlah_cetak || selectedInvoice.value?.jumlah_cetak || 0),
    watermark: buildInvoiceWatermark()
  };
}

function buildPrintableRows() {
  return invoiceRows.value.map((item, index) => {
    const pieces = Number(item.pieces_order || item.pieces_shipped || item.pieces_delivered || 0);
    const box = Number(item.box_order || item.box_shipped || item.box_delivered || 0);
    const karton = Number(item.karton_order || item.karton_shipped || item.karton_delivered || 0);
    const subtotal = Number(item.subtotalorder || item.subtotal || item.total_harga || 0);

    return `
      <tr>
        <td>${index + 1}</td>
        <td>${escapeHtml(item.kode_sku || item.kode_produk || '-')}</td>
        <td>${escapeHtml(item.nama_produk || item.nama_barang || '-')}</td>
        <td class="num">${pieces.toLocaleString('id-ID')}</td>
        <td class="num">${box.toLocaleString('id-ID')}</td>
        <td class="num">${karton.toLocaleString('id-ID')}</td>
        <td class="num">${formatCurrency(subtotal)}</td>
      </tr>
    `;
  }).join('');
}

async function printDocument(type = 'faktur', options = {}) {
  if (printSubmitting.value) {
    return;
  }

  if (!invoiceRows.value.length) {
    errorMessage.value = 'Detail produk belum dimuat, belum bisa cetak dokumen.';
    return;
  }

  const isDelivery = type === 'surat-jalan';
  const title = isDelivery ? 'Surat Jalan' : 'Faktur Penjualan';
  const printWindow = reservePrintWindow({ width: 1280, height: 760 });
  if (!printWindow) {
    errorMessage.value = 'Popup cetak diblokir browser. Izinkan popup untuk membuka dokumen cetak.';
    return;
  }

  const header = getPrintableHeader();
  printSubmitting.value = true;

  try {
    if (!isDelivery) {
      const idFaktur = Number(header.idFaktur || 0);
      if (!idFaktur) {
        throw new Error('ID faktur belum tersedia. Muat ulang detail faktur lalu coba cetak kembali.');
      }

      printWindow.document.write('<!doctype html><title>Menyiapkan cetakan</title><p style="font-family:Arial,sans-serif;padding:24px">Menyiapkan faktur…</p>');
      printWindow.document.close();

      const response = await recordInvoicePrint(idFaktur);
      const result = unwrapResponse(response) || {};
      const printCount = Number(result.jumlah_cetak);
      header.printCount = Number.isFinite(printCount) ? printCount : Number(header.printCount || 0) + 1;
      invoiceHeader.value = {
        ...invoiceHeader.value,
        jumlah_cetak: header.printCount
      };
      showToast(options.reprint
        ? `Faktur dicetak ulang sebagai Cetak ke-${header.printCount}.`
        : `Faktur siap dicetak sebagai Cetak ke-${header.printCount}.`);
    }

    const html = buildSalesDocumentHtml({
      type: isDelivery ? 'delivery' : 'invoice',
      title,
      header,
      rows: invoiceRows.value,
      company: {
        name: header.companyName,
        address: header.companyAddress,
        phone: header.companyPhone
      }
    });

    const opened = openPrintHtml(`${title} - ${header.noFaktur}`, html, {
      width: 1280,
      height: 760,
      printWindow
    });
    if (!opened) {
      throw new Error('Popup cetak diblokir browser. Izinkan popup untuk membuka dokumen cetak.');
    }
  } catch (error) {
    if (!printWindow.closed) {
      printWindow.close();
    }
    errorMessage.value = normalizeError(error, 'Faktur belum dapat disiapkan untuk dicetak.');
  } finally {
    printSubmitting.value = false;
  }
}

function showToast(message) {
  successToast.value = message;
  if (toastTimer) {
    clearTimeout(toastTimer);
  }
  toastTimer = setTimeout(() => {
    successToast.value = '';
  }, 3500);
}

function normalizeNumber(value) {
  return Number(value || 0);
}

function parseIds(value) {
  if (Array.isArray(value)) {
    return [...new Set(value.map((item) => Number(item)).filter((item) => Number.isFinite(item) && item > 0))];
  }

  return [...new Set(String(value || '')
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item) && item > 0))];
}

function firstSalesOrderId(value) {
  if (Array.isArray(value)) {
    return value[0];
  }

  return String(value || '').split(',')[0].trim();
}

function getInvoiceSalesOrderIds(row) {
  return parseIds(row?.id_sales_order || row?.id_sales_orders || row?.sales_order_id);
}

function resolveInvoiceDetailRequest(row, fallbackId = salesOrderId.value) {
  const routeContext = !row && isCompletedInvoiceView.value
    ? {
        id_sales_order: route.query.id_sales_orders || route.query.sales_order_id || fallbackId,
        id_order_batch: route.query.id_order_batch,
        id_faktur: route.query.id_faktur
      }
    : null;
  const source = row || routeContext;
  const ids = source ? getInvoiceSalesOrderIds(source) : parseIds(fallbackId);
  const params = {};

  // Batch invoices keep their per-principal relation in faktur_detail.  The
  // detail endpoint needs both the batch and every related SO; using only the
  // first ID silently drops the other principal(s).
  if (source?.id_order_batch && ids.length) {
    params.id_order_batch = source.id_order_batch;
    params.id_sales_orders = ids.join(',');
  }

  if (source?.id_faktur) params.id_faktur = source.id_faktur;
  if (isCompletedInvoiceView.value) params.include_batch_invoice = 1;

  return {
    id: ids[0] || firstSalesOrderId(fallbackId),
    ids,
    params
  };
}

function syncStageFromRoute() {
  const stageQuery = String(route.query.stage || '').toLowerCase();
  filters.stage = stageQuery === 'realisasi' ? 'realisasi' : 'shipping';
}

function syncContextFromRoute() {
  if (route.query.id_cabang) {
    filters.id_cabang = String(route.query.id_cabang);
  }

  if (route.query.id_perusahaan) {
    filters.id_perusahaan = String(route.query.id_perusahaan);
  }

  if (route.query.sales_order_id) {
    salesOrderId.value = String(route.query.sales_order_id);
  }
}

async function autoSelectInvoiceBySalesOrder() {
  if (!salesOrderId.value || !invoiceListRows.value.length) {
    return false;
  }

  const targetId = String(salesOrderId.value);
  const matchedInvoice = invoiceListRows.value.find((item) =>
    parseIds(item.id_sales_order).map(String).includes(targetId)
  );

  if (!matchedInvoice) {
    return false;
  }

  await selectInvoice(matchedInvoice);
  return true;
}

async function autoSelectRouteBySalesOrder() {
  if (!salesOrderId.value || !routeRows.value.length) {
    return false;
  }

  for (const routeRow of routeRows.value) {
    await selectRoute(routeRow);
    const matched = await autoSelectInvoiceBySalesOrder();
    if (matched) {
      return true;
    }
  }

  return false;
}

async function loadBranches() {
  const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
  companies.value = normalizeList(unwrapResponse(companyResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));

  if (!filters.id_cabang && !isSuperUser(authStore) && fallbackBranchId.value) {
    filters.id_cabang = String(fallbackBranchId.value);
  }
  if (canUseLoginScope.value && fallbackCompanyId.value) {
    filters.id_perusahaan = String(fallbackCompanyId.value);
  }
  syncBranchFromCompany();

  if (!shippingForm.namaFakturist) {
    shippingForm.namaFakturist = String(
      authStore.user?.nama ||
      authStore.user?.name ||
      authStore.user?.nama_user ||
      ''
    );
  }

  if (!realizationForm.namaUser) {
    realizationForm.namaUser = shippingForm.namaFakturist;
  }
}

function clearRouteSelection() {
  routeRows.value = [];
  invoiceListRows.value = [];
  selectedRoute.value = null;
  selectedInvoice.value = null;
  invoiceModalOpen.value = false;
  realizationForm.rows = [];
}

function closeInvoiceModal() {
  invoiceModalOpen.value = false;
}

function syncBranchFromCompany() {
  // Route context arrives before master references are loaded.  Do not clear
  // a valid branch merely because the company/branch lookup is still empty.
  if (!branches.value.length || !filters.id_perusahaan || !filters.id_cabang) {
    return;
  }

  if (!companyIdsForBranch(filters.id_cabang).includes(String(filters.id_perusahaan))) {
    filters.id_cabang = '';
  }
}

async function loadRoutes() {
  if (!filters.id_cabang) {
    errorMessage.value = 'Pilih cabang terlebih dahulu.';
    return;
  }

  routeLoading.value = true;
  feedback.value = '';
  errorMessage.value = '';
  routeRows.value = [];
  invoiceListRows.value = [];
  selectedRoute.value = null;
  selectedInvoice.value = null;

  try {
    const response = isRealisasiMode.value ? await getRealizationRoutes(filters.id_cabang) : await getShippingRoutes(filters.id_cabang);
    routeRows.value = normalizeList(unwrapResponse(response));
    if (!routeRows.value.length) {
      feedback.value = isRealisasiMode.value ? 'Belum ada rute realisasi untuk cabang ini.' : 'Belum ada rute shipping untuk cabang ini.';
    } else if (salesOrderId.value) {
      await autoSelectRouteBySalesOrder();
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, isRealisasiMode.value ? 'Gagal memuat rute realisasi.' : 'Gagal memuat rute shipping.');
  } finally {
    routeLoading.value = false;
  }
}

async function selectRoute(row) {
  selectedRoute.value = row;
  selectedInvoice.value = null;
  invoiceModalOpen.value = true;
  invoiceListRows.value = [];
  invoiceRows.value = [];
  invoiceHeader.value = {};
  realizationForm.rows = [];
  invoiceLoading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await (isRealisasiMode.value ? getRealizationInvoices : getShippingInvoices)({
      id_cabang: filters.id_cabang,
      id_rute: row.id_rute,
      id_armada: row.id_armada,
      id_driver: row.id_driver,
      delivering_date: row.delivering_date
    });
    const payload = unwrapResponse(response);
    invoiceListRows.value = normalizeList(payload?.list_faktur || payload?.data || payload);
    if (!invoiceListRows.value.length) {
      feedback.value = isRealisasiMode.value ? 'Belum ada faktur realisasi pada rute yang dipilih.' : 'Belum ada faktur pada rute yang dipilih.';
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, isRealisasiMode.value ? 'Gagal memuat daftar faktur realisasi.' : 'Gagal memuat daftar faktur shipping.');
  } finally {
    invoiceLoading.value = false;
  }
}

async function selectInvoice(row) {
  selectedInvoice.value = row;
  invoiceModalOpen.value = true;
  const request = resolveInvoiceDetailRequest(row);
  salesOrderId.value = String(request.id || '');
  await loadDetail(request.id, row);
}

async function loadRealizationDetail(detailRequest) {
  if (!selectedRoute.value) {
    return;
  }

  const request = detailRequest || resolveInvoiceDetailRequest(null, salesOrderId.value);
  if (!request.id) {
    realizationForm.rows = [];
    return;
  }

  const response = await getRealizationDetail({
    id_cabang: filters.id_cabang,
    id_rute: selectedRoute.value.id_rute,
    id_sales_order: request.id,
    ...(request.params?.id_sales_orders ? { id_sales_orders: request.params.id_sales_orders } : {}),
    ...(request.params?.id_order_batch ? { id_order_batch: request.params.id_order_batch } : {}),
    id_armada: selectedRoute.value.id_armada,
    id_driver: selectedRoute.value.id_driver,
    delivering_date: selectedRoute.value.delivering_date
  });

  const rows = normalizeList(unwrapResponse(response)).map((item, index) => ({
    ...item,
    row_key: `${item.produk_id || item.id_produk || index}`,
    id_produk: Number(item.produk_id || item.id_produk || 0),
    id_faktur: Number(item.id_faktur || 0),
    id_detail_sales: item.id_detail_sales_array || item.id_order_detail || [],
    konversi1: Number(item.konversi1 || 1),
    konversi2: Number(item.konversi2 || 0),
    konversi3: Number(item.konversi3 || 0),
    jumlah_picked: Number(item.jumlah_picked || 0),
    realisasi: Number(item.realisasi || item.jumlah_picked || 0)
  }));

  realizationForm.rows = rows;
}

function buildShippingPayload() {
  if (!selectedRoute.value || !selectedInvoice.value) {
    return null;
  }

  const detailProduk = invoiceRows.value.map((product) => ({
    id_produk: product.id_produk,
    subtotal: normalizeNumber(product.subtotalorder ?? product.subtotal ?? product.total_harga),
    total_diskon: normalizeNumber(
      product.total_nilai_discount ??
      product.total_diskon ??
      product.diskon_total ??
      product.total_diskon_produk
    ),
    ppn: normalizeNumber(product.ppn)
  }));

  const subtotal = detailProduk.reduce((total, item) => total + normalizeNumber(item.subtotal), 0);
  const diskonNota = detailProduk.reduce((total, item) => total + normalizeNumber(item.total_diskon), 0);
  const pajak = detailProduk.reduce((total, item) => total + normalizeNumber(item.ppn), 0);

  return {
    id_rute: selectedRoute.value.id_rute,
    id_cabang: Number(filters.id_cabang),
    id_armada: Number(selectedRoute.value.id_armada),
    id_driver: Number(selectedRoute.value.id_driver),
    delivering_date: selectedRoute.value.delivering_date,
    nama_fakturist: shippingForm.namaFakturist || shippingForm.namaFakturist === '' ? shippingForm.namaFakturist : '',
    faktur_ids: parseIds(selectedInvoice.value.id_sales_order),
    faktur_data: [
      {
        id_sales_order: selectedInvoice.value.id_sales_order,
        detail_faktur: invoiceRows.value,
        faktur_info: {
          ...(selectedInvoice.value || {}),
          ...(invoiceHeader.value || {})
        },
        rincian_pembayaran: {
          subtotal,
          diskon_nota: diskonNota,
          pajak,
          total_penjualan: subtotal - diskonNota + pajak
        },
        detail_produk: detailProduk
      }
    ]
  };
}

async function processShipping() {
  const payload = buildShippingPayload();
  if (!payload) {
    errorMessage.value = 'Pilih rute dan faktur terlebih dahulu.';
    return;
  }

  shippingSubmitting.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await submitInvoices(payload);
    const payloadResponse = unwrapResponse(response) || response?.data || {};
    feedback.value = payloadResponse.message || 'Pengiriman berhasil diproses.';
    showToast(payloadResponse.message || 'Pengiriman berhasil diproses.');

    await loadRoutes();
    filters.stage = 'realisasi';
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Proses shipping belum berhasil dijalankan.');
  } finally {
    shippingSubmitting.value = false;
  }
}

async function processRealization() {
  if (!selectedRoute.value || !selectedInvoice.value) {
    errorMessage.value = 'Pilih rute dan faktur realisasi terlebih dahulu.';
    return;
  }

  const routeToRefresh = selectedRoute.value
    ? {
        id_rute: selectedRoute.value.id_rute,
        id_armada: selectedRoute.value.id_armada,
        id_driver: selectedRoute.value.id_driver,
        delivering_date: selectedRoute.value.delivering_date
      }
    : null;

  const realisasi = realizationForm.rows
    .filter((item) => Number(item.realisasi || 0) >= 0)
    .map((item) => ({
      realisasi: Number(item.realisasi || 0),
      id_detail_sales: item.id_detail_sales,
      id_faktur: Number(item.id_faktur || 0),
      id_produk: Number(item.id_produk || 0),
      konversi1: Number(item.konversi1 || 1),
      konversi2: Number(item.konversi2 || 0),
      konversi3: Number(item.konversi3 || 0)
    }))
    .filter((item) => item.id_produk && item.id_faktur);

  if (!realisasi.length) {
    errorMessage.value = 'Data realisasi belum valid.';
    return;
  }

  realizationSubmitting.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await submitRealization({
      realisasi,
      id_cabang: Number(filters.id_cabang),
      id_sales_order: Number(salesOrderId.value),
      id_order_batch: selectedInvoice.value?.id_order_batch ? Number(selectedInvoice.value.id_order_batch) : null,
      nama_user: realizationForm.namaUser || shippingForm.namaFakturist || '',
      no_faktur: selectedInvoice.value?.no_faktur || invoiceHeader.value?.no_faktur || invoiceHeader.value?.nomor_faktur || '',
      pembayaran_via_dropper: realizationForm.pembayaranViaDropper ? Number(realizationForm.pembayaranViaDropper) : undefined
    });

    const payloadResponse = unwrapResponse(response) || response?.data || {};
    feedback.value = payloadResponse.message || 'Realisasi berhasil diproses.';
    showToast(payloadResponse.message || 'Realisasi berhasil diproses.');

    await loadRoutes();

    if (routeToRefresh) {
      const matchedRoute = routeRows.value.find(
        (item) =>
          String(item.id_rute ?? '') === String(routeToRefresh.id_rute ?? '') &&
          String(item.id_armada ?? '') === String(routeToRefresh.id_armada ?? '') &&
          String(item.id_driver ?? '') === String(routeToRefresh.id_driver ?? '') &&
          String(item.delivering_date ?? '') === String(routeToRefresh.delivering_date ?? '')
      );

      if (matchedRoute) {
        await selectRoute(matchedRoute);
      }
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Proses realisasi belum berhasil dijalankan.');
  } finally {
    realizationSubmitting.value = false;
  }
}

async function loadDetail(id = salesOrderId.value, invoiceContext = null) {
  const detailRequest = invoiceContext
    ? resolveInvoiceDetailRequest(invoiceContext, id)
    : resolveInvoiceDetailRequest(null, id);
  const requestId = detailRequest.id;

  if (!requestId) {
    errorMessage.value = 'Isi Sales Order ID terlebih dahulu.';
    invoiceRows.value = [];
    invoiceHeader.value = {};
    return false;
  }

  if (!/^\d+$/.test(String(requestId).trim())) {
    errorMessage.value = 'Sales Order ID harus berupa angka.';
    invoiceRows.value = [];
    invoiceHeader.value = {};
    return false;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getInvoiceDetail(requestId, detailRequest.params);
    const payload = unwrapResponse(response) || {};
    invoiceRows.value = normalizeList(payload?.list_detail_order || payload);
    invoiceHeader.value = payload?.detail_faktur || {};

    if (!invoiceRows.value.length && !Object.keys(invoiceHeader.value || {}).length) {
      feedback.value = 'Detail faktur untuk sales order ini belum tersedia.';
    }

    if (isRealisasiMode.value && selectedRoute.value) {
      await loadRealizationDetail(detailRequest);
    } else {
      realizationForm.rows = [];
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Gagal memuat detail faktur.');
    invoiceRows.value = [];
    invoiceHeader.value = {};
    realizationForm.rows = [];
  } finally {
    loading.value = false;
  }

  return Boolean(invoiceRows.value.length || Object.keys(invoiceHeader.value || {}).length);
}

function buildCompletedInvoiceContext() {
  const detailRequest = resolveInvoiceDetailRequest(null, salesOrderId.value);
  return {
    id_sales_order: detailRequest.ids.join(',') || String(salesOrderId.value || ''),
    id_order_batch: detailRequest.params.id_order_batch || '',
    id_faktur: invoiceHeader.value.id_faktur || detailRequest.params.id_faktur || '',
    no_faktur: invoiceHeader.value.nomor_faktur || invoiceHeader.value.no_faktur || route.query.no_faktur || '',
    nama_customer: invoiceHeader.value.nama_customer || '',
    nama_principal: invoiceHeader.value.nama_principal || '',
    id_armada: route.query.id_armada || '',
    id_driver: route.query.id_driver || '',
    delivering_date: route.query.delivering_date || ''
  };
}

async function loadCompletedInvoiceFromRoute() {
  if (!isCompletedInvoiceView.value || !salesOrderId.value) return;

  const loaded = await loadDetail(salesOrderId.value);
  if (!loaded) return;

  // A finished invoice must be readable without reopening its old route.
  // The route list intentionally excludes status 6 because it is operational
  // only; this context keeps the completed document strictly read-only.
  selectedRoute.value = null;
  selectedInvoice.value = buildCompletedInvoiceContext();
  invoiceModalOpen.value = true;
}

async function loadInvoiceFromRoute() {
  if (!salesOrderId.value) return;
  if (isCompletedInvoiceView.value) {
    await loadCompletedInvoiceFromRoute();
    return;
  }
  await loadDetail();
}

onMounted(() => {
  syncStageFromRoute();
  syncContextFromRoute();
  loadBranches().then(loadInvoiceFromRoute);
});

onDeactivated(() => {
  closeInvoiceModal();
});

watch(
  () => filters.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    syncBranchFromCompany();
    clearRouteSelection();
  }
);

watch(
  () => filters.id_cabang,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;
    clearRouteSelection();
  }
);

watch(
  () => route.query.stage,
  () => {
    syncStageFromRoute();
    syncContextFromRoute();
    routeRows.value = [];
    invoiceListRows.value = [];
    selectedRoute.value = null;
    selectedInvoice.value = null;
    invoiceModalOpen.value = false;
    realizationForm.rows = [];
  }
);

watch(
  () => [route.query.sales_order_id, route.query.view, route.query.id_faktur],
  () => {
    syncContextFromRoute();
    loadInvoiceFromRoute();
  }
);

watch(
  () => filters.stage,
  (value) => {
    router.replace({
      query: {
        ...route.query,
        stage: value
      }
    });
    routeRows.value = [];
    invoiceListRows.value = [];
    selectedRoute.value = null;
    selectedInvoice.value = null;
    invoiceModalOpen.value = false;
    realizationForm.rows = [];
  }
);
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>

    <PageHeader :title="pageTitle" :description="pageDescription">
      <div class="flex flex-wrap gap-2">
        <button
          v-if="isCompletedInvoiceView"
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="loading || (!invoiceRows.length && !Object.keys(invoiceHeader || {}).length)"
          @click="invoiceModalOpen = true"
        >
          Buka Faktur Selesai
        </button>
        <button
          class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          @click="router.push({ name: 'sales-order-list', query: route.query.sales_user_id ? { sales_user_id: route.query.sales_user_id } : {} })"
        >
          Kembali ke Sales Order
        </button>
      </div>
    </PageHeader>

    <section v-if="isCompletedInvoiceView" class="rounded-2xl border border-sky-200 bg-sky-50 px-5 py-4 text-sm text-sky-900 dark:border-sky-400/30 dark:bg-sky-500/10 dark:text-sky-100">
      <p v-if="loading" class="font-medium">Memuat faktur selesai…</p>
      <p v-else-if="errorMessage" class="font-medium text-rose-700 dark:text-rose-200">{{ errorMessage }}</p>
      <p v-else-if="feedback" class="font-medium">{{ feedback }}</p>
      <p v-else>Faktur dibuka dalam mode baca-saja. Anda tetap dapat memeriksa detail dan mencetak ulang tanpa menjalankan realisasi kembali.</p>
    </section>

    <section v-if="!isCompletedInvoiceView" class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="step in invoiceFlowSteps" :key="step.number" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex items-start gap-3">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">{{ step.number }}</span>
          <div>
            <h3 class="text-sm font-semibold text-slate-900">{{ step.title }}</h3>
            <p class="mt-1 text-xs leading-5 text-slate-500">{{ step.note }}</p>
          </div>
        </div>
      </article>
    </section>

    <section v-if="!isCompletedInvoiceView" class="rounded-2xl border border-sky-200 bg-sky-50 px-5 py-4 text-sm text-sky-900">
      <p class="font-semibold">Alur shipping</p>
      <p class="mt-1">
        Setelah <span class="font-semibold">final picking</span>, order masuk ke tahap
        <span class="font-semibold">shipping</span>. Buka rute shipping, pilih faktur yang sesuai, lalu lanjutkan proses pengiriman.
        Setelah pengiriman berjalan atau selesai lapangan, pindah ke tahap
        <span class="font-semibold">realisasi</span>.
      </p>
    </section>

    <section v-if="!isCompletedInvoiceView" class="panel p-5">
      <div class="grid gap-3 md:grid-cols-[1fr_1fr_1fr_auto_auto]">
        <AppSearchSelect
          v-model="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Pilih perusahaan"
          :options="companyOptions"
          :disabled="canUseLoginScope && !!fallbackCompanyId"
          empty-text="Perusahaan belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.id_cabang"
          label="Cabang"
          placeholder="Pilih cabang"
          :options="branchOptions"
          :disabled="!filters.id_perusahaan || (!isSuperUser(authStore) && !!fallbackBranchId)"
          empty-text="Pilih perusahaan terlebih dahulu."
        />
        <AppSearchSelect v-model="filters.stage" label="Tahap" placeholder="Pilih tahap" :options="stageOptions" empty-text="Tahap belum tersedia." />
        <button class="self-end rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700" :disabled="routeLoading" @click="loadRoutes">
          {{ routeLoading ? 'Memuat...' : 'Muat Rute' }}
        </button>
        <button class="self-end rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="loading" @click="loadDetail()">
          Cari by ID
        </button>
      </div>
      <div class="mt-4">
        <AppFormField
          v-model="salesOrderId"
          label="Sales Order ID manual"
          placeholder="Masukkan ID numerik sales_order.id, bukan nomor faktur"
        />
        <p class="mt-2 text-xs text-slate-500">
          Gunakan klik baris faktur agar ID terisi otomatis. Nomor seperti <span class="font-semibold">NPBMMSLO-2604000002</span> adalah
          <span class="font-semibold">no_faktur</span>, bukan <span class="font-semibold">sales_order.id</span>.
        </p>
      </div>
      <div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
        Pilih rute lalu klik faktur. Nama fakturist, detail faktur, tombol cetak, dan tombol proses sekarang berada dalam satu modal faktur agar flow shipping tidak perlu buka-tutup panel.
      </div>
      <div v-if="feedback" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ feedback }}
      </div>
      <div v-if="errorMessage" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ errorMessage }}
      </div>
    </section>

    <section v-if="!isCompletedInvoiceView">
      <div class="mb-3">
        <h3 class="text-lg font-semibold text-slate-900 dark:text-white">{{ routeSectionTitle }}</h3>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ routeSectionDescription }}</p>
      </div>
      <AppTable
        :rows="routeTableRows"
        :columns="[
          { key: 'route_label', label: 'Rute' },
          { key: 'armada_label', label: 'Armada' },
          { key: 'driver_label', label: 'Driver' },
          { key: 'delivering_date', label: 'Tanggal' },
          { key: 'total_label', label: 'Total' }
        ]"
        :loading="routeLoading"
        :clickable-rows="true"
        :selected-key="selectedRouteKey"
        row-key="route_label"
        :empty-message="routeEmptyMessage"
        @row-click="selectRoute"
      />
    </section>

    <AppModal
      :open="invoiceModalOpen"
      :title="invoiceSectionTitle"
      :description="isCompletedInvoiceView
        ? `Faktur selesai ${invoiceHeader.nomor_faktur || invoiceHeader.no_faktur || route.query.no_faktur || ''}`.trim()
        : (selectedRoute ? `Rute ${selectedRoute.route_label || selectedRoute.nama_rute || '-'}` : 'Pilih rute untuk melihat faktur.')"
      size="7xl"
      @close="closeInvoiceModal"
    >
      <div class="space-y-5">
        <section v-if="!isCompletedInvoiceView">
          <div class="mb-3">
            <h3 class="text-lg font-semibold text-slate-900 dark:text-white">{{ invoiceSectionTitle }}</h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {{ selectedRoute ? (!isRealisasiMode ? 'Klik faktur, cek detailnya, lalu tekan Proses Shipping.' : 'Klik faktur untuk melihat detail produk.') : 'Pilih rute terlebih dahulu.' }}
            </p>
          </div>
          <AppTable
            :rows="invoiceTableRows"
            :columns="[
              { key: 'no_faktur', label: 'No Faktur' },
              { key: 'sales_order_label', label: 'Sales Order' },
              { key: 'customer_label', label: 'Customer' },
              { key: 'nama_principal', label: 'Principal' },
              { key: 'total_label', label: 'Total' }
            ]"
            :loading="invoiceLoading"
            :clickable-rows="true"
            :selected-key="selectedInvoiceKey"
            row-key="no_faktur"
            :empty-message="invoiceEmptyMessage"
            @row-click="selectInvoice"
          />
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800/70">
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Ringkasan Faktur</h3>
          <div class="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4 text-sm text-slate-600 dark:text-slate-300">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
              <p class="text-xs uppercase tracking-wide text-slate-400">No Faktur</p>
              <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ invoiceHeader.nomor_faktur || invoiceHeader.no_faktur || selectedInvoice?.no_faktur || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
              <p class="text-xs uppercase tracking-wide text-slate-400">Customer</p>
              <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ invoiceHeader.nama_customer || selectedInvoice?.nama_customer || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
              <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
              <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ invoiceHeader.nama_principal || selectedInvoice?.nama_principal || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
              <p class="text-xs uppercase tracking-wide text-slate-400">Driver</p>
              <p class="mt-2 font-semibold text-slate-900 dark:text-white">{{ invoiceHeader.nama_driver || selectedRoute?.nama_driver || '-' }}</p>
            </div>
          </div>
          <div v-if="selectedInvoice && !isRealisasiMode" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-100">
            Faktur terpilih siap diproses ke tahap shipping. Setelah berhasil, status order akan naik ke <span class="font-semibold">shipping</span> dan halaman ini otomatis diarahkan ke tahap <span class="font-semibold">realisasi</span>.
          </div>
          <div v-if="selectedInvoice && isRealisasiMode" class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-900 dark:border-sky-400/30 dark:bg-sky-500/10 dark:text-sky-100">
            <p>
              Cetak ulang memakai data faktur yang sama dan otomatis melanjutkan nomor <span class="font-semibold">Cetak ke-…</span>.
            </p>
            <button
              class="rounded-xl border border-sky-300 bg-white px-4 py-2 text-sm font-medium text-sky-800 hover:bg-sky-100 disabled:opacity-50 dark:border-sky-400/40 dark:bg-slate-900 dark:text-sky-100 dark:hover:bg-sky-500/20"
              :disabled="!invoiceRows.length || printSubmitting"
              @click="printDocument('faktur', { reprint: true })"
            >
              {{ printSubmitting ? 'Menyiapkan...' : 'Cetak Ulang Faktur' }}
            </button>
          </div>
        </section>

        <section v-if="selectedInvoice && !isRealisasiMode && !isCompletedInvoiceView" class="rounded-2xl border border-brand-200 bg-brand-50 p-5 dark:border-brand-400/30 dark:bg-brand-500/10">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Proses Shipping</h3>
              <p class="mt-1 text-sm text-slate-600 dark:text-slate-300">
                Isi nama fakturist, cek detail faktur di bawah, lalu cetak atau proses shipping dari modal ini.
              </p>
            </div>
            <span class="rounded-full bg-brand-600 px-3 py-1 text-xs font-bold uppercase tracking-[0.18em] text-white">
              Satu Modal
            </span>
          </div>

          <div class="mt-4 grid gap-3 lg:grid-cols-[1fr_auto_auto_auto]">
            <AppFormField
              v-model="shippingForm.namaFakturist"
              label="Nama Fakturist"
              placeholder="Nama petugas proses shipping"
            />
            <button
              class="self-end rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="!invoiceRows.length || printSubmitting"
              @click="printDocument('faktur', { reprint: hasPrintedInvoice })"
            >
              {{ printSubmitting ? 'Menyiapkan...' : (hasPrintedInvoice ? 'Cetak Ulang Faktur' : 'Cetak Faktur') }}
            </button>
            <button
              class="self-end rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
              :disabled="!invoiceRows.length || printSubmitting"
              @click="printDocument('surat-jalan')"
            >
              {{ printSubmitting ? 'Menyiapkan...' : 'Cetak Surat Jalan' }}
            </button>
            <button
              class="self-end rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
              :disabled="!canSubmitShipping"
              @click="processShipping"
            >
              {{ shippingSubmitting ? 'Memproses Shipping...' : 'Proses Shipping' }}
            </button>
          </div>
        </section>

    <section v-if="isRealisasiMode && !isCompletedInvoiceView" class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800/70">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Form Realisasi</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Form utama realisasi dipindahkan ke atas agar tidak tenggelam di bawah detail faktur.</p>
        </div>
        <button
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          :disabled="!canSubmitRealization"
          @click="processRealization"
        >
          {{ realizationSubmitting ? 'Memproses Realisasi...' : 'Proses Realisasi' }}
        </button>
      </div>

      <div class="mb-4 grid gap-3 md:grid-cols-2">
        <AppFormField
          v-model="realizationForm.namaUser"
          label="Nama Petugas / Driver"
          placeholder="Nama petugas realisasi"
        />
        <AppFormField
          v-model="realizationForm.pembayaranViaDropper"
          label="Pembayaran Via Dropper"
          type="number"
          placeholder="Opsional"
        />
      </div>

      <div v-if="!realizationForm.rows.length" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
        Data realisasi belum tersedia untuk faktur ini.
      </div>

      <div v-else class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th class="px-4 py-3">Produk</th>
              <th class="px-4 py-3">SKU</th>
              <th class="px-4 py-3">Picked</th>
              <th class="px-4 py-3">Realisasi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-for="item in realizationForm.rows" :key="item.row_key">
              <td class="px-4 py-3 font-semibold text-slate-900">{{ item.nama_produk || '-' }}</td>
              <td class="px-4 py-3 text-slate-600">{{ item.kode_sku || '-' }}</td>
              <td class="px-4 py-3 text-slate-600">{{ Number(item.jumlah_picked || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">
                <input
                  v-model.number="item.realisasi"
                  type="number"
                  min="0"
                  class="w-32 rounded-xl border border-slate-200 px-3 py-2 outline-none focus:border-brand-400"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section v-if="invoiceRows.length" class="grid gap-4 md:grid-cols-3">
      <article v-for="item in detailSummary" :key="item.label" class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-800/70">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900 dark:text-white">{{ item.value }}</p>
      </article>
    </section>

    <AppTable
      :rows="detailRows"
      :columns="[
        { key: 'kode_sku', label: 'SKU' },
        { key: 'nama_produk', label: 'Produk' },
        { key: 'qty_uom_label', label: 'Rincian UOM' },
        { key: 'qty_pcs_label', label: 'Total PCS' },
        { key: 'subtotal_label', label: 'Subtotal' }
      ]"
      :loading="loading"
      empty-message="Detail faktur belum tersedia untuk sales order ini."
    />
      </div>
    </AppModal>

  </div>
</template>
