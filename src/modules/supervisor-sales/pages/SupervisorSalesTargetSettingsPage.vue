<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { getBranches, getCompanies, getPrincipals } from '@/api/master';
import { getMonthlySalesTargets, saveMonthlySalesTargets } from '@/api/sales';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';
import {
  getSupervisorBranchOptions,
  getSupervisorCompanyOptions,
  getSupervisorPrincipalOptions,
  resetSupervisorBranchWhenCompanyChanges,
  syncSupervisorCompanyFromBranch,
} from '@/modules/supervisor-sales/utils/supervisorScope';

const auth = useAuthStore();
const now = new Date();

const filter = reactive({
  tahun: String(now.getFullYear()),
  bulan: String(now.getMonth() + 1).padStart(2, '0'),
  id_cabang: '',
  id_perusahaan: '',
  id_principal: '',
  search: ''
});

const loading = ref(false);
const saving = ref(false);
const error = ref('');
const feedback = ref('');
const principals = ref([]);
const companies = ref([]);
const branches = ref([]);
const rows = ref([]);

const fallbackBranchId = computed(() => auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
const companyOptions = computed(() => getSupervisorCompanyOptions(companies.value, branches.value, '', auth, true));
const branchOptions = computed(() => getSupervisorBranchOptions(branches.value, auth, true, filter.id_perusahaan, companies.value));
const principalOptions = computed(() => getSupervisorPrincipalOptions(principals.value, filter.id_perusahaan, true));

const monthOptions = [
  { value: '01', label: 'Januari' },
  { value: '02', label: 'Februari' },
  { value: '03', label: 'Maret' },
  { value: '04', label: 'April' },
  { value: '05', label: 'Mei' },
  { value: '06', label: 'Juni' },
  { value: '07', label: 'Juli' },
  { value: '08', label: 'Agustus' },
  { value: '09', label: 'September' },
  { value: '10', label: 'Oktober' },
  { value: '11', label: 'November' },
  { value: '12', label: 'Desember' }
];

const summary = computed(() => {
  const totalTargetVisit = rows.value.reduce((sum, row) => sum + Number(row.target_kunjungan || 0), 0);
  const totalActualVisit = rows.value.reduce((sum, row) => sum + Number(row.actual_kunjungan || 0), 0);
  const visitAchievement = totalTargetVisit > 0 ? Math.round((totalActualVisit / totalTargetVisit) * 10000) / 100 : 0;
  const totalTarget = rows.value.reduce((sum, row) => sum + Number(row.target_omset || 0), 0);
  const totalActual = rows.value.reduce((sum, row) => sum + Number(row.actual_omset || 0), 0);
  const omsetAchievement = totalTarget > 0 ? Math.round((totalActual / totalTarget) * 10000) / 100 : 0;

  return {
    salesCount: rows.value.length,
    totalTargetVisit,
    totalActualVisit,
    visitAchievement,
    totalTarget,
    totalActual,
    omsetAchievement
  };
});

const filteredRows = computed(() => {
  const query = String(filter.search || '').trim().toLowerCase();
  if (!query) return rows.value;

  return rows.value.filter((row) =>
    [row.nama_sales, row.kode_sales, row.nama_cabang, row.nama_principals]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query))
  );
});

const changedRows = computed(() =>
  rows.value.filter((row) =>
    Number(row.target_kunjungan || 0) !== Number(row.original_target_kunjungan || 0) ||
    Number(row.target_omset || 0) !== Number(row.original_target_omset || 0) ||
    String(row.notes || '') !== String(row.original_notes || '')
  )
);

