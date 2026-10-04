<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { workflowGet, workflowPost, workflowPut, workflowDelete, mobileWorkflow } from '@/api/paymentWorkflow';
import { getCompanies, getBranches, getSales } from '@/api/master';
import { getCoaCatalog } from '@/api/finance';
import { normalizeList, normalizeError, unwrapResponse } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
import { getBranchOptionsForCompany, getCompanyOptionsForScope } from '@/utils/filterScope';
import { toLocalDateInputValue } from '@/utils/date';
import PageHeader from '@/shared/components/PageHeader.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import AppModal from '@/shared/components/AppModal.vue';

const route = useRoute(), auth = useAuthStore();
const tab = computed(() => route.meta.workflowTab || 'receipts');
const title = computed(() => ({ receipts: 'Pembayaran Tagihan — Kuitansi', cash: 'Setoran Tunai — Kuitansi', transfer: 'Setoran Non Tunai — Kuitansi', giro: 'Setoran Giro', cancel: 'Batal Kuitansi', settings: 'Pengaturan Workflow Pembayaran', journals: 'Jurnal Pembayaran', mobile: 'LPH & Pembayaran Sales' }[tab.value]));
const allowed = p => auth.hasPermission(p);
const list = ref([]), lphs = ref([]), funds = ref([]), companies = ref([]), branches = ref([]), sales = ref([]), accounts = ref([]), mutations = ref([]), credits = ref([]);
const error = ref(''), success = ref(''), busy = ref(false), modal = ref(''), detail = ref(null), lp = ref(null), quote = ref(null);
const form = reactive({}), settings = reactive({ company: '', enabled: false, max_fee: '2900', accounts: {} });
const purposes = { CASH: 'Kas', BANK: 'Bank', GIRO: 'Piutang Giro', CLEARING: 'Dana Belum Teridentifikasi', RECEIVABLE: 'Piutang Usaha', ADVANCE: 'Uang Muka', RETURN: 'Retur', FEE: 'Biaya Lain' };
const labels = { CASH: 'Tunai', TRANSFER: 'Non Tunai', GIRO: 'Giro', ADVANCE: 'Uang Muka', RETURN: 'Retur', PENDING: 'Menunggu approval', APPROVED: 'Disetujui', DRAFT: 'Draft', FINALIZED: 'Finalized', CANCEL_REQUESTED: 'Pengajuan batal', CANCELLED: 'Cancelled', REJECTED: 'Ditolak', NOT_CLEARED: 'Belum cair', CLEARED: 'Cair', BOUNCED: 'Ditolak bank' };
const money = v => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR' }).format(Number(v || 0));
const shownDate = v => v ? new Date(v).toLocaleDateString('id-ID') : '—';
const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth));
const branchOptions = computed(() => getBranchOptionsForCompany(branches.value, auth, form.id_perusahaan, false, companies.value));
const optionRows = (rows, label) => rows.map(r => ({ value: String(r.id), label: label(r) }));
const actorId = computed(() => String(auth.user?.id_user || auth.user?.id || auth.user?.user_id || ''));
const canFinalize = row => allowed('finance.receipts.approve') && row.status === 'DRAFT' && String(row.created_by) !== actorId.value;
const scopedFunds = invoice => funds.value.filter(f => f.approval === 'APPROVED' && f.giro_status !== 'BOUNCED' && Number(f.remaining) > 0 && String(f.id_perusahaan) === String(lp.value?.id_perusahaan) && String(f.id_cabang) === String(lp.value?.id_cabang) && (!f.id_customer || String(f.id_customer) === String(invoice.id_customer)) && (!f.id_sales || String(f.id_sales) === String(lp.value?.id_sales)));
let refreshSequence = 0;
async function refresh() {
  const seq = ++refreshSequence; busy.value = true; error.value = '';
  try {
    const mode = tab.value;
    let response;
    if (mode === 'mobile') response = await mobileWorkflow('get', 'lphs');
    else if (mode === 'settings') response = await workflowGet('settings');
    else response = await workflowGet(mode === 'cancel' ? 'cancellations' : mode === 'journals' ? 'journals' : ['cash','transfer','giro'].includes(mode) ? 'funds' : 'receipts');
    if (seq !== refreshSequence) return;
    list.value = normalizeList(unwrapResponse(response));
    if (['cash','transfer','giro'].includes(mode)) {
      const kind = { cash: 'CASH', transfer: 'TRANSFER', giro: 'GIRO' }[mode];
      list.value = list.value.filter(r => r.kind === kind);
    }
  } catch (e) { if (seq === refreshSequence) { list.value = []; error.value = normalizeError(e); } }
  finally { if (seq === refreshSequence) busy.value = false; }
}
async function action(fn, message) {
  if (busy.value) return;
  busy.value = true; error.value = ''; success.value = '';
  try { await fn(); success.value = message; modal.value = ''; await refresh(); }
  catch (e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function masters() {
  const values = await Promise.all([getCompanies(), getBranches(), getSales()]);
  [companies.value, branches.value, sales.value] = values.map(r => normalizeList(unwrapResponse(r)));
}
function resetForm(values = {}) { Object.keys(form).forEach(k => delete form[k]); Object.assign(form, values); quote.value = null; }
async function newFund(row = null) {
  try {
    await masters();
    resetForm({ kind: { cash:'CASH', transfer:'TRANSFER', giro:'GIRO' }[tab.value], id_perusahaan:'', id_cabang:'', id_sales:'', reference:'', bank:'', account_name:'', amount:'', client_key:crypto.randomUUID(), ...row, received_date:row?.received_date ? toLocalDateInputValue(new Date(row.received_date)) : toLocalDateInputValue(), due_date:row?.due_date ? toLocalDateInputValue(new Date(row.due_date)) : '', edit_id:row?.id });
    modal.value = 'fund';
  } catch(e) { error.value = normalizeError(e); }
}
async function importBank() {
  try { mutations.value = normalizeList(unwrapResponse(await workflowGet('bank-mutations'))); resetForm({ id_mutasi:'' }); modal.value = 'import'; }
  catch(e) { error.value = normalizeError(e); }
}
async function registerCredit() {
  try { credits.value = normalizeList(unwrapResponse(await workflowGet('credit-notes'))); resetForm({ id_credit_note:'' }); modal.value = 'credit'; }
  catch(e) { error.value = normalizeError(e); }
}
async function newReceipt(row = null) {
  busy.value = true; error.value = '';
  try {
    const [l, f] = await Promise.all([workflowGet('lphs'), workflowGet('funds')]);
    lphs.value = normalizeList(unwrapResponse(l)); funds.value = normalizeList(unwrapResponse(f));
    resetForm({ id_lph: row?.id_lph || '', number: row?.number || '', receipt_date:toLocalDateInputValue(), client_key:crypto.randomUUID(), invoices:[], edit_id:row?.id });
    lp.value = null; modal.value = 'receipt';
    if (row) await selectLph();
  } catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function selectLph() {
  quote.value = null; lp.value = null; form.invoices = [];
  if (!form.id_lph) return;
  try {
    lp.value = unwrapResponse(await workflowGet(`lphs/${form.id_lph}/detail`));
    form.invoices = lp.value.invoices.filter(i => Number(i.remaining) > 0).map(i => ({ ...i, selected:false, sources:[], fee:'', fee_name:'', excess_treatment:'ADVANCE' }));
  } catch(e) { error.value = normalizeError(e); }
}
function payload() {
  return { id_lph:form.id_lph, number:form.number, receipt_date:form.receipt_date, client_key:form.client_key, edit_id:form.edit_id, invoices:form.invoices.filter(i => i.selected).map(i => ({ id_faktur:i.id, sources:i.sources, fee:i.fee || 0, fee_name:i.fee_name, excess_treatment:i.excess_treatment })) };
}
async function preview() {
  error.value = ''; quote.value = null; busy.value = true;
  try { quote.value = unwrapResponse(await workflowPost('receipts/preview', payload())); }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function openDetail(row) {
  error.value = ''; busy.value = true;
  try { detail.value = unwrapResponse(await workflowGet(`receipts/${row.id}`)); modal.value = 'detail'; }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
function ask(row, operation) { detail.value = row; resetForm({ reason:'', note:'', id_mutasi:'', clearing_reference:`CLR-${row.id}` }); modal.value = operation; }
async function openMobile(row) {
  busy.value = true; error.value = '';
  try { lp.value = unwrapResponse(await mobileWorkflow('get', `lphs/${row.id}`)); resetForm({ id_faktur:'', method:'CASH', amount:'', giro_number:'', bank:'', due_date:'', cash_transfer:'0', checked:[], client_key:crypto.randomUUID() }); modal.value = 'mobile'; }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function configuration() {
  try { await masters(); accounts.value = normalizeList(unwrapResponse(await getCoaCatalog())); }
  catch(e) { error.value = normalizeError(e); }
}
watch(() => settings.company, company => {
  const found = list.value.find(r => String(r.id_perusahaan) === String(company));
  settings.enabled = found?.enabled || false; settings.max_fee = String(found?.max_fee ?? 2900); settings.accounts = { ...(found?.accounts || {}) };
});
watch(() => form.id_perusahaan, () => { if (!branchOptions.value.some(b => b.value === String(form.id_cabang))) form.id_cabang = ''; });
watch(() => form.invoices, () => { quote.value = null; }, { deep:true });
watch(tab, async () => { modal.value = ''; await refresh(); if (tab.value === 'settings') await configuration(); });
onMounted(async () => { await refresh(); if (tab.value === 'settings') await configuration(); });
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="title" description="LPH → klaim sales → setoran → kuitansi → approval → jurnal. Transaksi Rekap lama tetap tersedia melalui menu legacy.">
      <button class="btn-secondary" :disabled="busy" @click="refresh">Muat ulang</button>
      <button v-if="['cash','transfer','giro'].includes(tab) && allowed('finance.funds.create')" class="btn-primary" :disabled="busy" @click="newFund()">Tambah Setoran</button>
      <button v-if="tab === 'transfer' && allowed('finance.funds.create')" class="btn-secondary" :disabled="busy" @click="importBank">Import Mutasi</button>
      <button v-if="tab === 'receipts' && allowed('finance.receipts.create')" class="btn-primary" :disabled="busy" @click="newReceipt()">Buat Kuitansi</button>
      <button v-if="tab === 'receipts' && allowed('finance.receipts.create')" class="btn-secondary" :disabled="busy" @click="registerCredit">Daftarkan Credit Note</button>
    </PageHeader>
    <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-4 text-rose-800">{{ error }}</p>
    <p v-if="success" role="status" class="rounded-xl bg-emerald-50 p-4 text-emerald-800">{{ success }}</p>
    <p v-if="busy" role="status">Memproses…</p>
    <div v-if="['cash','transfer','giro'].includes(tab)" class="panel overflow-x-auto p-4">
      <table class="w-full text-left text-sm"><thead><tr><th>Referensi</th><th>Tanggal</th><th>Nominal / Sisa</th><th>Status</th><th>Aksi</th></tr></thead><tbody>
        <tr v-for="row in list" :key="row.id" class="border-t border-slate-400/20"><td class="py-4">{{ row.reference }}<p>{{ row.bank }}</p></td><td>{{ shownDate(row.received_date) }}<p v-if="row.due_date">Jatuh tempo: {{ shownDate(row.due_date) }}</p></td><td>{{ money(row.amount) }}<p>Sisa: {{ money(row.remaining) }}</p></td><td>{{ labels[row.approval] }}<p>{{ labels[row.giro_status] }} <b v-if="row.overdue" class="text-rose-600">Lewat jatuh tempo</b></p></td><td><div class="flex flex-wrap gap-2">
          <button v-if="row.kind === 'CASH' && row.approval === 'PENDING' && allowed('finance.funds.approve')" class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`funds/${row.id}/approve`), 'Setoran disetujui Kasir; jurnal penerimaan tercatat.')">Approve Kasir</button>
          <button v-if="row.giro_status === 'NOT_CLEARED' && allowed('finance.giro.clear')" class="btn-primary" :disabled="busy" @click="ask(row, 'clear')">Pencairan</button>
          <button v-if="row.giro_status === 'NOT_CLEARED' && allowed('finance.giro.bounce')" class="btn-secondary" :disabled="busy" @click="ask(row, 'bounce')">Tolak Giro</button>
          <button v-if="Number(row.remaining) === Number(row.amount) && allowed('finance.funds.create') && !row.id_lph && !row.id_mutasi && !['CLEARED','BOUNCED'].includes(row.giro_status)" class="btn-secondary" :disabled="busy" @click="newFund(row)">Edit</button>
          <button v-if="Number(row.remaining) === Number(row.amount) && allowed('finance.funds.create') && !row.id_lph && !row.id_mutasi && !['CLEARED','BOUNCED'].includes(row.giro_status)" class="btn-secondary" :disabled="busy" @click="ask(row,'delete')">Hapus</button>
        </div></td></tr>
      </tbody></table>
      <p v-if="!list.length && !busy" class="py-6">Belum ada setoran pada alur kuitansi ini.</p>
    </div>
    <div v-if="tab === 'receipts'" class="panel overflow-x-auto p-4"><table class="w-full text-left text-sm"><thead><tr><th>No. Kuitansi</th><th>LPH</th><th>Tanggal</th><th>Nominal</th><th>Status</th><th>Aksi</th></tr></thead><tbody>
      <tr v-for="row in list" :key="row.id" class="border-t border-slate-400/20"><td class="py-4">{{ row.number }}</td><td>{{ row.kode_lph }}</td><td>{{ shownDate(row.receipt_date) }}</td><td>{{ money(row.total) }}</td><td>{{ labels[row.status] }}</td><td><div class="flex flex-wrap gap-2"><button class="btn-secondary" :disabled="busy" @click="openDetail(row)">{{ canFinalize(row) ? 'Tinjau & Finalisasi' : 'Rincian' }}</button><button v-if="row.status === 'FINALIZED' && allowed('finance.receipts.cancel')" class="btn-secondary" :disabled="busy" @click="ask(row, 'cancel')">Ajukan Batal</button><button v-if="row.status === 'CANCELLED' && allowed('finance.receipts.create') && String(row.created_by) === actorId" class="btn-secondary" :disabled="busy" @click="newReceipt(row)">Edit Ulang</button></div></td></tr>
    </tbody></table><p v-if="!list.length && !busy" class="py-6">Belum ada kuitansi. Buat LPH versi Kuitansi, minta sales menerima dan mengembalikannya, lalu catat setoran.</p></div>
    <div v-if="tab === 'cancel'" class="panel space-y-4 p-5"><article v-for="row in list" :key="row.id" class="rounded-xl border border-slate-400/30 p-4"><b>{{ row.number }} · {{ labels[row.status] }}</b><p>{{ row.reason }}</p><p v-if="row.auto_giro" class="text-amber-600">Auto BG: giro ditolak bank</p><div class="mt-3 flex gap-2"><button v-if="row.status === 'DRAFT' && allowed('finance.receipts.cancel')" class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`receipts/${row.id_receipt}/cancel`, { reason:row.reason }), 'Pembatalan diajukan ke supervisor.')">Ajukan ke SPV</button><template v-if="row.status === 'PENDING' && allowed('finance.receipts.cancel-approve') && String(row.created_by) !== actorId && String(row.requested_by) !== actorId"><button class="btn-primary" :disabled="busy" @click="ask(row,'cancel-approve')">Tinjau Pembatalan</button></template></div></article><p v-if="!list.length && !busy">Belum ada pengajuan pembatalan.</p></div>
    <section v-if="tab === 'settings'" class="panel space-y-4 p-5"><p>Pilih COA perusahaan yang sesuai. Tidak ada kode akun yang dibuat atau diasumsikan otomatis. Aktivasi berlaku untuk LPH baru yang dipilih memakai alur Kuitansi.</p><AppSearchSelect v-model="settings.company" label="Perusahaan" :options="companyOptions"/><div class="grid gap-4 md:grid-cols-2"><AppSearchSelect v-for="(label, purpose) in purposes" :key="purpose" v-model="settings.accounts[purpose]" :label="label" :options="accounts.filter(a => String(a.id_perusahaan) === String(settings.company) && a.is_active !== false).map(a => ({value:String(a.id_coa),label:`${a.nomor_akun} — ${a.nama_akun}`}))"/></div><label class="block">Batas Biaya Lain per faktur (Rp)<input v-model="settings.max_fee" type="number" min="0" step="0.01" class="field-control"/></label><label class="flex items-center gap-2"><input v-model="settings.enabled" type="checkbox"/>Aktifkan alur kuitansi untuk perusahaan ini</label><button class="btn-primary" :disabled="busy || !settings.company" @click="action(() => workflowPut('settings', { id_perusahaan:settings.company,accounts:settings.accounts,enabled:settings.enabled,max_fee:settings.max_fee }), 'Pengaturan tersimpan.')">Simpan Pengaturan</button></section>
    <section v-if="tab === 'journals'" class="panel space-y-4 p-5"><article v-for="row in list" :key="row.id_jurnal" class="rounded-xl border border-slate-400/30 p-4"><h3 class="font-bold">{{ row.reference }}</h3><p>{{ row.keterangan }}</p><table class="mt-3 w-full text-left text-sm"><thead><tr><th>Akun</th><th>Debit</th><th>Kredit</th></tr></thead><tbody><tr v-for="line in row.lines" :key="line.id_jurnal_detail"><td>{{ line.kode_jurnal }} {{ line.nama_akun }}</td><td>{{ money(line.debit) }}</td><td>{{ money(line.kredit) }}</td></tr></tbody></table></article><p v-if="!list.length && !busy">Belum ada jurnal workflow.</p></section>
    <section v-if="tab === 'mobile'" class="panel space-y-4 p-5"><p>LPH milik akun Sales yang login. Klaim tidak mengurangi piutang sebelum Finance memfinalisasi kuitansi.</p><button v-for="row in list" :key="row.id" class="block w-full rounded-xl border border-slate-400/30 p-4 text-left" :disabled="busy" @click="openMobile(row)">{{ row.kode_lph }} · {{ row.status_dokumen }}</button><p v-if="!list.length && !busy">Belum ada LPH versi Kuitansi untuk sales ini.</p></section>

    <AppModal :open="modal === 'fund'" :title="form.edit_id ? 'Edit Setoran' : 'Tambah Setoran'" size="xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''"><form @submit.prevent="action(() => form.edit_id ? workflowPut(`funds/${form.edit_id}`, { ...form }) : workflowPost('funds',{ ...form }), 'Setoran tersimpan.')"><fieldset :disabled="busy" class="grid gap-4 md:grid-cols-2"><AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companyOptions" :disabled="busy || !!form.edit_id"/><AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="branchOptions" :disabled="busy || !!form.edit_id"/><AppSearchSelect v-model="form.id_sales" label="Sales penyerah (opsional)" :options="optionRows(sales,r => r.nama || r.nama_sales || String(r.id))"/><label>Nomor referensi / BG<input v-model="form.reference" required maxlength="160" class="field-control"/></label><label>Tanggal penerimaan<input v-model="form.received_date" type="date" required class="field-control"/></label><label>Nominal (Rp)<input v-model="form.amount" type="number" min="0.01" step="0.01" required class="field-control"/></label><label v-if="form.kind !== 'CASH'">Bank<input v-model="form.bank" :required="form.kind === 'GIRO'" maxlength="160" class="field-control"/></label><template v-if="form.kind === 'GIRO'"><label>Atas nama<input v-model="form.account_name" class="field-control"/></label><label>Jatuh tempo<input v-model="form.due_date" type="date" required class="field-control"/></label></template></fieldset><p class="mt-4 text-sm">Tunai menunggu approval Kasir. Non tunai/Giro memposting jurnal penerimaan saat disimpan. Setoran yang memiliki alokasi tidak dapat diubah.</p><button class="btn-primary mt-4" :disabled="busy">Simpan Setoran</button></form><p v-if="error" role="alert" class="mt-3 text-rose-600">{{ error }}</p></AppModal>
    <AppModal :open="modal === 'receipt'" title="Buat / Edit Kuitansi" size="6xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''"><div class="space-y-4"><label>No. Kuitansi<input v-model="form.number" :disabled="busy || !!form.edit_id" class="field-control" maxlength="100" @input="quote = null"/></label><label>Tanggal<input v-model="form.receipt_date" type="date" :disabled="busy" class="field-control" @input="quote = null"/></label><label>LPH dikembalikan<select v-model="form.id_lph" :disabled="busy || !!form.edit_id" class="field-control" @change="selectLph"><option value="">Pilih LPH</option><option v-for="l in lphs.filter(l => l.status_dokumen === 'DIKEMBALIKAN')" :key="l.id" :value="l.id">{{ l.kode_lph }} — {{ l.nama_sales }}</option></select></label><article v-for="invoice in form.invoices" :key="invoice.id" class="rounded-xl border border-slate-400/30 p-4"><label class="flex gap-2"><input v-model="invoice.selected" type="checkbox" :disabled="busy"/><b>{{ invoice.no_faktur }} — {{ invoice.nama_customer }} · Sisa {{ money(invoice.remaining) }}</b></label><div v-if="invoice.selected" class="mt-4 grid gap-3 md:grid-cols-2"><fieldset :disabled="busy"><legend>Pilih sumber dana</legend><label v-for="source in scopedFunds(invoice)" :key="source.id" class="mt-2 flex gap-2"><input v-model="invoice.sources" type="checkbox" :value="source.id"/>{{ labels[source.kind] }} {{ source.reference }} — Sisa {{ money(source.remaining) }}</label><p v-if="!scopedFunds(invoice).length">Belum ada sumber dana yang tersedia.</p></fieldset><div class="space-y-3"><label class="block">Biaya Lain (Rp)<input v-model="invoice.fee" type="number" min="0" step="0.01" :disabled="busy" class="field-control"/></label><label class="block">Keterangan biaya<input v-model="invoice.fee_name" :disabled="busy" class="field-control"/></label><label class="block">Jika ada kelebihan<select v-model="invoice.excess_treatment" :disabled="busy" class="field-control"><option value="ADVANCE">Uang Muka Customer</option><option value="FEE">Biaya Lain</option></select></label></div></div></article><p>Nominal dihitung server dari klaim sales, sisa sumber dana, dan sisa piutang. Jumlah alokasi tidak diketik.</p><button class="btn-secondary" :disabled="busy" @click="preview">Hitung & Tinjau Alokasi</button><div v-if="quote" class="rounded-xl bg-emerald-50 p-4 text-emerald-900"><p v-for="i in quote.invoices" :key="i.id_faktur">{{ i.no_faktur }}: pembayaran {{ money(i.paid) }} · kelebihan {{ money(i.excess) }} ({{ i.excess_treatment }})</p><button class="btn-primary mt-3" :disabled="busy" @click="action(() => form.edit_id ? workflowPut(`receipts/${form.edit_id}`,payload()) : workflowPost('receipts',payload()), 'Kuitansi Draft tersimpan; sumber dana ditahan sampai finalisasi/pembatalan.')">Simpan Draft</button></div><p v-if="error" role="alert" class="text-rose-600">{{ error }}</p></div></AppModal>
    <AppModal :open="modal === 'detail'" title="Tinjau Kuitansi & Rekonsiliasi" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''"><div v-if="detail" class="space-y-4"><h3 class="font-bold">{{ detail.number }} · {{ labels[detail.status] }}</h3><article v-for="invoice in detail.invoices" :key="invoice.id" class="rounded-xl border border-slate-400/30 p-3"><b>{{ invoice.no_faktur }} · {{ invoice.nama_customer }}</b><p>Alokasi {{ money(invoice.paid) }} · Kelebihan {{ money(invoice.excess) }}</p><p v-for="a in detail.allocations.filter(a => a.id_faktur === invoice.id_faktur)" :key="a.id">{{ labels[a.kind] || 'Biaya Lain' }} {{ a.reference || a.fee_name }}: {{ money(a.amount) }}</p></article><p v-for="a in detail.audit" :key="a.id" class="text-sm">{{ a.action }} · {{ a.nama }} · {{ shownDate(a.created_at) }}</p><button v-if="canFinalize(detail)" class="btn-primary" :disabled="busy" @click="ask(detail,'finalize')">Konfirmasi Rekonsiliasi & Finalisasi</button><p v-else-if="detail.status === 'DRAFT'">Finalisasi memerlukan petugas berizin approval yang berbeda dari pembuat kuitansi.</p></div><p v-if="error" role="alert" class="mt-3 text-rose-600">{{ error }}</p></AppModal>
    <AppModal :open="['clear','bounce','cancel','cancel-approve','finalize','delete','import','credit'].includes(modal)" :title="{clear:'Pencairan Giro',bounce:'Penolakan Giro',cancel:'Ajukan Pembatalan', 'cancel-approve':'Keputusan SPV',finalize:'Konfirmasi Finalisasi',delete:'Hapus Setoran',import:'Import Mutasi Dana Masuk',credit:'Daftarkan Credit Note'}[modal] || ''" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''"><div class="space-y-4"><p v-if="detail">{{ detail.number || detail.reference }} · {{ money(detail.amount || detail.total) }}</p><template v-if="modal === 'clear'"><label>Referensi kliring bank<input v-model="form.clearing_reference" class="field-control"/></label><label>ID mutasi bank (opsional)<input v-model="form.id_mutasi" type="number" class="field-control"/></label><p>Nominal harus sama. Bukti kliring tidak dibuat sebagai sumber pembayaran baru.</p><button class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`giro/${detail.id}/clear`,{...form}), 'Giro cair; jurnal pencairan tercatat.')">Konfirmasi Pencairan</button></template><template v-if="['bounce','cancel'].includes(modal)"><label>Alasan wajib<textarea v-model="form.reason" maxlength="2000" class="field-control"/></label><button class="btn-primary" :disabled="busy || !form.reason.trim()" @click="action(() => workflowPost(modal === 'bounce' ? `giro/${detail.id}/bounce` : `receipts/${detail.id}/cancel`,{reason:form.reason}), modal === 'bounce' ? 'Giro ditolak; kuitansi terkait masuk tindak lanjut pembatalan.' : 'Pembatalan diajukan.')">Kirim</button></template><template v-if="modal === 'cancel-approve'"><label>Catatan keputusan<textarea v-model="form.note" maxlength="2000" class="field-control"/></label><p>Persetujuan membalik jurnal, membuka piutang, dan melepaskan sumber dana. Uang muka hasil kuitansi yang sudah dipakai akan mengunci pembatalan.</p><div class="flex gap-2"><button class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`cancellations/${detail.id}/decision`,{decision:'APPROVED',note:form.note}), 'Pembatalan disetujui; jurnal reversal tercatat.')">Setujui Pembatalan</button><button class="btn-secondary" :disabled="busy" @click="action(() => workflowPost(`cancellations/${detail.id}/decision`,{decision:'REJECTED',note:form.note}), 'Pembatalan ditolak; kuitansi tetap final.')">Tolak Pembatalan</button></div></template><template v-if="modal === 'finalize'"><p>Saya sudah meninjau sumber dana, klaim sales, nominal per faktur, dan kelebihan dana. Finalisasi akan mengurangi piutang dan memposting jurnal. Nominal diperiksa ulang oleh server.</p><button class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`receipts/${detail.id}/finalize`,{confirm_reconciliation:true}), 'Kuitansi difinalisasi; piutang dan jurnal diperbarui.')">Setujui & Finalisasi</button></template><template v-if="modal === 'delete'"><p>Hapus hanya diperbolehkan jika setoran belum pernah dialokasikan. Jurnal penerimaan yang sudah tercatat dibalik dengan jurnal koreksi.</p><button class="btn-primary" :disabled="busy" @click="action(() => workflowDelete(`funds/${detail.id}`),'Setoran dihapus dengan audit koreksi.')">Konfirmasi Hapus</button></template><template v-if="modal === 'import'"><AppSearchSelect v-model="form.id_mutasi" label="Mutasi dana masuk belum diimpor" :options="mutations.map(m => ({value:String(m.id_mutasi),label:`${m.kode_mutasi} — ${money(m.nominal_mutasi)}`}))"/><button class="btn-primary" :disabled="busy || !form.id_mutasi" @click="action(() => workflowPost(`mutations/${form.id_mutasi}/import`),'Mutasi diimpor sebagai sumber pembayaran.')">Import</button></template><template v-if="modal === 'credit'"><AppSearchSelect v-model="form.id_credit_note" label="Credit Note belum dipakai" :options="credits.map(c => ({value:String(c.id_cn),label:`${c.kode_cn} — ${money(c.total_cn)}`}))"/><button class="btn-primary" :disabled="busy || !form.id_credit_note" @click="action(() => workflowPost(`credit-notes/${form.id_credit_note}/reserve`),'Credit Note dicadangkan sebagai sumber retur.')">Daftarkan</button></template><p v-if="error" role="alert" class="text-rose-600">{{ error }}</p></div></AppModal>
    <AppModal :open="modal === 'mobile'" title="LPH Sales" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''"><div v-if="lp" class="space-y-4"><h3 class="font-bold">{{ lp.kode_lph }} · {{ lp.status_dokumen }}</h3><label v-for="i in lp.invoices" :key="i.id" class="block"><input v-if="lp.status_dokumen === 'MENUNGGU_PENERIMAAN'" v-model="form.checked" type="checkbox" :value="i.id"/> {{ i.no_faktur }} {{ i.nama_customer }} — {{ money(i.remaining) }}</label><button v-if="lp.status_dokumen === 'MENUNGGU_PENERIMAAN'" class="btn-primary" :disabled="busy || form.checked.length !== lp.invoices.length" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/accept`,{checked_detail_ids:lp.checked_details.filter(d => form.checked.includes(d.id_faktur)).map(d => d.id)}),'LPH diterima sales.')">Terima LPH</button><template v-if="lp.status_dokumen === 'AKTIF'"><label>Faktur<select v-model="form.id_faktur" class="field-control"><option value="">Pilih faktur</option><option v-for="i in lp.invoices" :key="i.id" :value="i.id">{{ i.no_faktur }}</option></select></label><label>Metode<select v-model="form.method" class="field-control"><option value="CASH">Cash</option><option value="TRANSFER">Transfer</option><option value="GIRO">Giro</option></select></label><label>Nominal klaim<input v-model="form.amount" type="number" min="0.01" step="0.01" class="field-control"/></label><div v-if="form.method === 'GIRO'" class="grid gap-3 md:grid-cols-3"><label>No. BG<input v-model="form.giro_number" class="field-control"/></label><label>Bank<input v-model="form.bank" class="field-control"/></label><label>Jatuh tempo<input v-model="form.due_date" type="date" class="field-control"/></label></div><button class="btn-primary" :disabled="busy" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/claims`,{...form}), 'Klaim dicatat, belum dianggap uang masuk.')">Catat Klaim</button></template><article v-for="c in lp.claims" :key="c.id" class="rounded-xl border border-slate-400/30 p-3">Faktur {{ c.id_faktur }} · {{ labels[c.method] }} · {{ money(c.amount) }}<button v-if="lp.status_dokumen === 'AKTIF'" class="btn-secondary ml-3" :disabled="busy" @click="action(() => mobileWorkflow('delete',`claims/${c.id}`),'Klaim dihapus.')">Hapus Klaim</button></article><div v-if="lp.status_dokumen === 'AKTIF'" class="border-t border-slate-400/30 pt-4"><label>Cash yang ditransfer<input v-model="form.cash_transfer" type="number" min="0" step="0.01" class="field-control"/></label><p>Sisa cash setor Kasir: {{ money(lp.claims.filter(c => c.method === 'CASH').reduce((a,c) => a + Number(c.amount),0) - Number(form.cash_transfer || 0)) }}</p><button class="btn-primary mt-3" :disabled="busy" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/return`,{cash_transfer:form.cash_transfer}),'LPH dikembalikan; sisa cash menjadi setoran Pending Kasir.')">Kembalikan LPH</button></div><p v-if="error" role="alert" class="text-rose-600">{{ error }}</p></div></AppModal>
  </div>
</template>
