import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import router from '@/app/router';
import '@/assets/styles.css';
import { useAppStore } from '@/app/stores/app';

window.__BUDIMAS_BUILD_TAG__ = '20260609-credit-note-status-cache-bust';

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
app.use(router);

const appStore = useAppStore(pinia);
appStore.initializeTheme();

app.mount('#app');
