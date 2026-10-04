<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { getBranches, getCompanies } from '@/api/master';
import { getEmployeeAdvances, getEmployeeAdvance, getEmployeeAdvanceEmployees, createEmployeeAdvance, decideEmployeeAdvance } from '@/api/finance';
import { useAuthStore } from '@/stores/auth';
import { normalizeList, normalizeError, unwrapResponse } from '@/utils/api';
import { getLoginBranchId, getLoginCompanyId, isSuperUser } from '@/utils/accessScope';
import { getBranchOptionsForCompany } from '@/utils/filterScope';
import { toLocalDateInputValue, firstLocalDayOfMonth } from '@/utils/date';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppTable from '@/shared/components/AppTable.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();
const canCreate = computed(() => auth.hasPermission('finance.employee-advances.create'));
const canApprove = computed(() => auth.hasPermission('finance.employee-advances.approve'));
const companyRows = ref([]), branchRows = ref([]), employees = ref([]), rows = ref([]);
const filters = reactive({ company: '', branch: '', status: '', from: toLocalDateInputValue(firstLocalDayOfMonth(new Date())), to: toLocalDateInputValue(), page: 1 });
const total = ref(0), limit = 25;
const loading = reactive({ list: false, save: false, detail: false, decision: false, employees: false });
const pageError = ref(''), formError = ref(''), detailError = ref(''), feedback = ref('');
const createOpen = ref(false), detailOpen = ref(false), detail = ref(null);
const decisionNote = ref('');
const form = reactive({ id_perusahaan: '', id_cabang: '', id_karyawan: '', tanggal_pengajuan: '', tanggal_jatuh_tempo: '', nominal: '', keperluan: '', client_request_id: '' });
let listSequence = 0, detailSequence = 0, employeeSequence = 0;
const companies = computed(() => companyRows.value.map(row => ({ value: String(row.id), label: `${row.kode || ''} - ${row.nama}` })));
const filterBranches = computed(() => getBranchOptionsForCompany(branchRows.value, auth, filters.company, false, companyRows.value));
const formBranches = computed(() => getBranchOptionsForCompany(branchRows.value, auth, form.id_perusahaan, false, companyRows.value));
const employeeOptions = computed(() => employees.value.map(row => ({ value: String(row.id), label: `${row.nama}${row.nama_jabatan ? ` — ${row.nama_jabatan}` : ''}` })));
const states = { PENDING: 'Menunggu approval', APPROVED: 'Disetujui', REJECTED: 'Ditolak' };
const statusOptions = Object.entries(states).map(([value, label]) => ({ value, label }));
const money = value => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 2 }).format(Number(value || 0));
const date = value => value ? new Date(value).toLocaleDateString('id-ID') : '-';
const canDecide = computed(() => canApprove.value && detail.value?.status === 'PENDING' && ![detail.value?.created_by, detail.value?.id_karyawan].map(String).includes(String(auth.user?.id_user || auth.user?.id)));
const columns = [
  { key: 'nomor', label: 'No. Kasbon' }, { key: 'tanggal_pengajuan', label: 'Tanggal', render: row => date(row.tanggal_pengajuan) },
  { key: 'nama_karyawan', label: 'Karyawan' }, { key: 'nama_perusahaan', label: 'Perusahaan' }, { key: 'nama_cabang', label: 'Cabang' },
  { key: 'nominal', label: 'Nominal', render: row => money(row.nominal) },
  { key: 'status', label: 'Status', render: row => states[row.status] || row.status }, { key: 'nama_pengaju', label: 'Diajukan oleh' }
];

async function loadRows(page = 1) {
  const sequence = ++listSequence;
  loading.list = true; pageError.value = ''; filters.page = page;
  try {
    const response = await getEmployeeAdvances({ id_perusahaan: filters.company || undefined, id_cabang: filters.branch || undefined, status: filters.status || undefined, periode_awal: filters.from || undefined, periode_akhir: filters.to || undefined, page, limit });
    if (sequence !== listSequence) return;
    rows.value = normalizeList(response.data); total.value = Number(response.data?.total || 0);
  } catch (error) { if (sequence === listSequence) { rows.value = []; total.value = 0; pageError.value = normalizeError(error); } }
  finally { if (sequence === listSequence) loading.list = false; }
}

