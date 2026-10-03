<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createCustomer,
  deleteCustomer,
  getBranches,
  getCompanies,
  getCustomerTypes,
  getCustomersTable,
  getProductPriceTypes,
  getRegionsLevel1,
  getRegionsLevel2,
  getRegionsLevel3,
  getRegionsLevel4,
  getRoutes,
  updateCustomer
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { branchMatchesCompany, getLoginBranchIds, getLoginCompanyIds, getRowBranchIds, getRowCompanyIds, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppDrawer from '@/shared/components/AppDrawer.vue';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const CUSTOMER_RESOURCE = 'master.customers';

const filters = reactive({ search: '' });
const form = reactive({
  kode: '',
  nama: '',
  id_tipe: '',
  id_cabang: [],
  id_perusahaan: [],
  id_rute: '',
  id_tipe_harga: '',
  alamat: '',
  telepon: '',
  telepon2: '',
  email: '',
  pic: '',
  status_pajak: '',
  jenis_identitas_pajak: '',
  npwp: '',
  no_rekening: '',
  is_ppn: '',
  nama_wajib_pajak: '',
  alamat_wajib_pajak: '',
  latitude: '',
  longitude: '',
  id_wilayah1: '',
  id_wilayah2: '',
  id_wilayah3: '',
  id_wilayah4: ''
});

const customers = ref([]);
const branches = ref([]);
const companies = ref([]);
const customerTypes = ref([]);
const routes = ref([]);
const priceTypes = ref([]);
const wilayah1Rows = ref([]);
const wilayah2Rows = ref([]);
const wilayah3Rows = ref([]);
const wilayah4Rows = ref([]);
const loading = ref(false);
const saving = ref(false);
const error = ref('');
const actionError = ref('');
const feedback = ref('');
const hasSubmitted = ref(false);
const drawerOpen = ref(false);
const mode = ref('create');
const selectedCustomer = ref(null);
const generatedCustomerCode = ref('');
const hydratingWilayah = ref(false);
const loginBranchIds = computed(() => getLoginBranchIds(auth.user));
const loginCompanyIds = computed(() => getLoginCompanyIds(auth.user));
const canCreateCustomer = computed(() => auth.canCreate(CUSTOMER_RESOURCE));
const canUpdateCustomer = computed(() => auth.canUpdate(CUSTOMER_RESOURCE));
const canDeleteCustomer = computed(() => auth.canDelete(CUSTOMER_RESOURCE));
const selectedBranchIds = computed(() => normalizeIds(form.id_cabang));
const selectedCompanyIdList = computed(() => normalizeIds(form.id_perusahaan));
const selectedBranches = computed(() => branches.value.filter((item) => selectedBranchIds.value.includes(String(item.id))));
const scopedBranches = computed(() => scopeRowsByLoginBranch(branches.value, auth));
const scopedCompanies = computed(() => {
  const allowedCompanyIds = new Set(loginCompanyIds.value.map(String));

  if (isSuperUser(auth) || !allowedCompanyIds.size) {
    return companies.value;
  }

  return companies.value.filter((item) => allowedCompanyIds.has(String(item.id)));
});
const scopedCustomers = computed(() => scopeRowsByLoginBranch(customers.value, auth));
const selectedBranchCompanyIds = computed(() => {
  if (!selectedBranchIds.value.length) return [];
  const ids = new Set();

  selectedBranches.value.forEach((branch) => {
    getRowCompanyIds(branch).forEach((id) => ids.add(String(id)));
  });

  companies.value.forEach((item) => {
    if (selectedBranchIds.value.some((branchId) => getRowBranchIds(item).includes(String(branchId)))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
});

const summaryCards = computed(() => {
  const rows = scopedCustomers.value;
  const branchCount = new Set(rows.map((item) => item.nama_cabang).filter(Boolean)).size;
  const typeCount = new Set(rows.map((item) => item.tipe).filter(Boolean)).size;
  const codedCount = rows.filter((item) => item.kode).length;

  return [
    { label: 'Customer Tampil', value: rows.length, note: 'Jumlah customer hasil pencarian aktif.' },
    { label: 'Cabang Terdeteksi', value: branchCount, note: 'Persebaran cabang pada hasil saat ini.' },
    { label: 'Tipe Customer', value: typeCount, note: 'Membantu audit segmentasi customer.' },
    { label: 'Kode Terisi', value: codedCount, note: 'Kontrol cepat customer yang sudah punya kode.' }
  ];
});

const branchOptions = computed(() =>
  scopedBranches.value
    .filter((item) => !selectedCompanyIdList.value.length || selectedCompanyIdList.value.some((companyId) => branchMatchesCompany(item, companyId)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama || `Cabang ${item.id}`}`
    }))
);

const companyOptions = computed(() =>
  scopedCompanies.value
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || 'Perusahaan'}`
    }))
);

const customerTypeOptions = computed(() =>
  customerTypes.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Tipe ${item.id}`
  }))
);

const routeOptions = computed(() =>
  routes.value
    .filter((item) => !selectedBranchIds.value.length || selectedBranchIds.value.includes(String(item.id_cabang)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode ? `${item.kode} - ` : ''}${item.nama_rute || item.nama || `Rute ${item.id}`}`
    }))
);

