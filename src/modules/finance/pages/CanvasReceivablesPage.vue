<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  finalizeCanvasFinancePayment,
  getBankMutations,
  getCanvasFinanceReceivables,
  getCanvasPaymentRecapCandidates,
  recordCanvasFinancePayment,
  retryCanvasFinanceJournal,
  submitCanvasPaymentRecap
} from '@/api/finance';
import { getBranches, getCompanies } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const numberFormatter = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 });

const filters = reactive({
  id_perusahaan: String(route.query.id_perusahaan || ''),
  id_cabang: String(route.query.id_cabang || ''),
  status: '',
  search: ''
});
const companyRows = ref([]);
const branchRows = ref([]);
const candidates = ref([]);
const receivables = ref([]);
const selectedCandidateIds = ref([]);
const selectedPayment = ref(null);
const mutationRows = ref([]);
const recordOpen = ref(false);
const feedback = ref('');
const errorMessage = ref('');
const loading = reactive({
  masters: false,
  data: false,
  recap: false,
  mutations: false,
  record: false,
  retryJournalId: '',
  finalizeId: ''
});
const recordForm = reactive({
  receipt_reference: '',
  received_by_name: '',
  receipt_note: '',
  id_mutasi: ''
});

const companyOptions = computed(() => getCompanyOptionsForScope(companyRows.value, auth, true));
const branchOptions = computed(() =>
  getBranchOptionsForCompany(branchRows.value, auth, filters.id_perusahaan, true, companyRows.value)
);
const selectedCandidates = computed(() => candidates.value.filter((row) =>
  selectedCandidateIds.value.includes(String(row.id_setoran_customer || row.id || ''))
));
const selectedCandidateTotal = computed(() => selectedCandidates.value.reduce(
  (total, row) => total + Number(row.nominal_claim ?? row.jumlah_setoran ?? 0), 0
));
const selectedPaymentMethod = computed(() => Number(selectedPayment.value?.tipe_pembayaran || 0));
const selectedPaymentIsNonCash = computed(() => selectedPaymentMethod.value === 2);
const mutationOptions = computed(() => [
  { value: '', label: 'Pilih mutasi CR yang sudah diterima' },
  ...mutationRows.value
    .filter((row) => Number(row.tipe || 0) === 1 && Number(row.status_mutasi ?? 1) === 1)
    .map((row) => ({
      value: String(row.id_mutasi || row.id || ''),
      label: `${row.kode_mutasi || `Mutasi #${row.id_mutasi || row.id}`} · ${formatCurrency(row.sisa ?? row.nominal_mutasi)} · ${formatDate(row.tanggal_mutasi)}`
    }))
    .filter((row) => row.value)
]);

function formatCurrency(value) {
  return `Rp ${numberFormatter.format(Number(value || 0))}`;
}

function formatDate(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(parsed);
}

function rowId(row) {
  return String(row?.id_setoran_customer || row?.id || '');
}

function paymentId(payment) {
  return payment?.id || payment?.id_canvas_payment || null;
}

function statusClass(status) {
  const value = String(status || '').toUpperCase();
  if (value === 'FINALIZED') return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-200';
  if (value === 'RECORDED' || value === 'PARTIAL') return 'bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-200';
  if (value === 'REKAPPED') return 'bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-200';
  if (value === 'VOID') return 'bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-200';
  return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200';
}

function statusLabel(row) {
  return row?.status_label || {
    OPEN: 'Menunggu Rekap',
    REKAPPED: 'Menunggu Penerimaan',
    RECORDED: 'Penerimaan Tercatat',
    PARTIAL: 'Dibayar Sebagian',
    FINALIZED: 'Final',
    VOID: 'Dibatalkan'
  }[String(row?.status || '').toUpperCase()] || '-';
}

function methodLabel(value) {
  return Number(value) === 2 ? 'Non Tunai / Transfer' : 'Tunai';
}

function requestParams() {
  return {
    id_perusahaan: filters.id_perusahaan || undefined,
    id_cabang: filters.id_cabang || undefined,
    status: filters.status || undefined,
    search: String(filters.search || '').trim() || undefined
  };
}

