<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { getAllCustomers, getBranches, getCompanies, getRoutes } from '@/api/master';
import { useAuthStore } from '@/stores/auth';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import { getRowBranchIds, getRowCompanyIds, scopeRowsByLoginBranch } from '@/utils/accessScope';
import {
  getBranchOptionsForCompany,
  getCompanyOptionsForScope,
  resetBranchWhenCompanyChanges
} from '@/utils/filterScope';
import AppFormField from '@/shared/components/AppFormField.vue';
import AppSearchSelect from '@/shared/components/AppSearchSelect.vue';
import PageHeader from '@/shared/components/PageHeader.vue';

const auth = useAuthStore();

const mapRef = ref(null);
const loading = reactive({ data: false, map: false });
const error = ref('');
const feedback = ref('');
const companies = ref([]);
const branches = ref([]);
const routes = ref([]);
const customers = ref([]);
const selectedRouteId = ref('');
const selectedCustomerKey = ref('');
const customerSearch = ref('');

const filters = reactive({
  companyId: '',
  branchId: '',
  routeId: '',
  speedKmh: 28,
  serviceMinutes: 8,
  optimizeRoute: true
});

let leafletLoader = null;
let mapInstance = null;
let routeLayer = null;
let markerLayer = null;
let markerMap = new Map();
let mapRenderToken = 0;
const roadRouteCache = new Map();
const knownDepotCoordinates = [
  {
    key: 'budimas-solo',
    latitude: -7.538837000000001,
    longitude: 110.8325702,
    name: 'Kantor Cabang Budimas Makmur Mulia Solo',
    address: 'Jl. Gn. Slamet IV, Mojosongo, Jebres, Kota Surakarta, Jawa Tengah 57136',
    matcher: (text) => (
      (text.includes('budimas') || text.includes('bmm') || text.includes('makmur mulia'))
      && (text.includes('solo') || text.includes('slo') || text.includes('mojosongo') || text.includes('gn. slamet') || text.includes('gunung slamet'))
    )
  }
];

const companyOptions = computed(() => getCompanyOptionsForScope(companies.value, auth, true));

const branchOptions = computed(() =>
  getBranchOptionsForCompany(branches.value, auth, filters.companyId, true, companies.value)
);

const scopedRoutes = computed(() => {
  const companyId = String(filters.companyId || '');
  const branchId = String(filters.branchId || '');

  return scopeRowsByLoginBranch(routes.value, auth).filter((route) => {
    const routeBranchIds = getRowBranchIds(route);
    const routeCompanyIds = getRowCompanyIds(route);
    const branchMatches = !branchId || routeBranchIds.includes(branchId);
    const companyMatches = !companyId || routeCompanyIds.includes(companyId) || branchMatchesCompanyRows(routeBranchIds, companyId);
    return branchMatches && companyMatches;
  });
});

const routeOptions = computed(() => [
  { value: '', label: 'Semua rute' },
  ...scopedRoutes.value.map((route) => ({
    value: String(route.id),
    label: `${route.kode ? `${route.kode} - ` : ''}${route.nama_rute || route.nama || `Rute ${route.id}`}`
  }))
]);

const selectedRoute = computed(() =>
  routeReports.value.find((route) => String(route.id) === String(selectedRouteId.value)) || defaultRouteReport() || null
);

const visibleCustomers = computed(() => {
  const route = selectedRoute.value;
  if (!route) return [];

  const keyword = customerSearch.value.trim().toLowerCase();
  if (!keyword) return route.customers;

  return route.customers.filter((customer) =>
    [
      customer.kode,
      customer.nama,
      customer.alamat,
      customer.nama_cabang,
      customer.nama_perusahaan_list,
      customer.nama_perusahaan
    ]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(keyword))
  );
});

