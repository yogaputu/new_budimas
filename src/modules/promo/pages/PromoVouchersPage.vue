<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  getBranches,
  getCompanies,
  getCustomerOptions,
  getPrincipals,
  getProductOptionsByPrincipal
} from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { createVoucher, deleteVoucher, getVoucherDetail, getVouchers, updateVoucher } from '@/api/promo';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany } from '@/utils/accessScope';
import {
  getBranchOptionsForCompany,
  getCompanyOptionsForScope,
  resetBranchWhenCompanyChanges
} from '@/utils/filterScope';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const props = defineProps({
  /**
   * The Canvas entry point reuses this master screen instead of duplicating
   * voucher data.  In Canvas mode the list is constrained to Canvas/Both and
   * the form cannot accidentally create a Promo-only voucher.
   */
  managementScope: {
    type: String,
    default: ''
  }
});

const filters = reactive({
  tipe_voucher: '1',
  status: '',
  branch: '',
  company: '',
  principal: '',
  channel_scope: '',
  search: ''
});

const form = reactive({
  id: '',
  tipe_voucher: 1,
  channel_scope: 'promo',
  id_cabang_filter: '',
  id_perusahaan: '',
  id_principal: '',
  nama: '',
  keterangan: '',
  status_diskon: '1',
  syarat_ketentuan: '',
  syarat_wajib: '',
  upload_file: '',
  tanggal_mulai: '',
  tanggal_kadaluarsa: '',
  minimal_subtotal_pembelian: '',
  persen_diskon: '',
  nilai_diskon: '',
  jenis_voucher: '1',
  kategori_voucher: '1',
  limit: '',
  level_uom: '',
  minimal_jumlah_produk: ''
});

const rows = ref([]);
const companies = ref([]);
const principals = ref([]);
const branches = ref([]);
const customers = ref([]);
const products = ref([]);
const selectedProducts = ref([]);
const selectedBranches = ref([]);
const selectedCustomers = ref([]);
const selectedRow = ref(null);
const selectedDetail = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const saving = ref(false);
const referencesLoading = ref(false);
const modalOpen = ref(false);
const mode = ref('create');
const error = ref('');
const actionError = ref('');
const feedback = ref('');
const productSearch = ref('');
const branchSearch = ref('');
const customerSearch = ref('');
const auth = useAuthStore();

const voucherTypeOptions = [
  { value: '1', label: 'Voucher 1 Reguler' },
  { value: '2', label: 'Voucher 2' },
  { value: '3', label: 'Voucher 3' }
];

const channelScopeOptions = [
  { value: 'promo', label: 'Promo All-In' },
  { value: 'canvas', label: 'Canvas' },
  { value: 'both', label: 'Promo All-In & Canvas' }
];

const statusOptions = [
  { value: '1', label: 'Aktif' },
  { value: '0', label: 'Nonaktif' }
];

const jenisVoucherOptions = [
  { value: '1', label: 'Reguler' },
  { value: '0', label: 'Produk' }
];

const kategoriVoucherOptions = [
  { value: '1', label: 'Persentase Diskon' },
  { value: '2', label: 'Nominal Diskon' }
];

const isTypeOne = computed(() => Number(form.tipe_voucher) === 1);
const isTypeTwo = computed(() => Number(form.tipe_voucher) === 2);
const isTypeThree = computed(() => Number(form.tipe_voucher) === 3);
const isProductVoucher = computed(() => !isTypeOne.value && Number(form.jenis_voucher) === 0);
const isCanvasManagement = computed(() => String(props.managementScope || '').toLowerCase() === 'canvas');
const formVoucherTypeOptions = computed(() =>
  isCanvasManagement.value
    ? voucherTypeOptions.filter((item) => item.value === '2' || item.value === '3')
    : voucherTypeOptions
);
const formChannelScopeOptions = computed(() =>
  isCanvasManagement.value
    ? channelScopeOptions.filter((item) => item.value === 'canvas' || item.value === 'both')
    : channelScopeOptions
);
const filterChannelScopeOptions = computed(() =>
  isCanvasManagement.value ? formChannelScopeOptions.value : channelScopeOptions
);

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));

// The voucher filter is intentionally company-first.  A non-super user can
// still only see companies that are linked to their assigned branch scope;
// a Super User can start from any company.
const formBranchOptions = computed(() => getPromoBranchOptions(branches.value, auth));

const filterCompanyOptions = computed(() => {
  const optionsByCompanyScope = getCompanyOptionsForScope(companies.value, auth);
  if (canAccessAllBranches.value) return optionsByCompanyScope;

  const companyIdsLinkedToAllowedBranches = new Set();
  formBranchOptions.value.forEach((branch) => {
    getPromoCompanyOptions(companies.value, branches.value, branch.value).forEach((company) => {
      companyIdsLinkedToAllowedBranches.add(String(company.value));
    });
  });

  return optionsByCompanyScope.filter((company) => companyIdsLinkedToAllowedBranches.has(String(company.value)));
});

const filterBranchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, auth, filters.company, false, companies.value)
);

const companyOptions = computed(() =>
  getPromoCompanyOptions(companies.value, branches.value, form.id_cabang_filter)
);

const principalOptions = computed(() =>
  getPromoPrincipalOptions(principals.value, form.id_perusahaan)
);

const filterPrincipalOptions = computed(() =>
  getPromoPrincipalOptions(principals.value, filters.company)
);