const priceTypeOptions = computed(() =>
  priceTypes.value.map((item) => ({
    value: String(item.id),
    label: item.nama || item.label || `Tipe Harga ${item.id}`
  }))
);

const taxStatusOptions = [
  { value: 'pkp', label: 'PKP' },
  { value: 'non_pkp', label: 'Non PKP' },
  { value: 'npwp', label: 'NPWP' },
  { value: 'lain_lain', label: 'Lain-lain' }
];

const taxIdentityOptions = [
  { value: 'npwp', label: 'NPWP' },
  { value: 'nik', label: 'NIK' },
  { value: 'lain_lain', label: 'Lain-lain' }
];

const taxIdentityLabel = computed(() => {
  if (form.jenis_identitas_pajak === 'nik') return 'NIK';
  if (form.jenis_identitas_pajak === 'lain_lain') return 'NPWP / NIK / Identitas Lain';
  return 'NPWP';
});

const taxIdentityPlaceholder = computed(() => {
  if (form.jenis_identitas_pajak === 'nik') return 'Contoh: 3372xxxxxxxxxxxx';
  if (form.jenis_identitas_pajak === 'lain_lain') return 'Isi nomor identitas pajak/customer';
  return 'Contoh: 01.234.567.8-999.000';
});

const wilayah1Options = computed(() => wilayah1Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));
const wilayah2Options = computed(() => wilayah2Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));
const wilayah3Options = computed(() => wilayah3Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));
const wilayah4Options = computed(() => wilayah4Rows.value.map((item) => ({ value: String(item.id), label: item.nama || `Wilayah ${item.id}` })));

const queryHint = computed(() => {
  if (!hasSubmitted.value) return 'Cari nama atau kode customer untuk memuat daftar customer yang relevan.';
  if (!customers.value.length && !loading.value) return 'Belum ada customer yang cocok dengan pencarian saat ini.';
  return 'Klik baris untuk edit customer. Tambah customer baru sudah bisa dilakukan langsung dari halaman ini.';
});

const customerColumns = [
  { key: 'identity', label: 'Customer', render: (row) => `${row.nama || '-'}${row.kode ? ` (${row.kode})` : ''}` },
  { key: 'tipe', label: 'Tipe' },
  { key: 'nama_perusahaan_list', label: 'Perusahaan', render: (row) => row.nama_perusahaan_list || row.nama_perusahaan || '-' },
  { key: 'nama_cabang_list', label: 'Cabang', render: (row) => row.nama_cabang_list || row.nama_cabang || '-' },
  { key: 'nama_rute', label: 'Rute' },
  { key: 'status_pajak', label: 'Pajak', render: (row) => taxStatusOptions.find((item) => item.value === normalizeTaxStatus(row))?.label || '-' },
  { key: 'npwp', label: 'NPWP/NIK', render: (row) => row.npwp || '-' },
  { key: 'pic', label: 'PIC' }
];

function normalizeIds(value) {
  const rawValues = Array.isArray(value) ? value : String(value || '').split(',');
  return rawValues.map((item) => String(item || '').trim()).filter(Boolean);
}

function normalizeId(value) {
  return value === undefined || value === null || value === '' ? '' : String(value);
}

function normalizeTaxStatus(row = {}) {
  const rawStatus = String(row.status_pajak || row.status_pkp || '').trim().toLowerCase();
  if (['pkp', 'non_pkp', 'npwp', 'lain_lain'].includes(rawStatus)) return rawStatus;
  if (String(row.is_ppn ?? '').trim() === '1') return 'pkp';
  return 'non_pkp';
}

