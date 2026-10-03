<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { checkSalesRetur, createSalesRetur, searchSalesInvoices } from '@/api/salesOrder';
import { getInvoiceDetail } from '@/api/distribution';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const route = useRoute();
const router = useRouter();
const SALES_FILTER_STORAGE_KEY = 'budimas.salesOrder.selectedSalesUserId';

const form = reactive({
  idSalesOrder: '',
  idSales: '',
  idPlafon: '',
  noOrder: '',
  noFaktur: '',
  customerName: '',
  tanggalRetur: toLocalDateInputValue()
});
const searchForm = reactive({
  invoiceNo: '',
  selectedInvoice: ''
});

const invoiceHeader = ref({});
const sourceRows = ref([]);
const returRows = ref([]);
const existingReturRows = ref([]);
const searchRows = ref([]);
const loading = ref(false);
const checking = ref(false);
const submitting = ref(false);
const searchLoading = ref(false);
const feedback = ref('');
const errorMessage = ref('');

const RETUR_STATUS_LABELS = {
  0: 'menunggu approval SPV',
  1: 'KPR sudah dicetak',
  2: 'sedang proses gudang',
  4: 'QC gudang selesai — menunggu Credit Note',
  3: 'sudah dibuat Credit Note',
  9: 'batal'
};

const hasActiveRetur = computed(() =>
  existingReturRows.value.some((item) => {
    const status = String(item?.status_request ?? item?.status_request_retur ?? '0').trim();
    return ['', '0', '1', '2', '4'].includes(status);
  })
);

const canSubmit = computed(() =>
  form.idSalesOrder &&
  form.idSales &&
  form.idPlafon &&
  !hasActiveRetur.value &&
  returRows.value.some((item) => Number(item.total_retur || 0) > 0)
);

const returSummary = computed(() => {
  const totalLines = returRows.value.filter((item) => Number(item.total_retur || 0) > 0).length;
  const totalQty = returRows.value.reduce((total, item) => total + Number(item.total_retur || 0), 0);
  const totalGood = returRows.value.reduce((total, item) => total + Number(item.good_total || 0), 0);
  const totalBad = returRows.value.reduce((total, item) => total + Number(item.bad_total || 0), 0);

  return [
    { label: 'Baris Retur', value: totalLines.toLocaleString('id-ID') },
    { label: 'Total Qty Retur', value: totalQty.toLocaleString('id-ID') },
    { label: 'Good', value: totalGood.toLocaleString('id-ID') },
    { label: 'Bad', value: totalBad.toLocaleString('id-ID') }
  ];
});

