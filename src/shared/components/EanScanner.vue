<script setup>
import { nextTick, onBeforeUnmount, ref } from 'vue';
const emit = defineEmits(['scan']);
const opened = ref(false);
const video = ref(null);
const input = ref(null);
const code = ref('');
const error = ref('');
let stream, timer, generation = 0;
function stop() {
  generation += 1;
  clearTimeout(timer);
  stream?.getTracks().forEach(track => track.stop());
  stream = null;
}
function close() { stop(); opened.value = false; }
function accept(raw) {
  const value = String(raw || '').trim();
  if (!/^\d{8}$|^\d{13}$/.test(value)) { error.value = 'Kode EAN harus 8 atau 13 digit.'; return; }
  const digits = [...value].map(Number);
  const check = digits.pop();
  const sum = digits.reverse().reduce((total, digit, i) => total + digit * (i % 2 ? 1 : 3), 0);
  if ((10 - sum % 10) % 10 !== check) { error.value = 'Checksum EAN tidak valid. Silakan scan ulang.'; return; }
  emit('scan', value); close();
}
async function open() {
  opened.value = true; error.value = ''; code.value = '';
  await nextTick(); input.value?.focus();
}
async function camera() {
  stop(); error.value = '';
  const attempt = generation;
  if (!window.BarcodeDetector || !navigator.mediaDevices?.getUserMedia) {
    error.value = 'Scan kamera tidak didukung browser ini. Gunakan scanner USB/Bluetooth pada kolom di bawah.'; return;
  }
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    const formats = ['ean_13', 'ean_8'].filter(format => supported.includes(format));
    if (!formats.length) throw new Error('unsupported');
    if (attempt !== generation || !opened.value) return;
    const detector = new window.BarcodeDetector({ formats });
    const acquired = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
    if (attempt !== generation || !opened.value) { acquired.getTracks().forEach(t => t.stop()); return; }
    stream = acquired; video.value.srcObject = stream; await video.value.play();
    const detect = async () => {
      if (attempt !== generation || !opened.value) return;
      try {
        const results = await detector.detect(video.value);
        if (results.length && attempt === generation) accept(results[0].rawValue);
      } catch { /* Retry while the camera produces a frame. */ }
      if (attempt === generation && opened.value) timer = setTimeout(detect, 250);
    };
    detect();
  } catch {
    if (attempt !== generation) return;
    stop(); error.value = 'Kamera belum dapat digunakan. Periksa izin kamera/HTTPS atau gunakan scanner USB/Bluetooth.';
  }
}
onBeforeUnmount(stop);
</script>

<template>
  <button type="button" class="rounded-lg border px-3 py-2 text-sm" @click="open">Scan EAN</button>
  <div v-if="opened" class="mt-3 space-y-3 rounded-xl border p-3" aria-label="Pemindai EAN">
    <p class="text-sm">Scan dengan USB/Bluetooth lalu Enter, atau aktifkan kamera.</p>
    <input ref="input" v-model="code" aria-label="Hasil scan EAN" inputmode="numeric" autocomplete="off" class="w-full rounded-lg border bg-transparent p-2" @keydown.enter.prevent="accept(code)" />
    <video ref="video" muted playsinline class="max-h-48 w-full rounded-lg" />
    <p v-if="error" role="alert" class="text-sm text-rose-500">{{ error }}</p>
    <div class="flex gap-2">
      <button type="button" class="rounded-lg border p-2" @click="camera">Aktifkan kamera</button>
      <button type="button" class="rounded-lg border p-2" @click="accept(code)">Gunakan kode</button>
      <button type="button" class="rounded-lg border p-2" @click="close">Tutup</button>
    </div>
  </div>
</template>