function normalizeTaxIdentityType(row = {}, status = '') {
  const rawType = String(row.jenis_identitas_pajak || row.tipe_identitas_pajak || row.tipe_npwp || '').trim().toLowerCase();
  if (['npwp', 'nik', 'lain_lain'].includes(rawType)) return rawType;
  if (status === 'pkp' || status === 'npwp') return 'npwp';
  return 'nik';
}

function resetForm() {
  Object.assign(form, {
    kode: '',
    nama: '',
    id_tipe: '',
    id_cabang: !isSuperUser(auth) && loginBranchIds.value.length ? [...loginBranchIds.value] : [],
    id_perusahaan: !isSuperUser(auth) && loginCompanyIds.value.length ? [...loginCompanyIds.value] : [],
    id_rute: '',
    id_tipe_harga: '',
    alamat: '',
    telepon: '',
    telepon2: '',
    email: '',
    pic: '',
    status_pajak: 'non_pkp',
    jenis_identitas_pajak: 'nik',
    npwp: '',
    no_rekening: '',
    is_ppn: '0',
    nama_wajib_pajak: '',
    alamat_wajib_pajak: '',
    latitude: '',
    longitude: '',
    id_wilayah1: '',
    id_wilayah2: '',
    id_wilayah3: '',
    id_wilayah4: ''
  });
  wilayah2Rows.value = [];
  wilayah3Rows.value = [];
  wilayah4Rows.value = [];
  generatedCustomerCode.value = '';
  syncCompanyFromBranch(true);
}

function buildPayload() {
  const branchIds = selectedBranchIds.value;
  const companyIds = selectedCompanyIdList.value;
  const payload = {};
  Object.entries(form).forEach(([key, value]) => {
    if (key === 'id_cabang' || key === 'id_perusahaan') return;
    if (value !== '') {
      payload[key] = value;
    }
  });
  payload.status_pajak = form.status_pajak || 'non_pkp';
  payload.jenis_identitas_pajak = form.jenis_identitas_pajak || (payload.status_pajak === 'pkp' || payload.status_pajak === 'npwp' ? 'npwp' : 'nik');
  payload.is_ppn = payload.status_pajak === 'pkp' ? '1' : '0';
  payload.id_cabang = branchIds[0] || '';
  payload.id_cabang_list = branchIds.join(',');
  payload.id_perusahaan_list = companyIds.join(',');
  return payload;
}

function syncCompanyFromBranch(preserveCurrent = false) {
  if (!selectedBranchIds.value.length) {
    if (!preserveCurrent) form.id_perusahaan = [];
    return;
  }

  const allowedCompanyIds = selectedBranchCompanyIds.value;
  const currentCompanyIds = selectedCompanyIdList.value;

  if (!currentCompanyIds.length && allowedCompanyIds.length) {
    form.id_perusahaan = allowedCompanyIds;
    return;
  }

  const nextCompanyIds = currentCompanyIds.filter((id) => allowedCompanyIds.includes(String(id)));

  if (!preserveCurrent || nextCompanyIds.length !== currentCompanyIds.length) {
    form.id_perusahaan = nextCompanyIds;
  }
}

function syncBranchesFromCompany(preserveCurrent = false) {
  if (!selectedCompanyIdList.value.length) {
    if (!preserveCurrent) form.id_cabang = [];
    return;
  }

  const allowedBranchIds = scopedBranches.value
    .filter((item) => selectedCompanyIdList.value.some((companyId) => branchMatchesCompany(item, companyId)))
    .map((item) => String(item.id));
  const currentBranchIds = selectedBranchIds.value;
  const nextBranchIds = currentBranchIds.filter((id) => allowedBranchIds.includes(String(id)));

  if (!preserveCurrent || nextBranchIds.length !== currentBranchIds.length) {
    form.id_cabang = nextBranchIds;
  }
}

function generateCustomerCode() {
  const branch = branches.value.find((item) => selectedBranchIds.value.includes(String(item.id)));
  const prefix = String(branch?.kode || branch?.nama || 'CUS')
    .replace(/[^a-zA-Z0-9]/g, '')
    .slice(0, 4)
    .toUpperCase()
    .padEnd(3, '0');
  const suffix = Date.now().toString().slice(-7);
  return `${prefix}${suffix}`;
}

