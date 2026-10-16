<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { principalClaims as api, claimStatus, claimMethod, rupiah } from '@/api/principalClaims';
import { getCompanies, getBranches, getPrincipals } from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import PageHeader from '@/shared/components/PageHeader.vue';
import PrincipalClaimDetail from '../components/PrincipalClaimDetail.vue';
import PrincipalClaimFulfilment from '../components/PrincipalClaimFulfilment.vue';
import PrincipalReturnForm from '../components/PrincipalReturnForm.vue';
import PrincipalReturnDispatch from '../components/PrincipalReturnDispatch.vue';

const route = useRoute(), auth = useAuthStore();
const accountsMode = computed(() => route.name === 'principal-accounts');
const returnsMode = computed(() => route.name === 'principal-returns');
const showReturnForm=ref(false);
const can = (action) => auth.hasPermission(`purchase.principal-${accountsMode.value ? 'accounts' : 'claims'}.${action}`) || auth.hasPermission(`m.purchase.${accountsMode.value ? 'apr' : 'kpr'}.${action}`);
const rows = ref([]), companies = ref([]), branches = ref([]), principals = ref([]), candidates = ref([]), selectedIds = ref([]), detail = ref(null);
const busy = ref(false), error = ref(''), success = ref(''), page = ref(1), total = ref(0), status = ref(''), showForm = ref(false), truncated = ref(false);
const filters = reactive({ id_perusahaan: '', id_cabang: '', id_principal: '', from: '', to: '' });
const proposal = reactive({ requested_method: 'CREDIT', note: '' });
const account = reactive({ id: null, id_perusahaan: '', id_principal: '', login: '', display_name: '', password: '', active: true });
const selectedTotal = computed(() => candidates.value.filter(r => selectedIds.value.includes(r.id)).reduce((n, r) => n + Number(r.nominal || 0), 0));
let clientKey = null;
async function run(fn) { if (busy.value) return; busy.value = true; error.value = ''; success.value = ''; try { await fn(); } catch (e) { error.value = normalizeError(e); } finally { busy.value = false; } }
async function load() {
  if (accountsMode.value) { rows.value = await api.accounts(); total.value = rows.value.length; }
  else { const result = await api.list({ page: page.value, status: status.value, kind: returnsMode.value ? 'RETURNS' : undefined }); rows.value = result.rows; total.value = result.total; }
}
async function masters() { const values = await Promise.all([getCompanies(), getBranches(), getPrincipals()]); [companies.value, branches.value, principals.value] = values.map(v => normalizeList(unwrapResponse(v))); }
function newForm() { run(async () => { await masters(); detail.value = null; showForm.value = true; candidates.value = []; selectedIds.value = []; Object.assign(account, { id: null, id_perusahaan: '', id_principal: '', login: '', display_name: '', password: '', active: true }); }); }
function editAccount(row) { run(async () => { await masters(); Object.assign(account, { id: row.id, id_perusahaan: row.id_perusahaan, id_principal: row.id_principal, login: row.login, display_name: row.display_name, password: '', active: row.active }); showForm.value = true; }); }
function saveAccount() { run(async () => { await api.saveAccount({ ...account }, account.id); account.password = ''; showForm.value = false; await load(); success.value = 'Akun principal tersimpan. Sampaikan kredensial melalui saluran aman.'; }); }
function findSources() { run(async () => { const result = await api.candidates(filters); candidates.value = result.rows; truncated.value = result.truncated; selectedIds.value = []; }); }
function submit() { run(async () => { if (!clientKey) clientKey = crypto.randomUUID(); detail.value = await api.submit({ ...filters, ...proposal, usage_ids: selectedIds.value, client_key: clientKey }); showForm.value = false; candidates.value = []; selectedIds.value = []; clientKey = null; await load(); success.value = 'Klaim diajukan. Principal dapat meninjau melalui portal.'; }); }
function open(id) { run(async () => { detail.value = await api.detail(id); proposal.note = detail.value.note; proposal.requested_method = detail.value.requested_method; showForm.value = false; }); }
async function returnSaved(result){showReturnForm.value=false;detail.value=result;await load();success.value='Pengajuan dikirim ke portal principal. Stok belum berkurang.';}
function resubmit() { run(async () => { detail.value = await api.resubmit(detail.value.id, { ...proposal, revision: detail.value.revision }); await load(); success.value = 'Revisi diajukan kembali.'; }); }
watch([() => JSON.stringify(filters), () => JSON.stringify(proposal), () => JSON.stringify(selectedIds.value)], () => { clientKey = null; });
watch(() => JSON.stringify(filters), () => { candidates.value = []; selectedIds.value = []; });
watch([accountsMode,returnsMode], () => { rows.value = []; detail.value = null; showForm.value = false; showReturnForm.value=false; page.value = 1; run(load); });
onMounted(() => run(load));
</script>

