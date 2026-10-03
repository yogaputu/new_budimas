<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import {
  createCustomerProductRule,
  deleteCustomerProductRule,
  getBranches,
  getCompanies,
  getCustomerProductRules,
  getCustomerTypes,
  getCustomersTable,
  getProductOptions,
  getProductOptionsByPrincipal,
  getPrincipals,
  updateCustomerProductRule
} from '@/api/master';
import { useAppStore } from '@/app/stores/app';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const app = useAppStore();

const filters = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_customer: '',
  id_customer_tipe: '',
  id_principal: '',
  rule_type: '',
  search: ''
});

const form = reactive({
  id_perusahaan: '',
  id_cabang: '',
  id_customer: '',
  id_customer_tipe: '',
  id_principal: '',
  id_produk: '',
  rule_type: 'required',
  start_date: '',
  end_date: '',
  aktif: true,
  notes: ''
});

const rows = ref([]);
const companies = ref([]);
const branches = ref([]);
const customers = ref([]);
const customerTypes = ref([]);
const principals = ref([]);
const products = ref([]);
const loading = ref(false);
const saving = ref(false);
const refsLoading = ref(false);
const errorMessage = ref('');
const actionError = ref('');
const feedback = ref('');
const modalOpen = ref(false);
const mode = ref('create');
const selectedRow = ref(null);

const optionLabel = (...values) => values.find((value) => String(value || '').trim()) || '-';
const toOption = (item, codeKey = 'kode', nameKey = 'nama') => ({
  value: String(item.id ?? item.value ?? ''),
  label: `${item[codeKey] || item.kode_sku || item.Kode || '-'} - ${item[nameKey] || item.nama_produk || item.Nama || item.label || 'Data'}`
});

const companyOptions = computed(() => companies.value.map((item) => toOption(item)));
const branchOptions = computed(() => branches.value.map((item) => toOption(item)));
const customerOptions = computed(() => customers.value.map((item) => toOption(item)));
const customerTypeOptions = computed(() => customerTypes.value.map((item) => toOption(item, 'kode', 'nama')));
const principalOptions = computed(() => principals.value.map((item) => toOption(item)));
const productOptions = computed(() => products.value.map((item) => ({
  value: String(item.id || item.id_produk || item.value || ''),
  label: optionLabel(
    item.label,
    `${item.kode_sku || item.Kode || item.kode || '-'} - ${item.nama || item.nama_produk || item.Nama || 'Produk'}`
  )
})));

const summary = computed(() => ({
  total: rows.value.length,
  required: rows.value.filter((item) => item.rule_type === 'required').length,
  forbidden: rows.value.filter((item) => item.rule_type === 'forbidden').length,
  active: rows.value.filter((item) => item.aktif !== false).length
}));

const tableColumns = [
  { key: 'rule_type', label: 'Aturan', render: (row) => row.rule_type === 'forbidden' ? 'Tidak boleh order' : 'Wajib order' },
  { key: 'nama_produk', label: 'Produk', render: (row) => `${row.kode_sku || '-'} - ${row.nama_produk || '-'}` },
  { key: 'nama_customer', label: 'Customer', render: (row) => row.nama_customer || row.nama_customer_tipe || 'Semua customer di scope' },
  { key: 'nama_principal', label: 'Principal', render: (row) => row.nama_principal || '-' },
  { key: 'nama_cabang', label: 'Cabang', render: (row) => row.kode_cabang || row.nama_cabang || '-' },
  { key: 'aktif', label: 'Status', render: (row) => row.aktif === false ? 'Nonaktif' : 'Aktif' },
  { key: 'selesai_diperbarui', label: 'Diperbarui', render: (row) => row.selesai_diperbarui || '-' }
];

async function loadRefs() {
  refsLoading.value = true;
  try {
    const [companyRes, branchRes, customerRes, typeRes, principalRes] = await Promise.all([
      getCompanies(),
      getBranches(),
      getCustomersTable({ search: '' }),
      getCustomerTypes(),
      getPrincipals()
    ]);
    companies.value = normalizeList(unwrapResponse(companyRes));
    branches.value = normalizeList(unwrapResponse(branchRes));
    customers.value = normalizeList(unwrapResponse(customerRes));
    customerTypes.value = normalizeList(unwrapResponse(typeRes));
    principals.value = normalizeList(unwrapResponse(principalRes));
  } finally {
    refsLoading.value = false;
  }
}

