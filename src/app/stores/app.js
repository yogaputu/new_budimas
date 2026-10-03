import { defineStore } from 'pinia';

const THEME_KEY = 'budimas-theme';

function getSystemDark() {
  if (typeof window === 'undefined') return false;
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches || false;
}

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarOpen: false,
    pageLoading: false,
    theme: 'system',
    systemDark: false,
    themeWatcherReady: false
  }),

  getters: {
    isDark: (state) => {
      if (state.theme === 'system') return state.systemDark;
      return state.theme === 'dark';
    },

    themeLabel: (state) => {
      if (state.theme === 'system') return 'Auto';
      return state.theme === 'dark' ? 'Dark' : 'Light';
    }
  },

  actions: {
    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen;
    },

    closeSidebar() {
      this.sidebarOpen = false;
    },

    setPageLoading(value) {
      this.pageLoading = value;
    },

    initializeTheme() {
      if (typeof window === 'undefined') return;

      const savedTheme = window.localStorage.getItem(THEME_KEY);
      this.theme = ['system', 'light', 'dark'].includes(savedTheme) ? savedTheme : 'system';

      const media = window.matchMedia?.('(prefers-color-scheme: dark)');
      this.systemDark = media?.matches || false;

      if (media && !this.themeWatcherReady) {
        media.addEventListener?.('change', (event) => {
          this.systemDark = event.matches;
          this.applyTheme();
        });

        this.themeWatcherReady = true;
      }

      this.applyTheme();
    },

    setTheme(value) {
      this.theme = ['system', 'light', 'dark'].includes(value) ? value : 'system';
      this.applyTheme();
    },

    toggleTheme() {
      const nextTheme = {
        system: 'light',
        light: 'dark',
        dark: 'system'
      };

      this.setTheme(nextTheme[this.theme] || 'system');
    },

    applyTheme() {
      if (typeof document === 'undefined') return;

      const root = document.documentElement;
      const activeTheme = this.isDark ? 'dark' : 'light';

      root.setAttribute('data-theme', activeTheme);
      root.classList.toggle('dark', this.isDark);
      root.style.colorScheme = activeTheme;

      if (typeof window !== 'undefined') {
        window.localStorage.setItem(THEME_KEY, this.theme);
      }
    }
  }
});