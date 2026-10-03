# Audit Filter Halaman

Tanggal audit: 2026-06-06

Tujuan:
- Menampung semua halaman yang punya filter/search/scope.
- Menentukan prioritas perbaikan filter agar konsisten.
- Standar target untuk filter scope: Perusahaan -> Cabang -> data turunan.

Catatan:
- Daftar ini hasil scan awal source Vue.
- Label `branch-first/mixed` adalah indikator awal dari kode, bukan vonis final UI. Saat perbaikan, tiap halaman tetap dicek manual.
- Halaman yang tidak memakai cabang/perusahaan tetap masuk daftar jika punya search/status/date filter.

## Standar Target

Urutan filter operasional:
1. Perusahaan
2. Cabang
3. Principal
4. Sales
5. Customer
6. Rute atau data turunan lain
7. Status
8. Tanggal/periode
9. Search text

Aturan perilaku:
- Cabang mengikuti perusahaan yang dipilih.
- Principal mengikuti perusahaan.
- Sales mengikuti cabang dan/atau principal sesuai konteks halaman.
- Customer mengikuti cabang/sales/principal bila datanya tersedia.
- Untuk user non-super, default scope login tetap dipakai, tetapi urutan UI dan dependensi data tetap konsisten.
- Reset filter tidak boleh menghilangkan scope wajib user non-super.

## Ringkasan

- Total file Vue discan: 119
- P1: 77 halaman
- P2: 13 halaman
- P3: 23 halaman

Prioritas:
- P1: Halaman list/report/monitor operasional yang punya kombinasi perusahaan dan cabang.
- P2: Halaman create/detail/form yang punya scope cabang/perusahaan atau turunan.
- P3: Filter sederhana, search-only, status-only, date-only, atau branch-only.

## P1 - Perlu Audit dan Standardisasi Utama

AI:
- `src/modules/ai/pages/AiAssistantPage.vue` - branch-first/mixed

Distribution:
- `src/modules/distribution/pages/DistributionHistoryPage.vue` - branch-first/mixed
- `src/modules/distribution/pages/DriverExpensesPage.vue` - branch-first/mixed
- `src/modules/distribution/pages/HelperDriverMonitorPage.vue` - company-first
- `src/modules/distribution/pages/InvoiceDetailPage.vue` - branch-first/mixed
- `src/modules/distribution/pages/InvoiceRevisionPage.vue` - branch-first/mixed
- `src/modules/distribution/pages/OrdersPage.vue` - branch-first/mixed
- `src/modules/distribution/pages/PickingPage.vue` - company-first
- `src/modules/distribution/pages/ScheduleFleetPage.vue` - company-first

Finance:
- `src/modules/finance/pages/AccountingTransactionPage.vue` - branch-first/mixed
- `src/modules/finance/pages/BalanceSheetPage.vue` - branch-first/mixed
- `src/modules/finance/pages/BankMutationPage.vue` - branch-first/mixed
- `src/modules/finance/pages/CashDepositLegacyPage.vue` - branch-first/mixed
- `src/modules/finance/pages/CashierExpensePage.vue` - branch-first/mixed
- `src/modules/finance/pages/CashierReportPage.vue` - branch-first/mixed
- `src/modules/finance/pages/CoaPage.vue` - branch-first/mixed
- `src/modules/finance/pages/CompanyBankAccountsPage.vue` - branch-first/mixed
- `src/modules/finance/pages/CreditNotePage.vue` - company-first
- `src/modules/finance/pages/DepositFinalizationPage.vue` - branch-first/mixed
- `src/modules/finance/pages/JournalPage.vue` - company-first
- `src/modules/finance/pages/LphPage.vue` - branch-first/mixed
- `src/modules/finance/pages/ManualJournalPage.vue` - branch-first/mixed
- `src/modules/finance/pages/NonCashDepositLegacyPage.vue` - branch-first/mixed
- `src/modules/finance/pages/OpeningBalancePage.vue` - branch-first/mixed
- `src/modules/finance/pages/ProfitLossPage.vue` - branch-first/mixed
- `src/modules/finance/pages/SalesBillingLetterPage.vue` - company-first
- `src/modules/finance/pages/TaxPage.vue` - company-first
- `src/modules/finance/pages/ValuedStockCardPage.vue` - branch-first/mixed

