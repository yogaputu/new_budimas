<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  confirmDepositStage,
  getDepositGroupDetail,
  getDepositGroups,
  retryFinanceJournalOutbox,
  saveCashierDeposit
} from '@/api/finance';
import { getBranches, getCompanies, getPlafons, getPrincipals, getSales } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getLoginSalesId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch, scopeSalesRowsByLogin, shouldLockToLoginSales } from '@/utils/accessScope';
import { addLocalDays, toLocalDateInputValue } from '@/utils/date';
import { FINANCE_DEPOSIT_STAGE_OPTIONS, resolveDepositStageLabelByCode } from '@/modules/finance/utils/statusLabels';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const numberFormatter = new Intl.NumberFormat('id-ID');
const today = new Date();
const defaultTo = toLocalDateInputValue(today);
const defaultFrom = toLocalDateInputValue(addLocalDays(today, -30));
const initialRouteLphId = Array.isArray(route.query.id_lph) ? route.query.id_lph[0] : route.query.id_lph;
const initialRouteType = Array.isArray(route.query.type) ? route.query.type[0] : route.query.type;
const initialDepositType = String(initialRouteType || '').toLowerCase() === 'noncash' ? 'noncash' : 'cash';

const filters = reactive({
  type: initialDepositType,
  stage: '',
  companyId: '',
  branchId: '',
  sales: '',
  // Payment Tagihan already scopes the hand-off by LPH.  Do not hide an
  // older eligible deposit behind the generic 30-day finalisation range.
  from: initialRouteLphId ? '' : defaultFrom,
  to: initialRouteLphId ? '' : defaultTo
});

const form = reactive({
  namaKasir: '',
  namaKonfirmasi: ''
});