const routeReports = computed(() => {
  const routeMap = new Map(scopedRoutes.value.map((route) => [String(route.id), route]));
  const companyId = String(filters.companyId || '');
  const branchId = String(filters.branchId || '');
  const routeId = String(filters.routeId || '');

  const grouped = scopedRoutes.value.map((route) => ({
    ...route,
    id: String(route.id),
    customers: []
  }));

  const groupedMap = new Map(grouped.map((route) => [String(route.id), route]));

  normalizedCustomers.value.forEach((customer) => {
    const customerRouteId = String(customer.id_rute || '');
    if (!customerRouteId || !routeMap.has(customerRouteId)) return;
    if (routeId && customerRouteId !== routeId) return;
    if (branchId && !getRowBranchIds(customer).includes(branchId)) return;
    if (companyId && !getRowCompanyIds(customer).includes(companyId)) return;

    groupedMap.get(customerRouteId)?.customers.push(customer);
  });

  return grouped
    .filter((route) => !routeId || String(route.id) === routeId)
    .map((route) => {
      const baseCustomers = route.customers
        .sort((left, right) => String(left.nama || '').localeCompare(String(right.nama || ''), 'id'))
        .map((customer, index) => ({ ...customer, sequence: index + 1 }));
      const depot = depotPointForRoute(route);
      const coordinateCustomers = baseCustomers.filter((customer) => customer.hasValidCoordinate);
      const orderedPointCustomers = filters.optimizeRoute ? nearestNeighborOrder(coordinateCustomers, depot) : coordinateCustomers;
      const orderedKeys = new Set(orderedPointCustomers.map((customer) => String(customer.markerKey)));
      const customersSorted = [
        ...orderedPointCustomers,
        ...baseCustomers.filter((customer) => !orderedKeys.has(String(customer.markerKey)))
      ].map((customer, index) => ({ ...customer, sequence: index + 1 }));
      const points = customersSorted.filter((customer) => customer.hasValidCoordinate);
      const routePathPoints = depot ? [depot, ...points] : points;
      const distanceKm = calculateRouteDistance(routePathPoints);
      const travelMinutes = estimateMinutes(distanceKm, points.length);

      return {
        ...route,
        depot,
        hasDepotCoordinate: Boolean(depot),
        customers: customersSorted,
        pointCustomers: points,
        routePathPoints,
        customerCount: customersSorted.length,
        pointCount: points.length,
        missingCoordinateCount: customersSorted.length - points.length,
        distanceKm,
        travelMinutes
      };
    })
    .sort((left, right) => {
      const priority = Number(left.prioritas || 0) - Number(right.prioritas || 0);
      if (priority) return priority;
      return String(left.nama_rute || '').localeCompare(String(right.nama_rute || ''), 'id');
    });
});

const normalizedCustomers = computed(() =>
  scopeRowsByLoginBranch(customers.value, auth).map((customer, index) => {
    const latitudeNumber = Number(customer.latitude);
    const longitudeNumber = Number(customer.longitude);
    const hasValidCoordinate =
      Number.isFinite(latitudeNumber)
      && Number.isFinite(longitudeNumber)
      && latitudeNumber >= -11
      && latitudeNumber <= 6
      && longitudeNumber >= 95
      && longitudeNumber <= 141;

    return {
      ...customer,
      markerKey: String(customer.id || customer.kode || index),
      latitudeNumber,
      longitudeNumber,
      hasValidCoordinate
    };
  })
);

const summaryCards = computed(() => {
  const routesWithCustomer = routeReports.value.filter((route) => route.customerCount).length;
  const customerCount = routeReports.value.reduce((sum, route) => sum + route.customerCount, 0);
  const pointCount = routeReports.value.reduce((sum, route) => sum + route.pointCount, 0);
  const distanceKm = routeReports.value.reduce((sum, route) => sum + route.distanceKm, 0);

  return [
    { label: 'Rute', value: numberLabel(routeReports.value.length) },
    { label: 'Rute Berisi Customer', value: numberLabel(routesWithCustomer) },
    { label: 'Customer', value: numberLabel(customerCount) },
    { label: 'Titik Map', value: `${numberLabel(pointCount)} / ${distanceLabel(distanceKm)}` }
  ];
});

function branchMatchesCompanyRows(branchIds, companyId) {
  if (!companyId || !branchIds.length) return true;
  return companies.value.some((company) =>
    String(company.id) === String(companyId)
    && getRowBranchIds(company).some((branchId) => branchIds.includes(String(branchId)))
  );
}

function defaultRouteReport() {
  return routeReports.value.find((route) => route.pointCount) || routeReports.value.find((route) => route.customerCount) || routeReports.value[0] || null;
}

function activeBranchId() {
  return String(auth.user?.cabang?.id || auth.user?.cabang_id || auth.user?.id_cabang || '');
}

function activeCompanyId(branchId = '') {
  return String(
    auth.user?.perusahaan?.id ||
    auth.user?.id_perusahaan ||
    branches.value.find((item) => String(item.id) === String(branchId))?.id_perusahaan ||
    ''
  );
}

function numberLabel(value) {
  return Number(value || 0).toLocaleString('id-ID');
}

function distanceLabel(value) {
  return `${Number(value || 0).toLocaleString('id-ID', { maximumFractionDigits: 1 })} km`;
}

