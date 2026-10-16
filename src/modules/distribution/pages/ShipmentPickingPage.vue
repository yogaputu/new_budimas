<script setup>
import { ref } from 'vue';
import ShipmentPickingPanel from '@/modules/wms/components/ShipmentPickingPanel.vue';
import PickingHistory from './PickingPage.vue';
const history = ref(false);
</script>
<template>
  <div class="workflow-ui space-y-5">
    <div class="workflow-tabs" role="group" aria-label="Tampilan picking">
      <button :aria-pressed="!history" @click="history=false">Picking Draf Kiriman</button>
      <button :aria-pressed="history" @click="history=true">Riwayat operasional</button>
    </div>
    <PickingHistory v-if="history" history-only />
    <ShipmentPickingPanel v-else />
  </div>
</template>
