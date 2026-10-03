<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getPrincipals } from '@/api/master';
import { confirmKasbonClaim, getKasbonClaimDetail, getKasbonClaimItems, getKasbonClaims } from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import {
  getAllowedSalesUserIds,
  getLoginPrincipalIds,
  getLoginSalesUserId,
  getSupervisedSalesRows,
  isSuperUser
} from '@/utils/accessScope';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFilterBar from '@/shared/components/AppFilterBar.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();

const filters = reactive({
  id_principal: '',
  status_kasbon: '',
  filters: ''
});

const principals = ref([]);
const rows = ref([]);
const claimRows = ref([]);
const detail = ref(null);
const loading = ref(false);
const detailLoading = ref(false);
const actionLoading = ref(false);
const error = ref('');
const feedback = ref('');
const selectedRow = ref(null);
const selectedClaimIds = ref([]);

const statusOptions = [
  { value: '0', label: 'Draft' },
  { value: '1', label: 'Disetujui' },
  { value: '2', label: 'Ditolak' },
  { value: '3', label: 'Diberikan' }
];

function parseIdList(...values) {
  return values
    .flatMap((value) => {
      if (Array.isArray(value)) return value;
      return String(value || '').split(',');
    })
    .map((value) => String(value || '').trim())
    .filter(Boolean);
}

const scopedSalesUserIds = computed(() => {
  if (isSuperUser(auth)) return [];

  const supervisedIds = getAllowedSalesUserIds(auth.user);
  if (supervisedIds.length) return supervisedIds;

  const loginUserId = getLoginSalesUserId(auth.user);
  return loginUserId ? [String(loginUserId)] : [];
});

const scopedPrincipalIds = computed(() => {
  if (isSuperUser(auth)) return [];

  const ids = new Set();
  getSupervisedSalesRows(auth.user).forEach((row) => {
    parseIdList(row?.id_principal, row?.principal_id, row?.id_principals, row?.principal_ids).forEach((id) => ids.add(id));
  });

  if (!ids.size) {
    getLoginPrincipalIds(auth.user).forEach((id) => ids.add(String(id)));
  }

  return Array.from(ids);
});

const principalOptions = computed(() =>
  principals.value
    .filter((item) => !scopedPrincipalIds.value.length || scopedPrincipalIds.value.includes(String(item.id)))
    .map((item) => ({
      value: String(item.id),
      label: `${item.kode || item.id} | ${item.nama || item.nama_principal || 'Principal'}`
    }))
);

const filterFields = computed(() => [
  {
    key: 'id_principal',
    label: 'Principal',
    type: 'search-select',
    options: principalOptions.value,
    placeholder: 'Semua principal'
  },
  { key: 'status_kasbon', label: 'Status Kasbon', type: 'search-select', options: statusOptions, placeholder: 'Semua status' },
  { key: 'filters', label: 'Cari', placeholder: 'Kode kasbon, principal, keterangan' }
]);

const selectedKey = computed(() => selectedRow.value?.id || '');
const canConfirm = computed(() => {
  const statusText = String(selectedRow.value?.status_kasbon || '').toLowerCase();
  const hasClaimsToChoose = claimRows.value.length > 0;
  return !!selectedRow.value && statusText !== 'diberikan' && (!hasClaimsToChoose || selectedClaimIds.value.length > 0) && !actionLoading.value;
});