const columns = [
  {
    key: 'nama_sales',
    label: 'Sales',
    render: (row) => `${row.nama_sales || '-'}${row.kode_sales ? ` (${row.kode_sales})` : ''}`
  },
  { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nama_principals', label: 'Principal' },
  {
    key: 'actual_kunjungan',
    label: 'Kunjungan Aktual',
    render: (row) => `${Number(row.actual_kunjungan || 0).toLocaleString('id-ID')} visit`
  },
  {
    key: 'visit_achievement_percent',
    label: 'Pencapaian Visit',
    render: (row) => `${Number(row.visit_achievement_percent || 0).toLocaleString('id-ID')}%`
  },
  {
    key: 'actual_omset',
    label: 'Omset Aktual',
    render: (row) => `Rp ${Number(row.actual_omset || 0).toLocaleString('id-ID')}`
  },
  {
    key: 'achievement_percent',
    label: 'Pencapaian',
    render: (row) => `${Number(row.achievement_percent || 0).toLocaleString('id-ID')}%`
  }
];

async function loadPrincipals() {
  const [branchResponse, companyResponse, principalResponse] = await Promise.all([getBranches(), getCompanies(), getPrincipals()]);
  branches.value = normalizeList(unwrapResponse(branchResponse));
  companies.value = normalizeList(unwrapResponse(companyResponse));
  principals.value = normalizeList(unwrapResponse(principalResponse));
  if (!filter.id_cabang && fallbackBranchId.value) filter.id_cabang = String(fallbackBranchId.value);
  syncSupervisorCompanyFromBranch(filter, 'id_cabang', 'id_perusahaan', branches.value, companies.value);
}

async function loadTargets() {
  loading.value = true;
  error.value = '';

  try {
    const response = await getMonthlySalesTargets({
      tahun: filter.tahun,
      bulan: Number(filter.bulan),
      id_principal: filter.id_principal || undefined,
      id_cabang: filter.id_cabang || fallbackBranchId.value || undefined,
      id_perusahaan: filter.id_perusahaan || undefined
    });

    const payload = unwrapResponse(response) || {};
    rows.value = normalizeList(payload.rows).map((row) => ({
      ...row,
      target_kunjungan: Number(row.target_kunjungan || 0),
      actual_kunjungan: Number(row.actual_kunjungan || 0),
      visit_achievement_percent: Number(row.visit_achievement_percent || 0),
      target_omset: Number(row.target_omset || 0),
      actual_omset: Number(row.actual_omset || 0),
      achievement_percent: Number(row.achievement_percent || 0),
      original_target_kunjungan: Number(row.target_kunjungan || 0),
      original_target_omset: Number(row.target_omset || 0),
      original_notes: row.notes || ''
    }));

    feedback.value = `Data target sales untuk ${monthOptions.find((item) => item.value === filter.bulan)?.label || filter.bulan} ${filter.tahun} berhasil dimuat.`;
  } catch (err) {
    error.value = normalizeError(err, 'Data target sales belum bisa dimuat.');
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function updateTargetValue(idSales, value) {
  rows.value = rows.value.map((row) =>
    row.id_sales === idSales
      ? {
          ...row,
          target_omset: Number(value || 0),
          achievement_percent: Number(value || 0) > 0
            ? Math.round((Number(row.actual_omset || 0) / Number(value || 0)) * 10000) / 100
            : 0
        }
      : row
  );
}

function updateVisitTargetValue(idSales, value) {
  rows.value = rows.value.map((row) =>
    row.id_sales === idSales
      ? {
          ...row,
          target_kunjungan: Number(value || 0),
          visit_achievement_percent: Number(value || 0) > 0
            ? Math.round((Number(row.actual_kunjungan || 0) / Number(value || 0)) * 10000) / 100
            : 0
        }
      : row
  );
}

function updateNotesValue(idSales, value) {
  rows.value = rows.value.map((row) =>
    row.id_sales === idSales
      ? { ...row, notes: value }
      : row
  );
}

async function saveTargets() {
  if (!changedRows.value.length) {
    feedback.value = 'Belum ada perubahan target yang perlu disimpan.';
    return;
  }

  saving.value = true;
  error.value = '';

  try {
    await saveMonthlySalesTargets({
      tahun: Number(filter.tahun),
      bulan: Number(filter.bulan),
      rows: changedRows.value.map((row) => ({
        id_sales: row.id_sales,
        id_user: row.id_user,
        id_cabang: row.id_cabang,
        target_kunjungan: Number(row.target_kunjungan || 0),
        target_omset: Number(row.target_omset || 0),
        notes: row.notes || ''
      }))
    });

    feedback.value = `${changedRows.value.length} target sales berhasil disimpan.`;
    await loadTargets();
  } catch (err) {
    error.value = normalizeError(err, 'Simpan target sales gagal.');
  } finally {
    saving.value = false;
  }
}

const showTargetModal = ref(false);

function openTargetModal() {
  showTargetModal.value = true;
}

function closeTargetModal() {
  showTargetModal.value = false;
}

onMounted(async () => {
  await loadPrincipals();
  await loadTargets();
});

function handleCompanyChange() {
  resetSupervisorBranchWhenCompanyChanges(filter, 'id_perusahaan', 'id_cabang', branches.value, auth, companies.value);
  filter.id_principal = '';
}
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Setting Target Sales"
      description="Supervisor bisa menetapkan target kunjungan dan target omset bulanan per sales, lalu langsung membandingkan realisasi visit maupun transaksi pada periode aktif."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="loadTargets">
          Refresh
        </button>
        <!-- <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60" :disabled="saving" @click="saveTargets">
          {{ saving ? 'Menyimpan...' : `Simpan ${changedRows.length} Perubahan` }}
        </button> -->
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Jumlah Sales</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ summary.salesCount }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Target Kunjungan</p>
        <p class="mt-3 text-3xl font-bold text-slate-950">{{ summary.totalTargetVisit.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Aktual Kunjungan</p>
        <p class="mt-3 text-3xl font-bold text-emerald-600">{{ summary.totalActualVisit.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Pencapaian Visit</p>
        <p class="mt-3 text-3xl font-bold text-brand-700">{{ summary.visitAchievement.toLocaleString('id-ID') }}%</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Target</p>
        <p class="mt-3 text-2xl font-bold text-slate-950">Rp {{ summary.totalTarget.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Total Aktual</p>
        <p class="mt-3 text-2xl font-bold text-emerald-600">Rp {{ summary.totalActual.toLocaleString('id-ID') }}</p>
      </article>
      <article class="panel p-5">
        <p class="text-sm font-semibold text-slate-500">Pencapaian Omset</p>
        <p class="mt-3 text-3xl font-bold text-brand-700">{{ summary.omsetAchievement.toLocaleString('id-ID') }}%</p>
      </article>
    </section>

    <section class="panel p-6">
      <div class="grid gap-4 md:grid-cols-6">
        <AppFormField v-model="filter.tahun" label="Tahun" type="number" />
        <AppSearchSelect v-model="filter.bulan" label="Bulan" placeholder="Pilih bulan" :options="monthOptions" />
        <AppSearchSelect v-model="filter.id_perusahaan" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" @update:model-value="handleCompanyChange" />
        <AppSearchSelect v-model="filter.id_cabang" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppSearchSelect v-model="filter.id_principal" label="Principal" placeholder="Semua principal" :options="principalOptions" :disabled="!filter.id_perusahaan" empty-text="Pilih perusahaan terlebih dahulu." />
        <AppFormField v-model="filter.search" label="Cari Sales" placeholder="Nama sales, kode, cabang" />
      </div>

      <div class="mt-5 flex flex-wrap gap-3">
        <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700" @click="loadTargets">
          Tampilkan Data
        </button>
      </div>

      <div v-if="feedback" class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-700">
        {{ feedback }}
      </div>
    </section>

    

    <section class="panel p-6">
      <div class="flex flex-wrap items-center gap-2">
  <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
    {{ filteredRows.length }} Sales
  </div>

  <button
    v-if="filteredRows.length"
    type="button"
    class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
    @click="openTargetModal"
  >
    Atur Target
  </button>
</div>

      <AppTable
        :rows="filteredRows"
        :columns="columns"
        :loading="loading"
        :paginated="true"
        :default-page-size="15"
        empty-message="Belum ada data sales untuk target bulan yang dipilih."
      />

      
    </section>
    <Teleport to="body">
  <div
    v-if="showTargetModal"
    class="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm"
  >
    <div class="flex max-h-[90vh] w-full max-w-7xl flex-col overflow-hidden rounded-3xl bg-white shadow-2xl">
      <div class="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 px-6 py-5">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Atur Target Sales</h3>
          <p class="mt-1 text-sm text-slate-500">
            Ubah target visit, target omset, dan catatan sales untuk periode
            {{ monthOptions.find((item) => item.value === filter.bulan)?.label || filter.bulan }}
            {{ filter.tahun }}.
          </p>
        </div>

        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            {{ filteredRows.length }} Sales
          </span>

          <span
            v-if="changedRows.length"
            class="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700"
          >
            {{ changedRows.length }} Perubahan
          </span>

          <button
            type="button"
            class="rounded-xl border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-50"
            @click="closeTargetModal"
          >
            Tutup
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-auto px-6 py-5">
        <div class="overflow-x-auto rounded-3xl border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="sticky top-0 z-10 bg-slate-50">
              <tr>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Sales</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Principal</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Visit Aktual</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Target Visit</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Pencapaian Visit</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Omset Aktual</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Target Omset</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Pencapaian Omset</th>
                <th class="px-4 py-3 text-left font-medium uppercase tracking-wide text-slate-500">Catatan</th>
              </tr>
            </thead>

            <tbody class="divide-y divide-slate-100 bg-white">
              <tr
                v-for="row in filteredRows"
                :key="row.id_sales"
                class="align-top hover:bg-slate-50/70"
              >
                <td class="px-4 py-3 text-slate-700">
                  <p class="font-semibold text-slate-950">{{ row.nama_sales || '-' }}</p>
                  <p class="text-xs text-slate-500">{{ row.kode_sales || row.nama_cabang || '-' }}</p>
                </td>

                <td class="px-4 py-3 text-slate-700">
                  {{ row.nama_principals || '-' }}
                </td>

                <td class="px-4 py-3 text-slate-700">
                  {{ Number(row.actual_kunjungan || 0).toLocaleString('id-ID') }} visit
                </td>

                <td class="px-4 py-3">
                  <input
                    :value="row.target_kunjungan"
                    type="number"
                    min="0"
                    class="w-36 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    @input="updateVisitTargetValue(row.id_sales, $event.target.value)"
                  />
                </td>

                <td class="px-4 py-3">
                  <span
                    :class="[
                      'rounded-full px-3 py-1 text-xs font-semibold',
                      row.visit_achievement_percent >= 100
                        ? 'bg-emerald-100 text-emerald-700'
                        : row.visit_achievement_percent >= 70
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-rose-100 text-rose-700'
                    ]"
                  >
                    {{ Number(row.visit_achievement_percent || 0).toLocaleString('id-ID') }}%
                  </span>
                </td>

                <td class="px-4 py-3 text-slate-700">
                  Rp {{ Number(row.actual_omset || 0).toLocaleString('id-ID') }}
                </td>

                <td class="px-4 py-3">
                  <input
                    :value="row.target_omset"
                    type="number"
                    min="0"
                    class="w-44 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    @input="updateTargetValue(row.id_sales, $event.target.value)"
                  />
                </td>

                <td class="px-4 py-3">
                  <span
                    :class="[
                      'rounded-full px-3 py-1 text-xs font-semibold',
                      row.achievement_percent >= 100
                        ? 'bg-emerald-100 text-emerald-700'
                        : row.achievement_percent >= 70
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-rose-100 text-rose-700'
                    ]"
                  >
                    {{ Number(row.achievement_percent || 0).toLocaleString('id-ID') }}%
                  </span>
                </td>

                <td class="px-4 py-3">
                  <input
                    :value="row.notes || ''"
                    type="text"
                    class="w-56 rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
                    placeholder="Catatan"
                    @input="updateNotesValue(row.id_sales, $event.target.value)"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-6 py-4">
        <p class="text-sm text-slate-500">
          Perubahan belum tersimpan: 
          <span class="font-semibold text-slate-900">{{ changedRows.length }}</span>
        </p>

        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            @click="closeTargetModal"
          >
            Batal
          </button>

          <button
            type="button"
            class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
            :disabled="saving || !changedRows.length"
            @click="saveTargets"
          >
            {{ saving ? 'Menyimpan...' : `Simpan ${changedRows.length} Perubahan` }}
          </button>
        </div>
      </div>
    </div>
  </div>
</Teleport>
  </div>
</template>
