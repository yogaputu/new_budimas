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
import ReceiptReconciliation from '../components/ReceiptReconciliation.vue';
import ReceiptEditor from '../components/ReceiptEditor.vue';
import { receiptPayload, workflowDate } from '../receiptAllocation';
import { depositSalesOptions } from '../depositSales';
import { paymentPermission } from '@/utils/paymentPermissions';

const route = useRoute(), auth = useAuthStore();
const tab = computed(() => route.meta.workflowTab || 'receipts');
const title = computed(() => ({ receipts: 'Pembayaran Tagihan — Kuitansi', cash: 'Setoran Tunai — Kuitansi', transfer: 'Setoran Non Tunai — Kuitansi', 'bank-input': 'Input / Import Mutasi Bank', giro: 'Setoran Giro', cancel: 'Batal Kuitansi', settings: 'Pengaturan Workflow Pembayaran', fees:'Master Biaya Lain', journals: 'Jurnal Pembayaran', mobile: 'LPH & Pembayaran Sales' }[tab.value]));
const fundKind = computed(() => ({cash:'CASH',transfer:'TRANSFER','bank-input':'TRANSFER',giro:'GIRO'}[tab.value]));
const allowed = p => paymentPermission(auth.permissions || [], p, fundKind.value) ?? auth.hasPermission(p);
const list = ref([]), lphs = ref([]), funds = ref([]), companies = ref([]), branches = ref([]), sales = ref([]), accounts = ref([]), mutations = ref([]), credits = ref([]);
const error = ref(''), success = ref(''), busy = ref(false), modal = ref(''), detail = ref(null), lp = ref(null), quote = ref(null);
const form = reactive({}), settings = reactive({ company: '', enabled: false, max_fee: '2900', accounts: {} });
const accountsLoading = ref(false), accountsError = ref('');
const feeTypes = ref([]), checkedReceipts = ref([]), filter = reactive({search:'',status:'',from:'',to:'',page:1});
const cancellationCandidates=ref([]);
const feeManage = computed(() => allowed('finance.workflow.configure') || allowed('finance.fees.manage'));
const filteredList = computed(() => list.value.filter(row => {
  const text = [row.reference,row.number,row.kode_lph,row.nama_sales,row.bank,row.description,row.notes,row.reason].filter(Boolean).join(' ').toLowerCase();
  const date = workflowDate(row.received_date || row.receipt_date || row.tanggal || row.requested_at);
  return (!filter.search || text.includes(filter.search.toLowerCase())) && (!filter.status || [row.status,row.approval,row.giro_status,row.allocation_status,row.journal_type].includes(filter.status)) && (!filter.from || date>=filter.from) && (!filter.to || date<=filter.to);
}));
const pageCount = computed(() => Math.max(1,Math.ceil(filteredList.value.length/50)));
const pageRows = computed(() => filteredList.value.slice((filter.page-1)*50,filter.page*50));
const statusOptions = computed(() => [...new Set(list.value.flatMap(r => [r.status,r.approval,r.giro_status,r.allocation_status,r.journal_type]).filter(Boolean))]);
const listTotal = computed(() => filteredList.value.reduce((total,row) => total+Number(row.amount || row.total || 0),0));
const availableTotal = computed(() => filteredList.value.reduce((total,row) => total+Number(row.remaining || 0),0));
const receiptSales = computed(() => [...new Map(lphs.value.map(l => [String(l.id_sales),{value:String(l.id_sales),label:l.nama_sales || String(l.id_sales)}])).values()]);
const returnedLphs = computed(() => lphs.value.filter(l => l.status_dokumen==='DIKEMBALIKAN' && (!form.id_sales || String(l.id_sales)===String(form.id_sales))));
const journalTotals = computed(() => filteredList.value.flatMap(r => r.lines || []).reduce((s,l) => ({debit:s.debit+Number(l.debit || 0),credit:s.credit+Number(l.kredit || 0)}),{debit:0,credit:0}));
const clearingCandidates = computed(() => funds.value.filter(f => f.kind==='TRANSFER' && f.transaction_type!=='CREDIT' && f.approval==='APPROVED' && Number(f.remaining)===Number(f.amount) && Number(f.amount)===Number(detail.value?.amount) && String(f.id_perusahaan)===String(detail.value?.id_perusahaan) && String(f.id_cabang)===String(detail.value?.id_cabang)));
let accountsSequence = 0;
const accountOptions = computed(() => accounts.value
  .filter(a => String(a.id_perusahaan) === String(settings.company) && a.is_active !== false)
  .map(a => ({ value: String(a.id_coa), label: `${a.nomor_akun} — ${a.nama_akun}` })));