function refreshGeneratedCode(force = false) {
  if (mode.value !== 'create') return;
  if (!force && form.kode && form.kode !== generatedCustomerCode.value) return;
  generatedCustomerCode.value = generateCustomerCode();
  form.kode = generatedCustomerCode.value;
}

function isDigitsOnly(value) {
  return !String(value || '').trim() || /^[0-9]+$/.test(String(value).trim());
}

function isNumericValue(value) {
  return !String(value || '').trim() || !Number.isNaN(Number(value));
}

function isDecimalText(value) {
  return !String(value || '').trim() || /^-?\d+(\.\d+)?$/.test(String(value).trim());
}

function validateForm() {
  const requiredFields = [
    ['kode', 'Kode customer wajib diisi.'],
    ['nama', 'Nama customer wajib diisi.'],
    ['id_tipe', 'Tipe customer wajib dipilih.'],
    ['id_tipe_harga', 'Tipe harga wajib dipilih.']
  ];

  const missing = requiredFields.find(([key]) => !String(form[key] || '').trim());
  if (missing) return missing[1];
  if (!selectedCompanyIdList.value.length) return 'Perusahaan wajib dipilih.';
  if (!selectedBranchIds.value.length) return 'Cabang wajib dipilih.';

  if (!isDigitsOnly(form.telepon)) return 'Telepon 1 hanya boleh berisi angka.';
  if (!isDigitsOnly(form.telepon2)) return 'Telepon 2 hanya boleh berisi angka.';
  if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(form.email).trim())) return 'Format email belum valid.';
  if (!isDecimalText(form.latitude)) return 'Latitude harus berupa angka desimal, contoh -7.5667.';
  if (!isDecimalText(form.longitude)) return 'Longitude harus berupa angka desimal, contoh 110.8167.';

  return '';
}