function openCreate() {
  formError.value = ''; feedback.value = '';
  Object.assign(form, { id_perusahaan: filters.company || getLoginCompanyId(auth.user), id_cabang: filters.branch || getLoginBranchId(auth.user), id_karyawan: '', tanggal_pengajuan: toLocalDateInputValue(), tanggal_jatuh_tempo: '', nominal: '', keperluan: '', client_request_id: crypto.randomUUID() });
  createOpen.value = true;
  loadEmployees();
}

async function loadEmployees() {
  const sequence = ++employeeSequence;
  employees.value = []; form.id_karyawan = ''; loading.employees = false;
  if (!form.id_perusahaan || !form.id_cabang) return;
  loading.employees = true;
  try {
    const response = await getEmployeeAdvanceEmployees({ id_perusahaan: form.id_perusahaan, id_cabang: form.id_cabang });
    if (sequence === employeeSequence) employees.value = normalizeList(unwrapResponse(response));
  } catch (error) { if (sequence === employeeSequence) formError.value = normalizeError(error, 'Daftar karyawan belum dapat dimuat.'); }
  finally { if (sequence === employeeSequence) loading.employees = false; }
}

async function submit() {
  if (loading.save) return;
  formError.value = '';
  if (!form.id_perusahaan || !form.id_cabang || !form.id_karyawan || !form.tanggal_pengajuan || !form.keperluan.trim() || !Number.isFinite(Number(form.nominal)) || Number(form.nominal) <= 0) { formError.value = 'Lengkapi perusahaan, cabang, karyawan, tanggal, nominal positif, dan keperluan.'; return; }
  if (form.tanggal_jatuh_tempo && form.tanggal_jatuh_tempo < form.tanggal_pengajuan) { formError.value = 'Jatuh tempo tidak boleh sebelum tanggal pengajuan.'; return; }
  loading.save = true;
  try {
    const response = await createEmployeeAdvance({ ...form, nominal: String(form.nominal), keperluan: form.keperluan.trim() });
    createOpen.value = false; feedback.value = response.data?.message || 'Pengajuan sudah tersimpan.';
    filters.company = String(form.id_perusahaan); filters.branch = String(form.id_cabang);
    filters.status = ''; filters.from = form.tanggal_pengajuan; filters.to = form.tanggal_pengajuan;
    await loadRows();
  } catch (error) { formError.value = normalizeError(error); }
  finally { loading.save = false; }
}

async function openDetail(row) {
  const sequence = ++detailSequence;
  detailOpen.value = true; detail.value = null; decisionNote.value = ''; detailError.value = ''; loading.detail = true;
  try { const response = await getEmployeeAdvance(row.id); if (sequence === detailSequence) detail.value = unwrapResponse(response); }
  catch (error) { if (sequence === detailSequence) detailError.value = normalizeError(error); }
  finally { if (sequence === detailSequence) loading.detail = false; }
}

async function decide(decision) {
  if (!canDecide.value || loading.decision) return;
  detailError.value = '';
  if (decision === 'REJECTED' && !decisionNote.value.trim()) { detailError.value = 'Alasan penolakan wajib diisi.'; return; }
  if (!window.confirm(`${decision === 'APPROVED' ? 'Setujui' : 'Tolak'} kasbon ${detail.value.nomor} sebesar ${money(detail.value.nominal)}?`)) return;
  loading.decision = true;
  try {
    const response = await decideEmployeeAdvance(detail.value.id, { decision, catatan: decisionNote.value.trim() });
    feedback.value = response.data?.message || 'Keputusan tersimpan.';
    await openDetail(detail.value); await loadRows(filters.page);
  } catch (error) { detailError.value = normalizeError(error); }
  finally { loading.decision = false; }
}