const purposes = { CASH: 'Kas', BANK: 'Bank', GIRO: 'Piutang Giro', CLEARING: 'Dana Belum Teridentifikasi', RECEIVABLE: 'Piutang Usaha', ADVANCE: 'Uang Muka', RETURN: 'Retur', FEE: 'Biaya Lain' };
const labels = { CASH: 'Tunai', TRANSFER: 'Non Tunai', GIRO: 'Giro', ADVANCE: 'Uang Muka', RETURN: 'Retur', PENDING: 'Menunggu approval', APPROVED: 'Disetujui', DRAFT: 'Draft', FINALIZED: 'Finalized', CANCEL_REQUESTED: 'Pengajuan batal', CANCELLED: 'Cancelled', REJECTED: 'Ditolak', NOT_CLEARED: 'Belum cair', CLEARED: 'Cair', BOUNCED: 'Ditolak bank', ALLOCATED:'Terpakai', PARTIAL:'Terpakai sebagian', UNIDENTIFIED:'Belum dialokasikan', DEBIT:'Debit / dana masuk', CREDIT:'Kredit / dana keluar', MANUAL:'Manual', IMPORT:'Import', LPH:'Pengembalian LPH' };
const money = v => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR' }).format(Number(v || 0));
const shownDate = v => v ? new Date(v).toLocaleDateString('id-ID') : '—';
const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth));
const branchOptions = computed(() => getBranchOptionsForCompany(branches.value, auth, form.id_perusahaan, false, companies.value));
const optionRows = (rows, label) => rows.map(r => ({ value: String(r.id), label: label(r) }));
const salesOptions = computed(() => depositSalesOptions(sales.value, form.id_cabang));
const actorId = computed(() => String(auth.user?.id_user || auth.user?.id || auth.user?.user_id || ''));
const canFinalize = row => allowed('finance.receipts.approve') && row.status === 'DRAFT';
const collectionSummary=computed(()=>{
  const totals={CASH:0,TRANSFER:0,GIRO:0};
  for(const c of lp.value?.claims || []) if(c.method in totals) totals[c.method]+=Math.round(Number(c.amount)*100);
  return {total:(totals.CASH+totals.TRANSFER+totals.GIRO)/100,...Object.fromEntries(Object.entries(totals).map(([k,v])=>[k,v/100]))};
});
let refreshSequence = 0;
async function refresh() {
  const seq = ++refreshSequence; busy.value = true; error.value = '';
  try {
    const mode = tab.value;
    let response;
    if (mode === 'mobile') response = await mobileWorkflow('get', 'lphs');
    else if (mode === 'settings') response = await workflowGet('settings');
    else if (mode === 'fees') response = await workflowGet('fee-types');
    else response = await workflowGet(mode === 'cancel' ? 'cancellations' : mode === 'journals' ? 'journals' : fundKind.value ? 'funds' : 'receipts');
    if (seq !== refreshSequence) return;
    list.value = normalizeList(unwrapResponse(response));
    if(mode==='journals') list.value=list.value.map(r=>({...r,journal_type:{FUND:'Penerimaan Setoran',RECEIPT:'Penerimaan Pembayaran',CLEAR:'Pencairan Giro',BOUNCE:'Giro Ditolak',CANCEL:'Pembatalan Pembayaran'}[r.reference.split(':')[0]] || 'Koreksi Setoran'}));
    checkedReceipts.value=[];
    if (fundKind.value) {
      list.value = list.value.filter(r => r.kind === fundKind.value && (mode !== 'transfer' || r.transaction_type !== 'CREDIT'));
    }
    if (['settings','fees'].includes(mode)) await loadFees(settings.company);
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
  // Branch master uses `id`; the login-scope helper expects `id_cabang`.
  branches.value = branches.value.map(row => ({...row, id_cabang:row.id_cabang || row.id}));
}
function resetForm(values = {}) { Object.keys(form).forEach(k => delete form[k]); Object.assign(form, values); quote.value = null; }
async function newFund(row = null) {
  try {
    await masters();
    resetForm({ kind: fundKind.value, id_perusahaan:'', id_cabang:'', id_sales:'', reference:'', bank:'', account_name:'', amount:'',description:'',notes:'',transaction_type:'DEBIT', client_key:crypto.randomUUID(), ...row, received_date:row?.received_date ? toLocalDateInputValue(new Date(row.received_date)) : toLocalDateInputValue(), due_date:row?.due_date ? toLocalDateInputValue(new Date(row.due_date)) : '', edit_id:row?.id });
    modal.value = 'fund';
  } catch(e) { error.value = normalizeError(e); }
}
async function importBank() {
  try { mutations.value = normalizeList(unwrapResponse(await workflowGet('bank-mutations')));detail.value=null; resetForm({ ids:mutations.value.slice(0,500).map(m => m.id_mutasi) }); modal.value = 'import'; }
  catch(e) { error.value = normalizeError(e); }
}
async function registerCredit() {
  try { credits.value = normalizeList(unwrapResponse(await workflowGet('credit-notes'))); resetForm({ id_credit_note:'' }); modal.value = 'credit'; }
  catch(e) { error.value = normalizeError(e); }
}
async function newReceipt(row = null) {
  busy.value = true; error.value = '';
  try {
    lphs.value = normalizeList(unwrapResponse(await workflowGet('lphs'))); funds.value = [];
    resetForm({ id_lph: row?.id_lph || '',id_sales:'', number: row?.number || '', receipt_date:toLocalDateInputValue(), client_key:crypto.randomUUID(), invoices:[], edit_id:row?.id });
    lp.value = null; modal.value = 'receipt';
    if (row) {
      await selectLph();
      const original=unwrapResponse(await workflowGet(`receipts/${row.id}`));
      for (const invoice of form.invoices) {
        invoice.selected=original.invoices.some(i => String(i.id_faktur)===String(invoice.id));
        invoice.sources=original.allocations.filter(a => String(a.id_faktur)===String(invoice.id) && a.id_source).map(a => ({id_source:a.id_source,amount:String(a.amount)}));
        invoice.fees=original.allocations.filter(a => String(a.id_faktur)===String(invoice.id) && a.id_fee_type).map(a => ({id_fee_type:a.id_fee_type,amount:String(a.amount)}));
        const legacy=original.allocations.find(a=>String(a.id_faktur)===String(invoice.id) && !a.id_source && !a.id_fee_type);
        invoice.legacy_fee=legacy ? {name:legacy.fee_name,amount:String(legacy.amount)} : null;
        invoice.excess_treatment=original.invoices.find(i => String(i.id_faktur)===String(invoice.id))?.excess_treatment || 'ADVANCE';
      }
    }
  } catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
let lphSequence=0;
async function selectLph() {
  const sequence=++lphSequence,selectedId=form.id_lph;
  quote.value = null; lp.value = null; form.invoices = [];
  if (!form.id_lph) return;
  try {
    const [l, f] = await Promise.all([workflowGet(`lphs/${form.id_lph}/detail`), workflowGet('funds', { id_lph:form.id_lph })]);
    if(sequence!==lphSequence || String(form.id_lph)!==String(selectedId)) return;
    const selected=unwrapResponse(l);
    const fees=normalizeList(unwrapResponse(await workflowGet('fee-types',{id_perusahaan:selected.id_perusahaan})));
    if(sequence!==lphSequence || String(form.id_lph)!==String(selectedId)) return;
    lp.value=selected;funds.value=normalizeList(unwrapResponse(f));feeTypes.value=fees;
    form.invoices = lp.value.invoices.filter(i => Number(i.remaining) > 0).map(i => ({ ...i, selected:false, sources:[], fees:[], excess_treatment:'ADVANCE' }));
  } catch(e) { error.value = normalizeError(e); }
}
function payload() {
  return receiptPayload(form);
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
async function ask(row, operation) {
  error.value='';detail.value = row; resetForm({ reason:'', note:'', id_mutasi:'',id_payment_source:'', reconciliation_checked:false, clearing_reference:`CLR-${row.id}` });
  if (operation==='clear') { try { funds.value=normalizeList(unwrapResponse(await workflowGet('funds'))); } catch(e){error.value=normalizeError(e);return;} }
  modal.value = operation;
}
async function openFundDetail(row) { busy.value=true;error.value='';try {detail.value=unwrapResponse(await workflowGet(`funds/${row.id}`));modal.value='fund-detail';} catch(e){error.value=normalizeError(e);} finally{busy.value=false;} }
async function loadFees(company) { feeTypes.value=company ? normalizeList(unwrapResponse(await workflowGet('fee-types',{id_perusahaan:company}))) : []; }
function editFee(row=null) { resetForm({id_perusahaan:settings.company,code:'',name:'',max_amount:'0',is_active:true,requires_approval:false,...row,edit_id:row?.id});modal.value='fee'; }
async function cancelBatch() {
  busy.value=true;error.value='';
  try{cancellationCandidates.value=normalizeList(unwrapResponse(await workflowGet('receipts'))).filter(r=>r.status==='FINALIZED');resetForm({ids:[...checkedReceipts.value],reason:''});modal.value='cancel-batch';}
  catch(e){error.value=normalizeError(e);}finally{busy.value=false;}
}
async function openMobile(row) {
  busy.value = true; error.value = '';
  try { lp.value = unwrapResponse(await mobileWorkflow('get', `lphs/${row.id}`)); resetForm({ id_faktur:'', method:'CASH', amount:'', giro_number:'', bank:'', due_date:'', cash_transfer:'0', checked:lp.value.invoices.map(i=>i.id), client_key:crypto.randomUUID() }); modal.value = 'mobile'; }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function configuration() {
  try { await masters(); if (settings.company) await loadAccounts(settings.company); }
  catch(e) { error.value = normalizeError(e); }
}
async function loadAccounts(company) {
  const sequence = ++accountsSequence;
  accounts.value = []; accountsError.value = ''; accountsLoading.value = false;
  if (!company || tab.value !== 'settings') return;
  accountsLoading.value = true;
  try {
    const response = await getCoaCatalog({ id_perusahaan: company, is_active: 'true', 'no-paginate': 'true', field: 'nomor_akun', order: 'asc' });
    if (sequence === accountsSequence) accounts.value = normalizeList(unwrapResponse(response));
  } catch(e) {
    if (sequence === accountsSequence) accountsError.value = normalizeError(e, 'Daftar COA belum bisa dimuat.');
  } finally { if (sequence === accountsSequence) accountsLoading.value = false; }
}
watch(() => settings.company, company => {
  const found = list.value.find(r => String(r.id_perusahaan) === String(company));
  settings.enabled = found?.enabled || false; settings.max_fee = String(found?.max_fee ?? 2900); settings.accounts = { ...(found?.accounts || {}) };
  loadAccounts(company);
  loadFees(company).catch(e=>{error.value=normalizeError(e);});
});
watch(() => form.id_perusahaan, () => { if (!branchOptions.value.some(b => b.value === String(form.id_cabang))) form.id_cabang = ''; });
watch(() => form.id_cabang, () => { if (modal.value === 'fund' && !salesOptions.value.some(s => s.value === String(form.id_sales))) form.id_sales = ''; });
watch(() => form.invoices, () => { quote.value = null; }, { deep:true });
watch(() => [filter.search,filter.status,filter.from,filter.to],()=>{filter.page=1;});
watch(pageCount,count=>{filter.page=Math.min(filter.page,count);});
watch(() => form.id_sales,()=>{if(modal.value==='receipt' && form.id_lph && !returnedLphs.value.some(l=>String(l.id)===String(form.id_lph))){form.id_lph='';lp.value=null;form.invoices=[];}});
watch(tab, async () => { modal.value = '';Object.assign(filter,{search:'',status:'',from:'',to:'',page:1}); await refresh(); if (['settings','fees'].includes(tab.value)) await configuration(); });
onMounted(async () => { await refresh(); if (['settings','fees'].includes(tab.value)) await configuration(); });
</script>

<template>
  <div class="space-y-5">
    <PageHeader :title="title" description="LPH → klaim sales → setoran → kuitansi → approval → jurnal. Transaksi Rekap lama tetap tersedia melalui menu legacy.">
      <button class="btn-secondary" :disabled="busy" @click="refresh">Muat ulang</button>
      <button v-if="['cash','bank-input','giro'].includes(tab) && allowed('finance.funds.create')" class="btn-primary" :disabled="busy" @click="newFund()">{{ tab === 'bank-input' ? 'Input Manual' : 'Tambah Setoran' }}</button>
      <button v-if="tab === 'bank-input' && allowed('finance.funds.create')" class="btn-secondary" :disabled="busy" @click="importBank">Import Mutasi</button>
      <button v-if="tab === 'receipts' && allowed('finance.receipts.create')" class="btn-primary" :disabled="busy" @click="newReceipt()">Buat Kuitansi</button>
      <button v-if="tab === 'receipts' && allowed('finance.receipts.create')" class="btn-secondary" :disabled="busy" @click="registerCredit">Daftarkan Credit Note</button>
      <button v-if="tab==='cancel' && allowed('finance.receipts.cancel')" class="btn-primary" :disabled="busy" @click="cancelBatch">Buat Pengajuan Pembatalan</button>
    </PageHeader>
    <p v-if="error" role="alert" class="rounded-xl bg-rose-50 p-4 text-rose-800">{{ error }}</p>
    <p v-if="success" role="status" class="rounded-xl bg-emerald-50 p-4 text-emerald-800">{{ success }}</p>
    <p v-if="busy" role="status">Memproses…</p>
    <section v-if="!['settings','fees','mobile'].includes(tab)" class="panel space-y-4 p-4">
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <label>Cari dokumen<input v-model="filter.search" class="field-control" placeholder="Nomor, sales, bank, catatan…"/></label>
        <label>Status<select v-model="filter.status" class="field-control"><option value="">Semua status</option><option v-for="status in statusOptions" :key="status" :value="status">{{ labels[status] || status }}</option></select></label>
        <label>Dari tanggal<input v-model="filter.from" type="date" class="field-control"/></label><label>Sampai tanggal<input v-model="filter.to" type="date" class="field-control"/></label>
      </div>
      <div class="flex flex-wrap gap-6 text-sm"><span>Dokumen: <b>{{ filteredList.length }}</b></span><template v-if="['cash','transfer','giro','receipts'].includes(tab)"><span>Total: <b>{{ money(listTotal) }}</b></span><span v-if="tab!=='receipts'">Belum dialokasikan: <b>{{ money(availableTotal) }}</b></span></template><template v-if="tab==='journals'"><span>Total Debit: <b>{{ money(journalTotals.debit) }}</b></span><span>Total Kredit: <b>{{ money(journalTotals.credit) }}</b></span><b>{{ Math.abs(journalTotals.debit-journalTotals.credit)<0.01 ? 'SEIMBANG' : 'ADA SELISIH' }}</b></template></div>
    </section>
    <p v-if="tab === 'transfer'" class="text-sm">Daftar dana masuk (Debit). Pencatatan dilakukan melalui menu Input / Import Mutasi Bank.</p>
    <div v-if="fundKind" class="panel overflow-x-auto p-4">
      <table class="w-full text-left text-sm"><thead><tr><th>Referensi / Bank</th><th>Tanggal / Sales</th><th>Deskripsi / Catatan</th><th>Nominal / Sisa</th><th>Status / Alokasi</th><th>Aksi</th></tr></thead><tbody>
        <tr v-for="row in pageRows" :key="row.id" class="border-t border-slate-400/20"><td class="py-4 pr-3"><b>{{ row.reference }}</b><p>{{ row.bank }}</p><p>{{ row.account_name }}</p><small>{{ labels[row.origin] }}</small></td><td class="pr-3">{{ shownDate(row.received_date) }}<p>{{ row.nama_sales || '—' }}</p><p v-if="row.due_date">Jatuh tempo: {{ shownDate(row.due_date) }}</p></td><td class="pr-3"><p>{{ row.description || '—' }}</p><p>{{ row.notes }}</p><small v-if="row.kind==='TRANSFER'">{{ labels[row.transaction_type || 'DEBIT'] }}</small></td><td class="pr-3">{{ money(row.amount) }}<p>Sisa: {{ money(row.remaining) }}</p><small v-if="Number(row.held_amount)">Ditahan draft: {{ money(row.held_amount) }}</small></td><td class="pr-3">{{ labels[row.approval] }}<p>{{ labels[row.allocation_status] }}</p><p>{{ labels[row.giro_status] }} <b v-if="row.overdue" class="text-rose-600">Lewat jatuh tempo</b></p></td><td><div class="flex flex-wrap gap-2">
          <button class="btn-secondary" :disabled="busy" @click="openFundDetail(row)">Detail & Tujuan</button>
          <button v-if="row.kind === 'CASH' && row.approval === 'PENDING' && allowed('finance.funds.approve')" class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`funds/${row.id}/approve`), 'Setoran disetujui Kasir; jurnal penerimaan tercatat.')">Approve Kasir</button>
          <button v-if="row.giro_status === 'NOT_CLEARED' && allowed('finance.giro.clear')" class="btn-primary" :disabled="busy" @click="ask(row, 'clear')">Pencairan</button>
          <button v-if="row.giro_status === 'NOT_CLEARED' && allowed('finance.giro.bounce')" class="btn-secondary" :disabled="busy" @click="ask(row, 'bounce')">Tolak Giro</button>
          <button v-if="tab !== 'transfer' && Number(row.remaining) === Number(row.amount) && allowed('finance.funds.update') && !row.id_lph && !row.id_mutasi && !['CLEARED','BOUNCED'].includes(row.giro_status)" class="btn-secondary" :disabled="busy" @click="newFund(row)">Edit</button>
          <button v-if="tab !== 'transfer' && Number(row.remaining) === Number(row.amount) && allowed('finance.funds.delete') && !row.id_lph && !row.id_mutasi && !['CLEARED','BOUNCED'].includes(row.giro_status)" class="btn-secondary" :disabled="busy" @click="ask(row,'delete')">Hapus</button>
        </div></td></tr>
      </tbody></table>
      <p v-if="!list.length && !busy" class="py-6">Belum ada setoran pada alur kuitansi ini.</p>
    </div>
    <div v-if="tab === 'receipts'" class="panel overflow-x-auto p-4"><button v-if="allowed('finance.receipts.cancel')" class="btn-secondary mb-4" :disabled="busy || !checkedReceipts.length" @click="cancelBatch">Ajukan Batal Terpilih ({{ checkedReceipts.length }})</button><table class="w-full text-left text-sm"><thead><tr><th>Pilih</th><th>No. Kuitansi</th><th>LPH</th><th>Tanggal</th><th>Nominal</th><th>Status</th><th>Aksi</th></tr></thead><tbody>
      <tr v-for="row in pageRows" :key="row.id" class="border-t border-slate-400/20"><td><input v-if="row.status==='FINALIZED' && allowed('finance.receipts.cancel')" v-model="checkedReceipts" type="checkbox" :value="row.id" :aria-label="`Pilih ${row.number}`"/></td><td class="py-4">{{ row.number }}</td><td>{{ row.kode_lph }}</td><td>{{ shownDate(row.receipt_date) }}</td><td>{{ money(row.total) }}</td><td>{{ labels[row.status] }}</td><td><div class="flex flex-wrap gap-2"><button class="btn-secondary" :disabled="busy" @click="openDetail(row)">{{ canFinalize(row) ? 'Tinjau & Finalisasi' : 'Rincian' }}</button><button v-if="row.status === 'FINALIZED' && allowed('finance.receipts.cancel')" class="btn-secondary" :disabled="busy" @click="ask(row, 'cancel')">Ajukan Batal</button><button v-if="row.status === 'CANCELLED' && allowed('finance.receipts.update') && String(row.created_by) === actorId" class="btn-secondary" :disabled="busy" @click="newReceipt(row)">Edit Ulang</button></div></td></tr>
    </tbody></table><p v-if="!list.length && !busy" class="py-6">Belum ada kuitansi. Buat LPH versi Kuitansi, minta sales menerima dan mengembalikannya, lalu catat setoran.</p></div>
    <div v-if="tab === 'cancel'" class="panel space-y-4 p-5"><article v-for="row in pageRows" :key="row.id" class="rounded-xl border border-slate-400/30 p-4"><b>{{ row.number }} · {{ labels[row.status] }}</b><p>{{ row.reason }}</p><p v-if="row.auto_giro" class="text-amber-600">Auto BG: giro ditolak bank</p><div class="mt-3 flex gap-2"><button v-if="row.status === 'DRAFT' && allowed('finance.receipts.cancel')" class="btn-primary" :disabled="busy" @click="action(() => workflowPost(`receipts/${row.id_receipt}/cancel`, { reason:row.reason }), 'Pembatalan diajukan ke supervisor.')">Ajukan ke SPV</button><template v-if="row.status === 'PENDING' && allowed('finance.receipts.cancel-approve') && String(row.created_by) !== actorId && String(row.requested_by) !== actorId"><button class="btn-primary" :disabled="busy" @click="ask(row,'cancel-approve')">Tinjau Pembatalan</button></template></div></article><p v-if="!list.length && !busy">Belum ada pengajuan pembatalan.</p></div>
    <section v-if="tab === 'settings'" class="panel space-y-4 p-5">
      <p>Pilih COA perusahaan yang sesuai. Tidak ada kode akun yang dibuat atau diasumsikan otomatis. Aktivasi berlaku untuk LPH baru yang dipilih memakai alur Kuitansi.</p>
      <AppSearchSelect v-model="settings.company" label="Perusahaan" :options="companyOptions"/>
      <p v-if="settings.company && !accountsError" class="text-sm" role="status">{{ accountsLoading ? 'Memuat akun COA…' : `${accountOptions.length} akun COA aktif tersedia. Cari berdasarkan nomor atau nama akun; gulir daftar untuk melihat hasil lainnya.` }}</p>
      <div v-if="accountsError" role="alert" class="flex items-center gap-3 text-sm text-rose-600">
        <span>{{ accountsError }}</span>
        <button type="button" class="btn-secondary" :disabled="accountsLoading" @click="loadAccounts(settings.company)">Coba lagi</button>
      </div>
      <div class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect v-for="(label, purpose) in purposes" :key="`${settings.company}-${purpose}`"
          v-model="settings.accounts[purpose]" :label="label" :options="accountOptions"
          placeholder="Cari nomor atau nama akun COA" :clear-search-on-open="true"
          :loading="accountsLoading" :disabled="!settings.company || !!accountsError"
          empty-text="Tidak ada akun COA aktif yang cocok."/>
      </div>
      <label class="block">Batas Biaya Lain per faktur (Rp)<input v-model="settings.max_fee" type="number" min="0" step="0.01" class="field-control"/></label>
      <label class="flex items-center gap-2"><input v-model="settings.enabled" type="checkbox"/>Aktifkan alur kuitansi untuk perusahaan ini</label>
      <button class="btn-primary" :disabled="busy || !settings.company || accountsLoading || !!accountsError" @click="action(() => workflowPut('settings', { id_perusahaan:settings.company,accounts:settings.accounts,enabled:settings.enabled,max_fee:settings.max_fee }), 'Pengaturan tersimpan.')">Simpan Pengaturan</button>
    </section>
    <section v-if="tab==='journals'" class="panel space-y-4 p-5">
      <article v-for="row in pageRows" :key="row.id_jurnal" class="rounded-xl border border-slate-400/30 p-4">
        <h3 class="font-bold">{{ row.reference }} · {{ row.journal_type }}</h3><p>{{ shownDate(row.tanggal) }} · {{ row.keterangan }}</p>
        <div class="overflow-x-auto"><table class="mt-3 w-full text-left text-sm"><thead><tr><th>Akun</th><th>Faktur</th><th>Sumber</th><th>Debit</th><th>Kredit</th></tr></thead><tbody><tr v-for="line in row.lines" :key="line.id_jurnal_detail"><td class="py-2 pr-3">{{ line.kode_jurnal }} {{ line.nama_akun }}</td><td class="pr-3">{{ line.no_faktur || line.workflow_invoice_id || '—' }}</td><td class="pr-3">{{ line.workflow_source || '—' }}</td><td class="pr-3">{{ money(line.debit) }}</td><td>{{ money(line.kredit) }}</td></tr></tbody><tfoot><tr class="border-t border-slate-400/30 font-bold"><td colspan="3" class="py-2">TOTAL</td><td>{{ money(row.lines.reduce((n,l)=>n+Number(l.debit || 0),0)) }}</td><td>{{ money(row.lines.reduce((n,l)=>n+Number(l.kredit || 0),0)) }}</td></tr></tfoot></table></div>
      </article><p v-if="!list.length && !busy">Belum ada jurnal workflow.</p>
    </section>
    <section v-if="['settings','fees'].includes(tab)" class="panel space-y-4 p-5">
      <h3 class="text-lg font-semibold">Master Jenis Biaya Lain</h3>
      <AppSearchSelect v-if="tab==='fees'" v-model="settings.company" label="Perusahaan" :options="companyOptions"/>
      <p class="text-sm">Batas berlaku per jenis per faktur, termasuk jika jenis yang sama diisi pada beberapa baris. Diskon pelunasan khusus tidak dapat dipakai pada kuitansi biasa.</p>
      <button v-if="feeManage" class="btn-primary" :disabled="busy || !settings.company" @click="editFee()">Tambah Jenis Biaya</button>
      <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Jenis Biaya</th><th>Batas / Faktur</th><th>Status</th><th>Aksi</th></tr></thead><tbody><tr v-for="fee in feeTypes" :key="fee.id" class="border-t border-slate-400/30"><td class="py-3">{{ fee.name }}</td><td>{{ money(fee.max_amount) }}</td><td>{{ fee.is_active ? 'Aktif' : 'Nonaktif' }}{{ fee.requires_approval ? ' · Persetujuan khusus' : '' }}</td><td><button v-if="feeManage" class="btn-secondary" :disabled="busy" @click="editFee(fee)">Edit</button></td></tr></tbody></table></div>
    </section>
    <nav v-if="!['settings','fees','mobile'].includes(tab)" aria-label="Halaman workflow" class="flex items-center justify-between gap-3"><button class="btn-secondary" :disabled="filter.page<=1 || busy" @click="filter.page--">Sebelumnya</button><span>Halaman {{ filter.page }} / {{ pageCount }} · {{ filteredList.length }} dokumen</span><button class="btn-secondary" :disabled="filter.page>=pageCount || busy" @click="filter.page++">Berikutnya</button></nav>
    <section v-if="tab === 'mobile'" class="panel space-y-4 p-5"><p>LPH milik akun Sales yang login. Klaim tidak mengurangi piutang sebelum Finance memfinalisasi kuitansi.</p><button v-for="row in list" :key="row.id" class="block w-full rounded-xl border border-slate-400/30 p-4 text-left" :disabled="busy" @click="openMobile(row)">{{ row.kode_lph }} · {{ row.status_dokumen }}</button><p v-if="!list.length && !busy">Belum ada LPH versi Kuitansi untuk sales ini.</p></section>

    <AppModal :open="modal==='fee'" title="Jenis Biaya Lain" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <form class="space-y-4" @submit.prevent="action(()=>form.edit_id ? workflowPut(`fee-types/${form.edit_id}`,{...form}) : workflowPost('fee-types',{...form}),'Master biaya tersimpan.')"><fieldset :disabled="busy" class="space-y-4"><label class="block">Nama Jenis Biaya<input v-model="form.name" required maxlength="160" class="field-control"/></label><label class="block">Batas Nominal per Faktur<input v-model="form.max_amount" type="number" min="0" step="0.01" required class="field-control"/></label><label class="flex gap-2"><input v-model="form.is_active" type="checkbox"/>Aktif</label><label class="flex gap-2"><input v-model="form.requires_approval" type="checkbox"/>Persetujuan khusus (tidak dapat dipilih pada kuitansi biasa)</label><button class="btn-primary">Simpan Jenis Biaya</button></fieldset></form><p v-if="error" role="alert" class="mt-3 text-rose-600">{{ error }}</p>
    </AppModal>
    <AppModal :open="modal==='cancel-batch'" title="Pengajuan Pembatalan Kuitansi" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <div class="space-y-4"><p>Pilih beberapa kuitansi Finalized. Setiap kuitansi tetap memerlukan keputusan Supervisor; pengajuan ini belum mengubah piutang.</p><div class="max-h-80 overflow-auto"><label v-for="r in cancellationCandidates" :key="r.id" class="flex gap-3 border-b border-slate-400/30 p-3"><input v-model="form.ids" type="checkbox" :value="r.id" :aria-label="`Batalkan ${r.number}`"/><span><b>{{ r.number }}</b> · {{ r.kode_lph }} · {{ money(r.total) }}</span></label></div><label class="block">Alasan Pembatalan<textarea v-model="form.reason" maxlength="2000" class="field-control"/></label><button class="btn-primary" :disabled="busy || !form.ids?.length || form.ids.length>500 || !form.reason?.trim()" @click="action(()=>workflowPost('receipts/cancel-batch',{ids:form.ids,reason:form.reason}),'Pengajuan pembatalan terpilih dikirim ke Supervisor.')">Ajukan {{ form.ids?.length || 0 }} Kuitansi</button><p v-if="error" role="alert" class="text-rose-600">{{ error }}</p></div>
    </AppModal>
    <AppModal :open="modal==='fund-detail'" title="Detail Setoran & Tujuan Alokasi" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <div v-if="detail" class="space-y-4"><h3 class="font-semibold">{{ detail.reference }} · {{ labels[detail.kind] }} · {{ money(detail.amount) }}</h3><p>{{ detail.bank }} · {{ detail.account_name }} · Diterima {{ shownDate(detail.received_date) }}</p><p v-if="detail.due_date">Jatuh tempo {{ shownDate(detail.due_date) }} · {{ labels[detail.giro_status] }}</p><p>{{ detail.description }}</p><p>Catatan: {{ detail.notes || '—' }}</p><p>Sisa tersedia: <b>{{ money(detail.remaining) }}</b></p><h4 class="font-semibold">Tujuan Alokasi</h4><div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Kuitansi</th><th>Faktur / Customer</th><th>Nominal</th><th>Status</th></tr></thead><tbody><tr v-for="a in detail.allocations" :key="a.id" class="border-t border-slate-400/30"><td class="py-3">{{ a.number }}</td><td>{{ a.no_faktur }} · {{ a.nama_customer }}</td><td>{{ money(a.amount) }}</td><td>{{ labels[a.status] }}</td></tr></tbody></table></div><p v-if="!detail.allocations?.length">Belum ada alokasi kuitansi.</p><p v-for="c in detail.clearings" :key="c.id">Kliring {{ c.reference }} · {{ money(c.amount) }} · Giro #{{ c.id_source }}</p><h4 class="font-semibold">Riwayat / Audit</h4><p v-for="a in detail.audit" :key="a.id">{{ a.action }} · {{ a.nama }} · {{ shownDate(a.created_at) }} · {{ a.note }}</p></div><p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
    </AppModal>
    <AppModal :open="modal==='fund'" :title="form.edit_id ? 'Edit Setoran' : 'Tambah Setoran'" size="xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <form @submit.prevent="action(() => form.edit_id ? workflowPut(`funds/${form.edit_id}`,{...form}) : workflowPost('funds',{...form}), 'Setoran tersimpan.')">
        <fieldset :disabled="busy" class="grid gap-4 md:grid-cols-2">
          <AppSearchSelect v-model="form.id_perusahaan" label="Perusahaan" :options="companyOptions" :disabled="!!form.edit_id"/>
          <AppSearchSelect v-model="form.id_cabang" label="Cabang" :options="branchOptions" :disabled="!!form.edit_id"/>
          <AppSearchSelect v-model="form.id_sales" label="Sales Penyerah" :options="salesOptions" :clear-search-on-open="true"/>
          <label>Nomor referensi / BG<input v-model="form.reference" :required="form.kind==='GIRO'" maxlength="160" class="field-control" :placeholder="form.kind==='GIRO' ? 'Nomor giro wajib' : 'Opsional, otomatis jika kosong'"/></label>
          <label>Tanggal Penerimaan<input v-model="form.received_date" type="date" required class="field-control"/></label>
          <label>Nominal (Rp)<input v-model="form.amount" type="number" min="0.01" step="0.01" required class="field-control"/></label>
          <label v-if="form.kind!=='CASH'">Bank<input v-model="form.bank" required maxlength="160" class="field-control"/></label>
          <label v-if="form.kind==='TRANSFER'">Tipe Mutasi<select v-model="form.transaction_type" class="field-control"><option value="DEBIT">Debit / dana masuk</option><option value="CREDIT">Kredit / dana keluar</option></select></label>
          <template v-if="form.kind==='GIRO'"><label>Nama Rekening BG<input v-model="form.account_name" class="field-control"/></label><label>Jatuh Tempo Giro<input v-model="form.due_date" type="date" required class="field-control"/></label></template>
          <label class="md:col-span-2">Deskripsi<textarea v-model="form.description" :required="form.kind==='TRANSFER'" maxlength="2000" class="field-control"/></label>
          <label class="md:col-span-2">Catatan Tambahan<textarea v-model="form.notes" maxlength="2000" class="field-control"/></label>
        </fieldset>
        <p class="mt-4 text-sm">Tunai menunggu approval Kasir. Setoran berdiri sendiri sampai dialokasikan ke faktur. Mutasi dana keluar tidak dapat dipakai untuk pembayaran.</p>
        <button class="btn-primary mt-4" :disabled="busy || !form.id_perusahaan || !form.id_cabang || (['CASH','GIRO'].includes(form.kind) && !form.id_sales)">Simpan Setoran</button>
      </form><p v-if="error" role="alert" class="mt-3 text-rose-600">{{ error }}</p>
    </AppModal>
    <ReceiptEditor :open="modal==='receipt'" :busy="busy" :form="form" :lp="lp" :funds="funds" :fee-types="feeTypes" :lphs="returnedLphs" :sales="receiptSales" :quote="quote" :error="error" @close="modal=''" @select-lph="selectLph" @preview="preview" @save="action(() => form.edit_id ? workflowPut(`receipts/${form.edit_id}`,payload()) : workflowPost('receipts',payload()), 'Kuitansi Draft tersimpan; sumber dana ditahan sampai finalisasi/pembatalan.')"/>
    <AppModal :open="modal==='detail'" title="Tinjau Kuitansi & Rekonsiliasi" size="6xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <div v-if="detail" class="space-y-5">
        <h3 class="text-lg font-bold">{{ detail.number }} · {{ labels[detail.status] }}</h3>
        <ReceiptReconciliation :value="detail.reconciliation"/>
        <article v-for="invoice in detail.invoices" :key="invoice.id" class="rounded-xl border border-slate-400/30 p-3">
          <b>{{ invoice.no_faktur }} · {{ invoice.nama_customer }}</b><p>Alokasi {{ money(invoice.paid) }} · Kelebihan {{ money(invoice.excess) }}</p>
          <p v-for="a in detail.allocations.filter(a=>a.id_faktur===invoice.id_faktur)" :key="a.id">{{ labels[a.kind] || 'Biaya Lain' }} {{ a.reference || a.fee_name }}: {{ money(a.amount) }}</p>
        </article>
        <h4 class="font-semibold">Riwayat / Audit</h4><p v-for="a in detail.audit" :key="a.id" class="text-sm">{{ a.action }} · {{ a.nama }} · {{ shownDate(a.created_at) }}</p>
        <button v-if="canFinalize(detail)" class="btn-primary" :disabled="busy" @click="ask(detail,'finalize')">Konfirmasi Rekonsiliasi & Finalisasi</button>
        <p v-else-if="detail.status==='DRAFT'">Menunggu persetujuan petugas yang memiliki hak Approve Pembayaran Tagihan — Kuitansi.</p>
        <button v-if="detail.status==='DRAFT' && String(detail.created_by)===actorId && allowed('finance.receipts.delete')" class="btn-secondary" :disabled="busy" @click="ask(detail,'discard')">Tarik Draft untuk Koreksi</button>
      </div><p v-if="error" role="alert" class="mt-3 text-rose-600">{{ error }}</p>
    </AppModal>
    <AppModal :open="['clear','bounce','cancel','cancel-approve','finalize','delete','import','credit','discard'].includes(modal)" :title="{clear:'Pencairan Giro',bounce:'Penolakan Giro',cancel:'Ajukan Pembatalan','cancel-approve':'Keputusan SPV',finalize:'Konfirmasi Finalisasi',delete:'Hapus Setoran',import:'Import Mutasi Dana Masuk',credit:'Daftarkan Credit Note',discard:'Tarik Draft untuk Koreksi'}[modal] || ''" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal=''">
      <div class="space-y-4">
        <p v-if="detail">{{ detail.number || detail.reference }} · {{ money(detail.amount || detail.total) }}</p>
        <template v-if="modal==='discard'">
          <p>Draft belum mengurangi piutang atau memposting jurnal pembayaran. Penarikan melepas dana yang ditahan. Setelah itu gunakan Edit Ulang untuk memperbaiki alokasi dan menghitung ulang rekonsiliasi; riwayat tetap disimpan.</p>
          <label class="block">Alasan koreksi<textarea v-model="form.reason" maxlength="2000" class="field-control"/></label>
          <button class="btn-primary" :disabled="busy || !form.reason.trim()" @click="action(()=>workflowPost(`receipts/${detail.id}/discard`,{reason:form.reason}),'Draft ditarik. Gunakan Edit Ulang untuk rekonsiliasi baru.')">Konfirmasi Penarikan Draft</button>
        </template>
        <template v-if="modal==='clear'">
          <AppSearchSelect v-model="form.id_payment_source" label="Setoran Non Tunai Pencairan" :options="clearingCandidates.map(f=>({value:String(f.id),label:`${f.reference} · ${f.bank} · ${money(f.amount)} · ${labels[f.origin] || 'Manual'}`}))" placeholder="Pilih setoran nominal cocok"/>
          <p class="text-sm">Pilihan mencakup setoran manual dan hasil import yang belum dipakai/ditahan. Bank tidak dibukukan dua kali.</p>
          <label class="block">Referensi Kliring Bank<input v-model="form.clearing_reference" class="field-control"/></label>
          <label class="flex items-center gap-2"><input v-model="form.manual_clearing" type="checkbox"/>Pencairan belum dicatat sebagai setoran non tunai; bukukan dari referensi bank di atas.</label>
          <p v-if="!clearingCandidates.length" class="text-amber-700">Belum ada setoran non tunai dengan nominal persis sama. Input/import setoran terlebih dahulu, atau konfirmasi pencairan manual.</p>
          <button class="btn-primary" :disabled="busy || (!form.id_payment_source && !form.manual_clearing) || !form.clearing_reference" @click="action(()=>workflowPost(`giro/${detail.id}/clear`,{id_payment_source:form.id_payment_source || null,clearing_reference:form.clearing_reference}), 'Giro cair; jurnal pencairan tercatat.')">Konfirmasi Pencairan</button>
        </template>
        <template v-if="['bounce','cancel'].includes(modal)">
          <label class="block">Alasan wajib<textarea v-model="form.reason" maxlength="2000" class="field-control"/></label>
          <button class="btn-primary" :disabled="busy || !form.reason.trim()" @click="action(()=>workflowPost(modal==='bounce' ? `giro/${detail.id}/bounce` : `receipts/${detail.id}/cancel`,{reason:form.reason}),modal==='bounce' ? 'Giro ditolak; kuitansi terkait masuk tindak lanjut pembatalan.' : 'Pembatalan diajukan.')">Kirim</button>
        </template>
        <template v-if="modal==='cancel-approve'">
          <label class="block">Catatan keputusan<textarea v-model="form.note" maxlength="2000" class="field-control"/></label>
          <p>Persetujuan membalik jurnal, membuka piutang, dan melepaskan sumber dana. Uang muka hasil kuitansi yang sudah dipakai akan mengunci pembatalan.</p>
          <div class="flex gap-2"><button class="btn-primary" :disabled="busy" @click="action(()=>workflowPost(`cancellations/${detail.id}/decision`,{decision:'APPROVED',note:form.note}),'Pembatalan disetujui; jurnal reversal tercatat.')">Setujui Pembatalan</button><button class="btn-secondary" :disabled="busy" @click="action(()=>workflowPost(`cancellations/${detail.id}/decision`,{decision:'REJECTED',note:form.note}),'Pembatalan ditolak; kuitansi tetap final.')">Tolak Pembatalan</button></div>
        </template>
        <template v-if="modal==='finalize'">
          <ReceiptReconciliation :value="detail.reconciliation"/>
          <label class="flex items-start gap-3"><input v-model="form.reconciliation_checked" type="checkbox" class="mt-1"/>Saya telah memeriksa sumber dana, klaim Sales, piutang sebelum/sesudah, dan seluruh selisih per faktur. Finalisasi akan mengurangi piutang serta memposting jurnal.</label>
          <button class="btn-primary" :disabled="busy || !form.reconciliation_checked" @click="action(()=>workflowPost(`receipts/${detail.id}/finalize`,{confirm_reconciliation:true}),'Kuitansi difinalisasi; piutang dan jurnal diperbarui.')">Setujui & Finalisasi</button>
        </template>
        <template v-if="modal==='delete'"><p>Hapus hanya diperbolehkan jika setoran belum pernah dialokasikan. Jurnal penerimaan yang sudah tercatat dibalik dengan jurnal koreksi.</p><button class="btn-primary" :disabled="busy" @click="action(()=>workflowDelete(`funds/${detail.id}`),'Setoran dihapus dengan audit koreksi.')">Konfirmasi Hapus</button></template>
        <template v-if="modal==='import'">
          <p>Pilih beberapa mutasi dana masuk. Seluruh pilihan diproses dalam satu transaksi; jika satu gagal, tidak ada yang diimpor.</p>
          <label class="flex gap-2"><input type="checkbox" :checked="form.ids?.length===mutations.length && !!mutations.length" @change="form.ids=$event.target.checked ? mutations.slice(0,500).map(m=>m.id_mutasi) : []"/>Pilih Semua (maks. 500)</label>
          <div class="max-h-80 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th>Pilih</th><th>Tanggal</th><th>Referensi</th><th>Deskripsi</th><th>Nominal</th></tr></thead><tbody><tr v-for="m in mutations" :key="m.id_mutasi" class="border-t border-slate-400/30"><td class="p-2"><input v-model="form.ids" type="checkbox" :value="m.id_mutasi" :aria-label="`Pilih mutasi ${m.kode_mutasi}`"/></td><td>{{ shownDate(m.tanggal_mutasi) }}</td><td>{{ m.kode_mutasi }}</td><td>{{ m.keterangan || m.deskripsi || '—' }}</td><td>{{ money(m.nominal_mutasi) }}</td></tr></tbody></table></div>
          <button class="btn-primary" :disabled="busy || !form.ids?.length || form.ids.length>500" @click="action(()=>workflowPost('mutations/import',{ids:form.ids}),'Mutasi terpilih berhasil diimpor.')">Import {{ form.ids?.length || 0 }} Mutasi</button>
        </template>
        <template v-if="modal==='credit'"><AppSearchSelect v-model="form.id_credit_note" label="Credit Note belum dipakai" :options="credits.map(c=>({value:String(c.id_cn),label:`${c.kode_cn} — ${money(c.total_cn)}`}))"/><button class="btn-primary" :disabled="busy || !form.id_credit_note" @click="action(()=>workflowPost(`credit-notes/${form.id_credit_note}/reserve`),'Credit Note dicadangkan sebagai sumber retur.')">Daftarkan</button></template>
        <p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
      </div>
    </AppModal>
    <AppModal :open="modal === 'mobile'" title="LPH Sales" size="4xl" :hide-close="busy" :close-on-backdrop="!busy" @close="modal = ''">
      <div v-if="lp" class="space-y-4">
        <h3 class="font-bold">{{ lp.kode_lph }} · {{ lp.status_dokumen }}</h3>
        <label v-for="i in lp.invoices" :key="i.id" class="block"><input v-if="lp.status_dokumen === 'MENUNGGU_PENERIMAAN'" v-model="form.checked" type="checkbox" :value="i.id"/> {{ i.no_faktur }} {{ i.nama_customer }} — {{ money(i.remaining) }}</label>
        <button v-if="lp.status_dokumen === 'MENUNGGU_PENERIMAAN'" class="btn-primary" :disabled="busy || form.checked.length !== lp.invoices.length" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/accept`,{checked_detail_ids:lp.checked_details.filter(d => form.checked.includes(d.id_faktur)).map(d => d.id)}),'LPH diterima sales.')">Terima LPH</button>
        <section class="grid grid-cols-2 gap-3 md:grid-cols-4" aria-label="Ringkasan penagihan Sales">
          <div v-for="(label,key) in {total:'Total Klaim',CASH:'Tunai',TRANSFER:'Transfer',GIRO:'Giro'}" :key="key" class="rounded-xl border border-slate-400/30 p-3"><p>{{ label }}</p><b>{{ money(collectionSummary[key]) }}</b></div>
        </section>
        <template v-if="lp.status_dokumen === 'AKTIF'">
          <label>Faktur<select v-model="form.id_faktur" class="field-control"><option value="">Pilih faktur</option><option v-for="i in lp.invoices" :key="i.id" :value="i.id">{{ i.no_faktur }}</option></select></label>
          <label>Metode<select v-model="form.method" class="field-control"><option value="CASH">Cash</option><option value="TRANSFER">Transfer</option><option value="GIRO">Giro</option></select></label>
          <label>Nominal klaim<input v-model="form.amount" type="number" min="0.01" step="0.01" class="field-control"/></label>
          <div v-if="form.method === 'GIRO'" class="grid gap-3 md:grid-cols-3"><label>No. BG<input v-model="form.giro_number" class="field-control"/></label><label>Bank<input v-model="form.bank" class="field-control"/></label><label>Jatuh tempo<input v-model="form.due_date" type="date" class="field-control"/></label></div>
          <button class="btn-primary" :disabled="busy" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/claims`,{...form}), 'Klaim dicatat, belum dianggap uang masuk.')">Catat Klaim</button>
        </template>
        <article v-for="c in lp.claims" :key="c.id" class="rounded-xl border border-slate-400/30 p-3">Faktur {{ c.id_faktur }} · {{ labels[c.method] }} · {{ money(c.amount) }}<button v-if="lp.status_dokumen === 'AKTIF'" class="btn-secondary ml-3" :disabled="busy" @click="action(() => mobileWorkflow('delete',`claims/${c.id}`),'Klaim dihapus.')">Hapus Klaim</button></article>
        <div v-if="lp.status_dokumen === 'AKTIF'" class="border-t border-slate-400/30 pt-4">
          <label>Cash yang ditransfer<input v-model="form.cash_transfer" type="number" min="0" :max="collectionSummary.CASH" step="0.01" class="field-control"/></label>
          <p>Sisa cash setor Kasir: {{ money(collectionSummary.CASH - Number(form.cash_transfer || 0)) }}</p>
          <button class="btn-primary mt-3" :disabled="busy || Number(form.cash_transfer)<0 || Number(form.cash_transfer)>collectionSummary.CASH" @click="action(() => mobileWorkflow('post',`lphs/${lp.id}/return`,{cash_transfer:form.cash_transfer}),'LPH dikembalikan; sisa cash menjadi setoran Pending Kasir.')">Kembalikan LPH</button>
        </div>
        <p v-if="error" role="alert" class="text-rose-600">{{ error }}</p>
      </div>
    </AppModal>
  </div>
</template>
<style scoped>
.btn-secondary { color:inherit; }
button:disabled { opacity:.5; cursor:not-allowed; }
</style>