function durationLabel(minutes) {
  const total = Math.max(0, Math.round(Number(minutes || 0)));
  const hours = Math.floor(total / 60);
  const minute = total % 60;
  if (!hours) return `${minute} menit`;
  return `${hours} jam ${minute} menit`;
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function haversineKm(left, right) {
  const radiusKm = 6371;
  const toRad = (value) => (Number(value) * Math.PI) / 180;
  const dLat = toRad(right.latitudeNumber - left.latitudeNumber);
  const dLon = toRad(right.longitudeNumber - left.longitudeNumber);
  const lat1 = toRad(left.latitudeNumber);
  const lat2 = toRad(right.latitudeNumber);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return radiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function calculateRouteDistance(points = []) {
  return points.reduce((sum, point, index) => {
    if (index === 0) return sum;
    return sum + haversineKm(points[index - 1], point);
  }, 0);
}

function firstCoordinateValue(row, keys = []) {
  for (const key of keys) {
    const value = Number(row?.[key]);
    if (Number.isFinite(value)) return value;
  }
  return null;
}

function isValidIndonesiaCoordinate(latitude, longitude) {
  return Number.isFinite(latitude)
    && Number.isFinite(longitude)
    && latitude >= -11
    && latitude <= 6
    && longitude >= 95
    && longitude <= 141;
}

function depotPointForRoute(route) {
  const branchId = String(route?.id_cabang || route?.cabang_id || filters.branchId || '');
  const branch = branches.value.find((item) => String(item.id) === branchId);
  if (!branch) return null;

  const latitudeNumber = firstCoordinateValue(branch, ['latitude', 'lat', 'latitude_cabang', 'lat_cabang', 'koordinat_lat']);
  const longitudeNumber = firstCoordinateValue(branch, ['longitude', 'lng', 'long', 'longitude_cabang', 'lng_cabang', 'koordinat_lng']);
  const fallbackDepot = !isValidIndonesiaCoordinate(latitudeNumber, longitudeNumber)
    ? knownDepotForBranch(branch, route)
    : null;
  const resolvedLatitude = fallbackDepot?.latitude ?? latitudeNumber;
  const resolvedLongitude = fallbackDepot?.longitude ?? longitudeNumber;

  if (!isValidIndonesiaCoordinate(resolvedLatitude, resolvedLongitude)) return null;

  return {
    ...branch,
    isDepot: true,
    markerKey: `branch-${branch.id}`,
    sequence: 0,
    kode: branch.kode || 'CABANG',
    nama: fallbackDepot?.name || `Kantor Cabang ${branch.nama || branch.nama_cabang || branch.kode || ''}`.trim(),
    alamat: branch.alamat || fallbackDepot?.address || '-',
    latitudeNumber: resolvedLatitude,
    longitudeNumber: resolvedLongitude,
    hasValidCoordinate: true
  };
}

function knownDepotForBranch(branch, route) {
  const companyNames = companies.value
    .filter((company) => getRowCompanyIds(route).includes(String(company.id)) || getRowBranchIds(company).includes(String(branch?.id)))
    .map((company) => `${company.kode || ''} ${company.nama || company.nama_perusahaan || ''}`);
  const text = [
    branch?.kode,
    branch?.nama,
    branch?.nama_cabang,
    branch?.alamat,
    route?.kode,
    route?.nama_rute,
    route?.nama_cabang,
    route?.nama_perusahaan,
    route?.nama_perusahaan_list,
    ...companyNames
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  return knownDepotCoordinates.find((depot) => depot.matcher(text)) || null;
}

function nearestNeighborOrder(points = [], depot = null) {
  if (points.length < 2) return points;

  const remaining = [...points];
  const ordered = [];
  let current = depot || remaining.shift();
  if (!depot && current) ordered.push(current);

  while (remaining.length) {
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;

    remaining.forEach((point, index) => {
      const distance = haversineKm(current, point);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestIndex = index;
      }
    });

    const [nextPoint] = remaining.splice(nearestIndex, 1);
    ordered.push(nextPoint);
    current = nextPoint;
  }

  return ordered;
}

function routeCacheKey(points = []) {
  return points
    .map((point) => `${Number(point.latitudeNumber).toFixed(6)},${Number(point.longitudeNumber).toFixed(6)}`)
    .join('|');
}

function chunkRoutePoints(points = [], chunkSize = 45) {
  if (points.length <= chunkSize) return [points];

  const chunks = [];
  for (let start = 0; start < points.length - 1; start += chunkSize - 1) {
    chunks.push(points.slice(start, Math.min(start + chunkSize, points.length)));
  }
  return chunks.filter((chunk) => chunk.length >= 2);
}

async function fetchRoadRouteLatLngs(points = []) {
  if (points.length < 2) {
    return points.map((point) => [point.latitudeNumber, point.longitudeNumber]);
  }

  const cacheKey = routeCacheKey(points);
  if (roadRouteCache.has(cacheKey)) {
    return roadRouteCache.get(cacheKey);
  }

  const routedLatLngs = [];
  const chunks = chunkRoutePoints(points);

  for (const chunk of chunks) {
    const coordinates = chunk
      .map((point) => `${point.longitudeNumber},${point.latitudeNumber}`)
      .join(';');
    const url = `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson&steps=false`;
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error('Rute jalan belum bisa dimuat.');
    }

    const payload = await response.json();
    const routeCoordinates = payload?.routes?.[0]?.geometry?.coordinates;
    if (!Array.isArray(routeCoordinates) || !routeCoordinates.length) {
      throw new Error('Rute jalan kosong.');
    }

    const latLngs = routeCoordinates.map(([lng, lat]) => [lat, lng]);
    if (routedLatLngs.length && latLngs.length) {
      latLngs.shift();
    }
    routedLatLngs.push(...latLngs);
  }

  const fallbackLatLngs = points.map((point) => [point.latitudeNumber, point.longitudeNumber]);
  const result = routedLatLngs.length ? routedLatLngs : fallbackLatLngs;
  roadRouteCache.set(cacheKey, result);
  return result;
}

function estimateMinutes(distanceKm, stopCount) {
  const speed = Math.max(1, Number(filters.speedKmh || 28));
  const serviceMinutes = Math.max(0, Number(filters.serviceMinutes || 0));
  return (Number(distanceKm || 0) / speed) * 60 + Number(stopCount || 0) * serviceMinutes;
}

function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (leafletLoader) return leafletLoader;

  leafletLoader = new Promise((resolve, reject) => {
    if (!document.querySelector('link[data-leaflet-runtime="true"]')) {
      const link = document.createElement('link');
      link.rel = 'stylesheet';
      link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
      link.dataset.leafletRuntime = 'true';
      document.head.appendChild(link);
    }

    const existingScript = document.querySelector('script[data-leaflet-runtime="true"]');
    if (existingScript) {
      existingScript.addEventListener('load', () => resolve(window.L));
      existingScript.addEventListener('error', () => reject(new Error('Leaflet gagal dimuat.')));
      return;
    }

    const script = document.createElement('script');
    script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
    script.async = true;
    script.dataset.leafletRuntime = 'true';
    script.onload = () => resolve(window.L);
    script.onerror = () => reject(new Error('Leaflet gagal dimuat.'));
    document.body.appendChild(script);
  });

  return leafletLoader;
}

