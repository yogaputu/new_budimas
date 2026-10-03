<script setup>
import { computed, onMounted, ref } from 'vue';
import { askAiAssistant, getAiAnalysis, getAiSummary } from '@/api/ai';
import { getBranches, getCompanies } from '@/api/master';

const loading = ref(false);
const asking = ref(false);
const analyzing = ref(false);
const summary = ref(null);
const analysis = ref(null);
const question = ref('');
const answer = ref('');
const chatMode = ref('ollama');
const dataMode = ref('');
const openaiError = ref('');
const aiNotice = ref(null);
let aiNoticeTimer = null;
const branches = ref([]);
const companies = ref([]);
const filters = ref({
  id_cabang: '',
  id_perusahaan: ''
});

const quickQuestions = [
  'Apa prioritas kerja hari ini?',
  'Tampilkan 5 faktur dengan nilai penjualan terbesar',
  'Cari customer dengan nama sumber',
  'Stok kosong ada berapa?',
  'Retur dan CN kondisinya bagaimana?'
];

function normalizeRows(response) {
  const payload = response?.data;
  if (Array.isArray(payload)) return payload;
  if (Array.isArray(payload?.result)) return payload.result;
  if (Array.isArray(payload?.data)) return payload.data;
  if (Array.isArray(payload?.data?.result)) return payload.data.result;
  return [];
}

function formatNumber(value) {
  return new Intl.NumberFormat('id-ID').format(Number(value || 0));
}

function formatCurrency(value) {
  return new Intl.NumberFormat('id-ID', {
    style: 'currency',
    currency: 'IDR',
    maximumFractionDigits: 0
  }).format(Number(value || 0));
}

function cardValue(card) {
  return card?.format === 'currency' ? formatCurrency(card.value) : formatNumber(card?.value);
}

function showAiNotice(type, message) {
  aiNotice.value = { type, message };
  if (aiNoticeTimer) window.clearTimeout(aiNoticeTimer);
  aiNoticeTimer = window.setTimeout(() => {
    aiNotice.value = null;
    aiNoticeTimer = null;
  }, 5000);
}

const cards = computed(() => summary.value?.cards || []);
const insights = computed(() => summary.value?.insights || []);
const topSales = computed(() => summary.value?.lists?.top_sales || []);
const riskOrders = computed(() => summary.value?.lists?.risk_orders || []);
const lowStockItems = computed(() => summary.value?.lists?.low_stock_items || []);
const modeLabel = computed(() => {
  if (dataMode.value === 'sql_read') return 'Ollama SQL Read Mode';
  if (chatMode.value === 'ollama') return 'Ollama Analysis';
  if (chatMode.value === 'openai') return 'OpenAI Analysis';
  return 'Local Insight Mode';
});
const modeDescription = computed(() => (
  dataMode.value === 'sql_read'
    ? 'Ollama membuat query SELECT read-only yang divalidasi backend sebelum membaca database.'
    : chatMode.value === 'ollama'
    ? 'Analisa memakai Ollama lokal di server dan snapshot ERP terkontrol.'
    : chatMode.value === 'openai'
    ? 'Analisa memakai OpenAI API dan snapshot ERP terkontrol.'
    : 'Analisa memakai aturan lokal dari snapshot ERP saat Ollama belum tersedia.'
));

async function loadOptions() {
  const [branchResponse, companyResponse] = await Promise.allSettled([getBranches(), getCompanies()]);
  branches.value = branchResponse.status === 'fulfilled' ? normalizeRows(branchResponse.value) : [];
  companies.value = companyResponse.status === 'fulfilled' ? normalizeRows(companyResponse.value) : [];
}

async function loadSummary() {
  loading.value = true;
  try {
    const { data } = await getAiSummary(filters.value);
    summary.value = data;
  } catch (error) {
    showAiNotice('error', error?.response?.data?.message || 'Gagal memuat ringkasan AI');
  } finally {
    loading.value = false;
  }
}

