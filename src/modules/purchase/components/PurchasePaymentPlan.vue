<script setup>
import {computed,reactive,ref,watch} from 'vue';
import {purchasePayments as api} from '@/api/purchasePayments';
import {normalizeError} from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import {useAuthStore} from '@/stores/auth';
const props=defineProps({receiptIds:{type:Array,default:()=>[]},billNumber:{type:String,default:''}});
const emit=defineEmits(['created','updated']);
const auth=useAuthStore(),busy=ref(false),error=ref(''),success=ref(''),options=ref(null),plan=ref(null),outgoing=ref([]);
const creating=computed(()=>!props.billNumber);
const canCreate=computed(()=>['purchase.bills.create','finance.payables.create','m.purchase.tp.create','m.finance.pj.create'].some(p=>auth.hasPermission(p)));
const canPay=computed(()=>['purchase.bills.update','finance.payables.update','m.purchase.tp.update','m.finance.pj.update'].some(p=>auth.hasPermission(p)));
const form=reactive({bank_account_id:'',cash_amount:'',adjustment_type:'NONE',adjustment_amount:'0',reference:'',
  credits:{},accounts:{clearing:'',claim:'',penalty:''}});
const payment=reactive({payment_date:'',source_keys:[],reference:'',confirmed:false});
let key=null,version=0;
const cents=v=>Math.round(Number(v||0)*100);
const rupiah=v=>new Intl.NumberFormat('id-ID',{style:'currency',currency:'IDR',maximumFractionDigits:2}).format(Number(v||0));
const totalCredit=computed(()=>Object.values(form.credits).reduce((n,v)=>n+cents(v),0));
const cashDue=computed(()=>((cents(options.value?.total)+
  (form.adjustment_type==='PENALTY'?cents(form.adjustment_amount):0))-
  (form.adjustment_type==='DISCOUNT'?cents(form.adjustment_amount):0)-totalCredit.value)/100);
const hasClaims=computed(()=>options.value?.credits.some(c=>c.kind!=='RETURN'&&Number(form.credits[c.id]||0)>0));
const bankOptions=computed(()=>options.value?.banks.map(b=>({value:String(b.id),label:`${b.nama_bank} · ${b.nomor_rekening}`}))||[]);
function accounts(role){return (options.value?.accounts||[]).filter(a=>role==='claim'?a.id_kategori===5:
  role==='penalty'?[6,7].includes(a.id_kategori):a.nama_akun?.trim().toLowerCase()==='pembayaran belum teridentifikasi')
  .map(a=>({value:String(a.id_coa),label:`${a.nomor_akun} — ${a.nama_akun}`}));}
const sourceKey=m=>m.source_key||(m.id_fund_source?`fund:${m.id_fund_source}`:`mutation:${m.id_mutasi}`);
const selectedKu=computed(()=>outgoing.value.filter(m=>payment.source_keys.includes(sourceKey(m))));
const selectedTotal=computed(()=>selectedKu.value.reduce((n,m)=>n+cents(m.nominal_mutasi),0));
const remainingKu=computed(()=>cents(plan.value?.cash_amount)-selectedTotal.value);
const kuMatches=computed(()=>!Number(plan.value?.cash_amount)||(selectedKu.value.length>0&&selectedKu.value.length===payment.source_keys.length&&remainingKu.value===0));
const kuOptions=computed(()=>outgoing.value.map(m=>({value:sourceKey(m),label:`${m.kode_mutasi} · ${m.tanggal_mutasi} · ${rupiah(m.nominal_mutasi)}`})));
const valid=computed(()=>!!options.value&&canCreate.value&&!!form.bank_account_id&&!!form.reference.trim()&&cashDue.value>=0&&
  form.cash_amount!==''&&cents(form.cash_amount)===cents(cashDue.value)&&
  (!Number(form.cash_amount)||!!form.accounts.clearing)&&(!hasClaims.value||!!form.accounts.claim)&&
  (!(form.adjustment_type==='PENALTY'&&Number(form.adjustment_amount))||!!form.accounts.penalty));
