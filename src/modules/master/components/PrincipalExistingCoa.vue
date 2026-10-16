<script setup>
import { computed, reactive, ref, watch } from 'vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import { getRowCompanyIds } from '@/utils/accessScope';
import { getPrincipalExistingCoa, linkPrincipalExistingCoa } from '@/api/master';
import { normalizeError } from '@/utils/api';
const props = defineProps({ company: String, principals: Array, roles: Array });
const emit = defineEmits(['saved', 'busy']);
const principal = ref(''), options = ref([]), parents = ref({}), linked = ref({}), chosen = reactive({});
const loading = ref(false), saving = ref(false), confirmed = ref(false), error = ref(''), success = ref('');
let version = 0;
const principalOptions = computed(() => props.principals.filter(p => getRowCompanyIds(p).includes(String(props.company))).map(p => ({value: String(p.id), label: `${p.kode || ''} — ${p.nama}`})));
function roleOptions(kind) {
  return options.value.filter(c => String(c.parent_id) === String(parents.value[kind])).map(c => ({value: String(c.id_coa), label: `${c.nomor_akun} — ${c.nama_akun}`}));
}
const changes = computed(() => Object.fromEntries(Object.entries(chosen).filter(([kind, id]) => id && !linked.value[kind])));
watch(changes, () => { confirmed.value = false; }, { deep: true });
watch(principal, async () => {
  const current = ++version;
  options.value = []; linked.value = {}; parents.value = {}; Object.keys(chosen).forEach(k => delete chosen[k]);
  error.value = ''; success.value = ''; confirmed.value = false; loading.value = !!principal.value;
  if (!principal.value) return;
  try {
    const { data } = await getPrincipalExistingCoa(principal.value, props.company);
    if (current !== version) return;
    options.value = data.options; parents.value = data.parents; linked.value = data.mapping;
    Object.entries(data.mapping).forEach(([k, id]) => { chosen[k] = String(id); });
  } catch(e) { if (current === version) error.value = normalizeError(e); }
  finally { if (current === version) loading.value = false; }
});
async function save() {
  if (saving.value || loading.value || !confirmed.value || !Object.keys(changes.value).length) return;
  saving.value = true; emit('busy', true); error.value = '';
  try {
    const { data } = await linkPrincipalExistingCoa(principal.value, {id_perusahaan: props.company, mapping: changes.value, confirmed: true});
    linked.value = data.mapping; confirmed.value = false; success.value = data.message; emit('saved');
  } catch(e) { error.value = normalizeError(e); }
  finally { saving.value = false; emit('busy', false); }
}
</script>
<template>
  <details class="rounded-xl border border-slate-300 p-4 dark:border-slate-700">
    <summary class="cursor-pointer font-semibold">Hubungkan akun principal lama (tanpa membuat akun duplikat)</summary>
    <div class="mt-4 space-y-4">
      <p class="text-sm">Pilih akun rincian dengan induk yang sudah disimpan. Akun ditandai milik principal terpilih, termasuk klasifikasi riwayatnya. Nomor, induk, saldo, dan jurnal tetap. Pemetaan yang sudah terhubung tidak ditimpa.</p>
      <AppSearchSelect v-model="principal" label="Principal perusahaan ini" :options="principalOptions" :disabled="saving" />
      <p v-if="loading">Memuat akun lama…</p>
      <div v-else-if="principal" class="grid gap-3 md:grid-cols-2">
        <div v-for="role in roles" :key="role.kind">
          <p v-if="linked[role.kind]" class="text-sm">{{ role.label }}: sudah terhubung (COA #{{ linked[role.kind] }})</p>
          <AppSearchSelect v-else v-model="chosen[role.kind]" :label="role.label" :options="roleOptions(role.kind)" :disabled="saving" placeholder="Pilih akun lama (opsional)" />
        </div>
      </div>
      <label v-if="Object.keys(changes).length" class="flex gap-2 text-sm"><input v-model="confirmed" type="checkbox" :disabled="saving" />Saya memastikan akun dan riwayat transaksi pilihan hanya milik principal ini, bukan akun gabungan beberapa principal.</label>
      <button class="btn-primary" :disabled="saving || loading || !confirmed || !Object.keys(changes).length" @click="save">Hubungkan Akun Lama</button>
      <p v-if="error" role="alert" class="text-rose-600 dark:text-rose-300">{{ error }}</p><p v-if="success" role="status" class="text-emerald-600 dark:text-emerald-300">{{ success }}</p>
    </div>
  </details>
</template>