const existingReturTableRows = computed(() =>
  existingReturRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_request_detail || item.id_request || index}`,
    qty_label: formatReturHistoryQty(item)
  }))
);

const invoiceOptions = computed(() =>
  searchRows.value.map((item) => ({
    value: String(item.id_sales_order),
    label: `${formatInvoiceSearchLabel(item)} | ${item.no_order || '-'} | ${item.nama_customer || '-'}`
  }))
);

function getStoredSalesUserId() {
  return window.localStorage.getItem(SALES_FILTER_STORAGE_KEY) || '';
}

function salesQuery() {
  const salesUserId = String(route.query.sales_user_id || form.idSales || getStoredSalesUserId() || '').trim();
  return salesUserId ? { sales_user_id: salesUserId } : {};
}

function toNumber(value) {
  return Number(value || 0);
}

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(toNumber(value));
}

function hasText(value) {
  return String(value ?? '').trim() !== '';
}

function formatInvoiceSearchLabel(item) {
  return item?.no_faktur || item?.nomor_faktur || item?.kode_request || item?.no_cn || '-';
}

function normalizeSearchCode(value) {
  return String(value ?? '').trim().toLowerCase();
}

function hasReturRecord(item) {
  return Boolean(
    item?.id_retur_request ||
    item?.kode_request ||
    item?.kode_kpr ||
    item?.no_cn ||
    item?.status_request_retur !== undefined && item?.status_request_retur !== null
  );
}

function isReturReferenceMatch(item, keyword) {
  const normalizedKeyword = normalizeSearchCode(keyword);
  if (!normalizedKeyword) return false;

  return [item?.kode_request, item?.kode_kpr, item?.no_cn]
    .map(normalizeSearchCode)
    .some((value) => value && value === normalizedKeyword);
}

function formatReturStatus(value) {
  const statusKey = String(value ?? '');
  return RETUR_STATUS_LABELS[statusKey] || (statusKey ? `status ${statusKey}` : 'status belum diketahui');
}

function buildAlreadyReturMessage(item, keyword) {
  const requestCode = item?.kode_request || item?.kode_kpr || item?.no_cn || keyword || '-';
  const orderCode = item?.no_faktur || item?.no_order || item?.nomor_faktur || '-';
  const statusLabel = formatReturStatus(item?.status_request_retur);
  return `Nomor ${requestCode} sudah dilakukan retur untuk ${orderCode} (${statusLabel}). Lanjutkan prosesnya dari menu Monitoring Retur.`;
}

function getReturUomName(item, level) {
  return (
    item?.[`puom${level}_nama`] ||
    item?.[`puom${level}_kode`] ||
    item?.[`uom_${level}`] ||
    item?.[`uom${level}`] ||
    ''
  );
}

function getReturUomConversion(item, level) {
  const rawValue = item?.[`konversi_level${level}`] ?? item?.[`konversi_${level}`];
  if (level === 1 && (rawValue === undefined || rawValue === null || rawValue === '')) {
    return 1;
  }

  return toNumber(rawValue);
}

function isReturUomEnabled(item, level) {
  return hasText(getReturUomName(item, level)) && getReturUomConversion(item, level) > 0;
}

function formatReturUomLabel(item, level) {
  const name = getReturUomName(item, level) || `UOM ${level} belum diset`;
  if (level === 1) return name;
  return `${name} x ${Number(getReturUomConversion(item, level) || 0).toLocaleString('id-ID')}`;
}

function getReturFieldLevel(field) {
  if (field.includes('pieces')) return 1;
  if (field.includes('box')) return 2;
  if (field.includes('karton')) return 3;
  return 0;
}

function formatReturQtyLimit(item) {
  const limits = [
    { level: 1, value: item.max_pieces },
    { level: 2, value: item.max_box },
    { level: 3, value: item.max_karton }
  ]
    .filter(({ level }) => isReturUomEnabled(item, level))
    .map(({ level, value }) => `${Number(value || 0).toLocaleString('id-ID')} ${getReturUomName(item, level)}`);

  return limits.length ? limits.join(' | ') : 'UOM produk belum lengkap';
}

function hasReturUomValue(value) {
  return value !== undefined && value !== null && String(value).trim() !== '';
}

function historyReturUomContext(item) {
  const sourceRow = sourceRows.value.find((row) => String(row?.id_produk ?? '') === String(item?.id_produk ?? '')) || {};
  const context = { ...sourceRow, ...item };

  [1, 2, 3].forEach((level) => {
    [
      `puom${level}_nama`,
      `puom${level}_kode`,
      `uom_${level}`,
      `uom${level}`,
      `konversi_level${level}`,
      `konversi_${level}`
    ].forEach((key) => {
      if (!hasReturUomValue(context[key]) && hasReturUomValue(sourceRow[key])) {
        context[key] = sourceRow[key];
      }
    });
  });

  return context;
}

function historyReturQtyValue(item, unitKey) {
  const stored = toNumber(item?.[`${unitKey}_retur`]);
  const splitRequest = toNumber(item?.[`${unitKey}_diajukan`]) + toNumber(item?.[`${unitKey}_good_diajukan`]);

  // Retur lama ada yang hanya menyimpan split GOOD/BAD, sementara retur baru
  // menyimpan total pada *_retur. Ambil nilai yang paling lengkap agar angka
  // riwayat tidak tampak lebih kecil dari qty yang benar-benar diajukan.
  return Math.max(stored, splitRequest);
}

function historyReturTotalPieces(item, uomItem) {
  // API terbaru memberikan total fisik yang dihitung dari UOM master. Tetap
  // pertahankan fallback lokal agar riwayat lama atau API yang belum diperbarui
  // tidak kembali menampilkan angka raw per kolom sebagai total PCS.
  if (hasReturUomValue(item?.qty_retur_pcs)) {
    return Math.max(0, Math.floor(toNumber(item.qty_retur_pcs)));
  }

  return Math.max(0, Math.floor(qtyTotalPieces({
    pieces: historyReturQtyValue(item, 'pieces'),
    box: historyReturQtyValue(item, 'box'),
    karton: historyReturQtyValue(item, 'karton')
  }, uomItem)));
}

function formatReturHistoryQty(item) {
  const uomItem = historyReturUomContext(item);
  if (item?.qty_retur_uom_valid === false || item?.qty_retur_uom_valid === 'false') {
    return 'Konversi UOM master belum lengkap';
  }

  const totalPieces = historyReturTotalPieces(item, uomItem);
  const splitQty = splitReturPieces(totalPieces, uomItem);
  const qtyRows = [
    { level: 3, value: splitQty.karton },
    { level: 2, value: splitQty.box },
    { level: 1, value: splitQty.pieces }
  ]
    .filter(({ level, value }) => isReturUomEnabled(uomItem, level) && value > 0)
    .map(({ level, value }) => `${Number(value).toLocaleString('id-ID')} ${getReturUomName(uomItem, level)}`);

  if (qtyRows.length) {
    const primaryLabel = getReturUomName(uomItem, 1);
    const usesHigherUom = splitQty.box > 0 || splitQty.karton > 0;
    return usesHigherUom && primaryLabel
      ? `${qtyRows.join(' | ')} (${totalPieces.toLocaleString('id-ID')} ${primaryLabel})`
      : qtyRows.join(' | ');
  }

  const primaryUomLevel = [1, 2, 3].find((level) => isReturUomEnabled(uomItem, level));
  if (primaryUomLevel) {
    return `0 ${getReturUomName(uomItem, primaryUomLevel)}`;
  }

  return 'UOM produk belum dikonfigurasi';
}

function getOrderUnitPrice(item) {
  return toNumber(item.hargaorder || item.harga_jual || item.harga || 0);
}

function getOrderSubtotal(item) {
  const explicitSubtotal = toNumber(item.subtotalorder || item.subtotal_order || item.subtotal);
  if (explicitSubtotal) return explicitSubtotal;

  const qty = qtyTotalPieces(
    {
      pieces: toNumber(item.pieces_order),
      box: toNumber(item.box_order),
      karton: toNumber(item.karton_order)
    },
    item
  );

  return qty * getOrderUnitPrice(item);
}

function getOrderDiscountTotal(item) {
  const explicitDiscount = toNumber(item.total_nilai_discount || item.totalDiskon || item.total_diskon);
  if (explicitDiscount) return explicitDiscount;

  return [
    item.v1r_diskon,
    item.v2r_diskon,
    item.v2p_diskon,
    item.v3r_diskon,
    item.v3p_diskon
  ].reduce((sum, value) => sum + toNumber(value), 0);
}

function getOrderNetSubtotal(item) {
  return Math.max(getOrderSubtotal(item) - getOrderDiscountTotal(item), 0);
}

function discountEntries(item) {
  return [
    { label: 'V1 Reg', name: item.v1r_nama, code: item.v1r_kode, discount: item.v1r_diskon, percent: item.v1r_persen },
    { label: 'V2 Reg', name: item.v2r_nama, code: item.v2r_kode, discount: item.v2r_diskon, percent: item.v2r_persen },
    { label: 'V2 Produk', name: item.v2p_nama, code: item.v2p_kode, discount: item.v2p_diskon, percent: item.v2p_persen },
    { label: 'V3 Reg', name: item.v3r_nama, code: item.v3r_kode, discount: item.v3r_diskon, percent: item.v3r_persen },
    { label: 'V3 Produk', name: item.v3p_nama, code: item.v3p_kode, discount: item.v3p_diskon, percent: item.v3p_persen }
  ].filter((entry) => toNumber(entry.discount) > 0 || hasText(entry.name) || hasText(entry.code));
}

function formatDiscountEntry(entry) {
  const parts = [
    entry.code || entry.name || entry.label,
    toNumber(entry.percent) ? `${Number(entry.percent).toLocaleString('id-ID')}%` : '',
    toNumber(entry.discount) ? formatCurrency(entry.discount) : ''
  ].filter(Boolean);

  return parts.join(' | ');
}

function qtyTotalPieces(qty, item) {
  const level1 = isReturUomEnabled(item, 1) ? getReturUomConversion(item, 1) : 0;
  const level2 = isReturUomEnabled(item, 2) ? getReturUomConversion(item, 2) : 0;
  const level3 = isReturUomEnabled(item, 3) ? getReturUomConversion(item, 3) : 0;

  return (
    toNumber(qty.pieces) * level1 +
    toNumber(qty.box) * level2 +
    toNumber(qty.karton) * level3
  );
}

function resolveReturnLimitQty(item) {
  const orderQty = {
    pieces: toNumber(item.pieces_order),
    box: toNumber(item.box_order),
    karton: toNumber(item.karton_order)
  };
  const deliveredQty = {
    pieces: toNumber(item.pieces_delivered ?? item.pieces_picked),
    box: toNumber(item.box_delivered ?? item.box_picked),
    karton: toNumber(item.karton_delivered ?? item.karton_picked)
  };

  const orderTotal = qtyTotalPieces(orderQty, item);
  const deliveredTotal = qtyTotalPieces(deliveredQty, item);

  if (!deliveredTotal || (orderTotal && deliveredTotal > orderTotal)) {
    return orderQty;
  }

  return deliveredQty;
}

function isCancelledRetur(item) {
  return ['9', 'batal', 'cancel', 'cancelled', 'canceled', 'reject', 'rejected', 'ditolak']
    .includes(String(item?.status_request ?? item?.status_request_retur ?? '').trim().toLowerCase());
}

function historicalReturPieces(item) {
  const productId = String(item?.id_produk ?? '');
  if (!productId) return 0;

  return existingReturRows.value
    .filter((history) => String(history?.id_produk ?? '') === productId && !isCancelledRetur(history))
    .reduce((total, history) => {
      if (hasReturUomValue(history?.qty_retur_pcs)) {
        return total + Math.max(0, toNumber(history.qty_retur_pcs));
      }

      const storedTotal = qtyTotalPieces({
        pieces: toNumber(history.pieces_retur),
        box: toNumber(history.box_retur),
        karton: toNumber(history.karton_retur)
      }, item);
      const splitTotal = qtyTotalPieces({
        pieces: toNumber(history.pieces_diajukan) + toNumber(history.pieces_good_diajukan),
        box: toNumber(history.box_diajukan) + toNumber(history.box_good_diajukan),
        karton: toNumber(history.karton_diajukan) + toNumber(history.karton_good_diajukan)
      }, item);
      return total + Math.max(storedTotal, splitTotal);
    }, 0);
}

function splitReturPieces(totalPieces, item) {
  let remaining = Math.max(0, Math.floor(toNumber(totalPieces)));
  const level2 = getReturUomConversion(item, 2);
  const level3 = getReturUomConversion(item, 3);
  const karton = isReturUomEnabled(item, 3) && level3 > 0 ? Math.floor(remaining / level3) : 0;
  remaining -= karton * level3;
  const box = isReturUomEnabled(item, 2) && level2 > 0 ? Math.floor(remaining / level2) : 0;
  remaining -= box * level2;
  return {
    pieces: isReturUomEnabled(item, 1) ? remaining : 0,
    box,
    karton
  };
}

function normalizeReturRow(item) {
  const limitQty = resolveReturnLimitQty(item);
  const limitPieces = qtyTotalPieces(limitQty, item);
  const alreadyReturPieces = historicalReturPieces(item);
  const remainingQty = splitReturPieces(Math.max(limitPieces - alreadyReturPieces, 0), item);

  return {
    ...item,
    row_key: String(item.id_order_detail || item.id_produk || Math.random()),
    pieces_retur_good: 0,
    box_retur_good: 0,
    karton_retur_good: 0,
    pieces_retur_bad: 0,
    box_retur_bad: 0,
    karton_retur_bad: 0,
    good_total: 0,
    bad_total: 0,
    total_retur: 0,
    keterangan_retur: '',
    max_pieces: remainingQty.pieces,
    max_box: remainingQty.box,
    max_karton: remainingQty.karton,
    already_retur_pieces: alreadyReturPieces
  };
}

function recalculateReturRow(row) {
  [
    'pieces_retur_good',
    'box_retur_good',
    'karton_retur_good',
    'pieces_retur_bad',
    'box_retur_bad',
    'karton_retur_bad'
  ].forEach((field) => {
    const level = getReturFieldLevel(field);
    if (!isReturUomEnabled(row, level)) {
      row[field] = 0;
    }
  });

  row.good_total = Number(row.pieces_retur_good || 0) + Number(row.box_retur_good || 0) + Number(row.karton_retur_good || 0);
  row.bad_total = Number(row.pieces_retur_bad || 0) + Number(row.box_retur_bad || 0) + Number(row.karton_retur_bad || 0);
  row.total_retur = row.good_total + row.bad_total;
}

function updateReturField(row, field, value) {
  const level = getReturFieldLevel(field);
  if (!isReturUomEnabled(row, level)) {
    row[field] = 0;
    recalculateReturRow(row);
    return;
  }

  row[field] = Math.max(0, Math.floor(Number(value || 0)));
  recalculateReturRow(row);
}

function returInputPieces(row) {
  return qtyTotalPieces({
    pieces: Number(row.pieces_retur_good || 0) + Number(row.pieces_retur_bad || 0),
    box: Number(row.box_retur_good || 0) + Number(row.box_retur_bad || 0),
    karton: Number(row.karton_retur_good || 0) + Number(row.karton_retur_bad || 0)
  }, row);
}

function validateReturQuantities() {
  const invalidRow = returRows.value.find((row) => {
    const limit = qtyTotalPieces({
      pieces: row.max_pieces,
      box: row.max_box,
      karton: row.max_karton
    }, row);
    return returInputPieces(row) > limit;
  });
  if (!invalidRow) return '';
  return `${invalidRow.nama_produk || invalidRow.kode_sku || 'Produk'}: total GOOD + BAD tidak boleh melebihi qty terkirim.`;
}

function buildReturPayload() {
  return {
    id_sales_order: Number(form.idSalesOrder),
    id_sales: Number(form.idSales),
    id_plafon: Number(form.idPlafon),
    tanggal_retur_pengajuan: form.tanggalRetur,
    products: returRows.value
      .filter((item) => Number(item.total_retur || 0) > 0)
      .map((item) => ({
        id_produk: Number(item.id_produk),
        harga_satuan: Number(item.hargaorder || item.harga_jual || item.harga || 0),
        pieces_retur_good: Number(item.pieces_retur_good || 0),
        box_retur_good: Number(item.box_retur_good || 0),
        karton_retur_good: Number(item.karton_retur_good || 0),
        pieces_retur_bad: Number(item.pieces_retur_bad || 0),
        box_retur_bad: Number(item.box_retur_bad || 0),
        karton_retur_bad: Number(item.karton_retur_bad || 0),
        keterangan_retur: item.keterangan_retur || ''
      }))
  };
}

async function loadExistingRetur() {
  if (!form.idSalesOrder) {
    existingReturRows.value = [];
    return;
  }

  checking.value = true;

  try {
    const response = await checkSalesRetur({ id_sales_order: form.idSalesOrder });
    existingReturRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    existingReturRows.value = [];
  } finally {
    checking.value = false;
  }
}

async function loadOrderDetail() {
  if (!form.idSalesOrder) {
    errorMessage.value = 'Sales order belum dipilih.';
    return;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getInvoiceDetail(form.idSalesOrder);
    const payload = unwrapResponse(response) || {};
    sourceRows.value = normalizeList(payload?.list_detail_order || payload);
    invoiceHeader.value = payload?.detail_faktur || {};
    await loadExistingRetur();
    returRows.value = sourceRows.value.map(normalizeReturRow);
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail order untuk retur belum bisa dimuat.');
    sourceRows.value = [];
    returRows.value = [];
    invoiceHeader.value = {};
  } finally {
    loading.value = false;
  }
}

async function searchInvoice() {
  feedback.value = '';
  errorMessage.value = '';

  if (!searchForm.invoiceNo.trim()) {
    errorMessage.value = 'Isi nomor faktur, nomor order, kode customer, atau nama customer terlebih dahulu.';
    return;
  }

  searchLoading.value = true;

  try {
    const params = {
      search: searchForm.invoiceNo.trim()
    };

    if (form.idPlafon) {
      params.id_plafon = [Number(form.idPlafon)];
    }

    const response = await searchSalesInvoices(params);
    const rows = normalizeList(unwrapResponse(response));
    const exactReturRow = rows.find((item) => isReturReferenceMatch(item, params.search));

    if (exactReturRow) {
      searchRows.value = [];
      searchForm.selectedInvoice = '';
      feedback.value = buildAlreadyReturMessage(exactReturRow, params.search);
      return;
    }

    searchRows.value = rows;
    if (!searchRows.value.length) {
      feedback.value = 'Faktur/order/retur tidak ditemukan. Coba cek nomor faktur, nomor order, kode retur, atau nama customer.';
      return;
    }

    const alreadyReturRow = searchRows.value.find(hasReturRecord);
    if (alreadyReturRow) {
      feedback.value = buildAlreadyReturMessage(alreadyReturRow, formatInvoiceSearchLabel(alreadyReturRow));
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Pencarian faktur retur belum berhasil.');
    searchRows.value = [];
  } finally {
    searchLoading.value = false;
  }
}

async function applyInvoiceSelection() {
  const selected = searchRows.value.find((item) => String(item.id_sales_order) === String(searchForm.selectedInvoice));
  if (!selected) {
    return;
  }

  form.idSalesOrder = String(selected.id_sales_order || '');
  form.idSales = String(selected.id_sales || selected.sales_user_id || form.idSales || '');
  form.idPlafon = String(selected.id_plafon || form.idPlafon || '');
  form.noOrder = String(selected.no_order || '');
  form.noFaktur = String(formatInvoiceSearchLabel(selected) === '-' ? '' : formatInvoiceSearchLabel(selected));
  form.customerName = String(selected.nama_customer || '');
  await loadOrderDetail();
}

async function submitRetur() {
  feedback.value = '';
  errorMessage.value = '';

  if (hasActiveRetur.value) {
    errorMessage.value = 'Nota/faktur ini masih memiliki retur aktif atau menunggu Credit Note. Lanjutkan prosesnya dari Monitoring Retur.';
    return;
  }

  if (!canSubmit.value) {
    errorMessage.value = 'Lengkapi order retur dan isi minimal satu qty retur.';
    return;
  }

  const quantityValidation = validateReturQuantities();
  if (quantityValidation) {
    errorMessage.value = quantityValidation;
    return;
  }

  submitting.value = true;

  try {
    await createSalesRetur(buildReturPayload());
    feedback.value = 'Request retur berhasil dibuat.';
    await loadExistingRetur();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Request retur belum berhasil dibuat.');
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  form.idSalesOrder = String(route.query.id_sales_order || '');
  form.idSales = String(route.query.id_sales || route.query.sales_user_id || getStoredSalesUserId() || '');
  form.idPlafon = String(route.query.id_plafon || '');
  form.noOrder = String(route.query.no_order || '');
  form.noFaktur = String(route.query.no_faktur || '');
  form.customerName = String(route.query.customer_name || '');

  if (form.idSalesOrder) {
    await loadOrderDetail();
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Ajukan Retur"
      description="Ajukan retur langsung dari order/faktur yang sudah terbentuk, lalu pantau request retur yang sudah pernah dibuat untuk order yang sama."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'sales-order-list', query: salesQuery() })">
          Kembali ke Order Sales
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="router.push({ name: 'sales-order-retur-list', query: salesQuery() })">
          Monitoring Retur
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="loading" @click="loadOrderDetail">
          {{ loading ? 'Memuat...' : 'Refresh Detail Order' }}
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Sales Order ID</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ form.idSalesOrder || '-' }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">No Order</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ form.noOrder || '-' }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">No Faktur</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ form.noFaktur || invoiceHeader.no_faktur || invoiceHeader.nomor_faktur || '-' }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Customer</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ form.customerName || invoiceHeader.nama_customer || '-' }}</p>
      </article>
      <article class="panel p-5">
        <AppFormField v-model="form.tanggalRetur" label="Tanggal Request Retur" type="date" />
      </article>
    </section>

    <section class="panel p-5">
      <div class="grid gap-3 md:grid-cols-[1.5fr_1.5fr_auto]">
        <AppFormField v-model="searchForm.invoiceNo" label="Cari Faktur / Order / Retur / Customer" placeholder="Ketik no faktur, no order, kode retur, kode/nama customer" />
        <AppSearchSelect
          v-model="searchForm.selectedInvoice"
          label="Hasil Faktur"
          placeholder="Pilih faktur hasil pencarian"
          :options="invoiceOptions"
          empty-text="Belum ada hasil faktur."
        />
        <div class="flex items-end gap-2">
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60" :disabled="searchLoading" @click="searchInvoice">
            {{ searchLoading ? 'Mencari...' : 'Cari Faktur' }}
          </button>
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="!searchForm.selectedInvoice" @click="applyInvoiceSelection">
            Pakai Faktur
          </button>
        </div>
      </div>
      <p class="mt-3 text-xs text-slate-500">Pencarian ini bisa dipakai langsung dari menu Ajukan Retur. Jika halaman dibuka dari order tertentu, hasil akan otomatis dibatasi ke plafon/order aktif.</p>
    </section>

    <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </div>
    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </div>

    <section class="space-y-6">
      <article class="panel overflow-hidden">
        <div class="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Input Barang Retur</h3>
            <p class="mt-1 text-sm text-slate-500">Retur ini terikat pada satu nota/faktur. Pisahkan qty GOOD dan BAD setelah pemeriksaan fisik. GOOD masuk Stok Ready/Good cabang saat diterima, sedangkan BAD masuk Stok Bad/Gudang Bad dan tidak siap jual. Untuk barang gagal kirim dari manifest, gunakan Karantina WMS → QC agar tidak tercatat dua kali.</p>
          </div>
        </div>

        <div v-if="hasActiveRetur" class="mx-5 mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Nota/faktur ini masih memiliki retur aktif atau menunggu Credit Note. Lanjutkan proses dari Monitoring Retur sebelum membuat pengajuan baru.
        </div>

        <div v-if="loading" class="px-5 py-10 text-center text-sm text-slate-500">
          Memuat detail order retur...
        </div>
        <div v-else-if="returRows.length" class="overflow-x-auto">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
              <tr>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Sisa Retur Nota</th>
                <th class="px-4 py-3">Harga & Diskon Nota</th>
                <th class="px-4 py-3">Good</th>
                <th class="px-4 py-3">Bad</th>
                <th class="px-4 py-3">Catatan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
              <tr v-for="item in returRows" :key="item.row_key">
                <td class="px-4 py-3 align-top">
                  <p class="font-semibold text-slate-900 dark:text-white">{{ item.nama_produk || '-' }}</p>
                  <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ item.kode_sku || '-' }}</p>
                </td>
                <td class="px-4 py-3 align-top text-slate-600 dark:text-slate-300">
                  {{ formatReturQtyLimit(item) }}
                  <p v-if="Number(item.already_retur_pieces || 0) > 0" class="mt-1 text-xs font-semibold text-slate-500">
                    Sudah diretur: {{ Number(item.already_retur_pieces || 0).toLocaleString('id-ID') }} PCS
                  </p>
                  <p v-if="!isReturUomEnabled(item, 1) || !isReturUomEnabled(item, 2) || !isReturUomEnabled(item, 3)" class="mt-2 text-xs font-semibold text-amber-600 dark:text-amber-300">
                    UOM yang belum lengkap otomatis dikunci.
                  </p>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="min-w-[230px] space-y-2 text-xs text-slate-600 dark:text-slate-300">
                    <div class="rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900">
                      <p class="font-semibold text-slate-900 dark:text-white">Harga satuan: {{ formatCurrency(getOrderUnitPrice(item)) }}</p>
                      <p class="mt-1">Subtotal nota: {{ formatCurrency(getOrderSubtotal(item)) }}</p>
                      <p class="mt-1">Total diskon: {{ formatCurrency(getOrderDiscountTotal(item)) }}</p>
                      <p class="mt-1 font-semibold text-emerald-700 dark:text-emerald-300">Net: {{ formatCurrency(getOrderNetSubtotal(item)) }}</p>
                    </div>
                    <div v-if="discountEntries(item).length" class="space-y-1">
                      <p class="font-semibold uppercase tracking-[0.18em] text-slate-400">Detail Diskon</p>
                      <p v-for="entry in discountEntries(item)" :key="`${entry.label}-${entry.code || entry.name || entry.discount}`" class="rounded-xl bg-sky-50 px-3 py-2 font-semibold text-sky-700 dark:bg-sky-500/10 dark:text-sky-200">
                        {{ formatDiscountEntry(entry) }}
                      </p>
                    </div>
                    <p v-else class="text-slate-400">Tidak ada diskon tercatat pada item ini.</p>
                  </div>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="grid gap-2">
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 1) }}
                      <input :value="item.pieces_retur_good" type="number" min="0" :disabled="!isReturUomEnabled(item, 1)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'pieces_retur_good', $event.target.value)">
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 2) }}
                      <input :value="item.box_retur_good" type="number" min="0" :disabled="!isReturUomEnabled(item, 2)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'box_retur_good', $event.target.value)">
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 3) }}
                      <input :value="item.karton_retur_good" type="number" min="0" :disabled="!isReturUomEnabled(item, 3)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'karton_retur_good', $event.target.value)">
                    </label>
                  </div>
                </td>
                <td class="px-4 py-3 align-top">
                  <div class="grid gap-2">
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 1) }}
                      <input :value="item.pieces_retur_bad" type="number" min="0" :disabled="!isReturUomEnabled(item, 1)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'pieces_retur_bad', $event.target.value)">
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 2) }}
                      <input :value="item.box_retur_bad" type="number" min="0" :disabled="!isReturUomEnabled(item, 2)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'box_retur_bad', $event.target.value)">
                    </label>
                    <label class="grid gap-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {{ formatReturUomLabel(item, 3) }}
                      <input :value="item.karton_retur_bad" type="number" min="0" :disabled="!isReturUomEnabled(item, 3)" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-normal tracking-normal text-slate-900 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800/60 dark:disabled:text-slate-500" @input="updateReturField(item, 'karton_retur_bad', $event.target.value)">
                    </label>
                  </div>
                </td>
                <td class="px-4 py-3 align-top">
                  <textarea :value="item.keterangan_retur" rows="4" class="w-full min-w-[220px] rounded-xl border border-slate-200 bg-white px-3 py-2 text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white" @input="item.keterangan_retur = $event.target.value" />
                  <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">Total retur: {{ Number(item.total_retur || 0).toLocaleString('id-ID') }}</p>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="px-5 py-10 text-center text-sm text-slate-500">
          Detail order retur belum tersedia. Buka halaman ini dari order yang sudah memiliki faktur.
        </div>
      </article>

      <aside class="grid gap-4 xl:grid-cols-[minmax(320px,0.45fr)_minmax(0,0.55fr)]">
        <section class="panel p-5">
          <div class="mb-4">
            <h3 class="text-lg font-semibold text-slate-900">Ringkasan Retur</h3>
            <p class="mt-1 text-sm text-slate-500">Kontrol submit dan total input retur.</p>
          </div>

          <div v-if="returRows.length" class="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            <article v-for="item in returSummary" :key="item.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">{{ item.label }}</p>
              <p class="mt-2 text-lg font-semibold text-slate-900">{{ item.value }}</p>
            </article>
          </div>
          <div v-else class="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
            Belum ada detail barang.
          </div>

          <button class="mt-4 w-full rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60" :disabled="submitting || !canSubmit" @click="submitRetur">
            {{ submitting ? 'Menyimpan...' : 'Submit Retur' }}
          </button>
        </section>

        <section class="panel p-5">
          <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 class="text-lg font-semibold text-slate-900">Riwayat Retur</h3>
              <p class="mt-1 text-sm text-slate-500">Request yang sudah dibuat untuk order ini.</p>
            </div>
            <div class="text-sm text-slate-500">
              {{ checking ? 'Memeriksa...' : `${existingReturRows.length} baris` }}
            </div>
          </div>

          <AppTable
            :rows="existingReturTableRows"
            :columns="[
              { key: 'kode_request', label: 'Request' },
              { key: 'status_request_label', label: 'Status' },
              { key: 'qty_label', label: 'Qty' }
            ]"
            :loading="checking"
            empty-message="Belum ada request retur untuk order ini."
          />
        </section>
      </aside>
    </section>
  </div>
</template>