async function loadMasters() {
  loading.masters = true;
  try {
    const [companies, branches] = await Promise.all([
      getCompanies(),
      getBranches()
    ]);
    companyRows.value = normalizeList(unwrapResponse(companies));
    branchRows.value = normalizeList(unwrapResponse(branches));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Master perusahaan/cabang Canvas belum dapat dimuat.');
  } finally {
    loading.masters = false;
  }
}

async function loadData() {
  loading.data = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    const params = requestParams();
    const [candidateResponse, receivableResponse] = await Promise.all([
      getCanvasPaymentRecapCandidates(params),
      getCanvasFinanceReceivables(params)
    ]);
    candidates.value = normalizeList(unwrapResponse(candidateResponse));
    receivables.value = normalizeList(unwrapResponse(receivableResponse));
    const validIds = new Set(candidates.value.map(rowId));
    selectedCandidateIds.value = selectedCandidateIds.value.filter((id) => validIds.has(id));
  } catch (error) {
    candidates.value = [];
    receivables.value = [];
    selectedCandidateIds.value = [];
    errorMessage.value = normalizeError(error, 'Antrean piutang Canvas Finance belum dapat dimuat.');
  } finally {
    loading.data = false;
  }
}

function toggleCandidate(row, checked) {
  const id = rowId(row);
  if (!id) return;
  if (checked) {
    selectedCandidateIds.value = [...new Set([...selectedCandidateIds.value, id])];
  } else {
    selectedCandidateIds.value = selectedCandidateIds.value.filter((value) => value !== id);
  }
}

async function submitRecap() {
  if (!selectedCandidates.value.length) {
    errorMessage.value = 'Pilih minimal satu claim Canvas untuk direkap.';
    return;
  }
  loading.recap = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    await submitCanvasPaymentRecap({
      data: selectedCandidates.value.map((row) => {
        const amount = Number(row.nominal_claim ?? row.jumlah_setoran ?? 0);
        const method = Number(row.tipe_pembayaran ?? row.tipe_setoran ?? 0);
        return {
          id: Number(row.id_setoran_customer || row.id),
          tunai: method === 1 ? amount : 0,
          non_tunai: method === 2 ? amount : 0
        };
      })
    });
    feedback.value = 'Claim Canvas masuk ke antrean penerimaan Finance. Belum ada faktur Sales Order atau finalisasi yang diubah.';
    selectedCandidateIds.value = [];
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Claim Canvas belum dapat direkap.');
  } finally {
    loading.recap = false;
  }
}

async function openRecord(payment) {
  selectedPayment.value = payment;
  recordForm.receipt_reference = String(payment.receipt_reference || '');
  recordForm.received_by_name = '';
  recordForm.receipt_note = String(payment.receipt_note || '');
  recordForm.id_mutasi = '';
  mutationRows.value = [];
  recordOpen.value = true;
  if (!selectedPaymentIsNonCash.value) return;
  loading.mutations = true;
  try {
    const response = await getBankMutations({
      id_perusahaan: payment.id_perusahaan || undefined,
      id_cabang: payment.id_cabang || undefined,
      tipe: 1
    });
    mutationRows.value = normalizeList(unwrapResponse(response));
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Mutasi CR belum dapat dimuat. Catat atau import mutasi terlebih dahulu bila belum tersedia.');
  } finally {
    loading.mutations = false;
  }
}

async function recordPayment() {
  const id = paymentId(selectedPayment.value);
  if (!id) return;
  if (!String(recordForm.received_by_name || '').trim()) {
    errorMessage.value = 'Nama petugas penerima/verifikator wajib diisi.';
    return;
  }
  if (selectedPaymentIsNonCash.value && !recordForm.id_mutasi) {
    errorMessage.value = 'Pilih mutasi CR yang benar sebelum mencatat pembayaran non tunai Canvas.';
    return;
  }
  if (!selectedPaymentIsNonCash.value && !String(recordForm.receipt_reference || '').trim()) {
    errorMessage.value = 'Nomor kuitansi atau referensi setoran tunai wajib diisi.';
    return;
  }
  loading.record = true;
  errorMessage.value = '';
  feedback.value = '';
  try {
    await recordCanvasFinancePayment(id, {
      receipt_reference: String(recordForm.receipt_reference || '').trim() || undefined,
      received_by_name: String(recordForm.received_by_name || '').trim(),
      receipt_note: String(recordForm.receipt_note || '').trim() || undefined,
      id_mutasi: selectedPaymentIsNonCash.value ? Number(recordForm.id_mutasi) : undefined
    });
    recordOpen.value = false;
    feedback.value = 'Bukti penerimaan Canvas tercatat. Finalisasi baru tersedia bila seluruh claim pada order ini sudah tercatat dan totalnya tepat.';
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Bukti penerimaan Canvas belum dapat dicatat.');
  } finally {
    loading.record = false;
  }
}

