<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { getBranches, getCompanies, getPrincipals, getProductDetail } from '@/api/master';
import { createPurchaseOrder, generatePurchaseOrderCode, getPurchaseOrderProducts } from '@/api/purchase';
import { exportSalesDoiAnalysis, getSalesDoiAnalysis } from '@/api/sales';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();
const router = useRouter();
const today = new Date();
const thirtyDaysAgo = new Date(today);
thirtyDaysAgo.setDate(today.getDate() - 29);

const filters = reactive({
  tanggal_awal: toLocalDateInputValue(thirtyDaysAgo),
  tanggal_akhir: toLocalDateInputValue(today),
  id_perusahaan: '',
  id_cabang: '',
  id_principal: '',
  search: '',
});

const loading = ref(false);
const exporting = ref(false);
const error = ref('');
const feedback = ref('');
const rows = ref([]);
const selectedDoiRow = ref(null);
const selectedDoiKeys = ref([]);
const creatingSplitPo = ref(false);
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const summary = ref({
  total_items: 0,
  understock: 0,
  healthy: 0,
  overstock: 0,
  no_movement: 0,
  average_doi: 0,
});

const fallbackBranchId = computed(() => auth.user?.id_cabang || auth.user?.cabang_id || auth.user?.cabang?.id || '');
const activeCompanyId = computed(() =>
  String(
    auth.user?.perusahaan?.id ||
    auth.user?.id_perusahaan ||
    branches.value.find((item) => String(item.id) === String(fallbackBranchId.value))?.id_perusahaan ||
    ''
  )
);

const companyOptions = computed(() =>
  getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true)
);

const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, true, filters.id_perusahaan, companies.value));

const principalOptions = computed(() => {
  const companyId = String(filters.id_perusahaan || '');
  return getSupervisorPrincipalOptions(principals.value, companyId, true);
});

const selectedDoiKey = computed(() => getDoiRowKey(selectedDoiRow.value));
const selectedDoiKeySet = computed(() => new Set(selectedDoiKeys.value.map((item) => String(item))));
const selectedDoiRows = computed(() =>
  rows.value.filter((row) => selectedDoiKeySet.value.has(getDoiRowKey(row)))
);
const selectedDoiGroups = computed(() => groupDoiRowsForPurchase(selectedDoiRows.value));
const canCreatePurchaseFromDoi = computed(() => {
  return selectedDoiGroups.value.length === 1 && selectedDoiGroups.value[0].items.length > 0;
});
const canCreateSplitPurchaseFromDoi = computed(() => {
  return selectedDoiGroups.value.length > 1 && selectedDoiGroups.value.every((group) =>
    group.branchId && group.principalId && group.items.length > 0
  );
});
const selectedDoiGroupSummary = computed(() => {
  if (!selectedDoiRows.value.length) {
    return 'Belum ada produk DOI yang dipilih.';
  }
  if (selectedDoiGroups.value.length === 1) {
    const group = selectedDoiGroups.value[0];
    return `${selectedDoiRows.value.length} produk dipilih | ${group.branchName || '-'} | ${group.principalName || '-'}`;
  }
  return `${selectedDoiRows.value.length} produk dipilih, akan menjadi ${selectedDoiGroups.value.length} PO berdasarkan Cabang + Principal.`;
});

