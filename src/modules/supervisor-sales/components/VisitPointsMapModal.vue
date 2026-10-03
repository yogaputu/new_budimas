<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import AppModal from '@/shared/components/AppModal.vue';

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  points: {
    type: Array,
    default: () => []
  },
  selectedKey: {
    type: [String, Number],
    default: ''
  },
  title: {
    type: String,
    default: 'Peta Kunjungan Sales'
  },
  description: {
    type: String,
    default: 'Semua titik customer yang memiliki koordinat untuk filter aktif saya tampilkan di sini.'
  }
});

const emit = defineEmits(['close', 'select']);

const mapRef = ref(null);
const internalSelectedKey = ref('');
let leafletLoader = null;
let mapInstance = null;
let markerLayer = null;
let markerMap = new Map();

const validPoints = computed(() =>
  props.points
    .map((point, index) => ({
      ...point,
      markerKey: String(point.id_kunjungan || point.id_plafon || point.kode_customer || index)
    }))
    .filter((point) => {
      const lat = Number(point.latitude);
      const lng = Number(point.longitude);
      return Number.isFinite(lat) && Number.isFinite(lng);
    })
);

function close() {
  emit('close');
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function loadLeaflet() {
  if (window.L) {
    return Promise.resolve(window.L);
  }

  if (leafletLoader) {
    return leafletLoader;
  }

  leafletLoader = new Promise((resolve, reject) => {
    const existingCss = document.querySelector('link[data-leaflet-runtime="true"]');
    if (!existingCss) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      link.dataset.leafletRuntime = 'true';
      document.head.appendChild(link);
    }

    const existingScript = document.querySelector('script[data-leaflet-runtime="true"]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(window.L));
      existingScript.addEventListener('error', () => reject(new Error('Leaflet gagal dimuat dari CDN.')));
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.async = true;
    script.dataset.leafletRuntime = 'true';
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error('Leaflet gagal dimuat dari CDN.'));
    document.body.appendChild(script);
  });

  return leafletLoader;
}

function destroyMap() {
  markerMap.clear();
  if (mapInstance) {
    mapInstance.remove();
    mapInstance = null;
    markerLayer = null;
  }
}

function getMarkerTone(point) {
  const source = String(point.data_source || '').toLowerCase();
  const status = String(point.status_kunjungan_label || '').toLowerCase();

  if (source === 'actual') {
    return {
      bg: '#f59e0b',
      border: '#b45309',
      ring: '#fef3c7'
    };
  }

  if (status.includes('selesai')) {
    return {
      bg: '#10b981',
      border: '#047857',
      ring: '#d1fae5'
    };
  }

  if (status.includes('check in')) {
    return {
      bg: '#3b82f6',
      border: '#1d4ed8',
      ring: '#dbeafe'
    };
  }

  return {
    bg: '#ef4444',
    border: '#b91c1c',
    ring: '#fee2e2'
  };
}

function buildMarkerIcon(L, point, isActive = false) {
  const tone = getMarkerTone(point);
  const size = isActive ? 24 : 18;
  const ringSize = isActive ? 38 : 30;

  return L.divIcon({
    className: '',
    iconSize: [ringSize, ringSize],
    iconAnchor: [ringSize / 2, ringSize / 2],
    popupAnchor: [0, -(ringSize / 2)],
    html: `
      <div style="position:relative;width:${ringSize}px;height:${ringSize}px;display:flex;align-items:center;justify-content:center;">
        <div style="
          width:${ringSize}px;
          height:${ringSize}px;
          border-radius:999px;
          background:${isActive ? tone.ring : 'transparent'};
          opacity:${isActive ? '1' : '0'};
          transition:all .2s ease;
        "></div>
        <div style="
          position:absolute;
          width:${size}px;
          height:${size}px;
          border-radius:999px;
          background:${tone.bg};
          border:3px solid ${tone.border};
          box-shadow:0 6px 12px rgba(15,23,42,.18);
        "></div>
      </div>
    `
  });
}

function buildPopup(point) {
  const customer = escapeHtml(point.nama_customer || point.kode_customer || 'Customer');
  const sales = escapeHtml(point.nama_sales || '-');
  const principal = escapeHtml(point.nama_principal || '-');
  const status = escapeHtml(point.status_kunjungan_label || '-');
  const source = escapeHtml(point.data_source_label || '-');
  const order = escapeHtml(point.status_order_label || '-');

  return `
    <div style="min-width:220px;font-family:Arial,sans-serif;">
      <div style="font-weight:700;margin-bottom:6px;">${customer}</div>
      <div style="font-size:12px;line-height:1.55;">
        <div><strong>Sales:</strong> ${sales}</div>
        <div><strong>Principal:</strong> ${principal}</div>
        <div><strong>Status:</strong> ${status}</div>
        <div><strong>Sumber:</strong> ${source}</div>
        <div><strong>Order:</strong> ${order}</div>
      </div>
    </div>
  `;
}

function updateMarkerIcons(L) {
  markerMap.forEach(({ marker, point }) => {
    const isActive = String(point.markerKey) === String(internalSelectedKey.value || '');
    marker.setIcon(buildMarkerIcon(L, point, isActive));
  });
}