watch(() => form.id_perusahaan, () => { if (!formBranches.value.some(row => row.value === String(form.id_cabang))) form.id_cabang = ''; });
watch(() => [form.id_perusahaan, form.id_cabang], loadEmployees);
watch(() => filters.company, () => { if (!filterBranches.value.some(row => row.value === String(filters.branch))) filters.branch = ''; });
onMounted(async () => {
  try {
    const [companyResponse, branchResponse] = await Promise.all([getCompanies(), getBranches()]);
    companyRows.value = normalizeList(unwrapResponse(companyResponse)); branchRows.value = normalizeList(unwrapResponse(branchResponse));
    if (!isSuperUser(auth)) { filters.company = getLoginCompanyId(auth.user); filters.branch = getLoginBranchId(auth.user); }
    await loadRows();
  } catch (error) { pageError.value = normalizeError(error, 'Referensi belum dapat dimuat.'); }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="Kasbon Karyawan" description="Pengajuan dan approval kasbon karyawan. Terpisah dari kasbon klaim promo.">
      <button v-if="canCreate" class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white" @click="openCreate">Ajukan Kasbon</button>
    </PageHeader>
    <section class="panel grid gap-4 p-5 md:grid-cols-3 xl:grid-cols-6">
      <AppSearchSelect v-model="filters.company" label="Perusahaan" :options="companies" placeholder="Semua perusahaan" />
      <AppSearchSelect v-model="filters.branch" label="Cabang" :options="filterBranches" placeholder="Semua cabang" />
      <AppSearchSelect v-model="filters.status" label="Status" :options="statusOptions" placeholder="Semua status" />
      <label class="field-label">Dari tanggal<input v-model="filters.from" type="date" class="field-control mt-1" /></label>
      <label class="field-label">Sampai tanggal<input v-model="filters.to" type="date" class="field-control mt-1" /></label>
      <button class="self-end rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" :disabled="loading.list" @click="loadRows()">Tampilkan</button>
    </section>
    <p v-if="feedback" role="status" class="rounded-xl bg-emerald-50 p-4 text-emerald-700">{{ feedback }}</p>
    <p v-if="pageError" role="alert" class="rounded-xl bg-rose-50 p-4 text-rose-700">{{ pageError }}</p>
    <AppTable :columns="columns" :rows="rows" :loading="loading.list" :paginated="false" clickable-rows row-key="id" empty-message="Belum ada kasbon pada filter ini." @row-click="openDetail" />
    <div class="flex items-center justify-end gap-3 text-sm"><span>{{ total }} pengajuan · Hal {{ filters.page }}</span><button :disabled="loading.list || filters.page <= 1" class="rounded-lg border px-3 py-2 disabled:opacity-40" @click="loadRows(filters.page - 1)">Sebelumnya</button><button :disabled="loading.list || filters.page * limit >= total" class="rounded-lg border px-3 py-2 disabled:opacity-40" @click="loadRows(filters.page + 1)">Berikutnya</button></div>
    <AppModal :open="createOpen" title="Ajukan Kasbon Karyawan" size="xl" :hide-close="loading.save" :close-on-backdrop="!loading.save" @close="!loading.save && (createOpen = false)">
      <p v-if="formError" role="alert" class="mb-4 rounded-xl bg-rose-50 p-3 text-rose-700">{{ formError }}</p>
      <fieldset :disabled="loading.save" class="grid min-w-0 gap-4 md:grid-cols-2">
        <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companies" :disabled="loading.save" />
        <AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="formBranches" :disabled="loading.save || !form.id_perusahaan" />
        <AppSearchSelect v-model="form.id_karyawan" label="Karyawan" :options="employeeOptions" :loading="loading.employees" :disabled="loading.save || !form.id_cabang" placeholder="Pilih karyawan" empty-text="Tidak ada karyawan dalam cakupan ini." />
        <label class="field-label">Nominal (Rp)<input v-model="form.nominal" type="number" min="0.01" step="0.01" max="9999999999999.99" class="field-control mt-1" /></label>
        <label class="field-label">Tanggal pengajuan<input v-model="form.tanggal_pengajuan" type="date" class="field-control mt-1" /></label>
        <label class="field-label">Jatuh tempo (opsional)<input v-model="form.tanggal_jatuh_tempo" type="date" :min="form.tanggal_pengajuan" class="field-control mt-1" /></label>
        <label class="field-label md:col-span-2">Keperluan<textarea v-model="form.keperluan" maxlength="2000" rows="3" class="field-control mt-1" /></label>
      </fieldset>
      <p class="mt-4 text-sm text-slate-500">Persetujuan belum mencairkan kas atau memotong gaji. Pengaju/penerima tidak dapat menyetujui pengajuannya sendiri.</p>
      <template #footer><div class="flex justify-end gap-3"><button :disabled="loading.save" class="rounded-xl border px-4 py-3" @click="createOpen = false">Batal</button><button :disabled="loading.save || loading.employees" class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" @click="submit">{{ loading.save ? 'Menyimpan…' : 'Kirim Pengajuan' }}</button></div></template>
    </AppModal>
    <AppModal :open="detailOpen" title="Detail Kasbon Karyawan" size="xl" :hide-close="loading.decision" :close-on-backdrop="!loading.decision" @close="!loading.decision && (detailOpen = false)">
      <p v-if="loading.detail">Memuat rincian…</p>
      <p v-if="detailError" role="alert" class="mb-4 rounded-xl bg-rose-50 p-3 text-rose-700">{{ detailError }}</p>
      <div v-if="detail && !loading.detail" class="space-y-5">
        <dl class="grid gap-4 md:grid-cols-2"><div><dt class="field-label">No. Kasbon</dt><dd>{{ detail.nomor }}</dd></div><div><dt class="field-label">Status</dt><dd>{{ states[detail.status] }}</dd></div><div><dt class="field-label">Karyawan</dt><dd>{{ detail.nama_karyawan }}</dd></div><div><dt class="field-label">Diajukan oleh</dt><dd>{{ detail.nama_pengaju }}</dd></div><div><dt class="field-label">Perusahaan / Cabang</dt><dd>{{ detail.nama_perusahaan }} / {{ detail.nama_cabang }}</dd></div><div><dt class="field-label">Nominal</dt><dd class="text-xl font-bold">{{ money(detail.nominal) }}</dd></div><div><dt class="field-label">Tanggal pengajuan</dt><dd>{{ date(detail.tanggal_pengajuan) }}</dd></div><div><dt class="field-label">Jatuh tempo</dt><dd>{{ date(detail.tanggal_jatuh_tempo) }}</dd></div></dl>
        <div><p class="field-label">Keperluan</p><p class="whitespace-pre-wrap">{{ detail.keperluan }}</p></div>
        <section><h3 class="mb-2 font-bold">Riwayat Pengajuan &amp; Approval</h3><ol class="space-y-3"><li v-for="event in detail.events" :key="event.id" class="rounded-xl border border-slate-400/30 p-3 text-sm"><strong>{{ event.action === 'SUBMITTED' ? 'Diajukan' : states[event.action] }}</strong> · {{ event.nama_actor }} · {{ new Date(event.created_at).toLocaleString('id-ID') }}<p v-if="event.catatan" class="mt-1 whitespace-pre-wrap">{{ event.catatan }}</p></li></ol></section>
        <label v-if="canDecide" class="field-label">Catatan keputusan (wajib untuk penolakan)<textarea v-model="decisionNote" :disabled="loading.decision" maxlength="2000" rows="3" class="field-control mt-1" /></label>
        <p v-else-if="detail.status === 'PENDING'" class="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">Menunggu keputusan petugas approval yang berbeda dari pengaju dan penerima kasbon.</p>
      </div>
      <template #footer><div class="flex justify-end gap-3"><button :disabled="loading.decision" class="rounded-xl border px-4 py-3" @click="detailOpen = false">Tutup</button><template v-if="canDecide && !loading.detail"><button :disabled="loading.decision" class="rounded-xl bg-rose-700 px-4 py-3 font-bold text-white disabled:opacity-50" @click="decide('REJECTED')">Tolak</button><button :disabled="loading.decision" class="rounded-xl bg-brand-600 px-4 py-3 font-bold text-white disabled:opacity-50" @click="decide('APPROVED')">{{ loading.decision ? 'Memproses…' : 'Setujui' }}</button></template></div></template>
    </AppModal>
  </div>
</template>
