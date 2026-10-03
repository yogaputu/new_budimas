<script setup>
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { useAppStore } from '@/app/stores/app';
import { normalizeError } from '@/utils/api';
import AppFormField from '@/shared/components/AppFormField.vue';

const auth = useAuthStore();
const app = useAppStore();
const router = useRouter();
const route = useRoute();

const form = reactive({
  email: '',
  password: ''
});

const errorMessage = ref('');

function resolveLoginError(error) {
  const status = error?.response?.status;
  const resultMessage = Array.isArray(error?.response?.data?.result)
    ? error.response.data.result.map((item) => item?.message).find(Boolean)
    : '';
  const rawMessage = String(
    error?.response?.data?.message ||
    error?.response?.data?.error ||
    resultMessage ||
    error?.message ||
    ''
  );
  const message = rawMessage.toLowerCase();

  if (message.includes('nonetype') || message.includes('object is not iterable') || message.includes('internal server error')) {
    return 'User tidak terdaftar atau password salah.';
  }

  if (message.includes('invalid salt')) {
    return 'Password akun belum valid atau data password lama rusak. Hubungi admin untuk reset password.';
  }

  if (status === 401 || status === 403) {
    return rawMessage || 'Username atau password tidak sesuai.';
  }

  if (message.includes('password') || message.includes('credential') || message.includes('login')) {
    return rawMessage || 'Username atau password tidak sesuai.';
  }

  return normalizeError(error, 'Login gagal. Periksa username dan password Anda.');
}

async function onSubmit() {
  errorMessage.value = '';

  if (!form.email.trim() || !form.password.trim()) {
    errorMessage.value = 'Username dan password wajib diisi.';
    return;
  }

  try {
    await auth.login(form);
    await auth.fetchMe();
    router.push(route.query.redirect || auth.homeRoute || '/');
  } catch (error) {
    errorMessage.value = resolveLoginError(error);
  }
}
</script>

<template>
  <div>
    <div class="text-center">
      <img src="/assets/images/logo-budimas.png" alt="Budimas" class="mx-auto h-16 w-auto object-contain" />
      <h2 :class="['pt-5 pb-3 text-2xl font-semibold', app.isDark ? 'text-slate-100' : 'text-slate-900']">Login</h2>
    </div>

    <form class="mt-4 space-y-4" @submit.prevent="onSubmit">
      <AppFormField v-model="form.email" label="Username" placeholder="Masukkan Username Akun" />
      <AppFormField v-model="form.password" label="Password" type="password" placeholder="Masukkan Password Akun" />

      <div
        v-if="errorMessage"
        :class="[
          'rounded-2xl px-4 py-3 text-sm',
          app.isDark
            ? 'border border-rose-900/60 bg-rose-950/50 text-rose-200'
            : 'border border-rose-200 bg-rose-50 text-rose-700'
        ]"
      >
        {{ errorMessage }}
      </div>

      <button
        type="submit"
        class="w-full rounded-2xl bg-brand-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="auth.loading"
      >
        {{ auth.loading ? 'Memproses...' : 'Login' }}
      </button>
    </form>
  </div>
</template>
