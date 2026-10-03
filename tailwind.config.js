/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f5f7f2',
          100: '#e8efe1',
          200: '#d4e1c7',
          300: '#b2cb9d',
          400: '#88ad67',
          500: '#6a8d42',
          600: '#516d2f',
          700: '#3c5124',
          800: '#29371a',
          900: '#182111'
        }
      },
      boxShadow: {
        panel: '0 20px 45px -25px rgba(15, 23, 42, 0.35)'
      }
    }
  },
  plugins: []
};