async function loadReferences() {
  const [branchResponse, companyResponse, typeResponse, routeResponse, priceTypeResponse, wilayah1Response] = await Promise.all([
    getBranches(),
    getCompanies(),
    getCustomerTypes(),
    getRoutes(),
    getProductPriceTypes(),
    getRegionsLevel1()
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  customerTypes.value = normalizeList(unwrapResponse(typeResponse));
  routes.value = normalizeList(unwrapResponse(routeResponse));
  priceTypes.value = normalizeList(unwrapResponse(priceTypeResponse));
  wilayah1Rows.value = normalizeList(unwrapResponse(wilayah1Response));
  if (!isSuperUser(auth) && loginBranchIds.value.length) {
    form.id_cabang = [...loginBranchIds.value];
    form.id_perusahaan = loginCompanyIds.value.length ? [...loginCompanyIds.value] : [];
    syncCompanyFromBranch(true);
  }
}

async function loadWilayah2(id, preserveValue = false) {
  if (!id) {
    wilayah2Rows.value = [];
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
    form.id_wilayah2 = '';
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel2(id);
  wilayah2Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah2 = '';
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
  }
}

async function loadWilayah3(id, preserveValue = false) {
  if (!id) {
    wilayah3Rows.value = [];
    wilayah4Rows.value = [];
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel3(id);
  wilayah3Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah3 = '';
    form.id_wilayah4 = '';
    wilayah4Rows.value = [];
  }
}

async function loadWilayah4(id, preserveValue = false) {
  if (!id) {
    wilayah4Rows.value = [];
    form.id_wilayah4 = '';
    return;
  }

  const response = await getRegionsLevel4(id);
  wilayah4Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah4 = '';
  }
}

watch(
  () => form.id_wilayah1,
  async (value, previousValue) => {
    if (hydratingWilayah.value) return;
    if (value !== previousValue) await loadWilayah2(value);
  }
);

watch(
  () => form.id_wilayah2,
  async (value, previousValue) => {
    if (hydratingWilayah.value) return;
    if (value !== previousValue) await loadWilayah3(value);
  }
);

watch(
  () => form.id_wilayah3,
  async (value, previousValue) => {
    if (hydratingWilayah.value) return;
    if (value !== previousValue) await loadWilayah4(value);
  }
);

watch(
  () => form.id_cabang,
  () => {
    syncCompanyFromBranch(true);
    if (form.id_rute && !routeOptions.value.some((item) => String(item.value) === String(form.id_rute))) {
      form.id_rute = '';
    }
    refreshGeneratedCode();
  },
  { deep: true }
);

watch(
  () => form.id_perusahaan,
  () => {
    syncBranchesFromCompany(true);
  },
  { deep: true }
);

watch(
  () => form.status_pajak,
  (value) => {
    if (value === 'pkp' || value === 'npwp') {
      form.jenis_identitas_pajak = 'npwp';
      form.is_ppn = '1';
    } else if (value === 'non_pkp') {
      form.jenis_identitas_pajak = 'nik';
      form.is_ppn = '0';
    } else {
      form.jenis_identitas_pajak = form.jenis_identitas_pajak || 'lain_lain';
      form.is_ppn = '0';
    }
  }
);

async function submit() {
  hasSubmitted.value = true;
  loading.value = true;
  error.value = '';

  try {
    const response = await getCustomersTable({ search: filters.search.trim() });
    const payload = unwrapResponse(response);
    customers.value = normalizeList(payload?.data || payload);
    return customers.value;
  } catch (err) {
    error.value = normalizeError(err, 'Data customer belum bisa dimuat.');
    customers.value = [];
    return [];
  } finally {
    loading.value = false;
  }
}

function reset() {
  filters.search = '';
  customers.value = [];
  error.value = '';
  hasSubmitted.value = false;
}

function openCreate() {
  if (!canCreateCustomer.value) {
    actionError.value = 'Hak akses Anda hanya view, sehingga tambah customer tidak tersedia.';
    return;
  }

  mode.value = 'create';
  selectedCustomer.value = null;
  resetForm();
  refreshGeneratedCode(true);
  feedback.value = '';
  actionError.value = '';
  drawerOpen.value = true;
}

async function openEdit(row) {
  if (!canUpdateCustomer.value) {
    return;
  }

  mode.value = 'edit';
  selectedCustomer.value = row;
  const taxStatus = normalizeTaxStatus(row);
  hydratingWilayah.value = true;
  Object.assign(form, {
    kode: row?.kode || '',
    nama: row?.nama || '',
    id_tipe: normalizeId(row?.id_tipe),
    id_cabang: normalizeIds(row?.id_cabang_list || row?.cabang_ids || row?.id_cabang),
    id_perusahaan: normalizeIds(row?.id_perusahaan_list || row?.perusahaan_ids || row?.id_perusahaan),
    id_rute: normalizeId(row?.id_rute),
    id_tipe_harga: normalizeId(row?.id_tipe_harga),
    alamat: row?.alamat || '',
    telepon: row?.telepon || '',
    telepon2: row?.telepon2 || '',
    email: row?.email || '',
    pic: row?.pic || '',
    status_pajak: taxStatus,
    jenis_identitas_pajak: normalizeTaxIdentityType(row, taxStatus),
    npwp: row?.npwp || '',
    no_rekening: row?.no_rekening || '',
    is_ppn: taxStatus === 'pkp' ? '1' : '0',
    nama_wajib_pajak: row?.nama_wajib_pajak || '',
    alamat_wajib_pajak: row?.alamat_wajib_pajak || '',
    latitude: row?.latitude || '',
    longitude: row?.longitude || '',
    id_wilayah1: normalizeId(row?.id_wilayah1),
    id_wilayah2: normalizeId(row?.id_wilayah2),
    id_wilayah3: normalizeId(row?.id_wilayah3),
    id_wilayah4: normalizeId(row?.id_wilayah4)
  });
  try {
    syncCompanyFromBranch(true);
    await loadWilayah2(form.id_wilayah1, true);
    await loadWilayah3(form.id_wilayah2, true);
    await loadWilayah4(form.id_wilayah3, true);
  } finally {
    hydratingWilayah.value = false;
  }
  feedback.value = '';
  actionError.value = '';
  drawerOpen.value = true;
}

function closeDrawer() {
  drawerOpen.value = false;
}

async function save() {
  if (mode.value === 'create' && !canCreateCustomer.value) {
    actionError.value = 'Hak akses Anda hanya view, sehingga tidak bisa menambahkan customer.';
    return;
  }

  if (mode.value === 'edit' && !canUpdateCustomer.value) {
    actionError.value = 'Hak akses Anda hanya view, sehingga tidak bisa mengubah customer.';
    return;
  }

  const validationError = validateForm();
  if (validationError) {
    actionError.value = validationError;
    return;
  }

  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createCustomer(buildPayload());
      feedback.value = 'Customer berhasil ditambahkan.';
      resetForm();
    } else {
      await updateCustomer(selectedCustomer.value?.id, buildPayload());
      feedback.value = 'Customer berhasil diperbarui.';
    }
    await submit();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data customer belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!canDeleteCustomer.value) {
    actionError.value = 'Hak akses Anda tidak memiliki izin hapus customer.';
    return;
  }

  if (!selectedCustomer.value?.id) return;
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    await deleteCustomer(selectedCustomer.value.id);
    drawerOpen.value = false;
    await submit();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data customer belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([loadReferences(), submit()]);
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Master Customer"
      description="Master customer sekarang naik ke CRUD operasional penuh: identitas, cabang, rute, tipe harga, pajak, kontak, alamat, dan wilayah bertingkat."
    >
      <button
        class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500"
        :disabled="!canCreateCustomer"
        @click="openCreate"
      >
        Tambah Customer
      </button>
    </PageHeader>

    <section class="rounded-[32px] border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
  <div class="mb-5 flex flex-wrap items-center justify-between gap-4">
    <div>
      <h3 class="text-lg font-bold text-slate-950 dark:text-white">
        Customer Data Table
      </h3>
      <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Cari customer berdasarkan nama atau kode. Data dibatasi 100 baris agar tetap ringan.
      </p>
    </div>

    <span class="rounded-full bg-brand-50 px-3 py-1 text-xs font-bold uppercase tracking-[0.2em] text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
      {{ scopedCustomers.length }} Data
    </span>
  </div>

  <div class="rounded-3xl border border-slate-200 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900">
    <div class="grid gap-3 xl:grid-cols-[1fr_auto_auto]">
      <label class="block">
        <span class="mb-1 block text-xs font-bold uppercase tracking-[0.22em] text-slate-400">
          Cari Customer
        </span>
        <input
          v-model="filters.search"
          type="text"
          placeholder="Nama customer / kode customer"
          class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-brand-400 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          @keyup.enter="submit"
        />
      </label>

      <button class="rounded-2xl bg-brand-600 px-5 py-3 text-sm font-bold text-white shadow-sm hover:bg-brand-700" @click="submit">
        Tampilkan
      </button>

      <button class="rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200 dark:hover:bg-slate-800" @click="reset">
        Reset
      </button>
    </div>

    <p class="mt-3 text-sm text-slate-500 dark:text-slate-400">{{ queryHint }}</p>
  </div>

  <section
    v-if="error"
    class="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300"
  >
    {{ error }}
  </section>

  <div v-if="hasSubmitted || loading" class="mt-5 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
    <AppTable
      :rows="scopedCustomers"
      :columns="customerColumns"
      :loading="loading"
      :clickable-rows="canUpdateCustomer"
      :selected-key="selectedCustomer?.id || ''"
      empty-message="Belum ada customer yang cocok dengan pencarian saat ini."
      @row-click="openEdit"
    />
  </div>