function focusPoint(markerKey, options = {}) {
  if (!mapInstance || !markerMap.has(String(markerKey))) {
    return;
  }

  const entry = markerMap.get(String(markerKey));
  internalSelectedKey.value = String(markerKey);
  updateMarkerIcons(window.L);

  if (options.emitSelect !== false) {
    emit('select', entry.point);
  }

  mapInstance.flyTo(entry.marker.getLatLng(), Math.max(mapInstance.getZoom(), 15), {
    duration: 0.6
  });
  entry.marker.openPopup();
}

async function renderMap() {
  if (!props.open) {
    return;
  }

  if (!validPoints.value.length) {
    destroyMap();
    return;
  }

  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 120));

  if (!mapRef.value) {
    return;
  }

  const L = await loadLeaflet();

  destroyMap();

  mapInstance = L.map(mapRef.value, {
    zoomControl: true,
    attributionControl: true
  });

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(mapInstance);

  markerLayer = L.featureGroup().addTo(mapInstance);

  validPoints.value.forEach((point) => {
    const lat = Number(point.latitude);
    const lng = Number(point.longitude);
    const marker = L.marker([lat, lng], {
      icon: buildMarkerIcon(L, point, String(point.markerKey) === String(internalSelectedKey.value || ''))
    });

    marker.bindPopup(buildPopup(point));
    marker.on('click', () => {
      internalSelectedKey.value = String(point.markerKey);
      updateMarkerIcons(L);
      emit('select', point);
    });

    marker.addTo(markerLayer);
    markerMap.set(String(point.markerKey), { marker, point });
  });

  const bounds = markerLayer.getBounds();
  if (bounds.isValid()) {
    mapInstance.fitBounds(bounds, { padding: [32, 32] });
  } else {
    mapInstance.setView([-7.5666, 110.8167], 10);
  }

  setTimeout(() => {
    if (mapInstance) {
      mapInstance.invalidateSize();
    }

    const preferredKey = internalSelectedKey.value || validPoints.value[0]?.markerKey;
    if (preferredKey) {
      focusPoint(preferredKey, { emitSelect: false });
    }
  }, 150);
}

watch(
  () => props.selectedKey,
  (value) => {
    if (!value) return;
    internalSelectedKey.value = String(value);
    if (props.open && mapInstance) {
      focusPoint(value, { emitSelect: false });
    }
  },
  { immediate: true }
);

watch(
  () => [props.open, validPoints.value.length],
  async ([open]) => {
    if (open) {
      await renderMap();
    } else {
      destroyMap();
    }
  },
  { flush: 'post' }
);

watch(
  () => props.points,
  async () => {
    if (props.open) {
      await renderMap();
    }
  },
  { deep: true, flush: 'post' }
);

onBeforeUnmount(() => {
  destroyMap();
});
</script>

<template>
  <AppModal
    :open="open"
    size="7xl"
    :title="title"
    :description="description"
    @close="close"
  >
    <div class="space-y-5">
      <div
        v-if="!validPoints.length"
        class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-500"
      >
        Belum ada titik customer yang punya koordinat untuk ditampilkan.
      </div>

      <div v-else class="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside class="flex h-[70vh] flex-col overflow-hidden rounded-3xl border border-slate-200 bg-slate-50">
          <div class="border-b border-slate-200 px-4 py-4">
            <h4 class="text-sm font-bold uppercase tracking-[0.2em] text-slate-500">Daftar Titik</h4>
            <p class="mt-1 text-xs text-slate-500">Klik salah satu customer untuk fokus ke marker terkait.</p>
          </div>

          <div class="flex-1 overflow-y-auto px-3 py-3">
            <button
              v-for="point in validPoints"
              :key="point.markerKey"
              :class="[
                'mb-3 w-full rounded-2xl border px-3 py-3 text-left transition',
                String(point.markerKey) === String(internalSelectedKey)
                  ? 'border-brand-300 bg-brand-50 shadow-sm'
                  : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
              ]"
              @click="focusPoint(point.markerKey)"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-slate-900">
                    {{ point.nama_customer || point.kode_customer || 'Customer' }}
                  </p>
                  <p class="mt-1 text-xs text-slate-500">{{ point.nama_sales || '-' }}</p>
                </div>
                <span
                  :class="[
                    'rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide',
                    point.data_source === 'actual'
                      ? 'bg-amber-100 text-amber-700'
                      : point.status_kunjungan_label?.includes('Selesai')
                        ? 'bg-emerald-100 text-emerald-700'
                        : point.status_kunjungan_label?.includes('Check In')
                          ? 'bg-sky-100 text-sky-700'
                          : 'bg-rose-100 text-rose-700'
                  ]"
                >
                  {{ point.status_kunjungan_label || 'Belum' }}
                </span>
              </div>

              <div class="mt-2 space-y-1 text-xs text-slate-500">
                <p>{{ point.nama_principal || '-' }}</p>
                <p>{{ point.data_source_label || '-' }}</p>
              </div>
            </button>
          </div>
        </aside>

        <div
          ref="mapRef"
          class="h-[70vh] w-full overflow-hidden rounded-3xl border border-slate-200"
        ></div>
      </div>

      <div v-if="validPoints.length" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
        {{ validPoints.length }} titik customer tampil di peta Leaflet untuk filter supervisor yang sedang aktif.
      </div>
    </div>
  </AppModal>
</template>
