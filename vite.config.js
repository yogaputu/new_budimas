import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';

const proxyTargets = [
  '^/api/base/.*',
  '^/api/.*',
  '^/user/.*',
  '^/getUser$',
  '^/getSales$',
  '^/getCabang$',
  '^/getPrincipal$',
  '^/getCustomerOpt$',
  '^/getCustomer$',
  '^/produk/.*',
  '^/getArmada$',
  '^/getDriver$',
  '^/get-rute-armada$',
  '^/get-all-armada$',
  '^/get-all-driver$',
  '^/get-rute-picking$',
  '^/get-info-rute-armada$',
  '^/daftar-picking-toko$',
  '^/submit-produk-picking$',
  '^/get-list-rute-shipping/.*',
  '^/get-list-rute-realisasi/.*',
  '^/get-list-faktur-shipping$',
  '^/get-list-faktur-realisasi$',
  '^/konfirmasi-order$',
  '^/tolak-order$',
  '^/get-detail-faktur/.*',
  '^/get-list-order/.*',
  '^/get-jadwal-armada$',
  '^/edit-jadwal$',
  '^/submit-picking$',
  '^/submit-faktur$',
  '^/list-tagihan-jatuh-tempo/.*',
  '^/list-faktur/.*',
  '^/create-payment$',
  '^/riwayat-setoran-customer$',
  '^/rekap-pembayaran-sales$',
  '^/submit-rekap-pembayaran-sales$',
  '^/pengiriman-stock-transfer$',
  '^/add-stock-transfer$',
  '^/detail-stock-transfer$',
  '^/konfirmasi-stock-transfer$',
  '^/konfirmasi-admin-stock-transfer$',
  '^/penerimaan-stock-transfer$',
  '^/tolak-stock-transfer$',
  '^/get-produks-stock-opname$',
  '^/create-stock-opname$',
  '^/stock-opname$',
  '^/stock-opname-diterima$',
  '^/stock-opname-ditolak$'
];

const proxy = Object.fromEntries(
  proxyTargets.map((pattern) => [
    pattern,
    {
      target: process.env.VITE_API_BASE_URL || 'https://127.0.0.1:5001',
      changeOrigin: true,
      secure: false
    }
  ])
);

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src')
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy
  }
});
