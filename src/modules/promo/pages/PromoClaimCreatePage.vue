<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import {
  createPromoClaim,
  generatePromoClaimCode,
  getPromoClaimCategories,
  getPromoClaimReadyDropdownData,
  getPromoClaimInvoiceList,
} from '@/api/promo';
import { useAuthStore } from '@/app/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { toLocalDateInputValue } from '@/utils/date';
import AppEmptyState from '@/shared/components/AppEmptyState.vue';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const router = useRouter();

const form = reactive({
  id_principal: '',
  promo_key: '',
  kode_voucher: '',
  claim_source: 'legacy_voucher',
  id_unified_promo: '',
  nomor_klaim: '',
  id_kategori_klaim: '',
  tanggal_pengajuan_klaim: toLocalDateInputValue(),
  total_dpp: 0,
  total_ppn: 0,
  total_pph: 0,
  total_klaim_diajukan: 0,
  status_klaim: true
});

const dropdownData = ref({ principal: [], kode_promo: [] });
const categories = ref([]);
const invoiceRows = ref([]);
const selectedInvoiceIds = ref([]);
const loadingCode = ref(false);
const loadingInvoices = ref(false);
const submitting = ref(false);
const error = ref('');
const feedback = ref('');

const principalOptions = computed(() =>
  normalizeList(dropdownData.value.principal).map((item) => ({
    value: String(item.id),
    label: item.nama || `Principal ${item.id}`
  }))
);

function getPromoSelectionKey(item = {}) {
  if (item.selection_key) return String(item.selection_key);
  const source = item.claim_source || 'legacy_voucher';
  const referenceId = item.id_unified_promo || item.id_voucher || item.id || item.kode_promo || '';
  return `${source}:${referenceId}:${item.id_principal || 0}`;
}

const promoOptions = computed(() =>
  normalizeList(dropdownData.value.kode_promo)
    .filter((item) => !form.id_principal || String(item.id_principal) === String(form.id_principal))
    .map((item) => ({
      value: getPromoSelectionKey(item),
      label: `${item.kode_promo} | ${item.nama_promo || 'Promo'}${item.claim_source === 'unified_promo' ? ' · Promo All-In' : ''}`,
      meta: item
    }))
);

const categoryOptions = computed(() =>
  categories.value.map((item) => ({
    value: String(item.id),
    label: `${item.nama}${item.deskripsi ? ` | ${item.deskripsi}` : ''}`
  }))
);

const selectedPrincipal = computed(() =>
  normalizeList(dropdownData.value.principal).find((item) => String(item.id) === String(form.id_principal))
);

const selectedPromo = computed(() =>
  normalizeList(dropdownData.value.kode_promo).find((item) => getPromoSelectionKey(item) === String(form.promo_key))
);

const selectedInvoices = computed(() =>
  invoiceRows.value.filter((row) => selectedInvoiceIds.value.includes(String(row.id)))
);

const totals = computed(() => {
  const totalDpp = selectedInvoices.value.reduce((sum, row) => sum + Number(row.calculated_dpp || 0), 0);
  const totalPpn = selectedInvoices.value.reduce((sum, row) => sum + Number(row.calculated_ppn_value || 0), 0);
  const totalClaim = selectedInvoices.value.reduce((sum, row) => sum + Number(row.estimasi_klaim || 0), 0);
  return {
    totalDpp,
    totalPpn,
    totalClaim
  };
});

const isFormReady = computed(() =>
  !!form.id_principal &&
  !!form.kode_voucher &&
  !!form.nomor_klaim &&
  !!form.id_kategori_klaim &&
  !!form.tanggal_pengajuan_klaim &&
  selectedInvoiceIds.value.length > 0
);

function syncTotalsToForm() {
  form.total_dpp = Number(totals.value.totalDpp.toFixed(2));
  form.total_ppn = Number(totals.value.totalPpn.toFixed(2));
  form.total_pph = 0;
  form.total_klaim_diajukan = Number(totals.value.totalClaim.toFixed(2));
}

function resetForm() {
  form.id_principal = '';
  form.promo_key = '';
  form.kode_voucher = '';
  form.claim_source = 'legacy_voucher';
  form.id_unified_promo = '';
  form.nomor_klaim = '';
  form.id_kategori_klaim = '';
  form.tanggal_pengajuan_klaim = toLocalDateInputValue();
  form.total_dpp = 0;
  form.total_ppn = 0;
  form.total_pph = 0;
  form.total_klaim_diajukan = 0;
  form.status_klaim = true;
  invoiceRows.value = [];
  selectedInvoiceIds.value = [];
}

function toggleInvoice(row) {
  const key = String(row.id);
  if (selectedInvoiceIds.value.includes(key)) {
    selectedInvoiceIds.value = selectedInvoiceIds.value.filter((item) => item !== key);
  } else {
    selectedInvoiceIds.value = [...selectedInvoiceIds.value, key];
  }
  syncTotalsToForm();
}

