<script setup>
import { computed, onDeactivated, onMounted, reactive, ref, watch } from 'vue';
import {
  getDraftVariantPickingNote,
  getFleetRoutes,
  getPickingProducts,
  getPickingRoutes,
  getPickingStores,
  getRealizationRoutes,
  getShippingRoutes,
  submitPicking,
  submitPickingProducts
} from '@/api/distribution';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { escapePrintHtml, formatPrintDate, openPrintHtml, reservePrintWindow } from '@/utils/printTemplates';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const props = defineProps({ historyOnly: { type: Boolean, default: false } });

const filters = reactive({
  branchId: '',
  companyId: '',
  search: '',
  status: 'all'
});

const submitForm = reactive({
  picker: ''
});

const companyRows = ref([]);
const branchRows = ref([]);
const routeRows = ref([]);
const productRows = ref([]);
const storeRows = ref([]);
const selectedRoute = ref(null);
const selectedProduct = ref(null);
const detailOpen = ref(false);
const activeTab = ref(props.historyOnly ? 'history' : 'ready');
const storePage = ref(1);
const storePageSize = ref(15);
const loadingRoutes = ref(false);
const loadingProducts = ref(false);
const loadingStores = ref(false);
const savingProducts = ref(false);
const submittingPicking = ref(false);
const printingDraftVariant = ref(false);
const feedback = ref('');
const errorMessage = ref('');

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canUseLoginScope = computed(() => !isSuperUser(authStore));

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const branchCompanyId = getRowCompanyId(branch);

  if (branchCompanyId) ids.add(String(branchCompanyId));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
}

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, authStore, true));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, authStore, filters.companyId, true)
);

const distributionTabs = [
  { key: 'pending', label: 'Pending Jadwal', description: 'Order sudah booked, belum dijadwalkan armada.' },
  { key: 'ready', label: 'Siap Picking', description: 'Rute sudah dijadwalkan dan siap diproses picking.' },
  { key: 'history', label: 'Riwayat Operasional', description: 'Rute yang sudah bergerak ke shipping atau realisasi.' }
];

const pickingSteps = [
  { number: '1', title: 'Pilih Perusahaan, Cabang & Tab', note: 'Mulai dari pending jadwal, siap picking, atau riwayat.' },
  { number: '2', title: 'Pilih Rute', note: 'Klik rute untuk memuat toko dan produk terkait.' },
  { number: '3', title: 'Input Picked', note: 'Sesuaikan PCS, BOX, dan KARTON per produk.' },
  { number: '4', title: 'Final Picking', note: 'Submit setelah semua jumlah picking sudah benar.' }
];

const statusOptions = computed(() => {
  if (activeTab.value === 'pending') {
    return [{ value: 'all', label: 'Semua Pending Jadwal' }];
  }

  if (activeTab.value === 'ready') {
    return [{ value: 'all', label: 'Semua Siap Picking' }];
  }

  return [
    { value: 'all', label: 'Semua Riwayat' },
    { value: 'shipping', label: 'Shipping' },
    { value: 'realisasi', label: 'Realisasi' }
  ];
});

const filterFields = computed(() => [
  { key: 'companyId', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, placeholder: 'Pilih perusahaan', disabled: canUseLoginScope.value && !!fallbackCompanyId.value },
  { key: 'branchId', label: 'Cabang', type: 'search-select', options: branchOptions.value, placeholder: filters.companyId ? 'Pilih cabang' : 'Pilih perusahaan dahulu', emptyText: filters.companyId ? 'Cabang belum tersedia.' : 'Pilih perusahaan dahulu.', disabled: !filters.companyId || (!isSuperUser(authStore) && !!fallbackBranchId.value) },
  { key: 'status', label: 'Filter status', type: 'select', options: statusOptions.value },
  { key: 'search', label: 'Cari rute', placeholder: 'Rute, armada, driver, tanggal' }
]);

const routeSummaryCards = computed(() => {
  const totalRoutes = filteredRoutes.value.length;
  const totalStores = filteredRoutes.value.reduce((total, item) => total + Number(item.jumlah_toko || 0), 0);
  const totalNotes = filteredRoutes.value.reduce((total, item) => total + Number(item.jumlah_nota || 0), 0);
  const totalKubik = filteredRoutes.value.reduce(
    (total, item) => total + Number(item.kubikal || item.estimasi_kubikasi || 0),
    0
  );

  return [
    { label: 'Rute Tampil', value: totalRoutes.toLocaleString('id-ID') },
    { label: 'Total Toko', value: totalStores.toLocaleString('id-ID') },
    { label: 'Total Nota', value: totalNotes.toLocaleString('id-ID') },
    { label: 'Estimasi Kubikasi', value: totalKubik.toLocaleString('id-ID') }
  ];
});

