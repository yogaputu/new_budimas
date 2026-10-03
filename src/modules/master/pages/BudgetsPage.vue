<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { createBudget, deleteBudget, getBranches, getBudgets, getDepartments, getPrincipals, updateBudget } from '@/api/master';
import { useRemoteCollection } from '@/composables/useRemoteCollection';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getRowCompanyId, isSuperUser } from '@/utils/accessScope';
import { useAuthStore } from '@/stores/auth';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const monthOptions = [
  { value: '1', label: 'Januari' },
  { value: '2', label: 'Februari' },
  { value: '3', label: 'Maret' },
  { value: '4', label: 'April' },
  { value: '5', label: 'Mei' },
  { value: '6', label: 'Juni' },
  { value: '7', label: 'Juli' },
  { value: '8', label: 'Agustus' },
  { value: '9', label: 'September' },
  { value: '10', label: 'Oktober' },
  { value: '11', label: 'November' },
  { value: '12', label: 'Desember' }
];

const numberFormatter = new Intl.NumberFormat('id-ID');

const authStore = useAuthStore();
const filters = reactive({ search: '' });
const { items, loading, load, error } = useRemoteCollection(() => getBudgets());
const departments = ref([]);
const principals = ref([]);
const branches = ref([]);
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);
const feedback = ref('');
const actionError = ref('');
const saving = ref(false);
const loginBranchId = computed(() => getLoginBranchId(authStore.user));
const loginBranch = computed(() => branches.value.find((item) => String(item.id) === String(loginBranchId.value || '')));
const scopedPrincipalIds = computed(() => new Set(principalOptions.value.map((item) => String(item.value))));

const form = reactive({
  id_principal: '',
  id_departemen: '',
  bulan: '',
  tahun: '',
  nominal: '',
  limit_nominal: '',
  kode: '',
  keterangan: ''
});

const departmentOptions = computed(() =>
  departments.value.map((item) => ({
    value: String(item.id),
    label: `${item.id} - ${item.nama || 'Departemen'}`
  }))
);