function destroyMap() {
  markerMap.clear();
  if (mapInstance) {
    mapInstance.remove();
    mapInstance = null;
    routeLayer = null;
    markerLayer = null;
  }
}

function markerIcon(L, point, active = false) {
  const size = active ? 34 : 28;
  const core = active ? 18 : 14;
  const isDepot = Boolean(point?.isDepot);
  const haloColor = isDepot ? '#fed7aa' : active ? '#dcfce7' : '#bbf7d0';
  const coreColor = isDepot ? '#f97316' : '#16a34a';
  const borderColor = isDepot ? '#9a3412' : '#166534';

  return L.divIcon({
    className: '',
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -(size / 2)],
    html: `
      <div style="position:relative;width:${size}px;height:${size}px;display:flex;align-items:center;justify-content:center;">
        <div style="position:absolute;width:${size}px;height:${size}px;border-radius:999px;background:${haloColor};border:2px solid #ffffff;box-shadow:0 10px 22px rgba(15,23,42,.26);"></div>
        <div style="position:absolute;width:${core}px;height:${core}px;border-radius:999px;background:${coreColor};border:3px solid ${borderColor};"></div>
      </div>
    `
  });
}

function popupHtml(customer) {
  if (customer?.isDepot) {
    return `
      <div style="min-width:220px;font-family:Arial,sans-serif;color:#0f172a;">
        <div style="font-weight:800;margin-bottom:4px;">Start: ${escapeHtml(customer.nama || 'Kantor Cabang')}</div>
        <div style="font-size:12px;line-height:1.6;">
          <div><strong>Kode:</strong> ${escapeHtml(customer.kode || '-')}</div>
          <div><strong>Alamat:</strong> ${escapeHtml(customer.alamat || '-')}</div>
        </div>
      </div>
    `;
  }

  return `
    <div style="min-width:240px;font-family:Arial,sans-serif;color:#0f172a;">
      <div style="font-weight:800;margin-bottom:4px;">${escapeHtml(customer.sequence)}. ${escapeHtml(customer.nama || 'Customer')}</div>
      <div style="font-size:12px;line-height:1.6;">
        <div><strong>Kode:</strong> ${escapeHtml(customer.kode || '-')}</div>
        <div><strong>Cabang:</strong> ${escapeHtml(customer.nama_cabang || customer.nama_cabang_list || '-')}</div>
        <div><strong>Alamat:</strong> ${escapeHtml(customer.alamat || '-')}</div>
      </div>
    </div>
  `;
}

