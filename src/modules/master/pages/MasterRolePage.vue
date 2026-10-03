<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import {
  createFeature,
  createFeaturePositionAssignment,
  deleteFeaturePositionAssignment,
  getFeaturePositionAssignments,
  getFeatures,
  getPositions,
  getUsers,
  updateUser
} from '@/api/master';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { permissionActions, rolePermissionDefinitions } from '@/shared/constants/permissions';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const positions = ref([]);
const users = ref([]);
const features = ref([]);
const assignedRows = ref([]);
const selectedPositionId = ref('');
const selectedTestUserId = ref('');
const search = ref('');
const loading = ref(false);
const savingCode = ref('');
const assigningUser = ref(false);
const syncingPermissions = ref(false);
const feedback = ref('');
const errorMessage = ref('');

const positionOptions = computed(() =>
  positions.value.map((item) => ({
    value: String(item.id),
    label: `${item.kode || '-'} - ${item.nama || 'Role'}`
  }))
);

const selectedPosition = computed(() =>
  positions.value.find((item) => String(item.id) === String(selectedPositionId.value))
);

const userOptions = computed(() =>
  users.value.map((item) => ({
    value: String(item.id),
    label: [
      item.nama || item.username || `User ${item.id}`,
      item.username,
      item.nama_jabatan,
      item.nama_cabang
    ]
      .filter(Boolean)
      .join(' | ')
  }))
);

const selectedTestUser = computed(() =>
  users.value.find((item) => String(item.id) === String(selectedTestUserId.value))
);

const featureByCode = computed(() => {
  const map = new Map();
  features.value.forEach((feature) => {
    const code = String(feature.nama || feature.kode || '').trim();
    if (code) map.set(code, feature);
  });
  return map;
});

const assignedByCode = computed(() => {
  const map = new Map();
  assignedRows.value.forEach((row) => {
    const code = String(row.nama_fitur || row.nama || '').trim();
    if (code) map.set(code, row);
  });
  return map;
});

const filteredResources = computed(() => {
  const keyword = search.value.trim().toLowerCase();
  if (!keyword) return rolePermissionDefinitions;
  return rolePermissionDefinitions.filter((resource) =>
    [
      resource.module,
      resource.label,
      resource.baseCode,
      ...resource.permissions.map((item) => item.code)
    ]
      .join(' ')
      .toLowerCase()
      .includes(keyword)
  );
});

const groupedResources = computed(() => {
  const groups = new Map();
  filteredResources.value.forEach((resource) => {
    if (!groups.has(resource.module)) groups.set(resource.module, []);
    groups.get(resource.module).push(resource);
  });
  return Array.from(groups.entries()).map(([module, resources]) => ({ module, resources }));
});

const activeCount = computed(() => assignedRows.value.length);
const totalPermissionCount = computed(() =>
  rolePermissionDefinitions.reduce((total, resource) => total + resource.permissions.length, 0)
);
const allPermissionCodes = computed(() =>
  rolePermissionDefinitions.flatMap((resource) => resource.permissions.map((permission) => permission.code))
);
const missingFeatureCount = computed(() =>
  allPermissionCodes.value.filter((code) => !featureByCode.value.has(code)).length
);

function isChecked(code) {
  return assignedByCode.value.has(code);
}

async function loadPositions() {
  const response = await getPositions();
  positions.value = normalizeList(unwrapResponse(response));
}

async function loadUsers() {
  const response = await getUsers();
  users.value = normalizeList(unwrapResponse(response));
}

async function loadFeatures() {
  const response = await getFeatures();
  features.value = normalizeList(unwrapResponse(response));
}

async function loadAssignments() {
  if (!selectedPositionId.value) {
    assignedRows.value = [];
    return;
  }

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    const response = await getFeaturePositionAssignments(selectedPositionId.value);
    assignedRows.value = normalizeList(unwrapResponse(response));
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Hak akses role belum bisa dimuat.');
    assignedRows.value = [];
  } finally {
    loading.value = false;
  }
}

async function ensureFeature(code) {
  const existing = featureByCode.value.get(code);
  if (existing?.id) return existing;

  try {
    await createFeature({ nama: code });
  } catch (err) {
    await loadFeatures();
    const recovered = featureByCode.value.get(code);
    if (recovered?.id) return recovered;
    throw err;
  }
  await loadFeatures();

  const created = featureByCode.value.get(code);
  if (!created?.id) {
    throw new Error(`Permission ${code} belum berhasil dibuat di master fitur.`);
  }
  return created;
}

async function setPermission(code, enabled) {
  if (!selectedPositionId.value) {
    errorMessage.value = 'Pilih role/jabatan terlebih dahulu.';
    return;
  }

  savingCode.value = code;
  feedback.value = '';
  errorMessage.value = '';

  try {
    if (enabled) {
      const feature = await ensureFeature(code);
      await createFeaturePositionAssignment({
        id_jabatan: selectedPositionId.value,
        id_fitur: feature.id
      });
      feedback.value = `Akses ${code} berhasil diaktifkan.`;
    } else {
      const assignment = assignedByCode.value.get(code);
      if (assignment?.id) {
        await deleteFeaturePositionAssignment(assignment.id);
      }
      feedback.value = `Akses ${code} berhasil dinonaktifkan.`;
    }
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, `Akses ${code} belum berhasil diperbarui.`);
  } finally {
    savingCode.value = '';
  }
}