<template>
  <div class="claim-page space-y-5 workflow-ui">
    <PageHeader :title="accountsMode ? 'Akun Portal Principal' : returnsMode ? 'Retur PO & Pemusnahan' : 'Klaim Principal'" :description="accountsMode ? 'Akses terpisah, dibatasi per principal dan perusahaan.' : returnsMode ? 'Ajukan berdasarkan penerimaan PO dan lot stok. Mutasi dicatat setelah persetujuan principal.' : 'Ajukan pemakaian Promo All-In yang sudah terpakai dan belum pernah diklaim.'"><button class="workflow-btn" :disabled="busy" @click="run(load)">Muat ulang</button><button v-if="can('create') && !returnsMode" :disabled="busy" class="primary workflow-btn workflow-btn-primary" @click="newForm">{{ accountsMode ? 'Buat akun' : 'Ajukan klaim promo' }}</button><button v-if="can('create') && returnsMode" :disabled="busy" class="primary workflow-btn workflow-btn-primary" @click="showReturnForm=true;showForm=false;detail=null">Ajukan Retur / Pemusnahan</button></PageHeader>
    <PrincipalReturnForm v-if="showReturnForm" @close="showReturnForm=false" @saved="returnSaved" />
    <p class="text-sm">Portal principal: <a class="underline workflow-link" href="/principal-portal" target="_blank" rel="noopener">Buka halaman login principal</a></p>
    <p v-if="error" role="alert" class="rounded-xl border border-red-500 p-4 workflow-notice workflow-notice-error">{{ error }}</p><p v-if="success" role="status" class="rounded-xl border border-emerald-500 p-4 workflow-notice workflow-notice-success">{{ success }}</p>
    <section v-if="showForm" class="panel space-y-5 workflow-card">
      <div class="flex justify-between flex-wrap items-center gap-3"><h2 class="text-xl font-semibold">{{ accountsMode ? 'Pengaturan akun principal' : 'Sumber pengajuan promo' }}</h2><button class="workflow-btn" :disabled="busy" @click="showForm = false">Tutup</button></div>
      <form v-if="accountsMode" class="space-y-4" @submit.prevent="saveAccount"><div class="grid gap-4 md:grid-cols-2">
        <label class="workflow-label">Perusahaan<AppSelect2 aria-label="Perusahaan"  v-model.number="account.id_perusahaan" :disabled="!!account.id" required><option value="">Pilih perusahaan</option><option v-for="c in companies" :key="c.id" :value="c.id">{{ c.nama }}</option></AppSelect2></label>
        <label class="workflow-label">Principal<AppSelect2 aria-label="Principal"  v-model.number="account.id_principal" :disabled="!!account.id" required><option value="">Pilih principal</option><option v-for="p in principals" :key="p.id" :value="p.id">{{ p.nama }}</option></AppSelect2></label>
        <label class="workflow-label">Username / email<input class="workflow-input" v-model="account.login" required minlength="3" maxlength="120" autocomplete="off"></label><label class="workflow-label">Nama penanggung jawab<input class="workflow-input" v-model="account.display_name" required maxlength="120"></label>
        <label class="workflow-label">{{ account.id ? 'Password baru (kosongkan jika tetap)' : 'Password awal' }}<input class="workflow-input" v-model="account.password" type="password" :required="!account.id" minlength="12" maxlength="128" autocomplete="new-password"></label>
        <label class="flex items-center gap-3"><input class="h-4 w-4 accent-brand-600 shrink-0" v-model="account.active" type="checkbox">Akun aktif</label>
      </div><p class="text-sm">Perubahan akun akan mengakhiri sesi portal yang masih aktif. Hak akun hanya berlaku untuk principal/perusahaan di atas.</p><button class="primary workflow-btn workflow-btn-primary" :disabled="busy">Simpan akun</button></form>
      <template v-else>
        <form class="space-y-4" @submit.prevent="findSources"><div class="grid gap-4 md:grid-cols-3">
          <label class="workflow-label">Perusahaan<AppSelect2 aria-label="Perusahaan"  v-model.number="filters.id_perusahaan" required><option value="">Pilih perusahaan</option><option v-for="c in companies" :key="c.id" :value="c.id">{{ c.nama }}</option></AppSelect2></label>
          <label class="workflow-label">Cabang<AppSelect2 aria-label="Cabang"  v-model.number="filters.id_cabang" required><option value="">Pilih cabang</option><option v-for="c in branches" :key="c.id" :value="c.id">{{ c.nama }}</option></AppSelect2></label>
          <label class="workflow-label">Principal<AppSelect2 aria-label="Principal"  v-model.number="filters.id_principal" required><option value="">Pilih principal</option><option v-for="p in principals" :key="p.id" :value="p.id">{{ p.nama }}</option></AppSelect2></label>
          <label class="workflow-label">Pemakaian dari<input class="workflow-input" v-model="filters.from" type="date" required></label><label class="workflow-label">Sampai<input class="workflow-input" v-model="filters.to" type="date" required></label>
        </div><button class="workflow-btn" :disabled="busy">Muat pemakaian promo</button></form>
        <p class="text-sm">Sumber dihitung per pemakaian, bukan budget promo. Faktur beretur atau transaksi belum selesai ditahan untuk pemeriksaan; klaim lama dikecualikan.</p>
        <p v-if="truncated" class="text-amber-500">Hanya 1.000 sumber pertama ditampilkan. Persempit periode sebelum melanjutkan.</p>
        <div class="overflow-x-auto workflow-table-wrap"><table class="workflow-table"><thead><tr><th>Pilih</th><th>Promo / Faktur</th><th>Pemakaian</th><th>Keterangan</th></tr></thead><tbody><tr v-for="r in candidates" :key="r.id"><td><input class="h-4 w-4 accent-brand-600 shrink-0" v-model="selectedIds" type="checkbox" :value="r.id" :disabled="!r.eligible || busy" :aria-label="`Pilih ${r.kode_promo} ${r.no_faktur}`"></td><td>{{ r.kode_promo }}<br>{{ r.no_faktur }}</td><td>{{ rupiah(r.nominal) }}</td><td>{{ r.hold_reason || 'Siap diajukan' }}</td></tr><tr v-if="!candidates.length"><td colspan="4">Belum ada sumber yang ditampilkan.</td></tr></tbody></table></div>
        <form v-if="candidates.length" class="space-y-4" @submit.prevent="submit"><p class="font-semibold">{{ selectedIds.length }} pemakaian dipilih · {{ rupiah(selectedTotal) }}</p><label class="workflow-label">Penyelesaian yang diminta<AppSelect2 aria-label="Penyelesaian yang diminta"  v-model="proposal.requested_method"><option v-for="(label,key) in claimMethod" :key="key" :value="key">{{label}}</option></AppSelect2></label><label class="workflow-label">Catatan<textarea class="workflow-input" v-model="proposal.note" maxlength="2000" rows="3" /></label><button :disabled="busy || !selectedIds.length" class="primary workflow-btn workflow-btn-primary">Ajukan ke principal</button></form>
      </template>
    </section>
    <label v-if="!accountsMode" class="max-w-xs workflow-label">Status<AppSelect2 aria-label="Status"  v-model="status" :disabled="busy" @change="page = 1; run(load)"><option value="">Semua status</option><option v-for="(label, key) in claimStatus" :key="key" :value="key">{{ label }}</option></AppSelect2></label>
    <div class="panel overflow-x-auto workflow-table-wrap"><table class="workflow-table" v-if="accountsMode"><thead><tr><th>Login</th><th>Principal / Perusahaan</th><th>Status</th><th></th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td>{{ r.login }}<br><small>{{ r.display_name }}</small></td><td>{{ r.principal_name }}<br>{{ r.company_name }}</td><td>{{ r.active ? 'Aktif' : 'Nonaktif' }}</td><td><button class="workflow-btn" v-if="can('update')" :disabled="busy" @click="editAccount(r)">Edit</button></td></tr><tr v-if="!rows.length"><td colspan="4">Belum ada akun.</td></tr></tbody></table><table class="workflow-table" v-else><thead><tr><th>Klaim / Principal</th><th>Diajukan</th><th>Disetujui</th><th>Status</th><th></th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td>{{ r.number }}<br><small>{{ r.principal_name }}</small></td><td>{{ rupiah(r.requested_amount) }}<br><small>{{ claimMethod[r.requested_method] }}</small></td><td>{{ rupiah(r.approved_amount) }}</td><td>{{ claimStatus[r.status] }}</td><td><button class="workflow-btn" :disabled="busy" @click="open(r.id)">Detail</button></td></tr><tr v-if="!rows.length"><td colspan="5">{{ busy ? 'Memuat…' : 'Belum ada klaim pada filter ini.' }}</td></tr></tbody></table></div>
    <div v-if="!accountsMode" class="flex justify-between flex-wrap items-center gap-3"><button class="workflow-btn" :disabled="busy || page <= 1" @click="page--; run(load)">Sebelumnya</button><span>Halaman {{ page }} · {{ total }} klaim</span><button class="workflow-btn" :disabled="busy || page * 50 >= total" @click="page++; run(load)">Berikutnya</button></div>
    <section v-if="detail" class="panel space-y-5 workflow-card"><div class="flex justify-between flex-wrap items-center gap-3"><h2 class="text-xl font-semibold">{{ detail.number }}</h2><button class="workflow-btn" @click="detail = null">Tutup</button></div><PrincipalClaimDetail :claim="detail" show-payables /><PrincipalReturnDispatch v-if="['RETURN','DESTRUCTION'].includes(detail.kind)" :claim="detail" @updated="open(detail.id)" /><PrincipalClaimFulfilment v-if="['GOODS','TRANSFER'].includes(detail.approved_method)" :claim="detail" @updated="open(detail.id)" /><form v-if="detail.status === 'REVISION' && can('update')" class="space-y-4" @submit.prevent="resubmit"><label class="workflow-label">Metode pengajuan<AppSelect2 aria-label="Metode pengajuan"  v-model="proposal.requested_method"><option v-for="(label,key) in claimMethod" :key="key" :value="key">{{label}}</option></AppSelect2></label><label class="workflow-label">Penjelasan revisi<textarea class="workflow-input" v-model="proposal.note" required maxlength="2000" /></label><button class="primary workflow-btn workflow-btn-primary" :disabled="busy">Ajukan ulang</button></form></section>
  </div>
</template>