const normalizedRoutes = computed(() =>
  routeRows.value.map((item, index) => {
    const historyStage = item.history_stage || null;
    const isPending = activeTab.value === 'pending';
    const isReady = activeTab.value === 'ready';

    let statusKey = 'default';
    let statusLabel = 'Rute';

    if (isPending) {
      statusKey = 'pending';
      statusLabel = 'Pending Jadwal';
    } else if (isReady) {
      statusKey = 'ready';
      statusLabel = 'Siap Picking';
    } else if (historyStage === 'realisasi') {
      statusKey = 'history-realisasi';
      statusLabel = 'Realisasi';
    } else {
      statusKey = 'history-shipping';
      statusLabel = 'Shipping';
    }

    return {
      ...item,
      row_key: `${item.id_proses_picking || item.id_order_detail || item.id_rute || index}-${item.id_armada || 'no-armada'}-${item.id_driver || 'no-driver'}-${item.delivering_date || 'no-date'}-${historyStage || 'active'}`,
      route_label: `${item.kode || item.kode_rute || '-'} - ${item.nama_rute || 'Rute'}`,
      fleet_label: item.nama_armada || (item.id_armada ? `Armada #${item.id_armada}` : '-'),
      driver_label: item.nama_driver || (item.id_driver ? `Driver #${item.id_driver}` : '-'),
      kubikal_label: Number(item.kubikal || item.estimasi_kubikasi || 0).toLocaleString('id-ID'),
      date_label: item.delivering_date || '-',
      status_key: statusKey,
      status_label: statusLabel
    };
  })
);

const filteredRoutes = computed(() => {
  const query = filters.search.trim().toLowerCase();
  return normalizedRoutes.value.filter((item) => {
    const rowCompanyId = getRowCompanyId(item) || item.id_perusahaan || item.company_id || item.idPerusahaan || '';
    if (filters.companyId && rowCompanyId && String(rowCompanyId) !== String(filters.companyId)) {
      return false;
    }

    const matchesStatus = filters.status === 'all' || item.history_stage === filters.status;
    if (!matchesStatus) {
      return false;
    }

    if (!query) {
      return true;
    }

    return [item.route_label, item.fleet_label, item.driver_label, item.delivering_date, item.jumlah_toko, item.jumlah_nota, item.status_label]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query));
  });
});

const normalizedProducts = computed(() =>
  productRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.produk_id || index}-${item.id_order_detail || ''}`,
    product_label: `${item.kode_sku || '-'} - ${item.nama_produk || 'Produk'}`,
    picked_label: `${Number(item.jumlah_picked || 0).toLocaleString('id-ID')} / ${Number(item.total_in_pieces || 0).toLocaleString('id-ID')}`,
    stok_label: Number(item.stok || 0).toLocaleString('id-ID')
  }))
);

const normalizedStores = computed(() =>
  storeRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_order_detail || index}`,
    order_label: `${item.no_faktur || '-'} / ${item.no_order || '-'}`,
    order_qty_label: [
      `${Number(item.pieces_order || 0).toLocaleString('id-ID')} pcs`,
      `${Number(item.box_order || 0).toLocaleString('id-ID')} box`,
      `${Number(item.karton_order || 0).toLocaleString('id-ID')} karton`
    ].join(' | '),
    total_in_pieces_label: Number(item.total_in_pieces || 0).toLocaleString('id-ID')
  }))
);

const storeTotalPages = computed(() => Math.max(1, Math.ceil(normalizedStores.value.length / storePageSize.value)));
const paginatedStores = computed(() => {
  const start = (storePage.value - 1) * storePageSize.value;
  return normalizedStores.value.slice(start, start + storePageSize.value);
});
const storeStartRow = computed(() => (storePage.value - 1) * storePageSize.value);
const storeEndRow = computed(() => Math.min(storeStartRow.value + storePageSize.value, normalizedStores.value.length));

const pickingSummary = computed(() => {
  const orderPieces = storeRows.value.reduce((total, item) => total + Number(item.total_in_pieces || 0), 0);
  const pickedPieces = storeRows.value.reduce((total, item) => total + Number(item.draft_picking || 0), 0);
  return {
    orderPieces,
    pickedPieces,
    difference: orderPieces - pickedPieces
  };
});

const showScheduleHint = computed(() => !loadingRoutes.value && !filteredRoutes.value.length);
const canPick = computed(() => !props.historyOnly && activeTab.value === 'ready');
const routePanelTitle = computed(() => {
  if (activeTab.value === 'pending') return 'Rute Pending Jadwal';
  if (activeTab.value === 'history') return 'Riwayat Rute Operasional';
  return 'Rute Siap Picking';
});
const routePanelDescription = computed(() => {
  if (activeTab.value === 'pending') {
    return 'Klik rute untuk lihat konteks operasional lalu lanjutkan penjadwalan armada.';
  }
  if (activeTab.value === 'history') {
    return 'Klik rute untuk melihat konteks operasional dan lanjutkan audit ke halaman faktur distribusi.';
  }
  return 'Klik rute untuk memuat produk dan detail picking.';
});
const activeTabMeta = computed(() => distributionTabs.find((tab) => tab.key === activeTab.value) || distributionTabs[1]);
const selectedRouteFacts = computed(() => {
  if (!selectedRoute.value) {
    return [];
  }

  return [
    { label: 'Status', value: selectedRoute.value.status_label || '-' },
    { label: 'Rute', value: selectedRoute.value.route_label || '-' },
    { label: 'Armada', value: selectedRoute.value.fleet_label || '-' },
    { label: 'Driver', value: selectedRoute.value.driver_label || '-' },
    { label: 'Tanggal Kirim', value: selectedRoute.value.date_label || '-' },
    { label: 'ID Picking', value: selectedRoute.value.id_proses_picking || '-' },
    { label: 'Toko / Nota', value: `${selectedRoute.value.jumlah_toko || 0} toko / ${selectedRoute.value.jumlah_nota || 0} nota` }
  ];
});

function getActiveBranchId() {
  return filters.branchId || String(fallbackBranchId.value || '');
}

function getActiveBranchIdNumber() {
  const branchId = Number(getActiveBranchId());
  return Number.isFinite(branchId) && branchId > 0 ? branchId : null;
}