</section>

    <AppDrawer
  :open="drawerOpen"
  :title="mode === 'create' ? 'Tambah Customer ERP' : selectedCustomer?.nama ? `Edit Customer: ${selectedCustomer.nama}` : 'Edit Customer ERP'"
  panel-class="max-w-6xl"
  @close="closeDrawer"
>
      <div class="space-y-6 pb-8">
        <section class="rounded-2xl border border-slate-200 p-4">
          <h4 class="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Identitas Utama</h4>
          <div class="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            <AppFormField v-model="form.kode" label="Kode Customer *" placeholder="Otomatis, contoh: SLO1234567" />
            <AppFormField v-model="form.nama" label="Nama Customer *" placeholder="Contoh: Luwes Kestalan" />
            <AppSearchSelect v-model="form.id_tipe" label="Tipe Customer *" placeholder="Pilih tipe customer" :options="customerTypeOptions" />
            <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan *" placeholder="Pilih perusahaan" :options="companyOptions" multiple empty-text="Perusahaan belum tersedia." />
            <AppSearchSelect v-model="form.id_cabang" label="Cabang *" placeholder="Pilih cabang" :options="branchOptions" :disabled="!selectedCompanyIdList.length || (!isSuperUser(auth) && !!loginBranchIds.length)" multiple empty-text="Pilih perusahaan dahulu atau cabang belum tersedia." />
            <AppSearchSelect v-model="form.id_rute" label="Rute" placeholder="Pilih rute" :options="routeOptions" :disabled="!selectedBranchIds.length" empty-text="Pilih cabang dahulu atau rute belum tersedia." />
            <AppSearchSelect v-model="form.id_tipe_harga" label="Tipe Harga *" placeholder="Pilih tipe harga" :options="priceTypeOptions" />
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 p-4">
          <h4 class="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Kontak & Lokasi</h4>
          <div class="mt-4 grid gap-4 sm:grid-cols-2">
            <AppFormField v-model="form.pic" label="PIC" placeholder="Nama penanggung jawab toko" />
            <AppFormField v-model="form.email" label="Email" type="email" placeholder="contoh@domain.com" />
            <AppFormField v-model="form.telepon" label="Telepon 1" type="number" placeholder="Contoh: 081234567890" />
            <AppFormField v-model="form.telepon2" label="Telepon 2" type="number" placeholder="Opsional, angka saja" />
            <AppFormField v-model="form.latitude" label="Latitude" placeholder="Contoh: -7.5667" />
            <AppFormField v-model="form.longitude" label="Longitude" placeholder="Contoh: 110.8167" />
          </div>
          <label class="mt-4 block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700">Alamat</span>
            <textarea v-model="form.alamat" rows="3" placeholder="Contoh: Jl. Slamet Riyadi No. 10, Surakarta" class="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-brand-400" />
          </label>
        </section>

        <section class="rounded-2xl border border-slate-200 p-4">
          <h4 class="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Wilayah Bertingkat</h4>
          <div class="mt-4 grid gap-4 sm:grid-cols-2">
            <AppSearchSelect v-model="form.id_wilayah1" label="Wilayah 1 = Provinsi" placeholder="Pilih provinsi" :options="wilayah1Options" />
            <AppSearchSelect v-model="form.id_wilayah2" label="Wilayah 2 = Kota/Kabupaten" placeholder="Pilih kota/kabupaten" :options="wilayah2Options" empty-text="Pilih provinsi dahulu." />
            <AppSearchSelect v-model="form.id_wilayah3" label="Wilayah 3 = Kecamatan" placeholder="Pilih kecamatan" :options="wilayah3Options" empty-text="Pilih kota/kabupaten dahulu." />
            <AppSearchSelect v-model="form.id_wilayah4" label="Wilayah 4 = Kelurahan/Desa" placeholder="Pilih kelurahan/desa" :options="wilayah4Options" empty-text="Pilih kecamatan dahulu." />
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 p-4">
          <h4 class="text-sm font-semibold uppercase tracking-[0.2em] text-slate-500">Pajak & Rekening</h4>
          <div class="mt-4 grid gap-4 sm:grid-cols-2">
            <AppSearchSelect v-model="form.status_pajak" label="Status Pajak / PKP" placeholder="Pilih status pajak" :options="taxStatusOptions" />
            <AppSearchSelect v-model="form.jenis_identitas_pajak" label="Jenis Identitas Pajak" placeholder="Pilih jenis identitas" :options="taxIdentityOptions" />
            <AppFormField v-model="form.npwp" :label="taxIdentityLabel" :placeholder="taxIdentityPlaceholder" />
            <AppFormField v-model="form.no_rekening" label="No Rekening" placeholder="Contoh: 1234567890" />
            <AppFormField v-model="form.nama_wajib_pajak" label="Nama Wajib Pajak" placeholder="Nama sesuai dokumen pajak" />
          </div>
          <label class="mt-4 block">
            <span class="mb-1.5 block text-sm font-medium text-slate-700">Alamat Wajib Pajak</span>
            <textarea v-model="form.alamat_wajib_pajak" rows="3" placeholder="Alamat sesuai dokumen pajak" class="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none transition focus:border-brand-400" />
          </label>
        </section>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="sticky bottom-0 -mx-6 flex flex-wrap gap-2 border-t border-slate-200 bg-white px-6 py-4">
          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
            :disabled="saving || (mode === 'create' ? !canCreateCustomer : !canUpdateCustomer)"
            @click="save"
          >
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan Customer' : 'Update Customer' }}
          </button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700 disabled:opacity-60" :disabled="saving || !canDeleteCustomer" @click="remove">
            Hapus
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50" :disabled="saving" @click="closeDrawer">
            Tutup
          </button>
        </div>
      </div>
    </AppDrawer>
  </div>
</template>
