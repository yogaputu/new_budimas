<script setup>
import AppSelect2 from '@/shared/components/AppSelect2.vue';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import AppModal from '@/shared/components/AppModal.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { getStandardCategories, readCoaXlsx, previewCoaStandard, applyCoaStandard } from '@/api/coaStandard';
import { normalizeError } from '@/utils/api';
const props = defineProps({ companies: { type: Array, default: () => [] } });
const emit = defineEmits(['close', 'applied']);
const companyIds = ref([]), rows = ref([]), sourceHash = ref(''), categories = ref([]), categoryMap = reactive({});
const busy = ref(false), error = ref(''), success = ref(''), notice = ref(''), plan = ref(null), confirmed = ref(false);
const search = ref(''), page = ref(1);
const normalized = v => String(v || '').trim().replace(/\s+/g, ' ').toLowerCase();
const categoryNames = computed(() => [...new Set(rows.value.map(r => r.category))]);
const selected = computed(() => rows.value.filter(r => r.selected));
const filtered = computed(() => rows.value.filter(r => normalized(`${r.code} ${r.name} ${r.category}`).includes(normalized(search.value))));
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / 25)));
const visible = computed(() => filtered.value.slice((page.value - 1) * 25, page.value * 25));
const payload = computed(() => ({company_ids: companyIds.value, source_sha256: sourceHash.value,
  rows: selected.value.map(r => ({code: r.code, name: r.name, parent_code: r.parent_code, category_id: categoryMap[r.category]}))}));
