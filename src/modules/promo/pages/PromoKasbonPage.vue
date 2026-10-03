<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { useAuthStore } from '@/app/stores/auth';
import { getKasbonClaimDetail, getKasbonClaimItems, getKasbonClaims } from '@/api/promo';
import {
  canAccessAllPromoBranches,
  getPromoBranchOptions,
  getPromoCompanyOptions,
  getPromoFallbackBranchId,
  getPromoPrincipalOptions
} from '@/modules/promo/utils/promoScope';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const filters = reactive({
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  status_kasbon: '',
  filters: ''
});

const auth = useAuthStore();
const branches = ref([]);
const companies = ref([]);
const principals = ref([]);
const rows = ref([]);
const claimRows = ref([]);
const detail = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);

const statusOptions = [
  { value: '', label: 'Semua status' },
  { value: '0', label: 'Draft' },
  { value: '1', label: 'Disetujui' },
  { value: '2', label: 'Ditolak' },
  { value: '3', label: 'Diberikan' }
];

const canAccessAllBranches = computed(() => canAccessAllPromoBranches(auth));
const branchOptions = computed(() => getPromoBranchOptions(branches.value, auth));
const companyOptions = computed(() => getPromoCompanyOptions(companies.value, branches.value, filters.id_cabang));
const principalOptions = computed(() => getPromoPrincipalOptions(principals.value, filters.id_perusahaan));

const filterFields = computed(() => [
  { key: 'id_cabang', label: 'Cabang', type: 'search-select', options: branchOptions.value, disabled: !canAccessAllBranches.value },
  { key: 'id_perusahaan', label: 'Perusahaan', type: 'search-select', options: companyOptions.value, disabled: !filters.id_cabang },
  {
    key: 'id_principal',
    label: 'Principal',
    type: 'search-select',
    options: principalOptions.value,
    disabled: !filters.id_perusahaan
  },
  { key: 'status_kasbon', label: 'Status Kasbon', type: 'search-select', options: statusOptions },
  { key: 'filters', label: 'Cari', placeholder: 'Kode kasbon, principal, keterangan' }
]);

const selectedKey = computed(() => selectedRow.value?.id || '');

const summary = computed(() => ({
  total: rows.value.length,
  draft: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'draft').length,
  approved: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'disetujui').length,
  rejected: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'ditolak').length,
  granted: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'diberikan').length
}));