async function finalizeReceivable(receivable) {
  const triggerPayment = (receivable.payments || []).find((payment) => paymentId(payment));
  const id = paymentId(triggerPayment);
  if (!id) return;
  if (!window.confirm(`Finalisasi penerimaan Canvas ${receivable.no_canvas_order || receivable.id_canvas_order || ''}? Semua claim harus sudah tercatat dan total harus sama persis.`)) return;
  loading.finalizeId = String(receivable.id_receivable || receivable.id);
  errorMessage.value = '';
  feedback.value = '';
  try {
    await finalizeCanvasFinancePayment(id);
    feedback.value = 'Piutang Canvas berhasil difinalisasi. Status Canvas Order diperbarui hanya setelah seluruh bukti penerimaan cocok.';
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Piutang Canvas belum dapat difinalisasi.');
  } finally {
    loading.finalizeId = '';
  }
}

async function retryJournal(payment) {
  const id = paymentId(payment);
  if (!id) return;
  loading.retryJournalId = String(id);
  errorMessage.value = '';
  feedback.value = '';
  try {
    await retryCanvasFinanceJournal(id);
    feedback.value = 'Pengiriman jurnal Canvas dicoba ulang. Finalisasi hanya aktif setelah status jurnal berhasil terkirim.';
    await loadData();
  } catch (error) {
    errorMessage.value = normalizeError(error, 'Jurnal Canvas belum dapat dikirim ulang.');
  } finally {
    loading.retryJournalId = '';
  }
}

function openBankMutations() {
  router.push({
    name: 'finance-bank-mutations',
    query: {
      id_perusahaan: selectedPayment.value?.id_perusahaan || undefined,
      id_cabang: selectedPayment.value?.id_cabang || undefined
    }
  });
}

watch(() => filters.id_perusahaan, () => {
  filters.id_cabang = '';
});

onMounted(async () => {
  await Promise.all([loadMasters(), loadData()]);
});
</script>

