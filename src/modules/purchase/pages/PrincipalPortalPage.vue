<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { onMounted, reactive, ref } from 'vue';
import { principalPortal as api, claimStatus, claimMethod, rupiah } from '@/api/principalClaims';
import PrincipalClaimDetail from '../components/PrincipalClaimDetail.vue';
import { normalizeError } from '@/utils/api';

const user = ref(null), rows = ref([]), selected = ref(null), products = ref([]);
const busy = ref(false), error = ref(''), success = ref(''), page = ref(1), total = ref(0), status = ref('');
const credentials = reactive({ login: '', password: '' });
const decision = reactive({ decision: 'APPROVED', approved_amount: '', approved_method: 'CREDIT', approval_reference: '', note: '', goods: [] });
async function run(fn) {
  if (busy.value) return;
  busy.value = true; error.value = ''; success.value = '';
  try { await fn(); } catch (e) {
    error.value = normalizeError(e);
    if (e?.response?.status === 401) { api.clearSession(); user.value = null; selected.value = null; rows.value = []; }
  } finally { busy.value = false; }
}
async function load() { const result = await api.list({ page: page.value, status: status.value }); rows.value = result.rows; total.value = result.total; }
function login() { run(async () => { user.value = await api.login(credentials); credentials.password = ''; await load(); }); }
function logout() { run(async () => { await api.logout(); api.clearSession(); user.value = null; selected.value = null; rows.value = []; }); }
function open(id) { run(async () => {
  selected.value = await api.detail(id);
  Object.assign(decision, { decision: 'APPROVED', approved_amount: selected.value.requested_amount, approved_method: selected.value.requested_method, approval_reference: '', note: '', goods: [] });
  products.value = await api.products();
}); }
function save() { run(async () => {
  selected.value = await api.decide(selected.value.id, { ...decision, revision: selected.value.revision });
  success.value = 'Keputusan tersimpan. Persetujuan tidak langsung mengubah utang atau stok.';
  await load();
}); }
onMounted(() => { if (api.hasSession()) run(async () => { user.value = await api.me(); await load(); }); });
</script>

