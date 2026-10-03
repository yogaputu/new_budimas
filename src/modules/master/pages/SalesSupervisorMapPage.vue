<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies, getSales, getUsers } from '@/api/master';
import { deleteSalesSupervisorMapping, getSalesSupervisorMappings, saveSalesSupervisorMapping } from '@/api/sales';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getRowBranchIds, getRowCompanyIds } from '@/utils/accessScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const form = reactive({
  id_spv_user: '',
  id_sales_user: [],
  id_cabang: '',
  id_perusahaan: '',
  start_date: '',
  end_date: '',
  notes: '',
  aktif: true
});

const mappings = ref([]);
const users = ref([]);
const salesRows = ref([]);
const branchRows = ref([]);
const companyRows = ref([]);
const loading = ref(false);
const saving = ref(false);
const errorMessage = ref('');
const feedback = ref('');
const selectedRow = ref(null);

function companyIdValue(row) {
  return String(row?.id || row?.id_perusahaan || row?.company_id || row?.perusahaan_id || '');
}

function companyScopeIdValue(row) {
  return String(row?.id_perusahaan || row?.company_id || row?.perusahaan_id || row?.id_company || '');
}

function branchIdValue(row) {
  return String(row?.id || row?.id_cabang || row?.cabang_id || row?.branch_id || '');
}

function branchIdsForRow(row) {
  const ids = new Set(getRowBranchIds(row).map(String));
  const directId = branchIdValue(row);
  if (directId) ids.add(directId);
  return Array.from(ids);
}

function companyIdsForRow(row) {
  const ids = new Set(getRowCompanyIds(row).map(String));
  const directCompanyId = companyScopeIdValue(row);
  if (directCompanyId) ids.add(directCompanyId);

  branchIdsForRow(row).forEach((branchId) => {
    const branch = branchRows.value.find((item) => branchIdValue(item) === String(branchId));
    getRowCompanyIds(branch).forEach((companyId) => ids.add(String(companyId)));
    const branchCompanyId = companyScopeIdValue(branch);
    if (branchCompanyId) ids.add(branchCompanyId);
  });
  return Array.from(ids);
}

function rowMatchesSelectedScope(row, { allowUnscoped = false } = {}) {
  const companyId = String(form.id_perusahaan || '');
  const branchId = String(form.id_cabang || '');
  const rowCompanyIds = companyIdsForRow(row);
  const rowBranchIds = branchIdsForRow(row);
  const hasScope = rowCompanyIds.length || rowBranchIds.length;

  if (allowUnscoped && !hasScope) return true;
  if (companyId && (!rowCompanyIds.length || !rowCompanyIds.includes(companyId))) return false;
  if (branchId && (!rowBranchIds.length || !rowBranchIds.includes(branchId))) return false;
  return true;
}

function pruneSalesSelection() {
  const validSalesIds = new Set(salesOptions.value.map((item) => String(item.value)));
  form.id_sales_user = (Array.isArray(form.id_sales_user) ? form.id_sales_user : [form.id_sales_user])
    .map((item) => String(item || ''))
    .filter((item) => item && validSalesIds.has(item));
}

function pruneBranchSelection() {
  if (!form.id_cabang) return;
  const validBranchIds = new Set(branchOptions.value.map((item) => String(item.value)).filter(Boolean));
  if (!validBranchIds.has(String(form.id_cabang))) {
    form.id_cabang = '';
  }
}

function pruneSpvSelection() {
  if (!form.id_spv_user) return;
  const validSpvIds = new Set(spvOptions.value.map((item) => String(item.value)));
  if (!validSpvIds.has(String(form.id_spv_user))) {
    form.id_spv_user = '';
  }
}

const spvOptions = computed(() => {
  const supervisorRows = users.value.filter((item) =>
    [item.nama_jabatan, item.user_jabatan_nama, item.jabatan?.nama]
      .filter(Boolean)
      .some((value) => /spv|supervisor|kepala sales/i.test(String(value)))
  );

  const source = supervisorRows.length ? supervisorRows : users.value;
  const scopedRows = source.filter((item) => rowMatchesSelectedScope(item, { allowUnscoped: true }));
  return scopedRows.map((item) => ({
    value: String(item.id || item.id_user),
    label: `${item.nama || item.nama_user || 'User'}${item.nama_jabatan ? ` | ${item.nama_jabatan}` : ''}${item.email ? ` | ${item.email}` : ''}`
  }));
});

const salesOptions = computed(() =>
  salesRows.value
    .filter((item) => rowMatchesSelectedScope(item))
    .map((item) => ({
      value: String(item.id_user || item.user_id || item.id),
      label: `${item.kode_sales || '-'} - ${item.nama || item.nama_sales || 'Sales'}${item.nama_cabang ? ` | ${item.nama_cabang}` : ''}`
    }))
);

