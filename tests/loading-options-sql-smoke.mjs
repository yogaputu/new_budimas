// Run explicitly: isolated PostgreSQL-compatible SQL checks, never a live DB.
import {PGlite} from '/tmp/budimas-lph-kasir-tests.gq65Vo/node_modules/@electric-sql/pglite/dist/index.js';
import {execFileSync} from 'node:child_process';
import assert from 'node:assert/strict';
const sql=JSON.parse(execFileSync('/Users/macairm2/www/API/venv/bin/python',['-c',"import runpy,json; m=runpy.run_path('/Users/macairm2/www/API/apps/lib/loading_options.py'); print(json.dumps({k:m[k] for k in ('VEHICLES_SQL','DRIVERS_SQL')}))"],{encoding:'utf8'}));
const db=new PGlite();
async function run(query,params) {
  const keys=[],values=[];
  return (await db.query(query.replace(/(?<!:):([a-zA-Z_]\w*)/g,(_,key)=>{if(!keys.includes(key)){keys.push(key);values.push(params[key]);}return `$${keys.indexOf(key)+1}`;}),values)).rows;
}
try {
await db.exec(`
CREATE TABLE perusahaan(id integer PRIMARY KEY,nama text);
CREATE TABLE cabang(id integer PRIMARY KEY,id_perusahaan integer,nama text);
CREATE TABLE armada(id integer PRIMARY KEY,kode text,nama text,no_pelat text,id_cabang integer,id_perusahaan integer,id_perusahaan_list text,status_operasional text,id_status integer);
CREATE TABLE users(id integer PRIMARY KEY,nama text,username text,id_cabang integer,id_cabang_list text,id_perusahaan integer,id_perusahaan_list text);
CREATE TABLE driver(id integer PRIMARY KEY,id_user integer);
INSERT INTO perusahaan VALUES(3,'P3'),(9,'P9'); INSERT INTO cabang VALUES(2,3,'C2'),(8,9,'C8');
INSERT INTO armada SELECT n,'A'||n,'Armada '||n,'B '||n,2,3,NULL,'AVAILABLE',1 FROM generate_series(1,305) n;
INSERT INTO users SELECT n,'Driver '||n,'driver'||n,2,NULL,3,NULL FROM generate_series(1,305) n;
INSERT INTO driver SELECT n,n FROM generate_series(1,305) n;
INSERT INTO armada VALUES(900,'SHARED','Shared','B SHARED',2,9,' 3 , 9 ','AVAILABLE',1),(901,'FOREIGN','Foreign','X',8,9,NULL,'AVAILABLE',1),(905,'OFF','Off','OFF',2,3,NULL,'MAINTENANCE',0);
INSERT INTO users VALUES(900,'Shared','shared',8,' 2 , 8 ',9,' 3 , 9 '),(901,'Foreign','foreign',8,NULL,9,NULL),(902,'Helper only','helper',2,NULL,3,NULL),(903,'Driver 1','duplicate',2,NULL,3,NULL);
INSERT INTO driver VALUES(900,900),(901,901),(903,903);
`);
const params={all_branches:false,branches:[2],all_companies:false,companies:[3]};
for (const query of Object.values(sql)) {
  const rows=await run(query,params);
  assert.equal(rows.length,307,'Complete master includes >200 unscheduled choices');
  assert.ok(rows.some(r=>r.id===305));assert.ok(rows.some(r=>r.id===900),'shared business scope included');
  assert.ok(!rows.some(r=>r.id===901),'foreign scope excluded');
  assert.equal(new Set(rows.map(r=>r.id)).size,rows.length,'no duplicate IDs');
  assert.equal((await run(query,{...params,all_branches:true,branches:[0],all_companies:true,companies:[0]})).length,308);
  assert.equal((await run(query,{...params,branches:[999]})).length,0);
  assert.equal((await run(query,{...params,companies:[999]})).length,0);
  assert.equal((await run(query,{...params,companies:[30]})).length,0,'shared scopes match whole IDs, not substrings');
  assert.equal((await run(query,{...params,branches:[8],companies:[9]})).length,query===sql.VEHICLES_SQL?1:2);
}
const drivers=await run(sql.DRIVERS_SQL,params);
assert.equal(drivers.filter(r=>r.nama==='Driver 1').length,2,'same names preserve different master IDs');
assert.ok(!drivers.some(r=>r.id===902),'users without driver master are excluded');
const vehicles=await run(sql.VEHICLES_SQL,params);
assert.equal(vehicles.find(r=>r.id===905).status_operasional,'MAINTENANCE','all master statuses visible; loading guards unchanged');
console.log('PASS: all 307 scoped master choices, no schedule dependency/caps, shared scopes, foreign scope denial, same-name IDs, inactive metadata.');
} finally {await db.close();}