Master:
- `src/modules/master/pages/BudgetsPage.vue` - company-only/mixed
- `src/modules/master/pages/CompaniesPage.vue` - branch-first/mixed
- `src/modules/master/pages/CustomersPage.vue` - branch-first/mixed
- `src/modules/master/pages/FleetsPage.vue` - branch-first/mixed
- `src/modules/master/pages/PlafonsPage.vue` - branch-first/mixed
- `src/modules/master/pages/PrincipalRulesPage.vue` - branch-first/mixed
- `src/modules/master/pages/PrincipalsPage.vue` - branch-first/mixed
- `src/modules/master/pages/ProductsPage.vue` - company-only/mixed
- `src/modules/master/pages/RoutesPage.vue` - branch-first/mixed
- `src/modules/master/pages/SalesPage.vue` - branch-first/mixed
- `src/modules/master/pages/UsersPage.vue` - branch-first/mixed

Promo:
- `src/modules/promo/pages/PromoClaimsApprovalPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoClaimsPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoKasbonPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoVoucherApprovalPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoVoucherByProductPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoVoucherMonitoringPage.vue` - branch-first/mixed
- `src/modules/promo/pages/PromoVouchersPage.vue` - branch-first/mixed
- `src/modules/promo/pages/TradePromoMonitoringPage.vue` - branch-first/mixed
- `src/modules/promo/pages/UnifiedPromoPage.vue` - branch-first/mixed

Purchase:
- `src/modules/purchase/pages/PurchaseBillsPage.vue` - branch-first/mixed
- `src/modules/purchase/pages/PurchaseBranchRequestConfirmationPage.vue` - branch-first/mixed
- `src/modules/purchase/pages/PurchaseConfirmationPage.vue` - branch-first/mixed
- `src/modules/purchase/pages/PurchaseOrderConfirmationPage.vue` - branch-first/mixed
- `src/modules/purchase/pages/PurchaseOrderReportPage.vue` - branch-first/mixed
- `src/modules/purchase/pages/PurchaseOrdersPage.vue` - company-first
- `src/modules/purchase/pages/PurchaseReceiptsPage.vue` - branch-first/mixed

Sales Canvas:
- `src/modules/sales-canvas/pages/CanvasOrdersPage.vue` - branch-first/mixed
- `src/modules/sales-canvas/pages/CanvasPaymentRecapPage.vue` - branch-first/mixed
- `src/modules/sales-canvas/pages/CanvasPaymentsPage.vue` - branch-first/mixed
- `src/modules/sales-canvas/pages/CanvasRequestsPage.vue` - branch-first/mixed
- `src/modules/sales-canvas/pages/CanvasReturnsPage.vue` - branch-first/mixed

Sales Order:
- `src/modules/sales-order/pages/SalesInvoiceListPage.vue` - branch-first/mixed
- `src/modules/sales-order/pages/SalesOrderListPage.vue` - branch-first/mixed
- `src/modules/sales-order/pages/SalesReturListPage.vue` - branch-first/mixed
- `src/modules/sales-order/pages/SalesStockOpnamePage.vue` - branch-first/mixed

Stock Opname:
- `src/modules/stock-opname/pages/StockOpnameEscalationPage.vue` - company-first
- `src/modules/stock-opname/pages/StockOpnameListPage.vue` - company-first
- `src/modules/stock-opname/pages/StockReportPage.vue` - company-first

Stock Transfer:
- `src/modules/stock-transfer/pages/TransferListPage.vue` - branch-first/mixed
- `src/modules/stock-transfer/pages/TransferProcessPage.vue` - company-first

