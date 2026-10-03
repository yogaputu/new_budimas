<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createSalesPrincipalGroup,
  createPrincipalRule,
  deletePrincipalRule,
  deleteSalesPrincipalGroup,
  getBranches,
  getCompanies,
  getPrincipalRules,
  getPrincipals,
  getSalesPrincipalGroups,
  updateSalesPrincipalGroup,
  updatePrincipalRule
} from '@/api/master';
import { useAppStore } from '@/app/stores/app';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowBranchIds, getRowCompanyId, isSuperUser, scopeRowsByLoginBranch } from '@/utils/accessScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const app = useAppStore();
const authStore = useAuthStore();

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  search: ''
});

const form = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  principal_group: '',
  target_doi_hari: 45,
  lead_time_hari: 7,
  moq_unit: 1,
  kelipatan_qty: 1,
  top_hari: 30,
  target_sell_in: 0,
  target_sell_out: 0,
  keterangan: '',
  is_active: true
});

const rows = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const principalRows = ref([]);
const principalGroupRows = ref([]);
const loading = ref(false);
const refsLoading = ref(false);
const saving = ref(false);
const groupSaving = ref(false);
const errorMessage = ref('');
const actionError = ref('');
const groupError = ref('');
const feedback = ref('');
const groupFeedback = ref('');
const modalOpen = ref(false);
const groupModalOpen = ref(false);
const mode = ref('create');
const groupMode = ref('create');
const selectedRow = ref(null);
const selectedGroup = ref(null);

const groupForm = reactive({
  id_cabang: '',
  id_perusahaan: '',
  kode_group: '',
  nama_group: '',
  principal_ids: [],
  notes: '',
  active: true
});

const fallbackBranchId = computed(() => getLoginBranchId(authStore.user));

function numberFormat(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function money(value) {
  return `Rp ${Number(value || 0).toLocaleString('id-ID')}`;
}

function companyIdsForBranch(branchId) {
  if (!branchId) return [];

  const ids = new Set();
  companyRows.value.forEach((item) => {
    if (getRowBranchIds(item).includes(String(branchId))) ids.add(String(item.id));
  });

  const branch = branchRows.value.find((item) => String(item.id) === String(branchId));
  principalRows.value.forEach((item) => {
    const companyId = getRowCompanyId(item);
    const sameRegion =
      branch &&
      item.id_wilayah1 &&
      item.id_wilayah2 &&
      String(item.id_wilayah1) === String(branch.id_wilayah1) &&
      String(item.id_wilayah2) === String(branch.id_wilayah2);
    if (companyId && sameRegion) ids.add(String(companyId));
  });

  return [...ids];
}

const branchOptions = computed(() =>
  scopeRowsByLoginBranch(branchRows.value, authStore).map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
  }))
);

function companyOptionsForBranch(branchId) {
  const allowed = companyIdsForBranch(branchId);
  return companyRows.value
    .filter((item) => branchId && allowed.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
    }));
}

const companyOptions = computed(() => companyOptionsForBranch(filters.id_cabang));
const formCompanyOptions = computed(() => companyOptionsForBranch(form.id_cabang));