const principalOptions = computed(() =>
  principals.value
    .filter((item) => {
      if (isSuperUser(authStore) || !loginBranch.value) return true;
      return String(item.id_perusahaan || item.company_id || '') === String(getRowCompanyId(loginBranch.value));
    })
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || '-'} - ${item.nama || item.nama_principal || 'Principal'}`
    }))
);

const budgetRows = computed(() =>
  items.value
    .filter((item) => isSuperUser(authStore) || !loginBranch.value || scopedPrincipalIds.value.has(String(item.id_principal || item.principal_id || '')))
    .map((item) => ({
      ...item,
      periode_label: formatPeriode(item.bulan, item.tahun),
      nominal_label: formatNumber(item.nominal),
      limit_label: formatNumber(item.limit_nominal)
    }))
);

const filteredItems = computed(() => {
  const query = filters.search.trim().toLowerCase();
  if (!query) return budgetRows.value;
  return budgetRows.value.filter((item) =>
    [item.nama_departemen, item.nama_principal, item.keterangan, item.kode, item.bulan, item.tahun, item.periode_label]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const summary = computed(() => {
  const rows = filteredItems.value;
  const totalNominal = rows.reduce((acc, item) => acc + Number(item.nominal || 0), 0);
  const totalLimit = rows.reduce((acc, item) => acc + Number(item.limit_nominal || 0), 0);

  return [
    { label: 'Total Budget', value: formatNumber(totalNominal) },
    { label: 'Total Limit', value: formatNumber(totalLimit) },
    { label: 'Baris Aktif', value: numberFormatter.format(rows.length) }
  ];
});

function formatNumber(value) {
  const parsed = Number(value || 0);
  return `Rp ${numberFormatter.format(Number.isFinite(parsed) ? parsed : 0)}`;
}

function formatPeriode(month, year) {
  const found = monthOptions.find((item) => String(item.value) === String(month));
  return `${found?.label || `Bulan ${month || '-'}`} ${year || ''}`.trim();
}

function resetForm() {
  Object.assign(form, {
    id_principal: '',
    id_departemen: '',
    bulan: '',
    tahun: '',
    nominal: '',
    limit_nominal: '',
    kode: '',
    keterangan: ''
  });
  if (!isSuperUser(authStore) && principalOptions.value.length === 1) {
    form.id_principal = principalOptions.value[0].value;
  }
}

function buildPayload() {
  const payload = {};
  Object.entries(form).forEach(([key, value]) => {
    if (value !== '') payload[key] = value;
  });
  return payload;
}

async function loadOptions() {
  const [departmentResponse, principalResponse, branchResponse] = await Promise.all([getDepartments(), getPrincipals(), getBranches()]);
  departments.value = normalizeList(unwrapResponse(departmentResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  branches.value = normalizeList(unwrapResponse(branchResponse));
  if (!isSuperUser(authStore) && form.id_principal && !principalOptions.value.some((item) => item.value === String(form.id_principal))) {
    form.id_principal = '';
  }
}

function submit() {
  load();
}

function reset() {
  filters.search = '';
}

function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  resetForm();
  form.tahun = String(new Date().getFullYear());
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  Object.assign(form, {
    id_principal: row?.id_principal ? String(row.id_principal) : '',
    id_departemen: row?.id_departemen ? String(row.id_departemen) : '',
    bulan: row?.bulan ? String(row.bulan) : '',
    tahun: row?.tahun ? String(row.tahun) : '',
    nominal: row?.nominal || '',
    limit_nominal: row?.limit_nominal || '',
    kode: row?.kode || '',
    keterangan: row?.keterangan || ''
  });
  feedback.value = '';
  actionError.value = '';
  modalOpen.value = true;
}

function closeModal() {
  modalOpen.value = false;
}

function validateForm() {
  const month = Number(form.bulan);
  const year = Number(form.tahun);

  if (!Number.isInteger(month) || month < 1 || month > 12) {
    actionError.value = 'Bulan budget harus dipilih dari 1 sampai 12.';
    return false;
  }

  if (!Number.isInteger(year) || String(year).length !== 4) {
    actionError.value = 'Tahun budget harus 4 digit.';
    return false;
  }

  return true;
}

async function save() {
  saving.value = true;
  feedback.value = '';
  actionError.value = '';

  try {
    if (!validateForm()) {
      return;
    }

    if (mode.value === 'create') {
      await createBudget(buildPayload());
      feedback.value = 'Budget berhasil ditambahkan.';
      resetForm();
      form.tahun = String(new Date().getFullYear());
    } else {
      await updateBudget(selectedRow.value?.id, buildPayload());
      feedback.value = 'Budget berhasil diperbarui.';
    }

    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data budget belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id) return;
  saving.value = true;
  feedback.value = '';
  actionError.value = '';
  try {
    await deleteBudget(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Data budget belum berhasil dihapus.');
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
    <PageHeader title="Master Budget" description="Budget saya naikkan dari CRUD dasar menjadi lebih operasional: periode jelas, nominal lebih terbaca, dan ringkasan cepat langsung terlihat.">
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="openCreate">Tambah Budget</button>
    </PageHeader>

    <section class="grid gap-4 md:grid-cols-3">
      <article v-for="item in summary" :key="item.label" class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">{{ item.label }}</p>
        <p class="mt-3 text-lg font-semibold text-slate-900">{{ item.value }}</p>
      </article>
    </section>

    <AppFilterBar
      :model-value="filters"
      :fields="[{ key: 'search', label: 'Cari budget', placeholder: 'Kode, departemen, principal, periode, atau tahun' }]"
      @update:model-value="Object.assign(filters, $event)"
      @submit="submit"
      @reset="reset"
    />

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ error }}</section>

    <AppTable
      :rows="filteredItems"
      :columns="[
        { key: 'kode', label: 'Kode' },
        { key: 'nama_departemen', label: 'Departemen' },
        { key: 'nama_principal', label: 'Principal' },
        { key: 'periode_label', label: 'Periode' },
        { key: 'nominal_label', label: 'Nominal' },
        { key: 'limit_label', label: 'Limit' }
      ]"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada data budget."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Budget' : 'Edit Budget'" panel-class="max-w-3xl" @close="closeModal">
      <div class="space-y-4">
        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_departemen" label="Departemen" placeholder="Pilih departemen" :options="departmentOptions" empty-text="Departemen belum tersedia." />
          <AppSearchSelect v-model="form.id_principal" label="Principal" placeholder="Pilih principal" :options="principalOptions" empty-text="Principal belum tersedia." />
          <AppSearchSelect v-model="form.bulan" label="Bulan" placeholder="Pilih bulan" :options="monthOptions" empty-text="Bulan belum tersedia." />
          <AppFormField v-model="form.tahun" label="Tahun" placeholder="YYYY" type="number" />
          <AppFormField v-model="form.nominal" label="Nominal" type="number" />
          <AppFormField v-model="form.limit_nominal" label="Limit Nominal" type="number" />
          <AppFormField v-model="form.kode" label="Kode Budget" />
          <AppFormField v-model="form.keterangan" label="Keterangan" />
        </div>

        <section class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-600">
          <p>Preview periode: <span class="font-semibold text-slate-900">{{ formatPeriode(form.bulan, form.tahun) }}</span></p>
          <p class="mt-1">Preview nominal: <span class="font-semibold text-slate-900">{{ formatNumber(form.nominal) }}</span></p>
        </section>

        <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">{{ feedback }}</div>
        <div v-if="actionError" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{{ actionError }}</div>

        <div class="flex flex-wrap gap-2">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white" :disabled="saving" @click="save">{{ saving ? 'Menyimpan...' : mode === 'create' ? 'Simpan' : 'Update' }}</button>
          <button v-if="mode === 'edit'" class="rounded-xl border border-rose-200 px-4 py-2 text-sm font-medium text-rose-700" :disabled="saving" @click="remove">Hapus</button>
        </div>
      </div>
    </AppModal>
  </div>
</template>