const branchOptions = computed(() =>
  branchRows.value
    .filter((item) => !form.id_perusahaan || companyIdsForRow(item).includes(String(form.id_perusahaan)))
    .map((item) => ({
      value: branchIdValue(item),
      label: `${item.kode || item.kode_cabang || '-'} - ${item.nama || item.nama_cabang || 'Cabang'}`
    }))
    .filter((item) => item.value)
);

const companyOptions = computed(() =>
  companyRows.value
    .map((item) => ({
      value: companyIdValue(item),
      label: `${item.kode || item.kode_perusahaan || '-'} - ${item.nama || item.nama_perusahaan || 'Perusahaan'}`
    }))
    .filter((item) => item.value)
);

const tableRows = computed(() =>
  mappings.value.map((item) => ({
    ...item,
    status_badge: {
      text: item.aktif ? 'Aktif' : 'Nonaktif',
      className: [
        'inline-flex min-w-[72px] justify-center rounded-full px-3 py-1 text-xs font-semibold',
        item.aktif ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-600'
      ].join(' ')
    },
    periode_label: [item.start_date || 'Mulai sekarang', item.end_date || 'Tanpa batas'].join(' - ')
  }))
);

const columns = [
  { key: 'nama_spv', label: 'SPV' },
  { key: 'kode_sales', label: 'Kode Sales' },
  { key: 'nama_sales', label: 'Sales' },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_perusahaan', label: 'Perusahaan' },
  { key: 'periode_label', label: 'Periode' },
  { key: 'status_badge', label: 'Status' }
];

function resetForm() {
  form.id_spv_user = '';
  form.id_sales_user = [];
  form.id_cabang = '';
  form.id_perusahaan = '';
  form.start_date = '';
  form.end_date = '';
  form.notes = '';
  form.aktif = true;
  selectedRow.value = null;
}

async function loadData() {
  loading.value = true;
  errorMessage.value = '';

  try {
    const [mappingResponse, userResponse, salesResponse, branchResponse, companyResponse] = await Promise.all([
      getSalesSupervisorMappings(),
      getUsers(),
      getSales(),
      getBranches(),
      getCompanies()
    ]);

    mappings.value = normalizeList(unwrapResponse(mappingResponse));
    users.value = normalizeList(unwrapResponse(userResponse));
    salesRows.value = normalizeList(unwrapResponse(salesResponse));
    branchRows.value = normalizeList(unwrapResponse(branchResponse));
    companyRows.value = normalizeList(unwrapResponse(companyResponse));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping SPV-Sales belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
}

function selectRow(row) {
  selectedRow.value = row;
  form.id_spv_user = String(row.id_spv_user || '');
  form.id_sales_user = row.id_sales_user ? [String(row.id_sales_user)] : [];
  form.id_cabang = row.id_cabang ? String(row.id_cabang) : '';
  form.id_perusahaan = row.id_perusahaan ? String(row.id_perusahaan) : '';
  form.start_date = row.start_date || '';
  form.end_date = row.end_date || '';
  form.notes = row.notes || '';
  form.aktif = Boolean(row.aktif);
}

async function submitForm() {
  const selectedSalesUsers = Array.isArray(form.id_sales_user)
    ? form.id_sales_user
    : String(form.id_sales_user || '').split(',').filter(Boolean);

  if (!form.id_spv_user || !selectedSalesUsers.length) {
    errorMessage.value = 'SPV dan sales wajib dipilih.';
    return;
  }

  if (!form.id_perusahaan || !form.id_cabang) {
    errorMessage.value = 'Perusahaan dan cabang wajib dipilih sebelum menyimpan mapping supervisor.';
    return;
  }

  saving.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await Promise.all(selectedSalesUsers.map((idSalesUser) =>
      saveSalesSupervisorMapping({
        ...form,
        id_sales_user: idSalesUser,
        aktif: Boolean(form.aktif)
      })
    ));
    feedback.value = `${selectedSalesUsers.length} mapping SPV-Sales berhasil disimpan.`;
    resetForm();
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping SPV-Sales belum bisa disimpan.');
  } finally {
    saving.value = false;
  }
}

