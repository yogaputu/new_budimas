import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveDashboardPanels } from '../src/modules/supervisor-sales/utils/dashboardPanels.js';

test('target failure preserves successful daily activity and calendar', async () => {
  const daily = { rows: [{ id_sales: 7 }] };
  const calendar = { rows: [{ tanggal: '2026-06-29' }] };
  const panels = resolveDashboardPanels(await Promise.allSettled([
    Promise.reject(new Error('target unavailable')),
    Promise.resolve(daily),
    Promise.resolve(calendar),
  ]));
  assert.deepEqual(panels.unavailable, ['targets']);
  assert.equal(panels.responses.targets, undefined);
  assert.equal(panels.responses.daily, daily);
  assert.equal(panels.responses.calendar, calendar);
});

test('empty successful responses remain valid panels', async () => {
  const panels = resolveDashboardPanels(await Promise.allSettled([
    Promise.resolve({ rows: [] }), Promise.resolve({ rows: [] }), Promise.resolve({ rows: [] }),
  ]));
  assert.deepEqual(panels.unavailable, []);
  assert.deepEqual(Object.keys(panels.responses), ['targets', 'daily', 'calendar']);
});

test('failure of every panel still reports the server error', async () => {
  const failure = new Error('server unavailable');
  const results = await Promise.allSettled([Promise.reject(failure), Promise.reject(failure), Promise.reject(failure)]);
  assert.throws(() => resolveDashboardPanels(results), failure);
});