const doiColumns = [
  {
    key: 'selection',
    label: 'Pilih',
    render: (row) => {
      const selected = selectedDoiKeySet.value.has(getDoiRowKey(row));
      return {
        text: selected ? 'Dipilih' : 'Pilih',
        className: [
          'inline-flex rounded-full px-3 py-1 text-xs font-semibold',
          selected ? 'bg-brand-100 text-brand-700' : 'bg-slate-100 text-slate-600',
        ].join(' '),
      };
    },
  },
  {
    key: 'nama_produk',
    label: 'Produk',
    render: (row) => `${row.nama_produk || '-'}${row.kode_sku ? ` (${row.kode_sku})` : ''}`,
  },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_cabang', label: 'Cabang' },
  {
    key: 'stok_ready',
    label: 'Stok Ready',
    render: (row) => Number(row.stok_ready || 0).toLocaleString('id-ID'),
  },
  {
    key: 'avg_daily_sales',
    label: 'Avg Jual/Hari',
    render: (row) => Number(row.avg_daily_sales || 0).toLocaleString('id-ID'),
  },
  {
    key: 'doi',
    label: 'DOI',
    render: (row) => (row.doi === null || row.doi === undefined ? '-' : `${Number(row.doi).toLocaleString('id-ID')} hari`),
  },
  {
    key: 'target_doi_hari',
    label: 'Target DOI',
    render: (row) => `${Number(row.target_doi_hari || 0).toLocaleString('id-ID')} hari`,
  },
  {
    key: 'recommended_purchase_qty',
    label: 'Rekom. PO',
    render: (row) => Number(row.recommended_purchase_qty || 0).toLocaleString('id-ID'),
  },
  {
    key: 'doi_gap_hari',
    label: 'Gap',
    render: (row) => {
      if (row.doi_gap_hari === null || row.doi_gap_hari === undefined) return '-';
      const value = Number(row.doi_gap_hari || 0);
      return {
        text: `${value > 0 ? '+' : ''}${value.toLocaleString('id-ID')} hari`,
        className: [
          'inline-flex rounded-full px-3 py-1 text-xs font-semibold',
          value > 0 ? 'bg-amber-100 text-amber-700' : value < 0 ? 'bg-rose-100 text-rose-700' : 'bg-emerald-100 text-emerald-700',
        ].join(' '),
      };
    },
  },
  {
    key: 'rule_source',
    label: 'Aturan',
    render: (row) => row.rule_source || 'Default',
  },
  {
    key: 'status_doi',
    label: 'Status',
    render: (row) => ({
      text: row.status_doi || '-',
      className: [
        'inline-flex rounded-full px-3 py-1 text-xs font-semibold',
        row.status_tone === 'rose'
          ? 'bg-rose-100 text-rose-700'
          : row.status_tone === 'amber'
            ? 'bg-amber-100 text-amber-700'
            : row.status_tone === 'emerald'
              ? 'bg-emerald-100 text-emerald-700'
              : 'bg-slate-100 text-slate-700',
      ].join(' '),
    }),
  },
  { key: 'recommendation', label: 'Rekomendasi' },
];

function getDoiRowKey(row) {
  if (!row) return '';
  return [
    row.cabang_id || '',
    row.id_principal || '',
    row.produk_id || '',
    row.stok_id || '',
  ].join('-');
}

function selectDoiRow(row) {
  const key = getDoiRowKey(row);
  if (!row?.cabang_id || !row?.id_principal || !row?.produk_id || !key) {
    error.value = 'Baris DOI belum lengkap untuk dibuat PO. Pastikan ada cabang, principal, dan produk.';
    return;
  }

  selectedDoiRow.value = row;
  if (selectedDoiKeySet.value.has(key)) {
    selectedDoiKeys.value = selectedDoiKeys.value.filter((item) => String(item) !== String(key));
    return;
  }

  error.value = '';
  selectedDoiKeys.value = [...selectedDoiKeys.value, key];
}

function groupDoiRowsForPurchase(sourceRows) {
  const groups = new Map();

  sourceRows.forEach((row) => {
    if (!row?.cabang_id || !row?.id_principal || !row?.produk_id) {
      return;
    }

    const key = `${row.cabang_id}-${row.id_principal}`;
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        branchId: row.cabang_id,
        companyId: row.id_perusahaan || filters.id_perusahaan || '',
        principalId: row.id_principal,
        branchName: row.nama_cabang || '',
        principalName: row.nama_principal || '',
        items: [],
      });
    }

    const group = groups.get(key);
    const productId = String(row.produk_id || '');
    if (!productId || group.items.some((item) => String(item.productId) === productId)) {
      return;
    }

    group.items.push({
      productId,
      qty: row.recommended_purchase_qty || '',
      productName: row.nama_produk || '',
      sku: row.kode_sku || '',
    });
  });

  return [...groups.values()];
}

function buildDoiPurchaseDraft(group = selectedDoiGroups.value[0]) {
  return {
    branchId: group?.branchId || '',
    companyId: group?.companyId || '',
    principalId: group?.principalId || '',
    items: group?.items || [],
  };
}