<template>
  <main class="portal workflow-ui min-h-screen px-4 py-8 sm:px-8">
    <div class="mx-auto max-w-6xl space-y-6">
      <header class="workflow-toolbar border-b border-slate-200 pb-6"><div><p class="workflow-link text-xs font-semibold tracking-[.2em]">BUDIMAS · PRINCIPAL PORTAL</p><h1 class="mt-3 text-3xl font-semibold">Klaim & persetujuan</h1><p class="workflow-caption mt-2">Tinjau pemakaian promo dan tentukan nilai penyelesaiannya.</p></div><div v-if="user" class="flex items-center gap-4"><span>{{ user.display_name }}</span><button class="workflow-btn" :disabled="busy" @click="logout">Keluar</button></div></header>
      <p v-if="error" role="alert" class="rounded-xl border border-red-400 bg-red-950 p-4 workflow-notice workflow-notice-error">{{ error }}</p>
      <p v-if="success" role="status" class="rounded-xl border border-emerald-500 p-4 workflow-notice workflow-notice-success">{{ success }}</p>
      <form v-if="!user" class="workflow-card mx-auto max-w-md space-y-5" @submit.prevent="login">
        <h2 class="workflow-heading">Masuk sebagai principal</h2><p class="workflow-caption">Gunakan akun portal yang diberikan administrator Budimas. Akun ini terpisah dari login ERP.</p>
        <label class="workflow-label">Username / email<input class="workflow-input" v-model="credentials.login" required autocomplete="username" maxlength="120"></label>
        <label class="workflow-label">Password<input class="workflow-input" v-model="credentials.password" type="password" required autocomplete="current-password" maxlength="128"></label>
        <button class="primary w-full workflow-btn workflow-btn-primary" :disabled="busy">{{ busy ? 'Memproses…' : 'Masuk' }}</button>
      </form>
      <template v-else>
        <div class="flex flex-wrap items-center gap-3"><label class="max-w-xs workflow-label">Status<AppSelect2 aria-label="Status"  v-model="status" :disabled="busy" @change="page = 1; run(load)"><option value="">Semua status</option><option v-for="(label, key) in claimStatus" :key="key" :value="key">{{ label }}</option></AppSelect2></label><button class="workflow-btn" :disabled="busy" @click="run(load)">Muat ulang</button></div>
        <div class="overflow-x-auto rounded-2xl border border-slate-700 bg-slate-900 workflow-table-wrap"><table class="w-full text-left workflow-table"><thead><tr><th>Nomor klaim</th><th>Pengajuan</th><th>Status</th><th></th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.number }}<br><small>{{ row.period_from }} – {{ row.period_to }}</small></td><td>{{ rupiah(row.requested_amount) }}<br><small>{{ claimMethod[row.requested_method] }}</small></td><td>{{ claimStatus[row.status] }}</td><td><button class="workflow-btn" :disabled="busy" @click="open(row.id)">Tinjau</button></td></tr><tr v-if="!rows.length"><td colspan="4">{{ busy ? 'Memuat klaim…' : 'Belum ada klaim pada filter ini.' }}</td></tr></tbody></table></div>
        <div class="flex items-center justify-between flex-wrap items-center gap-3"><button class="workflow-btn" :disabled="busy || page <= 1" @click="page--; run(load)">Sebelumnya</button><span>Halaman {{ page }} · {{ total }} klaim</span><button class="workflow-btn" :disabled="busy || page * 50 >= total" @click="page++; run(load)">Berikutnya</button></div>
        <section v-if="selected" class="space-y-6 rounded-2xl border border-slate-700 bg-slate-900 p-5 sm:p-8 workflow-inset">
          <div class="flex items-center justify-between flex-wrap items-center gap-3"><h2 class="text-xl font-semibold">{{ selected.number }}</h2><button class="workflow-btn" :disabled="busy" @click="selected = null">Tutup</button></div>
          <PrincipalClaimDetail :claim="selected" />
          <form v-if="selected.status === 'SUBMITTED'" class="space-y-4 border-t border-slate-700 pt-6" @submit.prevent="save">
            <h3 class="text-lg font-semibold">Keputusan principal</h3>
            <label class="workflow-label">Keputusan<AppSelect2 aria-label="Keputusan"  v-model="decision.decision"><option value="APPROVED">Setujui penuh / sebagian</option><option value="REVISION">Minta revisi</option><option value="REJECTED">Tolak</option></AppSelect2></label>
            <div v-if="decision.decision === 'APPROVED'" class="grid gap-4 sm:grid-cols-3"><label class="workflow-label">Nominal disetujui<input class="workflow-input" v-model="decision.approved_amount" type="number" min="0.01" :max="selected.requested_amount" step="0.01" required></label><label class="workflow-label">Penyelesaian<AppSelect2 aria-label="Penyelesaian"  v-model="decision.approved_method"><option v-for="(label,key) in claimMethod" :key="key" :value="key">{{label}}</option></AppSelect2></label><label class="workflow-label">Referensi persetujuan<input class="workflow-input" v-model="decision.approval_reference" required maxlength="200"></label></div>
            <div v-if="decision.decision === 'APPROVED' && decision.approved_method === 'GOODS'" class="space-y-3"><p>Nilai total barang harus sama dengan nominal disetujui.</p><div v-for="(g, i) in decision.goods" :key="i" class="grid gap-3 sm:grid-cols-4"><label class="workflow-label">Produk<AppSelect2 aria-label="Produk"  v-model.number="g.id_produk" required><option value="">Pilih produk</option><option v-for="p in products" :key="p.id" :value="p.id">{{ p.kode_sku }} · {{ p.nama }}</option></AppSelect2></label><label class="workflow-label">Jumlah PCS<input class="workflow-input" v-model.number="g.qty_pcs" required type="number" min="1" step="1"></label><label class="workflow-label">Nilai per PCS<input class="workflow-input" v-model="g.unit_value" required type="number" min="0.01" step="0.01"></label><button class="workflow-btn" type="button" @click="decision.goods.splice(i, 1)">Hapus baris</button></div><button class="workflow-btn" type="button" @click="decision.goods.push({ id_produk: '', qty_pcs: 1, unit_value: '' })">Tambah barang</button></div>
            <label class="workflow-label">Catatan keputusan<textarea class="workflow-input" v-model="decision.note" required maxlength="2000" rows="3" /></label><button class="primary workflow-btn workflow-btn-primary" :disabled="busy">{{ busy ? 'Menyimpan…' : 'Simpan keputusan' }}</button>
          </form>
        </section>
      </template>
    </div>
  </main>
</template>