function clearSelection() {
  selectedRoute.value = null;
  selectedProduct.value = null;
  detailOpen.value = false;
  productRows.value = [];
  storeRows.value = [];
}

function closePickingModal() {
  detailOpen.value = false;
}

function toIdList(value) {
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

async function loadBranches() {
  const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
  companyRows.value = normalizeList(unwrapResponse(companyResponse));
  branchRows.value = normalizeList(unwrapResponse(branchResponse));

  if (!filters.companyId && canUseLoginScope.value && fallbackCompanyId.value) {
    filters.companyId = String(fallbackCompanyId.value);
  }
  if (!filters.branchId && canUseLoginScope.value && fallbackBranchId.value) {
    filters.branchId = String(fallbackBranchId.value);
  }
  syncBranchFromCompany();
}

function updateFilters(nextFilters) {
  const previousBranchId = filters.branchId;
  const previousCompanyId = filters.companyId;

  Object.assign(filters, nextFilters);

  if (filters.companyId !== previousCompanyId) {
    syncBranchFromCompany();
    clearSelection();
    routeRows.value = [];
    return;
  }

  if (filters.branchId !== previousBranchId) {
    clearSelection();
    routeRows.value = [];
  }
}

function syncBranchFromCompany() {
  if (!filters.companyId || !filters.branchId) {
    return;
  }

  if (!companyIdsForBranch(filters.branchId).includes(String(filters.companyId))) {
    filters.branchId = '';
  }
}

async function loadRoutes() {
  loadingRoutes.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const branchId = getActiveBranchId();
    if (!branchId) {
      routeRows.value = [];
      clearSelection();
      feedback.value = 'Pilih cabang terlebih dahulu untuk memuat distribusi.';
      return;
    }

    let nextRows = [];

    if (activeTab.value === 'pending') {
      const response = await getFleetRoutes({ id: branchId });
      nextRows = normalizeList(unwrapResponse(response)).map((item) => ({
        ...item,
        history_stage: null
      }));
    } else if (activeTab.value === 'history') {
      const [shippingResponse, realizationResponse] = await Promise.all([
        getShippingRoutes(branchId),
        getRealizationRoutes(branchId)
      ]);

      const shippingRows = normalizeList(unwrapResponse(shippingResponse)).map((item) => ({
        ...item,
        history_stage: 'shipping'
      }));
      const realizationRows = normalizeList(unwrapResponse(realizationResponse)).map((item) => ({
        ...item,
        history_stage: 'realisasi'
      }));

      nextRows = [...shippingRows, ...realizationRows];
    } else {
      const response = await getPickingRoutes({ id: branchId });
      nextRows = normalizeList(unwrapResponse(response)).map((item) => ({
        ...item,
        history_stage: null
      }));
    }

    routeRows.value = nextRows;
    clearSelection();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Daftar rute picking belum bisa dimuat.');
    routeRows.value = [];
    clearSelection();
  } finally {
    loadingRoutes.value = false;
  }
}

async function openRoute(row) {
  selectedRoute.value = row;
  selectedProduct.value = null;
  detailOpen.value = true;
  productRows.value = [];
  storeRows.value = [];
  feedback.value = '';
  errorMessage.value = '';
  if (!canPick.value) {
    return;
  }

  loadingProducts.value = true;

  try {
    const response = await getPickingProducts({
      id: getActiveBranchId(),
      rute_id: row.id_rute,
      id_armada: row.id_armada,
      id_driver: row.id_driver,
      delivering_date: row.delivering_date,
      id_proses_picking: row.id_proses_picking,
      id_order_detail: row.id_order_detail
    });
    productRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Produk picking untuk rute ini belum bisa dimuat.');
    productRows.value = [];
  } finally {
    loadingProducts.value = false;
  }
}

async function openProduct(row) {
  selectedProduct.value = row;
  storeRows.value = [];
  feedback.value = '';
  errorMessage.value = '';
  loadingStores.value = true;

  try {
    const response = await getPickingStores({
      id_cabang: getActiveBranchIdNumber(),
      id_rute: selectedRoute.value?.id_rute,
      id_produk: row.produk_id,
      id_order_detail: row.id_order_detail
    });
    storeRows.value = normalizeList(unwrapResponse(response)).map((item) => ({
      ...item,
      draft_picking: Number(item.jumlah_picked || item.total_in_pieces || 0)
    }));
    storePage.value = 1;
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Detail toko untuk produk ini belum bisa dimuat.');
    storeRows.value = [];
  } finally {
    loadingStores.value = false;
  }
}

function updateDraftPicking(row, value) {
  const target = storeRows.value.find((item) => String(item.id_order_detail) === String(row.id_order_detail));
  if (target) {
    const max = Number(target.total_in_pieces || 0);
    const nextValue = Math.max(0, Number(value || 0));
    target.draft_picking = max > 0 ? Math.min(nextValue, max) : nextValue;
  }
}

function fillPickedFromOrder() {
  storeRows.value = storeRows.value.map((item) => ({
    ...item,
    draft_picking: Number(item.total_in_pieces || 0)
  }));
}

function clearPicked() {
  storeRows.value = storeRows.value.map((item) => ({
    ...item,
    draft_picking: 0
  }));
}

function previousStorePage() {
  storePage.value = Math.max(1, storePage.value - 1);
}

function nextStorePage() {
  storePage.value = Math.min(storeTotalPages.value, storePage.value + 1);
}