function updateMarkerIcons() {
  if (!window.L) return;
  markerMap.forEach(({ marker, customer }) => {
    marker.setIcon(markerIcon(window.L, customer, String(customer.markerKey) === String(selectedCustomerKey.value)));
  });
}

function focusCustomer(customer, options = {}) {
  if (!customer?.markerKey || !markerMap.has(String(customer.markerKey))) return;
  const entry = markerMap.get(String(customer.markerKey));
  selectedCustomerKey.value = String(customer.markerKey);
  updateMarkerIcons();

  if (options.fly !== false && mapInstance) {
    mapInstance.flyTo(entry.marker.getLatLng(), Math.max(mapInstance.getZoom(), 15), { duration: 0.45 });
    entry.marker.openPopup();
  }
}

async function renderMap() {
  await nextTick();
  const renderToken = ++mapRenderToken;
  if (!mapRef.value || !selectedRoute.value?.routePathPoints?.length) {
    destroyMap();
    return;
  }

  loading.map = true;
  try {
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
    const pathPoints = selectedRoute.value.routePathPoints;
    const points = selectedRoute.value.pointCustomers;
    const fallbackPathLatLngs = pathPoints.map((point) => [point.latitudeNumber, point.longitudeNumber]);
    let latLngs = fallbackPathLatLngs;

    try {
      latLngs = await fetchRoadRouteLatLngs(pathPoints);
      if (renderToken !== mapRenderToken) return;
    } catch (routeError) {
      if (renderToken !== mapRenderToken) return;
      console.warn(routeError);
      feedback.value = 'Polyline memakai garis langsung karena rute jalan belum bisa dimuat.';
    }

    if (latLngs.length >= 2) {
      routeLayer = L.polyline(latLngs, {
        color: '#0284c7',
        weight: 5,
        opacity: 0.82,
        lineJoin: 'round'
      }).addTo(mapInstance);
    }

    if (selectedRoute.value.depot) {
      const depot = selectedRoute.value.depot;
      const marker = L.marker([depot.latitudeNumber, depot.longitudeNumber], {
        icon: markerIcon(L, depot, false)
      });
      marker.bindPopup(popupHtml(depot));
      marker.addTo(markerLayer);
    }

    points.forEach((customer) => {
      const marker = L.marker([customer.latitudeNumber, customer.longitudeNumber], {
        icon: markerIcon(L, customer, String(customer.markerKey) === String(selectedCustomerKey.value))
      });
      marker.bindPopup(popupHtml(customer));
      marker.on('click', () => focusCustomer(customer, { fly: false }));
      marker.addTo(markerLayer);
      markerMap.set(String(customer.markerKey), { marker, customer });
    });

    const boundsLayers = routeLayer ? [routeLayer, markerLayer] : [markerLayer];
    const bounds = L.featureGroup(boundsLayers).getBounds();
    if (bounds.isValid()) {
      mapInstance.fitBounds(bounds.pad(0.16), { maxZoom: 14 });
    }
  } finally {
    loading.map = false;
  }
}

function applyFilters() {
  selectedRouteId.value = filters.routeId || defaultRouteReport()?.id || '';
  selectedCustomerKey.value = selectedRoute.value?.pointCustomers?.[0]?.markerKey || '';
  customerSearch.value = '';
  feedback.value = `Laporan memuat ${numberLabel(routeReports.value.length)} rute.`;
  renderMap();
}

function resetFilters() {
  filters.routeId = '';
  filters.speedKmh = 28;
  filters.serviceMinutes = 8;
  filters.optimizeRoute = true;
  applyFilters();
}

async function loadData() {
  loading.data = true;
  error.value = '';
  feedback.value = '';

  try {
    const [companyResponse, branchResponse, routeResponse, customerResponse] = await Promise.all([
      getCompanies(),
      getBranches(),
      getRoutes(),
      getAllCustomers()
    ]);

    companies.value = normalizeList(unwrapResponse(companyResponse));
    branches.value = normalizeList(unwrapResponse(branchResponse));
    routes.value = normalizeList(unwrapResponse(routeResponse));
    customers.value = normalizeList(unwrapResponse(customerResponse));

    const branchId = activeBranchId();
    if (!filters.branchId && branchId) {
      filters.branchId = branchId;
    }
    if (!filters.companyId) {
      filters.companyId = activeCompanyId(filters.branchId);
    }
    applyFilters();
  } catch (err) {
    error.value = normalizeError(err, 'Laporan rute customer belum bisa dimuat.');
    routes.value = [];
    customers.value = [];
    destroyMap();
  } finally {
    loading.data = false;
  }
}

