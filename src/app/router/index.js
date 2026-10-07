import { createRouter, createWebHistory } from 'vue-router';
import { setupAuthGuard } from '@/app/guards/authGuard';

function resolvePromoLanding() {
  return '/promo/all-in';
}

const routes = [
  {
    path: '/login',
    component: () => import('@/app/layouts/AuthLayout.vue'),
    meta: { requiresGuest: true },
    children: [{ path: '', name: 'login', component: () => import('@/modules/auth/pages/LoginPage.vue') }]
  },
  {
    path: '/',
    component: () => import('@/app/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'dashboard', component: () => import('@/modules/dashboard/pages/DashboardPage.vue'), meta: { permission: 'dashboard.view' } },
      { path: 'profile', name: 'profile', component: () => import('@/modules/profile/pages/ProfilePage.vue'), meta: { permission: 'profile.view' } },
      { path: 'master/users', name: 'master-users', component: () => import('@/modules/master/pages/UsersPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/positions', name: 'master-positions', component: () => import('@/modules/master/pages/PositionsPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/departments', name: 'master-departments', component: () => import('@/modules/master/pages/DepartmentsPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/customer-types', name: 'master-customer-types', component: () => import('@/modules/master/pages/CustomerTypesPage.vue'), meta: { permission: 'master.customers.view' } },
      {
        path: 'master/price-types',
        name: 'master-price-types',
        component: () => import('@/modules/master/pages/PriceTypesPage.vue'),
        meta: {
          permission: 'master.customers.view',
          pageTitle: 'Master Tipe Harga',
          pageDescription: 'Kelola referensi tipe harga untuk customer, plafon, dan harga jual produk.'
        }
      },
      { path: 'master/sales-types', name: 'master-sales-types', component: () => import('@/modules/master/pages/SalesTypesPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/sales', name: 'master-sales', component: () => import('@/modules/master/pages/SalesPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/sales-supervisors', name: 'master-sales-supervisors', component: () => import('@/modules/master/pages/SalesSupervisorMapPage.vue'), meta: { permission: 'master.users.view' } },
      { path: 'master/customers', name: 'master-customers', component: () => import('@/modules/master/pages/CustomersPage.vue'), meta: { permission: 'master.customers.view' } },
      { path: 'master/principals', name: 'master-principals', component: () => import('@/modules/master/pages/PrincipalsPage.vue'), meta: { permission: 'master.products.view' } },
      { path: 'master/principal-rules', name: 'master-principal-rules', component: () => import('@/modules/master/pages/PrincipalRulesPage.vue'), meta: { permission: 'master.principal-rules.view' } },
      { path: 'master/customer-product-rules', name: 'master-customer-product-rules', component: () => import('@/modules/master/pages/CustomerProductRulesPage.vue'), meta: { permission: 'master.customer-product-rules.view' } },
      { path: 'master/regions', name: 'master-regions', component: () => import('@/modules/master/pages/RegionsPage.vue'), meta: { permission: 'master.branches.view' } },
      { path: 'master/companies', name: 'master-companies', component: () => import('@/modules/master/pages/CompaniesPage.vue'), meta: { permission: 'master.branches.view' } },
      { path: 'master/routes', name: 'master-routes', component: () => import('@/modules/master/pages/RoutesPage.vue'), meta: { permission: 'master.branches.view' } },
      { path: 'master/products', name: 'master-products', component: () => import('@/modules/master/pages/ProductsPage.vue'), meta: { permission: 'master.products.view' } },
      { path: 'master/subbrands', name: 'master-subbrands', component: () => import('@/modules/master/pages/SubbrandsPage.vue'), meta: { permission: 'master.products.view' } },
      { path: 'master/ppn', name: 'master-ppn', component: () => import('@/modules/master/pages/ProductPpnPage.vue'), meta: { permission: 'master.products.view' } },
      { path: 'master/branches', name: 'master-branches', component: () => import('@/modules/master/pages/BranchesPage.vue'), meta: { permission: 'master.branches.view' } },
      { path: 'master/fleets', name: 'master-fleets', component: () => import('@/modules/master/pages/FleetsPage.vue'), meta: { permission: 'master.fleets.view' } },
      { path: 'master/drivers', name: 'master-drivers', component: () => import('@/modules/master/pages/DriversPage.vue'), meta: { permission: 'master.drivers.view' } },
      { path: 'master/helpers', name: 'master-helpers', component: () => import('@/modules/master/pages/HelpersPage.vue'), meta: { permission: 'master.drivers.view' } },
      { path: 'master/closed-periods', name: 'master-closed-periods', component: () => import('@/modules/master/pages/ClosedPeriodsPage.vue'), meta: { permission: 'master.branches.view' } },
      { path: 'master/budgets', name: 'master-budgets', component: () => import('@/modules/master/pages/BudgetsPage.vue'), meta: { permission: 'master.products.view' } },
      { path: 'master/plafons', name: 'master-plafons', component: () => import('@/modules/master/pages/PlafonsPage.vue'), meta: { permission: 'master.plafons.view' } },
      { path: 'access/roles', name: 'access-roles', component: () => import('@/modules/master/pages/MasterRolePage.vue'), meta: { permission: 'master.roles.view' } },
      { path: 'access/user-features', name: 'access-user-features', component: () => import('@/modules/master/pages/UserFeaturesPage.vue'), meta: { permission: 'master.user-features.view' } },
      { path: 'access/position-features', name: 'access-position-features', component: () => import('@/modules/master/pages/PositionFeaturesPage.vue'), meta: { permission: 'master.position-features.view' } },
      { path: 'data-tools/import-download', name: 'data-tools-import-download', component: () => import('@/modules/data-tools/pages/ImportDownloadDataPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'data-tools/sales-order-template', name: 'data-tools-sales-order-template', component: () => import('@/modules/data-tools/pages/SalesOrderTemplatePage.vue'), meta: { permission: 'distribution.orders.view', pageTitle: 'Template Order Sales', pageDescription: 'Template Excel dan panduan penyiapan order customer.' } },
      {
        path: 'data-tools/legacy-sync-monitor',
        name: 'data-tools-legacy-sync-monitor',
        component: () => import('@/modules/data-tools/pages/LegacySyncMonitorPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          pageTitle: 'Monitor Sync Legacy',
          pageDescription: 'Pantau proses sinkronisasi insert-only dari SQL Server legacy ke PostgreSQL ERP.'
        }
      },
      {
        path: 'data-tools/import-akasha',
        name: 'data-tools-import-akasha',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'tmp',
          importCompanyCode: 'TMP',
          importCompanyLabel: 'TMP',
          importSourceServer: '192.168.5.243',
          pageTitle: 'Import Sales Order Akasha TMP',
          pageDescription: 'Upload file Sales Order Excel Akasha/Odoo untuk source TMP, preview validasi, lalu proses menjadi Sales Order.'
        }
      },
      {
        path: 'data-tools/import-akasha-budimas',
        name: 'data-tools-import-akasha-budimas',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'budimas',
          importCompanyCode: 'BMM',
          importCompanyLabel: 'Budimas',
          importSourceServer: '192.168.5.242',
          pageTitle: 'Import Sales Order Akasha Budimas',
          pageDescription: 'Upload file Sales Order Excel Akasha/Odoo untuk source Budimas, preview validasi, lalu proses menjadi Sales Order.'
        }
      },
      {
        path: 'data-tools/import-onesky-sosro',
        name: 'data-tools-import-onesky-sosro',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'onesky-sosro',
          importSourceFormat: 'onesky_sosro_csv',
          importCompanyCode: 'BMM',
          importCompanyLabel: 'ONESKY : Sosro',
          importSourceServer: 'ONESKY CSV',
          importPrincipalCode: 'SOSRO',
          importPrincipalName: 'sosro',
          importFileLabel: 'File Faktur ONESKY Sosro (.csv)',
          importFileAccept: '.csv,text/csv',
          importUploadLabel: 'Upload File Faktur ONESKY Sosro',
          importPresetLabel: 'Preset Sosro',
          pageTitle: 'Import ONESKY : Sosro',
          pageDescription: 'Upload file faktur CSV ONESKY Sosro, preview validasi outlet/sales/produk, lalu proses menjadi Sales Order.'
        }
      },
      {
        path: 'data-tools/import-godrej',
        name: 'data-tools-import-godrej',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'godrej',
          importSourceFormat: 'godrej_rd_txt',
          importCompanyCode: 'BMM',
          importCompanyLabel: 'Godrej',
          importSourceServer: 'RD TXT',
          importPrincipalCode: 'GODREJ',
          importPrincipalName: 'godrej',
          importFileLabel: 'File RD Godrej (.txt/.csv)',
          importFileAccept: '.txt,.csv,text/plain,text/csv',
          importUploadLabel: 'Upload File RD Godrej',
          importPresetLabel: 'Preset Godrej',
          pageTitle: 'Import Godrej',
          pageDescription: 'Upload file RD TXT/CSV Godrej, preview validasi customer/sales/produk, lalu proses menjadi Sales Order.'
        }
      },
      {
        path: 'data-tools/import-bosnet-hidro',
        name: 'data-tools-import-bosnet-hidro',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'bosnet-hidro',
          importSourceFormat: 'bosnet_hidro_csv',
          importCompanyCode: 'BMM',
          importCompanyLabel: 'Bosnet Hidro',
          importSourceServer: 'BOSNET CSV',
          importPrincipalCode: 'HIDRO',
          importPrincipalName: 'hidro',
          importFileLabel: 'File SI Header + SI Detail Bosnet Hidro (.csv)',
          importFileAccept: '.csv,text/csv',
          importMultipleFiles: true,
          importUploadLabel: 'Upload File Bosnet Hidro',
          importPresetLabel: 'Preset Hidro',
          pageTitle: 'Import Bosnet Hidro',
          pageDescription: 'Upload file SI_HEADER dan SI_DETAIL CSV Bosnet Hidro, preview validasi customer/sales/produk, lalu proses menjadi Sales Order.'
        }
      },
      {
        path: 'data-tools/import-ufit',
        name: 'data-tools-import-ufit',
        component: () => import('@/modules/data-tools/pages/AkashaSalesOrderImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          importSourceKey: 'ufit',
          importSourceFormat: 'ufit_order_txt',
          importCompanyCode: 'BMM',
          importCompanyLabel: 'UFIT',
          importSourceServer: 'UFIT TXT',
          importPrincipalCode: 'UFIT',
          importPrincipalName: 'ufit',
          importFileLabel: 'File H_ORDER + D_ORDER UFIT (.txt)',
          importFileAccept: '.txt,.csv,text/plain,text/csv',
          importMultipleFiles: true,
          importUploadLabel: 'Upload File UFIT',
          importPresetLabel: 'Preset UFIT',
          pageTitle: 'Import UFIT',
          pageDescription: 'Upload file H_ORDER dan D_ORDER TXT UFIT, preview validasi customer/sales/produk, lalu proses menjadi Sales Order.'
        }
      },
      { path: 'data-tools/dms-import', name: 'data-tools-dms-import', component: () => import('@/modules/data-tools/pages/DmsImportPage.vue'), meta: { permission: 'distribution.orders.view' } },
      {
        path: 'data-tools/dms-mondelez',
        name: 'data-tools-dms-mondelez',
        component: () => import('@/modules/data-tools/pages/DmsImportPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          pageTitle: 'DMS Mondelez',
          pageDescription: 'Import DMS Mondelez dari ZIP berisi INVOICE_HDR.csv dan INVOICE_DTL.csv atau dua file CSV pipe-delimited.'
        }
      },
      { path: 'ai/assistant', name: 'ai-assistant', component: () => import('@/modules/ai/pages/AiAssistantPage.vue'), meta: { permission: 'ai.assistant.view' } },
      {
        path: 'workflow/tasks',
        name: 'workflow-tasks',
        component: () => import('@/modules/workflow/pages/WorkflowCenterPage.vue'),
        meta: {
          permission: 'workflow.tasks.view',
          pageTitle: 'Workflow Center',
          pageDescription: 'Task, approval, PIC, deadline, dan audit lintas modul.'
        }
      },
      { path: 'distribution/orders', name: 'distribution-orders', component: () => import('@/modules/distribution/pages/OrdersPage.vue'), meta: { permission: 'distribution.orders.view' } },
      {
        path: 'sales-order',
        name: 'sales-order-list',
        component: () => import('@/modules/sales-order/pages/SalesOrderListPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          pageTitle: 'Sales Order Control Center',
          pageDescription: 'Monitor order sales, faktur, retur, dan progres distribusi.'
        }
      },
      { path: 'sales-order/create', name: 'sales-order-create', component: () => import('@/modules/sales-order/pages/SalesOrderCreatePage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-order/edit/:id', name: 'sales-order-edit', component: () => import('@/modules/sales-order/pages/SalesOrderCreatePage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-order/retur', name: 'sales-order-retur', component: () => import('@/modules/sales-order/pages/SalesReturPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-order/retur-tracking', name: 'sales-order-retur-list', component: () => import('@/modules/sales-order/pages/SalesReturListPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-order/stock-opname-sales', name: 'sales-order-stock-opname-sales', component: () => import('@/modules/sales-order/pages/SalesStockOpnamePage.vue'), meta: { permission: 'distribution.orders.view', pageTitle: 'Stok Opname Sales', pageDescription: 'Pantau stok opname yang dikirim dari aplikasi Android sales.' } },
      { path: 'sales-order/invoices', name: 'sales-order-invoices', component: () => import('@/modules/sales-order/pages/SalesInvoiceListPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-canvas/requests', name: 'sales-canvas-requests', component: () => import('@/modules/sales-canvas/pages/CanvasRequestsPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-canvas/orders', name: 'sales-canvas-orders', component: () => import('@/modules/sales-canvas/pages/CanvasOrdersPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-canvas/returns', name: 'sales-canvas-returns', component: () => import('@/modules/sales-canvas/pages/CanvasReturnsPage.vue'), meta: { permission: 'distribution.orders.view' } },
      {
        path: 'sales-canvas/vouchers',
        name: 'sales-canvas-vouchers',
        component: () => import('@/modules/sales-canvas/pages/CanvasVouchersPage.vue'),
        meta: {
          permission: 'distribution.orders.view',
          pageTitle: 'Info Voucher Canvas',
          pageDescription: 'Voucher yang berlaku untuk order Canvas beserta ketentuan diskonnya.'
        }
      },
      {
        path: 'sales-canvas/vouchers/manage',
        name: 'sales-canvas-vouchers-manage',
        component: () => import('@/modules/promo/pages/PromoVouchersPage.vue'),
        props: { managementScope: 'canvas' },
        meta: {
          permission: 'distribution.orders.view',
          pageTitle: 'Kelola Voucher Canvas',
          pageDescription: 'CRUD Voucher Canvas pada master voucher yang sama dengan Promo All-In.'
        }
      },
      { path: 'sales-canvas/payments', name: 'sales-canvas-payments', component: () => import('@/modules/sales-canvas/pages/CanvasPaymentsPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'sales-canvas/payment-recap', name: 'sales-canvas-payment-recap', component: () => import('@/modules/sales-canvas/pages/CanvasPaymentRecapPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'distribution/picking', name: 'distribution-picking', component: () => import('@/modules/distribution/pages/ShipmentPickingPage.vue'), meta: { permission: 'distribution.picking.view' } },
      { path: 'distribution/invoices', name: 'distribution-invoices', component: () => import('@/modules/distribution/pages/InvoiceDetailPage.vue'), meta: { permission: 'distribution.invoices.view' } },
      { path: 'distribution/invoice-revisions', name: 'distribution-invoice-revisions', component: () => import('@/modules/distribution/pages/InvoiceRevisionPage.vue'), meta: { permission: 'distribution.invoices.view' } },
      {
        path: 'distribution/cancel-realization',
        name: 'distribution-cancel-realization',
        component: () => import('@/modules/distribution/pages/CancelRealizationPage.vue'),
        meta: {
          permission: 'distribution.invoices.view',
          permissionAliases: [
            'distribution.cancel-realisasi.view',
            'distribution.cancel-realisasi.create',
            'distribution.cancel-realisasi.edit',
            'distribution.cancel-realisasi.approve',
            'distribution.cancel-realisasi.final-approve'
          ],
          pageTitle: 'Batal Realisasi',
          pageDescription: 'Request, approval, revisi faktur, dan finalisasi pembatalan realisasi secara terkendali.'
        }
      },
      { path: 'distribution/schedules', name: 'distribution-schedules', component: () => import('@/modules/distribution/pages/ScheduleFleetPage.vue'), meta: { permission: 'distribution.schedules.view' } },
      {
        path: 'distribution/helper-driver',
        name: 'distribution-helper-driver',
        redirect: { name: 'distribution-fleet-management' },
        meta: { permission: 'distribution.schedules.view' }
      },
      {
        path: 'distribution/fleet-management',
        name: 'distribution-fleet-management',
        component: () => import('@/modules/distribution/pages/FleetManagementPage.vue'),
        meta: {
          permission: 'distribution.schedules.view',
          pageTitle: 'Monitoring Armada',
          pageDescription: 'Pantau perjalanan, manifest, GPS armada, POD, dan jadwal maintenance.'
        }
      },
      { path: 'distribution/history', name: 'distribution-history', component: () => import('@/modules/distribution/pages/DistributionHistoryPage.vue'), meta: { permission: 'distribution.invoices.view' } },
      { path: 'distribution/driver-expenses', name: 'distribution-driver-expenses', component: () => import('@/modules/distribution/pages/DriverExpensesPage.vue'), meta: { permission: 'distribution.schedules.view' } },
      { path: 'finance/coa', name: 'finance-coa', component: () => import('@/modules/finance/pages/CoaPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/employee-advances', name: 'finance-employee-advances', component: () => import('@/modules/finance/pages/EmployeeAdvancePage.vue'), meta: { permission: 'finance.employee-advances.view' } },
      { path: 'finance/opening-balance', name: 'finance-opening-balance', component: () => import('@/modules/finance/pages/OpeningBalancePage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/inventaris', name: 'finance-inventaris', component: () => import('@/modules/finance/pages/InventoryAssetsPage.vue'), meta: { permission: 'finance.recap.view', pageTitle: 'Inventaris', pageDescription: 'Kelola aset tetap dan jadwal penyusutan fiskal.' } },
      { path: 'finance/journal-settings', name: 'finance-journal-settings', component: () => import('@/modules/finance/pages/ManualJournalPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/manual-journal', redirect: '/finance/journal-settings' },
      { path: 'finance/journal', name: 'finance-journal', component: () => import('@/modules/finance/pages/JournalPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/company-bank-accounts', name: 'finance-company-bank-accounts', component: () => import('@/modules/finance/pages/CompanyBankAccountsPage.vue'), meta: { permission: 'finance.company-bank-accounts.view' } },
      { path: 'finance/credit-note', name: 'finance-credit-note', component: () => import('@/modules/finance/pages/CreditNotePage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/bank-mutations', name: 'finance-bank-mutations', component: () => import('@/modules/finance/pages/BankMutationPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/profit-loss', name: 'finance-profit-loss', component: () => import('@/modules/finance/pages/ProfitLossPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/valued-stock-card', name: 'finance-valued-stock-card', component: () => import('@/modules/finance/pages/ValuedStockCardPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/balance-sheet', name: 'finance-balance-sheet', component: () => import('@/modules/finance/pages/BalanceSheetPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/customer-receivable-balances', name: 'finance-customer-receivable-balances', component: () => import('@/modules/finance/pages/CustomerReceivableBalancePage.vue'), meta: { permission: 'finance.receivables.view' } },
      { path: 'finance/receivables', name: 'finance-receivables', component: () => import('@/modules/finance/pages/ReceivablesPage.vue'), meta: { permission: 'finance.receivables.view' } },
      { path: 'finance/receipt-workflow', name: 'finance-receipt-workflow', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.receipts.view', workflowTab: 'receipts', pageTitle: 'Pembayaran Tagihan — Kuitansi' } },
      { path: 'finance/receipt-cash', name: 'finance-receipt-cash', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.funds.view', workflowTab: 'cash', pageTitle: 'Setoran Tunai — Kuitansi' } },
      { path: 'finance/receipt-transfer', name: 'finance-receipt-transfer', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.funds.view', workflowTab: 'transfer', pageTitle: 'Setoran Non Tunai — Kuitansi' } },
      { path: 'finance/bank-input', name: 'finance-bank-input', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.bank-input.view', workflowTab: 'bank-input', pageTitle: 'Mutasi Bank' } },
      { path: 'finance/giro-deposits', name: 'finance-giro-deposits', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.funds.view', workflowTab: 'giro', pageTitle: 'Setoran Giro' } },
      { path: 'finance/receipt-cancellation', name: 'finance-receipt-cancellation', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.receipts.view', workflowTab: 'cancel', pageTitle: 'Batal Kuitansi' } },
      { path: 'finance/payment-workflow-settings', name: 'finance-payment-workflow-settings', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.workflow.configure', workflowTab: 'settings', pageTitle: 'Pengaturan Workflow Pembayaran' } },
      { path: 'finance/payment-fees', name: 'finance-payment-fees', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.fees.view', workflowTab: 'fees', pageTitle: 'Master Biaya Lain' } },
      { path: 'finance/payment-workflow-journals', name: 'finance-payment-workflow-journals', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'finance.receipts.view', workflowTab: 'journals', pageTitle: 'Jurnal Pembayaran' } },
      { path: 'sales-order/receipt-lph', name: 'sales-order-receipt-lph', component: () => import('@/modules/finance/pages/ReceiptWorkflowPage.vue'), meta: { permission: 'distribution.orders.view', workflowTab: 'mobile', pageTitle: 'LPH & Pembayaran Sales' } },
      { path: 'finance/payments', name: 'finance-payments', component: () => import('@/modules/finance/pages/PaymentsPage.vue'), meta: { permission: 'finance.payments.view' } },
      {
        path: 'finance/canvas-receivables',
        name: 'finance-canvas-receivables',
        component: () => import('@/modules/finance/pages/CanvasReceivablesPage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Piutang Canvas Finance',
          pageDescription: 'Rekap claim Canvas, catat bukti penerimaan, dan finalisasi tanpa memakai faktur Sales Order.'
        }
      },
      {
        path: 'finance/customer-advances',
        name: 'finance-customer-advances',
        component: () => import('@/modules/finance/pages/CustomerAdvancePage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Uang Muka Customer',
          pageDescription: 'Saldo uang muka dari kelebihan kuitansi dan mutasi bank customer.'
        }
      },
      {
        path: 'finance/recap',
        name: 'finance-recap',
        component: () => import('@/modules/finance/pages/RecapPage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Rekap Pembayaran',
          pageDescription: 'Cocokkan pembayaran customer per sales sebelum diteruskan ke setoran tunai atau non tunai.'
        }
      },
      {
        path: 'finance/payment-cancellation',
        name: 'finance-payment-cancellation',
        component: () => import('@/modules/finance/pages/PaymentCancellationPage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Batal Pembayaran',
          pageDescription: 'Batalkan setoran Rekap yang belum final dengan audit Finance.'
        }
      },
      {
        path: 'finance/cash-deposits',
        name: 'finance-cash-deposits',
        component: () => import('@/modules/finance/pages/CashDepositLegacyPage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Setoran Tunai',
          pageDescription: 'Catat, periksa, dan finalkan setoran kas dari pembayaran yang telah direkap.'
        }
      },
      {
        path: 'finance/noncash-deposits',
        name: 'finance-noncash-deposits',
        component: () => import('@/modules/finance/pages/NonCashDepositLegacyPage.vue'),
        meta: {
          permission: 'finance.recap.view',
          pageTitle: 'Setoran Non Tunai',
          pageDescription: 'Catat bukti transfer atau mutasi dari pembayaran yang telah direkap sebelum pencocokan tagihan.'
        }
      },
      { path: 'finance/cashier-reports', name: 'finance-cashier-reports', component: () => import('@/modules/finance/pages/CashierReportPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/cashier-expenses', name: 'finance-cashier-expenses', component: () => import('@/modules/finance/pages/CashierExpensePage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/accounting-transactions', name: 'finance-accounting-transactions', component: () => import('@/modules/finance/pages/AccountingTransactionPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/sales-billing-letters', name: 'finance-sales-billing-letters', component: () => import('@/modules/finance/pages/SalesBillingLetterPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/lph', name: 'finance-lph', component: () => import('@/modules/finance/pages/LphPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/general-ledger', name: 'finance-general-ledger', component: () => import('@/modules/finance/pages/GeneralLedgerPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/tax', name: 'finance-tax', component: () => import('@/modules/finance/pages/TaxPage.vue'), meta: { permission: 'finance.recap.view' } },
      { path: 'finance/deposit-finalization', name: 'finance-deposit-finalization', component: () => import('@/modules/finance/pages/DepositFinalizationPage.vue'), meta: { permission: 'finance.recap.view', pageTitle: 'Finalisasi Setoran', pageDescription: 'Kelola grup setoran, proses kasir, dan finalisasi finance.' } },
      { path: 'reports/route-customers', name: 'reports-route-customers', component: () => import('@/modules/reports/pages/RouteCustomerReportPage.vue'), meta: { permission: 'distribution.orders.view', pageTitle: 'Rute Customer', pageDescription: 'Daftar rute, customer, polyline map, dan estimasi perjalanan.' } },
      { path: 'purchase/orders', name: 'purchase-orders', component: () => import('@/modules/purchase/pages/PurchaseOrdersPage.vue'), meta: { permission: 'purchase.orders.view' } },
      { path: 'purchase/orders/create', name: 'purchase-orders-create', component: () => import('@/modules/purchase/pages/PurchaseOrderCreatePage.vue'), meta: { permission: 'purchase.orders.create' } },
      { path: 'purchase/orders/edit/:id', name: 'purchase-orders-edit', component: () => import('@/modules/purchase/pages/PurchaseOrderCreatePage.vue'), meta: { permission: 'purchase.orders.update' } },
      { path: 'purchase/order-reports', name: 'purchase-order-reports', component: () => import('@/modules/purchase/pages/PurchaseOrderReportPage.vue'), meta: { permission: 'purchase.orders.view' } },
      { path: 'purchase/branch-requests/create', name: 'purchase-branch-requests-create', component: () => import('@/modules/purchase/pages/PurchaseOrderCreatePage.vue'), meta: { permission: 'purchase.orders.create', pageTitle: 'Buat Request Cabang' } },
      { path: 'purchase/branch-requests', name: 'purchase-branch-requests', component: () => import('@/modules/purchase/pages/PurchaseBranchRequestConfirmationPage.vue'), meta: { permission: 'purchase.branch-requests.approve' } },
      { path: 'purchase/order-confirmations', name: 'purchase-order-confirmations', component: () => import('@/modules/purchase/pages/PurchaseOrderConfirmationPage.vue'), meta: { permission: 'purchase.order-confirmations.approve' } },
      { path: 'purchase/receipts', name: 'purchase-receipts', component: () => import('@/modules/purchase/pages/PurchaseReceiptsPage.vue'), meta: { permission: 'purchase.receipts.view' } },
      { path: 'purchase/receipts/create', name: 'purchase-receipts-create', component: () => import('@/modules/purchase/pages/PurchaseReceiptCreatePage.vue'), meta: { permission: 'purchase.receipts.create' } },
      { path: 'purchase/confirmations', name: 'purchase-confirmations', component: () => import('@/modules/purchase/pages/PurchaseConfirmationPage.vue'), meta: { permission: 'purchase.confirmations.approve' } },
      { path: 'purchase/bills', name: 'purchase-bills', component: () => import('@/modules/purchase/pages/PurchaseBillsPage.vue'), meta: { permission: 'purchase.bills.view' } },
      { path: 'promo', redirect: () => resolvePromoLanding() },
      { path: 'promo/all-in', name: 'promo-all-in', component: () => import('@/modules/promo/pages/UnifiedPromoPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/claim-categories', name: 'promo-claim-categories', component: () => import('@/modules/promo/pages/PromoClaimCategoriesPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/vouchers', name: 'promo-vouchers', component: () => import('@/modules/promo/pages/PromoVouchersPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/vouchers/monitoring', name: 'promo-vouchers-monitoring', component: () => import('@/modules/promo/pages/PromoVoucherMonitoringPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/vouchers/by-product', name: 'promo-vouchers-by-product', component: () => import('@/modules/promo/pages/PromoVoucherByProductPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/vouchers/approval', name: 'promo-vouchers-approval', component: () => import('@/modules/promo/pages/PromoVoucherApprovalPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/trade-cashback', name: 'promo-trade-cashback', component: () => import('@/modules/promo/pages/TradePromoMonitoringPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/claims', name: 'promo-claims', component: () => import('@/modules/promo/pages/PromoClaimsPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/claims/approval', name: 'promo-claims-approval', component: () => import('@/modules/promo/pages/PromoClaimsApprovalPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/claims/create', name: 'promo-claims-create', component: () => import('@/modules/promo/pages/PromoClaimCreatePage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/kasbon', name: 'promo-kasbon', component: () => import('@/modules/promo/pages/PromoKasbonPage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'promo/kasbon/create', name: 'promo-kasbon-create', component: () => import('@/modules/promo/pages/PromoKasbonCreatePage.vue'), meta: { permission: 'distribution.orders.view' } },
      { path: 'wms', name: 'wms-dashboard', component: () => import('@/modules/wms/pages/WmsDashboardPage.vue'), meta: { permission: 'wms.view', wmsSection: 'monitoring', pageTitle: 'WMS Monitoring', pageDescription: 'Inventory rak, incoming, picking, loading, dropping, transfer rak, transaksi, dan alert gudang.' } },
      { path: 'wms/rak-3d', name: 'wms-rak-3d', component: () => import('@/modules/wms/pages/WmsRack3DPage.vue'), meta: { permission: 'wms.view', pageTitle: 'Rak 3D WMS', pageDescription: 'Visual lokasi rak, isi rak, status aktif, dan alur perpindahan palet gudang.' } },
      { path: 'wms/master-rak', name: 'wms-master-rak', component: () => import('@/modules/wms/pages/WmsDashboardPage.vue'), meta: { permission: 'wms.view', wmsSection: 'racks', pageTitle: 'Master Rak WMS', pageDescription: 'Kelola master rak gudang dan status aktif rak.' } },
      { path: 'wms/master-pallet', name: 'wms-master-pallet', component: () => import('@/modules/wms/pages/WmsDashboardPage.vue'), meta: { permission: 'wms.view', wmsSection: 'pallets', pageTitle: 'Master Pallet WMS', pageDescription: 'Kelola pallet, batas berat, batas qty, dan status pemakaian pallet.' } },
      { path: 'wms/penempatan', name: 'wms-penempatan', component: () => import('@/modules/wms/pages/WmsDashboardPage.vue'), meta: { permission: 'wms.view', wmsSection: 'placements', pageTitle: 'Penempatan Barang WMS', pageDescription: 'Kelola penempatan barang di rak dan penyesuaian stok rak.' } },
      { path: 'stock-transfer', name: 'stock-transfer-list', component: () => import('@/modules/stock-transfer/pages/TransferListPage.vue'), meta: { permission: 'stock-transfer.view' } },
      { path: 'stock-transfer/create', name: 'stock-transfer-create', component: () => import('@/modules/stock-transfer/pages/TransferCreatePage.vue'), meta: { permission: 'stock-transfer.create' } },
      { path: 'stock-transfer/detail', name: 'stock-transfer-detail', component: () => import('@/modules/stock-transfer/pages/TransferDetailPage.vue'), meta: { permission: 'stock-transfer.view' } },
      { path: 'stock-transfer/confirmations', name: 'stock-transfer-confirmations', component: () => import('@/modules/stock-transfer/pages/TransferProcessPage.vue'), meta: { permission: 'stock-transfer.view', processMode: 'confirmation' } },
      { path: 'stock-transfer/shipments', name: 'stock-transfer-shipments', component: () => import('@/modules/stock-transfer/pages/TransferProcessPage.vue'), meta: { permission: 'stock-transfer.view', processMode: 'shipment' } },
      { path: 'stock-transfer/receipts', name: 'stock-transfer-receipts', component: () => import('@/modules/stock-transfer/pages/TransferProcessPage.vue'), meta: { permission: 'stock-transfer.view', processMode: 'receipt' } },
      { path: 'stock-transfer/shipment-status', name: 'stock-transfer-shipment-status', component: () => import('@/modules/stock-transfer/pages/TransferProcessPage.vue'), meta: { permission: 'stock-transfer.view', processMode: 'status' } },
      { path: 'stock-transfer/escalations', name: 'stock-transfer-escalations', component: () => import('@/modules/stock-transfer/pages/TransferProcessPage.vue'), meta: { permission: 'stock-transfer.view', processMode: 'escalation' } },
      { path: 'stock-opname', name: 'stock-opname-list', component: () => import('@/modules/stock-opname/pages/StockOpnameListPage.vue'), meta: { permission: 'stock-opname.view', pageTitle: 'Stok Opname', pageDescription: 'Daftar stok opname, detail produk, dan approval operasional.' } },
      { path: 'stock-opname/create', name: 'stock-opname-create', component: () => import('@/modules/stock-opname/pages/StockOpnameCreatePage.vue'), meta: { permission: 'stock-opname.create' } },
      { path: 'stock-opname/report', name: 'stock-opname-report', component: () => import('@/modules/stock-opname/pages/StockReportPage.vue'), meta: { permission: 'stock-opname.view' } },
      { path: 'stock-opname/escalations', name: 'stock-opname-escalations', component: () => import('@/modules/stock-opname/pages/StockOpnameEscalationPage.vue'), meta: { permission: 'stock-opname.view' } },
      { path: 'supervisor-sales/dashboard', name: 'supervisor-sales-dashboard', component: () => import('@/modules/supervisor-sales/pages/SupervisorDashboardPage.vue'), meta: { permission: 'supervisor-sales.dashboard.view' } },
      { path: 'supervisor-sales/visits', name: 'supervisor-sales-visits', component: () => import('@/modules/supervisor-sales/pages/SupervisorVisitSalesPage.vue'), meta: { permission: 'supervisor-sales.visits.view' } },
      { path: 'supervisor-sales/performance-checklist', name: 'supervisor-sales-performance-checklist', component: () => import('@/modules/supervisor-sales/pages/SupervisorPerformanceChecklistPage.vue'), meta: { permission: 'supervisor-sales.dashboard.view', pageTitle: 'Checklist Kinerja Sales', pageDescription: 'Checklist harian supervisor untuk memantau callplan, stock opname, omset, retur, LPH, dan pembayaran sales.' } },
      { path: 'supervisor-sales/customer-map', name: 'supervisor-sales-customer-map', component: () => import('@/modules/supervisor-sales/pages/SupervisorCustomerMapPage.vue'), meta: { permission: 'supervisor-sales.visits.view', pageTitle: 'Mapping Customer', pageDescription: 'Peta customer supervisor, histori order barang, frekuensi pembelian, dan status tidak order 30 hari.' } },
      { path: 'supervisor-sales/callplan-calendar', name: 'supervisor-sales-callplan-calendar', component: () => import('@/modules/supervisor-sales/pages/SupervisorCallplanCalendarPage.vue'), meta: { permission: 'supervisor-sales.callplan.view', pageTitle: 'Kalender Call Plan Sales', pageDescription: 'Supervisor melihat beban callplan sales per hari dalam bentuk kalender bulanan.' } },
      { path: 'supervisor-sales/stock-opname-monitor', name: 'supervisor-sales-stock-opname-monitor', component: () => import('@/modules/supervisor-sales/pages/SupervisorStockOpnameMonitorPage.vue'), meta: { permission: 'supervisor-sales.stock-opname-monitor.view', pageTitle: 'Monitoring Stok Opname', pageDescription: 'Area supervisor sales untuk memantau stok opname dari aktivitas kunjungan dan tindak lanjut tim sales.' } },
      { path: 'supervisor-sales/sales-target-settings', name: 'supervisor-sales-target-settings', component: () => import('@/modules/supervisor-sales/pages/SupervisorSalesTargetSettingsPage.vue'), meta: { permission: 'supervisor-sales.targets.update', pageTitle: 'Setting Target Sales', pageDescription: 'Halaman supervisor sales untuk menyusun target penjualan dan distribusi target ke tim sales.' } },
      { path: 'supervisor-sales/omset-target-monitor', name: 'supervisor-sales-omset-target-monitor', component: () => import('@/modules/supervisor-sales/pages/SupervisorOmsetTargetMonitorPage.vue'), meta: { permission: 'supervisor-sales.targets.view', pageTitle: 'Monitoring Target Omset', pageDescription: 'Halaman supervisor sales untuk memantau capaian omset terhadap target sales per periode.' } },
      { path: 'supervisor-sales/retur-approval', name: 'supervisor-sales-retur-approval', redirect: { name: 'sales-order-retur-list' }, meta: { permission: 'distribution.orders.view' } },
      { path: 'supervisor-sales/attendance', name: 'supervisor-sales-attendance', component: () => import('@/modules/supervisor-sales/pages/SupervisorSalesAttendancePage.vue'), meta: { permission: 'supervisor-sales.attendance.view', pageTitle: 'Absensi Sales', pageDescription: 'Ringkasan kehadiran, check-in, dan kedisiplinan lapangan untuk tim sales.' } },
      { path: 'supervisor-sales/kasbon', name: 'supervisor-sales-kasbon', component: () => import('@/modules/supervisor-sales/pages/SupervisorKasbonPage.vue'), meta: { permission: 'supervisor-sales.kasbon.approve', pageTitle: 'Approval Kasbon', pageDescription: 'Monitoring pengajuan kasbon sales yang akan ditindaklanjuti supervisor.' } },
      { path: 'supervisor-sales/doi-analysis', name: 'supervisor-sales-doi-analysis', component: () => import('@/modules/supervisor-sales/pages/SupervisorDoiAnalysisPage.vue'), meta: { permission: 'supervisor-sales.doi.view', pageTitle: 'Analisa DOI', pageDescription: 'Analisa DOI untuk membantu supervisor sales membaca pergerakan stok dan kebutuhan follow-up.' } },
      { path: 'supervisor-sales/audit-log', name: 'supervisor-sales-audit-log', component: () => import('@/modules/supervisor-sales/pages/SupervisorAuditLogPage.vue'), meta: { permission: 'supervisor-sales.audit.view', pageTitle: 'Audit Log Supervisor', pageDescription: 'Jejak approval, perubahan target, callplan, stok opname, kasbon, dan analisa supervisor.' } }
    ]
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    return { top: 0 };
  }
});

setupAuthGuard(router);

export default router;