async function runAnalysis() {
  analyzing.value = true;
  try {
    const { data } = await getAiAnalysis(filters.value);
    analysis.value = data?.analysis || null;
    chatMode.value = data?.mode || chatMode.value;
    dataMode.value = data?.data_mode || '';
    openaiError.value = data?.openai_error || '';
    if (data?.summary) summary.value = data.summary;
    showAiNotice('success', 'Analisa AI selesai');
  } catch (error) {
    showAiNotice('error', error?.response?.data?.message || 'Gagal menjalankan analisa AI');
  } finally {
    analyzing.value = false;
  }
}

async function submitQuestion(text) {
  const nextQuestion = text || question.value;
  if (!String(nextQuestion || '').trim()) {
    showAiNotice('warning', 'Tulis pertanyaan dulu');
    return;
  }

  asking.value = true;
  question.value = nextQuestion;
  try {
    const { data } = await askAiAssistant({
      question: nextQuestion,
      ...filters.value
    });
    answer.value = data?.answer || 'Belum ada jawaban.';
    chatMode.value = data?.mode || 'local';
    dataMode.value = data?.data_mode || '';
    openaiError.value = data?.openai_error || '';
    if (data?.summary) summary.value = data.summary;
  } catch (error) {
    showAiNotice('error', error?.response?.data?.message || 'AI Assistant belum bisa menjawab');
  } finally {
    asking.value = false;
  }
}

onMounted(async () => {
  await loadOptions();
  await loadSummary();
});
</script>

