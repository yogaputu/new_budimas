<script setup>
import { ref } from 'vue';
import ShipmentPickingPanel from '@/modules/wms/components/ShipmentPickingPanel.vue';
import PickingHistory from './PickingPage.vue';
const history = ref(false);
</script>
<template><div class="space-y-4"><div class="flex gap-3"><button class="rounded-lg border px-4 py-2" @click="history=false">Picking Draf Kiriman</button><button class="rounded-lg border px-4 py-2" @click="history=true">Riwayat operasional</button></div><PickingHistory v-if="history" history-only /><ShipmentPickingPanel v-else /></div></template>