watch(
  () => filters.companyId,
  () => {
    const branchReset = resetBranchWhenCompanyChanges(filters, 'companyId', 'branchId', branches.value, auth, companies.value);
    if (branchReset) filters.routeId = '';
    if (!routeOptions.value.some((option) => String(option.value) === String(filters.routeId))) {
      filters.routeId = '';
    }
  }
);

watch(
  () => filters.branchId,
  () => {
    if (!routeOptions.value.some((option) => String(option.value) === String(filters.routeId))) {
      filters.routeId = '';
    }
  }
);

watch(selectedRouteId, async () => {
  selectedCustomerKey.value = selectedRoute.value?.pointCustomers?.[0]?.markerKey || '';
  await renderMap();
});

watch(selectedCustomerKey, updateMarkerIcons);

onMounted(loadData);
onBeforeUnmount(destroyMap);
</script>

<template>
  <div class="space-y-5">
    <PageHeader
      title="Rute Customer"
      description="Daftar rute, customer, polyline map, dan estimasi perjalanan berdasarkan titik koordinat customer."
    >
      <button
        class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900"
        :disabled="loading.data"
        @click="loadData"
      >
        {{ loading.data ? 'Memuat...' : 'Refresh' }}
      </button>
    </PageHeader>

    <section v-if="error" class="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-semibold text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-100">
      {{ error }}
    </section>

    <section class="panel p-4">
      <div class="route-report-filter">
        <section class="route-report-filter-group">
          <p class="route-report-filter-title">Cakupan laporan</p>
          <div class="route-report-filter-grid">
            <AppSearchSelect v-model="filters.companyId" label="Perusahaan" placeholder="Semua perusahaan" :options="companyOptions" :loading="loading.data" />
            <AppSearchSelect v-model="filters.branchId" label="Cabang" placeholder="Semua cabang" :options="branchOptions" :disabled="!filters.companyId" empty-text="Pilih perusahaan terlebih dahulu." />
            <AppSearchSelect v-model="filters.routeId" label="Rute" placeholder="Semua rute" :options="routeOptions" empty-text="Rute belum tersedia untuk filter ini." />
          </div>
        </section>

        <section class="route-report-filter-group">
          <p class="route-report-filter-title">Estimasi perjalanan</p>
          <div class="route-report-filter-grid">
            <AppFormField v-model="filters.speedKmh" label="Kecepatan km/jam" type="number" min="1" max="120" />
            <AppFormField v-model="filters.serviceMinutes" label="Menit per customer" type="number" min="0" max="180" />
            <label class="route-report-checkbox">
              <span>Optimasi Rute</span>
              <input v-model="filters.optimizeRoute" type="checkbox" />
              <strong>Terdekat</strong>
            </label>
          </div>
        </section>

        <div class="route-report-actions">
          <button class="rounded-xl bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700 disabled:opacity-60" :disabled="loading.data" @click="applyFilters">
            Terapkan
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-900" @click="resetFilters">
            Reset
          </button>
          <span v-if="feedback">{{ feedback }}</span>
        </div>
      </div>
    </section>

    <section class="grid gap-2 md:grid-cols-4">
      <article v-for="card in summaryCards" :key="card.label" class="route-report-card">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
      </article>
    </section>

    <section class="route-report-layout">
      <aside class="route-report-list">
        <div class="route-report-list-head">
          <div>
            <p>Daftar Rute</p>
            <strong>{{ numberLabel(routeReports.length) }}</strong>
          </div>
        </div>

        <button
          v-for="route in routeReports"
          :key="route.id"
          type="button"
          :class="['route-report-route', { active: String(route.id) === String(selectedRouteId || selectedRoute?.id) }]"
          @click="selectedRouteId = String(route.id)"
        >
          <span>
            <strong>{{ route.nama_rute || route.nama || '-' }}</strong>
            <small>{{ route.kode || '-' }} | {{ route.nama_cabang || 'Cabang belum terbaca' }}</small>
          </span>
          <em>{{ numberLabel(route.customerCount) }}</em>
        </button>

        <p v-if="!routeReports.length && !loading.data" class="route-report-muted">Belum ada rute untuk filter ini.</p>
      </aside>

      <div class="route-report-main">
        <section class="route-report-map-wrap">
          <div ref="mapRef" class="route-report-map"></div>
          <div v-if="loading.data || loading.map" class="route-report-overlay">Memuat peta...</div>
          <div v-else-if="!selectedRoute?.pointCount" class="route-report-overlay">Belum ada titik koordinat customer.</div>
          <div class="route-report-map-summary">
            <span>{{ selectedRoute?.nama_rute || 'Rute' }}</span>
            <strong>{{ distanceLabel(selectedRoute?.distanceKm) }} | {{ durationLabel(selectedRoute?.travelMinutes) }}</strong>
            <small>{{ selectedRoute?.hasDepotCoordinate ? `Start ${selectedRoute?.depot?.nama || 'kantor cabang'}` : 'Start cabang belum punya koordinat' }}</small>
          </div>
        </section>

        <section class="route-report-detail">
          <div class="route-report-detail-head">
            <div>
              <p>Customer Rute</p>
              <h3>{{ selectedRoute?.nama_rute || '-' }}</h3>
            </div>
            <div class="route-report-metrics">
              <span>{{ numberLabel(selectedRoute?.customerCount) }} customer</span>
              <span>{{ numberLabel(selectedRoute?.missingCoordinateCount) }} tanpa titik</span>
              <span>{{ selectedRoute?.hasDepotCoordinate ? 'start dari cabang' : 'tanpa titik cabang' }}</span>
              <span>{{ filters.optimizeRoute ? 'urut terdekat' : 'urut master' }}</span>
              <span>{{ durationLabel(selectedRoute?.travelMinutes) }}</span>
            </div>
          </div>

          <div class="route-report-search">
            <input v-model="customerSearch" type="search" placeholder="Cari customer, kode, alamat" />
          </div>

          <div class="route-report-table-wrap">
            <table class="route-report-table">
              <thead>
                <tr>
                  <th>No</th>
                  <th>Customer</th>
                  <th>Alamat</th>
                  <th>Koordinat</th>
                  <th>Map</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="customer in visibleCustomers" :key="customer.markerKey" :class="{ active: String(customer.markerKey) === String(selectedCustomerKey) }">
                  <td>{{ customer.sequence }}</td>
                  <td>
                    <strong>{{ customer.nama || '-' }}</strong>
                    <small>{{ customer.kode || '-' }}</small>
                  </td>
                  <td>{{ customer.alamat || '-' }}</td>
                  <td>{{ customer.hasValidCoordinate ? `${customer.latitude}, ${customer.longitude}` : '-' }}</td>
                  <td>
                    <button v-if="customer.hasValidCoordinate" type="button" @click="focusCustomer(customer)">Lihat</button>
                    <span v-else>Tidak ada titik</span>
                  </td>
                </tr>
                <tr v-if="!visibleCustomers.length">
                  <td colspan="5" class="empty">Belum ada customer pada rute ini.</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.route-report-filter {
  display: grid;
  gap: 18px;
  min-width: 0;
  container-type: inline-size;
}

