<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, reactive, ref, watch } from 'vue';
import { principalClaims as api, rupiah } from '@/api/principalClaims';
import { normalizeError } from '@/utils/api';
import { useAuthStore } from '@/stores/auth';
const props=defineProps({ number:{type:String,required:true}, unpaid:{type:Boolean,default:false} });
const emit=defineEmits(['paid']);
const auth=useAuthStore();
const allowed=computed(() => auth.hasPermission('purchase.principal-claims.settle') || auth.hasPermission('m.purchase.kpr.approve'));
const busy=ref(false), error=ref(''), success=ref(''), options=ref(null), history=ref(null), enabled=ref(false);
const form=reactive({tanggal_bayar:'',payment_method:'TRANSFER',payment_reference:'',cash_amount:'',accounts:{payable:'',claim_recovery:'',cash:''},credits:{}});
const totalCredit=computed(() => Object.values(form.credits).reduce((n,v) => n+Math.round(Number(v || 0)*100),0)/100);
const cashDue=computed(() => (Math.round(Number(options.value?.total || 0)*100)-Math.round(totalCredit.value*100))/100);
let key=null;
async function run(fn) { if(busy.value)return; busy.value=true;error.value='';success.value='';try { await fn(); } catch(e){ error.value=normalizeError(e); } finally{ busy.value=false; } }
async function load() { await run(async()=>{ options.value=null;history.value=null;if(props.unpaid)options.value=await api.creditOptions(props.number);else history.value=await api.settlementHistory(props.number); }); }
async function save() { await run(async()=>{
  if(!key)key=crypto.randomUUID();
  const credits=Object.entries(form.credits).filter(([,amount])=>Number(amount)>0).map(([id,amount])=>({claim_id:Number(id),amount:String(amount)}));
  history.value=await api.settle({client_key:key,no_tagihan:props.number,...form,credits});
  success.value='Pelunasan, pemakaian klaim, dan jurnal tersimpan bersama.';options.value=null;emit('paid');
}); }
watch(()=>JSON.stringify(form),()=>{key=null;});
watch(()=>props.number,()=>{enabled.value=false;options.value=null;history.value=null;error.value='';success.value='';Object.assign(form,{tanggal_bayar:'',payment_method:'TRANSFER',payment_reference:'',cash_amount:'',accounts:{payable:'',claim_recovery:'',cash:''},credits:{}});key=null;});
</script>

<template>
  <section class="rounded-2xl border border-blue-300 p-4 space-y-4 workflow-ui workflow-card">
    <div><h4 class="font-semibold">Pelunasan dengan klaim principal</h4><p class="mt-1 text-sm opacity-75">Saldo klaim yang telah disetujui dapat dipakai sebagian. Sisa tagihan dibayar tunai/transfer; jurnal dicatat dalam transaksi yang sama.</p></div>
    <button type="button" class="rounded-lg border px-4 py-2 workflow-btn" :disabled="busy" @click="enabled=true;load()">{{ unpaid ? 'Muat saldo klaim yang tersedia' : 'Lihat rincian pelunasan klaim' }}</button>
    <p v-if="error" role="alert" class="text-red-600 workflow-notice workflow-notice-error">{{ error }}</p><p v-if="success" role="status" class="text-emerald-600 workflow-notice workflow-notice-success">{{ success }}</p>
    <div v-if="history" class="space-y-2 text-sm"><p>Tagihan {{ history.no_tagihan }} · Total {{ rupiah(history.total) }}</p><p>Potongan {{ rupiah(history.credit_amount) }} · Uang dibayar {{ rupiah(history.cash_amount) }} · Jurnal #{{ history.id_jurnal }}</p><p v-for="c in history.credits" :key="c.claim_id">{{ c.number }}: dipakai {{ rupiah(c.amount) }} · Sisa {{ rupiah(c.remaining) }}</p></div>
    <p v-else-if="enabled && !unpaid && !busy && !error" class="text-sm">Tidak ada pelunasan melalui klaim principal pada tagihan ini.</p>
    <form v-if="options" class="space-y-4" @submit.prevent="save">
      <p>Total tagihan: <strong>{{ rupiah(options.total) }}</strong></p>
      <div v-for="c in options.credits" :key="c.id" class="grid gap-2 rounded-xl border p-3 sm:grid-cols-2 workflow-inset"><div>{{ c.number }}<p class="text-sm opacity-75">Saldo {{ rupiah(c.remaining) }}</p></div><label class="text-sm workflow-label">Nominal dipakai<input class="workflow-input" v-model="form.credits[c.id]" type="number" min="0" :max="c.remaining" step="0.01" placeholder="0" :disabled="busy || !allowed"></label></div>
      <p v-if="!options.credits.length">Belum ada saldo klaim yang dapat digunakan untuk tagihan ini.</p>
      <template v-if="options.credits.length">
        <div class="grid gap-4 sm:grid-cols-2"><label class="workflow-label">Tanggal pembayaran<input class="workflow-input" v-model="form.tanggal_bayar" type="date" required :disabled="busy"></label><label class="workflow-label">Referensi pembayaran / bukti<input class="workflow-input" v-model="form.payment_reference" required maxlength="200" placeholder="Nomor transfer / referensi pelunasan" :disabled="busy"></label><label class="workflow-label">Metode pembayaran sisa<AppSelect2 aria-label="Metode pembayaran sisa"  v-model="form.payment_method" :disabled="busy || cashDue===0"><option value="TRANSFER">Transfer</option><option value="TUNAI">Tunai</option></AppSelect2></label><label class="workflow-label">Uang yang benar-benar dibayar<input class="workflow-input" v-model="form.cash_amount" type="number" min="0" step="0.01" required :disabled="busy"></label></div>
        <p class="workflow-inset">Potongan {{ rupiah(totalCredit) }} · Sisa yang harus dibayar {{ rupiah(cashDue) }}</p>
        <p class="text-sm opacity-75">Pilih COA sesuai kebijakan perusahaan. Akun klaim adalah akun lawan untuk pemulihan klaim; jangan memilih kas atau utang. Form ini memakai referensi bukti, bukan unggah file.</p>
        <div class="grid gap-4 sm:grid-cols-3"><label class="workflow-label" v-for="role in ['payable','claim_recovery',...(cashDue>0?['cash']:[])]" :key="role">{{ {payable:'COA utang principal',claim_recovery:'COA pemulihan klaim',cash:'COA kas / bank'}[role] }}<AppSelect2  v-model.number="form.accounts[role]" required :disabled="busy"><option value="">Pilih akun</option><option v-for="a in options.accounts" :key="a.id_coa" :value="a.id_coa">{{ a.nomor_akun }} · {{ a.nama_akun }}</option></AppSelect2></label></div>
        <p v-if="!allowed" class="text-amber-600">Diperlukan hak Approve pada Klaim Principal serta hak pembayaran tagihan purchase.</p>
        <button class="rounded-xl bg-blue-600 px-4 py-3 text-white workflow-btn workflow-btn-primary" :disabled="busy || !allowed || totalCredit<=0 || cashDue<0 || Number(form.cash_amount)!==cashDue">{{ busy?'Menyimpan…':'Lunasi dengan klaim + pembayaran' }}</button>
      </template>
    </form>
  </section>
</template>