async function syncAllPermissions() {
  syncingPermissions.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    await loadFeatures();
    const existingCodes = new Set(featureByCode.value.keys());
    let createdCount = 0;

    for (const code of allPermissionCodes.value) {
      if (existingCodes.has(code)) continue;

      try {
        await createFeature({ nama: code });
        existingCodes.add(code);
        createdCount += 1;
      } catch (err) {
        await loadFeatures();
        if (!featureByCode.value.has(code)) {
          throw err;
        }
        existingCodes.add(code);
      }
    }

    await loadFeatures();
    const stillMissing = allPermissionCodes.value.filter((code) => !featureByCode.value.has(code));
    if (stillMissing.length) {
      throw new Error(`${stillMissing.length} permission menu belum tersinkron ke master fitur.`);
    }

    feedback.value = createdCount
      ? `Sinkron menu selesai. ${createdCount} permission baru dibuat di master fitur.`
      : 'Sinkron menu selesai. Semua permission menu sudah tersedia di master fitur.';
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Sinkron menu role belum berhasil.');
  } finally {
    syncingPermissions.value = false;
  }
}

async function applyResource(resource, mode) {
  const allowedActions = mode === 'view'
    ? ['view']
    : mode === 'crud'
      ? ['view', 'create', 'update', 'delete']
      : resource.actions;

  loading.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    for (const permission of resource.permissions) {
      const shouldEnable = allowedActions.includes(permission.action);
      const currentlyEnabled = isChecked(permission.code);
      if (shouldEnable === currentlyEnabled) continue;
      if (shouldEnable) {
        const feature = await ensureFeature(permission.code);
        await createFeaturePositionAssignment({
          id_jabatan: selectedPositionId.value,
          id_fitur: feature.id
        });
      } else {
        const assignment = assignedByCode.value.get(permission.code);
        if (assignment?.id) await deleteFeaturePositionAssignment(assignment.id);
      }
    }
    feedback.value = `Hak akses ${resource.label} berhasil disesuaikan.`;
    await loadAssignments();
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Hak akses resource belum berhasil disesuaikan.');
  } finally {
    loading.value = false;
  }
}

async function assignRoleToUser() {
  if (!selectedPositionId.value) {
    errorMessage.value = 'Pilih role/jabatan terlebih dahulu.';
    return;
  }

  if (!selectedTestUserId.value) {
    errorMessage.value = 'Pilih user uji coba terlebih dahulu.';
    return;
  }

  assigningUser.value = true;
  feedback.value = '';
  errorMessage.value = '';

  try {
    await updateUser(selectedTestUserId.value, {
      id_jabatan: selectedPositionId.value
    });
    await loadUsers();
    feedback.value = `Role ${selectedPosition.value?.nama || selectedPositionId.value} berhasil diterapkan ke user ${selectedTestUser.value?.nama || selectedTestUserId.value}. Silakan logout-login user tersebut untuk membaca permission terbaru.`;
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Role belum berhasil diterapkan ke user uji coba.');
  } finally {
    assigningUser.value = false;
  }
}

watch(selectedPositionId, loadAssignments);