const filterFields = computed(() => [
  {
    key: 'company',
    label: 'Perusahaan',
    type: 'search-select',
    options: filterCompanyOptions.value,
    placeholder: 'Cari perusahaan',
    emptyText: 'Perusahaan sesuai akses belum tersedia.'
  },
  {
    key: 'branch',
    label: 'Cabang',
    type: 'search-select',
    options: filterBranchOptions.value,
    placeholder: filters.company ? 'Cari cabang' : 'Pilih perusahaan dahulu',
    emptyText: filters.company ? 'Cabang untuk perusahaan ini belum tersedia.' : 'Pilih perusahaan terlebih dahulu.',
    disabled: !filters.company
  },
  {
    key: 'principal',
    label: 'Principal',
    type: 'search-select',
    options: filterPrincipalOptions.value,
    placeholder: filters.company ? 'Cari principal' : 'Pilih perusahaan dahulu',
    emptyText: filters.company ? 'Principal untuk perusahaan ini belum tersedia.' : 'Pilih perusahaan terlebih dahulu.',
    disabled: !filters.company
  },
  {
    key: 'tipe_voucher',
    label: 'Tipe Voucher',
    type: 'search-select',
    options: formVoucherTypeOptions.value,
    placeholder: 'Cari tipe voucher'
  },
  {
    key: 'channel_scope',
    label: 'Berlaku untuk',
    type: 'search-select',
    options: filterChannelScopeOptions.value,
    placeholder: 'Cari cakupan voucher'
  },
  {
    key: 'status',
    label: 'Status',
    type: 'search-select',
    options: statusOptions,
    placeholder: 'Cari status'
  },
  { key: 'search', label: 'Cari Voucher', placeholder: 'Kode, nama, principal, diskon' }
]);

const filteredRows = computed(() => {
  const keyword = filters.search.trim().toLowerCase();

  return rows.value.filter((item) => {
    const matchStatus = filters.status ? String(item.status_voucher) === String(filters.status) : true;
    const matchPrincipal = filters.principal ? String(item.id_principal) === String(filters.principal) : true;
    const matchCompany = filters.company ? String(item.id_perusahaan || item.company_id || '') === String(filters.company) : true;
    const branchIds = normalizeList(item.id_cabang || item.cabang).map(String);
    const matchBranch = filters.branch ? branchIds.includes(String(filters.branch)) : true;
    const channelScope = normalizeChannelScope(item.channel_scope);
    const matchesCanvasContext = !isCanvasManagement.value || ['canvas', 'both'].includes(channelScope);
    const matchChannelScope = filters.channel_scope ? channelScope === String(filters.channel_scope) : true;
    const matchKeyword = !keyword
      ? true
      : [
          item.kode_voucher,
          item.nama_voucher,
          item.nama_principal,
          item.keterangan,
          resolveChannelScopeLabel(item),
          resolveVoucherModeLabel(item),
          resolveDiscountLabel(item),
          resolveVoucherStatusLabel(item)
        ]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(keyword));

    return matchStatus
      && matchPrincipal
      && matchCompany
      && matchBranch
      && matchesCanvasContext
      && matchChannelScope
      && matchKeyword;
  });
});

const selectedKey = computed(() => selectedRow.value?.id || '');

const summary = computed(() => ({
  total: rows.value.length,
  active: rows.value.filter((row) => Number(row.status_voucher) === 1).length,
  regular: rows.value.filter((row) => resolveVoucherModeLabel(row) === 'Reguler').length,
  product: rows.value.filter((row) => resolveVoucherModeLabel(row) === 'Produk').length
}));

const filteredProductOptions = computed(() => {
  const keyword = productSearch.value.trim().toLowerCase();
  if (!keyword) return products.value;
  return products.value.filter((item) => String(item.nama || item.label || '').toLowerCase().includes(keyword));
});

const filteredBranchOptions = computed(() => {
  const keyword = branchSearch.value.trim().toLowerCase();
  const scoped = branches.value.filter((item) => !form.id_perusahaan || branchMatchesCompany(item, form.id_perusahaan));
  if (!keyword) return scoped;
  return scoped.filter((item) => String(item.nama || '').toLowerCase().includes(keyword));
});