const summary = computed(() => ({
  total: rows.value.length,
  draft: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'draft').length,
  approved: rows.value.filter((row) => String(row.status_kasbon || '').toLowerCase() === 'disetujui').length,
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
  const response = await getPrincipals();
  principals.value = normalizeList(unwrapResponse(response));
}

async function loadKasbonRows(preserveId = null) {
  loading.value = true;
  error.value = '';
  feedback.value = '';
  const targetId = preserveId || selectedRow.value?.id || null;

  try {
    const response = await getKasbonClaims({
      ...filters,
      sales_user_ids: scopedSalesUserIds.value.join(',') || undefined,
      page: 0,
      limit: 100,
      'no-paginate': 'true'
    });
    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.pages || payload);
    selectedRow.value = targetId ? rows.value.find((row) => String(row.id) === String(targetId)) || null : null;
    feedback.value = `Supervisor memuat ${rows.value.length} pengajuan kasbon untuk ditinjau.`;
  } catch (err) {
    error.value = normalizeError(err, 'Data kasbon belum bisa dimuat.');
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
  selectedClaimIds.value = [];

  try {
    const [detailResponse, claimsResponse] = await Promise.all([
      getKasbonClaimDetail(row.id),
      getKasbonClaimItems(row.id, { 'no-paginate': 'true' })
    ]);
    detail.value = unwrapResponse(detailResponse) || null;
    const claimsPayload = unwrapResponse(claimsResponse) || {};
    claimRows.value = normalizeList(claimsPayload.pages || claimsPayload);
    selectedClaimIds.value = claimRows.value.map((item) => String(item.id)).filter(Boolean);
  } catch (err) {
    error.value = normalizeError(err, 'Detail kasbon belum bisa dimuat.');
    detail.value = null;
    claimRows.value = [];
  } finally {
    detailLoading.value = false;
  }
}

function toggleClaimSelection(row) {
  const id = String(row.id);
  if (selectedClaimIds.value.includes(id)) {
    selectedClaimIds.value = selectedClaimIds.value.filter((item) => item !== id);
    return;
  }
  selectedClaimIds.value = [...selectedClaimIds.value, id];
}

async function confirmSelectedKasbon() {
  if (!selectedRow.value?.id) return;
  if (claimRows.value.length && !selectedClaimIds.value.length) {
    selectedClaimIds.value = claimRows.value.map((item) => String(item.id)).filter(Boolean);
  }

  actionLoading.value = true;
  error.value = '';

  try {
    await confirmKasbonClaim(selectedRow.value.id, {
      selectedKlaimIds: selectedClaimIds.value.map((item) => Number(item)),
      id_user_approval: auth.user?.id || auth.user?.id_user || auth.user?.user_id || null
    });

    feedback.value = selectedClaimIds.value.length
      ? `${selectedClaimIds.value.length} klaim berhasil dikonfirmasi untuk kasbon terpilih.`
      : 'Kasbon terpilih berhasil dikonfirmasi.';
    await loadKasbonRows(selectedRow.value.id);
    if (selectedRow.value?.id) {
      await loadKasbonDetail(selectedRow.value);
    }
  } catch (err) {
    error.value = normalizeError(err, 'Konfirmasi kasbon belum berhasil diproses.');
  } finally {
    actionLoading.value = false;
  }
}

function resetFilters() {
  filters.id_principal = '';
  filters.status_kasbon = '';
  filters.filters = '';
  loadKasbonRows();
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
      title="Approval Kasbon"
      description="Supervisor meninjau pengajuan kasbon klaim, memeriksa klaim yang dijaminkan, lalu mengonfirmasi kasbon yang siap diteruskan."
    >
      <div class="flex flex-wrap gap-2">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset Filter
        </button>
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700" @click="loadKasbonRows">
          Refresh Data
        </button>
      </div>
    </PageHeader>

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

    <AppFilterBar v-model="filters" :fields="filterFields" @submit="loadKasbonRows" @reset="resetFilters" />

    <section v-if="feedback" class="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
      {{ feedback }}
    </section>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <div class="grid gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(360px,0.95fr)]">
      <section class="panel p-5">
        <div class="mb-4">
          <h3 class="text-lg font-semibold text-slate-900">Daftar Approval Kasbon</h3>
          <p class="mt-1 text-sm text-slate-500">Pilih salah satu kasbon untuk melihat detail dan daftar klaim yang dijaminkan.</p>
        </div>

        <AppTable
          :columns="tableColumns"
          :rows="rows"
          :loading="loading"
          row-key="id"
          :selected-key="selectedKey"
          :clickable-rows="true"
          empty-message="Belum ada pengajuan kasbon untuk filter yang dipilih."
          @row-click="loadKasbonDetail"
        />
      </section>

      <section class="panel p-5">
        <div v-if="selectedRow" class="space-y-4">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Detail Approval Kasbon</h3>
            <p class="mt-1 text-sm text-slate-500">Ringkasan pengajuan dan aksi supervisor untuk kasbon yang dipilih.</p>
          </div>

          <div v-if="detail" class="grid gap-3 md:grid-cols-2">
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Kode Kasbon</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.kode_kasbon_klaim || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
              <p class="mt-2 font-semibold text-slate-900">{{ detail.principal || '-' }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Diajukan</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.nominal_kasbon_diajukan || 0).toLocaleString('id-ID') }}</p>
            </article>
            <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <p class="text-xs uppercase tracking-wide text-slate-400">Disetujui</p>
              <p class="mt-2 font-semibold text-slate-900">Rp {{ Number(detail.nominal_kasbon_disetujui || 0).toLocaleString('id-ID') }}</p>
            </article>
          </div>

          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            {{ detail?.keterangan || 'Belum ada keterangan tambahan untuk kasbon ini.' }}
          </div>

          <button
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
            :disabled="!canConfirm"
            @click="confirmSelectedKasbon"
          >
            {{ actionLoading ? 'Memproses...' : selectedClaimIds.length ? `Konfirmasi ${selectedClaimIds.length} Klaim` : 'Konfirmasi Kasbon' }}
          </button>
        </div>

        <div v-else class="py-8">
          <AppEmptyState
            title="Belum ada kasbon terpilih"
            description="Pilih salah satu pengajuan kasbon dari tabel kiri untuk melihat detail dan daftar klaimnya."
          />
        </div>
      </section>
    </div>

    <section class="panel p-5">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-lg font-semibold text-slate-900">Daftar Klaim di Dalam Kasbon</h3>
          <p class="mt-1 text-sm text-slate-500">Supervisor bisa memilih klaim yang akan dijaminkan saat kasbon dikonfirmasi.</p>
        </div>
        <div class="text-sm text-slate-500">{{ selectedClaimIds.length }} klaim dipilih</div>
      </div>

      <div v-if="detailLoading" class="py-10 text-center text-sm text-slate-500">
        Memuat klaim kasbon...
      </div>

      <div v-else-if="claimRows.length" class="overflow-x-auto rounded-2xl border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th class="px-4 py-3">Pilih</th>
              <th class="px-4 py-3">Nomor Klaim</th>
              <th class="px-4 py-3">Kode Promo</th>
              <th class="px-4 py-3">Nama Promo</th>
              <th class="px-4 py-3">Nominal Klaim</th>
              <th class="px-4 py-3">Nominal Dijamin</th>
              <th class="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr
              v-for="row in claimRows"
              :key="row.id"
              :class="selectedClaimIds.includes(String(row.id)) ? 'bg-brand-50/60' : ''"
            >
              <td class="px-4 py-3">
                <input
                  :checked="selectedClaimIds.includes(String(row.id))"
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                  @change="toggleClaimSelection(row)"
                >
              </td>
              <td class="px-4 py-3">{{ row.nomor_klaim || '-' }}</td>
              <td class="px-4 py-3">{{ row.kode_promo || '-' }}</td>
              <td class="px-4 py-3">{{ row.nama_promo || '-' }}</td>
              <td class="px-4 py-3">Rp {{ Number(row.nominal_klaim || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">Rp {{ Number(row.nominal_dijamin || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">{{ row.status_klaim || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <AppEmptyState
        v-else
        title="Belum ada klaim kasbon"
        description="Pilih kasbon terlebih dahulu, atau pengajuan ini memang belum memiliki klaim yang dijaminkan."
      />
    </section>
  </div>
</template>
