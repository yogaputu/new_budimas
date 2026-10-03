<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import {
  getCompanyBankAccounts,
  getCreditNoteCandidates,
  getCreditNoteDetail,
  getCreditNoteList,
  issueCreditNoteFromQcReturn,
  refundCreditNote
} from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const authStore = useAuthStore();
const route = useRoute();
const numberFormatter = new Intl.NumberFormat('id-ID');

const filters = reactive({
  search: '',
  branchId: '',
  companyId: '',
  principalId: '',
  status: ''
});

const loading = reactive({
  refs: false,
  list: false,
  detail: false,
  accounts: false,
  refund: false,
  candidates: false,
  issue: false
});

const rows = ref([]);
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const accounts = ref([]);
const pageError = ref('');
const feedback = ref('');
const selectedRow = ref(null);
const detailOpen = ref(false);
const detailHeader = ref(null);
const detailRows = ref([]);
const candidates = ref([]);
const candidateError = ref('');
const candidateOpen = ref(false);
const selectedCandidate = ref(null);
const issueConfirmation = ref('');
const refundOpen = ref(false);
const refundError = ref('');
const refundForm = reactive({
  tanggal_refund: localDateInput(),
  nominal_refund: '',
  metode_refund: 'bank',
  id_rekening_perusahaan: '',
  catatan_refund: '',
  confirm_potong_tagihan: ''
});

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: '0', label: 'Pending' },
  { value: '3', label: 'Realisasi' },
  { value: '1', label: 'Potong Tagihan' },
  { value: '9', label: 'Batal' }
];

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));
const fallbackCompanyId = computed(() => getLoginCompanyId(authStore.user));
const canAccessAllBranches = computed(() => isSuperUser(authStore));
const canUseLoginScope = computed(() => !canAccessAllBranches.value);

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branches.value, authStore)
    .filter((item) => !filters.companyId || branchMatchesCompany(item, filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || `Cabang ${item.id}`}`
    }))
);

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  const branch = branches.value.find((item) => String(item.id) === String(branchId));
  getRowCompanyIds(branch).forEach((id) => ids.add(String(id)));
  if (fallbackCompanyId.value) ids.add(String(fallbackCompanyId.value));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).some((id) => String(id) === String(branchId))) {
      ids.add(String(item.id));
    }
  });

  return [...ids];
}

const companyOptions = computed(() =>
  companies.value
    .filter((item) => {
      if (canAccessAllBranches.value) return true;
      const scopedCompanyIds = new Set(
        scopeRowsByLoginBranch(branches.value, authStore)
          .flatMap((branch) => getRowCompanyIds(branch).map(String))
          .filter(Boolean)
      );
      return scopedCompanyIds.has(String(item.id)) || String(item.id) === String(fallbackCompanyId.value || '');
    })
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => !filters.companyId || String(item.id_perusahaan || item.company_id || '') === String(filters.companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_principal || 'Principal'}`
    }))
);

const accountOptions = computed(() =>
  accounts.value
    .filter((item) => item.is_aktif === undefined || item.is_aktif === true || item.is_aktif === 'true' || Number(item.is_aktif) === 1)
    .map((item) => ({
      value: String(item.id_rekening_perusahaan || item.id),
      label: `${item.nama_bank || 'Kas/Bank'} - ${item.nomor_rekening || '-'} (${item.nama_pemilik || '-'})`
    }))
);

const summary = computed(() => {
  const openRows = rows.value.filter((item) => resolveStatusValue(item) === 0);
  const realizedRows = rows.value.filter((item) => resolveStatusValue(item) === 3);
  const usedRows = rows.value.filter((item) => resolveStatusValue(item) === 1);
  const canceledRows = rows.value.filter((item) => resolveStatusValue(item) === 9);

  return {
    total: rows.value.length,
    open: openRows.length,
    realized: realizedRows.length,
    used: usedRows.length,
    canceled: canceledRows.length,
    totalNominal: rows.value.reduce((acc, item) => acc + Number(item.total_cn || 0), 0),
    openNominal: openRows.reduce((acc, item) => acc + Number(item.total_cn || 0), 0),
    usedNominal: usedRows.reduce((acc, item) => acc + Number(item.nominal_refund || item.total_cn || 0), 0)
  };
});