const filteredCustomerOptions = computed(() => {
  const keyword = customerSearch.value.trim().toLowerCase();
  const scoped = customers.value.filter((item) => {
    const companyMatch = !form.id_perusahaan || String(item.id_perusahaan || item.company_id || '') === String(form.id_perusahaan);
    const branchMatch =
      !selectedBranches.value.length ||
      selectedBranches.value.includes(String(item.id_cabang || item.cabang_id || item.branch_id || ''));
    return companyMatch && branchMatch;
  });
  if (!keyword) return scoped;
  return scoped.filter((item) =>
    [item.nama, item.kode]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

const selectedProductLabels = computed(() =>
  products.value.filter((item) => selectedProducts.value.includes(String(item.id)))
);

const selectedBranchLabels = computed(() =>
  branches.value.filter((item) => selectedBranches.value.includes(String(item.id)))
);

const selectedCustomerLabels = computed(() =>
  customers.value.filter((item) => selectedCustomers.value.includes(String(item.id)))
);

const detailModeLabel = computed(() =>
  selectedDetail.value ? resolveVoucherModeLabel(selectedDetail.value) : '-'
);

const detailDiscountLabel = computed(() =>
  selectedDetail.value ? resolveDiscountLabel(selectedDetail.value) : '-'
);

const detailScopeSummary = computed(() => {
  if (!selectedDetail.value) return '-';

  const parts = [];
  const productCount = normalizeList(selectedDetail.value.produk).length;
  const branchCount = normalizeList(selectedDetail.value.cabang).length;
  const customerCount = normalizeList(selectedDetail.value.customer).length;

  if (productCount) parts.push(`${productCount} produk`);
  if (branchCount) parts.push(`${branchCount} cabang`);
  if (customerCount) parts.push(`${customerCount} customer`);

  return parts.length ? parts.join(' • ') : 'Tanpa target khusus';
});

const detailProducts = computed(() => mapIdsToLabels(selectedDetail.value?.produk, products.value, 'nama', 'Produk'));
const detailBranches = computed(() => mapIdsToLabels(selectedDetail.value?.cabang, branches.value, 'nama', 'Cabang'));
const detailCustomers = computed(() => mapIdsToLabels(selectedDetail.value?.customer, customers.value, 'nama', 'Customer', 'kode'));

const tableColumns = [
  { key: 'kode_voucher', label: 'Kode Voucher' },
  { key: 'nama_voucher', label: 'Nama Voucher' },
  { key: 'nama_principal', label: 'Principal' },
  {
    key: 'channel_scope',
    label: 'Berlaku untuk',
    render: (row) => badgeValue(resolveChannelScopeLabel(row), resolveChannelScopeBadge(row))
  },
  {
    key: 'periode',
    label: 'Periode',
    render: (row) => formatPeriod(row.tanggal_mulai, row.tanggal_kadaluarsa)
  },
  {
    key: 'mode_voucher',
    label: 'Mode',
    render: (row) => badgeValue(resolveVoucherModeLabel(row), resolveVoucherModeBadge(resolveVoucherModeLabel(row)))
  },
  {
    key: 'diskon',
    label: 'Diskon',
    render: (row) => resolveDiscountLabel(row)
  },
  {
    key: 'status_voucher',
    label: 'Status',
    render: (row) => badgeValue(resolveVoucherStatusLabel(row), resolveVoucherStatusBadge(row))
  }
];

function badgeValue(text, className) {
  return { text, className };
}

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function formatDate(value) {
  if (!value) return '-';
  const raw = String(value).slice(0, 10);
  const [year, month, day] = raw.split('-');
  if (!year || !month || !day) return value;
  return `${day}/${month}/${year}`;
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(amount);
}

function formatPeriod(start, end) {
  if (!start && !end) return '-';
  return `${formatDate(start)} - ${formatDate(end)}`;
}

function normalizeChannelScope(value) {
  const scope = String(value || '').trim().toLowerCase();
  return ['promo', 'canvas', 'both'].includes(scope) ? scope : 'both';
}

function resolveChannelScopeLabel(row) {
  return {
    promo: 'Promo All-In',
    canvas: 'Canvas',
    both: 'Promo & Canvas'
  }[normalizeChannelScope(row?.channel_scope)];
}

function resolveChannelScopeBadge(row) {
  return {
    promo: 'inline-flex min-w-[112px] items-center justify-center rounded-full bg-violet-100 px-3 py-1 text-xs font-semibold text-violet-700',
    canvas: 'inline-flex min-w-[112px] items-center justify-center rounded-full bg-cyan-100 px-3 py-1 text-xs font-semibold text-cyan-700',
    both: 'inline-flex min-w-[112px] items-center justify-center rounded-full bg-indigo-100 px-3 py-1 text-xs font-semibold text-indigo-700'
  }[normalizeChannelScope(row?.channel_scope)];
}

function resolveVoucherModeLabel(row) {
  const tipe = Number(row?.tipe_voucher || filters.tipe_voucher || form.tipe_voucher || 1);
  if (tipe === 1 || Number(row?.is_reguler) === 1) {
    return 'Reguler';
  }
  return 'Produk';
}

function resolveVoucherModeBadge(label) {
  return label === 'Reguler'
    ? 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700'
    : 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700';
}

function resolveVoucherStatusLabel(row) {
  return Number(row?.status_voucher) === 1 ? 'Aktif' : 'Nonaktif';
}

function resolveVoucherStatusBadge(row) {
  return Number(row?.status_voucher) === 1
    ? 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700'
    : 'inline-flex min-w-[86px] items-center justify-center rounded-full bg-slate-200 px-3 py-1 text-xs font-semibold text-slate-700';
}

function resolveDiscountLabel(row) {
  const percentage =
    Number(row?.persentase_diskon_1 || 0) ||
    Number(row?.persentase_diskon_2 || 0) ||
    Number(row?.persentase_diskon_3 || 0);
  const nominal = Number(row?.nominal_diskon || row?.nilai_diskon || 0);

  if (percentage > 0) {
    return `${percentage}%`;
  }

  if (nominal > 0) {
    return formatCurrency(nominal);
  }

  return '-';
}

function mapIdsToLabels(ids, source, nameKey, fallbackPrefix, secondaryKey = null) {
  return normalizeList(ids).map((value) => {
    const found = source.find((item) => String(item.id) === String(value));
    if (!found) {
      return `${fallbackPrefix} ${value}`;
    }

    if (secondaryKey && found[secondaryKey]) {
      return `${found[secondaryKey]} | ${found[nameKey] || found.nama}`;
    }

    return found[nameKey] || found.nama || `${fallbackPrefix} ${value}`;
  });
}

function resetSelections() {
  selectedProducts.value = [];
  selectedBranches.value = [];
  selectedCustomers.value = [];
  productSearch.value = '';
  branchSearch.value = '';
  customerSearch.value = '';
}

function resetForm() {
  Object.assign(form, {
    id: '',
    tipe_voucher: Number(filters.tipe_voucher || 1),
    channel_scope: isCanvasManagement.value ? 'canvas' : (filters.channel_scope || 'promo'),
    id_cabang_filter: filters.branch || getPromoFallbackBranchId(auth) || '',
    id_perusahaan: '',
    id_principal: '',
    nama: '',
    keterangan: '',
    status_diskon: '1',
    syarat_ketentuan: '',
    syarat_wajib: '',
    upload_file: '',
    tanggal_mulai: '',
    tanggal_kadaluarsa: '',
    minimal_subtotal_pembelian: '',
    persen_diskon: '',
    nilai_diskon: '',
    jenis_voucher: '1',
    kategori_voucher: '1',
    limit: '',
    level_uom: '',
    minimal_jumlah_produk: ''
  });
  resetSelections();
}

function toggleSelection(targetRef, id) {
  const key = String(id);
  if (targetRef.value.includes(key)) {
    targetRef.value = targetRef.value.filter((item) => item !== key);
    return;
  }
  targetRef.value = [...targetRef.value, key];
}

function buildVoucherPayload() {
  const payload = {
    id_principal: Number(form.id_principal || 0),
    nama: form.nama,
    keterangan: form.keterangan || '',
    status_diskon: Number(form.status_diskon || 0),
    channel_scope: normalizeChannelScope(form.channel_scope),
    syarat_ketentuan: form.syarat_ketentuan || '',
    syarat_wajib: form.syarat_wajib || '',
    upload_file: form.upload_file || '',
    tanggal_mulai: form.tanggal_mulai || null,
    tanggal_kadaluarsa: form.tanggal_kadaluarsa || null,
    minimal_subtotal_pembelian: Number(form.minimal_subtotal_pembelian || 0),
    persen_diskon: Number(form.persen_diskon || 0),
    nilai_diskon: Number(form.nilai_diskon || 0),
    jenis_voucher: Number(form.jenis_voucher || 1),
    kategori_voucher: Number(form.kategori_voucher || 1),
    limit: Number(form.limit || 0),
    level_uom: Number(form.level_uom || 0),
    minimal_jumlah_produk: Number(form.minimal_jumlah_produk || 0),
    id_produk: selectedProducts.value.map((id) => ({ id: Number(id) })),
    id_cabang: selectedBranches.value.map((id) => ({ id: Number(id) })),
    id_customer: selectedCustomers.value.map((id) => ({ id: Number(id) }))
  };

  if (mode.value === 'edit') {
    payload.id = Number(form.id);
  }

  if (isTypeOne.value) {
    delete payload.jenis_voucher;
    delete payload.kategori_voucher;
    delete payload.limit;
    delete payload.level_uom;
    delete payload.minimal_jumlah_produk;
    delete payload.id_cabang;
    delete payload.id_customer;
  }

  if (!isProductVoucher.value) {
    payload.kategori_voucher = 1;
    payload.limit = 0;
    payload.level_uom = 0;
    payload.minimal_jumlah_produk = 0;
  }

  if (Number(form.kategori_voucher) === 1) {
    payload.nilai_diskon = 0;
  } else {
    payload.persen_diskon = 0;
  }

  if (!isTypeThree.value) {
    delete payload.id_customer;
  }

  return payload;
}

function validateForm() {
  if (isCanvasManagement.value && ![2, 3].includes(Number(form.tipe_voucher))) {
    return 'Voucher Canvas hanya mendukung Voucher 2 atau Voucher 3.';
  }

  if (isCanvasManagement.value && !['canvas', 'both'].includes(normalizeChannelScope(form.channel_scope))) {
    return 'Voucher yang dibuat dari Canvas harus berlaku untuk Canvas atau keduanya.';
  }

  if (!form.id_principal) {
    return 'Principal voucher wajib dipilih.';
  }

  if (!form.nama.trim()) {
    return 'Nama voucher wajib diisi.';
  }

  if (!form.tanggal_mulai || !form.tanggal_kadaluarsa) {
    return 'Tanggal mulai dan tanggal kadaluarsa wajib diisi.';
  }

  if (String(form.tanggal_kadaluarsa) < String(form.tanggal_mulai)) {
    return 'Tanggal kadaluarsa tidak boleh lebih awal dari tanggal mulai.';
  }

  if (Number(form.minimal_subtotal_pembelian || 0) < 0) {
    return 'Minimal subtotal pembelian tidak boleh negatif.';
  }

  if (!isTypeOne.value && selectedBranches.value.length === 0) {
    return 'Pilih minimal satu cabang target untuk voucher tipe 2 atau 3.';
  }

  if (isProductVoucher.value && selectedProducts.value.length === 0) {
    return 'Voucher produk wajib memiliki minimal satu produk terkait.';
  }

  if (isProductVoucher.value && Number(form.kategori_voucher) === 1 && Number(form.persen_diskon || 0) <= 0) {
    return 'Persentase diskon wajib lebih dari 0.';
  }

  if (isProductVoucher.value && Number(form.kategori_voucher) === 2 && Number(form.nilai_diskon || 0) <= 0) {
    return 'Nominal diskon wajib lebih dari 0.';
  }

  if (isTypeOne.value && Number(form.persen_diskon || 0) <= 0 && Number(form.nilai_diskon || 0) <= 0) {
    return 'Voucher reguler wajib memiliki nilai diskon.';
  }

  if (isTypeTwo.value && isProductVoucher.value) {
    if (Number(form.level_uom || 0) <= 0) {
      return 'Level UOM wajib diisi untuk voucher 2 produk.';
    }
    if (Number(form.minimal_jumlah_produk || 0) <= 0) {
      return 'Minimal jumlah produk wajib diisi untuk voucher 2 produk.';
    }
  }

  if (isTypeThree.value && selectedCustomers.value.length === 0) {
    return 'Voucher 3 wajib memiliki customer target.';
  }

  return '';
}

async function loadRows() {
  loading.value = true;
  error.value = '';
  try {
    const response = await getVouchers({
      'tipe-voucher': Number(filters.tipe_voucher || 1),
      scope_context: isCanvasManagement.value ? 'canvas' : undefined,
      page: 0,
      limit: 250
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload).map((item) => ({
      ...item,
      channel_scope: normalizeChannelScope(item.channel_scope),
      tipe_voucher: Number(filters.tipe_voucher || 1)
    }));

    if (selectedRow.value) {
      const replacement = rows.value.find((item) => String(item.id) === String(selectedRow.value.id));
      selectedRow.value = replacement || null;
    }
  } catch (err) {
    error.value = normalizeError(err, 'Daftar voucher belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function loadReferences() {
  referencesLoading.value = true;
  try {
    const [companyResponse, principalResponse, branchResponse, customerResponse] = await Promise.all([
      getCompanies(),
      getPrincipals(),
      getBranches(),
      getCustomerOptions()
    ]);
    companies.value = normalizeList(unwrapResponse(companyResponse));
    principals.value = normalizeList(unwrapResponse(principalResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    customers.value = normalizeList(unwrapResponse(customerResponse));
    applyLoginBranchScope();
  } finally {
    referencesLoading.value = false;
  }
}

async function loadProductsByPrincipal(idPrincipal) {
  if (!idPrincipal) {
    products.value = [];
    selectedProducts.value = [];
    return;
  }

  try {
    const response = await getProductOptionsByPrincipal(idPrincipal);
    products.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    actionError.value = normalizeError(err, 'Daftar produk voucher belum bisa dimuat.');
    products.value = [];
  }
}

async function fetchVoucherDetail(row) {
  const response = await getVoucherDetail(Number(filters.tipe_voucher || 1), row.id);
  return unwrapResponse(response) || {};
}

async function openPreview(row) {
  selectedRow.value = row;
  detailLoading.value = true;
  error.value = '';
  try {
    const detail = await fetchVoucherDetail(row);
    selectedDetail.value = {
      ...detail,
      tipe_voucher: Number(filters.tipe_voucher || 1)
    };

    if (detail.id_principal) {
      await loadProductsByPrincipal(detail.id_principal);
    }
  } catch (err) {
    error.value = normalizeError(err, 'Detail voucher belum bisa dimuat.');
    selectedDetail.value = null;
  } finally {
    detailLoading.value = false;
  }
}

watch(
  () => form.id_cabang_filter,
  () => {
    if (!companyOptions.value.some((item) => item.value === String(form.id_perusahaan))) {
      form.id_perusahaan = '';
    }
    selectedBranches.value = [];
    selectedCustomers.value = [];
  }
);

watch(
  () => form.id_perusahaan,
  () => {
    if (form.id_principal && !principalOptions.value.some((item) => item.value === String(form.id_principal))) {
      form.id_principal = '';
    }
    selectedBranches.value = selectedBranches.value.filter((id) =>
      filteredBranchOptions.value.some((item) => String(item.id) === String(id))
    );
    selectedCustomers.value = selectedCustomers.value.filter((id) =>
      filteredCustomerOptions.value.some((item) => String(item.id) === String(id))
    );
  }
);

watch(
  () => form.id_principal,
  async (value, oldValue) => {
    if (!value) {
      products.value = [];
      selectedProducts.value = [];
      return;
    }

    if (String(value) !== String(oldValue)) {
      selectedProducts.value = [];
    }
    await loadProductsByPrincipal(value);
  }
);

watch(
  () => filters.branch,
  () => {
    selectedRow.value = null;
    selectedDetail.value = null;
  }
);

watch(
  () => filters.company,
  () => {
    keepBranchInsideCompanyScope();
    if (filters.principal && !filterPrincipalOptions.value.some((item) => item.value === String(filters.principal))) {
      filters.principal = '';
    }
    selectedRow.value = null;
    selectedDetail.value = null;
  }
);

watch(
  () => filters.tipe_voucher,
  async () => {
    selectedRow.value = null;
    selectedDetail.value = null;
    await loadRows();
  }
);

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  actionError.value = '';
  feedback.value = '';
  resetForm();
  modalOpen.value = true;
}

function applyLoginBranchScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.branch = String(fallbackBranch);
    form.id_cabang_filter = String(fallbackBranch);

    // When an assigned branch belongs to exactly one company, select it as
    // the safe default.  Otherwise the user chooses a company first and the
    // branch remains locked to their access scope.
    if (filterCompanyOptions.value.length === 1) {
      filters.company = String(filterCompanyOptions.value[0].value);
    }
  }
}

function keepBranchInsideCompanyScope() {
  resetBranchWhenCompanyChanges(filters, 'company', 'branch', branches.value, auth, companies.value);

  // A branch-scoped account must never lose its branch predicate merely by
  // changing the company filter.  If the current branch does not belong to
  // the selected company, use the first branch still permitted for that
  // company instead of broadening the local result set.
  if (!canAccessAllBranches.value && filters.company && !filters.branch) {
    const scopedBranch = filterBranchOptions.value[0]?.value;
    if (scopedBranch) {
      filters.branch = String(scopedBranch);
    }
  }
}

function updateFilters(nextFilters) {
  const previousCompany = filters.company;
  Object.assign(filters, nextFilters || {});

  if (String(previousCompany || '') !== String(filters.company || '')) {
    keepBranchInsideCompanyScope();
    filters.principal = '';
  }
}

function resetFilters() {
  Object.assign(filters, {
    tipe_voucher: isCanvasManagement.value ? '2' : '1',
    status: '',
    branch: canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '',
    company: '',
    principal: '',
    channel_scope: '',
    search: ''
  });
  if (!canAccessAllBranches.value && filterCompanyOptions.value.length === 1) {
    filters.company = String(filterCompanyOptions.value[0].value);
  }
  selectedRow.value = null;
  selectedDetail.value = null;
}

async function openEdit(row = selectedRow.value) {
  if (!row?.id) return;

  mode.value = 'edit';
  actionError.value = '';
  feedback.value = '';
  resetForm();

  try {
    const detail = await fetchVoucherDetail(row);
    Object.assign(form, {
      id: normalizeId(detail.id),
      tipe_voucher: Number(filters.tipe_voucher || 1),
      channel_scope: normalizeChannelScope(detail.channel_scope),
      id_perusahaan: normalizeId(detail.id_perusahaan || ''),
      id_principal: normalizeId(detail.id_principal),
      nama: detail.nama_voucher || '',
      keterangan: detail.keterangan || '',
      status_diskon: normalizeId(detail.status_voucher ?? 1),
      syarat_ketentuan: detail.syarat_ketentuan || '',
      syarat_wajib: detail.syarat_wajib || '',
      upload_file: detail.pic_voucher || '',
      tanggal_mulai: String(detail.tanggal_mulai || '').slice(0, 10),
      tanggal_kadaluarsa: String(detail.tanggal_kadaluarsa || '').slice(0, 10),
      minimal_subtotal_pembelian: normalizeId(detail.minimal_subtotal_pembelian || ''),
      persen_diskon: normalizeId(
        detail.persentase_diskon_1 || detail.persentase_diskon_2 || detail.persentase_diskon_3 || ''
      ),
      nilai_diskon: normalizeId(detail.nominal_diskon || detail.nilai_diskon || ''),
      jenis_voucher: normalizeId(detail.is_reguler === 1 ? 1 : 0),
      kategori_voucher: normalizeId(detail.kategori_voucher || 1),
      limit: normalizeId(detail.budget_diskon || ''),
      level_uom: normalizeId(detail.level_uom || ''),
      minimal_jumlah_produk: normalizeId(detail.minimal_jumlah_produk || '')
    });

    await loadProductsByPrincipal(form.id_principal);

    selectedProducts.value = normalizeList(detail.produk).map((id) => String(id));
    selectedBranches.value = normalizeList(detail.cabang).map((id) => String(id));
    selectedCustomers.value = normalizeList(detail.customer).map((id) => String(id));
    modalOpen.value = true;
  } catch (err) {
    actionError.value = normalizeError(err, 'Detail voucher belum bisa dimuat.');
  }
}

async function saveVoucher() {
  actionError.value = validateForm();
  if (actionError.value) return;

  saving.value = true;
  feedback.value = '';
  try {
    const payload = buildVoucherPayload();
    const tipe = Number(form.tipe_voucher || filters.tipe_voucher || 1);
    if (mode.value === 'create') {
      await createVoucher(tipe, payload);
      feedback.value = 'Voucher berhasil ditambahkan.';
    } else {
      await updateVoucher(tipe, payload);
      feedback.value = 'Voucher berhasil diperbarui.';
    }
    await loadRows();
    if (selectedRow.value) {
      const refreshed = rows.value.find((item) => String(item.id) === String(selectedRow.value.id));
      if (refreshed) {
        await openPreview(refreshed);
      }
    }
  } catch (err) {
    actionError.value = normalizeError(err, 'Data voucher belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function removeVoucher() {
  if (!selectedRow.value?.id) return;
  const confirmed = window.confirm('Hapus voucher yang sedang dipilih?');
  if (!confirmed) return;

  saving.value = true;
  actionError.value = '';
  feedback.value = '';
  try {
    await deleteVoucher(Number(filters.tipe_voucher || 1), selectedRow.value.id);
    modalOpen.value = false;
    selectedDetail.value = null;
    selectedRow.value = null;
    await loadRows();
  } catch (err) {
    actionError.value = normalizeError(err, 'Voucher belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  if (isCanvasManagement.value && !['2', '3'].includes(String(filters.tipe_voucher))) {
    filters.tipe_voucher = '2';
  }
  await Promise.all([loadReferences(), loadRows()]);
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      :title="isCanvasManagement ? 'Kelola Voucher Canvas' : 'Voucher'"
      :description="isCanvasManagement
        ? 'CRUD Voucher Canvas memakai master voucher yang sama dengan Promo. Pilih Canvas atau Promo All-In & Canvas agar voucher dapat dipakai di order Canvas.'
        : 'Master voucher terpusat untuk Promo All-In dan Canvas. Setiap voucher memiliki cakupan penggunaan yang jelas agar tidak dibuat dua kali.'"
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        {{ isCanvasManagement ? 'Tambah Voucher Canvas' : 'Tambah Voucher' }}
      </button>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Voucher</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Aktif</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.active.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Reguler</p>
        <p class="mt-3 text-2xl font-semibold text-sky-700">{{ summary.regular.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Produk</p>
        <p class="mt-3 text-2xl font-semibold text-amber-600">{{ summary.product.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="filterFields"
      @update:model-value="updateFilters"
      @submit="loadRows"
      @reset="resetFilters"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="voucher-workspace grid gap-6">
      <div class="voucher-table-wrap space-y-4">
        <p class="voucher-table-hint">
          Klik voucher untuk melihat detail. Geser tabel ke samping bila seluruh kolom belum terlihat.
        </p>
        <AppTable
          :rows="filteredRows"
          :columns="tableColumns"
          :loading="loading"
          :clickable-rows="true"
          row-key="id"
          :selected-key="selectedKey"
          empty-message="Belum ada data voucher untuk tipe yang dipilih."
          @row-click="openPreview"
        />
      </div>

      <aside class="voucher-detail-panel panel p-5">
        <div class="voucher-detail-heading flex flex-wrap items-start justify-between gap-4">
          <div class="min-w-0">
            <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Detail Voucher</p>
            <h3 class="mt-2 text-xl font-semibold text-slate-900">
              {{ selectedDetail?.nama_voucher || 'Pilih voucher' }}
            </h3>
            <p class="mt-1 text-sm text-slate-500">
              {{ selectedDetail?.kode_voucher || 'Klik salah satu baris voucher untuk melihat ringkasan lengkap.' }}
            </p>
          </div>
          <button
            v-if="selectedRow"
            class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            @click="openEdit()"
          >
            Edit Voucher
          </button>
        </div>

        <div v-if="detailLoading" class="mt-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          Memuat detail voucher...
        </div>

        <AppEmptyState
          v-else-if="!selectedDetail"
          title="Belum ada voucher dipilih"
          description="Detail voucher akan tampil di panel ini, termasuk periode, mode voucher, diskon, serta target produk, cabang, dan customer."
        />

        <div v-else class="voucher-detail-content mt-6 space-y-5">
          <div class="voucher-detail-grid grid gap-3">
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Principal</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedDetail.nama_principal || '-' }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Status</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ resolveVoucherStatusLabel(selectedDetail) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Periode</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">
                {{ formatPeriod(selectedDetail.tanggal_mulai, selectedDetail.tanggal_kadaluarsa) }}
              </p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Mode Voucher</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ detailModeLabel }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Berlaku untuk</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ resolveChannelScopeLabel(selectedDetail) }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Diskon</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ detailDiscountLabel }}</p>
            </div>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Minimal Belanja</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">
                {{ formatCurrency(selectedDetail.minimal_subtotal_pembelian || 0) }}
              </p>
            </div>
          </div>

          <div class="voucher-detail-lower grid gap-5">
            <div class="rounded-2xl border border-slate-200 bg-white p-4">
              <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Target Voucher</p>
              <p class="mt-2 text-sm font-semibold text-slate-900">{{ detailScopeSummary }}</p>
              <div class="mt-4 space-y-4">
                <div>
                  <p class="text-sm font-medium text-slate-700">Produk</p>
                  <div class="mt-2 flex flex-wrap gap-2">
                    <span
                      v-for="item in detailProducts"
                      :key="item"
                      class="rounded-full bg-sky-100 px-3 py-1 text-xs font-semibold text-sky-700"
                    >
                      {{ item }}
                    </span>
                    <span v-if="!detailProducts.length" class="text-sm text-slate-400">Tidak ada produk spesifik.</span>
                  </div>
                </div>
                <div>
                  <p class="text-sm font-medium text-slate-700">Cabang</p>
                  <div class="mt-2 flex flex-wrap gap-2">
                    <span
                      v-for="item in detailBranches"
                      :key="item"
                      class="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700"
                    >
                      {{ item }}
                    </span>
                    <span v-if="!detailBranches.length" class="text-sm text-slate-400">Tidak ada cabang spesifik.</span>
                  </div>
                </div>
                <div>
                  <p class="text-sm font-medium text-slate-700">Customer</p>
                  <div class="mt-2 flex flex-wrap gap-2">
                    <span
                      v-for="item in detailCustomers"
                      :key="item"
                      class="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700"
                    >
                      {{ item }}
                    </span>
                    <span v-if="!detailCustomers.length" class="text-sm text-slate-400">Tidak ada customer spesifik.</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Catatan & Syarat</p>
              <div class="mt-4 space-y-3 text-sm text-slate-700">
                <div>
                  <p class="font-medium text-slate-900">Keterangan</p>
                  <p class="mt-1">{{ selectedDetail.keterangan || '-' }}</p>
                </div>
                <div>
                  <p class="font-medium text-slate-900">Syarat Ketentuan</p>
                  <p class="mt-1 whitespace-pre-line">{{ selectedDetail.syarat_ketentuan || '-' }}</p>
                </div>
                <div>
                  <p class="font-medium text-slate-900">Syarat Wajib</p>
                  <p class="mt-1 whitespace-pre-line">{{ selectedDetail.syarat_wajib || '-' }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </aside>
    </section>

    <AppModal
      :open="modalOpen"
      :title="mode === 'create' ? (isCanvasManagement ? 'Tambah Voucher Canvas' : 'Tambah Voucher') : 'Edit Voucher'"
      :description="isCanvasManagement
        ? 'Voucher Canvas disimpan pada master Voucher yang sama. Cakupan penggunaan menentukan apakah voucher hanya untuk Canvas atau juga dapat dipakai pada Promo All-In.'
        : 'Form voucher terpusat: pilih cakupan penggunaan agar voucher tidak dibuat dua kali untuk Promo All-In dan Canvas.'"
      size="7xl"
      @close="modalOpen = false"
    >
      <div class="space-y-6">
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>
        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>

        <div class="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
          <section class="space-y-4">
            <div class="grid gap-4 md:grid-cols-2">
              <AppSearchSelect v-model="form.tipe_voucher" label="Tipe Voucher" placeholder="Pilih tipe voucher" :options="formVoucherTypeOptions" />
              <AppSearchSelect v-model="form.channel_scope" label="Berlaku untuk" placeholder="Pilih kanal penggunaan" :options="formChannelScopeOptions" />
              <AppSearchSelect
                v-model="form.id_cabang_filter"
                label="Cabang"
                placeholder="Pilih cabang"
                :options="formBranchOptions"
                :disabled="!canAccessAllBranches"
              />
              <AppSearchSelect
                v-model="form.id_perusahaan"
                label="Perusahaan"
                placeholder="Pilih perusahaan"
                :options="companyOptions"
                :disabled="!form.id_cabang_filter"
              />
              <AppSearchSelect
                v-model="form.id_principal"
                label="Principal"
                placeholder="Pilih principal"
                :options="principalOptions"
                :disabled="!form.id_perusahaan"
              />
              <AppFormField v-model="form.nama" label="Nama Voucher" placeholder="Masukkan nama voucher" />
              <AppSearchSelect v-model="form.status_diskon" label="Status Voucher" placeholder="Pilih status" :options="statusOptions" />
              <AppFormField v-model="form.tanggal_mulai" label="Tanggal Mulai" type="date" />
              <AppFormField v-model="form.tanggal_kadaluarsa" label="Tanggal Kadaluarsa" type="date" />
              <AppFormField v-model="form.minimal_subtotal_pembelian" label="Minimal Subtotal Pembelian" type="number" min="0" />
              <AppFormField v-model="form.upload_file" label="PIC Voucher / File" placeholder="URL atau path file gambar voucher" />
            </div>

            <div class="grid gap-4 md:grid-cols-2">
              <AppSearchSelect
                v-if="!isTypeOne"
                v-model="form.jenis_voucher"
                label="Mode Voucher"
                placeholder="Pilih mode"
                :options="jenisVoucherOptions"
              />
              <AppSearchSelect
                v-if="isProductVoucher"
                v-model="form.kategori_voucher"
                label="Kategori Diskon"
                placeholder="Pilih kategori"
                :options="kategoriVoucherOptions"
              />
              <AppFormField
                v-if="isTypeOne || !isProductVoucher || Number(form.kategori_voucher) === 1"
                v-model="form.persen_diskon"
                label="Persentase Diskon"
                type="number"
                min="0"
                max="100"
              />
              <AppFormField
                v-if="isProductVoucher && Number(form.kategori_voucher) === 2"
                v-model="form.nilai_diskon"
                label="Nominal Diskon"
                type="number"
                min="0"
              />
              <AppFormField v-if="isProductVoucher" v-model="form.limit" label="Budget / Limit Diskon" type="number" min="0" />
              <AppFormField v-if="isTypeTwo && isProductVoucher" v-model="form.level_uom" label="Level UOM" type="number" min="0" />
              <AppFormField v-if="isTypeTwo && isProductVoucher" v-model="form.minimal_jumlah_produk" label="Minimal Jumlah Produk" type="number" min="0" />
            </div>

            <div class="grid gap-4">
              <AppFormField v-model="form.keterangan" label="Keterangan" type="textarea" placeholder="Tambahkan keterangan voucher" />
              <AppFormField
                v-model="form.syarat_ketentuan"
                label="Syarat Ketentuan"
                type="textarea"
                placeholder="Tuliskan syarat dan ketentuan voucher"
              />
              <AppFormField
                v-model="form.syarat_wajib"
                label="Syarat Wajib"
                type="textarea"
                placeholder="Tuliskan syarat wajib voucher"
              />
            </div>
          </section>

          <section class="space-y-5">
            <div class="rounded-3xl border border-slate-200 bg-slate-50 p-4">
              <div class="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Produk Terkait</h3>
                  <p class="text-xs text-slate-500">Produk hadiah atau produk target untuk voucher produk.</p>
                </div>
                <span class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600">
                  {{ selectedProducts.length }} dipilih
                </span>
              </div>
              <input
                v-model="productSearch"
                type="text"
                class="mb-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400"
                placeholder="Cari produk"
              >
              <div class="max-h-56 space-y-2 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3">
                <label v-for="item in filteredProductOptions" :key="item.id" class="flex items-start gap-3 rounded-xl px-2 py-2 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    :checked="selectedProducts.includes(String(item.id))"
                    @change="toggleSelection(selectedProducts, item.id)"
                  >
                  <span class="text-sm text-slate-700">{{ item.nama || item.label || `Produk ${item.id}` }}</span>
                </label>
                <p v-if="!filteredProductOptions.length && !referencesLoading" class="text-sm text-slate-500">
                  Pilih principal dulu atau belum ada produk yang cocok.
                </p>
              </div>
            </div>

            <div v-if="!isTypeOne" class="rounded-3xl border border-slate-200 bg-slate-50 p-4">
              <div class="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Cabang Target</h3>
                  <p class="text-xs text-slate-500">Cabang yang diizinkan menggunakan voucher ini.</p>
                </div>
                <span class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600">
                  {{ selectedBranches.length }} dipilih
                </span>
              </div>
              <input
                v-model="branchSearch"
                type="text"
                class="mb-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400"
                placeholder="Cari cabang"
              >
              <div class="max-h-48 space-y-2 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3">
                <label v-for="item in filteredBranchOptions" :key="item.id" class="flex items-start gap-3 rounded-xl px-2 py-2 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    :checked="selectedBranches.includes(String(item.id))"
                    @change="toggleSelection(selectedBranches, item.id)"
                  >
                  <span class="text-sm text-slate-700">{{ item.nama || `Cabang ${item.id}` }}</span>
                </label>
              </div>
            </div>

            <div v-if="isTypeThree" class="rounded-3xl border border-slate-200 bg-slate-50 p-4">
              <div class="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-slate-900">Customer Target</h3>
                  <p class="text-xs text-slate-500">Customer khusus untuk voucher tipe 3.</p>
                </div>
                <span class="rounded-full bg-white px-3 py-1 text-xs font-semibold text-slate-600">
                  {{ selectedCustomers.length }} dipilih
                </span>
              </div>
              <input
                v-model="customerSearch"
                type="text"
                class="mb-3 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400"
                placeholder="Cari customer"
              >
              <div class="max-h-56 space-y-2 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-3">
                <label v-for="item in filteredCustomerOptions" :key="item.id" class="flex items-start gap-3 rounded-xl px-2 py-2 hover:bg-slate-50">
                  <input
                    type="checkbox"
                    class="mt-1 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    :checked="selectedCustomers.includes(String(item.id))"
                    @change="toggleSelection(selectedCustomers, item.id)"
                  >
                  <span class="text-sm text-slate-700">
                    {{ [item.kode, item.nama].filter(Boolean).join(' | ') || `Customer ${item.id}` }}
                  </span>
                </label>
              </div>
            </div>
          </section>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div class="text-sm text-slate-500">
            Produk {{ selectedProducts.length }}, Cabang {{ selectedBranches.length }}, Customer {{ selectedCustomers.length }}
          </div>
          <div class="flex flex-wrap gap-2">
            <button
              v-if="mode === 'edit' && selectedRow"
              class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60"
              :disabled="saving"
              @click="removeVoucher"
            >
              Hapus
            </button>
            <button
              class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 disabled:opacity-60"
              :disabled="saving"
              @click="modalOpen = false"
            >
              Tutup
            </button>
            <button
              class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
              :disabled="saving"
              @click="saveVoucher"
            >
              {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan Voucher' : 'Update Voucher' }}
            </button>
          </div>
        </div>
      </template>
    </AppModal>
  </div>
</template>

<style scoped>
.voucher-workspace {
  grid-template-columns: minmax(0, 1fr);
  align-items: start;
}

.voucher-table-wrap,
.voucher-detail-panel {
  min-width: 0;
}

.voucher-detail-panel {
  width: 100%;
  max-width: none;
}

.voucher-detail-heading > div:first-child {
  flex: 1 1 360px;
}

.voucher-table-hint {
  color: #64748b;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.45;
}

.dark .voucher-table-hint {
  color: #94a3b8;
}

/*
 * On a normal desktop the ERP sidebar leaves roughly 1,200px for this page.
 * Keeping the table on its own row makes the voucher detail usable instead of
 * compressing it into a narrow right rail.  AppTable owns the horizontal
 * scrollbar, so all table columns stay readable at every width.
 */
.voucher-table-wrap :deep(table) {
  min-width: 1280px;
}

.voucher-table-wrap :deep(.overflow-x-auto) {
  overscroll-behavior-x: contain;
  scrollbar-gutter: stable both-edges;
  touch-action: pan-x pan-y;
}

.voucher-table-wrap :deep(th) {
  white-space: nowrap;
}

.voucher-detail-grid {
  grid-template-columns: minmax(0, 1fr);
}

.voucher-detail-lower {
  grid-template-columns: minmax(0, 1fr);
}

.voucher-detail-panel :deep(p),
.voucher-detail-panel :deep(span) {
  overflow-wrap: anywhere;
}

@media (min-width: 640px) {
  .voucher-detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

/* The sidebar reduces a 1,100px browser viewport too much for a third card. */
@media (min-width: 1440px) {
  .voucher-detail-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .voucher-detail-lower {
    grid-template-columns: minmax(0, 1.2fr) minmax(330px, 0.8fr);
  }
}

/* Only use the two-pane workspace on genuinely ultra-wide displays. */
@media (min-width: 2100px) {
  .voucher-workspace {
    grid-template-columns: minmax(760px, 1.18fr) minmax(520px, 0.82fr);
  }

  .voucher-detail-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .voucher-detail-lower {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
