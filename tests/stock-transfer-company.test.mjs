import assert from 'node:assert/strict';
import test from 'node:test';
import { principalBelongsToTransferCompany, transferCompanyIds, transferCompanyLabel } from '../src/modules/stock-transfer/companyScope.js';

test('BMM transfer at a shared TMP warehouse keeps its selected company in labels and filters', () => {
  const row = { id_perusahaan: 1, id_perusahaan_awal: 2, id_perusahaan_tujuan: 2,
    nama_perusahaan_awal: 'BMM', nama_perusahaan_tujuan: 'BMM', nama_perusahaan: 'TMP' };
  assert.equal(transferCompanyLabel(row), 'BMM');
  assert.deepEqual(transferCompanyIds(row), ['2']);
});

test('cross-company transfer shows and filters both endpoints', () => {
  const row = { id_perusahaan_awal: 2, id_perusahaan_tujuan: 1,
    nama_perusahaan_awal: 'BMM', nama_perusahaan_tujuan: 'TMP' };
  assert.equal(transferCompanyLabel(row), 'BMM → TMP');
  assert.deepEqual(transferCompanyIds(row), ['2', '1']);
});

test('older company response aliases remain readable', () => {
  assert.equal(transferCompanyLabel({ nama_perusahaan_transfer: 'BMM' }), 'BMM');
  assert.deepEqual(transferCompanyIds({ id_perusahaan: 2 }), ['2']);
  assert.equal(transferCompanyLabel({}), '-');
});

test('source company limits principal choices and rejects stale selections', () => {
  assert.equal(principalBelongsToTransferCompany({ id_perusahaan: 2 }, '2'), true);
  assert.equal(principalBelongsToTransferCompany({ id_perusahaan: 1 }, '2'), false);
  assert.equal(principalBelongsToTransferCompany({ id_perusahaan: 2 }, ''), false);
  assert.equal(principalBelongsToTransferCompany({}, '2'), false);
});
