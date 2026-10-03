import api from './axios';

function toFormPayload(payload = {}) {
  const form = new URLSearchParams();

  Object.entries(payload || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      form.append(key, value);
    }
  });

  return form;
}

function baseFormRequestConfig(params) {
  return {
    params,
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded'
    }
  };
}

export function getDueReceivables(plafonId, params) {
  return api.get(`/api/finance/list-tagihan-jatuh-tempo/${plafonId}`, { params });
}

export function getFinanceInvoices(plafonId, params) {
  return api.get(`/api/finance/list-faktur/${plafonId}`, { params });
}

export function getPaymentPlafons(params) {
  return api.get('/api/finance/payment-plafons', { params });
}

export function getPaymentLphs(params) {
  return api.get('/api/finance/payment-lphs', { params });
}

export function getPaymentLphDetail(params) {
  return api.get('/api/finance/payment-lph-detail', { params });
}

export function reconcilePaymentLph(payload) {
  return api.post('/api/finance/payment-lph-reconcile', payload);
}

/**
 * Canvas has an isolated Finance receivable lane.  Canvas Orders never borrow
 * a synthetic Sales Order/faktur or the normal LPH payment endpoints.
 */
export function getCanvasPaymentRecapCandidates(params) {
  return api.get('/api/finance/canvas-rekap-candidates', { params });
}

export function getCanvasFinanceReceivables(params) {
  return api.get('/api/finance/canvas-receivables', { params });
}

export function submitCanvasPaymentRecap(payload) {
  return api.post('/api/finance/canvas-payments/rekap', payload);
}

export function recordCanvasFinancePayment(id, payload) {
  return api.post(`/api/finance/canvas-payments/${id}/record`, payload);
}

export function retryCanvasFinanceJournal(id) {
  return api.post(`/api/finance/canvas-payments/${id}/journal/retry`);
}

export function finalizeCanvasFinancePayment(id, payload = {}) {
  return api.post(`/api/finance/canvas-payments/${id}/finalize`, payload);
}

/**
 * Controlled LPH expense/rounding adjustments. These rows deliberately live
 * outside `setoran`: an approved PENGURANG_SETORAN changes only the Finance
 * net-receipt control display, never a Mobile Sales claim or invoice balance.
 */
export function getPaymentExpenseAdjustments(params) {
  return api.get('/api/finance/payment-expense-adjustments', { params });
}

export function createPaymentExpenseAdjustment(payload) {
  return api.post('/api/finance/payment-expense-adjustments', payload);
}

export function approvePaymentExpenseAdjustment(id, payload = {}) {
  return api.post(`/api/finance/payment-expense-adjustments/${id}/approve`, payload);
}

export function voidPaymentExpenseAdjustment(id, payload) {
  return api.post(`/api/finance/payment-expense-adjustments/${id}/void`, payload);
}

export function bindNonCashMutation(payload) {
  return api.post('/api/finance/bind-noncash-mutation', payload);
}

/**
 * Allocate one incoming bank mutation to one or more non-cash deposits.
 *
 * Contract for the Finance API (implemented server-side separately):
 * {
 *   id_lph: number,
 *   id_mutasi: number,
 *   id_customer?: number, // server derives/validates it from selected deposits
 *   allocations: [{ id_setoran: number, nominal_alokasi: number }],
 *   surplus_disposition: 'ADVANCE' | 'UNALLOCATED',
 *   catatan?: string
 * }
 *
 * The server must lock the mutation and deposits, reject cross-customer /
 * cross-company allocations, require each `nominal_alokasi` to equal that
 * source Rekap deposit's remaining amount (no Finance-side split), retain the
 * unallocated `sisa`, and create a pending customer advance when
 * surplus_disposition is ADVANCE.
 */
export function allocateNonCashMutation(payload) {
  return api.post('/api/finance/allocate-noncash-mutation', payload);
}

/**
 * Controlled cancellation is intentionally limited to a payment that has
 * entered Rekap/Setoran but has not reached Finance finalisation.  The API
 * records an immutable audit row and reopens the original Mobile Sales source
 * for Rekap; it never deletes a financial record.
 */
export function getPreFinalPaymentCancellationCandidates(params) {
  return api.get('/api/finance/payment-cancellation-candidates', { params });
}

export function cancelPreFinalPayment(payload) {
  return api.post('/api/finance/cancel-pre-final-payment', payload);
}

/**
 * Retry one durable Finance journal event. This is intentionally separate
 * from finalising a deposit: a retry must never re-run the money transition.
 */