.route-report-filter-group {
  min-width: 0;
}

.route-report-filter-title {
  margin: 0 0 10px;
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.route-report-filter-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(220px, 1fr));
  align-items: end;
  gap: 16px;
}

.route-report-filter-grid > :deep(label) {
  min-width: 0;
}

.route-report-actions {
  display: flex;
  flex-wrap: wrap;
  grid-column: 1 / -1;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  min-width: 0;
}

.route-report-checkbox {
  display: flex;
  min-height: 42px;
  align-items: center;
  gap: 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(248, 250, 252, 0.92);
  padding: 8px 10px;
}

.dark .route-report-checkbox {
  background: rgba(15, 23, 42, 0.72);
}

.route-report-checkbox span {
  flex: 1;
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0;
  text-transform: uppercase;
}

.route-report-checkbox input {
  width: 16px;
  height: 16px;
  accent-color: #0284c7;
}

.route-report-checkbox strong {
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.dark .route-report-checkbox strong {
  color: #f8fafc;
}

.route-report-actions span {
  flex-basis: 100%;
  color: #0369a1;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.35;
  text-align: left;
}

@container (max-width: 820px) {
  .route-report-filter-grid {
    grid-template-columns: repeat(2, minmax(220px, 1fr));
  }
}

@container (max-width: 560px) {
  .route-report-filter-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

.route-report-card {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.9);
  padding: 12px 14px;
}

.dark .route-report-card {
  background: rgba(15, 23, 42, 0.78);
}

.route-report-card span,
.route-report-list-head p,
.route-report-detail-head p {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.route-report-card strong {
  display: block;
  margin-top: 6px;
  color: #0f172a;
  font-size: 24px;
  line-height: 1;
}

.dark .route-report-card strong {
  color: #f8fafc;
}

.route-report-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 14px;
  min-height: 620px;
}

.route-report-list,
.route-report-detail {
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: rgba(255, 255, 255, 0.92);
}

.dark .route-report-list,
.dark .route-report-detail {
  background: rgba(15, 23, 42, 0.82);
}

.route-report-list {
  max-height: 720px;
  overflow: auto;
  padding: 12px;
}

.route-report-list-head {
  margin-bottom: 10px;
}

.route-report-list-head strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 20px;
  font-weight: 900;
}