Supervisor Sales:
- `src/modules/supervisor-sales/pages/SupervisorAuditLogPage.vue` - branch-first/mixed
- `src/modules/supervisor-sales/pages/SupervisorCallplanCalendarPage.vue` - branch-first/mixed
- `src/modules/supervisor-sales/pages/SupervisorDoiAnalysisPage.vue` - company-first
- `src/modules/supervisor-sales/pages/SupervisorOmsetTargetMonitorPage.vue` - branch-first/mixed
- `src/modules/supervisor-sales/pages/SupervisorReturApprovalPage.vue` - branch-first/mixed
- `src/modules/supervisor-sales/pages/SupervisorSalesAttendancePage.vue` - company-first
- `src/modules/supervisor-sales/pages/SupervisorSalesTargetSettingsPage.vue` - branch-first/mixed
- `src/modules/supervisor-sales/pages/SupervisorStockOpnameMonitorPage.vue` - branch-first/mixed

## P2 - Scope pada Form/Create/Detail

- `src/modules/data-tools/pages/ImportDownloadDataPage.vue`
- `src/modules/finance/pages/PaymentsPage.vue`
- `src/modules/finance/pages/RecapPage.vue`
- `src/modules/finance/pages/ReceivablesPage.vue`
- `src/modules/master/pages/SalesSupervisorMapPage.vue`
- `src/modules/purchase/pages/PurchaseOrderCreatePage.vue`
- `src/modules/purchase/pages/PurchaseReceiptCreatePage.vue`
- `src/modules/sales-order/pages/SalesOrderCreatePage.vue`
- `src/modules/stock-opname/pages/StockOpnameCreatePage.vue`
- `src/modules/stock-transfer/pages/TransferCreatePage.vue`
- `src/modules/stock-transfer/pages/TransferDetailPage.vue`
- `src/modules/supervisor-sales/pages/SupervisorDashboardPage.vue`
- `src/modules/supervisor-sales/pages/SupervisorVisitSalesPage.vue`

## P3 - Filter Sederhana atau Tidak Perlu Scope Perusahaan-Cabang

- `src/modules/dashboard/pages/DashboardPage.vue`
- `src/modules/finance/pages/GeneralLedgerPage.vue`
- `src/modules/master/pages/BranchesPage.vue`
- `src/modules/master/pages/ClosedPeriodsPage.vue`
- `src/modules/master/pages/CustomerTypesPage.vue`
- `src/modules/master/pages/DepartmentsPage.vue`
- `src/modules/master/pages/DriversPage.vue`
- `src/modules/master/pages/HelpersPage.vue`
- `src/modules/master/pages/MasterRolePage.vue`
- `src/modules/master/pages/PositionFeaturesPage.vue`
- `src/modules/master/pages/PositionsPage.vue`
- `src/modules/master/pages/ProductPpnPage.vue`
- `src/modules/master/pages/SalesTypesPage.vue`
- `src/modules/master/pages/SubbrandsPage.vue`
- `src/modules/master/pages/UserFeaturesPage.vue`
- `src/modules/promo/pages/PromoClaimCategoriesPage.vue`
- `src/modules/promo/pages/PromoClaimCreatePage.vue`
- `src/modules/promo/pages/PromoKasbonCreatePage.vue`
- `src/modules/sales-canvas/pages/CanvasVouchersPage.vue`
- `src/modules/sales-order/pages/SalesReturPage.vue`
- `src/modules/supervisor-sales/pages/SupervisorKasbonPage.vue`
- `src/modules/wms/pages/WmsDashboardPage.vue`
- `src/modules/workflow/pages/WorkflowCenterPage.vue`

## Urutan Perbaikan Disarankan

1. Sales Order, Finance penagihan/pembayaran, Distribution.
2. Purchase dan Promo.
3. Master yang punya scope relasi.
4. Supervisor Sales dan Stock Opname.
5. P2 form/create.
6. P3 bila memang perlu disamakan tampilan saja.

## Checklist Per Halaman Saat Diperbaiki

- Filter perusahaan tampil sebelum cabang.
- Cabang difilter oleh perusahaan.
- Principal difilter oleh perusahaan.
- Sales difilter oleh cabang dan/atau principal sesuai konteks.
- Customer difilter oleh scope customer multi-cabang/perusahaan bila tersedia.
- Reset mempertahankan scope user login bila user bukan super.
- Parameter API tidak berubah nama kecuali endpoint memang mendukung.
- Build frontend sukses.
- Halaman dicek cepat di browser atau minimal URL live 200 setelah deploy.