async function saveProductPicking() {
  feedback.value = '';
  errorMessage.value = '';

  if (!storeRows.value.length) {
    errorMessage.value = 'Klik produk dan muat detail toko terlebih dahulu.';
    return;
  }

  const picking = storeRows.value
    .flatMap((row) =>
      toIdList(row.id_order_detail).map((id) => ({
        id_order_detail: Number(id),
        picking: Number(row.draft_picking || 0)
      }))
    )
    .filter((row) => Number.isFinite(row.id_order_detail) && Number.isFinite(row.picking));

  if (!picking.length) {
    errorMessage.value = 'Data detail picking tidak valid.';
    return;
  }

  const overPicked = storeRows.value.some((row) => Number(row.draft_picking || 0) > Number(row.total_in_pieces || 0));
  if (overPicked) {
    errorMessage.value = 'Ada jumlah picked yang melebihi quantity order. Koreksi dulu sebelum simpan.';
    return;
  }

  savingProducts.value = true;

  try {
    await submitPickingProducts({ picking });
    feedback.value = 'Jumlah picked produk berhasil disimpan.';

    if (selectedRoute.value) {
      const currentRoute = selectedRoute.value;
      const currentProductId = selectedProduct.value?.produk_id;
      await openRoute(currentRoute);
      const refreshedProduct = normalizedProducts.value.find((item) => String(item.produk_id) === String(currentProductId));
      if (refreshedProduct) {
        await openProduct(refreshedProduct);
      }
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Submit produk picking gagal.');
  } finally {
    savingProducts.value = false;
  }
}

async function handleSubmitPicking() {
  feedback.value = '';
  errorMessage.value = '';

  if (!selectedRoute.value || !productRows.value.length) {
    errorMessage.value = 'Klik rute picking dan muat produk terlebih dahulu.';
    return;
  }

  const branchId = getActiveBranchIdNumber();
  if (!branchId) {
    errorMessage.value = 'Cabang aktif tidak valid untuk submit picking.';
    return;
  }

  if (!submitForm.picker) {
    errorMessage.value = 'Nama picker wajib diisi.';
    return;
  }

  submittingPicking.value = true;

  try {
    await submitPicking({
      id_cabang: branchId,
      nama_picked: submitForm.picker,
      id_proses_picking: selectedRoute.value.id_proses_picking,
      id_order_detail: selectedRoute.value.id_order_detail,
      id_armada: selectedRoute.value.id_armada,
      id_driver: selectedRoute.value.id_driver,
      delivering_date: selectedRoute.value.delivering_date,
      list_picking: productRows.value.map((item) => ({
        id_order_detail: item.id_order_detail,
        id_faktur: item.id_faktur,
        produk_id: item.produk_id,
        nama_produk: item.nama_produk,
        konversi1: Number(item.konversi1 || 1),
        konversi2: Number(item.konversi2 || 0),
        konversi3: Number(item.konversi3 || 0)
      }))
    });
    feedback.value = 'Picking final berhasil disubmit.';
    await loadRoutes();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Submit final picking gagal.');
  } finally {
    submittingPicking.value = false;
  }
}

function formatDraftQty(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return '0';
  return number.toLocaleString('id-ID', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  });
}

function draftOrderUomText(variant) {
  const order = variant?.order_uom || {};
  const uom = variant?.uom || {};
  const items = [
    { value: order.karton, label: uom.karton?.label },
    { value: order.box, label: uom.box?.label },
    { value: order.pieces, label: uom.pieces?.label || 'PCS' }
  ].filter((item) => Number(item.value || 0) > 0);

  if (!items.length) {
    return `0 ${uom.pieces?.label || 'PCS'}`;
  }

  return items
    .map((item) => `${formatDraftQty(item.value)} ${item.label || '-'}`)
    .join(' + ');
}

function draftListText(values, fallback = '-') {
  if (!Array.isArray(values) || !values.length) return fallback;
  return values.filter(Boolean).join(', ') || fallback;
}