const ready = computed(() => companyIds.value.length && selected.value.length && selected.value.every(r => categoryMap[r.category]));
watch(payload, () => { plan.value = null; confirmed.value = false; success.value = ''; }, { deep: true, flush: 'sync' });
watch(search, () => { page.value = 1; });
async function loadCategories() {
  busy.value = true; error.value = '';
  try { categories.value = (await getStandardCategories()).data.data; }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
onMounted(loadCategories);
async function upload(event) {
  const file = event.target.files?.[0]; if (!file || busy.value) return;
  busy.value = true; error.value = ''; success.value = ''; plan.value = null; rows.value = []; sourceHash.value = ''; page.value = 1;
  try {
    const { data } = await readCoaXlsx(file);
    rows.value = data.rows; sourceHash.value = data.source_sha256; notice.value = data.notice;
    for (const name of categoryNames.value) {
      const matches = categories.value.filter(c => normalized(c.nama_kategori) === normalized(name));
      categoryMap[name] = matches.length === 1 ? String(matches[0].id_category) : '';
    }
  } catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; event.target.value = ''; }
}
async function preview() {
  if (!ready.value || busy.value) return;
  busy.value = true; error.value = ''; plan.value = null; confirmed.value = false;
  try { plan.value = (await previewCoaStandard(payload.value)).data; }
  catch(e) { error.value = normalizeError(e); }
  finally { busy.value = false; }
}
async function apply() {
  if (busy.value || !confirmed.value || !plan.value?.can_apply) return;
  busy.value = true; error.value = '';
  try {
    const { data } = await applyCoaStandard({...payload.value, preview_token: plan.value.preview_token, confirmed: true});
    success.value = `${data.message} Dibuat: ${data.counts.CREATE}; akun lama dipertahankan: ${data.counts.REUSE}.`;
    plan.value = null; confirmed.value = false;
    emit('applied');
  } catch(e) { error.value = normalizeError(e); plan.value = null; confirmed.value = false; }
  finally { busy.value = false; }
}
</script>
<template>
  <AppModal open size="7xl" title="Standarisasi COA Multi-Perusahaan" :hide-close="busy" :close-on-backdrop="!busy" @close="!busy && emit('close')">
    <div class="space-y-5">
      <p>Kode dan struktur akun umum dapat sama. Akun, saldo, jurnal, principal, rekening bank, dan kas cabang tetap milik perusahaan masing-masing.</p>
      <p class="rounded-xl bg-amber-50 p-3 text-amber-900 dark:bg-amber-950 dark:text-amber-100">Hanya menambah akun yang belum ada. Tidak mengganti saldo, memindahkan jurnal, atau menyalin akun principal otomatis. Pilih hanya akun umum yang sudah ditinjau.</p>
      <fieldset :disabled="busy" class="space-y-5">
        <AppSearchSelect v-model="companyIds" :options="companies" multiple label="Perusahaan tujuan" :disabled="busy" />
        <button v-if="!categories.length" type="button" :disabled="busy" @click="loadCategories">{{ busy ? 'Memuat kategori ERP…' : 'Muat Ulang Kategori ERP' }}</button>
        <label class="block">File Chart of Accounts (.xlsx, maksimal 4 MB)<input class="mt-2 block w-full" type="file" accept=".xlsx" :disabled="busy || !categories.length" @change="upload" /></label>
        <p v-if="notice" class="text-sm text-slate-500 dark:text-slate-300">{{ notice }}</p>
        <details v-if="categoryNames.length" open class="rounded-xl border border-slate-300 p-3 dark:border-slate-700">
          <summary class="cursor-pointer font-semibold">Pemetaan kategori Excel ke kategori ERP</summary>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <label v-for="name in categoryNames" :key="name">{{ name }}
              <AppSelect2 v-model="categoryMap[name]" ><option value="">Pilih kategori ERP</option><option v-for="c in categories" :key="c.id_category" :value="String(c.id_category)">{{ c.nama_kategori }}</option></AppSelect2>
            </label>
          </div>
        </details>
        <template v-if="rows.length">
          <p>{{ rows.length }} akun sumber · {{ selected.length }} dipilih. Nama dan nomor asli dipertahankan; periksa/ubah nomor induk bila usulan indentasi tidak sesuai.</p>
          <input v-model="search" class="coa-input" placeholder="Cari kode, akun, kategori" aria-label="Cari akun sumber" />
          <div class="overflow-x-auto"><table class="w-full text-left text-sm"><thead><tr><th>Pilih</th><th>Kode / Nama akun</th><th>Kategori</th><th>Nomor induk</th><th>Peninjauan</th></tr></thead>
            <tbody><tr v-for="r in visible" :key="r.code" class="border-t border-slate-200 dark:border-slate-700">
              <td class="p-2"><input v-model="r.selected" type="checkbox" :aria-label="`Pilih ${r.code}`" /></td>
              <td class="p-2"><strong>{{ r.code }}</strong><br />{{ r.name }}</td><td class="p-2">{{ r.category }}</td>
              <td class="p-2"><input v-model="r.parent_code" class="coa-input min-w-32" :aria-label="`Induk ${r.code}`" placeholder="Kosong = akun utama" /></td><td class="p-2 text-xs">{{ r.review }}</td>
            </tr></tbody></table></div>
          <div class="flex items-center gap-4"><button type="button" :disabled="page <= 1" @click="page--">Sebelumnya</button><span>{{ page }} / {{ pages }}</span><button type="button" :disabled="page >= pages" @click="page++">Berikutnya</button></div>
          <button class="btn-primary" :disabled="!ready || busy" @click="preview">{{ busy ? 'Memproses…' : 'Preview per Perusahaan' }}</button>
        </template>
      </fieldset>
      <section v-if="plan" class="space-y-3">
        <h3 class="font-semibold">Preview: {{ plan.counts.CREATE }} baru · {{ plan.counts.REUSE }} tetap · {{ plan.counts.CONFLICT }} konflik</h3>
        <p v-if="!plan.can_apply" class="text-rose-600 dark:text-rose-300">Konflik tidak ditimpa. Batalkan pilihan akun yang berkonflik atau rekonsiliasi dahulu, lalu preview ulang.</p>
        <div class="max-h-80 overflow-auto"><table class="w-full text-left text-sm"><thead><tr><th>Perusahaan</th><th>Akun</th><th>Hasil</th></tr></thead><tbody>
          <tr v-for="r in plan.items" :key="`${r.company_id}-${r.code}`" class="border-t border-slate-200 dark:border-slate-700"><td class="p-2">{{ r.company_name }}</td><td class="p-2">{{ r.code }} — {{ r.name }}</td><td class="p-2">{{ {CREATE:'Tambah baru',REUSE:'Pertahankan akun lama',CONFLICT:'Konflik'}[r.status] }}<p v-for="message in r.errors" :key="message" class="text-rose-600 dark:text-rose-300">{{ message }}</p></td></tr>
        </tbody></table></div>
        <label v-if="plan.can_apply" class="flex gap-2"><input v-model="confirmed" type="checkbox" :disabled="busy" />Saya sudah meninjau perusahaan, kategori, induk, dan memastikan akun pilihan berlaku umum untuk perusahaan tujuan.</label>
        <button class="btn-primary" :disabled="busy || !confirmed || !plan.can_apply" @click="apply">Terapkan Struktur Tanpa Mengubah Saldo</button>
      </section>
      <p v-if="error" role="alert" class="text-rose-600 dark:text-rose-300">{{ error }}</p><p v-if="success" role="status" class="text-emerald-600 dark:text-emerald-300">{{ success }}</p>
    </div>
  </AppModal>
</template>
<style scoped>
.coa-input { @apply block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 dark:border-slate-700 dark:bg-slate-950 dark:text-white; }
th { @apply p-2; }
button:disabled { @apply cursor-not-allowed opacity-50; }
</style>