.dark .route-report-list-head strong {
  color: #f8fafc;
}

.route-report-route {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid transparent;
  border-bottom-color: rgba(148, 163, 184, 0.14);
  padding: 10px 8px;
  text-align: left;
}

.route-report-route:hover,
.route-report-route.active {
  border-color: rgba(14, 165, 233, 0.34);
  background: rgba(14, 165, 233, 0.08);
}

.route-report-route span {
  min-width: 0;
}

.route-report-route strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  line-height: 1.25;
  overflow-wrap: anywhere;
}

.route-report-route small {
  display: block;
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.3;
}

.dark .route-report-route strong {
  color: #f8fafc;
}

.dark .route-report-route small {
  color: #94a3b8;
}

.route-report-route em {
  flex: 0 0 auto;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.08);
  color: #0f172a;
  font-size: 11px;
  font-style: normal;
  font-weight: 900;
  padding: 4px 7px;
}

.dark .route-report-route em {
  background: rgba(148, 163, 184, 0.16);
  color: #f8fafc;
}

.route-report-main {
  display: grid;
  grid-template-rows: 420px minmax(0, 1fr);
  gap: 14px;
  min-width: 0;
}

.route-report-map-wrap {
  position: relative;
  min-height: 0;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.22);
  background: #0f172a;
}

.route-report-map {
  width: 100%;
  height: 100%;
}

:deep(.leaflet-container) {
  width: 100%;
  height: 100%;
  font-family: inherit;
}

.route-report-overlay,
.route-report-map-summary {
  position: absolute;
  z-index: 500;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(2, 6, 23, 0.78);
  color: #f8fafc;
  backdrop-filter: blur(14px);
}

.route-report-overlay {
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  padding: 12px 16px;
  font-weight: 800;
}

.route-report-map-summary {
  left: 14px;
  bottom: 14px;
  max-width: calc(100% - 28px);
  padding: 10px 12px;
}

.route-report-map-summary span {
  display: block;
  color: #bae6fd;
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}

.route-report-map-summary strong {
  display: block;
  margin-top: 4px;
  font-size: 14px;
  line-height: 1.25;
}

.route-report-map-summary small {
  display: block;
  margin-top: 4px;
  color: #e0f2fe;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.3;
}

.route-report-detail {
  min-width: 0;
  padding: 14px;
}

.route-report-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.route-report-detail-head h3 {
  margin-top: 4px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 900;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.dark .route-report-detail-head h3 {
  color: #f8fafc;
}

.route-report-metrics {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.route-report-metrics span {
  border-radius: 999px;
  background: rgba(14, 165, 233, 0.12);
  color: #0369a1;
  font-size: 11px;
  font-weight: 900;
  padding: 5px 8px;
}

.route-report-search {
  margin-top: 12px;
}

.route-report-search input {
  width: 100%;
  border: 1px solid rgba(148, 163, 184, 0.28);
  background: rgba(248, 250, 252, 0.9);
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  outline: none;
  padding: 9px 10px;
}

.dark .route-report-search input {
  background: rgba(15, 23, 42, 0.72);
  color: #f8fafc;
}

.route-report-table-wrap {
  margin-top: 12px;
  overflow: auto;
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.route-report-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}

.route-report-table th,
.route-report-table td {
  border-bottom: 1px solid rgba(148, 163, 184, 0.16);
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
}

.route-report-table th {
  background: rgba(15, 23, 42, 0.04);
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
  text-transform: uppercase;
}

.dark .route-report-table th {
  background: rgba(148, 163, 184, 0.08);
}

.route-report-table td {
  color: #0f172a;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.35;
}

.dark .route-report-table td {
  color: #f8fafc;
}

.route-report-table tr.active td {
  background: rgba(14, 165, 233, 0.08);
}

.route-report-table td strong,
.route-report-table td small {
  display: block;
}

.route-report-table td small {
  margin-top: 2px;
  color: #64748b;
}

.route-report-table button {
  border-radius: 10px;
  background: #0284c7;
  color: #fff;
  font-size: 11px;
  font-weight: 900;
  padding: 6px 9px;
}

.route-report-table span,
.route-report-muted {
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.route-report-table .empty {
  padding: 24px 12px;
  text-align: center;
}

@media (max-width: 1280px) {
  .route-report-layout {
    grid-template-columns: 1fr;
  }

  .route-report-list {
    max-height: 320px;
  }
}

@media (max-width: 760px) {
  .route-report-main {
    grid-template-rows: 380px minmax(0, 1fr);
  }

  .route-report-detail-head {
    display: block;
  }

  .route-report-metrics {
    justify-content: flex-start;
    margin-top: 10px;
  }
}
</style>