<template>
  <section class="space-y-6">
    <PageHeader
      title="Piutang Canvas Finance"
      description="Jalur Finance terpisah untuk Canvas: claim Sales → Rekap Canvas → bukti penerimaan tunai/CR → finalisasi. Tidak memakai LPH, Sales Order, atau faktur sintetis."
    >
      <template #actions>
        <button class="button-secondary" :disabled="loading.data" @click="loadData">
          {{ loading.data ? 'Memuat...' : 'Muat Ulang' }}
        </button>
      </template>
    </PageHeader>

    <section class="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-950 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100">
      <p class="font-semibold">Kontrol Finance Canvas</p>
      <p class="mt-1">Claim dari Mobile Sales tidak otomatis melunasi order. Rekap hanya membuat antrean Finance; tunai memerlukan kuitansi/penerima, sedangkan non tunai wajib memakai mutasi CR pada perusahaan dan cabang yang sama. Finalisasi ditahan sampai seluruh claim, bukti penerimaan, dan jurnal Finance sudah cocok.</p>
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-4">
        <AppSearchSelect
          :model-value="filters.id_perusahaan"
          label="Perusahaan"
          placeholder="Semua perusahaan"
          :options="companyOptions"
          :loading="loading.masters"
          @update:model-value="filters.id_perusahaan = String($event || '')"
        />
        <AppSearchSelect
          :model-value="filters.id_cabang"
          label="Cabang"
          placeholder="Semua cabang"
          :options="branchOptions"
          :disabled="loading.masters"
          @update:model-value="filters.id_cabang = String($event || '')"
        />
        <label class="block">
          <span class="field-label">Status piutang</span>
          <select v-model="filters.status" class="field-control">
            <option value="">Semua status</option>
            <option value="OPEN">Menunggu Rekap</option>
            <option value="REKAPPED">Menunggu Penerimaan</option>
            <option value="PARTIAL">Dibayar Sebagian</option>
            <option value="FINALIZED">Final</option>
          </select>
        </label>
        <label class="block">
          <span class="field-label">Cari</span>
          <input v-model="filters.search" class="field-control" placeholder="Order Canvas, customer, atau kode" @keyup.enter="loadData" />
        </label>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button class="button-primary" :disabled="loading.data" @click="loadData">Terapkan Filter</button>
        <button class="button-secondary" @click="Object.assign(filters, { id_perusahaan: '', id_cabang: '', status: '', search: '' }); loadData()">Reset</button>
      </div>
    </section>

    <p v-if="errorMessage" class="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ errorMessage }}</p>
    <p v-if="feedback" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">{{ feedback }}</p>

    <section class="panel overflow-hidden">
      <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <div>
          <p class="section-eyebrow">01 · Rekap Canvas</p>
          <h2 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">Claim Mobile Sales menunggu Rekap</h2>
          <p class="mt-1 text-sm text-slate-500">Nominal dan metode dikunci dari claim Sales. Rekap tidak boleh mengubah atau memecahnya.</p>
        </div>
        <div class="text-right">
          <p class="text-sm text-slate-500">{{ selectedCandidateIds.length }} claim dipilih</p>
          <p class="font-bold text-slate-950 dark:text-white">{{ formatCurrency(selectedCandidateTotal) }}</p>
        </div>
      </div>
      <div class="overflow-x-auto">
        <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
          <thead class="bg-slate-50 text-left text-slate-600 dark:bg-slate-900 dark:text-slate-300">
            <tr>
              <th class="w-12 px-4 py-3 text-center">Pilih</th>
              <th class="px-4 py-3">Order Canvas</th>
              <th class="px-4 py-3">Customer</th>
              <th class="px-4 py-3">Sales</th>
              <th class="px-4 py-3">Metode</th>
              <th class="px-4 py-3 text-right">Claim</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-950">
            <tr v-if="loading.data"><td colspan="6" class="px-4 py-8 text-center text-slate-500">Memuat antrean claim Canvas...</td></tr>
            <tr v-else-if="!candidates.length"><td colspan="6" class="px-4 py-8 text-center text-slate-500">Tidak ada claim Canvas yang menunggu Rekap pada filter ini.</td></tr>
            <tr v-for="row in candidates" v-else :key="rowId(row)" class="text-slate-700 dark:text-slate-200">
              <td class="px-4 py-3 text-center"><input type="checkbox" :checked="selectedCandidateIds.includes(rowId(row))" @change="toggleCandidate(row, $event.target.checked)" /></td>
              <td class="px-4 py-3"><p class="font-semibold">{{ row.no_canvas_order || row.kode_order || `CANVAS-${row.id_canvas_order || '-'}` }}</p><p class="mt-1 text-xs text-slate-500">Claim #{{ row.id_setoran_customer || row.id }}</p></td>
              <td class="px-4 py-3">{{ row.nama_customer || row.nama_customer_snapshot || '-' }}</td>
              <td class="px-4 py-3">{{ row.nama_sales || '-' }}</td>
              <td class="px-4 py-3">{{ row.metode_label || methodLabel(row.tipe_pembayaran ?? row.tipe_setoran) }}</td>
              <td class="px-4 py-3 text-right font-semibold">{{ formatCurrency(row.nominal_claim ?? row.jumlah_setoran) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="flex justify-end border-t border-slate-200 px-5 py-4 dark:border-slate-800">
        <button class="button-primary" :disabled="loading.recap || !selectedCandidateIds.length" @click="submitRecap">
          {{ loading.recap ? 'Merekap...' : 'Rekap Claim Terpilih' }}
        </button>
      </div>
    </section>

    <section class="panel overflow-hidden">
      <div class="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
        <p class="section-eyebrow">02 · Penerimaan & Finalisasi</p>
        <h2 class="mt-1 text-lg font-bold text-slate-950 dark:text-white">Piutang Canvas yang sudah direkap</h2>
        <p class="mt-1 text-sm text-slate-500">Finalisasi dilakukan per Canvas Order, hanya jika seluruh claim tercatat dan nominalnya sama persis dengan tagihan order.</p>
      </div>
      <div class="space-y-4 p-5">
        <div v-if="loading.data" class="py-8 text-center text-sm text-slate-500">Memuat piutang Canvas...</div>
        <div v-else-if="!receivables.length" class="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700">Belum ada piutang Canvas Finance pada filter ini.</div>
        <article v-for="row in receivables" v-else :key="row.id_receivable || row.id" class="overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
          <div class="flex flex-wrap items-start justify-between gap-4 bg-slate-50 px-4 py-4 dark:bg-slate-900">
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="font-bold text-slate-950 dark:text-white">{{ row.no_canvas_order || `CANVAS-${row.id_canvas_order}` }}</h3>
                <span class="rounded-full px-2.5 py-1 text-xs font-bold" :class="statusClass(row.status)">{{ statusLabel(row) }}</span>
              </div>
              <p class="mt-1 text-sm text-slate-600 dark:text-slate-300">{{ row.nama_customer_snapshot || row.nama_customer || '-' }} · {{ row.nama_sales || 'Sales -' }}</p>
            </div>
            <div class="grid grid-cols-2 gap-x-5 gap-y-1 text-right text-sm sm:grid-cols-4">
              <div><p class="text-slate-500">Tagihan</p><p class="font-bold">{{ formatCurrency(row.nominal_tagihan) }}</p></div>
              <div><p class="text-slate-500">Claim</p><p class="font-bold">{{ formatCurrency(row.total_claim) }}</p></div>
              <div><p class="text-slate-500">Tercatat</p><p class="font-bold">{{ formatCurrency(row.total_recorded) }}</p></div>
              <div><p class="text-slate-500">Sisa</p><p class="font-bold">{{ formatCurrency(row.sisa_tagihan) }}</p></div>
            </div>
          </div>
          <div class="overflow-x-auto">
            <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead class="bg-white text-left text-slate-500 dark:bg-slate-950"><tr><th class="px-4 py-2">Claim</th><th class="px-4 py-2">Metode</th><th class="px-4 py-2">Bukti</th><th class="px-4 py-2">Status</th><th class="px-4 py-2 text-right">Nominal</th><th class="px-4 py-2 text-right">Aksi</th></tr></thead>
              <tbody class="divide-y divide-slate-100 dark:divide-slate-800">
                <tr v-for="payment in row.payments || []" :key="paymentId(payment)" class="text-slate-700 dark:text-slate-200">
                  <td class="px-4 py-3">#{{ payment.id_setoran_customer || '-' }}</td>
                  <td class="px-4 py-3">{{ payment.metode_label || methodLabel(payment.tipe_pembayaran) }}</td>
                  <td class="px-4 py-3">{{ payment.receipt_reference || payment.kode_mutasi || '-' }}</td>
                  <td class="px-4 py-3"><span class="rounded-full px-2 py-1 text-xs font-semibold" :class="statusClass(payment.status)">{{ statusLabel(payment) }}</span><p v-if="String(payment.status || '').toUpperCase() !== 'REKAPPED'" class="mt-1 text-xs" :class="String(payment.journal_outbox_status || '').toUpperCase() === 'DELIVERED' ? 'text-emerald-600 dark:text-emerald-300' : 'text-amber-600 dark:text-amber-300'">Jurnal: {{ String(payment.journal_outbox_status || 'PENDING').toUpperCase() === 'DELIVERED' ? 'terkirim' : 'menunggu mapping/kirim' }}</p><p v-if="payment.journal_outbox_error" class="mt-1 max-w-72 text-xs text-rose-600 dark:text-rose-300">{{ payment.journal_outbox_error }}</p></td>
                  <td class="px-4 py-3 text-right font-semibold">{{ formatCurrency(payment.nominal_claim) }}</td>
                  <td class="px-4 py-3 text-right"><button v-if="String(payment.status || '').toUpperCase() === 'REKAPPED'" class="button-secondary text-xs" @click="openRecord(payment)">Catat Bukti</button><button v-else-if="String(payment.journal_outbox_status || '').toUpperCase() !== 'DELIVERED'" class="button-secondary text-xs" :disabled="loading.retryJournalId === String(paymentId(payment))" @click="retryJournal(payment)">{{ loading.retryJournalId === String(paymentId(payment)) ? 'Mengirim...' : 'Ulang Jurnal' }}</button><span v-else class="text-xs text-emerald-600 dark:text-emerald-300">Siap final</span></td>
                </tr>
                <tr v-if="!(row.payments || []).length"><td colspan="6" class="px-4 py-4 text-center text-slate-500">Belum ada claim yang direkap.</td></tr>
              </tbody>
            </table>
          </div>
          <div class="flex justify-end border-t border-slate-200 px-4 py-3 dark:border-slate-800">
            <button class="button-primary" :disabled="!row.can_finalize || loading.finalizeId === String(row.id_receivable || row.id)" @click="finalizeReceivable(row)">
              {{ loading.finalizeId === String(row.id_receivable || row.id) ? 'Memfinalisasi...' : 'Finalisasi Piutang Canvas' }}
            </button>
          </div>
        </article>
      </div>
    </section>

    <AppModal
      :open="recordOpen"
      title="Catat Penerimaan Canvas"
      :description="selectedPaymentIsNonCash ? 'Pilih mutasi CR yang benar. Mutasi harus satu perusahaan dan cabang dengan Canvas Order.' : 'Simpan nomor kuitansi dan nama penerima kas sebelum claim dapat ikut difinalisasi.'"
      size="xl"
      @close="recordOpen = false"
    >
      <div class="space-y-4">
        <div class="grid gap-3 rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-800/70 sm:grid-cols-3">
          <div><p class="text-slate-500">Claim</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ formatCurrency(selectedPayment?.nominal_claim) }}</p></div>
          <div><p class="text-slate-500">Metode</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedPayment?.metode_label || methodLabel(selectedPayment?.tipe_pembayaran) }}</p></div>
          <div><p class="text-slate-500">Order</p><p class="mt-1 font-bold text-slate-950 dark:text-white">{{ selectedPayment?.no_canvas_order || `CANVAS-${selectedPayment?.id_canvas_order || '-'}` }}</p></div>
        </div>
        <label class="block">
          <span class="field-label">Nama petugas penerima / verifikator</span>
          <input v-model="recordForm.received_by_name" class="field-control" placeholder="Wajib diisi untuk audit" />
        </label>
        <AppSearchSelect
          v-if="selectedPaymentIsNonCash"
          :model-value="recordForm.id_mutasi"
          label="Mutasi CR"
          placeholder="Pilih mutasi dana masuk"
          :options="mutationOptions"
          :loading="loading.mutations"
          empty-text="Belum ada mutasi CR yang tersedia. Catat/import mutasi melalui menu Mutasi Bank terlebih dahulu."
          @update:model-value="recordForm.id_mutasi = String($event || '')"
        />
        <label v-else class="block">
          <span class="field-label">Nomor kuitansi / referensi setoran tunai</span>
          <input v-model="recordForm.receipt_reference" class="field-control" placeholder="Wajib diisi" />
        </label>
        <label class="block">
          <span class="field-label">Catatan bukti <span class="font-normal text-slate-400">(opsional)</span></span>
          <textarea v-model="recordForm.receipt_note" class="field-control min-h-24" placeholder="Keterangan penerimaan atau referensi pendukung." />
        </label>
        <button v-if="selectedPaymentIsNonCash" class="button-secondary" @click="openBankMutations">Buka Mutasi Bank</button>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2"><button class="button-secondary" @click="recordOpen = false">Batal</button><button class="button-primary" :disabled="loading.record" @click="recordPayment">{{ loading.record ? 'Menyimpan...' : 'Catat Penerimaan' }}</button></div>
      </template>
    </AppModal>
  </section>
</template>