const groupRows = ref([]);
const companyRows = ref([]);
const branchRows = ref([]);
const principalRows = ref([]);
const plafonRows = ref([]);
const salesRows = ref([]);
const detailInfo = ref(null);
const detailRows = ref([]);
const selectedGroupKey = ref('');
const selectedGroup = ref(null);
const detailOpen = ref(false);
const loading = reactive({
  sales: false,
  groups: false,
  detail: false,
  save: false,
  confirm: false
});
const feedback = ref('');
const errorMessage = ref('');
const successToast = ref('');
const errorToast = ref('');
const failedJournalDeliveries = ref([]);
const retryingJournalId = ref('');
let toastTimer = null;

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const fallbackSalesId = computed(() => getLoginSalesId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const shouldLockBusinessScope = computed(() => !canAccessAllBranches.value);
const canUseLoginScope = computed(() => shouldLockToLoginSales(authStore));
const selectedLphId = computed(() => {
  const rawValue = Array.isArray(route.query.id_lph) ? route.query.id_lph[0] : route.query.id_lph;
  return rawValue && String(rawValue).trim() ? String(rawValue).trim() : '';
});
const routeDepositType = computed(() => {
  const rawValue = Array.isArray(route.query.type) ? route.query.type[0] : route.query.type;
  return String(rawValue || '').toLowerCase() === 'noncash' ? 'noncash' : 'cash';
});

function applyLphRouteScope() {
  filters.type = routeDepositType.value;
  if (selectedLphId.value) {
    filters.from = '';
    filters.to = '';
  } else if (!filters.from && !filters.to) {
    filters.from = defaultFrom;
    filters.to = defaultTo;
  }
}

const depositTypeOptions = [
  { value: 'cash', label: 'Tunai' },
  { value: 'noncash', label: 'Non Tunai' }
];

const stageOptions = FINANCE_DEPOSIT_STAGE_OPTIONS;

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  const directCompanyId = getRowCompanyId(branch);
  if (directCompanyId) ids.add(String(directCompanyId));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() =>
  companyRows.value
    .filter((item) => companyIdsForBranch(filters.branchId).includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

function getSalesBranchKey(item) {
  return String(item.id_cabang || item.cabang_id || item.branch_id || item.id_cabang_sales || '');
}

function getSalesCompanyKey(item) {
  return String(item.id_perusahaan || item.company_id || item.perusahaan_id || item.id_company || '');
}

function getSalesPrincipalKeys(item) {
  return [
    item?.id_principal,
    item?.principal_id,
    item?.id_principal_sales,
    item?.principal_ids,
    item?.id_principal_list
  ]
    .flatMap((value) => String(value || '').split(','))
    .map((value) => value.trim())
    .filter(Boolean);
}

function getPlafonSalesKeys(item) {
  return [
    item?.id_sales,
    item?.id_user,
    item?.sales_id,
    item?.user_id
  ]
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map((value) => String(value));
}

function getPlafonBranchKey(item) {
  return String(item.id_cabang || item.cabang_id || item.branch_id || '');
}

function getPlafonCompanyKey(item) {
  return String(item.id_perusahaan || item.company_id || item.perusahaan_id || item.id_company || '');
}

function getPlafonPrincipalKey(item) {
  return String(item.id_principal || item.principal_id || '');
}

function getPrincipalCompanyKey(item) {
  return String(item?.id_perusahaan || item?.company_id || item?.perusahaan_id || item?.id_company || '');
}

function principalMatchesCompany(principalId, companyId) {
  if (!principalId || !companyId) return false;
  const principal = principalRows.value.find((item) => String(item.id) === String(principalId));
  return Boolean(principal && getPrincipalCompanyKey(principal) === String(companyId));
}

function salesMatchesCompany(item, companyId) {
  if (!companyId) return true;

  const rowCompanyId = getSalesCompanyKey(item);
  if (rowCompanyId) return rowCompanyId === String(companyId);

  if (getSalesPrincipalKeys(item).some((id) => principalMatchesCompany(id, companyId))) {
    return true;
  }

  const salesKeys = [
    item?.id_sales,
    item?.id_user,
    item?.id
  ]
    .filter((value) => value !== null && value !== undefined && value !== '')
    .map((value) => String(value));

  return plafonRows.value.some((plafon) => {
    if (filters.branchId && getPlafonBranchKey(plafon) !== String(filters.branchId)) return false;
    if (!getPlafonSalesKeys(plafon).some((key) => salesKeys.includes(key))) return false;

    const plafonCompanyId = getPlafonCompanyKey(plafon);
    if (plafonCompanyId) return plafonCompanyId === String(companyId);

    return principalMatchesCompany(getPlafonPrincipalKey(plafon), companyId);
  });
}

const salesOptions = computed(() =>
  scopeSalesRowsByLogin(salesRows.value, authStore)
    .filter((item) => !filters.branchId || getSalesBranchKey(item) === String(filters.branchId))
    .filter((item) => salesMatchesCompany(item, filters.companyId))
    .map((item) => ({
      value: String(item.id_sales || item.id),
      label: item.nama_sales || item.nama || 'Sales'
    }))
);

const summaryCards = computed(() => {
  const totalGroup = groupRows.value.length;
  const totalSetoran = groupRows.value.reduce((acc, item) => acc + Number(item.setoran_piutang || 0), 0);
  const readyCashier = groupRows.value.filter((item) => Number(item.status_code) === 1).length;
  const readyFinal = groupRows.value.filter((item) => Number(item.status_code) === 2).length;

  return [
    { label: 'Grup Setoran', value: String(totalGroup) },
    { label: 'Total Draft Setoran', value: formatCurrency(totalSetoran) },
    { label: 'Menunggu Proses Kasir', value: String(readyCashier) },
    { label: 'Siap Finalisasi Finance', value: String(readyFinal) }
  ];
});

const groupTableRows = computed(() =>
  groupRows.value.map((item, index) => ({
    ...item,
    row_key: buildGroupKey(item, index),
    tanggal_label: formatDate(item.draft_tanggal_input),
    setoran_piutang_label: formatCurrency(item.setoran_piutang),
    status_label: resolveStageLabel(item.status_code, item.status_setoran_label),
    penanggung_jawab_label: item.nama_pj || '-'
  }))
);

const detailTableRows = computed(() =>
  detailRows.value.map((item, index) => ({
    ...item,
    row_key: `${item.id_setoran || index}`,
    tagihan_label: formatCurrency(item.tagihan),
    setoran_label: formatCurrency(item.setoran),
    diterima_kasir_label: formatCurrency(item.setor_diterima_kasir),
    target_kasir_label: formatCurrency(item.diterima_target),
    biaya_lainnya_label: formatCurrency(item.biaya_lainnya),
    tahap_label: resolveStageLabel(item.status_setoran),
    status_pembayaran_label: String(item.status_pembayaran || '-').toUpperCase()
  }))
);

const selectedStageCode = computed(() => Number(selectedGroup.value?.status_code ?? -1));
const isCashType = computed(() => filters.type === 'cash');
// Status 1 only means the source was created by Rekap.  Receipt/transfer
// evidence must be recorded in Setoran Tunai or Setoran Non Tunai before this
// finalization screen can do anything with the group.
const needsDepositRecording = computed(() => Boolean(selectedGroup.value) && selectedStageCode.value < 2);
const canSaveCashier = computed(() => Boolean(selectedGroup.value) && detailRows.value.length > 0 && selectedStageCode.value === 2);
const canFinalize = computed(() => Boolean(selectedGroup.value) && detailRows.value.length > 0 && selectedStageCode.value === 2);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  return String(value).slice(0, 10);
}

function buildGroupKey(item) {
  return `${item.nama_pj || '-'}::${item.draft_tanggal_input || '-'}::${item.pj_setoran ?? '-'}::${item.id_sales ?? '-'}::${item.status_code ?? '-'}`;
}

function isSameGroupIdentity(left, right) {
  if (!left || !right) return false;

  return (
    String(left.nama_pj || '') === String(right.nama_pj || '') &&
    formatDate(left.draft_tanggal_input) === formatDate(right.draft_tanggal_input) &&
    String(left.pj_setoran || '') === String(right.pj_setoran || '') &&
    String(left.id_sales || '') === String(right.id_sales || '')
  );
}

function resolveStageLabel(value, fallback = '') {
  return resolveDepositStageLabelByCode(value, fallback);
}

function showToast(type, message) {
  if (toastTimer) clearTimeout(toastTimer);

  if (type === 'success') {
    successToast.value = message;
    errorToast.value = '';
  } else {
    errorToast.value = message;
    successToast.value = '';
  }

  toastTimer = setTimeout(() => {
    successToast.value = '';
    errorToast.value = '';
  }, 3500);
}

function getTargetDeltaMap() {
  const deltaMap = {};
  let hasDecrease = false;

  detailRows.value.forEach((item) => {
    const currentValue = Number(item.setor_diterima_kasir || 0);
    const targetValue = Number(item.diterima_target ?? currentValue);

    if (targetValue < currentValue) {
      hasDecrease = true;
      return;
    }

    const delta = targetValue - currentValue;
    if (delta > 0) {
      deltaMap[String(item.id_setoran)] = delta;
    }
  });

  return { deltaMap, hasDecrease };
}

function applySavedCashierTargets() {
  detailRows.value = detailRows.value.map((item) => ({
    ...item,
    setor_diterima_kasir: Number(item.diterima_target || 0),
    diterima_target: Number(item.diterima_target || 0)
  }));
}

function setTargetValue(index, event) {
  const nextValue = Number(event.target.value || 0);
  detailRows.value[index].diterima_target = nextValue < 0 ? 0 : nextValue;
}

function fillTargetFromDraft(index) {
  const row = detailRows.value[index];
  if (!row) return;
  row.diterima_target = Number(row.setoran || 0);
}

async function loadSalesOptions() {
  loading.sales = true;
  try {
    const [companyResponse, branchResponse, principalResponse, plafonResponse, salesResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getPrincipals(),
      getPlafons(),
      getSales()
    ]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    principalRows.value = normalizeList(unwrapResponse(principalResponse));
    plafonRows.value = normalizeList(unwrapResponse(plafonResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    if (shouldLockBusinessScope.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
    if (shouldLockBusinessScope.value && fallbackCompanyId.value) {
      filters.companyId = String(fallbackCompanyId.value);
    }
    if (canUseLoginScope.value && fallbackSalesId.value) {
      filters.sales = String(fallbackSalesId.value);
    }
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Master sales belum bisa dimuat.');
  } finally {
    loading.sales = false;
  }
}

async function loadGroups() {
  loading.groups = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getDepositGroups(filters.type, {
      periode_awal: filters.from,
      periode_akhir: filters.to,
      status: filters.stage || undefined,
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      sales: filters.sales || undefined,
      id_lph: selectedLphId.value || undefined,
      'no-paginate': 'true',
      field: 'draft_tanggal_input',
      order: 'desc'
    });

    const payload = unwrapResponse(response);
    groupRows.value = normalizeList(payload).map((item) => ({
      ...item,
      status_code: Number(
        item.status_code ??
          item.status ??
          item.status_setoran ??
          (() => {
            const label = String(item.status_setoran_label || '').toLowerCase();
            if (label.includes('admin')) return 0;
            if (label.includes('sales')) return 1;
            if (label.includes('kasir')) return 2;
            if (label.includes('audit')) return 3;
            return -1;
          })()
      )
    }));

    const matchedRow = groupRows.value.find((item) => buildGroupKey(item) === selectedGroupKey.value);
    if (matchedRow) {
      await selectGroup(matchedRow, detailOpen.value);
    } else {
      selectedGroupKey.value = '';
      selectedGroup.value = null;
      detailInfo.value = null;
      detailRows.value = [];
      detailOpen.value = false;
    }
  } catch (error) {
    const message = normalizeError(error, 'Daftar finalisasi setoran belum bisa dimuat.');
    errorMessage.value = message;
    showToast('error', message);
    groupRows.value = [];
  } finally {
    loading.groups = false;
  }
}

async function selectGroup(row, openModal = true) {
  if (!row) return;

  selectedGroup.value = row;
  selectedGroupKey.value = buildGroupKey(row);
  detailOpen.value = openModal;
  loading.detail = true;
  errorMessage.value = '';

  try {
    const response = await getDepositGroupDetail({
      tanggal: formatDate(row.draft_tanggal_input),
      id_sales: row.id_sales || undefined,
      nama_pj: row.nama_pj || undefined,
      pj_setoran: row.pj_setoran || undefined,
      status: row.status_code,
      id_lph: selectedLphId.value || undefined
    });

    const rawPayload = response?.data || {};
    detailInfo.value = rawPayload.informasi || rawPayload.detail_setoran || rawPayload.data?.detail_setoran || null;
    detailRows.value = normalizeList(rawPayload.data || rawPayload.list_setoran || rawPayload.data?.list_setoran).map((item) => ({
      ...item,
      diterima_target: Number(item.setor_diterima_kasir || 0)
    }));

    form.namaKasir = detailInfo.value?.nama_kasir || form.namaKasir;
    form.namaKonfirmasi = detailInfo.value?.nama_kasir || detailInfo.value?.nama_auditor || form.namaKonfirmasi;
  } catch (error) {
    const message = normalizeError(error, 'Detail setoran belum bisa dimuat.');
    errorMessage.value = message;
    showToast('error', message);
    detailInfo.value = null;
    detailRows.value = [];
  } finally {
    loading.detail = false;
  }
}

function closeDetailModal() {
  detailOpen.value = false;
}

async function saveCashierAmounts() {
  if (!selectedGroup.value) return;

  const { deltaMap, hasDecrease } = getTargetDeltaMap();
  if (hasDecrease) {
    const message = 'Nominal diterima kasir tidak bisa lebih kecil dari nominal yang sudah tersimpan.';
    errorMessage.value = message;
    showToast('error', message);
    return;
  }

  if (!Object.keys(deltaMap).length) {
    const message = 'Belum ada tambahan nominal diterima kasir yang perlu disimpan.';
    feedback.value = message;
    showToast('success', message);
    return;
  }

  loading.save = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await saveCashierDeposit({
      id_setoran: detailRows.value.map((item) => item.id_setoran),
      nama_kasir: form.namaKasir || form.namaKonfirmasi || '',
      diterima_kasir: deltaMap
    });

    applySavedCashierTargets();
    feedback.value = 'Nominal diterima kasir berhasil disimpan.';
    showToast('success', feedback.value);
  } catch (error) {
    const message = normalizeError(error, 'Simpan nominal diterima kasir gagal.');
    errorMessage.value = message;
    showToast('error', message);
  } finally {
    loading.save = false;
  }
}

function openDepositRecording() {
  router.push({
    name: isCashType.value ? 'finance-cash-deposits' : 'finance-noncash-deposits',
    query: { id_lph: selectedLphId.value || undefined }
  });
}

async function finalizeDeposit() {
  if (!selectedGroup.value) return;
  const previousGroup = { ...selectedGroup.value };
  if (!String(form.namaKonfirmasi || '').trim()) {
    const message = 'Isi nama petugas finalisasi terlebih dahulu.';
    errorMessage.value = message;
    showToast('error', message);
    return;
  }

  loading.confirm = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    // Cash and non-cash must use the same guarded stage-3 transition.  The
    // grouped cash endpoint is intentionally retired because it predates
    // Mobile Sales source binding, mutation allocation, and journal gates.
    const response = await confirmDepositStage({
      id_setoran: detailRows.value.map((item) => item.id_setoran),
      status_setoran: 3,
      nama_konfirmasi: String(form.namaKonfirmasi || '').trim(),
      id_lph: selectedLphId.value || undefined
    });
    const finalizationPayload = unwrapResponse(response) || {};

    failedJournalDeliveries.value = Array.isArray(finalizationPayload?.journal_delivery)
      ? finalizationPayload.journal_delivery.filter((item) => String(item?.status || '').toUpperCase() !== 'DELIVERED' && item?.id)
      : [];
    const journalBlocked = Boolean(finalizationPayload?.finalisasi_diblokir) || failedJournalDeliveries.value.length > 0;
    feedback.value = journalBlocked
      ? 'Setoran sudah mencapai finalisasi operasional, tetapi jurnalnya belum terkirim. Kirim ulang jurnal di bawah; jangan finalisasi setoran ini kembali.'
      : 'Setoran berhasil difinalkan ke finance. Tahap setoran sekarang masuk final dan sinkron ke status pembayaran.';
    showToast(journalBlocked ? 'error' : 'success', feedback.value);
    if (journalBlocked) {
      // Keep the detail modal open so Finance can retry the durable journal
      // event. The money transition already succeeded and must not be run a
      // second time just to repair the accounting delivery.
      await loadGroups();
      return;
    }
    selectedGroupKey.value = '';
    selectedGroup.value = null;
    detailInfo.value = null;
    detailRows.value = [];
    detailOpen.value = false;
    await loadGroups();

    const nextGroup =
      groupRows.value.find((item) => isSameGroupIdentity(item, previousGroup) && Number(item.status_code) === 3) ||
      groupRows.value.find((item) => isSameGroupIdentity(item, previousGroup));
    if (nextGroup) {
      await selectGroup(nextGroup);
    } else {
      selectedGroupKey.value = '';
      selectedGroup.value = null;
      detailInfo.value = null;
      detailRows.value = [];
      detailOpen.value = false;
    }
  } catch (error) {
    const message = normalizeError(error, 'Finalisasi setoran gagal diproses.');
    errorMessage.value = message;
    showToast('error', message);
  } finally {
    loading.confirm = false;
  }
}

async function retryFailedJournal(delivery) {
  const id = delivery?.id;
  if (!id) return;
  retryingJournalId.value = String(id);
  errorMessage.value = '';

  try {
    const response = await retryFinanceJournalOutbox(id);
    const payload = unwrapResponse(response) || {};
    const status = String(payload?.delivery?.status || payload?.data?.delivery?.status || '').toUpperCase();
    if (status && status !== 'DELIVERED') {
      throw new Error(payload?.message || 'Jurnal belum berhasil dikirim ulang.');
    }
    failedJournalDeliveries.value = failedJournalDeliveries.value.filter((item) => String(item?.id) !== String(id));
    const message = payload?.message || 'Jurnal berhasil dikirim ulang tanpa mengulang finalisasi setoran.';
    feedback.value = message;
    showToast('success', message);
    if (!failedJournalDeliveries.value.length) await loadGroups();
  } catch (error) {
    const message = normalizeError(error, 'Jurnal belum berhasil dikirim ulang. Finalisasi operasional tidak perlu diulang.');
    errorMessage.value = message;
    showToast('error', message);
  } finally {
    retryingJournalId.value = '';
  }
}

watch(
  () => filters.companyId,
  (value) => {
    if (value && filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(value))) {
      filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
    }
    if (filters.sales && !salesOptions.value.some((item) => item.value === String(filters.sales))) {
      filters.sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    }
  }
);

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') !== String(previousBranchId || '')) {
      filters.companyId = shouldLockBusinessScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '';
      filters.sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
      groupRows.value = [];
      detailRows.value = [];
      detailInfo.value = null;
      selectedGroup.value = null;
      selectedGroupKey.value = '';
      detailOpen.value = false;
    }
    if (filters.sales && !salesOptions.value.some((item) => item.value === String(filters.sales))) {
      filters.sales = canUseLoginScope.value && fallbackSalesId.value ? String(fallbackSalesId.value) : '';
    }
  }
);