export function retryFinanceJournalOutbox(id) {
  return api.post(`/api/finance/journal-outbox/${id}/retry`);
}

/**
 * Customer advance contracts.  Advances are created from a bank-mutation
 * surplus and require finance approval before they can be used on another
 * invoice.  The list/detail endpoints return balance and immutable audit
 * history; the approve endpoint accepts { catatan_approval? }.
 */
export function getCustomerAdvances(params) {
  return api.get('/api/finance/customer-advances', { params });
}

export function getCustomerAdvanceDetail(id) {
  return api.get(`/api/finance/customer-advances/${id}`);
}

export function approveCustomerAdvance(id, payload = {}) {
  return api.post(`/api/finance/customer-advances/${id}/approve`, payload);
}

export function rejectCustomerAdvance(id, payload = {}) {
  return api.post(`/api/finance/customer-advances/${id}/reject`, payload);
}

export function getCustomerAdvanceEligibleInvoices(id, params) {
  return api.get(`/api/finance/customer-advances/${id}/eligible-invoices`, { params });
}

/**
 * Apply an approved customer advance to one or more outstanding invoices.
 * Contract: { allocations: [{ id_faktur, nominal_pakai }], catatan?: string }.
 * The server must atomically validate the remaining advance balance and each
 * invoice balance, then append immutable usage-history rows.
 */
export function useCustomerAdvance(id, payload) {
  return api.post(`/api/finance/customer-advances/${id}/use`, payload);
}

export function updateFinanceInvoiceStatuses(payload) {
  return api.post('/api/finance/update-status-fakturs', payload);
}

export function createPayment(payload) {
  return api.post('/api/finance/create-payment', payload);
}

export function getEligiblePaymentVouchers(params) {
  return api.get('/api/finance/eligible-payment-vouchers', { params });
}

export function getCustomerDepositHistory(params) {
  return api.get('/api/finance/riwayat-setoran-customer', { params });
}

export function getPaymentReconciliation(params) {
  return api.get('/api/finance/payment-reconciliation', { params });
}

export function getCustomerReceivableBalances(params) {
  return api.get('/api/finance/customer-receivable-balances', { params });
}

export function getCustomerReceivableInvoices(params) {
  return api.get('/api/finance/customer-receivable-invoices', { params });
}

export function getSalesPaymentRecap(params) {
  return api.get('/api/finance/rekap-pembayaran-sales', { params });
}

export function submitSalesPaymentRecap(payload) {
  // Large Mobile Sales batches are handled atomically by Finance.  The
  // server is optimised for bulk updates, while this client allowance keeps a
  // slow but healthy request from being reported as a false 30-second error.
  return api.post('/api/finance/submit-rekap-pembayaran-sales', payload, { timeout: 120000 });
}

export function getDepositGroups(type = 'cash', params) {
  const endpoint = type === 'noncash' ? '/api/akuntansi/list-setoran-non-tunai' : '/api/akuntansi/list-setoran-tunai';
  return api.get(endpoint, { params });
}

export function getDepositGroupDetail(params) {
  return api.get('/api/akuntansi/detail-setoran', { params });
}

export function getCashDepositConfirmations(params) {
  return api.get('/api/akuntansi/get-list-konfirmasi-setoran-tunai', { params });
}

export function getCashDepositConfirmationDetail(namaPj, draftTanggalInput) {
  return api.get(`/api/akuntansi/get-detail-setoran-tunai/${encodeURIComponent(namaPj)}/${draftTanggalInput}`);
}

export function saveCashierDeposit(payload) {
  return api.post('/api/akuntansi/simpan-kasir-setoran', payload);
}

export function createDepositRecord(payload) {
  return api.post('/api/akuntansi/create-setoran', payload);
}

export function updateDepositRecord(id, payload) {
  return api.put(`/api/akuntansi/update-setoran/${id}`, payload);
}

export function deleteDepositRecord(id) {
  return api.delete(`/api/akuntansi/delete-setoran/${id}`);
}

export function confirmDepositStage(payload) {
  return api.post('/api/akuntansi/konfirmasi-setoran', payload);
}

export function getNonCashDepositConfirmations(params) {
  return api.get('/api/akuntansi/get-list-konfirmasi-setoran-nontunai', { params });
}

export function getNonCashDepositConfirmationDetail(idMutasi) {
  return api.get(`/api/akuntansi/get-detail-setoran-nontunai/${idMutasi}`);
}

export function getSalesBillingLetters(params) {
  return api.get('/api/akuntansi/get-tagihan-sales', { params });
}

