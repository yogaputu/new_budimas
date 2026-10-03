<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createSales,
  createSalesDetail,
  createSalesPrincipalAssignment,
  deleteSales,
  deleteSalesDetail,
  deleteSalesPrincipalAssignment,
  getBranches,
  getCompanies,
  getPrincipals,
  getRegionsLevel1,
  getRegionsLevel2,
  getSales,
  getSalesDetails,
  getSalesPrincipalAssignments,
  getSalesTypes,
  getUsers,
  updateSales,
  updateSalesDetail,
  updateUser
} from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const SALES_POSITION_ID = '4';

const authStore = useAuthStore();
const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getSales());
const companies = ref([]);
const branches = ref([]);
const principals = ref([]);
const salesTypes = ref([]);
const users = ref([]);
const wilayah1Rows = ref([]);
const wilayah2Rows = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);
const detailRow = ref(null);
const salesDetailRows = ref([]);
const assignmentRows = ref([]);
const assignmentPrincipalIds = ref([]);
const assignmentPrincipalToAdd = ref('');
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginCompanyId = computed(() => getLoginCompanyId(authStore.user));
const selectedBranch = computed(() => branches.value.find((item) => String(item.id) === String(form.id_cabang || '')));
const selectedCompanyIds = computed(() => {
  if (!form.id_cabang) return [];
  const ids = new Set();
  const branchCompanyId = getRowCompanyId(selectedBranch.value);

  if (branchCompanyId) ids.add(String(branchCompanyId));

  companies.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(form.id_cabang))) {
      ids.add(String(item.id));
    }
  });

  return Array.from(ids);
});
const scopedItems = computed(() => scopeRowsByLoginBranch(items.value, authStore));
const scopedBranches = computed(() => scopeRowsByLoginBranch(branches.value, authStore));
const scopedCompanies = computed(() => {
  const companyIds = new Set(scopedBranches.value.map((item) => String(getRowCompanyId(item))).filter(Boolean));

  if (isSuperUser(authStore) || !companyIds.size) {
    return companies.value;
  }

  return companies.value.filter((item) => companyIds.has(String(item.id)));
});

const form = reactive({
  id_perusahaan: '',
  id_user: '',
  nama: '',
  nik: '',
  tanggal_lahir: '',
  username: '',
  password: '',
  email: '',
  alamat: '',
  telepon: '',
  id_cabang: '',
  id_principal: '',
  id_wilayah1: '',
  id_wilayah2: '',
  id_tipe: '',
  plafon_limit: '',
  kode_sales: ''
});

const existingSalesUserIds = computed(() =>
  new Set(
    items.value
      .map((item) => String(item.id_user || item.id || ''))
      .filter(Boolean)
  )
);

const companyOptions = computed(() =>
  scopedCompanies.value
    .filter((item) => {
      if (!form.id_cabang) return false;
      if (!selectedCompanyIds.value.length) return false;
      return selectedCompanyIds.value.includes(String(item.id));
    })
    .map((item) => ({
      value: String(item.id),
      label: item.nama || item.nama_perusahaan || `Perusahaan ${item.id}`
    }))
);

const branchOptions = computed(() =>
  scopedBranches.value
    .map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => !form.id_perusahaan || String(item.id_perusahaan || item.company_id || '') === String(form.id_perusahaan))
    .map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_principal || 'Principal'}`
    }))
);

const salesTypeOptions = computed(() =>
  salesTypes.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Tipe ${item.id}`
  }))
);

