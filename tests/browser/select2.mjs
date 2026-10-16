// All browser requests stay local. These fixtures never connect to ERP APIs.
import assert from 'node:assert/strict';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.TEST_BASE_URL || 'http://127.0.0.1:5176';
assert.ok(['localhost','127.0.0.1'].includes(new URL(origin).hostname));
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, headless: true });
let checks=0;
try {
  for (const theme of ['light','dark']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 1000 }, hasTouch: true });
    await context.addInitScript(theme => localStorage.setItem('budimas-theme',theme),theme);
    await context.route('**/*',route => {
      const url=new URL(route.request().url());
      return url.origin===origin && !url.pathname.startsWith('/api/') ? route.continue() : route.abort();
    });
    const page=await context.newPage(),errors=[];
    page.on('pageerror', e=>errors.push(e.message));
    await page.goto(origin+'/tests/browser/fixtures/select2.html');
    const state=async()=>JSON.parse(await page.locator('#state').textContent());
    const pick=async(label,query,option)=>{
      const field=page.getByRole('combobox',{name:label,exact:true});
      await field.fill(query);
      await page.getByRole('option',{name:option,exact:true}).click();
      checks++;
    };
    await page.getByRole('button',{name:'Kirim formulir',exact:true}).click();
    assert.equal((await state()).submits,0);
    assert.equal(await page.getByRole('combobox',{name:'COA wajib',exact:true}).getAttribute('aria-expanded'),'true');
    await pick('COA wajib','kas besar','1101 · Kas Besar');
    assert.equal((await state()).number,42);assert.equal((await state()).numberType,'number');
    assert.equal((await state()).changes,1);assert.equal((await state()).lastEvent,'42');
    await page.getByRole('button',{name:'Kirim formulir',exact:true}).click();
    assert.equal((await state()).submits,1);checks+=3;
    assert.equal(await page.getByRole('combobox',{name:'Status aktif',exact:true}).inputValue(),'Nonaktif');
    assert.equal(await page.getByRole('combobox',{name:'Nilai nol',exact:true}).inputValue(),'Nol');
    await pick('Status aktif','Aktif','Aktif');assert.equal((await state()).active,true);
    await pick('Status aktif','Nonaktif','Nonaktif');assert.equal((await state()).active,false);
    await pick('Group principal','Delapan','Principal Delapan');assert.deepEqual((await state()).selected,[7,8]);
    await pick('Group principal','Tujuh','Principal Tujuh');assert.deepEqual((await state()).selected,[8]);
    await page.getByRole('combobox',{name:'Jenis biaya',exact:true}).fill('biaya');
    assert.ok(await page.getByRole('option',{name:'Biaya perlu approval',exact:true}).isDisabled());
    assert.ok(await page.getByRole('option',{name:'Biaya nonaktif',exact:true}).isDisabled());
    await page.getByRole('combobox',{name:'Jenis biaya',exact:true}).fill('');
    await page.getByRole('combobox',{name:'Jenis biaya',exact:true}).press('ArrowDown');
    await page.getByRole('combobox',{name:'Jenis biaya',exact:true}).press('ArrowDown');
    await page.getByRole('combobox',{name:'Jenis biaya',exact:true}).press('Enter');
    assert.equal((await state()).fee,2);checks+=3;
    await pick('Pilih draf','drf50220','DRF-5-0220 · 2026-10-15 · 220 nota');
    assert.equal((await state()).draft,'DRF-5-0220');
    await page.getByRole('combobox',{name:'Pilih draf',exact:true}).click();
    const list=page.locator('#'+await page.getByRole('combobox',{name:'Pilih draf',exact:true}).getAttribute('aria-controls'));
    assert.equal(await list.getByRole('option').count(),50);
    await list.getByRole('button',{name:/Tampilkan 50 berikutnya/}).click();
    assert.equal(await list.getByRole('option').count(),100);
    await page.getByRole('combobox',{name:'Pilih draf',exact:true}).press('Escape');
    assert.equal(await page.getByRole('combobox',{name:'Pilih draf',exact:true}).inputValue(),'DRF-5-0220 · 2026-10-15 · 220 nota');
    await page.getByRole('button',{name:'Ubah fieldset',exact:true}).click();
    assert.ok(await page.getByRole('combobox',{name:'Pilih draf',exact:true}).isDisabled());
    await page.getByRole('combobox',{name:'Pilih draf',exact:true}).locator('..').dispatchEvent('click');
    assert.equal(await page.getByRole('listbox').count(),0);checks+=4;
    await pick('Status filter','baru','Baru');assert.equal((await state()).filter.status,'1');
    await page.getByRole('combobox',{name:'Cari remote',exact:true}).fill('SKU-9');
    await page.getByRole('option',{name:'Produk SKU-9',exact:true}).click();
    assert.equal((await state()).remote,99);assert.equal((await state()).remoteQuery,'SKU-9');checks++;
    await page.getByRole('button',{name:'Buka modal',exact:true}).click();
    await pick('Draf dalam modal','0220','DRF-5-0220 · 2026-10-15 · 220 nota');
    for(const width of [390,768,1440]){
      await page.setViewportSize({width,height:1000});
      await page.getByRole('combobox',{name:'Draf dalam modal',exact:true}).fill('0219');
      const option=page.getByRole('option',{name:'DRF-5-0219 · 2026-10-15 · 219 nota',exact:true});
      assert.ok(await option.isVisible());
      const hit=await option.evaluate(el=>{const r=el.getBoundingClientRect();return el.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2));});
      assert.ok(hit,'Dropdown is not clipped by modal bounds');
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await page.screenshot({path:`/tmp/budimas-select2-${theme}-${width}.png`,fullPage:true,animations:'disabled'});
      await option.tap();checks++;
    }
    assert.deepEqual(errors,[]);await context.close();
  }
  console.log(`PASS ${checks} searchable dropdown checks: search/paging, typed values, multi-select, disabled choices/fieldset, keyboard, required form, change events, remote search, modal, light/dark and 3 widths.`);
} finally {await browser.close();}
