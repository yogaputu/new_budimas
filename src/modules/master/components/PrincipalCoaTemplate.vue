<script setup>
import { computed, reactive, ref, watch } from 'vue';
import { getPrincipalCoaTemplate, savePrincipalCoaTemplate } from '@/api/master';
import { normalizeError } from '@/utils/api';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PrincipalExistingCoa from './PrincipalExistingCoa.vue';
const props = defineProps({ companyOptions: { type: Array, default: () => [] }, principals: { type: Array, default: () => [] }, initialCompany: { type: String, default: '' } });
const emit = defineEmits(['saved']);
const company = ref(props.initialCompany);
const roles = ref([]), accounts = ref([]), mapping = reactive({});
const loading = ref(false), saving = ref(false), error = ref(''), success = ref('');
const suggestions = ref({}), notice = ref(''), linkBusy = ref(false);
let requestId = 0;
const options = computed(() => accounts.value.map(a => ({ value: String(a.id_coa), label: `${a.nomor_akun} — ${a.nama_akun} (${a.nama_kategori})` })));
const validIds = computed(() => new Set(options.value.map(a => a.value)));
const complete = computed(() => roles.value.length > 0 && roles.value.every(r => validIds.value.has(mapping[r.kind])));
async function load() {
  const current = ++requestId;
  error.value = ''; success.value = ''; roles.value = []; accounts.value = [];
  suggestions.value = {}; notice.value = '';
  Object.keys(mapping).forEach(key => delete mapping[key]);
  loading.value = !!company.value;
  if (!company.value) return;
  try {
    const { data } = await getPrincipalCoaTemplate(company.value);
    if (current !== requestId) return;
    roles.value = data.roles; accounts.value = data.options;
    suggestions.value = data.reference_suggestions || {}; notice.value = data.reference_notice || '';
    Object.entries(data.mapping).forEach(([key, value]) => { mapping[key] = String(value); });
  } catch (e) { if (current === requestId) error.value = normalizeError(e); }
  finally { if (current === requestId) loading.value = false; }
}
async function save() {
  if (saving.value || loading.value || !complete.value) return;
  saving.value = true; error.value = ''; success.value = '';
  try {
    await savePrincipalCoaTemplate({ id_perusahaan: company.value, mapping: { ...mapping } });
    success.value = 'Pemetaan tersimpan. Berlaku untuk principal baru; akun lama tidak diubah.';
    emit('saved');
  } catch (e) { error.value = normalizeError(e); }
  finally { saving.value = false; }
}
watch(company, load, { immediate: true });
function suggest() {
  for (const [kind, id] of Object.entries(suggestions.value)) if (!mapping[kind]) mapping[kind] = String(id);
}
</script>

<template>
  <div class="space-y-4">
    <p class="text-sm text-slate-500 dark:text-slate-300">Atur sekali per perusahaan. Pilih akun induk yang benar untuk setiap jenis; kategori akun baru mengikuti induknya. Tidak ada saldo awal atau jurnal yang dibuat.</p>
    <fieldset :disabled="saving || linkBusy" class="space-y-4">
      <AppSearchSelect v-model="company" label="Perusahaan" :options="companyOptions" :disabled="saving || linkBusy" />
      <p v-if="notice" class="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-100">{{ notice }}</p>
      <button v-if="Object.keys(suggestions).length" class="btn-secondary" :disabled="saving || loading || linkBusy" @click="suggest">Isi Pilihan Kosong dari Acuan COA (Tinjau Sebelum Simpan)</button>
      <p v-if="loading" role="status">Memuat pemetaan…</p>
      <div v-else class="grid gap-4 md:grid-cols-2">
        <AppSearchSelect v-for="role in roles" :key="role.kind" v-model="mapping[role.kind]" :label="role.label" :options="options" :disabled="saving" placeholder="Pilih akun induk" />
      </div>
    </fieldset>
    <p v-if="company && !loading && roles.length" class="text-sm text-slate-500 dark:text-slate-300">Nomor otomatis: nomor induk-P[ID principal]-[jenis akun]. Nama: jenis akun - nama principal. Akun induk harus mencakup cabang yang dipilih pada principal.</p>
    <p v-if="error" role="alert" class="text-rose-500">{{ error }}</p>
    <p v-if="success" role="status" class="text-emerald-600">{{ success }}</p>
    <button class="rounded-xl bg-brand-600 px-4 py-2 text-white disabled:opacity-50" :disabled="saving || loading || linkBusy || !complete" @click="save">{{ saving ? 'Menyimpan…' : `Simpan ${roles.length} Pemetaan` }}</button>
    <PrincipalExistingCoa v-if="company && !loading && !saving" :key="company" :company="company" :principals="principals" :roles="roles" @busy="linkBusy = $event" @saved="emit('saved')" />
  </div>
</template>
