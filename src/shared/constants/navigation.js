const rawNavigationSections = [
  {
    title: 'Overview',
    items: [
      { label: 'Dashboard', to: '/', icon: 'DB', permission: 'dashboard.view' },
      { label: 'Profil', to: '/profile', icon: 'PR', permission: 'profile.view' },
      { label: 'Task Center', to: '/workflow/tasks', icon: 'TC', permission: 'workflow.tasks.view', menuPermission: 'm.workflow-center.tc.view' },
      { label: 'AI Assistant', to: '/ai/assistant', icon: 'AI', permission: 'ai.assistant.view', menuPermission: 'm.ai.ai.view' },
      { label: 'Audit Log', to: '/supervisor-sales/audit-log', icon: 'AL', permission: 'supervisor-sales.audit.view', menuPermission: 'm.supervisor-sales.al.view' }
    ]
  },
  {
    title: 'Master Data',
    items: [
      { label: 'Perusahaan', to: '/master/companies', icon: 'PS', permission: 'master.branches.view' },
      { label: 'Cabang', to: '/master/branches', icon: 'CB', permission: 'master.branches.view' },
      { label: 'Departemen', to: '/master/departments', icon: 'DP', permission: 'master.users.view' },
      { label: 'Jabatan', to: '/master/positions', icon: 'JB', permission: 'master.users.view' },
      { label: 'User', to: '/master/users', icon: 'US', permission: 'master.users.view' },
      { label: 'Budget', to: '/master/budgets', icon: 'BG', permission: 'master.products.view' },
      { label: 'Wilayah', to: '/master/regions', icon: 'WG', permission: 'master.branches.view' },
      { label: 'Rute', to: '/master/routes', icon: 'RT', permission: 'master.branches.view' },
      { label: 'Tipe Sales', to: '/master/sales-types', icon: 'ST', permission: 'master.users.view' },
      { label: 'Sales', to: '/master/sales', icon: 'SL', permission: 'master.users.view' },
      { label: 'Mapping Sales SPV', to: '/master/sales-supervisors', icon: 'MS', permission: 'master.users.view' },
      { label: 'Principal', to: '/master/principals', icon: 'PC', permission: 'master.products.view' },
      { label: 'Aturan Principal', to: '/master/principal-rules', icon: 'AP', permission: 'master.principal-rules.view' },
      { label: 'Aturan Produk Customer', to: '/master/customer-product-rules', icon: 'AC', permission: 'master.customer-product-rules.view' },
      { label: 'Sub-brand', to: '/master/subbrands', icon: 'SB', permission: 'master.products.view' },
      { label: 'Tipe PPN', to: '/master/ppn', icon: 'PP', permission: 'master.products.view' },
      { label: 'Tipe Harga', to: '/master/price-types', icon: 'TH', permission: 'master.customers.view' },
      { label: 'Produk', to: '/master/products', icon: 'PR', permission: 'master.products.view' },
      { label: 'Tipe Customer', to: '/master/customer-types', icon: 'CT', permission: 'master.customers.view' },
      { label: 'Customer', to: '/master/customers', icon: 'CU', permission: 'master.customers.view' },
      { label: 'Plafon', to: '/master/plafons', icon: 'PF', permission: 'master.plafons.view' },
      { label: 'Armada', to: '/master/fleets', icon: 'AR', permission: 'master.fleets.view' },
      { label: 'Driver', to: '/master/drivers', icon: 'DR', permission: 'master.drivers.view' },
      { label: 'Helper', to: '/master/helpers', icon: 'HP', permission: 'master.drivers.view' }
    ]
  },
  {
    title: 'Purchasing',
    items: [
      { label: 'Buat Request Cabang', to: '/purchase/branch-requests/create', icon: 'BRC', permission: 'purchase.orders.create', menuPermission: 'm.purchase.ip.view' },
      { label: 'Approval Request Cabang', to: '/purchase/branch-requests', icon: 'RC', permission: 'purchase.branch-requests.approve', menuPermission: 'm.purchase.rc.view' },
      { label: 'Purchase Order', to: '/purchase/orders', icon: 'PO', permission: 'purchase.orders.view', menuPermission: 'm.purchase.po.view' },
      { label: 'Buat Purchase Order', to: '/purchase/orders/create', icon: 'IP', permission: 'purchase.orders.create', menuPermission: 'm.purchase.ip.view' },
      { label: 'Approval Purchase Order', to: '/purchase/order-confirmations', icon: 'KO', permission: 'purchase.order-confirmations.approve', menuPermission: 'm.purchase.ko.view' },
      { label: 'Penerimaan Barang', to: '/purchase/receipts', icon: 'PB', permission: 'purchase.receipts.view', menuPermission: 'm.purchase.pb.view' },
      { label: 'Input Penerimaan Barang', to: '/purchase/receipts/create', icon: 'IB', permission: 'purchase.receipts.create', menuPermission: 'm.purchase.ib.view' },
      { label: 'Finalisasi Purchase Order', to: '/purchase/confirmations', icon: 'KP', permission: 'purchase.confirmations.approve', menuPermission: 'm.purchase.kp.view' },
      { label: 'Tagihan Purchase Order', to: '/purchase/bills', icon: 'TP', permission: 'purchase.bills.view', menuPermission: 'm.purchase.tp.view' },
      { label: 'Laporan Purchase Order', to: '/purchase/order-reports', icon: 'LP', permission: 'purchase.orders.view', menuPermission: 'm.purchase.lp.view' }
    ]
  },
  {
    title: 'Warehouse',
    items: [
      { label: 'Monitoring Gudang', to: '/wms', icon: 'MN', permission: 'wms.view', menuPermission: 'm.operasional.mn.view', permissionAliases: ['m.operasional.wm.view'] },
      { label: 'Master Rak', to: '/wms/master-rak', icon: 'MR', permission: 'wms.view', menuPermission: 'm.operasional.mr.view', permissionAliases: ['m.operasional.wm.view'] },
      { label: 'Master Pallet', to: '/wms/master-pallet', icon: 'MP', permission: 'wms.view', menuPermission: 'm.operasional.mr.view', permissionAliases: ['m.operasional.wm.view'] },
      { label: 'Penempatan Barang', to: '/wms/penempatan', icon: 'PN', permission: 'wms.view', menuPermission: 'm.operasional.pn.view', permissionAliases: ['m.operasional.wm.view'] },
      { label: 'Rak 3D', to: '/wms/rak-3d', icon: '3D', permission: 'wms.view', menuPermission: 'm.operasional.3d.view', permissionAliases: ['m.operasional.wm.view'] }
    ]
  },
  {
    title: 'Stock',
    items: [
      { label: 'Stok Transfer', to: '/stock-transfer', icon: 'ST', permission: 'stock-transfer.view', menuPermission: 'm.operasional.st.view' },
      { label: 'Buat Stok Transfer', to: '/stock-transfer/create', icon: 'BT', permission: 'stock-transfer.create', menuPermission: 'm.operasional.bt.view' },
      { label: 'Approval Stok Transfer', to: '/stock-transfer/confirmations', icon: 'KT', permission: 'stock-transfer.view', menuPermission: 'm.operasional.kt.view' },
      { label: 'Pengiriman Stok Transfer', to: '/stock-transfer/shipments', icon: 'PT', permission: 'stock-transfer.view', menuPermission: 'm.operasional.pt.view' },
      { label: 'Status Pengiriman', to: '/stock-transfer/shipment-status', icon: 'SP', permission: 'stock-transfer.view', menuPermission: 'm.operasional.sp.view' },
      { label: 'Penerimaan Stok Transfer', to: '/stock-transfer/receipts', icon: 'PB', permission: 'stock-transfer.view', menuPermission: 'm.operasional.pb.view' },
      { label: 'Eskalasi Stok Transfer', to: '/stock-transfer/escalations', icon: 'ET', permission: 'stock-transfer.view', menuPermission: 'm.operasional.et.view' },
      { label: 'Stok Opname', to: '/stock-opname', icon: 'SO', permission: 'stock-opname.view', menuPermission: 'm.operasional.so.view' },
      { label: 'Buat Stok Opname', to: '/stock-opname/create', icon: 'BO', permission: 'stock-opname.create', menuPermission: 'm.operasional.bo.view' },
      { label: 'Eskalasi Stok Opname', to: '/stock-opname/escalations', icon: 'EO', permission: 'stock-opname.view', menuPermission: 'm.operasional.eo.view' },
      { label: 'Laporan Stok Gudang', to: '/stock-opname/report', icon: 'LS', permission: 'stock-opname.view', menuPermission: 'm.operasional.ls.view' }
    ]
  },
  {
    title: 'Promo',
    items: [
      { label: 'Promo All-In', to: '/promo/all-in', icon: 'PA', permission: 'distribution.orders.view' },
      { label: 'Kategori Klaim Promo', to: '/promo/claim-categories', icon: 'KC', permission: 'distribution.orders.view' },
      { label: 'Monitoring Promo', to: '/promo/trade-cashback', icon: 'MP', permission: 'distribution.orders.view' },
      { label: 'Ajukan Klaim Promo', to: '/promo/claims/create', icon: 'JK', permission: 'distribution.orders.view' },
      { label: 'Daftar Klaim Promo', to: '/promo/claims', icon: 'DK', permission: 'distribution.orders.view' },
      { label: 'Approval Klaim Promo', to: '/promo/claims/approval', icon: 'AP', permission: 'distribution.orders.view' },
      { label: 'Ajukan Kasbon', to: '/promo/kasbon/create', icon: 'AK', permission: 'distribution.orders.view' },
      { label: 'Approval Kasbon', to: '/supervisor-sales/kasbon', icon: 'KB', permission: 'supervisor-sales.kasbon.approve', menuPermission: 'm.supervisor-sales.kb.view' },
      { label: 'Daftar Kasbon', to: '/promo/kasbon', icon: 'KK', permission: 'distribution.orders.view' }
    ]
  },
  {
    title: 'Distribution',
    items: [
      { label: 'Stok Opname Sales', to: '/sales-order/stock-opname-sales', icon: 'SO', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.so.view' },
      { label: 'Order Sales', to: '/sales-order', icon: 'OS', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.os.view' },
      { label: 'Buat Order', to: '/sales-order/create', icon: 'IO', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.io.view' },
      { label: 'Approval Order', to: '/distribution/orders', icon: 'OR', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.or.view' },
      { label: 'Jadwal Pengiriman', to: '/distribution/schedules', icon: 'JD', permission: 'distribution.schedules.view', menuPermission: 'm.distribusi.jd.view' },
      { label: 'Picking', to: '/distribution/picking', icon: 'PK', permission: 'distribution.picking.view', menuPermission: 'm.distribusi.pk.view' },
      { label: 'Detail Faktur', to: '/distribution/invoices', icon: 'FK', permission: 'distribution.invoices.view', menuPermission: 'm.distribusi.fk.view' },
      { label: 'Revisi Faktur', to: '/distribution/invoice-revisions', icon: 'RF', permission: 'distribution.invoices.view', menuPermission: 'm.distribusi.rf.view' },
      {
        label: 'Batal Realisasi',
        to: '/distribution/cancel-realization',
        icon: 'BR',
        permission: 'distribution.invoices.view',
        permissionAliases: [
          'distribution.cancel-realisasi.view',
          'distribution.cancel-realisasi.create',
          'distribution.cancel-realisasi.edit',
          'distribution.cancel-realisasi.approve',
          'distribution.cancel-realisasi.final-approve'
        ]
      },
      { label: 'Invoice Order', to: '/sales-order/invoices', icon: 'IV', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.iv.view' },
      { label: 'Ajukan Retur', to: '/sales-order/retur', icon: 'RS', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.rs.view' },
      { label: 'Monitoring Retur', to: '/sales-order/retur-tracking', icon: 'TR', permission: 'distribution.orders.view', menuPermission: 'm.distribusi.tr.view' },
      { label: 'Monitoring Armada', to: '/distribution/fleet-management', icon: 'MA', permission: 'distribution.schedules.view', menuPermission: 'm.distribusi.hd.view' },
      { label: 'Pengeluaran Driver', to: '/distribution/driver-expenses', icon: 'PD', permission: 'distribution.schedules.view', menuPermission: 'm.distribusi.pd.view' },
      { label: 'Riwayat Distribusi', to: '/distribution/history', icon: 'DH', permission: 'distribution.invoices.view', menuPermission: 'm.distribusi.dh.view' }
    ]
  },
  {
    title: 'Canvassing',
    items: [
      { label: 'Request Canvas', to: '/sales-canvas/requests', icon: 'CR', permission: 'distribution.orders.view', menuPermission: 'm.sales-canvas.cr.view', permissionAliases: ['menu.sales-canvas.sales-canvas-requests.view'] },
      { label: 'Order Canvas', to: '/sales-canvas/orders', icon: 'CO', permission: 'distribution.orders.view', menuPermission: 'm.sales-canvas.co.view', permissionAliases: ['menu.sales-canvas.sales-canvas-orders.view'] },
      { label: 'Tagihan Canvas', to: '/sales-canvas/payments', icon: 'TC', permission: 'distribution.orders.view', menuPermission: 'm.sales-canvas.tc.view', permissionAliases: ['menu.sales-canvas.sales-canvas-payments.view'] },
      {
        label: 'Retur Canvas',
        to: '/sales-canvas/returns',
        icon: 'RT',
        permission: 'distribution.orders.view',
        menuPermission: 'm.sales-canvas.rt.view',
        // Compatibility for existing menu-scoped Canvas roles. The API still
        // authorizes approve/reject actions independently from menu visibility.
        permissionAliases: [
          'menu.sales-canvas.sales-canvas-returns.view',
          'm.sales-canvas.cr.view',
          'm.sales-canvas.co.view'
        ]
      },
      { label: 'Voucher Canvas', to: '/sales-canvas/vouchers', icon: 'VC', permission: 'distribution.orders.view', menuPermission: 'm.sales-canvas.vc.view', permissionAliases: ['menu.sales-canvas.sales-canvas-vouchers.view'] },
      { label: 'Riwayat Canvas', to: '/sales-canvas/payment-recap', icon: 'RC', permission: 'distribution.orders.view', menuPermission: 'm.sales-canvas.rc.view', permissionAliases: ['menu.sales-canvas.sales-canvas-payment-recap.view'] }
    ]
  },
  {
    title: 'Finance',
    items: [
      {
        label: 'Rekening Perusahaan',
        to: '/finance/company-bank-accounts',
        icon: 'RP',
        permission: 'finance.company-bank-accounts.view',
        menuPermission: 'finance.company-bank-accounts.view',
        permissionAliases: ['m.finance.rp.view']
      },
      { label: 'Input Transaksi', to: '/finance/accounting-transactions', icon: 'IT', permission: 'finance.recap.view' },
      { label: 'Credit Note', to: '/finance/credit-note', icon: 'CN', permission: 'finance.recap.view' },
      { label: 'Tagihan Plafon', to: '/finance/receivables', icon: 'TG', permission: 'finance.receivables.view' },
      { label: 'LPH', to: '/finance/lph', icon: 'LP', permission: 'finance.recap.view' },
      { label: 'Surat Tagihan Sales', to: '/finance/sales-billing-letters', icon: 'TS', permission: 'finance.recap.view' },
      { label: 'Pembayaran Tagihan', to: '/finance/payments', icon: 'BY', permission: 'finance.payments.view' },
      { label: 'Piutang Canvas Finance', to: '/finance/canvas-receivables', icon: 'PC', permission: 'finance.recap.view' },
      { label: 'Rekap Pembayaran', to: '/finance/recap', icon: 'RK', permission: 'finance.recap.view' },
      { label: 'Batal Pembayaran', to: '/finance/payment-cancellation', icon: 'BP', permission: 'finance.recap.view' },
      { label: 'Setoran Tunai', to: '/finance/cash-deposits', icon: 'ST', permission: 'finance.recap.view' },
      { label: 'Setoran Non Tunai', to: '/finance/noncash-deposits', icon: 'SN', permission: 'finance.recap.view' },
      { label: 'Uang Muka Customer', to: '/finance/customer-advances', icon: 'UM', permission: 'finance.recap.view' },
      { label: 'Finalisasi Setoran', to: '/finance/deposit-finalization', icon: 'FS', permission: 'finance.recap.view' },
      { label: 'Pengeluaran Kasir', to: '/finance/cashier-expenses', icon: 'PK', permission: 'finance.recap.view' },
      { label: 'Kasbon Karyawan', to: '/finance/employee-advances', icon: 'KKY', permission: 'finance.employee-advances.view', menuPermission: 'finance.employee-advances.view', permissionAliases: ['finance.employee-advances.create', 'finance.employee-advances.approve'] },
      { label: 'Laporan Kasir', to: '/finance/cashier-reports', icon: 'LK', permission: 'finance.recap.view' }
    ]
  },
  {
    title: 'Accounting',
    items: [
      { label: 'Chart of Account', to: '/finance/coa', icon: 'CA', permission: 'finance.recap.view', menuPermission: 'm.finance.ca.view' },
      { label: 'Saldo Awal', to: '/finance/opening-balance', icon: 'SA', permission: 'finance.recap.view', menuPermission: 'm.finance.sa.view' },
      { label: 'Inventaris', to: '/finance/inventaris', icon: 'IN', permission: 'finance.recap.view', menuPermission: 'm.finance.in.view' },
      { label: 'Jurnal Setting', to: '/finance/journal-settings', icon: 'JS', permission: 'finance.recap.view', menuPermission: 'm.finance.js.view' },
      { label: 'Jurnal', to: '/finance/journal', icon: 'JU', permission: 'finance.recap.view', menuPermission: 'm.finance.ju.view' },
      { label: 'Buku Besar', to: '/finance/general-ledger', icon: 'BB', permission: 'finance.recap.view', menuPermission: 'm.finance.bb.view' },
      { label: 'Piutang Customer', to: '/finance/customer-receivable-balances', icon: 'SP', permission: 'finance.receivables.view', menuPermission: 'm.finance.sp.view' },
      { label: 'Pajak', to: '/finance/tax', icon: 'PJ', permission: 'finance.recap.view', menuPermission: 'm.finance.pj.view' },
      { label: 'Laba Rugi', to: '/finance/profit-loss', icon: 'LR', permission: 'finance.recap.view', menuPermission: 'm.finance.lr.view' },
      { label: 'Neraca', to: '/finance/balance-sheet', icon: 'NR', permission: 'finance.recap.view', menuPermission: 'm.finance.nr.view' },
      { label: 'Kartu Stok Bernilai', to: '/finance/valued-stock-card', icon: 'KS', permission: 'finance.recap.view', menuPermission: 'm.finance.ks.view' },
      { label: 'Periode Close', to: '/master/closed-periods', icon: 'CL', permission: 'master.branches.view', menuPermission: 'm.master-data.cl.view' }
    ]
  },
  {
    title: 'Supervisor',
    items: [
      { label: 'Dashboard SPV', to: '/supervisor-sales/dashboard', icon: 'SD', permission: 'supervisor-sales.dashboard.view', menuPermission: 'm.supervisor-sales.sd.view' },
      { label: 'Checklist Kinerja Sales', to: '/supervisor-sales/performance-checklist', icon: 'CK', permission: 'supervisor-sales.dashboard.view', menuPermission: 'm.supervisor-sales.sd.view' },
      { label: 'Setting Target Sales', to: '/supervisor-sales/sales-target-settings', icon: 'TS', permission: 'supervisor-sales.targets.update', menuPermission: 'm.supervisor-sales.ts.view' },
      { label: 'Monitoring Target Omset', to: '/supervisor-sales/omset-target-monitor', icon: 'TO', permission: 'supervisor-sales.targets.view', menuPermission: 'm.supervisor-sales.to.view' },
      { label: 'Monitoring Stok Opname', to: '/supervisor-sales/stock-opname-monitor', icon: 'MO', permission: 'supervisor-sales.stock-opname-monitor.view', menuPermission: 'm.supervisor-sales.mo.view' },
      { label: 'Analisa DOI', to: '/supervisor-sales/doi-analysis', icon: 'DO', permission: 'supervisor-sales.doi.view', menuPermission: 'm.supervisor-sales.do.view' },
      { label: 'Absensi Sales', to: '/supervisor-sales/attendance', icon: 'AS', permission: 'supervisor-sales.attendance.view', menuPermission: 'm.supervisor-sales.as.view' },
      { label: 'Kalender Call Plan', to: '/supervisor-sales/callplan-calendar', icon: 'KC', permission: 'supervisor-sales.callplan.view', menuPermission: 'm.supervisor-sales.kc.view' },
      { label: 'Kunjungan Sales', to: '/supervisor-sales/visits', icon: 'KS', permission: 'supervisor-sales.visits.view', menuPermission: 'm.supervisor-sales.ks.view' },
      { label: 'Mapping Customer', to: '/supervisor-sales/customer-map', icon: 'MC', permission: 'supervisor-sales.visits.view', menuPermission: 'm.supervisor-sales.mc.view' },
      {
        label: 'Rute Customer',
        to: '/reports/route-customers',
        icon: 'RC',
        permission: 'distribution.orders.view',
        menuPermission: 'm.laporan.rc.view',
        permissionAliases: ['distribution.orders.view', 'm.distribusi.or.view', 'm.supervisor-sales.mc.view']
      }
    ]
  },
  {
    title: 'Data Tools',
    items: [
      { label: 'Import DMS', to: '/data-tools/dms-import', icon: 'DM', permission: 'distribution.orders.view' },
      { label: 'DMS Mondelez', to: '/data-tools/dms-mondelez', icon: 'MD', permission: 'distribution.orders.view' },
      { label: 'Import / Download Data', to: '/data-tools/import-download', icon: 'ID', permission: 'distribution.orders.view' },
      { label: 'Template Order Sales', to: '/data-tools/sales-order-template', icon: 'TS', permission: 'distribution.orders.view', permissionAliases: ['m.data-tools.id.view'] },
      { label: 'Monitor Sync Legacy', to: '/data-tools/legacy-sync-monitor', icon: 'LS', permission: 'distribution.orders.view' },
      { label: 'Import SO Akasha TMP', to: '/data-tools/import-akasha', icon: 'AT', permission: 'distribution.orders.view' },
      { label: 'Import SO Akasha Budimas', to: '/data-tools/import-akasha-budimas', icon: 'AB', permission: 'distribution.orders.view' },
      { label: 'ONESKY : Sosro', to: '/data-tools/import-onesky-sosro', icon: 'OS', permission: 'distribution.orders.view' },
      { label: 'Godrej', to: '/data-tools/import-godrej', icon: 'GD', permission: 'distribution.orders.view' },
      { label: 'Bosnet Hidro', to: '/data-tools/import-bosnet-hidro', icon: 'BH', permission: 'distribution.orders.view' },
      { label: 'UFIT', to: '/data-tools/import-ufit', icon: 'UF', permission: 'distribution.orders.view' }
    ]
  },
  {
    title: 'RBAC Setting',
    items: [
      { label: 'Hak Akses', to: '/access/roles', icon: 'MR', permission: 'master.users.view', menuPermission: 'm.akses.mr.view' },
      { label: 'Hak Akses User', to: '/access/user-features', icon: 'FU', permission: 'master.user-features.view', menuPermission: 'm.akses.fu.view' },
      { label: 'Hak Akses Jabatan', to: '/access/position-features', icon: 'FJ', permission: 'master.position-features.view', menuPermission: 'm.akses.fj.view' }
    ]
  }
];

function slugifyMenu(value = '') {
  return String(value)
    .toLowerCase()
    .replace(/&/g, 'and')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

function resolveMenuPermission(sectionTitle, item) {
  if (item.menuPermission) return item.menuPermission;
  const section = slugifyMenu(sectionTitle || 'menu');
  const itemKey = slugifyMenu(item.icon || item.label || 'item');
  return `m.${section}.${itemKey}.view`;
}

export const navigationSections = rawNavigationSections.map((section) => ({
  ...section,
  items: mapNavigationItems(section.title, section.items)
}));

function mapNavigationItems(sectionTitle, items = []) {
  return items.map((item) => ({
    ...item,
    menuPermission: resolveMenuPermission(sectionTitle, item),
    children: item.children ? mapNavigationItems(sectionTitle, item.children) : undefined
  }));
}
