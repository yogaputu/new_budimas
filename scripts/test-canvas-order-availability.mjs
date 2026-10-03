// Run with node scripts/test-canvas-order-availability.mjs. No API or browser.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { parse, compileScript } from '@vue/compiler-sfc';
import { canvasPieces } from '../src/modules/sales-canvas/utils/canvasUom.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function loadDeclarations(filename, names, context) {
  const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename });
  const script = compileScript(descriptor, { id: 'canvas-regression' });
  const nodes = script.scriptSetupAst.filter((node) => {
    const name = node.type === 'FunctionDeclaration' ? node.id.name : node.declarations?.[0]?.id?.name;
    return names.includes(name);
  });
  assert.equal(nodes.length, names.length);
  const source = nodes.map((node) => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n');
  vm.createContext(context);
  vm.runInContext(`${source}\nthis.subject = {${names.join(',')}}`, context);
  return context.subject;
}

const web = loadDeclarations(path.join(root, 'src/modules/sales-canvas/pages/CanvasOrdersPage.vue'),
  ['orderItemAvailablePieces'], { canvasPieces });
assert.equal(web.orderItemAvailablePieces({ stock_canvas: 16, available_order_qty_pcs: 8 }), 8);
assert.equal(web.orderItemAvailablePieces({ stock_canvas: 16, available_order_qty_pcs: 0 }), 0);
assert.equal(web.orderItemAvailablePieces({ stock_canvas: 16, request_qty_uom1: 20 }), 16);

const calls = [];
const ref = (value) => ({ value });
const item = { id: 2, nama_produk: 'P1 - Produk 2', stock_canvas: 30, available_order_qty_pcs: 16, qty_uom1: 16 };
const state = {
  mode: ref('order'), loading: ref(false), selectedCanvasRequestId: ref('91'),
  approvedCanvasRequests: ref([]), canvasProductsRequestSequence: 0,
  canvasScopeParams: ref({ id_sales: 33, id_principal: 11 }), items: ref([]),
  draft: ref({}), selectedCanvasVoucherIds: ref({ 2: '', 3: '' }),
  customerId: ref('7'), customerName: ref('Toko'), customerCode: ref('C7'),
  selectedItems: ref([item]), selectedCount: ref(1), selectedCanvasOrder: ref(null),
  paymentAmount: ref(0), selectedOrderRemaining: ref(0),
  selectedCanvasVoucherQuoteReason: ref(''),
  getCanvasArray: (payload) => payload.pages, normalizeRows: (payload) => payload.pages,
  ensureDraft: () => {}, applyCarriedStockSummary: () => {},
  getDraftPieces: () => state.enteredPieces,
  enteredPieces: 15,
  buildCanvasVoucherSelections: () => [],
  buildCanvasVoucherItems: () => [{ id_produk: 2, qty_uom1: state.enteredPieces }],
  loadEligibleCanvasVouchers: async () => true, assertCanvasSuccess: (payload) => payload,
  formatNumber: String, computed: (getter) => ({ get value() { return getter(); } }),
  Swal: { fire: async (...args) => calls.push(['warning', ...args]) }, console,
  api: {
    get: async (url, options) => {
      calls.push(['get', url, options]);
      return { data: { pages: url.endsWith('all-canvas-request')
        ? [{ id: 91, available_qty_pcs: 16 }, { id: 92, available_qty_pcs: 8 }] : [item] } };
    },
    post: async (url, payload) => { calls.push(['post', url, payload]); return { data: { status: 'success' } }; }
  }
};
const mobile = loadDeclarations(path.resolve(root, '../budimas-mobile/src/views/SalesCanvas.vue'),
  ['getStock', 'canSubmit', 'fetchProducts', 'selectCanvasRequest', 'submitOrder'], state);

await mobile.fetchProducts();
assert.equal(state.selectedCanvasRequestId.value, '91');
assert.equal(state.items.value[0].qty_uom1, 0, 'A displayed approval must not prefill an order');
assert.equal(mobile.getStock(item), 16, 'Order stock badge uses approval availability, not total physical stock');
const detailCall = calls.find((call) => call[1]?.endsWith('detail-canvas-request'));
assert.equal(detailCall[2].params.id_canvas, 91);
assert.equal(detailCall[2].params.eligible_only, 1);
assert.equal(detailCall[2].params.tanggal_request, undefined, 'Prior-date approved requests remain orderable');
assert.equal(mobile.canSubmit.value, true);
await mobile.submitOrder();
assert.equal(calls.find((call) => call[0] === 'post')[2].id_canvas_request, 91);

state.enteredPieces = 17;
assert.equal(mobile.canSubmit.value, false);
assert.equal(await mobile.submitOrder(), false);
assert.equal(calls.filter((call) => call[0] === 'post').length, 1);

state.draft.value = { 2: { qty_uom1: 15 } };
await mobile.selectCanvasRequest('92');
assert.equal(state.selectedCanvasRequestId.value, '92');
assert.equal(Object.keys(state.draft.value).length, 0);
assert.equal(calls.filter((call) => call[1]?.endsWith('detail-canvas-request')).at(-1)[2].params.id_canvas, 92);

state.mode.value = 'return';
assert.equal(mobile.getStock(item), 30, 'Returns continue to show physical Canvas stock');
console.log('PASS Canvas web/mobile availability, selected request, mixed stock scope and over-order guards');