function buildDraftVariantHtml(payload) {
  const document = payload?.document || {};
  const summary = payload?.summary || {};
  const variants = Array.isArray(payload?.variants) ? payload.variants : [];
  const generatedAt = document.generated_at || '-';
  const routeLabel = [document.route?.code, document.route?.name].filter(Boolean).join(' - ') || '-';
  const fleetLabel = [document.fleet?.code, document.fleet?.name, document.fleet?.plate]
    .filter((item) => item && item !== '-')
    .join(' | ') || '-';
  const branchLabel = [document.branch?.code, document.branch?.name].filter(Boolean).join(' - ') || '-';

  const rowsHtml = variants.length
    ? variants.map((variant, index) => {
      const customerText = `${formatDraftQty(variant.customer_count)} toko${variant.customer_names?.length ? `: ${draftListText(variant.customer_names)}` : ''}`;
      const orderText = draftListText(variant.order_numbers);
      return `
        <tr>
          <td class="center">${index + 1}</td>
          <td>
            <strong>${escapePrintHtml(variant.sku || '-')}</strong>
            <div class="muted">${escapePrintHtml(variant.product_name || '-')}</div>
            <div class="muted tiny">${escapePrintHtml(variant.variant_key || '-')}</div>
          </td>
          <td>${escapePrintHtml(variant.principal_name || '-')}</td>
          <td class="num">${escapePrintHtml(draftOrderUomText(variant))}<div class="muted tiny">${formatDraftQty(variant.total_order_pcs)} PCS</div></td>
          <td class="num strong">${formatDraftQty(variant.draft_picked_pcs)} PCS</td>
          <td>
            <div>${escapePrintHtml(customerText)}</div>
            <div class="muted tiny">Order: ${escapePrintHtml(orderText)}</div>
          </td>
        </tr>
      `;
    }).join('')
    : '<tr><td colspan="6" class="center muted">Tidak ada varian produk pada jadwal ini.</td></tr>';

  return `<!doctype html>
    <html lang="id">
      <head>
        <meta charset="utf-8" />
        <title>${escapePrintHtml(document.document_code || 'Nota Draft By Variant')}</title>
        <style>
          @page { size: A4 landscape; margin: 9mm; }
          * { box-sizing: border-box; }
          body { margin: 0; color: #111827; font-family: Arial, Helvetica, sans-serif; font-size: 11px; }
          .sheet { width: 100%; }
          .header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; border-bottom: 2px solid #0f172a; padding-bottom: 10px; }
          .title { margin: 0; font-size: 21px; letter-spacing: .04em; }
          .subtitle { margin: 5px 0 0; color: #475569; font-size: 11px; }
          .draft { display: inline-block; border: 1.5px solid #b45309; background: #fffbeb; color: #92400e; border-radius: 999px; padding: 5px 9px; font-size: 10px; font-weight: 700; letter-spacing: .07em; }
          .code { margin-top: 8px; text-align: right; font-family: monospace; font-weight: 700; }
          .meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 18px; margin: 14px 0 10px; }
          .meta div { border-bottom: 1px solid #cbd5e1; padding: 0 0 5px; }
          .label { display: block; color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
          .notice { margin: 10px 0; border: 1px solid #f59e0b; background: #fffbeb; color: #78350f; padding: 8px 10px; border-radius: 6px; line-height: 1.4; }
          table { width: 100%; border-collapse: collapse; margin-top: 10px; }
          th { background: #0f172a; color: #fff; font-size: 9px; letter-spacing: .04em; text-align: left; text-transform: uppercase; }
          th, td { border: 1px solid #94a3b8; padding: 7px 8px; vertical-align: top; }
          tr:nth-child(even) td { background: #f8fafc; }
          .center { text-align: center; }
          .num { text-align: right; white-space: nowrap; }
          .strong { font-weight: 700; }
          .muted { color: #64748b; margin-top: 3px; }
          .tiny { font-size: 9px; }
          .summary { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-top: 12px; }
          .summary div { border: 1px solid #cbd5e1; border-radius: 5px; padding: 7px 8px; }
          .summary strong { display: block; margin-top: 3px; font-size: 14px; }
          .footer { display: grid; grid-template-columns: repeat(3, 1fr); gap: 42px; margin-top: 28px; text-align: center; }
          .footer div { border-top: 1px solid #64748b; padding-top: 6px; }
          @media print { .sheet { break-after: avoid; } }
        </style>
      </head>
      <body>
        <main class="sheet">
          <header class="header">
            <div>
              <h1 class="title">NOTA DRAFT BY VARIANT</h1>
              <p class="subtitle">${escapePrintHtml(document.stage_label || 'Siap Picking / sebelum Shipping')}</p>
            </div>
            <div>
              <span class="draft">DRAFT • BELUM SHIPPING</span>
              <div class="code">${escapePrintHtml(document.document_code || '-')}</div>
            </div>
          </header>

          <section class="meta">
            <div><span class="label">Cabang</span>${escapePrintHtml(branchLabel)}</div>
            <div><span class="label">Rute</span>${escapePrintHtml(routeLabel)}</div>
            <div><span class="label">Tanggal Kirim</span>${escapePrintHtml(formatPrintDate(document.delivering_date))}</div>
            <div><span class="label">Armada</span>${escapePrintHtml(fleetLabel)}</div>
            <div><span class="label">Driver</span>${escapePrintHtml(document.driver?.name || '-')}</div>
            <div><span class="label">Dicetak</span>${escapePrintHtml(generatedAt)}</div>
          </section>

          <div class="notice">
            <strong>Definisi varian:</strong> ${escapePrintHtml(document.variant_definition || 'SKU + ID produk')}
            <br />${escapePrintHtml(document.notice || '')}
          </div>

          <table>
            <thead>
              <tr>
                <th style="width:4%">No</th>
                <th style="width:25%">SKU / Varian Produk</th>
                <th style="width:16%">Principal</th>
                <th style="width:17%">Qty Order</th>
                <th style="width:13%">Qty Draft Picking</th>
                <th>Toko / Order</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>

          <section class="summary">
            <div><span class="label">Varian</span><strong>${formatDraftQty(summary.variant_count)}</strong></div>
            <div><span class="label">Toko</span><strong>${formatDraftQty(summary.customer_count)}</strong></div>
            <div><span class="label">Order</span><strong>${formatDraftQty(summary.order_count)}</strong></div>
            <div><span class="label">Total Order</span><strong>${formatDraftQty(summary.total_order_pcs)} PCS</strong></div>
            <div><span class="label">Total Draft Picking</span><strong>${formatDraftQty(summary.total_draft_picked_pcs)} PCS</strong></div>
          </section>

          <section class="footer">
            <div>Disiapkan Gudang</div>
            <div>Checker</div>
            <div>Driver / Helper</div>
          </section>
        </main>
      </body>
    </html>`;
}

