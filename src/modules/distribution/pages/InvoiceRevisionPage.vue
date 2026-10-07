<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  getInvoiceDetail,
  getRevisionInvoices,
  getRevisionRoutes,
  submitInvoiceRevision
} from '@/api/distribution';
import { getBranches, getCompanies, getProducts, getProductUoms } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  sales_order_id: '',
  search: ''
});

const revisionCursors = ref([null]);
const revisionPagination = ref({ has_more: false, next_cursor: null });

const form = reactive({
  nama_fakturist: ''
});

const companies = ref([]);
const branches = ref([]);
const routeRows = ref([]);
const invoiceRows = ref([]);
const detailRows = ref([]);
const invoiceHeader = ref({});
const productRows = ref([]);
const selectedRoute = ref(null);
const selectedInvoice = ref(null);
const selectedProductId = ref('');
const loading = reactive({ branches: false, routes: false, invoices: false, detail: false, products: false, productUom: false, submit: false });
const feedback = ref('');
const errorMessage = ref('');
const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser(authStore));

const revisionSteps = [
  { number: '1', title: 'Pilih Perusahaan & Cabang', note: 'Halaman ini hanya mengambil order status Need Revision.' },
  { number: '2', title: 'Pilih Rute Revisi', note: 'Faktur kurang picked atau hasil realisasi yang perlu disesuaikan.' },
  { number: '3', title: 'Cek Faktur', note: 'Buka faktur dan audit nilai produk yang perlu disesuaikan.' },
  { number: '4', title: 'Submit Revisi', note: 'Revisi picking kembali ke checker; revisi pascapengiriman mengikuti realisasi.' }
];