async function loadReferences() {
  const [readyDropdownResponse, categoryResponse] = await Promise.all([
    getPromoClaimReadyDropdownData(),
    getPromoClaimCategories()
  ]);

  const readyDropdown = unwrapResponse(readyDropdownResponse) || {};

  dropdownData.value = {
    principal: normalizeList(readyDropdown.principal),
    kode_promo: normalizeList(readyDropdown.kode_promo)
  };
  categories.value = normalizeList(unwrapResponse(categoryResponse));
}

async function generateClaimCodeIfNeeded() {
  if (!form.id_principal) return;

  loadingCode.value = true;
  error.value = '';

  try {
    const response = await generatePromoClaimCode({
      id_principal: Number(form.id_principal)
    });
    const payload = unwrapResponse(response) || {};
    form.nomor_klaim = payload.kode_klaim || '';
  } catch (err) {
    error.value = normalizeError(err, 'Nomor klaim otomatis belum bisa dibuat.');
  } finally {
    loadingCode.value = false;
  }
}

async function loadInvoices() {
  invoiceRows.value = [];
  selectedInvoiceIds.value = [];
  syncTotalsToForm();

  const promo = selectedPromo.value;
  if (!promo?.kode_promo) return;

  loadingInvoices.value = true;
  error.value = '';

  try {
    const response = await getPromoClaimInvoiceList({
      kode_promo: promo.kode_promo,
      claim_source: promo.claim_source || 'legacy_voucher',
      id_unified_promo: promo.id_unified_promo || undefined,
      id_principal: form.id_principal || undefined
    });
    invoiceRows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    error.value = normalizeError(err, 'Daftar faktur promo belum bisa dimuat.');
    invoiceRows.value = [];
  } finally {
    loadingInvoices.value = false;
  }
}

async function submitClaim() {
  if (!isFormReady.value) {
    error.value = 'Lengkapi principal, promo, kategori, dan pilih minimal satu faktur promo.';
    feedback.value = '';
    return;
  }

  submitting.value = true;
  error.value = '';
  feedback.value = '';

  try {
    await createPromoClaim({
      kode_voucher: form.kode_voucher,
      claim_source: form.claim_source,
      id_unified_promo: form.id_unified_promo ? Number(form.id_unified_promo) : null,
      id_principal: Number(form.id_principal),
      nomor_klaim: form.nomor_klaim,
      id_kategori_klaim: Number(form.id_kategori_klaim),
      tanggal_pengajuan_klaim: form.tanggal_pengajuan_klaim,
      total_dpp: form.total_dpp,
      total_ppn: form.total_ppn,
      total_pph: form.total_pph,
      total_klaim_diajukan: form.total_klaim_diajukan,
      id_user_adm_klaim: auth.user?.id || auth.user?.id_user || auth.user?.user_id || null,
      id_draft_voucher: form.claim_source === 'unified_promo' ? [] : selectedInvoiceIds.value.map((item) => Number(item)),
      id_unified_promo_usage: form.claim_source === 'unified_promo' ? selectedInvoiceIds.value.map((item) => Number(item)) : [],
      status_klaim: form.status_klaim ? 1 : 0,
      dpp: form.total_dpp,
      ppn: form.total_ppn,
      pph: form.total_pph
    });

    feedback.value = `Klaim promo ${form.nomor_klaim} berhasil diajukan.`;
    resetForm();
  } catch (err) {
    error.value = normalizeError(err, 'Klaim promo belum berhasil diajukan.');
  } finally {
    submitting.value = false;
  }
}

watch(
  () => form.id_principal,
  async () => {
    form.promo_key = '';
    form.kode_voucher = '';
    form.claim_source = 'legacy_voucher';
    form.id_unified_promo = '';
    invoiceRows.value = [];
    selectedInvoiceIds.value = [];
    syncTotalsToForm();
    await generateClaimCodeIfNeeded();
  }
);

watch(
  () => form.promo_key,
  async () => {
    const promo = selectedPromo.value;
    form.kode_voucher = promo?.kode_promo || '';
    form.claim_source = promo?.claim_source || 'legacy_voucher';
    form.id_unified_promo = promo?.id_unified_promo ? String(promo.id_unified_promo) : '';
    await loadInvoices();
  }
);