<template>
  <section class="space-y-6">
    <div
      v-if="aiNotice"
      :class="[
        'rounded-2xl border px-5 py-4 text-sm font-semibold shadow-sm',
        aiNotice.type === 'success'
          ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
          : aiNotice.type === 'warning'
          ? 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
          : 'border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200'
      ]"
    >
      {{ aiNotice.message }}
    </div>

    <div class="relative overflow-hidden rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-950">
      <div class="absolute right-0 top-0 h-48 w-48 rounded-full bg-sky-400/20 blur-3xl"></div>
      <div class="absolute bottom-0 left-1/3 h-40 w-40 rounded-full bg-lime-400/20 blur-3xl"></div>
      <div class="relative flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-xs font-black uppercase tracking-[0.35em] text-lime-600 dark:text-lime-300">Budimas Intelligence</p>
          <h1 class="mt-3 text-3xl font-black text-slate-950 dark:text-white">AI Assistant</h1>
          <p class="mt-2 max-w-3xl text-sm text-slate-600 dark:text-slate-300">
            AI membaca snapshot ERP terkontrol. Jawaban utama memakai Ollama di server; jika layanan AI belum tersedia, sistem otomatis memakai Local Insight Mode.
          </p>
        </div>
        <button
          class="rounded-2xl bg-lime-600 px-5 py-3 text-sm font-black text-white shadow-lg shadow-lime-900/20 transition hover:bg-lime-500 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="loading"
          @click="loadSummary"
        >
          {{ loading ? 'Membaca data...' : 'Refresh Snapshot' }}
        </button>
      </div>
    </div>

    <div class="grid gap-4 rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 lg:grid-cols-[1fr_1fr_auto_auto]">
      <label class="space-y-2">
        <span class="text-xs font-bold uppercase tracking-[0.2em] text-slate-500">Cabang</span>
        <select v-model="filters.id_cabang" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
          <option value="">Semua cabang</option>
          <option v-for="branch in branches" :key="branch.id" :value="branch.id">
            {{ branch.kode ? `${branch.kode} - ${branch.nama}` : branch.nama }}
          </option>
        </select>
      </label>
      <label class="space-y-2">
        <span class="text-xs font-bold uppercase tracking-[0.2em] text-slate-500">Perusahaan</span>
        <select v-model="filters.id_perusahaan" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-white">
          <option value="">Semua perusahaan</option>
          <option v-for="company in companies" :key="company.id" :value="company.id">
            {{ company.kode ? `${company.kode} - ${company.nama}` : company.nama }}
          </option>
        </select>
      </label>
      <div class="flex items-end">
        <button class="w-full rounded-2xl border border-slate-200 px-5 py-3 text-sm font-black text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-100 dark:hover:bg-slate-800" @click="loadSummary">
          Terapkan Filter
        </button>
      </div>
      <div class="flex items-end">
        <button
          class="w-full rounded-2xl bg-sky-600 px-5 py-3 text-sm font-black text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="analyzing"
          @click="runAnalysis"
        >
          {{ analyzing ? 'Menganalisa...' : 'Analisa Kondisi' }}
        </button>
      </div>
    </div>

    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article
        v-for="card in cards"
        :key="card.key"
        class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900"
      >
        <p class="text-xs font-black uppercase tracking-[0.25em] text-slate-500">{{ card.label }}</p>
        <p class="mt-4 text-2xl font-black text-slate-950 dark:text-white">{{ cardValue(card) }}</p>
        <div class="mt-4 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
          <div class="h-full w-2/3 rounded-full bg-gradient-to-r from-sky-400 via-lime-400 to-emerald-500"></div>
        </div>
      </article>
    </div>

    <section v-if="analysis" class="rounded-[1.5rem] border border-sky-200 bg-sky-50 p-5 shadow-sm dark:border-sky-500/30 dark:bg-sky-500/10">
      <div class="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div>
          <p class="text-xs font-black uppercase tracking-[0.3em] text-sky-700 dark:text-sky-300">Analisa Otomatis</p>
          <h2 class="mt-2 text-xl font-black text-slate-950 dark:text-white">Rekomendasi AI</h2>
          <p class="mt-2 max-w-4xl text-sm leading-6 text-slate-700 dark:text-slate-200">{{ analysis.executive_summary }}</p>
        </div>
        <span class="rounded-full bg-white px-4 py-2 text-xs font-black uppercase tracking-[0.2em] text-sky-700 dark:bg-slate-950 dark:text-sky-300">{{ modeLabel }}</span>
      </div>
      <div class="mt-5 grid gap-4 lg:grid-cols-3">
        <div class="rounded-2xl border border-white/60 bg-white/80 p-4 dark:border-slate-700 dark:bg-slate-950/60">
          <h3 class="text-sm font-black text-slate-950 dark:text-white">Prioritas</h3>
          <ul class="mt-3 space-y-2 text-sm text-slate-700 dark:text-slate-200">
            <li v-for="item in analysis.priorities || []" :key="item">• {{ item }}</li>
          </ul>
        </div>
        <div class="rounded-2xl border border-white/60 bg-white/80 p-4 dark:border-slate-700 dark:bg-slate-950/60">
          <h3 class="text-sm font-black text-slate-950 dark:text-white">Risiko</h3>
          <ul class="mt-3 space-y-2 text-sm text-slate-700 dark:text-slate-200">
            <li v-for="item in analysis.risks || []" :key="item">• {{ item }}</li>
          </ul>
        </div>
        <div class="rounded-2xl border border-white/60 bg-white/80 p-4 dark:border-slate-700 dark:bg-slate-950/60">
          <h3 class="text-sm font-black text-slate-950 dark:text-white">Aksi Berikutnya</h3>
          <ul class="mt-3 space-y-2 text-sm text-slate-700 dark:text-slate-200">
            <li v-for="item in analysis.next_actions || []" :key="item">• {{ item }}</li>
          </ul>
        </div>
      </div>
    </section>

    <div class="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
      <section class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-lg font-black text-slate-950 dark:text-white">Insight Cepat</h2>
        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">Sinyal awal yang bisa ditindaklanjuti tim.</p>
        <div class="mt-5 space-y-3">
          <div
            v-for="(insight, index) in insights"
            :key="index"
            class="rounded-2xl border border-lime-200 bg-lime-50 p-4 text-sm font-medium text-lime-950 dark:border-lime-500/30 dark:bg-lime-500/10 dark:text-lime-100"
          >
            {{ insight }}
          </div>
        </div>
      </section>

      <section class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 class="text-lg font-black text-slate-950 dark:text-white">Tanya AI</h2>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
              Mode saat ini: <span class="font-bold text-sky-600 dark:text-sky-300">{{ modeLabel }}</span>
            </p>
            <p class="mt-2 max-w-2xl text-xs leading-5 text-slate-500 dark:text-slate-400">
              {{ modeDescription }}
            </p>
            <p v-if="openaiError" class="mt-2 max-w-2xl text-xs leading-5 text-amber-600 dark:text-amber-300">
              Ollama belum aktif atau belum merespons, jadi jawaban dialihkan ke mode lokal.
            </p>
          </div>
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <button
            v-for="item in quickQuestions"
            :key="item"
            class="rounded-full border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
            @click="submitQuestion(item)"
          >
            {{ item }}
          </button>
        </div>
        <textarea
          v-model="question"
          rows="4"
          class="mt-4 w-full rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-900 outline-none transition focus:border-lime-500 dark:border-slate-700 dark:bg-slate-950 dark:text-white"
          placeholder="Contoh: toko mana yang perlu ditagih dulu, retur hari ini bagaimana, atau order yang paling perlu dipantau apa?"
        ></textarea>
        <button
          class="mt-3 rounded-2xl bg-sky-600 px-5 py-3 text-sm font-black text-white shadow-lg shadow-sky-900/20 transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="asking"
          @click="submitQuestion()"
        >
          {{ asking ? 'Memikirkan...' : 'Tanya AI' }}
        </button>
        <div v-if="answer" class="mt-5 whitespace-pre-line rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm leading-7 text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200">
          {{ answer }}
        </div>
      </section>
    </div>

    <div class="grid gap-5 xl:grid-cols-3">
      <section class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-lg font-black text-slate-950 dark:text-white">Top Sales</h2>
        <div class="mt-4 space-y-3">
          <div v-for="row in topSales" :key="row.nama_sales" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="font-black text-slate-950 dark:text-white">{{ row.nama_sales }}</p>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ formatNumber(row.total_order) }} order · {{ formatCurrency(row.total_nilai) }}</p>
          </div>
          <p v-if="!topSales.length" class="text-sm text-slate-500">Belum ada data top sales pada filter ini.</p>
        </div>
      </section>
      <section class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-lg font-black text-slate-950 dark:text-white">Order Perlu Dipantau</h2>
        <div class="mt-4 space-y-3">
          <div v-for="row in riskOrders" :key="row.id_sales_order" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="font-black text-slate-950 dark:text-white">{{ row.nomor }}</p>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ row.customer }} · {{ row.principal }} · Status {{ row.status_order }}</p>
          </div>
          <p v-if="!riskOrders.length" class="text-sm text-slate-500">Belum ada order berisiko dari filter ini.</p>
        </div>
      </section>
      <section class="rounded-[1.5rem] border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 class="text-lg font-black text-slate-950 dark:text-white">Stok Kosong/Minus</h2>
        <div class="mt-4 space-y-3">
          <div v-for="row in lowStockItems" :key="`${row.cabang}-${row.kode_produk}`" class="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
            <p class="font-black text-slate-950 dark:text-white">{{ row.nama_produk }}</p>
            <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ row.cabang }} · {{ row.kode_produk }} · Ready {{ formatNumber(row.stok_ready) }}</p>
          </div>
          <p v-if="!lowStockItems.length" class="text-sm text-slate-500">Belum ada stok kosong/minus dari filter ini.</p>
        </div>
      </section>
    </div>
  </section>
</template>
