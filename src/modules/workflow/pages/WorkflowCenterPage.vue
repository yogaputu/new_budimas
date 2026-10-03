<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  getPurchaseBillingQueue,
  getPurchaseConfirmationQueue,
  getPurchaseOrderConfirmationQueue,
  getPurchasePayables,
  getPurchaseReadyOrders
} from '@/api/purchase';
import { getSalesOrderList, getSalesReturList } from '@/api/salesOrder';
import { getDepositGroups, getJournalList } from '@/api/finance';
import { getStockOpnameList } from '@/api/stockOpname';
import { getStockTransfers } from '@/api/stockTransfer';
import { getSupervisorAuditLogs } from '@/api/supervisorAudit';
import { normalizeError, normalizeList, unwrapResponse } from '@/utils/api';
import AppModal from '@/shared/components/AppModal.vue';
import AppTable from '@/shared/components/AppTable.vue';
import { useAuthStore } from '@/stores/auth';
import { canAccessRoleGroups, isCurrentUserPic } from '@/utils/roleAccess';

const router = useRouter();
const authStore = useAuthStore();

const today = new Date();
const filters = reactive({
  department: '',
  status: '',
  priority: '',
  search: ''
});

const selectedTaskId = ref('');
const detailOpen = ref(false);
const loading = ref(false);
const pageError = ref('');
const lastSync = ref('');
const taskItems = ref([]);
const exceptionItems = ref([]);
const auditLogItems = ref([]);

const departmentOptions = [
  { value: '', label: 'Semua Department' },
  { value: 'Finance', label: 'Finance' },
  { value: 'Sales', label: 'Sales' },
  { value: 'Warehouse', label: 'Warehouse' },
  { value: 'Purchasing', label: 'Purchasing' },
  { value: 'HRD', label: 'HRD' }
];

const statusOptions = [
  { value: '', label: 'Semua Status' },
  { value: 'Draft', label: 'Draft' },
  { value: 'Submitted', label: 'Submitted' },
  { value: 'Waiting Approval', label: 'Waiting Approval' },
  { value: 'In Review', label: 'In Review' },
  { value: 'Blocked', label: 'Blocked' },
  { value: 'Done', label: 'Done' }
];

const priorityOptions = [
  { value: '', label: 'Semua Prioritas' },
  { value: 'High', label: 'High' },
  { value: 'Medium', label: 'Medium' },
  { value: 'Low', label: 'Low' }
];

const accessMap = {
  Finance: { permissions: ['finance.recap.view', 'finance.payments.view', 'finance.receivables.view'], roles: ['finance'] },
  Purchasing: { permissions: ['purchase.orders.view', 'purchase.confirmations.approve'], roles: ['purchase'] },
  Sales: { permissions: ['supervisor-sales.dashboard.view', 'distribution.orders.view'], roles: ['salesSupervisor'] },
  Warehouse: { permissions: ['stock-transfer.view', 'stock-opname.view'], roles: ['warehouse'] },
  HRD: { permissions: ['master.users.view', 'dashboard.view'], roles: ['adminIt'] }
};

function addDays(days, baseDate = today) {
  const date = new Date(baseDate);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function normalizeRows(response) {
  return normalizeList(unwrapResponse(response));
}

function pick(row, keys, fallback = '') {
  const source = row || {};
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== '') {
      return value;
    }
  }
  return fallback;
}