onMounted(async () => {
  try {
    await loadReferences();
  } catch (err) {
    error.value = normalizeError(err, 'Referensi promo klaim belum bisa dimuat.');
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Ajukan Klaim Promo"
      description="Pilih promo yang sudah dipakai, termasuk Promo All-In, lalu ajukan faktur yang belum pernah masuk klaim."
    >
      <div class="flex flex-wrap gap-3">
        <button class="rounded-xl border border-brand-200 px-4 py-2 text-sm text-brand-700 hover:bg-brand-50" @click="router.push('/promo/claims')">
          Lihat Klaim Saya
        </button>
        <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50" @click="resetForm">
          Reset Form
        </button>
        <button
          class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60"
          :disabled="submitting"
          @click="submitClaim"
        >
          {{ submitting ? 'Mengajukan...' : 'Ajukan Klaim' }}
        </button>
      </div>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
      {{ error }}
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
      {{ feedback }}
    </section>

    <div class="grid gap-6 xl:grid-cols-[1fr_0.95fr]">
      <section class="panel p-6">
        <div class="mb-4">
          <h3 class="text-xl font-bold text-slate-950">Form Klaim Promo</h3>
          <p class="mt-1 text-sm text-slate-500">Nomor klaim saya buat otomatis berdasarkan principal agar konsisten dengan format backend lama.</p>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_principal" label="Principal" placeholder="Pilih principal" :options="principalOptions" />
          <AppSearchSelect v-model="form.promo_key" label="Kode Promo" placeholder="Pilih kode promo" :options="promoOptions" />
          <AppFormField v-model="form.nomor_klaim" label="Nomor Klaim" :readonly="true" placeholder="Otomatis dari principal" />
          <AppSearchSelect v-model="form.id_kategori_klaim" label="Kategori Klaim" placeholder="Pilih kategori klaim" :options="categoryOptions" />
          <AppFormField v-model="form.tanggal_pengajuan_klaim" label="Tanggal Pengajuan" type="date" />
          <AppFormField :model-value="loadingCode ? 'Membuat kode...' : (selectedPromo?.nama_promo || '-')" label="Nama Promo" :readonly="true" />
          <AppFormField :model-value="Number(form.total_dpp || 0).toLocaleString('id-ID')" label="Total DPP" :readonly="true" />
          <AppFormField :model-value="Number(form.total_ppn || 0).toLocaleString('id-ID')" label="Total PPN" :readonly="true" />
          <AppFormField :model-value="Number(form.total_pph || 0).toLocaleString('id-ID')" label="Total PPH" :readonly="true" />
          <AppFormField :model-value="Number(form.total_klaim_diajukan || 0).toLocaleString('id-ID')" label="Total Klaim" :readonly="true" />
        </div>
      </section>

      <section class="panel p-6">
        <div class="mb-4">
          <h3 class="text-xl font-bold text-slate-950">Ringkasan Pengajuan</h3>
          <p class="mt-1 text-sm text-slate-500">Saya tampilkan konteks utama sebelum klaim benar-benar diajukan.</p>
        </div>

        <div class="space-y-3">
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Principal</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedPrincipal?.nama || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Promo</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedPromo?.nama_promo || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Nomor Klaim</p>
            <p class="mt-2 font-semibold text-slate-900">{{ form.nomor_klaim || '-' }}</p>
          </article>
          <article class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-xs uppercase tracking-wide text-slate-400">Faktur Dipilih</p>
            <p class="mt-2 font-semibold text-slate-900">{{ selectedInvoiceIds.length.toLocaleString('id-ID') }} faktur promo</p>
          </article>
        </div>
      </section>
    </div>

    <section class="panel p-6">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="text-xl font-bold text-slate-950">Faktur Promo yang Bisa Diklaim</h3>
          <p class="mt-1 text-sm text-slate-500">Checklist faktur promo yang ingin dimasukkan ke klaim. Nilai klaim akan terakumulasi otomatis.</p>
        </div>
        <div class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
          {{ selectedInvoiceIds.length }} Terpilih
        </div>
      </div>

      <div v-if="loadingInvoices" class="py-10 text-center text-sm text-slate-500">
        Memuat daftar faktur promo...
      </div>

      <div v-else-if="invoiceRows.length" class="overflow-x-auto rounded-2xl border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.2em] text-slate-500">
            <tr>
              <th class="px-4 py-3">Pilih</th>
              <th class="px-4 py-3">No Faktur</th>
              <th class="px-4 py-3">Customer</th>
              <th class="px-4 py-3">Sumber</th>
              <th class="px-4 py-3">Estimasi Klaim</th>
              <th class="px-4 py-3">DPP</th>
              <th class="px-4 py-3">PPN</th>
              <th class="px-4 py-3">Status Promo</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-for="row in invoiceRows" :key="row.id" :class="selectedInvoiceIds.includes(String(row.id)) ? 'bg-brand-50/60' : ''">
              <td class="px-4 py-3">
                <input
                  :checked="selectedInvoiceIds.includes(String(row.id))"
                  type="checkbox"
                  class="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                  @change="toggleInvoice(row)"
                >
              </td>
              <td class="px-4 py-3">{{ row.no_faktur || '-' }}</td>
              <td class="px-4 py-3">{{ row.customer || '-' }}</td>
              <td class="px-4 py-3">{{ row.claim_source === 'unified_promo' ? 'Promo All-In' : 'Voucher' }}</td>
              <td class="px-4 py-3">Rp {{ Number(row.estimasi_klaim || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">Rp {{ Number(row.calculated_dpp || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">Rp {{ Number(row.calculated_ppn_value || 0).toLocaleString('id-ID') }}</td>
              <td class="px-4 py-3">{{ row.status_promo || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <AppEmptyState
        v-else
        title="Belum ada faktur promo"
        description="Promo yang tampil sudah disaring dari pemakaian yang siap diklaim. Jika kosong, faktur belum terpakai atau sudah pernah masuk klaim."
      />
    </section>
  </div>
</template>