const revisionUomDefinitions = [
  { level: 1, key: 'revisi_pieces' },
  { level: 2, key: 'revisi_box' },
  { level: 3, key: 'revisi_karton' }
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

const routeTableRows = computed(() =>
  routeRows.value.map((item) => ({
    ...item,
    row_key: routeKey(item),
    route_label: `${item.kode || item.kode_rute || '-'} - ${item.nama_rute || 'Rute'}`,
    armada_label: item.nama_armada || item.no_pelat || item.id_armada || '-',
    driver_label: item.nama_driver || item.nama || item.id_driver || '-',
    total_label: item.total_penjualan ? formatCurrency(item.total_penjualan) : '-'
  }))
);

const invoiceTableRows = computed(() =>
  invoiceRows.value.map((item) => ({
    ...item,
    row_key: String(item.no_faktur || item.id_sales_order || Math.random()),
    sales_order_label: Array.isArray(item.id_sales_order) ? item.id_sales_order.join(', ') : item.id_sales_order,
    customer_label: `${item.kode_customer || '-'} - ${item.nama_customer || '-'}`,
    total_label: item.total_bayar || item.total_penjualan ? formatCurrency(item.total_bayar || item.total_penjualan) : '-'
  }))
);

const selectedRouteKey = computed(() => selectedRoute.value ? routeKey(selectedRoute.value) : '');
const selectedInvoiceKey = computed(() => selectedInvoice.value ? String(selectedInvoice.value.no_faktur || selectedInvoice.value.id_sales_order || '') : '');
const selectedInvoiceSalesOrderLabel = computed(() =>
  selectedInvoice.value ? getInvoiceSalesOrderIds(selectedInvoice.value).join(', ') : ''
);

const totals = computed(() => {
  const activeRows = detailRows.value.filter((item) => !item._deleted);
  const subtotal = activeRows.reduce((acc, item) => acc + Number(item.revisi_subtotal || 0), 0);
  const diskon = activeRows.reduce((acc, item) => acc + Number(item.revisi_diskon || 0), 0);
  const pajak = activeRows.reduce((acc, item) => acc + Number(item.revisi_ppn || 0), 0);
  return {
    subtotal,
    diskon,
    pajak,
    total: subtotal - diskon + pajak
  };
});

const canSubmit = computed(() =>
  !!selectedInvoice.value &&
  detailRows.value.some((item) => !item._deleted) &&
  !loading.submit
);

const productOptions = computed(() =>
  productRows.value.map((item) => ({
    ...item,
    value: String(item.id_produk || item.id || item.produk_id),
    label: `${item.kode_sku || item.kode || '-'} - ${item.nama || item.nama_produk || 'Produk'} | ${rowPpnLabel(item)}`
  }))
);

function routeKey(item) {
  return `${item.id_rute || ''}-${item.id_armada || ''}-${item.id_driver || ''}-${item.delivering_date || ''}`;
}

function formatCurrency(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function normalizeNumber(value) {
  return Number(value || 0);
}

function hasText(value) {
  return String(value ?? '').trim() !== '';
}

function rowConversion(row, level) {
  if (level === 1) return Number(row.konversi_level1 || row.konversi1 || 1) || 1;
  if (level === 2) return Number(row.konversi_level2 || row.konversi2 || 0) || 0;
  return Number(row.konversi_level3 || row.konversi3 || 0) || 0;
}

function rowUomCode(row, level) {
  return String(
    row?.[`puom${level}_kode`] ??
    row?.[`uom${level}_kode`] ??
    row?.[`uom_${level}_kode`] ??
    ''
  ).trim();
}

function rowUomName(row, level) {
  return String(
    row?.[`puom${level}_nama`] ??
    row?.[`uom${level}_nama`] ??
    row?.[`uom_${level}_nama`] ??
    row?.[`uom_${level}`] ??
    row?.[`uom${level}`] ??
    ''
  ).trim();
}

function rowUomLabel(row, level) {
  const code = rowUomCode(row, level);
  const name = rowUomName(row, level);
  if (code && name && code.toLowerCase() !== name.toLowerCase()) {
    return `${code} · ${name}`;
  }
  return code || name || `UOM ${level}`;
}

function isRevisionUomEnabled(row, level) {
  return hasText(rowUomCode(row, level) || rowUomName(row, level)) && rowConversion(row, level) > 0;
}

function revisionUomFields(row) {
  return revisionUomDefinitions
    .filter((field) => isRevisionUomEnabled(row, field.level))
    .map((field) => ({
      ...field,
      label: rowUomLabel(row, field.level)
    }));
}

function rowTotalPieces(row) {
  return (
    Number(row.revisi_pieces || 0) * rowConversion(row, 1) +
    Number(row.revisi_box || 0) * rowConversion(row, 2) +
    Number(row.revisi_karton || 0) * rowConversion(row, 3)
  );
}

function rowBaseUomLabel(row) {
  return rowUomLabel(row, 1);
}

function rowPpnRate(row = {}) {
  return normalizeNumber(row.ppn_rate ?? row.ppn_persentase ?? row.ppn);
}

function rowPpnLabel(row = {}) {
  const name = row.ppn_nama || row.status_ppn || row.ppn_kode;
  const rate = rowPpnRate(row);
  return name ? `${name} (${rate}%)` : `${rate}%`;
}

function calculateRowPpn(row = {}) {
  const taxableBase = Math.max(normalizeNumber(row.revisi_subtotal) - normalizeNumber(row.revisi_diskon), 0);
  return taxableBase * rowPpnRate(row) / 100;
}

function recalculateRow(row) {
  const subtotal = rowTotalPieces(row) * Number(row.revisi_harga || 0);
  row.revisi_subtotal = subtotal < 0 ? 0 : subtotal;
  row.revisi_diskon = Math.min(Number(row.revisi_diskon || 0), row.revisi_subtotal);
  row.revisi_ppn = calculateRowPpn(row);
}

function parseIds(value) {
  if (Array.isArray(value)) {
    return value.map((item) => Number(item)).filter((item) => Number.isFinite(item));
  }

  return String(value || '')
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isFinite(item));
}

function firstSalesOrderId(value) {
  if (Array.isArray(value)) return value[0];
  return String(value || '').split(',')[0].trim();
}

function getInvoiceSalesOrderIds(row) {
  return parseIds(row?.id_sales_order || row?.id_sales_orders || row?.sales_order_id);
}

function resolveInvoiceDetailRequest(row) {
  const ids = getInvoiceSalesOrderIds(row);
  const params = { revision_context: 1, include_batch_invoice: 1, id_faktur: row?.id_faktur || undefined };

  if (row?.id_order_batch && ids.length) {
    params.id_order_batch = row.id_order_batch;
    params.id_sales_orders = ids.join(',');
  }

  return {
    id: ids[0] || firstSalesOrderId(row?.id_sales_order),
    params
  };
}

function extractInvoiceDetail(payload) {
  const body = payload?.result && !Array.isArray(payload.result) ? payload.result : payload;

  return {
    header: body?.detail_faktur || body?.header || body?.faktur || {},
    rows: normalizeList(body?.list_detail_order || body?.detail || body?.data || body?.result || [])
  };
}

function normalizeDetailRow(item) {
  const qtyPieces =
    normalizeNumber(item.pieces_delivered ?? item.pieces_order);
  const qtyBox =
    normalizeNumber(item.box_delivered ?? item.box_order);
  const qtyKarton =
    normalizeNumber(item.karton_delivered ?? item.karton_order);
  const subtotalAfterDiscount = normalizeNumber(item.subtotalorder ?? item.subtotal ?? item.total_harga);
  const diskon = normalizeNumber(
    item.total_nilai_discount ??
    item.total_diskon ??
    item.diskon_total ??
    item.total_diskon_produk
  );
  const subtotal = subtotalAfterDiscount + diskon;
  const ppnRate = normalizeNumber(item.ppn_rate ?? item.ppn_persentase ?? item.ppn);
  const totalPieces =
    qtyPieces * (Number(item.konversi_level1 || 1) || 1) +
    qtyBox * (Number(item.konversi_level2 || 0) || 0) +
    qtyKarton * (Number(item.konversi_level3 || 0) || 0);
  const harga = normalizeNumber(item.hargaorder ?? item.harga_order ?? item.harga_jual ?? (
    totalPieces > 0 ? (subtotal + diskon) / totalPieces : 0
  ));

  return {
    ...item,
    row_key: String(item.id_order_detail || item.id_detail_sales || item.id_produk || Math.random()),
    revisi_pieces: qtyPieces,
    revisi_box: qtyBox,
    revisi_karton: qtyKarton,
    revisi_harga: harga,
    revisi_subtotal: subtotal,
    revisi_diskon: diskon,
    revisi_ppn: Math.max(subtotal - diskon, 0) * ppnRate / 100,
    ppn_rate: ppnRate,
    _action: 'update',
    _deleted: false
  };
}

function updateNumber(row, key, value) {
  if (key === 'revisi_ppn') return;
  const numberValue = Number(value || 0);
  row[key] = numberValue < 0 ? 0 : numberValue;
  if (['revisi_pieces', 'revisi_box', 'revisi_karton', 'revisi_harga', 'revisi_diskon'].includes(key)) {
    recalculateRow(row);
  }
}

function toggleDeleteRow(row) {
  row._deleted = !row._deleted;
  row._action = row._deleted ? 'delete' : (row.id_order_detail ? 'update' : 'add');
}

async function loadProducts() {
  loading.products = true;
  try {
    const response = await getProducts({
      id_principal: invoiceHeader.value?.id_principal || selectedInvoice.value?.id_principal || undefined,
      limit: 100
    });
    productRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    productRows.value = [];
    errorMessage.value = normalizeError(error, 'Daftar produk untuk revisi belum bisa dimuat.');
  } finally {
    loading.products = false;
  }
}

function getProductUomFields(uoms) {
  const uomsByLevel = new Map();

  normalizeList(uoms).forEach((item) => {
    const level = Number(item?.level ?? item?.uom_level ?? 0);
    if (![1, 2, 3].includes(level) || uomsByLevel.has(level)) return;

    uomsByLevel.set(level, item);
  });

  return revisionUomDefinitions.reduce((fields, definition) => {
    const uom = uomsByLevel.get(definition.level);
    if (!uom) return fields;

    fields[`puom${definition.level}_kode`] = String(uom.kode ?? uom.uom_kode ?? '').trim();
    fields[`puom${definition.level}_nama`] = String(uom.nama ?? uom.uom_nama ?? '').trim();
    fields[`konversi_level${definition.level}`] = Number(
      uom.faktor_konversi ?? uom.uom_faktor_konversi ?? (definition.level === 1 ? 1 : 0)
    ) || (definition.level === 1 ? 1 : 0);
    return fields;
  }, {});
}

async function addProductRow() {
  const product = productOptions.value.find((item) => String(item.value) === String(selectedProductId.value));
  if (!product) {
    errorMessage.value = 'Pilih produk yang akan ditambahkan.';
    return;
  }

  const idProduk = product.id_produk || product.id || product.produk_id;
  if (detailRows.value.some((item) => !item._deleted && String(item.id_produk) === String(idProduk))) {
    errorMessage.value = 'Produk tersebut sudah ada di detail revisi.';
    return;
  }

  loading.productUom = true;
  try {
    const response = await getProductUoms(idProduk);
    const uomFields = getProductUomFields(unwrapResponse(response));
    if (!revisionUomDefinitions.some((field) => isRevisionUomEnabled(uomFields, field.level))) {
      errorMessage.value = 'Produk belum memiliki UOM aktif. Lengkapi setting UOM di master produk terlebih dahulu.';
      return;
    }

    const row = {
      row_key: `new-${Date.now()}-${idProduk}`,
      id_order_detail: null,
      id_sales_order: firstSalesOrderId(selectedInvoice.value?.id_sales_order),
      id_produk: idProduk,
      kode_sku: product.kode_sku || product.kode || '-',
      nama_produk: product.nama || product.nama_produk || 'Produk',
      ppn: normalizeNumber(product.ppn),
      ppn_rate: normalizeNumber(product.ppn),
      id_ppn: product.id_ppn || null,
      ppn_nama: product.ppn_nama || '',
      ppn_kode: product.ppn_kode || '',
      revisi_pieces: 0,
      revisi_box: 0,
      revisi_karton: 0,
      revisi_harga: normalizeNumber(product.hargaorder || product.harga_jual || product.harga || product.price),
      revisi_subtotal: 0,
      revisi_diskon: 0,
      revisi_ppn: 0,
      _action: 'add',
      _deleted: false,
      ...uomFields
    };

    detailRows.value.push(row);
    selectedProductId.value = '';
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Konfigurasi UOM produk belum bisa dimuat.');
  } finally {
    loading.productUom = false;
  }
}

function clearRevisionContext() {
  selectedRoute.value = null;
  selectedInvoice.value = null;
  routeRows.value = [];
  invoiceRows.value = [];
  detailRows.value = [];
  invoiceHeader.value = {};
}

async function loadBranches() {
  loading.branches = true;
  try {
    const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    if (!filters.id_cabang && !isSuperUser(authStore) && fallbackBranchId.value) {
      filters.id_cabang = String(fallbackBranchId.value);
    }
    filters.id_perusahaan = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    syncBranchFromCompany();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Referensi cabang belum bisa dimuat.');
  } finally {
    loading.branches = false;
  }
}

function syncBranchFromCompany() {
  if (!filters.id_perusahaan || !filters.id_cabang) {
    return;
  }

  if (!companyIdsForBranch(filters.id_cabang).includes(String(filters.id_perusahaan))) {
    filters.id_cabang = '';
  }
}

function revisionRouteDeliveryTime(value) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function sortRevisionRoutes(rows) {
  return [...rows].sort((left, right) => {
    const byDeliveryDate = revisionRouteDeliveryTime(right?.delivering_date) - revisionRouteDeliveryTime(left?.delivering_date);
    if (byDeliveryDate) return byDeliveryDate;
    return routeKey(left).localeCompare(routeKey(right));
  });
}

async function loadRoutes(keepPage = false) {
  if (keepPage !== true) revisionCursors.value = [null];
  if (!filters.id_cabang) {
    errorMessage.value = 'Pilih cabang terlebih dahulu.';
    return;
  }

  loading.routes = true;
  feedback.value = '';
  errorMessage.value = '';
  selectedRoute.value = null;
  selectedInvoice.value = null;
  routeRows.value = [];
  invoiceRows.value = [];
  detailRows.value = [];
  invoiceHeader.value = {};

  try {
    const response = await getRevisionRoutes({
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan || undefined,
      search: filters.search || undefined,
      cursor: revisionCursors.value.at(-1) || undefined,
      limit: 50,
      sales_order_id: filters.sales_order_id || undefined
    });
    const payload = unwrapResponse(response);
    revisionPagination.value = payload?.pagination || { has_more: false, next_cursor: null };
    routeRows.value = sortRevisionRoutes(normalizeList(payload?.routes || payload));
    if (!routeRows.value.length) {
      feedback.value = 'Belum ada faktur yang perlu revisi pada cabang ini.';
    } else if (filters.sales_order_id) {
      await autoSelectRouteBySalesOrder();
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Rute revisi faktur belum bisa dimuat.');
  } finally {
    loading.routes = false;
  }
}

async function nextRevisionPage() {
  if (!revisionPagination.value.has_more || loading.routes) return;
  revisionCursors.value.push(revisionPagination.value.next_cursor);
  await loadRoutes(true);
}

async function previousRevisionPage() {
  if (revisionCursors.value.length <= 1 || loading.routes) return;
  revisionCursors.value.pop();
  await loadRoutes(true);
}

async function selectRoute(row) {
  selectedRoute.value = row;
  selectedInvoice.value = null;
  invoiceRows.value = [];
  detailRows.value = [];
  invoiceHeader.value = {};
  loading.invoices = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getRevisionInvoices({
      id_cabang: filters.id_cabang,
      id_perusahaan: filters.id_perusahaan || undefined,
      invoice_ids: row.id_faktur || undefined,
      id_rute: row.id_rute,
      id_armada: row.id_armada,
      id_driver: row.id_driver,
      delivering_date: row.delivering_date
    });
    const payload = unwrapResponse(response);
    invoiceRows.value = normalizeList(payload?.list_faktur_shipping || payload?.list_faktur || payload?.data || payload);
    if (!invoiceRows.value.length) {
      feedback.value = 'Belum ada faktur revisi pada rute ini.';
    } else if (filters.sales_order_id) {
      await autoSelectInvoiceBySalesOrder();
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Faktur revisi belum bisa dimuat.');
  } finally {
    loading.invoices = false;
  }
}

async function selectInvoice(row) {
  selectedInvoice.value = row;
  detailRows.value = [];
  invoiceHeader.value = {};
  loading.detail = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const { id, params } = resolveInvoiceDetailRequest(row);
    if (!id) {
      errorMessage.value = 'ID sales order pada faktur ini tidak terbaca.';
      return;
    }

    const response = await getInvoiceDetail(id, params);
    const payload = unwrapResponse(response) || {};
    const detail = extractInvoiceDetail(payload);
    invoiceHeader.value = detail.header;
    detailRows.value = detail.rows.map(normalizeDetailRow);
    if (invoiceHeader.value.picking_revision) {
      for (const item of detailRows.value) {
        if (item.picking_actual_pcs == null) continue;
        let remaining = Number(item.picking_actual_pcs);
        item.revisi_pieces = 0; item.revisi_box = 0; item.revisi_karton = 0;
        for (const field of [...revisionUomFields(item)].reverse()) {
          const factor = rowConversion(item, field.level);
          item[field.key] = Math.floor(remaining / factor);
          remaining -= item[field.key] * factor;
        }
        recalculateRow(item);
      }
    } else {
      await loadProducts();
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail faktur revisi belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function autoSelectInvoiceBySalesOrder() {
  const targetId = String(filters.sales_order_id || '');
  const matched = invoiceRows.value.find((item) => parseIds(item.id_sales_order).map(String).includes(targetId));
  if (!matched) return false;
  await selectInvoice(matched);
  return true;
}

async function autoSelectRouteBySalesOrder() {
  for (const row of routeRows.value) {
    await selectRoute(row);
    const matched = await autoSelectInvoiceBySalesOrder();
    if (matched) return true;
  }
  return false;
}

function buildPayload() {
  const detailProduk = detailRows.value.map((item) => ({
    action: item._deleted ? 'delete' : item._action || (item.id_order_detail ? 'update' : 'add'),
    id_order_detail: item.id_order_detail || null,
    id_sales_order: item.id_sales_order || firstSalesOrderId(selectedInvoice.value?.id_sales_order),
    id_produk: item.id_produk,
    pieces_order: normalizeNumber(item.revisi_pieces),
    box_order: normalizeNumber(item.revisi_box),
    karton_order: normalizeNumber(item.revisi_karton),
    hargaorder: normalizeNumber(item.revisi_harga),
    subtotal: normalizeNumber(item.revisi_subtotal),
    total_diskon: normalizeNumber(item.revisi_diskon),
    ppn: calculateRowPpn(item),
    ppn_rate: rowPpnRate(item),
    id_ppn: item.id_ppn || null
  }));

  return {
    nama_fakturist: form.nama_fakturist,
    faktur_ids: parseIds(selectedInvoice.value.id_sales_order),
    faktur_data: [
      {
        id_sales_order: selectedInvoice.value.id_sales_order,
        detail_faktur: detailRows.value,
        faktur_info: {
          ...(selectedInvoice.value || {}),
          ...(invoiceHeader.value || {})
        },
        rincian_pembayaran: {
          subtotal: totals.value.subtotal,
          diskon_nota: totals.value.diskon,
          pajak: totals.value.pajak,
          total_penjualan: totals.value.total
        },
        detail_produk: detailProduk
      }
    ]
  };
}

async function submitRevision() {
  if (!canSubmit.value) {
    errorMessage.value = 'Pilih faktur dan pastikan detail produk sudah tampil.';
    return;
  }

  loading.submit = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    if (invoiceHeader.value.picking_revision && detailRows.value.some(row => row._deleted || row.picking_actual_pcs == null || rowTotalPieces(row) < Number(row.picking_actual_pcs))) {
      throw new Error('Qty revisi tidak boleh kurang dari jumlah fisik picked; jangan hapus baris.');
    }
    const response = await submitInvoiceRevision(buildPayload());
    const payload = unwrapResponse(response) || response?.data || {};
    const successMessage = payload.message || 'Revisi faktur berhasil diproses.';
    const routeToReload = selectedRoute.value;
    await loadRoutes();
    if (routeToReload) {
      const matchedRoute = routeRows.value.find((item) => routeKey(item) === routeKey(routeToReload));
      if (matchedRoute) await selectRoute(matchedRoute);
    }
    feedback.value = successMessage;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Revisi faktur belum berhasil diproses.');
  } finally {
    loading.submit = false;
  }
}

onMounted(async () => {
  filters.id_cabang = String(route.query.id_cabang || (!isSuperUser(authStore) ? fallbackBranchId.value : '') || '');
  filters.sales_order_id = String(route.query.sales_order_id || '');
  filters.id_perusahaan = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  form.nama_fakturist = String(authStore.user?.nama || authStore.user?.name || authStore.user?.nama_user || '');
  await loadBranches();
  await loadRoutes();
});

watch(
  () => filters.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    syncBranchFromCompany();
    clearRevisionContext();
  }
);

watch(
  () => filters.id_cabang,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;
    clearRevisionContext();
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Revisi Faktur"
      description="Halaman khusus untuk order status Need Revision. Operator cukup fokus pada faktur yang realisasinya berbeda dan perlu penyesuaian nilai."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'distribution-invoices', query: { stage: 'realisasi', id_cabang: filters.id_cabang } })">
          Buka Realisasi
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="router.push({ name: 'sales-order-list' })">
          Kembali ke Order Sales
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="step in revisionSteps" :key="step.number" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex items-start gap-3">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-600 text-sm font-bold text-white">{{ step.number }}</span>
          <div>
            <h3 class="text-sm font-semibold text-slate-900">{{ step.title }}</h3>
            <p class="mt-1 text-xs leading-5 text-slate-500">{{ step.note }}</p>
          </div>
        </div>
      </article>
    </section>

    <section class="panel p-5">
      <p v-if="invoiceHeader.picking_revision" class="mb-4 rounded-xl bg-amber-50 p-4 font-semibold text-amber-800">Revisi kekurangan picking: qty disiapkan sesuai fisik picked. Periksa harga dan diskon. Qty di atas picked akan menunggu picking stok susulan. Nota seluruhnya 0 PCS tetap ditahan; tidak otomatis dibatalkan atau dianggap terkirim.</p>
      <div class="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
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
        <button class="self-end rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50" :disabled="loading.routes" @click="loadRoutes">
          Muat Revisi
        </button>
        <button class="self-end rounded-xl bg-amber-600 px-4 py-3 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-60" :disabled="!canSubmit" @click="submitRevision">
          {{ loading.submit ? 'Memproses...' : 'Submit Revisi Faktur' }}
        </button>
      </div>
      <label class="mt-4 block text-sm text-slate-600">
        Cari nomor faktur, nomor order, kode atau nama customer
        <input v-model="filters.search" class="mt-1 w-full rounded-xl border border-slate-200 px-4 py-3" placeholder="Cari di seluruh faktur revisi" @keyup.enter="loadRoutes()" />
      </label>
      <p v-if="filters.sales_order_id" class="mt-2 text-sm text-amber-700">
        Difilter dari order #{{ filters.sales_order_id }}.
        <button class="underline" @click="filters.sales_order_id = ''; loadRoutes()">Tampilkan semua revisi</button>
      </p>
      <div class="mt-3 flex items-center justify-between gap-3 text-sm">
        <span>Halaman {{ revisionCursors.length }} · maksimal 50 faktur, dikelompokkan menurut rute</span>
        <div class="flex gap-3">
          <button :disabled="loading.routes || revisionCursors.length <= 1" class="disabled:opacity-40" @click="previousRevisionPage">Sebelumnya</button>
          <button :disabled="loading.routes || !revisionPagination.has_more" class="disabled:opacity-40" @click="nextRevisionPage">Berikutnya</button>
        </div>
      </div>
    </section>

    <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</div>

    <section class="grid gap-6 xl:grid-cols-2">
      <article>
        <div class="mb-3">
          <h3 class="text-lg font-semibold text-slate-900">Rute Revisi</h3>
          <p class="mt-1 text-sm text-slate-500">Rute ini berisi faktur dengan status order 5.</p>
        </div>
        <AppTable
          :rows="routeTableRows"
          :columns="[
            { key: 'route_label', label: 'Rute' },
            { key: 'armada_label', label: 'Armada' },
            { key: 'driver_label', label: 'Driver' },
            { key: 'delivering_date', label: 'Tanggal Kirim' },
            { key: 'total_label', label: 'Total' }
          ]"
          :loading="loading.routes"
          :clickable-rows="true"
          row-key="row_key"
          :selected-key="selectedRouteKey"
          empty-message="Belum ada rute revisi."
          @row-click="selectRoute"
        />
      </article>

      <article>
        <div class="mb-3">
          <h3 class="text-lg font-semibold text-slate-900">Faktur Perlu Revisi</h3>
          <p class="mt-1 text-sm text-slate-500">Klik faktur untuk membuka rincian penyesuaian.</p>
        </div>
        <AppTable
          :rows="invoiceTableRows"
          :columns="[
            { key: 'no_faktur', label: 'No Faktur' },
            { key: 'sales_order_label', label: 'Sales Order' },
            { key: 'customer_label', label: 'Customer' },
            { key: 'total_label', label: 'Total' }
          ]"
          :loading="loading.invoices"
          :clickable-rows="true"
          row-key="row_key"
          :selected-key="selectedInvoiceKey"
          empty-message="Pilih rute untuk memuat faktur revisi."
          @row-click="selectInvoice"
        />
      </article>
    </section>

    <section class="panel p-5">
      <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Detail Revisi</h3>
          <p class="mt-1 text-sm text-slate-500">Jumlah produk, harga, diskon harga, tambah produk, dan hapus produk bisa disesuaikan sebelum submit revisi faktur. PPN mengikuti Status PPN produk.</p>
        </div>
        <div class="grid gap-2 text-sm text-slate-600 sm:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Subtotal</p>
            <p class="mt-1 font-semibold text-slate-900">{{ formatCurrency(totals.subtotal) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Diskon</p>
            <p class="mt-1 font-semibold text-slate-900">{{ formatCurrency(totals.diskon) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">PPN</p>
            <p class="mt-1 font-semibold text-slate-900">{{ formatCurrency(totals.pajak) }}</p>
          </div>
          <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-amber-700">Total Baru</p>
            <p class="mt-1 font-semibold text-amber-950">{{ formatCurrency(totals.total) }}</p>
          </div>
        </div>
      </div>

      <label class="mb-4 block max-w-md">
        <span class="mb-1.5 block text-sm font-medium text-slate-700">Nama Fakturist</span>
        <input v-model="form.nama_fakturist" type="text" class="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-900 outline-none focus:border-brand-400">
      </label>

      <section v-if="selectedInvoice && !invoiceHeader.picking_revision" class="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4">
        <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <AppSearchSelect
            v-model="selectedProductId"
            label="Tambah Produk"
            placeholder="Cari produk"
            :options="productOptions"
            :loading="loading.products"
            empty-text="Produk belum tersedia."
          />
          <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="!selectedProductId || loading.productUom" @click="addProductRow">
            {{ loading.productUom ? 'Memuat UOM...' : 'Tambah Produk' }}
          </button>
        </div>
      </section>

      <div v-if="loading.detail" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        Memuat detail faktur revisi...
      </div>

      <div v-else-if="!selectedInvoice" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        Pilih faktur revisi untuk menampilkan detail produk.
      </div>

      <div v-else-if="!detailRows.length" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-8 text-center text-sm text-amber-800">
        Detail produk faktur {{ selectedInvoice.no_faktur || '-' }} belum ditemukan dari API.
        <span class="mt-1 block text-xs text-amber-700">Sales Order: {{ selectedInvoiceSalesOrderLabel || '-' }}</span>
      </div>

      <div v-else class="overflow-x-auto rounded-2xl border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th class="px-4 py-3">Produk</th>
              <th class="px-4 py-3">Qty Revisi</th>
              <th class="px-4 py-3">Harga</th>
              <th class="px-4 py-3">Diskon Harga</th>
              <th class="px-4 py-3">PPN</th>
              <th class="px-4 py-3">Subtotal</th>
              <th class="px-4 py-3">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-for="row in detailRows" :key="row.row_key" :class="row._deleted ? 'bg-rose-50 text-slate-400 line-through' : ''">
              <td class="px-4 py-3 align-top">
                <p class="font-semibold text-slate-900">{{ row.nama_produk || '-' }}</p>
                <p class="mt-1 text-xs text-slate-500">{{ row.kode_sku || '-' }}</p>
                <p v-if="row.picking_actual_pcs != null" class="mt-1 text-xs font-bold text-amber-700">{{ row.shipment_reference }} · Picked {{ row.picking_actual_pcs }} PCS</p>
                <p v-if="row._action === 'add'" class="mt-1 text-xs font-semibold text-brand-700">Produk baru</p>
              </td>
              <td class="px-4 py-3 align-top">
                <div v-if="revisionUomFields(row).length" class="flex min-w-[260px] flex-wrap gap-2">
                  <label v-for="field in revisionUomFields(row)" :key="field.key" class="text-xs text-slate-500">
                    {{ field.label }}
                    <input :value="row[field.key]" type="number" min="0" class="mt-1 w-24 rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand-400" :disabled="row._deleted" @input="updateNumber(row, field.key, $event.target.value)">
                  </label>
                </div>
                <p v-else class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">UOM belum dikonfigurasi pada master produk.</p>
                <p class="mt-2 text-xs text-slate-500">{{ Number(rowTotalPieces(row)).toLocaleString('id-ID') }} {{ rowBaseUomLabel(row) }} terkalkulasi</p>
              </td>
              <td class="px-4 py-3 align-top">
                <input :value="row.revisi_harga" type="number" min="0" class="w-36 rounded-xl border border-slate-200 px-3 py-2 outline-none focus:border-brand-400" :disabled="row._deleted" @input="updateNumber(row, 'revisi_harga', $event.target.value)">
              </td>
              <td class="px-4 py-3 align-top">
                <input :value="row.revisi_diskon" type="number" min="0" class="w-36 rounded-xl border border-slate-200 px-3 py-2 outline-none focus:border-brand-400" :disabled="row._deleted" @input="updateNumber(row, 'revisi_diskon', $event.target.value)">
              </td>
              <td class="px-4 py-3 align-top">
                <p class="w-40 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 font-semibold text-slate-800">
                  {{ formatCurrency(row._deleted ? 0 : row.revisi_ppn) }}
                </p>
                <p class="mt-1 text-xs text-slate-500">{{ rowPpnLabel(row) }}</p>
              </td>
              <td class="px-4 py-3 align-top font-semibold text-slate-900">
                {{ formatCurrency(row._deleted ? 0 : row.revisi_subtotal - row.revisi_diskon + row.revisi_ppn) }}
              </td>
              <td class="px-4 py-3 align-top">
                <button v-if="!invoiceHeader.picking_revision" type="button" class="rounded-xl border border-rose-200 px-3 py-2 text-xs font-medium text-rose-700 hover:bg-rose-50" @click="toggleDeleteRow(row)">
                  {{ row._deleted ? 'Batal Hapus' : 'Hapus' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>