async function activateSelected() {
  if (!selectedRow.value?.id_spv_user || !selectedRow.value?.id_sales_user) return;

  saving.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await saveSalesSupervisorMapping({
      id_spv_user: selectedRow.value.id_spv_user,
      id_sales_user: selectedRow.value.id_sales_user,
      id_cabang: selectedRow.value.id_cabang || '',
      id_perusahaan: selectedRow.value.id_perusahaan || '',
      start_date: selectedRow.value.start_date || '',
      end_date: '',
      notes: selectedRow.value.notes || '',
      aktif: true
    });
    feedback.value = 'Mapping SPV-Sales sudah diaktifkan kembali.';
    resetForm();
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping SPV-Sales belum bisa diaktifkan kembali.');
  } finally {
    saving.value = false;
  }
}

async function deactivateSelected() {
  if (!selectedRow.value?.id) return;

  saving.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await deleteSalesSupervisorMapping(selectedRow.value.id);
    feedback.value = 'Mapping SPV-Sales sudah dinonaktifkan.';
    resetForm();
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping SPV-Sales belum bisa dinonaktifkan.');
  } finally {
    saving.value = false;
  }
}

async function deleteSelected() {
  if (!selectedRow.value?.id) return;

  const confirmed = window.confirm(`Hapus mapping ${selectedRow.value.nama_spv || 'SPV'} - ${selectedRow.value.nama_sales || 'Sales'} secara permanen?`);
  if (!confirmed) return;

  saving.value = true;
  errorMessage.value = '';
  feedback.value = '';

  try {
    await deleteSalesSupervisorMapping(selectedRow.value.id, { hard: 'true' });
    feedback.value = 'Mapping SPV-Sales berhasil dihapus.';
    resetForm();
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mapping SPV-Sales belum bisa dihapus.');
  } finally {
    saving.value = false;
  }
}

watch(
  () => form.id_perusahaan,
  () => {
    pruneBranchSelection();
    pruneSalesSelection();
    pruneSpvSelection();
  }
);

watch(
  () => form.id_cabang,
  () => {
    pruneSalesSelection();
    pruneSpvSelection();
  }
);

onMounted(loadData);
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Mapping Sales SPV"
      description="Kelola relasi many-to-many antara supervisor sales dan sales yang dibawahi untuk filter data, approval, dan monitoring."
    >
      <button class="btn-erp-secondary" @click="loadData">Refresh</button>
    </PageHeader>

    <div v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ errorMessage }}
    </div>

    <div v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </div>

    <section class="panel p-6">
      <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 class="text-lg font-bold text-slate-950 dark:text-white">Form Mapping</h3>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Pilih perusahaan lebih dulu, lalu cabang, kemudian SPV dan sales yang berada dalam scope tersebut.</p>
        </div>
        <button class="btn-erp-secondary" @click="resetForm">Reset Form</button>
      </div>

      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" placeholder="Pilih perusahaan" :options="companyOptions" />
        <AppSearchSelect v-model="form.id_cabang" label="Cabang" placeholder="Pilih cabang" :options="branchOptions" :disabled="!form.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="form.id_spv_user" label="SPV" placeholder="Pilih SPV" :options="spvOptions" :disabled="!form.id_cabang" empty-text="Pilih cabang terlebih dahulu." />
        <AppSearchSelect v-model="form.id_sales_user" label="Sales" placeholder="Pilih satu atau beberapa sales" :options="salesOptions" :disabled="!form.id_cabang" multiple empty-text="Pilih cabang terlebih dahulu." />
        <AppFormField v-model="form.start_date" label="Mulai" type="date" />
        <AppFormField v-model="form.end_date" label="Selesai" type="date" />
        <AppFormField v-model="form.notes" label="Catatan" placeholder="Catatan mapping" />
        <label class="flex items-end gap-3 pb-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
          <input v-model="form.aktif" type="checkbox" class="h-4 w-4 rounded border-slate-300" />
          Aktif
        </label>
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="btn-erp-primary" :disabled="saving" @click="submitForm">
          {{ saving ? 'Menyimpan...' : 'Simpan Mapping' }}
        </button>
        <button class="btn-erp-secondary" :disabled="saving || !selectedRow" @click="deactivateSelected">
          Nonaktifkan Terpilih
        </button>
        <button class="btn-erp-secondary" :disabled="saving || !selectedRow || selectedRow.aktif" @click="activateSelected">
          Aktifkan Terpilih
        </button>
        <button class="rounded-xl border border-rose-200 px-4 py-3 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-60" :disabled="saving || !selectedRow" @click="deleteSelected">
          Hapus Mapping
        </button>
      </div>
    </section>

    <section>
      <AppTable
        :rows="tableRows"
        :columns="columns"
        :loading="loading"
        row-key="id"
        :clickable-rows="true"
        :selected-key="selectedRow?.id || ''"
        empty-message="Belum ada mapping SPV-Sales."
        @row-click="selectRow"
      />
    </section>
  </div>
</template>