const columns = [
  { key: 'kode_cn', label: 'Kode CN' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'tanggal_label', label: 'Tanggal', render: (row) => formatDate(row.tanggal) },
  { key: 'total_cn_label', label: 'Nominal', render: (row) => formatCurrency(row.total_cn) },
  {
    key: 'status_label',
    label: 'Status',
    render: (row) => ({
      text: resolveStatusLabel(row),
      className:
        resolveStatusValue(row) === 1
          ? 'inline-flex min-w-[112px] justify-center rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-800 ring-1 ring-sky-200 dark:bg-sky-300 dark:text-slate-950 dark:ring-sky-200'
          : resolveStatusValue(row) === 9
            ? 'inline-flex min-w-[78px] justify-center rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-800 ring-1 ring-rose-200 dark:bg-rose-300 dark:text-slate-950 dark:ring-rose-200'
            : resolveStatusValue(row) === 3
              ? 'inline-flex min-w-[86px] justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200 dark:bg-emerald-300 dark:text-slate-950 dark:ring-emerald-200'
              : 'inline-flex min-w-[78px] justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 ring-1 ring-amber-200 dark:bg-amber-200 dark:text-slate-950 dark:ring-amber-100'
    })
  },
  { key: 'no_faktur_digunakan', label: 'Faktur Pakai' },
  { key: 'kode_refund', label: 'Transaksi Potong' }
];

const candidateColumns = [
  { key: 'kode_request', label: 'Kode Retur' },
  { key: 'no_faktur', label: 'Faktur' },
  { key: 'nama_customer', label: 'Customer' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'qty_qc_label', label: 'QC Diterima', render: (row) => `${Number(row.qty_qc_pcs || 0).toLocaleString('id-ID')} PCS` },
  { key: 'total_cn_candidate_label', label: 'Estimasi CN (Total)', render: (row) => formatCurrency(row.total_cn_candidate) },
  {
    key: 'issue_status_label',
    label: 'Status',
    render: (row) => ({
      text: row.issueable ? 'Siap diterbitkan' : 'Perlu perbaikan data',
      className: row.issueable
        ? 'inline-flex min-w-[132px] justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-200 dark:bg-emerald-300 dark:text-slate-950 dark:ring-emerald-200'
        : 'inline-flex min-w-[152px] justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800 ring-1 ring-amber-200 dark:bg-amber-200 dark:text-slate-950 dark:ring-amber-100'
    })
  }
];

watch(
  () => filters.branchId,
  (branchId, previousBranchId) => {
    if (String(branchId || '') === String(previousBranchId || '')) return;
    if (branchId && filters.companyId && !companyIdsForBranch(branchId).includes(String(filters.companyId))) {
      filters.branchId = '';
    }
    filters.principalId = '';
  }
);