watch(
  () => [filters.type, filters.stage],
  () => {
    selectedGroupKey.value = '';
    selectedGroup.value = null;
    detailInfo.value = null;
    detailRows.value = [];
    detailOpen.value = false;
  }
);

watch(
  () => [selectedLphId.value, routeDepositType.value],
  async () => {
    applyLphRouteScope();
    selectedGroupKey.value = '';
    selectedGroup.value = null;
    detailInfo.value = null;
    detailRows.value = [];
    detailOpen.value = false;
    await loadGroups();
  }
);

onMounted(async () => {
  applyLphRouteScope();
  await loadSalesOptions();
  await loadGroups();
});

onBeforeUnmount(() => {
  if (toastTimer) clearTimeout(toastTimer);
});
</script>

<template>
  <div class="space-y-6">
    <div v-if="successToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800 shadow-lg">
      {{ successToast }}
    </div>
    <div v-if="errorToast" class="fixed right-4 top-4 z-50 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-800 shadow-lg">
      {{ errorToast }}
    </div>

    <PageHeader
      title="Finalisasi Setoran"
      :description="selectedLphId
        ? 'Tahap terakhir finance untuk LPH terpilih. Hanya setoran dengan faktur yang ada pada LPH ini yang ditampilkan.'
        : 'Tahap terakhir finance setelah setoran tunai atau transfer sudah dicatat dan diterima. Grup yang masih menunggu pencatatan harus diselesaikan dari menu Setoran terlebih dahulu.'"
    />

    <section class="panel p-5">
      <div class="grid min-w-0 gap-4 [grid-template-columns:repeat(auto-fit,minmax(210px,1fr))]">
        <AppSearchSelect v-model="filters.type" label="Tipe Setoran" placeholder="Pilih tipe" :options="depositTypeOptions" />
        <AppSearchSelect v-model="filters.stage" label="Tahap" placeholder="Pilih tahap" :options="stageOptions" />
        <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="shouldLockBusinessScope && !!fallbackBranchId" empty-text="Cabang belum tersedia." />
        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" :disabled="!filters.branchId || (shouldLockBusinessScope && !!fallbackCompanyId)" empty-text="Pilih cabang terlebih dahulu." />
        <AppSearchSelect v-model="filters.sales" label="Sales" placeholder="Semua sales" :options="salesOptions" :disabled="canUseLoginScope && !!fallbackSalesId" empty-text="Sales belum tersedia." />
        <AppFormField v-model="filters.from" label="Dari Tanggal" type="date" />
        <AppFormField v-model="filters.to" label="Sampai Tanggal" type="date" />
        <button class="self-end rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="loadGroups">
          Muat Setoran
        </button>
      </div>

      <section class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
        <p v-if="selectedLphId" class="mb-1 font-semibold text-brand-700">Scope LPH #{{ selectedLphId }} aktif. Setoran dari LPH lain tidak dapat dipilih atau difinalkan dari halaman ini.</p>
        <p>Alur operasional: <span class="font-semibold text-slate-900">Pembayaran Customer -> Draft Rekap -> Catat/Terima Setoran Tunai atau Non Tunai -> Pembayaran Tagihan -> Finalisasi</span>.</p>
        <p class="mt-1">Nominal <span class="font-semibold text-slate-900">Diterima Kasir</span> di halaman ini dianggap target final yang diterima kasir. Jika Anda edit lalu simpan ulang, sistem hanya menambahkan selisih yang belum tersimpan.</p>
        <p class="mt-1">Untuk setoran <span class="font-semibold text-slate-900">Non Tunai</span>, pencatatan bukti transfer atau mutasi wajib dilakukan di menu Setoran Non Tunai; halaman ini tidak dapat menaikkan setoran yang belum dicatat.</p>
      </section>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="item in summaryCards" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ errorMessage }}</section>

    <section class="min-w-0">
      <div class="mb-3">
        <h3 class="text-lg font-semibold text-slate-900">Grup Setoran</h3>
        <p class="text-sm text-slate-500">Klik satu grup untuk membuka detail faktur dan status kasirnya.</p>
      </div>

      <AppTable
        :rows="groupTableRows"
        :columns="[
          { key: 'tanggal_label', label: 'Tanggal Input' },
          { key: 'penanggung_jawab_label', label: 'Penanggung Jawab' },
          { key: 'setoran_piutang_label', label: 'Total Setoran' },
          { key: 'status_label', label: 'Tahap Setoran' }
        ]"
        :loading="loading.groups"
        :clickable-rows="true"
        row-key="row_key"
        :selected-key="selectedGroupKey"
        empty-message="Belum ada grup setoran pada filter ini."
        @row-click="selectGroup"
      />
    </section>

    <AppModal
      :open="detailOpen"
      :title="selectedGroup ? 'Detail Finalisasi Setoran' : 'Detail Finalisasi'"
      :description="selectedGroup ? `${selectedGroup.nama_pj || '-'} | ${formatDate(selectedGroup.draft_tanggal_input)}` : 'Detail faktur dan status kasir.'"
      size="7xl"
      @close="closeDetailModal"
    >
      <div class="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Detail Finalisasi</h3>
          <p class="text-sm text-slate-500">Baris setoran di bawah dipakai untuk cek faktur, nominal setor, dan target diterima kasir.</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
            :disabled="loading.save || !canSaveCashier"
            @click="saveCashierAmounts"
          >
            {{ loading.save ? 'Menyimpan...' : 'Simpan Nominal Kasir' }}
          </button>
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            :disabled="loading.confirm || !canFinalize"
            @click="finalizeDeposit"
          >
            {{ loading.confirm && canFinalize ? 'Memfinalisasi...' : 'Finalkan Setoran' }}
          </button>
        </div>
      </div>

      <div v-if="needsDepositRecording" class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <span>Setoran ini masih menunggu pencatatan atau penerimaan. Finalisasi dikunci sampai setoran dilengkapi di menu {{ isCashType ? 'Setoran Tunai' : 'Setoran Non Tunai' }}.</span>
        <button class="rounded-xl border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-900 hover:bg-amber-100" @click="openDepositRecording">
          Buka {{ isCashType ? 'Setoran Tunai' : 'Setoran Non Tunai' }}
        </button>
      </div>

      <div v-if="failedJournalDeliveries.length" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-950">
        <p class="font-semibold">Jurnal finalisasi belum terkirim</p>
        <p class="mt-1">Finalisasi setoran sudah tersimpan. Jangan jalankan finalisasi ulang; kirim ulang hanya event jurnal yang gagal berikut.</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            v-for="delivery in failedJournalDeliveries"
            :key="delivery.id"
            class="rounded-xl border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-800 hover:bg-rose-100 disabled:opacity-60"
            :disabled="Boolean(retryingJournalId)"
            @click="retryFailedJournal(delivery)"
          >
            {{ String(retryingJournalId) === String(delivery.id) ? 'Mengirim ulang...' : `Kirim ulang jurnal #${delivery.id}` }}
          </button>
        </div>
      </div>

      <div v-if="selectedGroup" class="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Tahap Grup</p>
          <p class="mt-3 text-base font-semibold text-slate-900">{{ resolveStageLabel(selectedGroup.status_code, selectedGroup.status_setoran_label) }}</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Tanggal Input</p>
          <p class="mt-3 text-base font-semibold text-slate-900">{{ formatDate(selectedGroup.draft_tanggal_input) }}</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Nama PJ</p>
          <p class="mt-3 text-base font-semibold text-slate-900">{{ selectedGroup.nama_pj || '-' }}</p>
        </article>
        <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Draft</p>
          <p class="mt-3 text-base font-semibold text-slate-900">{{ formatCurrency(selectedGroup.setoran_piutang) }}</p>
        </article>
      </div>

      <div v-if="selectedGroup" class="mt-4 grid gap-4 xl:grid-cols-[1fr_1fr]">
        <AppFormField v-model="form.namaKasir" label="Nama Kasir" placeholder="Petugas penerima kasir" />
        <AppFormField v-model="form.namaKonfirmasi" label="Nama Konfirmasi / Auditor" placeholder="Nama petugas finalisasi" />
      </div>

      <section v-if="detailInfo" class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
        <p>Jumlah customer: <span class="font-semibold text-slate-900">{{ detailInfo.jumlah_customer || 0 }}</span></p>
        <p class="mt-1">Total setoran grup: <span class="font-semibold text-slate-900">{{ formatCurrency(detailInfo.total_setoran) }}</span></p>
        <p class="mt-1">Kasir terakhir: <span class="font-semibold text-slate-900">{{ detailInfo.nama_kasir || '-' }}</span></p>
        <p class="mt-1">Auditor terakhir: <span class="font-semibold text-slate-900">{{ detailInfo.nama_auditor || '-' }}</span></p>
      </section>

      <div class="mt-4 overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50">
            <tr>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">No Faktur</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Customer</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tagihan</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Draft Setor</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Diterima Kasir</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Target Baru</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Tahap</th>
              <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-if="loading.detail">
              <td colspan="8" class="px-4 py-10 text-center text-slate-500">Memuat detail setoran...</td>
            </tr>
            <tr v-else-if="!detailRows.length">
              <td colspan="8" class="px-4 py-10 text-center text-slate-500">Detail setoran belum tersedia.</td>
            </tr>
            <tr v-for="(row, index) in detailTableRows" v-else :key="row.row_key">
              <td class="px-4 py-3 text-slate-700">{{ row.no_faktur || '-' }}</td>
              <td class="px-4 py-3 text-slate-700">{{ row.nama_customer || '-' }}</td>
              <td class="px-4 py-3 text-slate-700">{{ row.tagihan_label }}</td>
              <td class="px-4 py-3 text-slate-700">{{ row.setoran_label }}</td>
              <td class="px-4 py-3 text-slate-700">{{ row.diterima_kasir_label }}</td>
              <td class="px-4 py-3">
                <input
                  :value="row.diterima_target"
                  type="number"
                  min="0"
                  :disabled="!canSaveCashier"
                  class="w-full rounded-xl border border-slate-200 px-3 py-2 text-sm outline-none transition focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                  @input="setTargetValue(index, $event)"
                />
              </td>
              <td class="px-4 py-3 text-slate-700">{{ row.tahap_label }}</td>
              <td class="px-4 py-3">
                <button class="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50" :disabled="!canSaveCashier" @click="fillTargetFromDraft(index)">
                  Pakai Draft
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </AppModal>
  </div>
</template>