async function printDraftVariant() {
  if (printingDraftVariant.value) return;

  const branchId = getActiveBranchIdNumber();
  const routeId = Number(selectedRoute.value?.id_rute || 0);
  if (!branchId || !routeId) {
    errorMessage.value = 'Pilih rute siap picking yang valid terlebih dahulu.';
    return;
  }

  const printWindow = reservePrintWindow({ width: 1280, height: 820 });
  if (!printWindow) {
    errorMessage.value = 'Popup cetak diblokir browser. Izinkan popup lalu coba kembali.';
    return;
  }

  printingDraftVariant.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    printWindow.document.write('<!doctype html><title>Menyiapkan nota draft</title><p style="font-family:Arial,sans-serif;padding:24px">Menyiapkan nota draft by variant…</p>');
    printWindow.document.close();

    const response = await getDraftVariantPickingNote({
      id_cabang: branchId,
      id_rute: routeId,
      id_armada: selectedRoute.value?.id_armada,
      id_driver: selectedRoute.value?.id_driver,
      delivering_date: selectedRoute.value?.delivering_date,
      id_proses_picking: selectedRoute.value?.id_proses_picking
    });
    const payload = unwrapResponse(response) || {};
    if (!Array.isArray(payload.variants) || !payload.variants.length) {
      throw new Error('Tidak ada varian produk pada jadwal ini untuk dicetak.');
    }

    const title = `Nota Draft Varian - ${payload.document?.document_code || selectedRoute.value?.route_label || ''}`;
    const opened = openPrintHtml(title, buildDraftVariantHtml(payload), {
      printWindow,
      width: 1280,
      height: 820
    });
    if (!opened) {
      throw new Error('Popup cetak diblokir browser. Izinkan popup lalu coba kembali.');
    }

    feedback.value = 'Nota draft by variant siap dicetak. Dokumen ini tidak mengubah stok maupun status pengiriman.';
  } catch (error) {
    if (!printWindow.closed) {
      printWindow.close();
    }
    errorMessage.value = normalizeError(error, 'Nota draft by variant belum dapat disiapkan.');
  } finally {
    printingDraftVariant.value = false;
  }
}

function reset() {
  filters.companyId = canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
  filters.branchId = canUseLoginScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  syncBranchFromCompany();
  filters.search = '';
  filters.status = 'all';
  submitForm.picker = '';
  loadRoutes();
}

onMounted(async () => {
  await loadBranches();
  await loadRoutes();
});

onDeactivated(() => {
  closePickingModal();
});

watch(activeTab, () => {
  filters.status = 'all';
  loadRoutes();
});