watch(
  () => filters.companyId,
  (companyId) => {
    if (companyId && filters.branchId && !companyIdsForBranch(filters.branchId).includes(String(companyId))) {
      filters.branchId = '';
    }
    filters.principalId = '';
  }
);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function localDateInput(date = new Date()) {
  const value = date instanceof Date ? date : new Date(date);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, '0');
  const day = String(value.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function formatDate(value) {
  if (!value) return '-';
  const text = String(value);
  const localDateMatch = text.match(/\d{4}-\d{2}-\d{2}/);
  if (localDateMatch) {
    const [year, month, day] = localDateMatch[0].split('-').map(Number);
    return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(year, month - 1, day));
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  return date.toLocaleDateString('id-ID', { day: '2-digit', month: 'short', year: 'numeric' });
}

function resolveStatusValue(value) {
  const row = value && typeof value === 'object' ? value : null;
  if (
    row &&
    (
      Number(row.status_cn) === 1 ||
      row.id_mutasi_acc ||
      row.kode_refund ||
      row.tanggal_refund ||
      Number(row.nominal_refund || 0) > 0
    )
  ) {
    return 1;
  }

  const status = Number(row ? row.status_cn : value);
  if (status === 1) return 1;
  if ([2, 9].includes(status)) return 9;
  if (status === 3) return 3;
  return 0;
}

function resolveStatusLabel(value) {
  const status = resolveStatusValue(value);
  if (status === 1) return 'Potong Tagihan';
  if (status === 9) return 'Batal';
  if (status === 3) return 'Realisasi';
  return 'Pending';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function printCreditNote() {
  const header = detailHeader.value || selectedRow.value;
  if (!header) return;

  const detailHtml = detailRows.value.map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${escapeHtml(item.kode_sku || '-')}<br><strong>${escapeHtml(item.nama_produk || '-')}</strong></td>
      <td>${Number(item.karton_retur || 0)} karton, ${Number(item.box_retur || 0)} box, ${Number(item.pieces_retur || 0)} pcs</td>
      <td class="right">${formatCurrency(item.subtotal_retur || item.subtotal)}</td>
      <td class="right">${formatCurrency(item.nominal_cn)}</td>
      <td>${escapeHtml(item.alasan_retur || '-')}</td>
    </tr>
  `).join('');

  const win = window.open('', '_blank', 'width=1120,height=820');
  if (!win) return;

  win.document.write(`
    <html>
      <head>
        <title>${escapeHtml(header.kode_cn || 'Credit Note')}</title>
        <style>
          * { box-sizing: border-box; }
          body { font-family: Arial, sans-serif; margin: 28px; color: #0f172a; }
          h1 { margin: 0; font-size: 22px; text-transform: uppercase; letter-spacing: .08em; }
          .header { display: flex; justify-content: space-between; gap: 24px; border-bottom: 2px solid #0f172a; padding-bottom: 16px; }
          .muted { color: #64748b; font-size: 12px; }
          .grid { margin-top: 18px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
          .card { border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px; }
          .label { color: #64748b; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
          .value { margin-top: 5px; font-weight: 700; }
          table { width: 100%; border-collapse: collapse; margin-top: 18px; font-size: 12px; }
          th, td { border: 1px solid #cbd5e1; padding: 8px; vertical-align: top; }
          th { background: #f1f5f9; text-align: left; text-transform: uppercase; font-size: 11px; }
          .right { text-align: right; }
          .signature { margin-top: 42px; display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; text-align: center; font-size: 12px; }
          .line { margin-top: 58px; border-top: 1px solid #0f172a; padding-top: 8px; }
          @media print { body { margin: 16mm; } }
        </style>
      </head>
      <body>
        <div class="header">
          <div>
            <h1>Credit Note</h1>
            <p class="muted">${escapeHtml(header.nama_principal || '')}</p>
          </div>
          <div class="right">
            <strong>${escapeHtml(header.kode_cn || '-')}</strong><br>
            <span class="muted">${formatDate(header.tanggal)}</span>
          </div>
        </div>
        <section class="grid">
          <div class="card"><div class="label">Customer</div><div class="value">${escapeHtml(header.nama_customer || '-')}</div></div>
          <div class="card"><div class="label">Status</div><div class="value">${escapeHtml(resolveStatusLabel(header))}</div></div>
          <div class="card"><div class="label">Kode Retur</div><div class="value">${escapeHtml(header.kode_request || '-')}</div></div>
          <div class="card"><div class="label">Nominal CN</div><div class="value">${formatCurrency(header.total_cn)}</div></div>
        </section>
        <table>
          <thead>
            <tr><th>No</th><th>Produk</th><th>Qty Retur</th><th>Subtotal</th><th>Nominal CN</th><th>Alasan</th></tr>
          </thead>
          <tbody>${detailHtml || '<tr><td colspan="6">Detail produk belum tersedia.</td></tr>'}</tbody>
        </table>
        <section class="signature">
          ${['Admin Retur', 'Finance', 'Supervisor', 'Customer'].map((label) => `<div><div class="line">${label}</div></div>`).join('')}
        </section>
      </body>
    </html>
  `);
  win.document.close();
  win.focus();
  win.print();
}

function resolveRows(response) {
  return normalizeList(unwrapResponse(response));
}

function firstFilledValue(values = []) {
  return values.find((value) => value !== undefined && value !== null && value !== '');
}

function resolveCompanyId(row = {}) {
  const principalId = firstFilledValue([row?.id_principal, detailHeader.value?.id_principal, selectedRow.value?.id_principal]);
  const principal = principals.value.find((item) => String(item.id) === String(principalId || ''));

  return firstFilledValue([
    row?.id_perusahaan,
    detailHeader.value?.id_perusahaan,
    selectedRow.value?.id_perusahaan,
    filters.companyId,
    principal?.id_perusahaan,
    principal?.company_id
  ]);
}

function resolveBranchId(row = {}) {
  return firstFilledValue([
    row?.id_cabang,
    detailHeader.value?.id_cabang,
    selectedRow.value?.id_cabang,
    filters.branchId
  ]);
}

function uniqueAccounts(list = []) {
  const seen = new Set();
  return list.filter((item) => {
    const id = item?.id_rekening_perusahaan || item?.id;
    if (!id || seen.has(String(id))) return false;
    seen.add(String(id));
    return true;
  });
}

async function loadReferences() {
  loading.refs = true;
  try {
    const [branchResponse, companyResponse, principalResponse] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals()
    ]);

    branches.value = normalizeList(unwrapResponse(branchResponse));
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    if (canUseLoginScope.value && fallbackBranchId.value) {
      filters.branchId = String(fallbackBranchId.value);
    }
    if (canUseLoginScope.value && fallbackCompanyId.value) {
      filters.companyId = String(fallbackCompanyId.value);
    }
  } catch (error) {
    pageError.value = normalizeError(error, 'Referensi filter Credit Note belum bisa dimuat.');
  } finally {
    loading.refs = false;
  }
}

async function loadRows() {
  loading.list = true;
  pageError.value = '';
  try {
    const response = await getCreditNoteList({
      search: filters.search || undefined,
      id_cabang: filters.branchId || undefined,
      id_perusahaan: filters.companyId || undefined,
      id_principal: filters.principalId || undefined,
      status_cn: filters.status === '' ? undefined : filters.status
    });

    rows.value = resolveRows(response);
  } catch (error) {
    rows.value = [];
    pageError.value = normalizeError(error, 'Daftar Credit Note belum bisa dimuat.');
  } finally {
    loading.list = false;
  }
}

function currentFilterParams() {
  return {
    search: filters.search || undefined,
    id_cabang: filters.branchId || undefined,
    id_perusahaan: filters.companyId || undefined,
    id_principal: filters.principalId || undefined
  };
}

async function loadCandidates() {
  loading.candidates = true;
  candidateError.value = '';
  try {
    const response = await getCreditNoteCandidates(currentFilterParams());
    candidates.value = resolveRows(response);
  } catch (error) {
    candidates.value = [];
    candidateError.value = normalizeError(error, 'Kandidat retur QC untuk Credit Note belum bisa dimuat.');
  } finally {
    loading.candidates = false;
  }
}

async function reloadCreditNoteData() {
  await Promise.all([loadRows(), loadCandidates()]);
}

function openCandidate(candidate) {
  selectedCandidate.value = candidate;
  issueConfirmation.value = '';
  candidateOpen.value = true;
}

async function issueCandidate() {
  const candidate = selectedCandidate.value;
  if (!candidate?.id_request || !candidate.issueable) return;
  if (String(issueConfirmation.value || '').trim().toUpperCase() !== 'TERBITKAN CN') return;

  loading.issue = true;
  candidateError.value = '';
  try {
    const response = await issueCreditNoteFromQcReturn(candidate.id_request, {
      confirm_issue: issueConfirmation.value
    });
    const payload = unwrapResponse(response);
    const issued = payload?.data || payload;
    feedback.value = `Credit Note ${issued?.kode_cn || ''} berhasil diterbitkan dari retur ${candidate.kode_request || ''}.`;
    candidateOpen.value = false;
    selectedCandidate.value = null;
    await reloadCreditNoteData();
    const issuedRow = rows.value.find((item) => String(item.id_cn) === String(issued?.id_cn));
    if (issuedRow) await openDetail(issuedRow);
  } catch (error) {
    candidateError.value = normalizeError(error, 'Credit Note dari hasil QC retur belum berhasil diterbitkan.');
  } finally {
    loading.issue = false;
  }
}

async function loadAccountsForCreditNote(row = detailHeader.value || selectedRow.value) {
  accounts.value = [];
  refundForm.id_rekening_perusahaan = '';
  const companyId = resolveCompanyId(row);
  const branchId = resolveBranchId(row);
  const attempts = [];

  if (companyId) {
    attempts.push({
      clause: JSON.stringify({ id_perusahaan: `=${Number(companyId)}` })
    });
  }

  if (branchId) {
    attempts.push({
      clause: JSON.stringify({ id_cabang: `=${Number(branchId)}` })
    });
  }

  attempts.push({
    clause: JSON.stringify({ is_aktif: '=true' })
  });
  attempts.push({});

  loading.accounts = true;
  try {
    for (const params of attempts) {
      const response = await getCompanyBankAccounts(params);
      const list = uniqueAccounts(normalizeList(unwrapResponse(response)));
      if (list.length) {
        accounts.value = list;
        break;
      }
    }
  } catch (error) {
    refundError.value = normalizeError(error, 'Daftar rekening kas/bank belum bisa dimuat.');
  } finally {
    loading.accounts = false;
  }
}

async function openDetail(row) {
  selectedRow.value = row;
  detailOpen.value = true;
  detailHeader.value = null;
  detailRows.value = [];
  loading.detail = true;

  try {
    const response = await getCreditNoteDetail(row.id_cn);
    const payload = unwrapResponse(response);
    detailHeader.value = payload?.header || null;
    detailRows.value = normalizeList(payload?.details);
  } catch (error) {
    pageError.value = normalizeError(error, 'Detail Credit Note belum bisa dimuat.');
  } finally {
    loading.detail = false;
  }
}

async function openRefundModal(row = detailHeader.value || selectedRow.value) {
  if (!row || ![0, 3].includes(resolveStatusValue(row))) return;
  refundError.value = '';
  refundForm.tanggal_refund = localDateInput();
  refundForm.nominal_refund = String(row.total_cn || '');
  refundForm.metode_refund = 'bank';
  refundForm.id_rekening_perusahaan = '';
  refundForm.catatan_refund = '';
  refundForm.confirm_potong_tagihan = '';
  refundOpen.value = true;
  await loadAccountsForCreditNote(row);
}

async function submitRefund() {
  refundError.value = '';
  if (!selectedRow.value?.id_cn && !detailHeader.value?.id_cn) {
    refundError.value = 'Credit Note belum dipilih.';
    return;
  }
  if (!refundForm.id_rekening_perusahaan) {
    refundError.value = 'Pilih rekening kas/bank untuk potong tagihan.';
    return;
  }
  if (!Number(refundForm.nominal_refund || 0)) {
    refundError.value = 'Nominal potong tagihan wajib diisi.';
    return;
  }
  if (String(refundForm.confirm_potong_tagihan || '').trim().toUpperCase() !== 'POTONG TAGIHAN') {
    refundError.value = 'Ketik POTONG TAGIHAN untuk mengunci CN.';
    return;
  }

  loading.refund = true;
  try {
    const idCn = detailHeader.value?.id_cn || selectedRow.value.id_cn;
    await refundCreditNote(idCn, {
      tanggal_refund: refundForm.tanggal_refund,
      nominal_refund: Number(refundForm.nominal_refund || 0),
      metode_refund: refundForm.metode_refund,
      id_rekening_perusahaan: refundForm.id_rekening_perusahaan,
      catatan_refund: refundForm.catatan_refund,
      confirm_potong_tagihan: refundForm.confirm_potong_tagihan
    });

    feedback.value = `Credit Note ${detailHeader.value?.kode_cn || selectedRow.value?.kode_cn || ''} berhasil diproses potong tagihan.`;
    refundOpen.value = false;
    await loadRows();
    const currentId = idCn;
    const updatedRow = rows.value.find((item) => String(item.id_cn) === String(currentId));
    if (updatedRow) {
      await openDetail(updatedRow);
    } else {
      detailOpen.value = false;
    }
  } catch (error) {
    refundError.value = normalizeError(error, 'Potong tagihan Credit Note belum berhasil diproses.');
  } finally {
    loading.refund = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    search: '',
    branchId: canUseLoginScope.value && fallbackBranchId.value ? String(fallbackBranchId.value) : '',
    companyId: canUseLoginScope.value && fallbackCompanyId.value ? String(fallbackCompanyId.value) : '',
    principalId: '',
    status: ''
  });
  reloadCreditNoteData();
}

onMounted(async () => {
  if (route.query.search) {
    filters.search = String(route.query.search);
  }
  await loadReferences();
  await reloadCreditNoteData();
});
</script>

<template>
  <section>
    <PageHeader
      title="Credit Note"
      description="Terbitkan Credit Note dari retur sales yang QC Gudangnya sudah selesai, lalu pantau pemakaiannya ke tagihan."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700" @click="reloadCreditNoteData">
        Reload
      </button>
    </PageHeader>

    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-7">
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Total CN</p>
        <p class="mt-3 text-2xl font-bold text-slate-950 dark:text-white">{{ summary.total }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Pending</p>
        <p class="mt-3 text-2xl font-bold text-emerald-600">{{ summary.open }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Potong Tagihan</p>
        <p class="mt-3 text-2xl font-bold text-slate-700 dark:text-slate-200">{{ summary.used }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Realisasi</p>
        <p class="mt-3 text-2xl font-bold text-emerald-600">{{ summary.realized }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Batal</p>
        <p class="mt-3 text-2xl font-bold text-amber-600">{{ summary.canceled }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Nominal Pending</p>
        <p class="mt-3 text-xl font-bold text-emerald-600">{{ formatCurrency(summary.openNominal) }}</p>
      </div>
      <div class="panel p-5">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Total Nominal</p>
        <p class="mt-3 text-xl font-bold text-slate-950 dark:text-white">{{ formatCurrency(summary.totalNominal) }}</p>
      </div>
    </div>

    <div class="panel mt-5 p-5">
      <div class="grid gap-4 lg:grid-cols-6">
        <label class="block lg:col-span-2">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Cari Credit Note</span>
          <input
            v-model="filters.search"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            placeholder="Kode CN, customer, faktur, atau retur"
            @keyup.enter="reloadCreditNoteData"
          />
        </label>

        <AppSearchSelect v-model="filters.companyId" label="Perusahaan" :options="companyOptions" :disabled="canUseLoginScope && !!fallbackCompanyId" placeholder="Semua perusahaan" />
        <AppSearchSelect v-model="filters.branchId" label="Cabang" :options="branchOptions" :disabled="!filters.companyId || (!canAccessAllBranches && !!fallbackBranchId)" placeholder="Semua cabang" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.principalId" label="Principal" :options="principalOptions" placeholder="Semua principal" />

        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Status</span>
          <select
            v-model="filters.status"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          >
            <option v-for="option in statusOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
      </div>

      <div class="mt-4 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" :disabled="loading.list || loading.candidates" @click="reloadCreditNoteData">
          {{ loading.list || loading.candidates ? 'Memuat...' : 'Terapkan Filter' }}
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="resetFilters">
          Reset
        </button>
      </div>
    </div>

    <p v-if="pageError" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ pageError }}
    </p>
    <p v-if="feedback" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </p>

    <section class="panel mt-5 p-5">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-sky-600 dark:text-sky-300">Tahap Finance</p>
          <h2 class="mt-1 text-lg font-semibold text-slate-950 dark:text-white">Retur QC Selesai — Menunggu Credit Note</h2>
          <p class="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
            Pilih retur sales yang sudah selesai QC untuk meninjau kuantitas GOOD/BAD dan menerbitkan satu Credit Note.
            Retur Canvas tidak ditampilkan karena pengembaliannya hanya memulihkan stok Canvas ke gudang dan tidak memiliki faktur customer.
          </p>
        </div>
        <button
          class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
          :disabled="loading.candidates"
          @click="loadCandidates"
        >
          {{ loading.candidates ? 'Memuat...' : 'Muat Kandidat QC' }}
        </button>
      </div>

      <p v-if="candidateError" class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100">
        {{ candidateError }}
      </p>

      <div class="mt-4">
        <AppTable
          :rows="candidates"
          :columns="candidateColumns"
          :loading="loading.candidates"
          row-key="id_request"
          :selected-key="selectedCandidate?.id_request"
          clickable-rows
          empty-message="Belum ada retur sales yang QC Gudangnya selesai pada filter ini."
          @row-click="openCandidate"
        />
      </div>
      <p class="mt-3 text-xs text-slate-500 dark:text-slate-400">Klik kandidat untuk meninjau nominal dan menerbitkan Credit Note. Kandidat bermasalah tidak dapat diterbitkan sebelum data QC/UOM diperbaiki.</p>
    </section>

    <div class="mt-5">
      <AppTable
        :rows="rows"
        :columns="columns"
        :loading="loading.list || loading.refs"
        row-key="id_cn"
        :selected-key="selectedRow?.id_cn"
        clickable-rows
        empty-message="Belum ada Credit Note sesuai filter."
        @row-click="openDetail"
      />
    </div>

    <AppModal
      :open="candidateOpen"
      :title="`Terbitkan Credit Note ${selectedCandidate?.kode_request || ''}`"
      description="Credit Note dihitung dari hasil fisik QC GOOD + BAD. Proses ini hanya dapat dilakukan sekali untuk satu retur."
      size="4xl"
      @close="candidateOpen = false"
    >
      <div v-if="selectedCandidate" class="space-y-5">
        <p v-if="candidateError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/40 dark:bg-rose-500/10 dark:text-rose-100">
          {{ candidateError }}
        </p>
        <div class="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCandidate.nama_customer || '-' }}</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">{{ selectedCandidate.kode_customer || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Faktur Sumber</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ selectedCandidate.no_faktur || '-' }}</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">{{ selectedCandidate.kode_kpr || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">QC Diterima</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ Number(selectedCandidate.qty_qc_pcs || 0).toLocaleString('id-ID') }} PCS</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">GOOD + BAD</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">DPP / Subtotal</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(selectedCandidate.total_subtotal_candidate) }}</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">Nilai barang hasil QC</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">PPN</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(selectedCandidate.total_ppn_candidate) }}</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">Proporsional hasil QC</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Estimasi CN</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(selectedCandidate.total_cn_candidate) }}</p>
            <p class="text-sm text-slate-500 dark:text-slate-400">DPP + PPN hasil QC</p>
          </div>
        </div>

        <div v-if="!selectedCandidate.issueable" class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
          <p class="font-semibold">Kandidat belum dapat diterbitkan.</p>
          <p class="mt-1">{{ selectedCandidate.issue_reason || 'Periksa data QC dan UOM retur.' }}</p>
        </div>

        <div v-else class="overflow-x-auto rounded-2xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3">Produk</th>
                <th class="px-4 py-3">Qty Retur</th>
                <th class="px-4 py-3">QC GOOD</th>
                <th class="px-4 py-3">QC BAD</th>
                <th class="px-4 py-3">DPP / Subtotal</th>
                <th class="px-4 py-3">PPN</th>
                <th class="px-4 py-3">Nominal CN</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-for="line in selectedCandidate.details || []" :key="line.id_retur_request_detail">
                <td class="px-4 py-3">
                  <p class="font-semibold text-slate-950 dark:text-white">{{ line.nama_produk || '-' }}</p>
                  <p class="text-xs text-slate-500 dark:text-slate-400">{{ line.kode_sku || '-' }}</p>
                </td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ Number(line.requested_pcs || 0).toLocaleString('id-ID') }} PCS</td>
                <td class="px-4 py-3 text-emerald-700 dark:text-emerald-300">{{ Number(line.qc_good_pcs || 0).toLocaleString('id-ID') }} PCS</td>
                <td class="px-4 py-3 text-amber-700 dark:text-amber-300">{{ Number(line.qc_bad_pcs || 0).toLocaleString('id-ID') }} PCS</td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ formatCurrency(line.subtotal_cn) }}</td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ formatCurrency(line.ppn_cn) }}</td>
                <td class="px-4 py-3 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(line.nominal_cn) }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <label v-if="selectedCandidate.issueable" class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Konfirmasi penerbitan</span>
          <input
            v-model="issueConfirmation"
            type="text"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm font-semibold text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            placeholder="Ketik TERBITKAN CN"
          />
        </label>

        <div class="flex flex-wrap justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" :disabled="loading.issue" @click="candidateOpen = false">
            Batal
          </button>
          <button
            v-if="selectedCandidate.issueable"
            class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700 disabled:opacity-60"
            :disabled="loading.issue || String(issueConfirmation || '').trim().toUpperCase() !== 'TERBITKAN CN'"
            @click="issueCandidate"
          >
            {{ loading.issue ? 'Menerbitkan...' : 'Terbitkan Credit Note' }}
          </button>
        </div>
      </div>
    </AppModal>

    <AppModal
      :open="detailOpen"
      :title="`Detail Credit Note ${selectedRow?.kode_cn || ''}`"
      description="Rincian sumber retur dan nominal credit note."
      size="4xl"
      @close="detailOpen = false"
    >
      <div v-if="loading.detail" class="py-10 text-center text-sm text-slate-500">Memuat detail...</div>
      <div v-else>
        <div class="grid gap-4 md:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Customer</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ detailHeader?.nama_customer || '-' }}</p>
            <p class="text-sm text-slate-500">{{ detailHeader?.kode_customer || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ detailHeader?.nama_principal || '-' }}</p>
            <p class="text-sm text-slate-500">{{ detailHeader?.nama_perusahaan || '-' }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Nominal CN</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(detailHeader?.total_cn) }}</p>
            <p class="text-sm text-slate-500">{{ formatDate(detailHeader?.tanggal) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Status</p>
            <p class="mt-2 font-semibold text-slate-950 dark:text-white">{{ resolveStatusLabel(detailHeader) }}</p>
            <p class="text-sm text-slate-500">Faktur: {{ detailHeader?.no_faktur_digunakan || '-' }}</p>
          </div>
        </div>

        <div class="mt-5 rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
          <p class="text-sm font-semibold text-slate-950 dark:text-white">Sumber Retur</p>
          <div class="mt-3 grid gap-3 text-sm md:grid-cols-4">
            <p><span class="text-slate-500">Kode Request:</span> {{ detailHeader?.kode_request || '-' }}</p>
            <p><span class="text-slate-500">Kode KPR:</span> {{ detailHeader?.kode_kpr || '-' }}</p>
            <p><span class="text-slate-500">No CN Retur:</span> {{ detailHeader?.no_cn_retur || '-' }}</p>
            <p><span class="text-slate-500">Total Retur:</span> {{ formatCurrency(detailHeader?.total_retur) }}</p>
          </div>
        </div>

        <div v-if="resolveStatusValue(detailHeader) === 1" class="mt-5 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-100">
          <p class="font-semibold">Credit Note sudah diproses potong tagihan</p>
          <div class="mt-3 grid gap-3 md:grid-cols-4">
            <p><span class="opacity-70">Tanggal:</span> {{ formatDate(detailHeader?.tanggal_refund) }}</p>
            <p><span class="opacity-70">Nominal:</span> {{ formatCurrency(detailHeader?.nominal_refund || detailHeader?.total_cn) }}</p>
            <p><span class="opacity-70">Transaksi:</span> {{ detailHeader?.kode_refund || '-' }}</p>
            <p><span class="opacity-70">Rekening:</span> {{ detailHeader?.refund_nama_bank || '-' }} {{ detailHeader?.refund_nomor_rekening || '' }}</p>
          </div>
          <p v-if="detailHeader?.catatan_refund" class="mt-3 opacity-80">{{ detailHeader.catatan_refund }}</p>
        </div>

        <div class="mt-5 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
            <thead class="bg-slate-50 text-slate-500 dark:bg-slate-950 dark:text-slate-400">
              <tr>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Produk</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Qty Retur</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Hasil QC</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Harga</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Subtotal</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Nominal CN</th>
                <th class="px-4 py-3 text-left font-semibold uppercase tracking-wide">Alasan</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
              <tr v-if="!detailRows.length">
                <td colspan="7" class="px-4 py-8 text-center text-slate-500">Detail produk belum tersedia.</td>
              </tr>
              <tr v-for="item in detailRows" :key="item.id_cn_detail">
                <td class="px-4 py-3">
                  <p class="font-semibold text-slate-950 dark:text-white">{{ item.nama_produk || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ item.kode_sku || '-' }}</p>
                </td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">
                  {{ Number(item.karton_retur || 0) }} karton, {{ Number(item.box_retur || 0) }} box, {{ Number(item.pieces_retur || 0) }} pcs
                </td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">
                  <span class="text-emerald-700 dark:text-emerald-300">GOOD {{ Number(item.pieces_good_qc || 0) }} PCS</span>
                  <span class="mx-1 text-slate-400">·</span>
                  <span class="text-amber-700 dark:text-amber-300">BAD {{ Number(item.pieces_bad_qc || 0) }} PCS</span>
                </td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ formatCurrency(item.harga_satuan) }}</td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ formatCurrency(item.subtotal_retur || item.subtotal) }}</td>
                <td class="px-4 py-3 font-semibold text-slate-950 dark:text-white">{{ formatCurrency(item.nominal_cn) }}</td>
                <td class="px-4 py-3 text-slate-700 dark:text-slate-200">{{ item.alasan_retur || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="mt-5 flex flex-wrap justify-end gap-3">
          <button
            class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
            @click="printCreditNote"
          >
            Cetak CN
          </button>
          <button
            v-if="[0, 3].includes(resolveStatusValue(detailHeader))"
            class="rounded-xl bg-amber-500 px-4 py-3 text-sm font-semibold text-slate-950 shadow-sm hover:bg-amber-400"
            @click="openRefundModal(detailHeader)"
          >
            Potong Tagihan
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" @click="detailOpen = false">
            Tutup
          </button>
        </div>
      </div>
    </AppModal>

    <AppModal
      :open="refundOpen"
      :title="`Potong Tagihan ${detailHeader?.kode_cn || selectedRow?.kode_cn || 'Credit Note'}`"
      description="Proses ini membuat transaksi kas/bank dan mengunci CN sebagai Potong Tagihan."
      size="2xl"
      @close="refundOpen = false"
    >
      <div class="space-y-4">
        <div class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-100">
          Potong tagihan CN saat ini diproses penuh sesuai nominal CN: <strong>{{ formatCurrency(detailHeader?.total_cn || selectedRow?.total_cn) }}</strong>.
        </div>

        <p v-if="refundError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ refundError }}
        </p>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Tanggal Potong</span>
            <input
              v-model="refundForm.tanggal_refund"
              type="date"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            />
          </label>

          <label class="block">
            <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Nominal Potong</span>
            <input
              v-model.number="refundForm.nominal_refund"
              type="number"
              min="0"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            />
          </label>

          <label class="block">
            <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Metode Potong</span>
            <select
              v-model="refundForm.metode_refund"
              class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            >
              <option value="bank">Transfer Bank</option>
              <option value="cash">Tunai</option>
              <option value="giro">Giro</option>
            </select>
          </label>

          <AppSearchSelect
            v-model="refundForm.id_rekening_perusahaan"
            label="Rekening Kas/Bank"
            :options="accountOptions"
            :disabled="loading.accounts"
            :placeholder="loading.accounts ? 'Memuat rekening...' : 'Pilih rekening'"
            empty-text="Rekening perusahaan belum tersedia."
          />
        </div>

        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Catatan Potong</span>
          <textarea
            v-model="refundForm.catatan_refund"
            rows="3"
            class="w-full rounded-xl border border-slate-200 bg-white px-3 py-3 text-sm text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
            placeholder="Contoh: Nilai retur dipakai memotong tagihan customer"
          />
        </label>

        <label class="block">
          <span class="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-500">Konfirmasi</span>
          <input
            v-model="refundForm.confirm_potong_tagihan"
            type="text"
            class="w-full rounded-xl border border-amber-200 bg-white px-3 py-3 text-sm font-semibold text-slate-900 outline-none focus:border-amber-400 dark:border-amber-500/40 dark:bg-slate-950 dark:text-white"
            placeholder="Ketik POTONG TAGIHAN"
          />
        </label>

        <div class="flex flex-wrap justify-end gap-3">
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200" :disabled="loading.refund" @click="refundOpen = false">
            Batal
          </button>
          <button
            class="rounded-xl bg-amber-500 px-4 py-3 text-sm font-semibold text-slate-950 shadow-sm hover:bg-amber-400 disabled:opacity-60"
            :disabled="loading.refund || String(refundForm.confirm_potong_tagihan || '').trim().toUpperCase() !== 'POTONG TAGIHAN'"
            @click="submitRefund"
          >
            {{ loading.refund ? 'Memproses...' : 'Proses Potong Tagihan' }}
          </button>
        </div>
      </div>
    </AppModal>
  </section>
</template>
