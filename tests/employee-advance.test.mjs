import test from 'node:test';
import assert from 'node:assert/strict';
import { canDecideEmployeeAdvance, validateEmployeeAdvance } from '../src/modules/finance/employeeAdvance.js';

const pending = { status: 'PENDING', created_by: 1, id_karyawan: 2 };
test('approval requires permission, known identities, pending status and a different actor', () => {
  assert.equal(canDecideEmployeeAdvance(pending, { id: 3 }, true), true);
  for (const id of [1, 2, undefined]) assert.equal(canDecideEmployeeAdvance(pending, { id }, true), false);
  assert.equal(canDecideEmployeeAdvance(pending, { id: 3 }, false), false);
  for (const row of [{ ...pending, status: 'APPROVED' }, { ...pending, created_by: null }, { ...pending, can_approve: false }]) {
    assert.equal(canDecideEmployeeAdvance(row, { id: 3 }, true), false);
  }
  assert.equal(canDecideEmployeeAdvance(pending, { user_id: '3' }, true), true);
});

const form = { id_perusahaan: '1', id_cabang: '2', id_karyawan: '3', tanggal_pengajuan: '2026-10-03', tanggal_jatuh_tempo: '', nominal: '100000.50', keperluan: 'Biaya keluarga' };
test('submission accepts a selected employee and rejects stale scope, invalid dates and invalid money', () => {
  assert.equal(validateEmployeeAdvance(form, [{ id: 3 }]), '');
  assert.ok(validateEmployeeAdvance(form, [{ id: 4 }]));
  for (const changes of [{ nominal: '-1' }, { nominal: '0' }, { nominal: '1.001' }, { nominal: '1e6' }, { nominal: '10000000000000' }, { tanggal_pengajuan: '2026-02-30' }, { tanggal_jatuh_tempo: '2026-10-02' }, { keperluan: '   ' }]) {
    assert.ok(validateEmployeeAdvance({ ...form, ...changes }, [{ id: 3 }]));
  }
});