async function loadProducts() {
  try {
    const response = form.id_principal
      ? await getProductOptionsByPrincipal(form.id_principal, { search: '', limit: 500 })
      : await getProductOptions({ search: '', limit: 500 });
    products.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    products.value = [];
  }
}

async function load() {
  loading.value = true;
  errorMessage.value = '';
  try {
    const response = await getCustomerProductRules({
      id_perusahaan: filters.id_perusahaan,
      id_cabang: filters.id_cabang,
      id_customer: filters.id_customer,
      id_customer_tipe: filters.id_customer_tipe,
      id_principal: filters.id_principal,
      rule_type: filters.rule_type,
      search: filters.search.trim()
    });
    rows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Aturan produk customer belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  Object.assign(filters, {
    id_perusahaan: '',
    id_cabang: '',
    id_customer: '',
    id_customer_tipe: '',
    id_principal: '',
    rule_type: '',
    search: ''
  });
  load();
}

function resetForm() {
  Object.assign(form, {
    id_perusahaan: filters.id_perusahaan || '',
    id_cabang: filters.id_cabang || '',
    id_customer: filters.id_customer || '',
    id_customer_tipe: filters.id_customer_tipe || '',
    id_principal: filters.id_principal || '',
    id_produk: '',
    rule_type: 'required',
    start_date: '',
    end_date: '',
    aktif: true,
    notes: ''
  });
}

async function openCreate() {
  mode.value = 'create';
  selectedRow.value = null;
  actionError.value = '';
  feedback.value = '';
  resetForm();
  modalOpen.value = true;
  await loadProducts();
}

async function openEdit(row) {
  mode.value = 'edit';
  selectedRow.value = row;
  actionError.value = '';
  feedback.value = '';
  Object.assign(form, {
    id_perusahaan: row.id_perusahaan ? String(row.id_perusahaan) : '',
    id_cabang: row.id_cabang ? String(row.id_cabang) : '',
    id_customer: row.id_customer ? String(row.id_customer) : '',
    id_customer_tipe: row.id_customer_tipe ? String(row.id_customer_tipe) : '',
    id_principal: row.id_principal ? String(row.id_principal) : '',
    id_produk: row.id_produk ? String(row.id_produk) : '',
    rule_type: row.rule_type || 'required',
    start_date: row.start_date || '',
    end_date: row.end_date || '',
    aktif: row.aktif !== false,
    notes: row.notes || ''
  });
  modalOpen.value = true;
  await loadProducts();
}

function buildPayload() {
  return {
    id_perusahaan: form.id_perusahaan || null,
    id_cabang: form.id_cabang || null,
    id_customer: form.id_customer || null,
    id_customer_tipe: form.id_customer_tipe || null,
    id_principal: form.id_principal || null,
    id_produk: form.id_produk || null,
    rule_type: form.rule_type,
    start_date: form.start_date || null,
    end_date: form.end_date || null,
    aktif: form.aktif,
    notes: form.notes
  };
}

async function save() {
  saving.value = true;
  actionError.value = '';
  feedback.value = '';
  try {
    if (mode.value === 'create') {
      await createCustomerProductRule(buildPayload());
      feedback.value = 'Aturan produk customer berhasil ditambahkan.';
      resetForm();
    } else {
      await updateCustomerProductRule(selectedRow.value.id, buildPayload());
      feedback.value = 'Aturan produk customer berhasil diperbarui.';
    }
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Aturan produk customer belum berhasil disimpan.');
  } finally {
    saving.value = false;
  }
}

async function remove() {
  if (!selectedRow.value?.id) return;
  saving.value = true;
  actionError.value = '';
  try {
    await deleteCustomerProductRule(selectedRow.value.id);
    modalOpen.value = false;
    await load();
  } catch (err) {
    actionError.value = normalizeError(err, 'Aturan produk customer belum berhasil dihapus.');
  } finally {
    saving.value = false;
  }
}

watch(() => form.id_principal, () => {
  form.id_produk = '';
  loadProducts();
});

watch(() => form.id_customer, (value) => {
  if (value) form.id_customer_tipe = '';
});

watch(() => form.id_customer_tipe, (value) => {
  if (value) form.id_customer = '';
});

onMounted(async () => {
  await loadRefs();
  await loadProducts();
  await load();
});
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Aturan Produk Customer"
      description="Atur produk yang wajib diorder atau tidak boleh diorder untuk customer/tipe customer tertentu."
    >
      <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="openCreate">
        + Tambah Aturan
      </button>
    </PageHeader>

    <section class="grid gap-3 md:grid-cols-4">
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Total</p>
        <p class="mt-2 text-2xl font-bold">{{ summary.total }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Wajib</p>
        <p class="mt-2 text-2xl font-bold text-sky-400">{{ summary.required }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Tidak Boleh</p>
        <p class="mt-2 text-2xl font-bold text-rose-400">{{ summary.forbidden }}</p>
      </article>
      <article :class="['rounded-2xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
        <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Aktif</p>
        <p class="mt-2 text-2xl font-bold text-emerald-400">{{ summary.active }}</p>
      </article>
    </section>

    <section :class="['rounded-3xl border p-4', app.isDark ? 'border-slate-800 bg-slate-900' : 'border-slate-200 bg-white']">
      <div class="grid gap-3 xl:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]">
        <AppSearchSelect v-model="filters.id_perusahaan" label="Perusahaan" :options="companyOptions" placeholder="Semua perusahaan" />
        <AppSearchSelect v-model="filters.id_cabang" label="Cabang" :options="branchOptions" placeholder="Semua cabang" />
        <AppSearchSelect v-model="filters.id_customer" label="Customer" :options="customerOptions" placeholder="Semua customer" />
        <AppSearchSelect v-model="filters.id_principal" label="Principal" :options="principalOptions" placeholder="Semua principal" />
        <AppFormField v-model="filters.search" label="Cari" placeholder="Produk/customer/catatan" />
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
      :rows="rows"
      :columns="tableColumns"
      :loading="loading"
      :clickable-rows="true"
      empty-message="Belum ada aturan produk customer pada filter ini."
      @row-click="openEdit"
    />

    <AppModal :open="modalOpen" :title="mode === 'create' ? 'Tambah Aturan Produk Customer' : 'Edit Aturan Produk Customer'" @close="modalOpen = false">
      <div class="space-y-4">
        <div class="grid gap-3 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companyOptions" :disabled="refsLoading" placeholder="Opsional" />
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="branchOptions" :disabled="refsLoading" placeholder="Opsional" />
          <AppSearchSelect v-model="form.id_customer" label="Customer" :options="customerOptions" :disabled="refsLoading || !!form.id_customer_tipe" placeholder="Pilih customer spesifik" />
          <AppSearchSelect v-model="form.id_customer_tipe" label="Tipe Customer" :options="customerTypeOptions" :disabled="refsLoading || !!form.id_customer" placeholder="Atau pilih tipe customer" />
          <AppSearchSelect v-model="form.id_principal" label="Principal" :options="principalOptions" :disabled="refsLoading" placeholder="Opsional, mempersempit produk" />
          <AppSearchSelect v-model="form.id_produk" label="Produk" :options="productOptions" :disabled="refsLoading" placeholder="Pilih produk" empty-text="Produk belum tersedia." />
        </div>

        <div class="grid gap-3 md:grid-cols-2">
          <label :class="['rounded-2xl border p-4', form.rule_type === 'required' ? 'border-sky-400 bg-sky-50 text-sky-700 dark:bg-sky-950/30' : 'border-slate-200 dark:border-slate-700']">
            <input v-model="form.rule_type" type="radio" value="required" class="mr-2" />
            <span class="font-semibold">Wajib Order</span>
            <p class="mt-1 text-xs opacity-75">Order customer akan ditolak jika produk ini belum dimasukkan.</p>
          </label>
          <label :class="['rounded-2xl border p-4', form.rule_type === 'forbidden' ? 'border-rose-400 bg-rose-50 text-rose-700 dark:bg-rose-950/30' : 'border-slate-200 dark:border-slate-700']">
            <input v-model="form.rule_type" type="radio" value="forbidden" class="mr-2" />
            <span class="font-semibold">Tidak Boleh Order</span>
            <p class="mt-1 text-xs opacity-75">Produk tetap terlihat sebagai info, tetapi tidak bisa dikirim sebagai order.</p>
          </label>
        </div>

        <div class="grid gap-3 md:grid-cols-3">
          <AppFormField v-model="form.start_date" label="Mulai Berlaku" type="date" />
          <AppFormField v-model="form.end_date" label="Selesai Berlaku" type="date" />
          <label class="flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
            <input v-model="form.aktif" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
            <span class="font-semibold">Aturan aktif</span>
          </label>
        </div>

        <AppFormField v-model="form.notes" label="Catatan" type="textarea" placeholder="Alasan wajib/tidak boleh, program, atau pengecualian" />

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
  </div>
</template>