function cleanText(value, fallback = '-') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function toNumber(value) {
  const parsed = Number(String(value ?? 0).replace(/[^\d.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value) {
  return new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(toNumber(value));
}

function rowCode(row, prefix, index) {
  return cleanText(
    pick(row, [
      'kode',
      'kode_order',
      'kode_po',
      'kode_transaksi',
      'kode_dokumen',
      'no_tagihan',
      'no_transaksi',
      'no_purchase_order',
      'kode_jurnal',
      'id_jurnal',
      'id',
      'id_purchase_order',
      'id_transaksi',
      'id_stock_opname'
    ], `${prefix}-${index + 1}`)
  );
}

function rowDate(row) {
  return pick(row, [
    'tanggal',
    'tanggal_input',
    'tanggal_po',
    'tanggal_order',
    'tanggal_transaksi',
    'tanggal_opname',
    'created_at',
    'createdAt'
  ], today.toISOString().slice(0, 10));
}

function deadline(row, plusDays = 1) {
  const parsed = new Date(rowDate(row));
  return Number.isNaN(parsed.getTime()) ? addDays(plusDays) : addDays(plusDays, parsed);
}

function branchName(row) {
  return cleanText(pick(row, ['nama_cabang', 'cabang_nama', 'cabang', 'branch', 'branch_name'], authStore.branchName || '-'));
}

function picName(row, fallback) {
  return cleanText(
    pick(row, [
      'pic',
      'nama_pic',
      'pic_name',
      'penanggung_jawab',
      'nama_pj',
      'nama_kasir',
      'created_by',
      'user_name',
      'nama_user'
    ], fallback)
  );
}

function requesterName(row, fallback) {
  return cleanText(pick(row, ['requester', 'nama_requester', 'created_by', 'nama_user', 'user_name'], fallback));
}

function statusText(row) {
  return cleanText(pick(row, ['status', 'status_bayar', 'status_so', 'tahap_setoran', 'status_penerimaan', 'status_konfirmasi'], 'submitted')).toLowerCase();
}

function normalizeStatus(row, fallback = 'Submitted') {
  const value = statusText(row);
  if (value.includes('done') || value.includes('selesai') || value.includes('final') || value.includes('lunas') || value.includes('closed')) return 'Done';
  if (value.includes('reject') || value.includes('tolak') || value.includes('blocked') || value.includes('eskalasi')) return 'Blocked';
  if (value.includes('approve') || value.includes('approval') || value.includes('menunggu')) return 'Waiting Approval';
  if (value.includes('review') || value.includes('proses') || value.includes('kasir') || value.includes('belum lunas')) return 'In Review';
  if (value.includes('draft')) return 'Draft';
  return fallback;
}

function priorityFromDeadline(dateValue, fallback = 'Medium') {
  const days = daysUntil(dateValue);
  if (days < 0) return 'High';
  if (days <= 1) return fallback;
  return 'Low';
}

function clampProgress(value) {
  return Math.max(5, Math.min(100, Number(value) || 35));
}

function taskFrom(partial) {
  return {
    id: partial.id,
    department: partial.department,
    module: partial.module,
    process: partial.process,
    sourceCode: partial.sourceCode,
    sourcePath: partial.sourcePath,
    status: partial.status || 'Submitted',
    priority: partial.priority || priorityFromDeadline(partial.deadline),
    approvalLevel: partial.approvalLevel || '-',
    requester: partial.requester || '-',
    pic: partial.pic || '-',
    deadline: partial.deadline || addDays(1),
    progress: clampProgress(partial.progress),
    branch: partial.branch || authStore.branchName || '-',
    audit: partial.audit || [],
    resource: partial.resource || 'dashboard',
    raw: partial.raw || null
  };
}

function baseAudit(row, action, note) {
  return [
    {
      at: rowDate(row),
      user: requesterName(row, 'System'),
      action,
      note
    }
  ];
}

function fallbackTasks() {
  return [
    taskFrom({
      id: 'WF-HRD-CHECK',
      department: 'HRD',
      module: 'HRD',
      process: 'Checkpoint approval karyawan dan administrasi internal',
      sourceCode: 'HRD-CHECK',
      sourcePath: '/workflow/tasks',
      status: 'Submitted',
      priority: 'Low',
      approvalLevel: 'HRD Officer',
      requester: 'System',
      pic: 'HRD',
      deadline: addDays(3),
      progress: 20,
      resource: 'dashboard',
      audit: [{ at: addDays(0), user: 'System', action: 'Sync', note: 'Task HRD tersedia sebagai placeholder sampai endpoint HRD aktif.' }]
    })
  ];
}

function buildPurchaseTasks(rows, type) {
  return rows.slice(0, 12).map((row, index) => {
    const code = rowCode(row, type, index);
    const map = {
      poApproval: {
        module: 'Purchase Order',
        process: `Approval Purchase Order ${code}`,
        sourcePath: '/purchase/order-confirmations',
        approvalLevel: 'Supervisor Purchase',
        pic: 'Kepala Purchase',
        deadlineDays: 1,
        progress: 55
      },
      receiptReady: {
        module: 'Penerimaan Barang',
        process: `Order siap terima ${code}`,
        sourcePath: '/purchase/receipts/create',
        approvalLevel: 'Warehouse Receipt',
        pic: 'Gudang Penerimaan',
        deadlineDays: 2,
        progress: 45
      },
      receiptApproval: {
        module: 'Finalisasi Purchase Order',
        process: `Review penerimaan ${code}`,
        sourcePath: '/purchase/confirmations',
        approvalLevel: 'Admin Purchase',
        pic: 'Purchase',
        deadlineDays: 1,
        progress: 65
      },
      billing: {
        module: 'Tagihan Purchase Order',
        process: `Proses tagihan ${code}`,
        sourcePath: '/purchase/bills',
        approvalLevel: 'Finance AP',
        pic: 'Finance AP',
        deadlineDays: 2,
        progress: 70
      }
    }[type];

    const taskDeadline = deadline(row, map.deadlineDays);
    return taskFrom({
      id: `WF-PUR-${type}-${code}`,
      department: type === 'billing' ? 'Finance' : 'Purchasing',
      module: map.module,
      process: map.process,
      sourceCode: code,
      sourcePath: map.sourcePath,
      status: normalizeStatus(row, type === 'receiptReady' ? 'Submitted' : 'Waiting Approval'),
      priority: priorityFromDeadline(taskDeadline, type === 'billing' ? 'High' : 'Medium'),
      approvalLevel: map.approvalLevel,
      requester: requesterName(row, 'Purchase'),
      pic: picName(row, map.pic),
      deadline: taskDeadline,
      progress: map.progress,
      branch: branchName(row),
      resource: type === 'billing' ? 'finance.recap' : 'distribution.orders',
      raw: row,
      audit: baseAudit(row, 'Sync Purchase', map.process)
    });
  });
}

function buildPayableTasks(rows) {
  return rows.slice(0, 10).map((row, index) => {
    const code = rowCode(row, 'PAY', index);
    const dueDate = pick(row, ['jatuh_tempo', 'tanggal_jatuh_tempo', 'due_date'], deadline(row, 0));
    return taskFrom({
      id: `WF-FIN-PAY-${code}`,
      department: 'Finance',
      module: 'Pembayaran Purchase',
      process: `Tagihan ${code} ${money(pick(row, ['total_tagihan', 'nominal', 'sisa_tagihan', 'total'], 0))}`,
      sourceCode: code,
      sourcePath: '/purchase/bills',
      status: normalizeStatus(row, 'In Review'),
      priority: priorityFromDeadline(dueDate, 'High'),
      approvalLevel: 'Finance AP',
      requester: requesterName(row, 'Purchase'),
      pic: picName(row, 'Finance AP'),
      deadline: dueDate,
      progress: 75,
      branch: branchName(row),
      resource: 'finance.payments',
      raw: row,
      audit: baseAudit(row, 'Sync Finance', 'Tagihan purchase masuk monitoring pembayaran.')
    });
  });
}

function buildSalesTasks(orderRows, returRows) {
  const orderTasks = orderRows.slice(0, 8).map((row, index) => {
    const code = rowCode(row, 'SO', index);
    const taskDeadline = deadline(row, 1);
    return taskFrom({
      id: `WF-SLS-ORDER-${code}`,
      department: 'Sales',
      module: 'Sales Order',
      process: `Monitoring sales order ${code}`,
      sourceCode: code,
      sourcePath: '/sales-order',
      status: normalizeStatus(row, 'In Review'),
      priority: priorityFromDeadline(taskDeadline),
      approvalLevel: 'Sales Admin',
      requester: requesterName(row, 'Sales'),
      pic: picName(row, 'Sales Admin'),
      deadline: taskDeadline,
      progress: 55,
      branch: branchName(row),
      resource: 'distribution.orders',
      raw: row,
      audit: baseAudit(row, 'Sync Sales', 'Sales order masuk monitoring lintas modul.')
    });
  });

  const returTasks = returRows.slice(0, 8).map((row, index) => {
    const code = rowCode(row, 'RET', index);
    const taskDeadline = deadline(row, 1);
    return taskFrom({
      id: `WF-SLS-RET-${code}`,
      department: 'Sales',
      module: 'Ajukan Retur',
      process: `Approval retur ${code}`,
      sourceCode: code,
      sourcePath: '/sales-order/retur-tracking',
      status: normalizeStatus(row, 'Waiting Approval'),
      priority: priorityFromDeadline(taskDeadline),
      approvalLevel: 'Supervisor Sales',
      requester: requesterName(row, 'Sales'),
      pic: picName(row, 'Sales Supervisor'),
      deadline: taskDeadline,
      progress: 45,
      branch: branchName(row),
      resource: 'distribution.orders',
      raw: row,
      audit: baseAudit(row, 'Sync Retur', 'Retur sales masuk antrean approval.')
    });
  });

  return [...orderTasks, ...returTasks];
}

function buildFinanceTasks(cashRows, nonCashRows, journalRows) {
  const depositTasks = [...cashRows, ...nonCashRows].slice(0, 12).map((row, index) => {
    const code = rowCode(row, 'DEP', index);
    const taskDeadline = deadline(row, 1);
    const isFinal = statusText(row).includes('final') || statusText(row).includes('selesai');
    return taskFrom({
      id: `WF-FIN-DEP-${code}`,
      department: 'Finance',
      module: 'Setoran',
      process: `Finalisasi setoran ${code}`,
      sourceCode: code,
      sourcePath: '/finance/deposit-finalization',
      status: isFinal ? 'Done' : normalizeStatus(row, 'In Review'),
      priority: isFinal ? 'Low' : priorityFromDeadline(taskDeadline, 'High'),
      approvalLevel: 'Finance Lead',
      requester: requesterName(row, 'Kasir'),
      pic: picName(row, 'Finance AR'),
      deadline: taskDeadline,
      progress: isFinal ? 100 : 70,
      branch: branchName(row),
      resource: 'finance.recap',
      raw: row,
      audit: baseAudit(row, 'Sync Setoran', 'Setoran masuk monitoring finalisasi.')
    });
  });

  const journalTasks = journalRows
    .filter((row) => Math.abs(toNumber(pick(row, ['total_debit', 'debit'], 0)) - toNumber(pick(row, ['total_kredit', 'kredit'], 0))) > 0)
    .slice(0, 8)
    .map((row, index) => {
      const code = rowCode(row, 'JRL', index);
      return taskFrom({
        id: `WF-FIN-JRL-${code}`,
        department: 'Finance',
        module: 'Jurnal',
        process: `Jurnal tidak balance ${code}`,
        sourceCode: code,
        sourcePath: '/finance/journal',
        status: 'Blocked',
        priority: 'High',
        approvalLevel: 'Accounting Lead',
        requester: requesterName(row, 'System'),
        pic: 'Accounting',
        deadline: deadline(row, 0),
        progress: 30,
        branch: branchName(row),
        resource: 'finance.recap',
        raw: row,
        audit: baseAudit(row, 'Exception', 'Debit dan kredit jurnal tidak sama.')
      });
    });

  return [...depositTasks, ...journalTasks];
}

function buildWarehouseTasks(stockRows, transferRows) {
  const stockTasks = stockRows.slice(0, 12).map((row, index) => {
    const code = rowCode(row, 'SO-STK', index);
    const taskDeadline = deadline(row, 1);
    const difference = Math.abs(toNumber(pick(row, ['selisih_nilai', 'nilai_selisih', 'total_selisih'], 0)));
    return taskFrom({
      id: `WF-WHS-OPN-${code}`,
      department: 'Warehouse',
      module: 'Stok Opname',
      process: `Review stok opname ${code}`,
      sourceCode: code,
      sourcePath: '/stock-opname',
      status: difference > 1000000 ? 'Blocked' : normalizeStatus(row, 'In Review'),
      priority: difference > 1000000 ? 'High' : priorityFromDeadline(taskDeadline),
      approvalLevel: 'Kepala Gudang',
      requester: requesterName(row, 'Warehouse'),
      pic: picName(row, 'Warehouse Supervisor'),
      deadline: taskDeadline,
      progress: normalizeStatus(row) === 'Done' ? 100 : 60,
      branch: branchName(row),
      resource: 'stock-opname',
      raw: row,
      audit: baseAudit(row, 'Sync Stok Opname', 'Dokumen stok opname masuk monitoring operasional.')
    });
  });

  const transferTasks = transferRows.slice(0, 8).map((row, index) => {
    const code = rowCode(row, 'TRF', index);
    const taskDeadline = deadline(row, 2);
    return taskFrom({
      id: `WF-WHS-TRF-${code}`,
      department: 'Warehouse',
      module: 'Stok Transfer',
      process: `Konfirmasi transfer ${code}`,
      sourceCode: code,
      sourcePath: '/stock-transfer/receipts',
      status: normalizeStatus(row, 'In Review'),
      priority: priorityFromDeadline(taskDeadline),
      approvalLevel: 'Kepala Gudang',
      requester: requesterName(row, 'Gudang Pengirim'),
      pic: picName(row, 'Checker Gudang'),
      deadline: taskDeadline,
      progress: 55,
      branch: branchName(row),
      resource: 'stock-transfer',
      raw: row,
      audit: baseAudit(row, 'Sync Stok Transfer', 'Transfer barang masuk monitoring penerimaan.')
    });
  });

  return [...stockTasks, ...transferTasks];
}

function buildExceptions({ readyRows, billingRows, payableRows, cashRows, nonCashRows, journalRows, stockRows }) {
  const rows = [];
  const readyWithBill = readyRows.filter((row) =>
    pick(row, ['no_tagihan', 'id_tagihan', 'tanggal_tagihan', 'status_tagihan'], '')
  );
  const billedCodes = new Set(
    [...billingRows, ...payableRows]
      .map((row, index) => rowCode(row, 'BILL', index))
      .filter(Boolean)
  );

  readyWithBill.slice(0, 5).forEach((row, index) => {
    rows.push({
      id: `EX-PO-RECEIPT-${index}`,
      type: 'PO sudah ditagihkan',
      module: 'Purchasing',
      document: rowCode(row, 'PO', index),
      severity: 'High',
      note: 'Dokumen masih muncul di daftar siap terima walau sudah punya tagihan.',
      sourcePath: '/purchase/receipts/create'
    });
  });

  journalRows
    .filter((row) => Math.abs(toNumber(pick(row, ['total_debit', 'debit'], 0)) - toNumber(pick(row, ['total_kredit', 'kredit'], 0))) > 0)
    .slice(0, 5)
    .forEach((row, index) => {
      rows.push({
        id: `EX-JOURNAL-${index}`,
        type: 'Jurnal tidak balance',
        module: 'Finance',
        document: rowCode(row, 'JRL', index),
        severity: 'High',
        note: `Selisih ${money(toNumber(pick(row, ['total_debit', 'debit'], 0)) - toNumber(pick(row, ['total_kredit', 'kredit'], 0)))}`,
        sourcePath: '/finance/journal'
      });
    });

  payableRows
    .filter((row) => normalizeStatus(row, 'In Review') !== 'Done' && daysUntil(pick(row, ['jatuh_tempo', 'tanggal_jatuh_tempo', 'due_date'], addDays(0))) < 0)
    .slice(0, 5)
    .forEach((row, index) => {
      rows.push({
        id: `EX-PAYABLE-${index}`,
        type: 'Tagihan lewat jatuh tempo',
        module: 'Finance',
        document: rowCode(row, 'PAY', index),
        severity: 'High',
        note: cleanText(pick(row, ['principal', 'nama_principal', 'supplier'], 'Principal belum terisi')),
        sourcePath: '/purchase/bills'
      });
    });

  stockRows
    .filter((row) => Math.abs(toNumber(pick(row, ['selisih_nilai', 'nilai_selisih', 'total_selisih'], 0))) > 1000000)
    .slice(0, 5)
    .forEach((row, index) => {
      rows.push({
        id: `EX-STOCK-${index}`,
        type: 'Selisih stock besar',
        module: 'Warehouse',
        document: rowCode(row, 'STK', index),
        severity: 'Medium',
        note: money(pick(row, ['selisih_nilai', 'nilai_selisih', 'total_selisih'], 0)),
        sourcePath: '/stock-opname'
      });
    });

  [...cashRows, ...nonCashRows]
    .filter((row) => {
      const status = statusText(row);
      return !status.includes('final') && !status.includes('selesai') && !status.includes('done');
    })
    .slice(0, 5)
    .forEach((row, index) => {
      rows.push({
        id: `EX-DEPOSIT-${index}`,
        type: 'Setoran belum finalisasi',
        module: 'Finance',
        document: rowCode(row, 'DEP', index),
        severity: 'Medium',
        note: picName(row, 'Finance AR'),
        sourcePath: '/finance/deposit-finalization'
      });
    });

  if (!readyWithBill.length && billedCodes.size) {
    rows.push({
      id: 'EX-PO-RECEIPT-CLEAN',
      type: 'PO ditagihkan vs receipt',
      module: 'Purchasing',
      document: `${billedCodes.size} dokumen tagihan`,
      severity: 'Low',
      note: 'Tidak ada indikasi order bertagihan yang masih membawa flag siap terima dari response aktif.',
      sourcePath: '/purchase/receipts/create'
    });
  }

  return rows;
}

async function loadWorkflowData() {
  loading.value = true;
  pageError.value = '';

  const requestMap = {
    poApproval: getPurchaseOrderConfirmationQueue({ limit: 50 }),
    ready: getPurchaseReadyOrders({ limit: 50 }),
    receiptApproval: getPurchaseConfirmationQueue({ limit: 50 }),
    billing: getPurchaseBillingQueue({ limit: 50 }),
    payables: getPurchasePayables({ limit: 50 }),
    salesOrders: getSalesOrderList({ limit: 50 }),
    salesRetur: getSalesReturList({ limit: 50 }),
    cashDeposits: getDepositGroups('cash', { limit: 50 }),
    nonCashDeposits: getDepositGroups('noncash', { limit: 50 }),
    journals: getJournalList({ limit: 50 }),
    stockOpname: getStockOpnameList({ limit: 50 }),
    transfers: getStockTransfers({ limit: 50 }),
    audits: getSupervisorAuditLogs({ limit: 50 })
  };

  const entries = Object.entries(requestMap);
  const settled = await Promise.allSettled(entries.map(([, promise]) => promise));
  const data = {};
  const errors = [];

  settled.forEach((result, index) => {
    const key = entries[index][0];
    if (result.status === 'fulfilled') {
      data[key] = normalizeRows(result.value);
    } else {
      data[key] = [];
      errors.push(`${key}: ${normalizeError(result.reason)}`);
    }
  });

  const rows = {
    poApprovalRows: data.poApproval || [],
    readyRows: data.ready || [],
    receiptApprovalRows: data.receiptApproval || [],
    billingRows: data.billing || [],
    payableRows: data.payables || [],
    salesOrderRows: data.salesOrders || [],
    salesReturRows: data.salesRetur || [],
    cashRows: data.cashDeposits || [],
    nonCashRows: data.nonCashDeposits || [],
    journalRows: data.journals || [],
    stockRows: data.stockOpname || [],
    transferRows: data.transfers || []
  };

  auditLogItems.value = (data.audits || []).slice(0, 30).map((row, index) => ({
    row_key: `AUD-${index}`,
    at: pick(row, ['created_at', 'tanggal', 'at'], ''),
    at_label: formatDate(pick(row, ['created_at', 'tanggal', 'at'], '')),
    user: cleanText(pick(row, ['user_name', 'nama_user', 'created_by', 'user'], '-')),
    action: cleanText(pick(row, ['action', 'aksi', 'event'], '-')),
    module: cleanText(pick(row, ['module', 'modul', 'source_module'], '-')),
    document: cleanText(pick(row, ['document_no', 'kode_dokumen', 'target_code', 'source_code'], '-')),
    note: cleanText(pick(row, ['note', 'catatan', 'description', 'keterangan'], '-'))
  }));

  const mappedTasks = [
    ...buildPurchaseTasks(rows.poApprovalRows, 'poApproval'),
    ...buildPurchaseTasks(rows.readyRows, 'receiptReady'),
    ...buildPurchaseTasks(rows.receiptApprovalRows, 'receiptApproval'),
    ...buildPurchaseTasks(rows.billingRows, 'billing'),
    ...buildPayableTasks(rows.payableRows),
    ...buildSalesTasks(rows.salesOrderRows, rows.salesReturRows),
    ...buildFinanceTasks(rows.cashRows, rows.nonCashRows, rows.journalRows),
    ...buildWarehouseTasks(rows.stockRows, rows.transferRows),
    ...fallbackTasks()
  ];

  taskItems.value = mappedTasks;
  exceptionItems.value = buildExceptions({
    readyRows: rows.readyRows,
    billingRows: rows.billingRows,
    payableRows: rows.payableRows,
    cashRows: rows.cashRows,
    nonCashRows: rows.nonCashRows,
    journalRows: rows.journalRows,
    stockRows: rows.stockRows
  });

  lastSync.value = new Intl.DateTimeFormat('id-ID', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date());

  if (errors.length && mappedTasks.length <= 1) {
    pageError.value = errors.slice(0, 2).join(' | ');
  }

  loading.value = false;
}

const selectedTask = computed(() => taskItems.value.find((task) => task.id === selectedTaskId.value) || null);

const filteredTasks = computed(() => {
  const query = filters.search.trim().toLowerCase();

  return taskItems.value.filter((task) => {
    const matchesDepartment = !filters.department || task.department === filters.department;
    const matchesStatus = !filters.status || task.status === filters.status;
    const matchesPriority = !filters.priority || task.priority === filters.priority;
    const matchesSearch =
      !query ||
      [task.id, task.department, task.module, task.process, task.sourceCode, task.pic, task.requester, task.branch]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));

    return matchesDepartment && matchesStatus && matchesPriority && matchesSearch;
  });
});

const tableRows = computed(() =>
  filteredTasks.value.map((task) => ({
    ...task,
    status_label: resolveStatus(task.status),
    priority_label: resolvePriority(task.priority),
    deadline_label: formatDeadline(task.deadline),
    sla_label: resolveSla(task),
    progress_label: `${task.progress}%`
  }))
);

const summaryCards = computed(() => {
  const active = taskItems.value.filter((task) => task.status !== 'Done');
  const overdue = active.filter((task) => isOverdue(task)).length;
  const waiting = active.filter((task) => task.status === 'Waiting Approval').length;
  const blocked = active.filter((task) => task.status === 'Blocked').length;
  const owned = active.filter((task) => String(task.pic || '').toLowerCase().includes(String(authStore.userName || '').toLowerCase())).length;

  return [
    { label: 'Task Aktif', value: String(active.length), accent: 'bg-slate-500', note: 'Belum selesai' },
    { label: 'Need Approval', value: String(waiting), accent: 'bg-amber-500', note: 'Menunggu approval' },
    { label: 'Overdue', value: String(overdue), accent: 'bg-rose-500', note: 'Lewat deadline' },
    { label: 'Blocked', value: String(blocked), accent: 'bg-orange-500', note: 'Perlu eskalasi' },
    { label: 'PIC Saya', value: String(owned), accent: 'bg-brand-500', note: authStore.userName || 'User aktif' }
  ];
});

const departmentRows = computed(() =>
  departmentOptions
    .filter((item) => item.value)
    .map((item) => {
      const rows = taskItems.value.filter((task) => task.department === item.value);
      const done = rows.filter((task) => task.status === 'Done').length;
      return {
        department: item.label,
        active: rows.length - done,
        approval: rows.filter((task) => task.status === 'Waiting Approval').length,
        overdue: rows.filter((task) => task.status !== 'Done' && isOverdue(task)).length,
        completion: rows.length ? `${Math.round((done / rows.length) * 100)}%` : '0%'
      };
    })
);

const selectedAuditRows = computed(() => {
  const task = selectedTask.value;
  if (!task) return [];
  const query = String(task.sourceCode || '').toLowerCase();
  const relatedAudit = auditLogItems.value.filter((item) => {
    const haystack = [item.module, item.document, item.note, item.action].join(' ').toLowerCase();
    return query && haystack.includes(query);
  });

  return [...(task.audit || []), ...relatedAudit].map((item, index) => ({
    ...item,
    row_key: `${task.id}-${index}`,
    at_label: item.at_label || formatDate(item.at)
  }));
});

const canTakeSelectedTask = computed(() => selectedTask.value && selectedTask.value.status !== 'Done' && canAccessDepartment(selectedTask.value));
const canApproveSelectedTask = computed(() => selectedTask.value && selectedTask.value.status !== 'Done' && canActOnTask(selectedTask.value));
const canEscalateSelectedTask = computed(() => selectedTask.value && selectedTask.value.status !== 'Done' && canActOnTask(selectedTask.value));
const actionHint = computed(() => {
  if (!selectedTask.value) return '';
  if (!canAccessDepartment(selectedTask.value)) {
    return `Role ${authStore.roleLabel || 'user'} tidak memiliki aksi untuk department ${selectedTask.value.department}.`;
  }
  if (!canActOnTask(selectedTask.value) && selectedTask.value.status !== 'Done') {
    return `Aksi hanya tampil untuk PIC ${selectedTask.value.pic || '-'} atau role terkait yang mengambil task.`;
  }
  return '';
});

function formatDate(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('id-ID', { day: '2-digit', month: 'short', year: 'numeric' }).format(parsed);
}

function formatDeadline(value) {
  return formatDate(value);
}

function daysUntil(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 0;
  const start = new Date(today.toISOString().slice(0, 10));
  return Math.ceil((date - start) / 86400000);
}

function isOverdue(task) {
  return task.status !== 'Done' && daysUntil(task.deadline) < 0;
}

function resolveSla(task) {
  if (task.status === 'Done') {
    return { text: 'Closed', className: 'inline-flex rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-700' };
  }
  const days = daysUntil(task.deadline);
  if (days < 0) {
    return { text: `Overdue ${Math.abs(days)} hari`, className: 'inline-flex rounded-full bg-rose-100 px-3 py-1 text-xs font-semibold text-rose-700' };
  }
  if (days === 0) {
    return { text: 'Jatuh tempo hari ini', className: 'inline-flex rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-700' };
  }
  return { text: `${days} hari lagi`, className: 'inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600' };
}

function resolveStatus(value) {
  const map = {
    Draft: 'bg-slate-100 text-slate-600',
    Submitted: 'bg-sky-100 text-sky-700',
    'Waiting Approval': 'bg-amber-100 text-amber-700',
    'In Review': 'bg-brand-100 text-brand-700',
    Blocked: 'bg-rose-100 text-rose-700',
    Done: 'bg-emerald-100 text-emerald-700'
  };
  return {
    text: value || '-',
    className: `inline-flex rounded-full px-3 py-1 text-xs font-semibold ${map[value] || map.Draft}`
  };
}

function resolvePriority(value) {
  const map = {
    High: 'bg-rose-100 text-rose-700',
    Medium: 'bg-amber-100 text-amber-700',
    Low: 'bg-slate-100 text-slate-600'
  };
  return {
    text: value || '-',
    className: `inline-flex rounded-full px-3 py-1 text-xs font-semibold ${map[value] || map.Low}`
  };
}

function canAccessDepartment(task) {
  if (!task) return false;
  if (authStore.hasPermission?.('*')) return true;
  const access = accessMap[task.department] || { permissions: ['dashboard.view'], roles: [] };
  return canAccessRoleGroups(authStore, access.roles) || access.permissions.some((permission) => authStore.hasPermission?.(permission));
}

function isTaskPic(task) {
  return isCurrentUserPic(authStore, task, ['pic']);
}

function canActOnTask(task) {
  return Boolean(task && canAccessDepartment(task) && (isTaskPic(task) || String(task.pic || '-').trim() === '-' || authStore.hasPermission?.('*')));
}

function openDetail(task) {
  selectedTaskId.value = task.id;
  detailOpen.value = true;
}

function closeDetail() {
  detailOpen.value = false;
}

function appendAudit(task, action, note) {
  return [
    {
      at: new Date().toISOString().slice(0, 10),
      user: authStore.userName || 'User',
      action,
      note
    },
    ...(task.audit || [])
  ];
}

function updateSelectedTask(patch, action, note) {
  if (!selectedTask.value) return;
  taskItems.value = taskItems.value.map((task) =>
    task.id === selectedTask.value.id
      ? {
          ...task,
          ...patch,
          audit: appendAudit(task, action, note)
        }
      : task
  );
}

function takeTask() {
  updateSelectedTask(
    { pic: authStore.userName || 'User', status: 'In Review', progress: Math.max(selectedTask.value?.progress || 0, 50) },
    'Ambil PIC',
    'PIC diganti ke user aktif.'
  );
}

function approveTask() {
  updateSelectedTask(
    { status: 'Done', progress: 100 },
    'Approve',
    'Task disetujui dan ditutup dari Workflow Center.'
  );
}

function escalateTask() {
  updateSelectedTask(
    { priority: 'High', status: 'Blocked' },
    'Escalate',
    'Task dinaikkan ke prioritas tinggi.'
  );
}

function openSource(path = selectedTask.value?.sourcePath) {
  if (path) {
    router.push(path);
  }
}

function resetFilters() {
  filters.department = '';
  filters.status = '';
  filters.priority = '';
  filters.search = '';
}

onMounted(loadWorkflowData);
</script>

<template>
  <div class="space-y-6">
    <section class="panel overflow-hidden p-6">
      <div class="flex flex-wrap items-start justify-between gap-5">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.28em] text-brand-600">Budimas ERP</p>
          <h1 class="mt-2 text-2xl font-bold text-slate-900">Workflow Center</h1>
          <p class="mt-2 max-w-4xl text-sm leading-6 text-slate-500">
            Pusat task lintas Finance, Sales, Warehouse, Purchasing, dan HRD untuk status, approval, PIC, deadline, serta audit.
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            <span class="font-semibold text-slate-900">{{ tableRows.length }}</span> task tampil
            <span v-if="lastSync" class="ml-2 text-xs text-slate-400">{{ lastSync }}</span>
          </div>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50" :disabled="loading" @click="loadWorkflowData">
            {{ loading ? 'Memuat...' : 'Refresh' }}
          </button>
        </div>
      </div>
      <p v-if="pageError" class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">{{ pageError }}</p>
    </section>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
      <article v-for="card in summaryCards" :key="card.label" class="panel relative overflow-hidden p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.22em] text-slate-400">{{ card.label }}</p>
            <p class="mt-3 text-3xl font-bold text-slate-900">{{ card.value }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ card.note }}</p>
          </div>
          <span class="h-11 w-2 rounded-full" :class="card.accent"></span>
        </div>
      </article>
    </section>

    <section class="panel p-4">
      <div class="grid gap-3 lg:grid-cols-[minmax(260px,1fr)_190px_190px_190px_auto]">
        <input v-model="filters.search" type="text" placeholder="Cari task, modul, source, PIC, requester..." class="field h-[54px]" />
        <select v-model="filters.department" class="field h-[54px]">
          <option v-for="item in departmentOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select v-model="filters.status" class="field h-[54px]">
          <option v-for="item in statusOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <select v-model="filters.priority" class="field h-[54px]">
          <option v-for="item in priorityOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <button class="h-[54px] rounded-xl border border-slate-200 px-5 text-sm font-semibold text-slate-700 hover:bg-slate-50" @click="resetFilters">
          Reset
        </button>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div class="space-y-3">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h3 class="text-lg font-semibold text-slate-900">Task Lintas Modul</h3>
            <p class="text-sm text-slate-500">Status operasional dari modul aktif.</p>
          </div>
        </div>

        <AppTable
          :rows="tableRows"
          :columns="[
            { key: 'id', label: 'Workflow ID' },
            { key: 'department', label: 'Dept' },
            { key: 'module', label: 'Modul' },
            { key: 'process', label: 'Proses' },
            { key: 'status_label', label: 'Status' },
            { key: 'priority_label', label: 'Prioritas' },
            { key: 'pic', label: 'PIC' },
            { key: 'deadline_label', label: 'Deadline' },
            { key: 'sla_label', label: 'SLA' }
          ]"
          :clickable-rows="true"
          row-key="id"
          :selected-key="selectedTaskId"
          empty-message="Belum ada task yang sesuai filter."
          @row-click="openDetail"
        />
      </div>

      <div class="space-y-6">
        <section class="panel p-5">
          <div class="mb-4">
            <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Health per Department</p>
            <h3 class="mt-2 text-lg font-semibold text-slate-900">Ringkasan Workflow</h3>
          </div>

          <div class="space-y-3">
            <article v-for="row in departmentRows" :key="row.department" class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div class="flex items-center justify-between gap-3">
                <p class="text-sm font-semibold text-slate-900">{{ row.department }}</p>
                <span class="text-xs font-semibold text-slate-500">{{ row.completion }} done</span>
              </div>
              <div class="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-500">
                <span>Aktif: <b class="text-slate-900">{{ row.active }}</b></span>
                <span>Approval: <b class="text-slate-900">{{ row.approval }}</b></span>
                <span>Overdue: <b class="text-slate-900">{{ row.overdue }}</b></span>
              </div>
            </article>
          </div>
        </section>

        <section class="panel p-5">
          <div class="mb-4 flex items-center justify-between gap-3">
            <div>
              <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Exception</p>
              <h3 class="mt-2 text-lg font-semibold text-slate-900">Monitoring Exception</h3>
            </div>
            <span class="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-rose-700">{{ exceptionItems.length }}</span>
          </div>

          <div class="space-y-3">
            <button
              v-for="item in exceptionItems.slice(0, 8)"
              :key="item.id"
              class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left hover:border-brand-300"
              @click="openSource(item.sourcePath)"
            >
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-semibold text-slate-900">{{ item.type }}</p>
                  <p class="mt-1 text-xs text-slate-500">{{ item.module }} - {{ item.document }}</p>
                  <p class="mt-2 text-xs text-slate-500">{{ item.note }}</p>
                </div>
                <span :class="resolvePriority(item.severity).className">{{ item.severity }}</span>
              </div>
            </button>
          </div>
        </section>
      </div>
    </section>

    <section class="panel p-5">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Audit</p>
          <h3 class="mt-2 text-lg font-semibold text-slate-900">Audit Terbaru</h3>
        </div>
        <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{{ auditLogItems.length }} log</span>
      </div>
      <AppTable
        :rows="auditLogItems.slice(0, 10)"
        :columns="[
          { key: 'at_label', label: 'Tanggal' },
          { key: 'user', label: 'User' },
          { key: 'module', label: 'Modul' },
          { key: 'document', label: 'Dokumen' },
          { key: 'action', label: 'Action' },
          { key: 'note', label: 'Catatan' }
        ]"
        :paginated="false"
        row-key="row_key"
        empty-message="Audit trail belum tersedia dari API."
      />
    </section>

    <AppModal
      :open="detailOpen"
      :title="selectedTask?.id || 'Detail Workflow'"
      :description="selectedTask?.process || 'Status, approval, PIC, deadline, dan audit task.'"
      size="6xl"
      @close="closeDetail"
    >
      <div v-if="!selectedTask" class="rounded-2xl border border-dashed border-slate-200 px-4 py-8 text-sm text-slate-500">
        Task belum dipilih.
      </div>

      <div v-else class="space-y-5">
        <div class="flex flex-wrap gap-3">
          <button v-if="canTakeSelectedTask" class="rounded-xl bg-brand-600 px-4 py-3 text-sm font-medium text-white" @click="takeTask">
            Ambil PIC
          </button>
          <button v-if="canApproveSelectedTask" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-700" @click="approveTask">
            Approve / Done
          </button>
          <button v-if="canEscalateSelectedTask" class="rounded-xl border border-rose-200 px-4 py-3 text-sm font-medium text-rose-700" @click="escalateTask">
            Escalate
          </button>
          <button class="rounded-xl border border-slate-200 px-4 py-3 text-sm font-medium text-slate-700" @click="openSource()">
            Buka Source Modul
          </button>
          <p v-if="actionHint" class="rounded-xl bg-slate-50 px-4 py-3 text-sm text-slate-500">{{ actionHint }}</p>
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Status</p>
            <p class="mt-2"><span :class="resolveStatus(selectedTask.status).className">{{ resolveStatus(selectedTask.status).text }}</span></p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Priority</p>
            <p class="mt-2"><span :class="resolvePriority(selectedTask.priority).className">{{ resolvePriority(selectedTask.priority).text }}</span></p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Deadline</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ formatDeadline(selectedTask.deadline) }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">SLA</p>
            <p class="mt-2"><span :class="resolveSla(selectedTask).className">{{ resolveSla(selectedTask).text }}</span></p>
          </div>
        </div>

        <div class="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Department</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedTask.department }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Approval</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedTask.approvalLevel }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">PIC</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedTask.pic }}</p>
          </div>
          <div class="rounded-2xl border border-slate-200 px-4 py-3">
            <p class="text-[11px] font-semibold uppercase tracking-[0.25em] text-slate-400">Requester</p>
            <p class="mt-2 text-sm font-semibold text-slate-900">{{ selectedTask.requester }}</p>
          </div>
        </div>

        <div class="rounded-2xl border border-slate-200 px-4 py-4">
          <div class="mb-2 flex items-center justify-between gap-3">
            <p class="text-sm font-semibold text-slate-900">Progress</p>
            <p class="text-sm font-semibold text-slate-600">{{ selectedTask.progress }}%</p>
          </div>
          <div class="h-3 overflow-hidden rounded-full bg-slate-100">
            <div class="h-full rounded-full bg-brand-600" :style="{ width: `${selectedTask.progress}%` }"></div>
          </div>
        </div>

        <div>
          <p class="mb-3 text-xs font-semibold uppercase tracking-[0.25em] text-slate-400">Audit Trail</p>
          <AppTable
            :rows="selectedAuditRows"
            :columns="[
              { key: 'at_label', label: 'Tanggal' },
              { key: 'user', label: 'User' },
              { key: 'action', label: 'Action' },
              { key: 'note', label: 'Catatan' }
            ]"
            :paginated="false"
            row-key="row_key"
            empty-message="Belum ada audit trail."
          />
        </div>
      </div>
    </AppModal>
  </div>
</template>