onMounted(async () => {
  loading.value = true;
  try {
    await Promise.all([loadPositions(), loadUsers(), loadFeatures()]);
  } catch (err) {
    errorMessage.value = normalizeError(err, 'Hak Akses belum bisa dimuat.');
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="space-y-6">
    <PageHeader
      title="Hak Akses"
      description="Centang Lihat untuk menampilkan menu di sidebar. Aksi CRUD, approve, cetak, dan export dipakai untuk kontrol tombol/proses di dalam halaman."
    />

    <section class="panel p-5">
      <div class="grid gap-4 xl:grid-cols-[minmax(260px,420px)_1fr_auto_auto]">
        <AppSearchSelect
          v-model="selectedPositionId"
          label="Role / Jabatan"
          placeholder="Pilih role"
          :options="positionOptions"
          empty-text="Role belum tersedia."
        />
        <label class="block text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          Cari Akses
          <input
            v-model="search"
            class="field mt-2"
            placeholder="Cari menu, modul, atau kode permission..."
          />
        </label>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900">
          <p class="text-[11px] font-black uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">Aktif</p>
          <p class="mt-1 text-xl font-black text-slate-950 dark:text-white">{{ activeCount }}</p>
        </div>
        <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900">
          <p class="text-[11px] font-black uppercase tracking-[0.24em] text-slate-500 dark:text-slate-400">Daftar</p>
          <p class="mt-1 text-xl font-black text-slate-950 dark:text-white">{{ totalPermissionCount }}</p>
        </div>
      </div>

      <div v-if="selectedPosition" class="mt-4 rounded-2xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-100">
        Role aktif: <strong>{{ selectedPosition.nama }}</strong>. Permission <strong>Lihat</strong> menentukan menu yang muncul di sidebar, sedangkan aksi lain mengatur proses CRUD dan approval.
      </div>

      <div class="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-700 dark:bg-slate-900">
        <p class="text-sm text-slate-600 dark:text-slate-300">
          {{ missingFeatureCount ? `${missingFeatureCount} permission menu belum ada di master fitur.` : 'Semua permission menu sudah ada di master fitur.' }}
        </p>
        <button
          class="rounded-xl bg-slate-900 px-4 py-2 text-sm font-black text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-brand-600 dark:hover:bg-brand-700"
          :disabled="syncingPermissions || loading"
          @click="syncAllPermissions"
        >
          {{ syncingPermissions ? 'Sinkron...' : 'Sinkron Semua Menu' }}
        </button>
      </div>
    </section>

    <section class="panel p-5">
      <div class="grid gap-4 lg:grid-cols-[minmax(260px,1fr)_minmax(180px,260px)_minmax(220px,320px)] lg:items-end">
        <AppSearchSelect
          v-model="selectedTestUserId"
          label="User Uji Coba"
          placeholder="Pilih satu user untuk test role"
          :options="userOptions"
          empty-text="User belum tersedia."
        />
        <RouterLink
          to="/access/user-features"
          class="rounded-2xl border border-slate-200 px-5 py-3 text-center text-sm font-black text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
        >
          Hak Akses User
        </RouterLink>
        <button
          class="rounded-2xl bg-brand-600 px-5 py-3 text-sm font-black text-white shadow-sm hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="assigningUser || !selectedPositionId || !selectedTestUserId"
          @click="assignRoleToUser"
        >
          {{ assigningUser ? 'Menerapkan...' : 'Terapkan Role ke User' }}
        </button>
      </div>
      <p class="mt-3 text-sm text-slate-500 dark:text-slate-400">
        Gunakan ini untuk UAT cepat: role yang dipilih di atas akan dipasang ke user terpilih. User tersebut perlu logout-login agar sidebar membaca permission terbaru.
      </p>
    </section>

    <section v-if="feedback" class="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200">{{ feedback }}</section>
    <section v-if="errorMessage" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">{{ errorMessage }}</section>

    <section v-if="!selectedPositionId" class="panel p-8 text-center text-sm text-slate-500 dark:text-slate-400">
      Pilih role terlebih dahulu untuk mulai mengatur hak akses.
    </section>

    <div v-else class="space-y-5">
      <section
        v-for="group in groupedResources"
        :key="group.module"
        class="panel overflow-hidden"
      >
        <div class="border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <h2 class="text-lg font-black text-slate-950 dark:text-white">{{ group.module }}</h2>
          <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">{{ group.resources.length }} resource hak akses.</p>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="bg-slate-50 text-left text-xs uppercase tracking-[0.16em] text-slate-500 dark:bg-slate-900 dark:text-slate-400">
              <tr>
                <th class="px-5 py-3">Menu / Resource</th>
                <th
                  v-for="action in permissionActions"
                  :key="action.key"
                  class="px-3 py-3 text-center"
                >
                  {{ action.label }}
                </th>
                <th class="px-5 py-3 text-right">Preset</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
              <tr
                v-for="resource in group.resources"
                :key="resource.baseCode"
                class="bg-white dark:bg-slate-950"
              >
                <td class="px-5 py-4">
                  <p class="font-black text-slate-950 dark:text-white">{{ resource.label }}</p>
                  <p class="mt-1 font-mono text-xs text-slate-500 dark:text-slate-400">{{ resource.baseCode }}</p>
                </td>
                <td
                  v-for="action in permissionActions"
                  :key="action.key"
                  class="px-3 py-4 text-center"
                >
                  <label
                    v-if="resource.actions.includes(action.key)"
                    class="inline-flex cursor-pointer items-center justify-center"
                  >
                    <input
                      type="checkbox"
                      class="h-5 w-5 rounded border-slate-300 text-brand-600 focus:ring-brand-500 disabled:cursor-wait"
                      :checked="isChecked(`${resource.baseCode}.${action.key}`)"
                      :disabled="loading || savingCode === `${resource.baseCode}.${action.key}`"
                      @change="setPermission(`${resource.baseCode}.${action.key}`, $event.target.checked)"
                    />
                  </label>
                  <span v-else class="text-slate-300 dark:text-slate-700">-</span>
                </td>
                <td class="px-5 py-4">
                  <div class="flex justify-end gap-2">
                    <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="applyResource(resource, 'view')">
                      View
                    </button>
                    <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="applyResource(resource, 'crud')">
                      CRUD
                    </button>
                    <button class="rounded-xl bg-brand-600 px-3 py-2 text-xs font-bold text-white hover:bg-brand-700" @click="applyResource(resource, 'all')">
                      Semua
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>