function principalOptionsForCompany(companyId) {
  return principalRows.value
    .filter((item) => !companyId || String(getRowCompanyId(item)) === String(companyId))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.principal_nama || 'Principal'}`
    }));
}

const principalOptions = computed(() => principalOptionsForCompany(filters.id_perusahaan));
const formPrincipalOptions = computed(() => principalOptionsForCompany(form.id_perusahaan));

const principalGroupOptions = computed(() => {
  const byCode = new Map();
  principalGroupRows.value
    .filter((item) => item.active !== false)
    .forEach((item) => {
      const code = String(item.kode_group || '').trim();
      if (!code) return;
      byCode.set(code, {
        value: code,
        label: `${code} - ${item.nama_group || 'Group Principal'}${item.total_principal ? ` | ${item.total_principal} principal` : ''}`
      });
    });
  rows.value.forEach((item) => {
    const code = String(item.principal_group || '').trim();
    if (code && !byCode.has(code)) byCode.set(code, { value: code, label: code });
  });
  return Array.from(byCode.values());
});

const groupPrincipalOptions = computed(() => principalOptionsForCompany(groupForm.id_perusahaan));

const filteredRows = computed(() => rows.value);

const summary = computed(() => ({
  total: rows.value.length,
  active: rows.value.filter((item) => item.is_active !== false).length,
  sellIn: rows.value.reduce((sum, item) => sum + Number(item.target_sell_in || 0), 0),
  sellOut: rows.value.reduce((sum, item) => sum + Number(item.target_sell_out || 0), 0)
}));

const tableColumns = [
  { key: 'nama_perusahaan', label: 'Perusahaan', render: (row) => row.nama_perusahaan || '-' },
  { key: 'nama_cabang', label: 'Cabang', render: (row) => row.kode_cabang || row.nama_cabang || '-' },
  {
    key: 'principal_group',
    label: 'Principal / Group',
    render: (row) => row.principal_group || row.nama_principal || '-'
  },
  { key: 'target_doi_hari', label: 'Target DOI', render: (row) => `${numberFormat(row.target_doi_hari)} hari` },
  { key: 'lead_time_hari', label: 'Lead Time', render: (row) => `${numberFormat(row.lead_time_hari)} hari` },
  { key: 'moq_unit', label: 'MOQ', render: (row) => numberFormat(row.moq_unit) },
  { key: 'kelipatan_qty', label: 'Kelipatan', render: (row) => numberFormat(row.kelipatan_qty) },
  { key: 'top_hari', label: 'TOP', render: (row) => `${numberFormat(row.top_hari)} hari` },
  { key: 'target_sell_in', label: 'Target Sell-In', render: (row) => money(row.target_sell_in) },
  { key: 'target_sell_out', label: 'Target Sell-Out', render: (row) => money(row.target_sell_out) },
  { key: 'selesai_diperbarui', label: 'Diperbarui', render: (row) => row.selesai_diperbarui || '-' }
];

async function loadRefs() {
  refsLoading.value = true;
  try {
    const [branchesRes, companiesRes, principalsRes, groupsRes] = await Promise.all([
      getBranches(),
      getCompanies(),
      getPrincipals(),
      getSalesPrincipalGroups()
    ]);
    branchRows.value = normalizeList(unwrapResponse(branchesRes));
    companyRows.value = normalizeList(unwrapResponse(companiesRes));
    principalRows.value = normalizeList(unwrapResponse(principalsRes));
    principalGroupRows.value = normalizeList(unwrapResponse(groupsRes));
  } finally {
    refsLoading.value = false;
  }
}

async function loadPrincipalGroups() {
  const response = await getSalesPrincipalGroups({
    id_cabang: filters.id_cabang,
    id_perusahaan: filters.id_perusahaan,
    search: filters.search.trim()
  });
  principalGroupRows.value = normalizeList(unwrapResponse(response));
}

async function load() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const [response] = await Promise.all([
      getPrincipalRules({
        id_cabang: filters.id_cabang,
        id_perusahaan: filters.id_perusahaan,
        id_principal: filters.id_principal,
        search: filters.search.trim()
      }),
      loadPrincipalGroups()
    ]);
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Aturan principal belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function resetGroupForm() {
  groupForm.id_cabang = filters.id_cabang || (!isSuperUser(authStore) && fallbackBranchId.value ? String(fallbackBranchId.value) : '');
  groupForm.id_perusahaan = filters.id_perusahaan || '';
  groupForm.kode_group = '';
  groupForm.nama_group = '';
  groupForm.principal_ids = [];
  groupForm.notes = '';
  groupForm.active = true;
}

function openGroupModal() {
  groupMode.value = 'create';
  selectedGroup.value = null;
  groupError.value = '';
  groupFeedback.value = '';
  resetGroupForm();
  groupModalOpen.value = true;
}

function editGroup(row) {
  groupMode.value = 'edit';
  selectedGroup.value = row;
  groupError.value = '';
  groupFeedback.value = '';
  groupForm.id_cabang = row?.id_cabang ? String(row.id_cabang) : '';
  groupForm.id_perusahaan = row?.id_perusahaan ? String(row.id_perusahaan) : '';
  groupForm.kode_group = row?.kode_group || '';
  groupForm.nama_group = row?.nama_group || '';
  groupForm.principal_ids = normalizeList(row?.principals).map((item) => String(item.id)).filter(Boolean);
  groupForm.notes = row?.notes || '';
  groupForm.active = row?.active !== false;
}

function buildGroupPayload() {
  return {
    id_cabang: groupForm.id_cabang || null,
    id_perusahaan: groupForm.id_perusahaan || null,
    kode_group: groupForm.kode_group,
    nama_group: groupForm.nama_group,
    principal_ids: groupForm.principal_ids.map((id) => Number(id)),
    notes: groupForm.notes,
    active: groupForm.active
  };
}

async function saveGroup() {
  groupSaving.value = true;
  groupError.value = '';
  groupFeedback.value = '';
  try {
    if (groupMode.value === 'create') {
      await createSalesPrincipalGroup(buildGroupPayload());
      groupFeedback.value = 'Group principal berhasil ditambahkan.';
      resetGroupForm();
    } else {
      await updateSalesPrincipalGroup(selectedGroup.value.id, buildGroupPayload());
      groupFeedback.value = 'Group principal berhasil diperbarui.';
    }
    await loadPrincipalGroups();
  } catch (err) {
    groupError.value = normalizeError(err, 'Group principal belum berhasil disimpan.');
  } finally {
    groupSaving.value = false;
  }
}

async function removeGroup() {
  if (!selectedGroup.value?.id) return;
  groupSaving.value = true;
  groupError.value = '';
  try {
    await deleteSalesPrincipalGroup(selectedGroup.value.id);
    groupFeedback.value = 'Group principal berhasil dihapus.';
    groupMode.value = 'create';
    selectedGroup.value = null;
    resetGroupForm();
    await loadPrincipalGroups();
  } catch (err) {
    groupError.value = normalizeError(err, 'Group principal belum berhasil dihapus.');
  } finally {
    groupSaving.value = false;
  }
}

function resetFilters() {
  filters.id_cabang = !isSuperUser(authStore) && fallbackBranchId.value ? String(fallbackBranchId.value) : '';
  filters.id_perusahaan = '';
  filters.id_principal = '';
  filters.search = '';
  load();
}

function resetForm() {
  form.id_cabang = filters.id_cabang || (!isSuperUser(authStore) && fallbackBranchId.value ? String(fallbackBranchId.value) : '');
  form.id_perusahaan = '';
  form.id_principal = '';
  form.principal_group = '';
  form.target_doi_hari = 45;
  form.lead_time_hari = 7;
  form.moq_unit = 1;
  form.kelipatan_qty = 1;
  form.top_hari = 30;
  form.target_sell_in = 0;
  form.target_sell_out = 0;
  form.keterangan = '';
  form.is_active = true;
}

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  feedback.value = '';
  actionError.value = '';
  resetForm();
  modalOpen.value = true;
}

function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  feedback.value = '';
  actionError.value = '';
  form.id_cabang = row?.id_cabang ? String(row.id_cabang) : '';
  form.id_perusahaan = row?.id_perusahaan ? String(row.id_perusahaan) : '';
  form.id_principal = row?.id_principal ? String(row.id_principal) : '';
  form.principal_group = row?.principal_group || '';
  form.target_doi_hari = Number(row?.target_doi_hari || 0);
  form.lead_time_hari = Number(row?.lead_time_hari || 0);
  form.moq_unit = Number(row?.moq_unit || 0);
  form.kelipatan_qty = Number(row?.kelipatan_qty || 1);
  form.top_hari = Number(row?.top_hari || 0);
  form.target_sell_in = Number(row?.target_sell_in || 0);
  form.target_sell_out = Number(row?.target_sell_out || 0);
  form.keterangan = row?.keterangan || '';
  form.is_active = row?.is_active !== false;
  modalOpen.value = true;
}

function buildPayload() {
  return {
    id_cabang: form.id_cabang || null,
    id_perusahaan: form.id_perusahaan || null,
    id_principal: form.id_principal || null,
    principal_group: form.principal_group,
    target_doi_hari: Number(form.target_doi_hari || 0),
    lead_time_hari: Number(form.lead_time_hari || 0),
    moq_unit: Number(form.moq_unit || 0),
    kelipatan_qty: Number(form.kelipatan_qty || 1),
    top_hari: Number(form.top_hari || 0),
    target_sell_in: Number(form.target_sell_in || 0),
    target_sell_out: Number(form.target_sell_out || 0),
    keterangan: form.keterangan,
    is_active: form.is_active
  };
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    if (mode.value === 'create') {
      await createPrincipalRule(buildPayload());
      feedback.value = 'Aturan principal berhasil ditambahkan.';
      resetForm();
    } else {
      await updatePrincipalRule(selectedRow.value.id, buildPayload());
      feedback.value = 'Aturan principal berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Aturan principal belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id) return;
  saving.value = true;
  actionError.value = '';
  try {
    await deletePrincipalRule(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Aturan principal belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

watch(
  () => filters.id_cabang,
  (value, previousValue) => {
    if (value === previousValue) return;
    filters.id_perusahaan = '';
    filters.id_principal = '';
  }
);

watch(
  () => filters.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    filters.id_principal = '';
  }
);

watch(
  () => form.id_cabang,
  (value, previousValue) => {
    if (value === previousValue) return;
    form.id_perusahaan = '';
    form.id_principal = '';
  }
);

watch(
  () => groupForm.id_cabang,
  (value, previousValue) => {
    if (value === previousValue) return;
    groupForm.id_perusahaan = '';
    groupForm.principal_ids = [];
  }
);

watch(
  () => groupForm.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    groupForm.principal_ids = [];
  }
);

watch(
  () => form.id_perusahaan,
  (value, previousValue) => {
    if (value === previousValue) return;
    form.id_principal = '';
  }
);

onMounted(async () => {
  await loadRefs();
  if (!isSuperUser(authStore) && fallbackBranchId.value) filters.id_cabang = String(fallbackBranchId.value);
  await load();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Aturan Principal"
      description="Konfigurasi target DOI, lead time, MOQ, kelipatan kuantitas, TOP, dan target sell-in/sell-out lintas perusahaan dan cabang."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold dark:border-slate-700" @click="openGroupModal">
          Kelola Group
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="openCreate">
          + Tambah Aturan Baru
        </button>
      </div>
    </PageHeader>

    <section class="grid gap-3 md:grid-cols-4">
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Total Aturan</p>
        <p class="mt-2 text-2xl font-bold">{{ summary.total }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Aktif</p>
        <p class="mt-2 text-2xl font-bold text-emerald-400">{{ summary.active }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Target Sell-In</p>
        <p class="mt-2 text-2xl font-bold">{{ money(summary.sellIn) }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Target Sell-Out</p>
        <p class="mt-2 text-2xl font-bold text-teal-400">{{ money(summary.sellOut) }}</p>
      </article>
    </section>

    <section :class="['rounded-3xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
      <div class="grid gap-3 xl:grid-cols-[1fr_1fr_1fr_1.2fr_auto]">
        <AppSearchSelect
          v-model="filters.id_cabang"
          label="Cabang"
          :options="branchOptions"
          :disabled="refsLoading || (!isSuperUser(authStore) && !!fallbackBranchId)"
          placeholder="Pilih cabang"
          empty-text="Cabang belum tersedia."
        />
        <AppSearchSelect
          v-model="filters.id_perusahaan"
          label="Perusahaan"
          :options="companyOptions"
          :disabled="!filters.id_cabang"
          placeholder="Pilih perusahaan"
          empty-text="Perusahaan belum tersedia untuk cabang ini."
        />
        <AppSearchSelect
          v-model="filters.id_principal"
          label="Principal"
          :options="principalOptions"
          :disabled="!filters.id_perusahaan"
          placeholder="Semua principal"
          empty-text="Principal belum tersedia."
        />
        <AppFormField v-model="filters.search" label="Cari" placeholder="Group, principal, cabang, catatan" />
        <div class="flex items-end gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white" @click="load">Terapkan</button>
          <button class="rounded-xl border border-slate-300 px-4 py-3 text-sm font-semibold dark:border-slate-700" @click="resetFilters">Reset</button>
        </div>
      </div>
    </section>

    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </section>

    <AppTable
      :rows="filteredRows"
      :columns="tableColumns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada aturan principal pada filter ini."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Aturan Principal' : 'Edit Aturan Principal'" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-3 md:grid-cols-2">
          <AppSearchSelect
            v-model="form.id_cabang"
            label="Cabang"
            :options="branchOptions"
            :disabled="!isSuperUser(authStore) && !!fallbackBranchId"
            placeholder="Pilih cabang"
            empty-text="Cabang belum tersedia."
          />
          <AppSearchSelect
            v-model="form.id_perusahaan"
            label="Perusahaan"
            :options="formCompanyOptions"
            :disabled="!form.id_cabang"
            placeholder="Pilih perusahaan"
            empty-text="Perusahaan belum tersedia untuk cabang ini."
          />
          <AppSearchSelect
            v-model="form.id_principal"
            label="Principal"
            :options="formPrincipalOptions"
            :disabled="!form.id_perusahaan"
            placeholder="Pilih principal spesifik"
            empty-text="Principal belum tersedia."
          />
          <AppSearchSelect
            v-model="form.principal_group"
            label="Principal Group"
            :options="principalGroupOptions"
            placeholder="Pilih group mix"
            empty-text="Group belum tersedia. Buat dari Kelola Group."
          />
        </div>

        <div class="grid gap-3 md:grid-cols-3">
          <AppFormField v-model="form.target_doi_hari" label="Target DOI (Hari)" type="number" min="0" />
          <AppFormField v-model="form.lead_time_hari" label="Lead Time (Hari)" type="number" min="0" />
          <AppFormField v-model="form.moq_unit" label="MOQ (Unit)" type="number" min="0" />
          <AppFormField v-model="form.kelipatan_qty" label="Kelipatan Qty" type="number" min="1" />
          <AppFormField v-model="form.top_hari" label="TOP (Hari)" type="number" min="0" />
          <label class="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
            <input v-model="form.is_active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
            <span class="font-semibold text-slate-700 dark:text-slate-200">Aturan aktif</span>
          </label>
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <AppFormField v-model="form.target_sell_in" label="Target Sell-In" type="number" min="0" step="1000" />
          <AppFormField v-model="form.target_sell_out" label="Target Sell-Out" type="number" min="0" step="1000" />
        </div>

        <AppFormField v-model="form.keterangan" label="Keterangan" type="textarea" placeholder="Catatan aturan khusus, pengecualian, atau dasar target" />

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ feedback }}
        </div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ actionError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white" :disabled="saving" @click="save">
            {{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan Aturan' : 'Update Aturan' }}
          </button>
          <button
            v-if="mode === 'edit'"
            class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-600 dark:border-rose-700"
            :disabled="saving"
            @click="remove"
          >
            Hapus
          </button>
          <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold dark:border-slate-700" :disabled="saving" @click="modalOpen = false">
            Tutup
          </button>
        </div>
      </div>
    </AppModal>

    <AppModal :open="groupModalOpen" :title="groupMode === 'create' ? 'Kelola Group Principal' : 'Edit Group Principal'" @close="groupModalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-3 md:grid-cols-2">
          <AppSearchSelect
            v-model="groupForm.id_cabang"
            label="Cabang"
            :options="branchOptions"
            :disabled="!isSuperUser(authStore) && !!fallbackBranchId"
            placeholder="Semua cabang"
            empty-text="Cabang belum tersedia."
          />
          <AppSearchSelect
            v-model="groupForm.id_perusahaan"
            label="Perusahaan"
            :options="companyOptionsForBranch(groupForm.id_cabang)"
            :disabled="!groupForm.id_cabang"
            placeholder="Pilih perusahaan"
            empty-text="Perusahaan belum tersedia untuk cabang ini."
          />
          <AppFormField v-model="groupForm.kode_group" label="Kode Group" placeholder="Contoh: MIX-FOOD" />
          <AppFormField v-model="groupForm.nama_group" label="Nama Group" placeholder="Contoh: Mix Food Budimas" />
        </div>

        <AppSearchSelect
          v-model="groupForm.principal_ids"
          label="Anggota Principal"
          :options="groupPrincipalOptions"
          multiple
          :disabled="!groupForm.id_perusahaan"
          placeholder="Pilih beberapa principal"
          empty-text="Principal belum tersedia."
        />

        <div class="grid gap-3 md:grid-cols-[1fr_auto]">
          <AppFormField v-model="groupForm.notes" label="Catatan" placeholder="Catatan pemakaian group" />
          <label class="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
            <input v-model="groupForm.active" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
            <span class="font-semibold text-slate-700 dark:text-slate-200">Aktif</span>
          </label>
        </div>

        <div v-if="groupFeedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
          {{ groupFeedback }}
        </div>
        <div v-if="groupError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {{ groupError }}
        </div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white" :disabled="groupSaving" @click="saveGroup">
            {{ groupSaving ? 'Menyimpan...' : groupMode === 'create' ? 'Simpan Group' : 'Update Group' }}
          </button>
          <button
            v-if="groupMode === 'edit'"
            class="rounded-xl border border-rose-300 px-4 py-2 text-sm font-semibold text-rose-600 dark:border-rose-700"
            :disabled="groupSaving"
            @click="removeGroup"
          >
            Hapus
          </button>
          <button class="rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold dark:border-slate-700" :disabled="groupSaving" @click="resetGroupForm">
            Reset
          </button>
        </div>

        <div class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-800">
          <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead :class="app.isDark ? 'bg-slate-900' : 'bg-slate-50'">
              <tr>
                <th class="px-4 py-3 text-left font-semibold">Group</th>
                <th class="px-4 py-3 text-left font-semibold">Scope</th>
                <th class="px-4 py-3 text-left font-semibold">Anggota</th>
                <th class="px-4 py-3 text-left font-semibold">Status</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
              <tr
                v-for="item in principalGroupRows"
                :key="item.id"
                class="cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800"
                @click="editGroup(item)"
              >
                <td class="px-4 py-3">
                  <p class="font-semibold">{{ item.kode_group }}</p>
                  <p class="text-xs text-slate-500">{{ item.nama_group }}</p>
                </td>
                <td class="px-4 py-3 text-slate-500">
                  {{ item.kode_perusahaan || 'Semua perusahaan' }} / {{ item.kode_cabang || 'Semua cabang' }}
                </td>
                <td class="px-4 py-3">
                  {{ item.nama_principal_list || '-' }}
                </td>
                <td class="px-4 py-3">
                  <span :class="item.active !== false ? 'text-emerald-500' : 'text-rose-500'">
                    {{ item.active !== false ? 'Aktif' : 'Nonaktif' }}
                  </span>
                </td>
              </tr>
              <tr v-if="!principalGroupRows.length">
                <td colspan="4" class="px-4 py-6 text-center text-slate-500">
                  Belum ada group principal.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </AppModal>
  </div>
</template>