function normalizeQty(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function normalizePurchaseQtyRows(detail, productDetail) {
  const purchaseQtyRows = normalizeList(detail?.jumlah).map((qty) => ({
    ...qty,
    uom_id: qty.uom_id ?? qty.id ?? '',
    uom_kode: qty.uom_kode ?? qty.kode ?? '',
    uom_nama: qty.uom_nama ?? qty.nama ?? '',
    uom_level: Number(qty.uom_level ?? qty.level ?? 0),
    uom_faktor_konversi: Number(qty.uom_faktor_konversi ?? qty.faktor_konversi ?? 1),
    uom_harga_beli: Number(qty.uom_harga_beli ?? detail?.produk_harga_beli ?? productDetail?.harga_beli ?? 0),
    uom_harga_beli_ppn: Number(
      qty.uom_harga_beli_ppn ??
        Number(qty.uom_harga_beli ?? detail?.produk_harga_beli ?? productDetail?.harga_beli ?? 0) *
          (1 + Number(detail?.ppn ?? productDetail?.ppn ?? 0) / 100)
    ),
    jumlah: 0,
    subtotal: 0,
  }));

  if (purchaseQtyRows.length) {
    return purchaseQtyRows;
  }

  return normalizeList(productDetail?.uoms).map((uom) => {
    const hargaBeli = Number(detail?.produk_harga_beli ?? productDetail?.harga_beli ?? 0);
    const ppnPercent = Number(detail?.ppn ?? productDetail?.ppn ?? 0);

    return {
      uom_id: uom.id,
      uom_kode: uom.kode ?? '',
      uom_nama: uom.nama ?? '',
      uom_level: Number(uom.level ?? 0),
      uom_faktor_konversi: Number(uom.faktor_konversi ?? 1),
      uom_harga_beli: hargaBeli,
      uom_harga_beli_ppn: hargaBeli * (1 + ppnPercent / 100),
      jumlah: 0,
      subtotal: 0,
    };
  });
}

function recalculateLine(line) {
  const details = normalizeList(line.jumlah);
  let subtotal = 0;
  let totalOrder = 0;
  details.forEach((item) => {
    item.jumlah = normalizeQty(item.jumlah);
    item.subtotal = Number(item.jumlah || 0) * Number(item.uom_harga_beli || 0);
    subtotal += Number(item.subtotal || 0);
    totalOrder += Number(item.jumlah || 0) * Number(item.uom_faktor_konversi || 1);
  });
  line.subtotal = subtotal;
  line.total_order = totalOrder;
  line.total_tersisa = totalOrder;
}

function applySuggestedQty(line, suggestedQty) {
  let remaining = Math.floor(normalizeQty(suggestedQty));
  if (!remaining) {
    return;
  }

  const qtyRows = normalizeList(line.jumlah)
    .map((item) => ({
      item,
      factor: Math.max(1, Number(item.uom_faktor_konversi || 1)),
    }))
    .sort((a, b) => b.factor - a.factor);

  if (!qtyRows.length) {
    return;
  }

  qtyRows.forEach(({ item, factor }) => {
    const qty = Math.floor(remaining / factor);
    item.jumlah = qty;
    remaining -= qty * factor;
  });

  if (remaining > 0) {
    qtyRows[qtyRows.length - 1].item.jumlah += 1;
  }

  recalculateLine(line);
}

async function buildDoiPurchaseLine(item) {
  const [purchaseResponse, productResponse] = await Promise.all([
    getPurchaseOrderProducts(item.productId),
    getProductDetail(item.productId),
  ]);
  const detail = unwrapResponse(purchaseResponse);
  const productDetail = unwrapResponse(productResponse);
  if (!detail) {
    throw new Error(`Detail produk DOI ${item.productName || item.productId} tidak ditemukan.`);
  }

  const line = {
    produk_id: detail.produk_id,
    produk_kode: detail.produk_kode,
    produk_nama: detail.produk_nama,
    produk_harga_beli: Number(detail.produk_harga_beli || productDetail?.harga_beli || 0),
    subtotal: 0,
    total_order: 0,
    total_tersisa: 0,
    jumlah: normalizePurchaseQtyRows(detail, productDetail),
  };
  applySuggestedQty(line, item.qty);
  recalculateLine(line);
  return line;
}

async function buildDoiPurchasePayload(group) {
  const codeResponse = await generatePurchaseOrderCode(group.branchId, group.principalId);
  const code = String(unwrapResponse(codeResponse) || '').trim();
  const detailRows = [];

  for (const item of group.items) {
    detailRows.push(await buildDoiPurchaseLine(item));
  }

  const invalidLine = detailRows.find((line) =>
    !normalizeList(line.jumlah).some((qty) => Number(qty.jumlah || 0) > 0)
  );
  if (invalidLine) {
    throw new Error(`Qty rekomendasi untuk ${invalidLine.produk_nama || 'produk'} masih 0. Gunakan Buat 1 PO untuk isi jumlah manual.`);
  }

  const total = detailRows.reduce((sum, line) => sum + Number(line.subtotal || 0), 0);
  return {
    cabang_id: Number(group.branchId),
    principal_id: Number(group.principalId),
    kode: code,
    keterangan: `Dibuat otomatis dari Analisa DOI (${filters.tanggal_awal} s/d ${filters.tanggal_akhir})`,
    user_id: auth.user?.id || auth.user?.id_user || auth.user?.user_id || '',
    total,
    detail: detailRows.map((line) => ({
      produk_id: Number(line.produk_id),
      produk_kode: line.produk_kode,
      produk_nama: line.produk_nama,
      produk_harga_beli: Number(line.produk_harga_beli || 0),
      subtotal: Number(line.subtotal || 0),
      total_order: Number(line.total_order || 0),
      total_tersisa: Number(line.total_tersisa || 0),
      jumlah: normalizeList(line.jumlah).map((qty) => ({
        uom_id: Number(qty.uom_id),
        uom_kode: qty.uom_kode,
        uom_nama: qty.uom_nama,
        uom_level: Number(qty.uom_level || 0),
        uom_faktor_konversi: Number(qty.uom_faktor_konversi || 1),
        uom_harga_beli: Number(qty.uom_harga_beli || 0),
        uom_harga_beli_ppn: Number(qty.uom_harga_beli_ppn || 0),
        jumlah: Number(qty.jumlah || 0),
        subtotal: Number(qty.subtotal || 0),
      })),
    })),
  };
}

function openPurchaseFromDoi() {
  if (!canCreatePurchaseFromDoi.value) {
    error.value = selectedDoiRows.value.length
      ? 'Untuk membuat satu PO, semua produk pilihan harus dari cabang dan principal yang sama. Gunakan Buat PO Terpisah untuk lintas cabang/principal.'
      : 'Pilih minimal satu baris DOI yang memiliki cabang, principal, dan produk.';
    return;
  }

  const draft = buildDoiPurchaseDraft(selectedDoiGroups.value[0]);
  if (!draft.items.length) {
    error.value = 'Produk DOI belum valid untuk dibuat Purchase Order.';
    return;
  }

  const draftKey = `doi-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  window.sessionStorage.setItem(`budimas.purchase.doi.${draftKey}`, JSON.stringify(draft));

  router.push({
    path: '/purchase/orders/create',
    query: {
      source: 'doi',
      draftKey,
      branchId: draft.branchId,
      companyId: draft.companyId,
      principalId: draft.principalId,
    },
  });
}

async function createSplitPurchaseFromDoi() {
  if (!canCreateSplitPurchaseFromDoi.value) {
    error.value = selectedDoiRows.value.length
      ? 'Pilih minimal dua kombinasi Cabang + Principal untuk dibuat PO terpisah.'
      : 'Pilih minimal satu baris DOI yang memiliki cabang, principal, dan produk.';
    return;
  }

  const confirmed = window.confirm(
    `Buat ${selectedDoiGroups.value.length} Purchase Order terpisah dari ${selectedDoiRows.value.length} produk DOI yang dipilih?`
  );
  if (!confirmed) {
    return;
  }

  creatingSplitPo.value = true;
  error.value = '';
  feedback.value = '';
  try {
    const payloads = [];
    for (const group of selectedDoiGroups.value) {
      payloads.push(await buildDoiPurchasePayload(group));
    }

    const createdCodes = [];
    for (const payload of payloads) {
      await createPurchaseOrder(payload);
      createdCodes.push(payload.kode);
    }

    selectedDoiRow.value = null;
    selectedDoiKeys.value = [];
    feedback.value = `${createdCodes.length} Purchase Order berhasil dibuat dari Analisa DOI: ${createdCodes.join(', ')}.`;
  } catch (err) {
    error.value = normalizeError(err, 'PO terpisah dari Analisa DOI belum berhasil dibuat.');
  } finally {
    creatingSplitPo.value = false;
  }
}

async function loadReferences() {
  const [companyResponse, branchResponse, principalResponse] = await Promise.all([getCompanies(), getBranches(), getPrincipals()]);
  companies.value = normalizeList(unwrapResponse(companyResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));

  if (!filters.id_cabang && fallbackBranchId.value) {
    filters.id_cabang = String(fallbackBranchId.value);
  }
  syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
}

async function loadDoiAnalysis() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getSalesDoiAnalysis(buildDoiParams());

    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows).map((row) => ({
      ...row,
      doi_key: getDoiRowKey(row),
    }));
    selectedDoiRow.value = null;
    selectedDoiKeys.value = [];
    summary.value = {
      total_items: Number(payload.summary?.total_items || 0),
      understock: Number(payload.summary?.understock || 0),
      healthy: Number(payload.summary?.healthy || 0),
      overstock: Number(payload.summary?.overstock || 0),
      no_movement: Number(payload.summary?.no_movement || 0),
      average_doi: Number(payload.summary?.average_doi || 0),
    };

    feedback.value = `Analisa DOI memuat ${summary.value.total_items} produk untuk periode ${filters.tanggal_awal} sampai ${filters.tanggal_akhir}.`;
  } catch (err) {
    error.value = normalizeError(err, 'Analisa DOI belum bisa dimuat.');
    rows.value = [];
    selectedDoiRow.value = null;
    selectedDoiKeys.value = [];
    summary.value = {
      total_items: 0,
      understock: 0,
      healthy: 0,
      overstock: 0,
      no_movement: 0,
      average_doi: 0,
    };
  } finally {
    loading.value = false;
  }
}

function buildDoiParams() {
  return {
    tanggal_awal: filters.tanggal_awal,
    tanggal_akhir: filters.tanggal_akhir,
    id_perusahaan: filters.id_perusahaan || undefined,
    id_cabang: filters.id_cabang || fallbackBranchId.value || undefined,
    id_principal: filters.id_principal || undefined,
    search: filters.search || undefined,
  };
}

function downloadNameFromDisposition(disposition, format = 'xlsx') {
  const encodedMatch = String(disposition || '').match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    return decodeURIComponent(encodedMatch[1]);
  }
  const basicMatch = String(disposition || '').match(/filename=\"?([^\";]+)\"?/i);
  return basicMatch?.[1] || `Analisa_DOI_${toLocalDateInputValue(new Date())}.${format}`;
}

async function exportDoiAnalysis(format = 'xlsx') {
  exporting.value = true;
  error.value = '';
  try {
    const response = await exportSalesDoiAnalysis(buildDoiParams(), format);
    const blob = new Blob(
      [response.data],
      {
        type: response.headers?.['content-type'] || (
          format === 'csv'
            ? 'text/csv;charset=utf-8'
            : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
      }
    );
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = downloadNameFromDisposition(response.headers?.['content-disposition'], format);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
    feedback.value = `File Analisa DOI (${format.toUpperCase()}) berhasil diunduh. Ubah hanya kolom Final OB SPV sebelum diimpor sebagai Purchase Order.`;
  } catch (err) {
    let message = normalizeError(err, 'Export Analisa DOI belum berhasil dibuat.');
    if (err?.response?.data instanceof Blob) {
      try {
        const payload = JSON.parse(await err.response.data.text());
        message = payload?.message || payload?.error || message;
      } catch (_) {
        // Tetap gunakan pesan fallback saat server tidak mengirim JSON.
      }
    }
    error.value = message;
  } finally {
    exporting.value = false;
  }
}

function resetFilters() {
  filters.tanggal_awal = toLocalDateInputValue(thirtyDaysAgo);
  filters.tanggal_akhir = toLocalDateInputValue(today);
  filters.id_cabang = fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.id_perusahaan = '';
  syncSupervisorCompanyFromBranch(filters, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
  filters.id_principal = '';
  filters.search = '';
  loadDoiAnalysis();
}

watch(
  () => filters.id_perusahaan,
  (companyId) => {
    if (resetSupervisorBranchWhenCompanyChanges(filters, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value)) {
      filters.id_principal = '';
    }
    if (!principalOptions.value.some((item) => item.value === String(filters.id_principal))) {
      filters.id_principal = '';
    }
  }
);

watch(
  () => filters.id_cabang,
  (branchId) => {
    if (!branchId) {
      return;
    }
  }
);

onMounted(async () => {
  try {
    await loadReferences();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi cabang dan principal belum bisa dimuat.');
  }

  await loadDoiAnalysis();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Analisa DOI"
      description="Supervisor bisa melihat stok dibanding kecepatan jual agar cepat membaca produk yang tipis, sehat, terlalu tinggi, atau belum bergerak."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
        <button
          class="rounded-xl border border-brand-200 bg-white px-4 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
          :disabled="exporting"
          @click="exportDoiAnalysis('xlsx')"
        >
          {{ exporting ? 'Menyiapkan Excel...' : 'Export Excel' }}
        </button>
        <button
          class="rounded-xl border border-brand-200 bg-white px-4 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-400"
          :disabled="exporting"
          @click="exportDoiAnalysis('csv')"
        >
          {{ exporting ? 'Menyiapkan CSV...' : 'Export CSV' }}
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadDoiAnalysis">
          Refresh DOI
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-6">
        <AppFormField v-model="filters.tanggal_awal" label="Tanggal Awal" type="date" />
        <AppFormField v-model="filters.tanggal_akhir" label="Tanggal Akhir" type="date" />
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filters.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" placeholder="" :options="principalOptions" :disabled="!filters.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppFormField v-model="filters.search" label="Cari Produk" placeholder="Nama produk atau SKU" />
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadDoiAnalysis">
          Tampilkan Analisa
        </button>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Rata-rata DOI</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ summary.average_doi.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Hari stok rata-rata berdasarkan penjualan pada periode aktif.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Understock</p>
        <p class="mt-3 text-3xl font-bold text-rose-600">{{ summary.understock.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Produk yang stoknya tipis dan perlu prioritas replenishment.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Healthy</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">{{ summary.healthy.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Produk dengan stok yang masih seimbang terhadap pergerakan jual.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Overstock</p>
        <p class="mt-3 text-3xl font-bold text-amber-600">{{ summary.overstock.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Produk dengan stok terlalu tinggi dibanding penjualan harian.</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">No Movement</p>
        <p class="mt-3 text-3xl font-bold text-slate-700">{{ summary.no_movement.toLocaleString('id-ID') }}</p>
        <p class="mt-2 text-sm text-slate-500">Produk belum bergerak dalam periode filter dan perlu review pasar.</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Tabel Analisa DOI</h3>
          <p class="mt-1 text-sm text-slate-500">Saya urutkan dengan fokus ke produk yang paling perlu tindakan lebih dulu, lalu saya beri status warna dan rekomendasi sederhana.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ summary.total_items.toLocaleString('id-ID') }} Produk
        </div>
      </div>

      <div class="mb-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        Satu Purchase Order hanya bisa berisi produk dari cabang dan principal yang sama. Jika tetap memilih banyak produk lintas
        cabang/principal, gunakan Buat PO Terpisah agar sistem otomatis memecah berdasarkan kombinasi Cabang + Principal.
      </div>

      <div class="mb-4 flex flex-wrap items-center gap-3">
        <button
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="!canCreatePurchaseFromDoi || creatingSplitPo"
          @click="openPurchaseFromDoi"
        >
          Buat 1 PO{{ selectedDoiRows.length && canCreatePurchaseFromDoi ? ` (${selectedDoiRows.length})` : '' }}
        </button>
        <button
          class="rounded-xl border border-brand-200 bg-white px-4 py-2 text-sm font-semibold text-brand-700 hover:bg-brand-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
          :disabled="!canCreateSplitPurchaseFromDoi || creatingSplitPo"
          @click="createSplitPurchaseFromDoi"
        >
          {{ creatingSplitPo ? 'Membuat PO...' : `Buat PO Terpisah${selectedDoiGroups.length > 1 ? ` (${selectedDoiGroups.length})` : ''}` }}
        </button>
        <span class="text-sm text-slate-500">
          {{ selectedDoiGroupSummary }}
        </span>
      </div>

      <AppTable
        :rows="rows"
        :columns="doiColumns"
        :loading="loading"
        :paginated="true"
        :clickable-rows="true"
        :default-page-size="15"
        row-key="doi_key"
        :selected-key="selectedDoiKey"
        empty-message="Belum ada data DOI yang cocok dengan filter ini."
        @row-click="selectDoiRow"
      />
    </section>
  </div>
</template>