async function load(){const current=++version;busy.value=true;error.value='';options.value=null;plan.value=null;outgoing.value=[];payment.source_keys=[];payment.confirmed=false;
  try{if(creating.value){
    if(!props.receiptIds.length)return;
    const result=await api.options({receipt_ids:props.receiptIds.map(Number)});
    if(current!==version)return;options.value=result;
    const clearing=accounts('clearing');if(clearing.length===1)form.accounts.clearing=clearing[0].value;
  }else{
    const result=await api.find(props.billNumber);if(current!==version)return;plan.value=result;
    if(result?.status==='SUBMITTED'&&Number(result.cash_amount)>0){
      const rows=await api.outgoing(result.id);if(current!==version)return;outgoing.value=rows;
    }
  }}catch(e){if(current===version)error.value=normalizeError(e);}finally{if(current===version)busy.value=false;}}
async function create(){if(busy.value||!valid.value)return;busy.value=true;error.value='';
  try{if(!key)key=crypto.randomUUID();
    const credits=(options.value.credits||[]).filter(c=>Number(form.credits[c.id]||0)>0).map(c=>({claim_id:c.id,
      kind:c.kind==='RETURN'?'RETURN':'CLAIM',amount:String(form.credits[c.id])}));
    const result=await api.create({client_key:key,receipt_ids:props.receiptIds.map(Number),bank_account_id:Number(form.bank_account_id),
      cash_amount:String(form.cash_amount),adjustment_type:form.adjustment_type,adjustment_amount:String(form.adjustment_amount),
      reference:form.reference,credits,accounts:{...form.accounts}});
    success.value='Pengajuan tersimpan. Belum ada pembayaran atau jurnal; cocokkan KU saat pelunasan.';emit('created',result);
  }catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
async function pay(){if(busy.value||!plan.value||!canPay.value)return;busy.value=true;error.value='';
  try{if(!kuMatches.value)throw new Error('Total KU terpilih harus persis sama dengan Kas/Bank pengajuan.');
    await api.pay(plan.value.id,{payment_date:payment.payment_date,reference:payment.reference,
      bank_sources:selectedKu.value.map(ku=>ku.id_fund_source?{id_fund_source:Number(ku.id_fund_source)}:{id_mutasi:Number(ku.id_mutasi)})});
    success.value='Pelunasan, pemakaian retur/klaim, KU, dan jurnal tersimpan bersama.';await load();emit('updated');
  }catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
async function cancel(){const reason=window.prompt('Alasan membatalkan pengajuan (belum dibayar):');if(!reason||busy.value)return;
  busy.value=true;error.value='';try{await api.cancel(plan.value.id,{reason});await load();emit('updated');}catch(e){error.value=normalizeError(e);}finally{busy.value=false;}}
watch(()=>JSON.stringify(form),()=>{key=null;});
watch(()=>form.adjustment_type,value=>{if(value==='NONE')form.adjustment_amount='0';});
watch(()=>[props.billNumber,props.receiptIds.join(',')],()=>{
  Object.assign(form,{bank_account_id:'',cash_amount:'',adjustment_type:'NONE',adjustment_amount:'0',reference:'',credits:{},accounts:{clearing:'',claim:'',penalty:''}});
  Object.assign(payment,{payment_date:new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Jakarta'}).format(new Date()),source_keys:[],reference:'',confirmed:false});
  key=null;outgoing.value=[];success.value='';load();
},{immediate:true});
watch(()=>[payment.source_keys.join(','),payment.payment_date,payment.reference],()=>{payment.confirmed=false;});
</script>

<template>
  <section class="workflow-ui workflow-card space-y-4 rounded-2xl border border-slate-400/30 p-4">
    <h3 class="font-semibold">{{creating?'Pengajuan Pembayaran ke Principal':'Pencocokan KU & Pelunasan PO'}}</h3>
    <p class="text-sm opacity-75">Retur dan klaim bersifat opsional. Kas/Bank wajib diisi sebagai sisa pembayaran. Pilih satu atau beberapa KU; totalnya harus persis sama dengan Kas/Bank, tanpa pembulatan.</p>
    <p v-if="busy" role="status">Memuat / memproses…</p>
    <p v-if="error" role="alert" class="workflow-notice workflow-notice-error">{{error}}</p>
    <p v-if="success" role="status" class="workflow-notice workflow-notice-success">{{success}}</p>
    <form v-if="creating&&options" class="space-y-4" @submit.prevent="create">
      <fieldset :disabled="busy" class="space-y-4">
        <div class="workflow-inset"><p v-for="r in options.receipts" :key="r.id">{{r.no_transaksi}}: {{rupiah(r.total)}}</p><p class="mt-2 font-bold">Total hutang nota: {{rupiah(options.total)}}</p></div>
        <div class="grid gap-4 sm:grid-cols-2">
          <AppSearchSelect v-model="form.bank_account_id" label="Rekening Kas/Bank untuk pembayaran" :options="bankOptions" :clear-search-on-open="true" placeholder="Pilih rekening perusahaan" />
          <label class="workflow-label">Referensi / keterangan pengajuan<input class="workflow-input" v-model="form.reference" maxlength="200" required></label>
          <AppSearchSelect v-model="form.adjustment_type" label="Penyesuaian pembayaran" :clear-search-on-open="true" :options="[{value:'NONE',label:'Tanpa penyesuaian'},{value:'DISCOUNT',label:'Diskon (mengurangi tagihan)'},{value:'PENALTY',label:'Penalti (menambah tagihan)'}]" />
          <label v-if="form.adjustment_type!=='NONE'" class="workflow-label">Nominal {{form.adjustment_type==='DISCOUNT'?'diskon':'penalti'}} (Rp)<input v-model="form.adjustment_amount" class="workflow-input" type="number" min="0" step="0.01" required></label>
        </div>
        <section class="space-y-2"><h4 class="font-medium">Retur Beli / Piutang Klaim disetujui</h4>
          <p v-if="!options.credits.length" class="text-sm opacity-70">Belum ada saldo retur/klaim yang tersedia. Pembayaran tetap dapat memakai Kas/Bank seluruhnya.</p>
          <div v-for="c in options.credits" :key="c.id" class="workflow-inset grid gap-3 sm:grid-cols-2">
            <p>{{c.kind==='RETURN'?'Retur Beli':'Piutang Klaim'}} · {{c.number}}<br><span class="text-xs opacity-70">Tersedia {{rupiah(c.remaining)}}</span></p>
            <label class="workflow-label">{{`Alokasi ${c.number}`}}<input class="workflow-input" v-model="form.credits[c.id]" type="number" min="0" :max="c.remaining" step="0.01" placeholder="0"></label>
          </div>
        </section>
        <div class="workflow-inset flex flex-wrap items-center justify-between gap-2"><p>Sisa Kas/Bank: <strong>{{rupiah(cashDue)}}</strong></p><button type="button" class="workflow-btn" @click="form.cash_amount=String(cashDue)">Isi nominal sisa</button></div>
        <label class="workflow-label">Nominal Kas/Bank yang diajukan (Rp)<input class="workflow-input" v-model="form.cash_amount" type="number" min="0" step="0.01" required></label>
        <div class="grid gap-4 sm:grid-cols-2">
          <AppSearchSelect v-if="Number(form.cash_amount)>0" v-model="form.accounts.clearing" label="COA Pembayaran Belum Teridentifikasi" :clear-search-on-open="true" :options="accounts('clearing')" />
          <AppSearchSelect v-if="hasClaims" v-model="form.accounts.claim" label="COA Piutang Klaim (kredit)" :clear-search-on-open="true" :options="accounts('claim')" />
          <AppSearchSelect v-if="form.adjustment_type==='PENALTY'&&Number(form.adjustment_amount)>0" v-model="form.accounts.penalty" label="COA Penalti (debit)" :clear-search-on-open="true" :options="accounts('penalty')" />
        </div>
        <p v-if="Number(form.cash_amount)>0&&!accounts('clearing').length" class="workflow-notice workflow-notice-error">Akun Pembayaran Belum Teridentifikasi aktif belum tersedia pada perusahaan ini. Lengkapi COA terlebih dahulu.</p>
        <p class="text-xs opacity-70">Hutang per nota, Retur Beli, dan Diskon memakai COA principal otomatis. Pengajuan ini menahan saldo klaim/retur agar tidak digunakan dua kali.</p>
        <button class="workflow-btn workflow-btn-primary" :disabled="busy||!valid">Simpan Pengajuan Pembayaran</button>
      </fieldset>
    </form>
    <div v-if="!creating&&plan" class="space-y-4">
      <div class="workflow-inset"><p class="font-bold break-all">{{plan.no_tagihan}} · {{plan.status}}</p>
        <p>Hutang {{rupiah(plan.bill_total)}} · Retur {{rupiah(plan.return_amount)}} · Klaim {{rupiah(plan.claim_amount)}}</p>
        <p>Diskon {{rupiah(plan.discount_amount)}} · Penalti {{rupiah(plan.penalty_amount)}} · Kas/Bank <strong>{{rupiah(plan.cash_amount)}}</strong></p>
        <p v-for="r in plan.snapshot" :key="r.receipt_id" class="text-sm">{{r.no_transaksi}} · Hutang {{rupiah(r.amount)}}</p>
        <p v-if="plan.id_jurnal">Jurnal #{{plan.id_jurnal}} · {{plan.paid_date}}</p>
        <p v-for="s in plan.bank_sources" :key="s.position" class="text-sm">{{s.reference}} · {{rupiah(s.amount)}}</p>
      </div>
      <form v-if="plan.status==='SUBMITTED'&&canPay" class="space-y-4" @submit.prevent="pay">
        <label class="workflow-label">Tanggal bayar<input class="workflow-input" v-model="payment.payment_date" type="date" required></label>
        <AppSearchSelect v-if="Number(plan.cash_amount)>0" v-model="payment.source_keys" multiple label="KU — mutasi bank keluar (DB)" :options="kuOptions" :clear-search-on-open="true" placeholder="Pilih satu atau beberapa KU dari rekening yang sama" />
        <div v-if="Number(plan.cash_amount)>0" class="workflow-inset space-y-1" aria-live="polite">
          <p>{{selectedKu.length}} KU terpilih · Total <strong>{{rupiah(selectedTotal/100)}}</strong></p>
          <p :class="{'text-rose-500':remainingKu!==0}">{{remainingKu<0?'Kelebihan':'Sisa yang harus dicocokkan'}}: {{rupiah(Math.abs(remainingKu)/100)}}</p>
          <p v-for="ku in selectedKu" :key="sourceKey(ku)" class="text-sm">{{ku.kode_mutasi}} · {{rupiah(ku.nominal_mutasi)}}</p>
        </div>
        <p v-if="Number(plan.cash_amount)>0&&!outgoing.length" class="workflow-notice">Belum ada KU bank keluar yang cocok. Input/import di Mutasi Bank dengan tipe Kredit / dana keluar, lalu refresh. Pastikan perusahaan, cabang, rekening, nominal, serta COA clearing sama; dana belum dipakai. Nama bank harus menunjuk satu rekening aktif.</p>
        <p v-if="Number(plan.cash_amount)>0" class="text-xs opacity-70">Mendukung Mutasi Bank baru (Kredit / dana keluar) dan KU impor lama (DB). Jurnal bank yang sudah tercatat tidak dibukukan lagi.</p>
        <label class="workflow-label">Referensi pelunasan<input class="workflow-input" v-model="payment.reference" maxlength="200" required></label>
        <label class="flex gap-2 text-sm"><input v-model="payment.confirmed" type="checkbox" required>Saya sudah memeriksa nominal Kas/Bank, KU, dan komposisi pembayaran.</label>
        <div class="flex flex-wrap gap-2"><button class="workflow-btn workflow-btn-primary" :disabled="busy||!payment.confirmed||!kuMatches">Cocokkan KU & Lunasi</button>
          <button type="button" class="workflow-btn" :disabled="busy" @click="load">Refresh KU</button>
          <button type="button" class="workflow-btn" :disabled="busy" @click="cancel">Batalkan Pengajuan</button></div>
      </form>
    </div>
    <p v-else-if="!creating&&!busy&&!error">Tagihan lama ini belum memiliki pengajuan komposisi pembayaran. Rekonsiliasi dengan Finance sebelum memakai alur baru; pembayaran langsung lama sudah dinonaktifkan.</p>
  </section>
</template>