export function getSalesBillingLetterDetail(params) {
  return api.get('/api/akuntansi/detail-tagihan-sales', { params });
}

export function getGeneralLedger(params) {
  return api.get('/api/akuntansi/get-bukubesar', { params });
}

export function getProfitLoss(params) {
  return api.get('/api/akuntansi/get-laba-rugi', { params });
}

export function getValuedStockCard(params) {
  return api.get('/api/akuntansi/inventory-ledger', { params });
}

export function backfillInventoryLedger(payload) {
  return api.post('/api/akuntansi/inventory-ledger/backfill', payload);
}

export function getBalanceSheet(params) {
  return api.get('/api/akuntansi/get-neraca', { params });
}

export function getInventoryTaxRules() {
  return api.get('/api/akuntansi/inventaris/tax-rules');
}

export function getFixedAssets(params) {
  return api.get('/api/akuntansi/inventaris', { params });
}

export function getFixedAssetSchedule(id) {
  return api.get(`/api/akuntansi/inventaris/${id}`);
}

export function createFixedAsset(payload) {
  return api.post('/api/akuntansi/inventaris', payload);
}

export function updateFixedAsset(id, payload) {
  return api.put(`/api/akuntansi/inventaris/${id}`, payload);
}

export function deleteFixedAsset(id) {
  return api.delete(`/api/akuntansi/inventaris/${id}`);
}

export function getJournalList(params) {
  return api.get('/api/akuntansi/get-jurnal', { params });
}

export function getJournalDetail(id) {
  return api.get(`/api/akuntansi/detail-jurnal/${id}`);
}

export function getCoaCatalog(params) {
  return api.get('/api/akuntansi/get-list-coa', { params });
}

export function getCoaActivity(id, params) {
  return api.get(`/api/akuntansi/coa/${id}/activity`, { params });
}

export function getCoaCashAccounts(id, params) {
  return api.get(`/api/akuntansi/coa/${id}/cash-accounts`, { params });
}

export function linkCoaCashAccount(id, bankId) {
  return api.put(`/api/akuntansi/coa/${id}/cash-accounts/${bankId}`, {});
}

export function unlinkCoaCashAccount(id, bankId) {
  return api.delete(`/api/akuntansi/coa/${id}/cash-accounts/${bankId}`);
}

export function getEmployeeAdvances(params) {
  return api.get('/api/akuntansi/employee-advances', { params });
}

export function getEmployeeAdvance(id) {
  return api.get(`/api/akuntansi/employee-advances/${id}`);
}

export function getEmployeeAdvanceEmployees(params) {
  return api.get('/api/akuntansi/employee-advances/employees', { params });
}

export function createEmployeeAdvance(payload) {
  return api.post('/api/akuntansi/employee-advances', payload);
}

export function decideEmployeeAdvance(id, payload) {
  return api.post(`/api/akuntansi/employee-advances/${id}/decision`, payload);
}

export function getAccountCoaList(params) {
  return api.get('/api/akuntansi/get-list-coa-list', { params });
}

export function getCoaCategoryList() {
  return api.get('/api/akuntansi/get-coa-category-list');
}

export function createCoa(payload) {
  return api.post('/api/akuntansi/insert-coa', payload);
}

export function updateCoa(payload) {
  return api.put('/api/akuntansi/update-coa', payload);
}

export function getOpeningBalances(params) {
  return api.get('/api/akuntansi/opening-balance', { params });
}

export function createOpeningBalance(payload) {
  return api.post('/api/akuntansi/opening-balance', payload);
}

export function updateOpeningBalance(id, payload) {
  return api.put(`/api/akuntansi/opening-balance/${id}`, payload);
}

export function deleteOpeningBalance(id) {
  return api.delete(`/api/akuntansi/opening-balance/${id}`);
}

export function postOpeningBalance(id) {
  return api.post(`/api/akuntansi/opening-balance/${id}/post`);
}

export function getManualJournalList(params) {
  return api.get('/api/akuntansi/get-jurnal-mal-list', { params });
}

export function getManualJournalDetail(id) {
  return api.get(`/api/akuntansi/get-jurnal-mal-detail/${id}`);
}

export function getFiturMalList() {
  return api.get('/api/akuntansi/get-fitur-mal-list');
}

export function getManualJournalSourceModules() {
  return api.get('/api/akuntansi/get-source-modul-use-jurnal-setting');
}

export function getJournalTriggerHealth(params) {
  return api.get('/api/akuntansi/get-jurnal-trigger-health', { params });
}

export function createManualJournal(payload) {
  return api.post('/api/akuntansi/insert-jurnal-mal', payload);
}