const salesUserOptions = computed(() =>
  users.value
    .filter((item) => {
      const isSalesUser =
        String(item.id_jabatan || '') === SALES_POSITION_ID ||
        String(item.nama_jabatan || item.jabatan || '').trim().toLowerCase() === 'sales';
      if (!isSalesUser) return false;

      const branchMatch = !form.id_cabang || String(item.id_cabang || '') === String(form.id_cabang);
      const companyMatch = !form.id_perusahaan || !item.id_perusahaan || String(item.id_perusahaan) === String(form.id_perusahaan);
      const alreadyUsedByOtherSales = existingSalesUserIds.value.has(String(item.id)) && String(item.id) !== String(form.id_user || '');

      return branchMatch && companyMatch && (mode.value === 'edit' || !alreadyUsedByOtherSales);
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.nama || 'User Sales'}${item.username ? ` - ${item.username}` : ''}${item.nama_cabang ? ` | ${item.nama_cabang}` : ''}`
    }))
);

const selectedSalesUser = computed(() =>
  users.value.find((item) => String(item.id) === String(form.id_user || ''))
);

const wilayah1Options = computed(() =>
  wilayah1Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const wilayah2Options = computed(() =>
  wilayah2Rows.value.map((item) => ({
    value: String(item.id),
    label: item.nama || `Wilayah ${item.id}`
  }))
);

const principalMap = computed(() =>
  principals.value.reduce((acc, item) => {
    acc[String(item.id)] = `${item.kode || '-'} - ${item.nama || item.nama_principal || 'Principal'}`;
    return acc;
  }, {})
);

const selectedAssignmentLabels = computed(() =>
  assignmentPrincipalIds.value.map((id) => ({
    id,
    label: principalMap.value[String(id)] || `Principal ${id}`
  }))
);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return scopedItems.value;
  return scopedItems.value.filter((item) =>
    [item.nama_sales, item.nama, item.kode_sales, item.username, item.nama_principal, item.nama_cabang, item.nama_perusahaan, item.tipe, item.nik]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const columns = [
  { key: 'nama', label: 'Sales', render: (row) => row.nama_sales || row.nama || '-' },
  { key: 'kode_sales', label: 'Kode Sales' },
  { key: 'nama_principal', label: 'Principal' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'tipe', label: 'Tipe' }
];

function getPrimarySalesId(row = {}) {
  return row?.id_sales || row?.sales_id || row?.id_user_sales || '';
}

function getPrimaryUserId(row = {}) {
  return row?.id_user || row?.user_id || row?.id || '';
}

function resetForm() {
  Object.assign(form, {
    id_perusahaan: '',
    id_user: '',
    nama: '',
    nik: '',
    tanggal_lahir: '',
    username: '',
    password: '',
    email: '',
    alamat: '',
    telepon: '',
    id_cabang: '',
    id_principal: '',
    id_wilayah1: '',
    id_wilayah2: '',
    id_tipe: '',
    plafon_limit: '',
    kode_sales: ''
  });
  detailRow.value = null;
  salesDetailRows.value = [];
  assignmentRows.value = [];
  assignmentPrincipalIds.value = [];
  assignmentPrincipalToAdd.value = '';
  wilayah2Rows.value = [];
  applyLoginBranchDefault();
}

async function loadOptions() {
  const [companyResponse, branchResponse, principalResponse, salesTypeResponse, wilayah1Response, userResponse] = await Promise.all([
    getCompanies(),
    getBranches(),
    getPrincipals(),
    getSalesTypes(),
    getRegionsLevel1(),
    getUsers()
  ]);
  companies.value = normalizeList(unwrapResponse(companyResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  salesTypes.value = normalizeList(unwrapResponse(salesTypeResponse));
  wilayah1Rows.value = normalizeList(unwrapResponse(wilayah1Response));
  users.value = scopeRowsByLoginBranch(normalizeList(unwrapResponse(userResponse)), authStore);
  applyLoginBranchDefault();
}

function syncCompanyFromBranch(preserveCurrent = false) {
  if (!form.id_cabang) {
    form.id_perusahaan = '';
    return;
  }

  const allowedCompanyIds = selectedCompanyIds.value;
  if (!preserveCurrent || !allowedCompanyIds.includes(String(form.id_perusahaan || ''))) {
    form.id_perusahaan = '';
  }
}

function applyLoginBranchDefault() {
  if (!isSuperUser(authStore) && loginBranchId.value) {
    form.id_cabang = String(loginBranchId.value);
    syncCompanyFromBranch();
  }
}

watch(
  () => form.id_perusahaan,
  () => {
    if (form.id_principal && !principalOptions.value.some((item) => item.value === String(form.id_principal))) {
      form.id_principal = '';
    }
    assignmentPrincipalIds.value = assignmentPrincipalIds.value.filter((id) =>
      principalOptions.value.some((item) => item.value === String(id))
    );
    if (assignmentPrincipalToAdd.value && !principalOptions.value.some((item) => item.value === String(assignmentPrincipalToAdd.value))) {
      assignmentPrincipalToAdd.value = '';
    }
  }
);

watch(
  () => form.id_cabang,
  () => {
    syncCompanyFromBranch();
  }
);

async function loadWilayah2(id, preserveValue = false) {
  if (!id) {
    wilayah2Rows.value = [];
    form.id_wilayah2 = '';
    return;
  }
  const response = await getRegionsLevel2(id);
  wilayah2Rows.value = normalizeList(unwrapResponse(response));
  if (!preserveValue) {
    form.id_wilayah2 = '';
  }
}

watch(
  () => form.id_wilayah1,
  async (value, previousValue) => {
    if (value !== previousValue) {
      await loadWilayah2(value);
    }
  }
);

function submit() {
  load();
}

function reset() {
  filters.search = '';
}

function applyUserToForm(user) {
  if (!user) return;

  form.nama = user.nama || '';
  form.nik = user.nik || '';
  form.tanggal_lahir = user.tanggal_lahir || '';
  form.username = user.username || '';
  form.email = user.email || '';
  form.alamat = user.alamat || '';
  form.telepon = user.telepon || '';

  if (user.id_cabang) {
    form.id_cabang = String(user.id_cabang);
  }

  if (user.id_perusahaan) {
    form.id_perusahaan = String(user.id_perusahaan);
  } else {
    syncCompanyFromBranch(true);
  }
}

watch(
  () => form.id_user,
  (value) => {
    const user = users.value.find((item) => String(item.id) === String(value || ''));
    if (user) {
      applyUserToForm(user);
    }
  }
);

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  resetForm();
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

async function openEdit(row) {
  mode.value = 'edit';
  const salesId = getPrimarySalesId(row);
  if (!salesId) {
    actionError.value = 'ID sales utama tidak terbaca, detail sales tidak dibuka agar data tidak salah.';
    return;
  }

  selectedRow.value = { ...row, id_sales: salesId };
  feedback.value = '';
  actionError.value = '';
  Object.assign(form, {
    id_perusahaan: row?.id_perusahaan ? String(row.id_perusahaan) : '',
    id_user: getPrimaryUserId(row) ? String(getPrimaryUserId(row)) : '',
    nama: row?.nama || row?.nama_sales || '',
    nik: row?.nik || '',
    tanggal_lahir: row?.tanggal_lahir || '',
    username: row?.username || '',
    password: '',
    email: row?.email || '',
    alamat: row?.alamat || '',
    telepon: row?.telepon || '',
    id_cabang: row?.id_cabang ? String(row.id_cabang) : '',
    id_principal: row?.id_principal ? String(row.id_principal) : '',
    id_wilayah1: row?.id_wilayah1 ? String(row.id_wilayah1) : '',
    id_wilayah2: row?.id_wilayah2 ? String(row.id_wilayah2) : '',
    id_tipe: row?.id_tipe ? String(row.id_tipe) : '',
    plafon_limit: row?.plafon_limit || '',
    kode_sales: ''
  });
  syncCompanyFromBranch(true);

  await loadWilayah2(form.id_wilayah1, true);

  try {
    const [detailResponse, assignmentResponse] = await Promise.all([
      getSalesDetails(salesId),
      getSalesPrincipalAssignments(salesId)
    ]);

    salesDetailRows.value = normalizeList(unwrapResponse(detailResponse));
    detailRow.value = salesDetailRows.value[0] || null;
    assignmentRows.value = normalizeList(unwrapResponse(assignmentResponse));
    assignmentPrincipalIds.value = assignmentRows.value
      .map((item) => Number(item.id_principal))
      .filter((item) => Number.isFinite(item));
    form.kode_sales = detailRow.value?.kode_sales || row?.kode_sales || '';
  } catch (err) {
    salesDetailRows.value = [];
    detailRow.value = null;
    assignmentRows.value = [];
    assignmentPrincipalIds.value = [];
    form.kode_sales = row?.kode_sales || '';
    actionError.value = normalizeError(err, 'Detail sales belum bisa dimuat.');
  }

  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

function addAssignmentPrincipal() {
  if (!assignmentPrincipalToAdd.value) {
    return;
  }

  const id = Number(assignmentPrincipalToAdd.value);
  if (!assignmentPrincipalIds.value.includes(id)) {
    assignmentPrincipalIds.value = [...assignmentPrincipalIds.value, id];
  }
  assignmentPrincipalToAdd.value = '';
}

function removeAssignmentPrincipal(id) {
  assignmentPrincipalIds.value = assignmentPrincipalIds.value.filter((item) => item !== id);
}

async function resolveCreatedSalesId(userId) {
  const response = await getSales();
  const rows = normalizeList(unwrapResponse(response));

  const matchedRows = rows.filter(
    (item) =>
      String(item.id_user || item.id || '') === String(userId || '') &&
      String(item.id_tipe || '') === String(form.id_tipe || '')
  );

  if (!matchedRows.length) {
    return null;
  }

  const latestRow = matchedRows
    .map((item) => Number(getPrimarySalesId(item)))
    .filter((item) => Number.isFinite(item))
    .sort((a, b) => b - a)[0];

  return latestRow || null;
}

async function syncSalesExtras(salesId) {
  const code = form.kode_sales?.trim();
  const extraDetailRows = salesDetailRows.value.filter((item) => item?.id && item.id !== detailRow.value?.id);

  if (detailRow.value?.id && !code) {
    await deleteSalesDetail(detailRow.value.id);
    for (const item of extraDetailRows) {
      await deleteSalesDetail(item.id);
    }
  } else if (detailRow.value?.id && code) {
    await updateSalesDetail(detailRow.value.id, {
      id_sales: salesId,
      kode_sales: code
    });
    for (const item of extraDetailRows) {
      await deleteSalesDetail(item.id);
    }
  } else if (!detailRow.value?.id && code) {
    await createSalesDetail({
      id_sales: salesId,
      kode_sales: code
    });
  }

  const requestedIds = assignmentPrincipalIds.value;
  const existingIds = assignmentRows.value.map((item) => Number(item.id_principal)).filter((item) => Number.isFinite(item));

  const toDelete = assignmentRows.value.filter((item) => !requestedIds.includes(Number(item.id_principal)));
  const toAdd = requestedIds.filter((id) => !existingIds.includes(id));

  for (const item of toDelete) {
    await deleteSalesPrincipalAssignment(item.id);
  }

  for (const idPrincipal of toAdd) {
    await createSalesPrincipalAssignment({
      id_sales: salesId,
      id_principal: idPrincipal
    });
  }
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (!form.id_user) {
      throw new Error('Pilih user dengan jabatan sales terlebih dahulu.');
    }

    await updateUser(form.id_user, {
      nama: form.nama,
      email: form.email,
      telepon: form.telepon,
      id_jabatan: selectedSalesUser.value?.id_jabatan || SALES_POSITION_ID,
      id_cabang: form.id_cabang,
      id_perusahaan: form.id_perusahaan,
      username: form.username,
      nik: form.nik,
      alamat: form.alamat,
      tanggal_lahir: form.tanggal_lahir
    });

    if (mode.value === 'create') {
      await createSales({
        id_user: form.id_user,
        id_principal: form.id_principal,
        id_wilayah1: form.id_wilayah1,
        id_wilayah2: form.id_wilayah2,
        id_tipe: form.id_tipe,
        plafon_limit: form.plafon_limit
      });

      const salesId = await resolveCreatedSalesId(form.id_user);

      if (salesId) {
        await syncSalesExtras(salesId);
        feedback.value = 'Sales berhasil ditambahkan dari user sales terpilih.';
      } else {
        feedback.value = 'Data utama sales berhasil dibuat, tetapi sinkron data tambahan sales belum terbaca otomatis.';
      }

      resetForm();
    } else {
      const userId = form.id_user || getPrimaryUserId(selectedRow.value);
      const salesId = getPrimarySalesId(selectedRow.value);

      if (!salesId) {
        throw new Error('ID sales utama tidak terbaca. Data tidak diupdate agar tidak membuat duplikasi.');
      }

      await updateSales(salesId, {
        id_user: userId,
        id_principal: form.id_principal,
        id_wilayah1: form.id_wilayah1,
        id_wilayah2: form.id_wilayah2,
        id_tipe: form.id_tipe,
        plafon_limit: form.plafon_limit
      });

      await syncSalesExtras(salesId);
      feedback.value = 'Data sales berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data sales belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  const salesId = getPrimarySalesId(selectedRow.value);
  if (!salesId) {
    actionError.value = 'ID sales utama tidak terbaca. Data tidak dihapus agar tidak salah target.';
    return;
  }
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    for (const item of assignmentRows.value) {
      await deleteSalesPrincipalAssignment(item.id);
    }
    if (detailRow.value?.id) {
      await deleteSalesDetail(detailRow.value.id);
    }
    await deleteSales(salesId);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data sales belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  await Promise.all([submit(), loadOptions()]);
});
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="Master Sales" description="Sales adalah profile operasional dari user yang sudah punya jabatan Sales. Pilih user sales, lalu lengkapi kode, tipe, principal, dan assignment operasionalnya.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">
        Tambah Sales
      </button>
    </PageHeader>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari sales', placeholder: 'Nama, kode sales, NIK, user, principal, cabang' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable
      :rows="filteredItems"
      :columns="columns"
      :loading="loading"
      row-key="id_sales"
      :selected-key="selectedRow?.id_sales"
      :clickable-rows="true"
      empty-message="Belum ada data sales yang bisa ditampilkan."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Sales' : 'Edit Sales'" panel-class="max-w-5xl" @close="closeModal">
      <div class="space-y-5">
        <section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-sm font-semibold text-slate-900">Data User Sales</p>
          <p class="mt-1 text-xs text-slate-500">Pilih user yang sudah dibuat di Master User dengan jabatan Sales. Data cabang dan perusahaan akan dipakai sebagai scope filter sales.</p>

          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <div class="md:col-span-2">
              <AppSearchSelect
                v-model="form.id_user"
                label="User Sales"
                placeholder="Pilih user jabatan sales"
                :options="salesUserOptions"
                empty-text="User jabatan sales belum tersedia atau sudah dipakai sebagai master sales."
              />
            </div>
            <AppFormField v-model="form.nama" label="Nama Sales" />
            <AppFormField v-model="form.nik" label="NIK" />
            <AppFormField v-model="form.tanggal_lahir" label="Tanggal Lahir" type="date" />
            <AppFormField v-model="form.username" label="Username" />
            <AppFormField v-model="form.email" label="Email" type="email" />
            <AppFormField v-model="form.telepon" label="Telepon" />
            <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!isSuperUser(authStore) && !!loginBranchId" empty-text="Cabang belum tersedia." />
            <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :placeholder="form.id_cabang ? 'Perusahaan cabang terpilih' : 'Pilih cabang dulu'" :options="companyOptions" :disabled="!form.id_cabang" empty-text="Perusahaan belum tersedia." />
          </div>

          <div class="mt-4">
            <AppFormField v-model="form.alamat" label="Alamat" />
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-white px-4 py-4">
          <p class="text-sm font-semibold text-slate-900">Data Sales</p>
          <div class="mt-4 grid gap-4 md:grid-cols-2">
            <AppFormField v-model="form.kode_sales" label="Kode Sales" />
            <AppSearchSelect v-model="form.id_tipe" label="Tipe Sales" placeholder="Pilih tipe sales" :options="salesTypeOptions" empty-text="Tipe sales belum tersedia." />
            <AppSearchSelect v-model="form.id_wilayah1" label="Wilayah 1 = Provinsi" placeholder="Pilih provinsi" :options="wilayah1Options" empty-text="Provinsi belum tersedia." />
            <AppSearchSelect v-model="form.id_wilayah2" label="Wilayah 2 = Kota/Kabupaten" placeholder="Pilih kota/kabupaten" :options="wilayah2Options" empty-text="Pilih provinsi dahulu." />
            <AppSearchSelect v-model="form.id_principal" label="Principal Utama" placeholder="Pilih principal" :options="principalOptions" empty-text="Principal belum tersedia." />
            <AppFormField v-model="form.plafon_limit" label="Plafon Limit" type="number" />
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <p class="text-sm font-semibold text-slate-900">Assignment Principal Tambahan</p>
          <div class="mt-4 grid gap-3 md:grid-cols-[1fr_auto]">
            <AppSearchSelect
              v-model="assignmentPrincipalToAdd"
              label="Principal Tambahan"
              placeholder="Pilih principal tambahan"
              :options="principalOptions"
              empty-text="Principal belum tersedia."
            />
            <button class="self-end rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" type="button" @click="addAssignmentPrincipal">
              Tambah Principal
            </button>
          </div>

          <div class="mt-3 flex flex-wrap gap-2">
            <button
              v-for="item in selectedAssignmentLabels"
              :key="item.id"
              type="button"
              class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 hover:border-rose-200 hover:text-rose-700"
              @click="removeAssignmentPrincipal(item.id)"
            >
              {{ item.label }} x
            </button>
            <span v-if="!selectedAssignmentLabels.length" class="text-xs text-slate-500">Belum ada principal tambahan dipilih.</span>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-xs text-slate-500">
          Jika user sales belum muncul di pilihan, buat atau ubah dulu user tersebut di Master User dengan jabatan Sales.
        </section>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}
          </button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700" :disabled="saving" @click="remove">
            Hapus
          </button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
