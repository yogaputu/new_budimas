<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getPrincipals } from '@/api/master';
import { createKasbonClaim, getKasbonClaims } from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();

const form = reactive({
  id_principal: '',
  tanggal_pengajuan: toLocalDateInputValue(),
  nominal_kasbon_diajukan: '',
  tipe_kasbon: '1',
  keterangan: ''
});

const principals = ref([]);
const rows = ref([]);
const loading = ref(false);
const submitting = ref(false);
const error = ref('');
const feedback = ref('');

const principalOptions = computed(() =>
  principals.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || item.id} | ${item.nama || item.nama_principal || 'Principal'}`
  }))
);

const tipeKasbonOptions = [
  { value: '1', label: 'Tunai' },
  { value: '2', label: 'Non Tunai' }
];

const summary = computed(() => ({
  total: rows.value.length,
  draft: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'draft').length,
  approved: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'disetujui').length,
  granted: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'diberikan').length
}));

const selectedPrincipal = computed(() =>
  principals.value.find((item) => String(item.id) === String(form.id_principal))
);

const isFormReady = computed(() =>
  !!form.id_principal &&
  !!form.tanggal_pengajuan &&
  Number(form.nominal_kasbon_diajukan || 0) > 0
);

const tableColumns = [
  { key: 'kode_kasbon_klaim', label: 'Kode Kasbon' },
  { key: 'tanggal_pengajuan', label: 'Tanggal' },
  { key: 'principal', label: 'Principal' },
  {
    key: 'nominal_kasbon_diajukan',
    label: 'Nominal Diajukan',
    render: (row) => `Rp ${Number(row.nominal_kasbon_diajukan || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'tipe_kasbon',
    label: 'Tipe',
    render: (row) => row.tipe_kasbon || '-'
  },
  {
    key: 'status_kasbon',
    label: 'Status',
    render: (row) => row.status_kasbon || '-'
  }
];

function resetForm() {
  form.id_principal = '';
  form.tanggal_pengajuan = toLocalDateInputValue();
  form.nominal_kasbon_diajukan = '';
  form.tipe_kasbon = '1';
  form.keterangan = '';
}

async function loadPrincipals() {
  const response = await getPrincipals();
  principals.value = normalizeList(unwrapResponse(response));
}

async function loadKasbonRows() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getKasbonClaims({
      page: 0,
      limit: 20,
      'no-paginate': 'true'
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
  } catch (err) {
    error.value = normalizeError(err, 'Daftar kasbon belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

async function submitKasbon() {
  if (!isFormReady.value) {
    feedback.value = '';
    error.value = 'Lengkapi principal, tanggal pengajuan, dan nominal kasbon terlebih dahulu.';
    return;
  }

  submitting.value = true;
  error.value = '';
  feedback.value = '';

  try {
    const response = await createKasbonClaim({
      id_principal: Number(form.id_principal),
      tanggal_pengajuan: form.tanggal_pengajuan,
      nominal_kasbon_diajukan: Number(form.nominal_kasbon_diajukan || 0),
      nominal_kasbon_disetujui: Number(form.nominal_kasbon_diajukan || 0),
      id_user_pengaju: auth.user?.id || auth.user?.id_user || auth.user?.user_id || null,
      tipe_kasbon: Number(form.tipe_kasbon || 1),
      keterangan: form.keterangan || ''
    });

    const payload = unwrapResponse(response) || {};
    feedback.value = `Kasbon berhasil diajukan dengan kode ${payload.kode_kasbon || '-'}.`;
    resetForm();
    await loadKasbonRows();
  } catch (err) {
    error.value = normalizeError(err, 'Pengajuan kasbon belum berhasil diproses.');
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  try {
    await loadPrincipals();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi principal belum bisa dimuat.');
  }

  await loadKasbonRows();
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Ajukan Kasbon"
      description="Halaman ini menjadi sumber input kasbon resmi di new-budimas. User memilih principal, menentukan nominal, lalu langsung mengirim pengajuan ke API promo lama."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetForm">
          Reset Form
        </button>
        <button
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          :disabled="submitting"
          @click="submitKasbon"
        >
          {{ submitting ? 'Mengajukan...' : 'Ajukan Kasbon' }}
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Total Kasbon</p>
        <p class="mt-3 text-2xl font-semibold text-slate-900">{{ summary.total.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Draft</p>
        <p class="mt-3 text-2xl font-semibold text-amber-600">{{ summary.draft.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Disetujui</p>
        <p class="mt-3 text-2xl font-semibold text-brand-700">{{ summary.approved.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Diberikan</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.granted.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <div class="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
      <section class="panel p-6">
        <div class="mb-4">
          <h3 class="text-xl font-bold text-slate-950">Form Ajukan Kasbon</h3>
          <p class="mt-1 text-sm text-slate-500">Isi data kasbon dasar dulu. Nanti supervisor bisa memantau dan mengonfirmasi dari menu pengajuan kasbon yang sudah kita buat sebelumnya.</p>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect
            v-model="form.id_principal"
            label="Principal"
            placeholder="Pilih principal"
            :options="principalOptions"
          />
          <AppFormField
            v-model="form.tanggal_pengajuan"
            label="Tanggal Pengajuan"
            type="date"
          />
          <AppFormField
            v-model="form.nominal_kasbon_diajukan"
            label="Nominal Kasbon"
            type="number"
            min="0"
            placeholder="Masukkan nominal kasbon"
          />
          <AppSearchSelect
            v-model="form.tipe_kasbon"
            label="Tipe Kasbon"
            placeholder="Pilih tipe kasbon"
            :options="tipeKasbonOptions"
          />
        </div>

        <div class="mt-4">
          <AppFormField
            v-model="form.keterangan"
            label="Keterangan"
            placeholder="Tambahkan keterangan kasbon"
          />
        </div>
      </section>

      <section class="panel p-6">
        <div class="mb-4">
          <h3 class="text-xl font-bold text-slate-950">Ringkasan Pengajuan</h3>
          <p class="mt-1 text-sm text-slate-500">Saya tampilkan ringkasan sebelum user menekan tombol ajukan.</p>
        </div>

        <div class="space-y-3">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Pengaju</p>
            <p class="mt-2 font-semibold text-slate-900">{{ auth.user?.nama || auth.userName || 'User' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedPrincipal?.nama || selectedPrincipal?.nama_principal || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Nominal</p>
            <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(form.nominal_kasbon_diajukan || 0).toLocaleString('id-ID') }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Tipe Kasbon</p>
            <p class="mt-2 font-semibold text-slate-900">{{ tipeKasbonOptions.find((item) => item.value === String(form.tipe_kasbon))?.label || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Keterangan</p>
            <p class="mt-2 text-sm text-slate-700">{{ form.keterangan || 'Belum ada keterangan tambahan.' }}</p>
          </article>
        </div>
      </section>
    </div>

    <section class="panel p-6">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Kasbon Terbaru</h3>
          <p class="mt-1 text-sm text-slate-500">Daftar ini membantu user memastikan pengajuan kasbon sudah benar-benar masuk ke sistem.</p>
        </div>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="loadKasbonRows">
          Refresh List
        </button>
      </div>

      <AppTable
        :rows="rows"
        :columns="tableColumns"
        :loading="loading"
        :paginated="true"
        :default-page-size="10"
        empty-message="Belum ada pengajuan kasbon yang berhasil dimuat."
      />

      <AppEmptyState
        v-if="!loading && !rows.length"
        title="Belum ada kasbon"
        description="Setelah user mengajukan kasbon, daftar pengajuan terbaru akan muncul di sini."
      />
    </section>
  </div>
</template>