export function updateManualJournal(payload) {
  return api.put('/api/akuntansi/update-jurnal-mal', payload);
}

export function getCashierReports(params) {
  return api.get('/api/akuntansi/list-laporan-kasir', { params });
}

export function getCashierReportDetail(params) {
  return api.get('/api/akuntansi/get-detail-laporan-kasir', { params });
}

export function getCashierExpenses(params) {
  return api.get('/api/akuntansi/get-list-pengeluaran-kasir', { params });
}

export function getCashierExpenseDetail(id) {
  return api.get('/api/akuntansi/get-konfirmasi-pengeluaran', { params: { id_pengeluaran: id } });
}

export function createCashierExpense(payload) {
  return api.post('/api/akuntansi/add-pengeluaran-kasir', payload);
}

export function confirmCashierExpense(payload) {
  return api.post('/api/akuntansi/konfirmasi-pengeluaran', payload);
}

export function getAccountingTransactions(params) {
  return api.get('/api/akuntansi/get-list-transaksi', { params });
}

export function createAccountingTransaction(payload) {
  return api.post('/api/akuntansi/insert-transaksi', payload);
}

export function updateAccountingTransaction(payload) {
  return api.put('/api/akuntansi/update-transaksi', payload);
}

export function getCompanyBankAccounts(params) {
  return api.get('/api/base/rekening_perusahaan/all', { params });
}

export function createCompanyBankAccount(payload) {
  return api.post('/api/base/rekening_perusahaan', toFormPayload(payload), baseFormRequestConfig());
}

export function updateCompanyBankAccount(id, payload) {
  return api.put(
    '/api/base/rekening_perusahaan',
    toFormPayload(payload),
    baseFormRequestConfig({
      where: JSON.stringify({
        id_rekening_perusahaan: `=${Number(id)}`
      })
    })
  );
}

export function deleteCompanyBankAccount(id) {
  return api.delete('/api/base/rekening_perusahaan', {
    params: {
      where: JSON.stringify({
        id_rekening_perusahaan: `=${Number(id)}`
      })
    }
  });
}

export function getCreditNoteList(params) {
  return api.get('/api/akuntansi/get-list-credit-note', { params });
}

export function getCreditNoteCandidates(params) {
  return api.get('/api/akuntansi/credit-note-candidates', { params });
}

export function issueCreditNoteFromQcReturn(idRequest, payload) {
  return api.post(`/api/akuntansi/credit-note-candidates/${idRequest}/issue`, payload);
}

export function getCreditNoteDetail(id) {
  return api.get(`/api/akuntansi/get-detail-credit-note/${id}`);
}

export function refundCreditNote(id, payload) {
  return api.post(`/api/akuntansi/refund-credit-note/${id}`, payload);
}

export function getBankMutations(params) {
  return api.get('/api/akuntansi/get-list-mutasi-bank', { params });
}

export function getBankMutationDetail(id) {
  return api.get(`/api/akuntansi/get-detail-mutasi-bank/${id}`);
}

export function importBankMutations(payload) {
  return api.post('/api/akuntansi/insert-mutasi', payload);
}

export function createBankMutation(payload) {
  return api.post('/api/akuntansi/create-mutasi-bank', payload);
}

export function updateBankMutation(id, payload) {
  return api.put(`/api/akuntansi/update-mutasi-bank/${id}`, payload);
}

export function deleteBankMutation(id) {
  return api.delete(`/api/akuntansi/delete-mutasi-bank/${id}`);
}

export function getLphList(params) {
  return api.get('/api/akuntansi/get-lph', { params });
}

export function getLphDetail(params) {
  return api.get('/api/akuntansi/get-detail-lph', { params });
}

export function getLphCreateCandidates(params, requestConfig = {}) {
  // Candidate LPH may legitimately need longer than ordinary list requests on
  // a branch with a substantial invoice history.  Keep the broader API client
  // timeout conservative, but give this one scoped read operation enough time
  // to complete while the server-side query is being optimized.
  return api.get('/api/akuntansi/get-add-lph', {
    ...requestConfig,
    params,
    timeout: requestConfig.timeout ?? 120000
  });
}

export function createLph(payload) {
  return api.post('/api/akuntansi/add-lph', payload);
}

export function updateLph(payload) {
  return api.put('/api/akuntansi/update-lph', payload);
}

export function deleteLph(payload) {
  return api.delete('/api/akuntansi/delete-lph', { data: payload });
}

export function reprintLph(payload) {
  return api.post('/api/akuntansi/cetak-ulang-lph', payload);
}