const tableColumns = [
  { key: 'kode_kasbon_klaim', label: 'Kode Kasbon' },
  { key: 'tanggal_pengajuan', label: 'Tanggal Pengajuan' },
  { key: 'principal', label: 'Principal' },
  {
    key: 'nominal_kasbon_diajukan',
    label: 'Diajukan',
    render: (row) => `Rp ${Number(row.nominal_kasbon_diajukan || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'nominal_kasbon_disetujui',
    label: 'Disetujui',
    render: (row) => `Rp ${Number(row.nominal_kasbon_disetujui || 0).toLocaleString('id-ID')}`
  },
  { key: 'status_kasbon', label: 'Status' }
];

const claimTableColumns = [
  { key: 'nomor_klaim', label: 'Nomor Klaim' },
  { key: 'kode_promo', label: 'Kode Promo' },
  { key: 'nama_promo', label: 'Nama Promo' },
  {
    key: 'nominal_klaim',
    label: 'Nominal Klaim',
    render: (row) => `Rp ${Number(row.nominal_klaim || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'nominal_dijamin',
    label: 'Nominal Dijamin',
    render: (row) => `Rp ${Number(row.nominal_dijamin || 0).toLocaleString('id-ID')}`
  },
  { key: 'status_klaim', label: 'Status Klaim' }
];

async function loadPrincipals() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([
    getBranches(),
    getCompanies(),
    getPrincipals()
  ]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  applyLoginBranchScope();
}

async function loadKasbonRows(preserveId = null) {
  loading.value = true;
  error.value = '';
  const targetId = preserveId || selectedRow.value?.id || null;

  try {
    const response = await getKasbonClaims({
      ...filters,
      page: 0,
      limit: 100,
      'no-paginate': 'true'
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
    selectedRow.value = targetId ? rows.value.find((row) => String(row.id) === String(targetId)) || null : null;
    feedback.value = `Kasbon klaim memuat ${rows.value.length} data untuk ditinjau user.`;
  } catch (err) {
    error.value = normalizeError(err, 'Data kasbon klaim belum bisa dimuat.');
    rows.value = [];
    selectedRow.value = null;
  } finally {
    loading.value = false;
  }
}

async function loadKasbonDetail(row = selectedRow.value) {
  if (!row?.id) return;

  selectedRow.value = row;
  detailLoading.value = true;
  error.value = '';

  try {
    const [detailResponse, claimsResponse] = await Promise.all([
      getKasbonClaimDetail(row.id),
      getKasbonClaimItems(row.id, { 'no-paginate': 'true' })
    ]);
    detail.value = unwrapResponse(detailResponse) || null;
    const claimsPayload = unwrapResponse(claimsResponse) || {};
    claimRows.value = normalizeList(claimsPayload.pages || claimsPayload);
  } catch (err) {
    error.value = normalizeError(err, 'Detail kasbon klaim belum bisa dimuat.');
    detail.value = null;
    claimRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

function resetFilters() {
  filters.id_cabang = canAccessAllBranches.value ? '' : getPromoFallbackBranchId(auth) || '';
  filters.id_perusahaan = '';
  filters.id_principal = '';
  filters.status_kasbon = '';
  filters.filters = '';
  loadKasbonRows();
}

function applyLoginBranchScope() {
  const fallbackBranch = getPromoFallbackBranchId(auth);
  if (!canAccessAllBranches.value && fallbackBranch) {
    filters.id_cabang = String(fallbackBranch);
  }
}

function updateFilters(nextFilters) {
  const previousBranch = filters.id_cabang;
  const previousCompany = filters.id_perusahaan;
  Object.assign(filters, nextFilters || {});
  if (String(previousBranch || '') !== String(filters.id_cabang || '')) {
    filters.id_perusahaan = '';
    filters.id_principal = '';
    selectedRow.value = null;
    detail.value = null;
    return;
  }
  if (String(previousCompany || '') !== String(filters.id_perusahaan || '')) {
    filters.id_principal = '';
    selectedRow.value = null;
    detail.value = null;
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
      title="Daftar Kasbon"
      description="User bisa memantau semua pengajuan kasbon promo, melihat nominal yang diajukan dan disetujui, serta membaca klaim yang dijaminkan pada setiap kasbon."
    />

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
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
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Ditolak</p>
        <p class="mt-3 text-2xl font-semibold text-rose-600">{{ summary.rejected.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-xs uppercase tracking-[0.25em] text-slate-400">Diberikan</p>
        <p class="mt-3 text-2xl font-semibold text-emerald-600">{{ summary.granted.toLocaleString('id-ID') }}</p>
      </article>
    </section>

    <AppFilterBar :model-value="filters" :fields="filterFields" @update:model-value="updateFilters" @submit="loadKasbonRows" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
      <section class="panel p-5">
        <div class="mb-4">
          <h3 class="text-lg font-semibold text-slate-900">Daftar Daftar Kasbon</h3>
          <p class="mt-1 text-sm text-slate-500">Klik salah satu kasbon untuk membaca detail pengajuan dan klaim yang dijaminkan.</p>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="rows"
          :loading="loading"
          row-key="id"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada kasbon klaim untuk filter yang dipilih."
          @row-click="loadKasbonDetail"
        />
      </section>

      <section class="panel p-5">
        <div v-if="selectedRow" class="space-y-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Detail Kasbon</h3>
            <p class="mt-1 text-sm text-slate-500">Ringkasan pengajuan kasbon yang dipilih.</p>
          </div>

          <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
            Memuat detail kasbon...
          </div>

          <template v-else-if="detail">
            <div class="grid gap-3 md:grid-cols-2">
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Kode Kasbon</p>
                <p class="mt-2 font-semibold text-slate-900">{{ detail.kode_kasbon_klaim || '-' }}</p>
              </article>
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
                <p class="mt-2 font-semibold text-slate-900">{{ detail.principal || '-' }}</p>
              </article>
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Tanggal Pengajuan</p>
                <p class="mt-2 font-semibold text-slate-900">{{ detail.tanggal_pengajuan || '-' }}</p>
              </article>
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Status</p>
                <p class="mt-2 font-semibold text-slate-900">{{ detail.status_kasbon || '-' }}</p>
              </article>
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Nominal Diajukan</p>
                <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.nominal_kasbon_diajukan || 0).toLocaleString('id-ID') }}</p>
              </article>
              <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                <p class="text-xs uppercase tracking-wide text-slate-400">Nominal Disetujui</p>
                <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.nominal_kasbon_disetujui || 0).toLocaleString('id-ID') }}</p>
              </article>
            </div>

            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              {{ detail.keterangan || 'Belum ada keterangan tambahan untuk kasbon ini.' }}
            </div>
          </template>
        </div>

        <div v-else class="py-8">
          <AppEmptyState
            title="Belum ada kasbon terpilih"
            description="Pilih salah satu kasbon klaim dari tabel kiri untuk membuka ringkasannya."
          />
        </div>
      </section>
    </div>

    <section class="panel p-5">
      <div class="mb-4">
        <h3 class="text-lg font-semibold text-slate-900">Daftar Klaim di Dalam Kasbon</h3>
        <p class="mt-1 text-sm text-slate-500">Bagian ini membantu user memastikan klaim apa saja yang dijaminkan pada kasbon yang dipilih.</p>
      </div>

      <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
        Memuat daftar klaim kasbon...
      </div>

      <AppTable
        v-else-if="claimRows.length"
        :columns="claimTableColumns"
        :rows="claimRows"
        :loading="false"
        row-key="id"
        :paginated="true"
        :default-page-size="10"
        empty-message="Belum ada klaim kasbon yang bisa ditampilkan."
      />

      <AppEmptyState
        v-else
        title="Belum ada klaim kasbon"
        description="Pilih kasbon terlebih dahulu, atau pengajuan ini memang belum memiliki klaim yang dijaminkan."
      />
    </section>
  </div>
</template>