watch(
  () => filters.companyId,
  (value, previousValue) => {
    if (value === previousValue) return;
    syncBranchFromCompany();
    clearSelection();
    routeRows.value = [];
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (branchId === previousBranchId) return;
    clearSelection();
    routeRows.value = [];
  }
);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Distribusi Picking"
      description="Distribusi saya rapikan jadi lebih operasional: pilih perusahaan dan cabang, pindah tab Pending Jadwal / Siap Picking / Riwayat Operasional, lalu lanjutkan proses dari daftar rute yang sudah diberi badge status."
    />

    <section v-if="!props.historyOnly" class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="step in pickingSteps" :key="step.number" class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex items-start gap-3">
          <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-600 text-sm font-bold text-white">{{ step.number }}</span>
          <div>
            <h3 class="text-sm font-semibold text-slate-900">{{ step.title }}</h3>
            <p class="mt-1 text-xs leading-5 text-slate-500">{{ step.note }}</p>
          </div>
        </div>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadRoutes"
      @reset="reset"
    />

    <section class="grid gap-3 lg:grid-cols-3">
      <button
        v-for="tab in distributionTabs.filter(tab => !props.historyOnly || tab.key === 'history')"
        :key="tab.key"
        type="button"
        class="group rounded-3xl border px-5 py-4 text-left transition"
        :class="tab.key === activeTab
          ? 'border-brand-300 bg-brand-50 text-brand-950 shadow-sm dark:border-brand-500/60 dark:bg-brand-500/15 dark:text-brand-100 dark:shadow-brand-950/20'
          : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200 dark:hover:border-slate-500 dark:hover:bg-slate-800'"
        @click="activeTab = tab.key"
      >
        <p class="text-sm font-semibold">{{ tab.label }}</p>
        <p
          :class="[
            'mt-1 text-sm leading-6',
            tab.key === activeTab
              ? 'text-brand-800 dark:text-brand-100/80'
              : 'text-slate-500 dark:text-slate-400'
          ]"
        >
          {{ tab.description }}
        </p>
      </button>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="item in routeSummaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section class="panel p-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900 dark:text-white">{{ routePanelTitle }}</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ routePanelDescription }}</p>
        </div>
        <span class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.25em] text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
          {{ activeTabMeta.label }}
        </span>
      </div>

      <div v-if="loadingRoutes" class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
        Memuat daftar rute distribusi...
      </div>

      <div v-else-if="!filteredRoutes.length" class="mt-4 rounded-2xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
        Belum ada rute untuk filter yang aktif.
      </div>

      <div v-else class="mt-4 space-y-3">
        <button
          v-for="row in filteredRoutes"
          :key="row.row_key"
          type="button"
          class="w-full rounded-3xl border p-4 text-left transition"
          :class="selectedRoute?.row_key === row.row_key
            ? 'border-brand-300 bg-brand-50 shadow-sm dark:border-brand-400/40 dark:bg-brand-500/10'
            : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900/60 dark:hover:border-slate-500 dark:hover:bg-slate-800'"
          @click="openRoute(row)"
        >
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <p class="text-sm font-semibold text-slate-900 dark:text-white">{{ row.route_label }}</p>
                <span
                  class="rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide"
                  :class="{
                    'bg-amber-100 text-amber-800': row.status_key === 'pending',
                    'bg-sky-100 text-sky-800': row.status_key === 'ready',
                    'bg-emerald-100 text-emerald-800': row.status_key === 'history-shipping',
                    'bg-violet-100 text-violet-800': row.status_key === 'history-realisasi',
                    'bg-slate-100 text-slate-700': row.status_key === 'default'
                  }"
                >
                  {{ row.status_label }}
                </span>
              </div>
              <p class="mt-2 text-sm text-slate-500 dark:text-slate-400">
                Armada: <span class="font-medium text-slate-700 dark:text-slate-200">{{ row.fleet_label }}</span>
                <span class="mx-2 text-slate-300 dark:text-slate-600">|</span>
                Driver: <span class="font-medium text-slate-700 dark:text-slate-200">{{ row.driver_label }}</span>
              </p>
            </div>
            <div class="text-right text-sm text-slate-500 dark:text-slate-400">
              <p>{{ row.date_label }}</p>
              <p class="mt-1">{{ row.kubikal_label }} kubik</p>
            </div>
          </div>

          <div class="mt-4 flex flex-wrap gap-2 text-xs text-slate-600 dark:text-slate-300">
            <span class="rounded-full bg-slate-100 px-3 py-1 dark:bg-slate-800">{{ Number(row.jumlah_toko || 0).toLocaleString('id-ID') }} toko</span>
            <span class="rounded-full bg-slate-100 px-3 py-1 dark:bg-slate-800">{{ Number(row.jumlah_nota || 0).toLocaleString('id-ID') }} nota</span>
            <span v-if="row.history_stage" class="rounded-full bg-slate-100 px-3 py-1 dark:bg-slate-800">Tahap {{ row.history_stage }}</span>
          </div>
        </button>
      </div>
    </section>

    <section v-if="showScheduleHint" class="panel border-amber-200 bg-amber-50 p-5 dark:border-amber-400/30 dark:bg-amber-500/10">
      <h3 class="text-base font-semibold text-amber-950 dark:text-amber-100">
        {{ activeTab === 'pending' ? 'Belum ada rute booked yang siap dijadwalkan.' : 'Order belum masuk Picking.' }}
      </h3>
      <p class="mt-2 text-sm leading-6 text-amber-800 dark:text-amber-100/80">
        Setelah konfirmasi order, status order masih <span class="font-semibold">Booked</span> dan akan tampil di
        <span class="font-semibold">Jadwal Pengiriman</span>. Pilih rute, armada, driver, dan tanggal kirim dulu agar status naik ke
        <span class="font-semibold">Picking</span>.
      </p>
      <RouterLink
        to="/distribution/schedules"
        class="mt-4 inline-flex rounded-xl bg-amber-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-800"
      >
        Buka Jadwal Pengiriman
      </RouterLink>
    </section>

    <AppModal
      :open="detailOpen"
      :title="canPick ? 'Detail Picking Rute' : 'Detail Operasional Rute'"
      :description="selectedRoute ? selectedRoute.route_label : 'Pilih rute untuk membuka detail.'"
      size="7xl"
      @close="closePickingModal"
    >
      <div v-if="selectedRoute" class="space-y-5">
        <section class="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
          <article v-for="item in selectedRouteFacts" :key="item.label" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-800/70">
            <p class="text-xs uppercase tracking-[0.2em] text-slate-400">{{ item.label }}</p>
            <p class="mt-2 text-sm font-semibold text-slate-900 dark:text-white">{{ item.value }}</p>
          </article>
        </section>

        <template v-if="!canPick">
          <section class="rounded-2xl border border-slate-200 bg-white px-4 py-4 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-800/70 dark:text-slate-300">
              <p v-if="activeTab === 'pending'" class="leading-6">
                Rute ini masih menunggu armada, driver, dan tanggal kirim final. Lanjutkan dari halaman Jadwal Pengiriman agar status naik ke Picking.
              </p>
              <p v-else class="leading-6">
                Rute ini sudah berada di tahap operasional lanjutan. Untuk audit faktur, shipping, atau realisasi, lanjutkan dari halaman Detail Faktur Distribusi.
              </p>
          </section>

          <div class="flex flex-wrap gap-2">
            <RouterLink
              v-if="activeTab === 'pending'"
              to="/distribution/schedules"
              class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white"
            >
              Buka Jadwal Pengiriman
            </RouterLink>
            <RouterLink
              v-else
              :to="{ path: '/distribution/invoices', query: { stage: activeTab === 'history' && selectedRoute?.history_stage === 'realisasi' ? 'realisasi' : 'shipping' } }"
              class="mt-4 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            >
              Buka Detail Faktur
            </RouterLink>
          </div>
        </template>

        <template v-else>
          <section class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800/70">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Produk Picking</h3>
                <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  Klik produk untuk memuat detail toko/order yang perlu dipicking.
                </p>
              </div>
              <div class="text-right">
                <p class="mb-2 text-xs text-slate-500 dark:text-slate-400">Varian = SKU + produk. Dokumen tidak mengubah stok.</p>
                <button
                  type="button"
                  class="rounded-xl border border-brand-200 bg-brand-50 px-3 py-2 text-xs font-semibold text-brand-700 hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-60 dark:border-brand-400/30 dark:bg-brand-500/10 dark:text-brand-100"
                  :disabled="printingDraftVariant || loadingProducts"
                  @click="printDraftVariant"
                >
                  {{ printingDraftVariant ? 'Menyiapkan cetakan...' : 'Cetak Nota Draft Varian' }}
                </button>
              </div>
            </div>
            <div class="mt-4">
              <AppTable
                :rows="normalizedProducts"
                :columns="[
                  { key: 'product_label', label: 'Produk' },
                  { key: 'nama_principal', label: 'Principal' },
                  { key: 'picked_label', label: 'Picked / Order' },
                  { key: 'stok_label', label: 'Stok Ready (PCS)' }
                ]"
                :loading="loadingProducts"
                :clickable-rows="true"
                empty-message="Produk picking untuk rute ini belum tersedia."
                @row-click="openProduct"
              />
            </div>
          </section>

          <section class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800/70">
            <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Detail Toko / Order</h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Produk aktif: <span class="font-semibold text-slate-900 dark:text-white">{{ selectedProduct?.product_label || '-' }}</span>
            </p>

            <div v-if="storeRows.length" class="mt-4 grid gap-3 sm:grid-cols-3">
              <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
                <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Order</p>
                <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{{ Number(pickingSummary.orderPieces || 0).toLocaleString('id-ID') }}</p>
              </div>
              <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
                <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Total Picked</p>
                <p class="mt-2 text-lg font-semibold text-slate-900 dark:text-white">{{ Number(pickingSummary.pickedPieces || 0).toLocaleString('id-ID') }}</p>
              </div>
              <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900/70">
                <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Sisa</p>
                <p class="mt-2 text-lg font-semibold" :class="pickingSummary.difference < 0 ? 'text-rose-700 dark:text-rose-300' : 'text-slate-900 dark:text-white'">
                  {{ Number(pickingSummary.difference || 0).toLocaleString('id-ID') }}
                </p>
              </div>
            </div>

            <div v-if="storeRows.length" class="mt-4 flex flex-wrap gap-2">
              <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="fillPickedFromOrder">
                Isi Picked = Order
              </button>
              <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="clearPicked">
                Kosongkan Picked
              </button>
            </div>

            <div class="mt-4 overflow-x-auto rounded-2xl border border-slate-200 dark:border-slate-700">
              <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
                <thead class="bg-slate-50 dark:bg-slate-900/80">
                  <tr>
                    <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Customer</th>
                    <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Faktur / Order</th>
                    <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Qty Order</th>
                    <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">Picked</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-700 dark:bg-slate-800">
                  <tr v-if="loadingStores">
                    <td colspan="4" class="px-4 py-10 text-center text-slate-500 dark:text-slate-300">Memuat detail toko...</td>
                  </tr>
                  <tr v-else-if="!normalizedStores.length">
                    <td colspan="4" class="px-4 py-10 text-center text-slate-500 dark:text-slate-300">Klik produk untuk memuat detail toko.</td>
                  </tr>
                  <tr v-for="row in paginatedStores" v-else :key="row.row_key">
                    <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">{{ row.nama_customer || '-' }}</td>
                    <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">{{ row.order_label }}</td>
                    <td class="px-4 py-3 align-top text-slate-700 dark:text-slate-200">{{ row.order_qty_label }}</td>
                    <td class="px-4 py-3 align-top">
                      <input
                        type="number"
                        min="0"
                        :value="row.draft_picking"
                        class="w-28 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
                        @input="updateDraftPicking(row, $event.target.value)"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div v-if="normalizedStores.length > storePageSize" class="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
              <div>
                Menampilkan <span class="font-semibold text-slate-900 dark:text-white">{{ storeStartRow + 1 }}</span>-<span class="font-semibold text-slate-900 dark:text-white">{{ storeEndRow }}</span>
                dari <span class="font-semibold text-slate-900 dark:text-white">{{ normalizedStores.length }}</span> toko/order
              </div>
              <div class="flex items-center gap-2">
                <select v-model.number="storePageSize" class="rounded-xl border border-slate-200 bg-white px-2 py-1.5 text-sm outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white" @change="storePage = 1">
                  <option :value="10">10</option>
                  <option :value="15">15</option>
                  <option :value="25">25</option>
                  <option :value="50">50</option>
                </select>
                <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950" :disabled="storePage <= 1" @click="previousStorePage">Sebelumnya</button>
                <span>Hal {{ storePage }} / {{ storeTotalPages }}</span>
                <button class="rounded-xl border border-slate-200 bg-white px-3 py-1.5 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-950" :disabled="storePage >= storeTotalPages" @click="nextStorePage">Berikutnya</button>
              </div>
            </div>

            <button class="mt-4 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="savingProducts || loadingStores" @click="saveProductPicking">
              {{ savingProducts ? 'Menyimpan...' : 'Simpan Jumlah Picked' }}
            </button>
          </section>

          <section class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800/70">
            <h3 class="text-lg font-semibold text-slate-900 dark:text-white">Submit Final Picking</h3>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Setelah semua jumlah picked sesuai, submit final akan membuat status order naik ke flow faktur/shipping berikutnya.</p>
            <div class="mt-4 space-y-3">
              <AppFormField v-model="submitForm.picker" label="Nama picker" />
            </div>
            <button class="mt-4 rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60" :disabled="submittingPicking || loadingProducts" @click="handleSubmitPicking">
              {{ submittingPicking ? 'Submit...' : 'Submit Final Picking' }}
            </button>
          </section>
        </template>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-100">
          {{ feedback }}
        </div>
        <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-100">
          {{ errorMessage }}
        </div>
      </div>
    </AppModal>
  </div>
</template>
