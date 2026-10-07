"""User-confirmed repair of C1's unpaid combined invoice and credit cache.

Default: dry run on the API host. --apply backs up the complete bounded input
snapshot, locks and rechecks it, applies only explicit field updates, and saves
a receipt. Never posts payments, applies available CNs, or creates an LPH.
"""
import argparse
import copy
import hashlib
import json
import os
import shlex
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

CUSTOMER = 89330
INVOICE = 66059040
ORDER_IDS = {66062181, 66062182}
PLAFON_IDS = {173127, 173129, 192927, 192928}
ACTIVE_STATES = {1, 2, 3, 4, 5, 6, 9, 10, 11}
APPROVED_TOTAL = Decimal('2265522.00')
ZERO = Decimal(0)


def amount(value):
    result = Decimal(str(value or 0))
    if not result.is_finite():
        raise ValueError('Non-finite amount')
    return result


def money(value):
    return float(amount(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_plan(snapshot):
    masters = {p['id']:p for p in snapshot['plafon']}
    orders = {o['id']:o for o in snapshot['sales_order']}
    invoices = {f['id']:f for f in snapshot['faktur']}
    require(set(masters)==PLAFON_IDS, 'Credit master scope changed')
    require(all(p['id_customer']==CUSTOMER for p in masters.values()), 'Wrong customer')
    require(all(o['id_plafon'] in masters and o['id_cabang']==5 for o in orders.values()), 'Wrong order scope')
    target = invoices[INVOICE]
    require(target['no_faktur']=='NPBMMSLO-2609000010' and target['id_order_batch']==4
            and target['id_sales_order'] is None and target['status_faktur']==2, 'Target invoice changed')
    require(not snapshot['target_lph'] and not snapshot['target_claims']
            and not snapshot['target_returns'] and not snapshot['target_revisions']
            and not snapshot['target_cn'], 'Target has LPH, payment claim, return, or revision; review again')
    require(amount(target.get('nominal_retur'))==0 and amount(target.get('total_dana_diterima'))==0
            and amount(target.get('credit_note_nominal'))==0, 'Target already settled/credited')
    details = {}
    for row in snapshot['faktur_detail']:
        details.setdefault(row['id_faktur'], []).append(row)
    target_details = details[INVOICE]
    require(len(target_details)==2 and {d['id_sales_order'] for d in target_details}==ORDER_IDS
            and {d['id_principal'] for d in target_details}=={33,232}, 'Both original principals are required')
    require(all(d['id_principal']==masters[orders[d['id_sales_order']]['id_plafon']]['id_principal']
                for d in target_details), 'Principal allocation changed')
    require(all(orders[oid]['status_order']==6 for oid in ORDER_IDS), 'Target order status changed')
    total = sum((amount(d['total']) for d in target_details), ZERO)
    require(total==APPROVED_TOTAL, 'Detail amount differs from user-confirmed amount')
    require(amount(target['total_penjualan']) in (Decimal('1100022'), APPROVED_TOTAL), 'Header amount changed')

    def is_target(row):
        return row.get('id_faktur')==INVOICE or row.get('id_sales_order') in ORDER_IDS or row.get('id_order_batch')==4

    for table in ('setoran','setoran_customer','payment_voucher_usage','finance_customer_advance_usage'):
        require(not any(is_target(r) for r in snapshot[table]), 'Target has a payment or adjustment: '+table)

    changes = []
    def change(table, row, fields):
        changed = {key:money(value) for key,value in fields.items() if amount(row.get(key))!=amount(value)}
        if changed:
            changes.append({'table':table, 'id':row['id'], 'before':{key:row.get(key) for key in changed}, 'after':changed})

    dpp = sum((amount(d['subtotal']) for d in target_details), ZERO)
    discount = sum((amount(d['subtotal_diskon']) for d in target_details), ZERO)
    tax = sum((amount(d['pajak']) for d in target_details), ZERO)
    require(dpp+tax==total, 'Detail components do not reconcile')
    change('faktur',target,{'total_penjualan':total, 'dpp':dpp, 'pajak':tax,
                           'subtotal_penjualan':dpp+discount, 'subtotal_diskon':discount})
    # Keep historical draft and promotion snapshots; use actual final detail
    # totals for the current invoice, SO summary, and credit exposure.
    for detail in target_details:
        change('sales_order',orders[detail['id_sales_order']],{'total_order':amount(detail['total'])})

    links = {}
    order_to_invoice = {}
    for fid, invoice in invoices.items():
        children = [invoice['id_sales_order']] if invoice['id_sales_order'] is not None else [d['id_sales_order'] for d in details.get(fid,[])]
        require(len(children)==len(set(children)), 'Duplicate invoice/SO link')
        require(all(oid in orders for oid in children), 'Invoice crosses customer scope')
        active = [oid for oid in children if orders[oid]['status_order'] in ACTIVE_STATES]
        if not active:
            continue
        require(len(active)==len(children), 'Mixed active/inactive parent invoice')
        require(invoice['jenis_faktur']=='penjualan' and invoice['status_faktur'] in (0,1,2,3), 'Unexpected active invoice status')
        if invoice['id_sales_order'] is None:
            require(all(orders[oid]['id_order_batch']==invoice['id_order_batch'] for oid in children), 'Wrong batch link')
            detail_total = sum((amount(d['total']) for d in details[fid]),ZERO)
            require(detail_total==(APPROVED_TOTAL if fid==INVOICE else amount(invoice['total_penjualan'])), 'Another header/detail mismatch')
        links[fid] = children
        for oid in children:
            require(oid not in order_to_invoice, 'Multiple active invoices on one SO')
            order_to_invoice[oid] = fid
    require(set(order_to_invoice)=={oid for oid,o in orders.items() if o['status_order'] in ACTIVE_STATES}, 'Active order missing invoice')

    offsets = {oid:ZERO for oid in order_to_invoice}
    final_payments = {oid:ZERO for oid in order_to_invoice}
    def allocate(row, value, final_payment=False):
        fid = row.get('id_faktur')
        oid = row.get('id_sales_order')
        if fid is None:
            fid = order_to_invoice.get(oid)
        if fid not in links:
            require(oid not in order_to_invoice, 'Adjustment links to a different invoice')
            return
        if oid not in links[fid]:
            require(oid is None and len(links[fid])==1, 'Ambiguous principal allocation')
            oid = links[fid][0]
        require(value>=0, 'Negative payment/adjustment')
        offsets[oid] += value
        if final_payment:
            final_payments[oid] += value

    for row in snapshot['setoran']:
        if row['status_setoran']==3:
            draft = row.get('draft_jumlah_setor')
            allocate(row,amount(draft if draft is not None else row.get('jumlah_setoran')),True)
    # setoran_customer is a projection, NOT an additional confirmed receipt.
    for row in snapshot['payment_voucher_usage']:
        if row['status']==1:
            allocate(row,amount(row['nominal']))
    for row in snapshot['finance_customer_advance_usage']:
        if row['status']=='FINALIZED':
            # Fail rather than double count an advance already projected as
            # a finalized receipt. No such usage exists in this repair scope.
            require(not row.get('id_setoran'), 'Advance/receipt deduplication requires review')
            allocate(row,amount(row['nominal_pakai']))

    by_master = {pid:{'receivable':ZERO,'open_order_reservation':ZERO,'final_receipts':ZERO,'order_count':0} for pid in masters}
    for fid,children in links.items():
        invoice = invoices[fid]
        returned = amount(invoice.get('nominal_retur'))
        require(not returned or len(children)==1, 'Unallocated parent return')
        for oid in children:
            base = amount(invoice['total_penjualan']) if invoice['id_sales_order'] is not None else amount(next(d['total'] for d in details[fid] if d['id_sales_order']==oid))
            require(base>=0 and returned>=0 and offsets[oid]+returned<=base, 'Settlement exceeds invoice amount')
            outstanding = base-returned-offsets[oid]
            group = by_master[orders[oid]['id_plafon']]
            key = 'receivable' if orders[oid]['status_order']==6 else 'open_order_reservation'
            group[key] += outstanding
            group['final_receipts'] += final_payments[oid]
            group['order_count'] += 1

    summary = []
    for pid,master in sorted(masters.items()):
        group = by_master[pid]
        remaining = amount(master['limit_bon'])-group['receivable']-group['open_order_reservation']
        require(0<=remaining<=amount(master['limit_bon']), 'Credit exposure outside expected range')
        change('plafon',master,{'sisa_bon':remaining})
        summary.append({'plafon_id':pid,'principal_id':master['id_principal'],
                        'limit':money(master['limit_bon']), 'before':master['sisa_bon'], 'after':money(remaining),
                        **{k:(v if k=='order_count' else money(v)) for k,v in group.items()}})
    return {'invoice_id':INVOICE,'invoice_total':money(total),'changes':changes,'credit_summary':summary,
            'company_receivable':money(sum((g['receivable'] for g in by_master.values()),ZERO))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    import pg8000.dbapi
    root = Path('/www/wwwroot/API')
    config = {}
    keys = ('DB_HOST','DB_PORT','DB_NAME','DB_USER','DB_PASS')
    for line in (root/'.env').read_text().splitlines():
        key,sep,value=line.strip().removeprefix('export ').partition('=')
        if sep and key.strip() in keys:
            config[key.strip()]=' '.join(shlex.split(value,comments=True))
    pid=(root/'uwsgi.pid').read_text().strip()
    for entry in (Path('/proc')/pid/'environ').read_bytes().split(b'\0'):
        key,sep,value=entry.partition(b'=')
        if sep and key.decode() in keys:
            config[key.decode()]=value.decode()
    conn=pg8000.dbapi.connect(user=config.get('DB_USER','postgres'),password=config.get('DB_PASS',''),
        host=config.get('DB_HOST','127.0.0.1'),port=int(config.get('DB_PORT') or 5432),
        database=config.get('DB_NAME','budimas_dev'),timeout=15)
    cur=conn.cursor()
    def rows(sql,params=()):
        cur.execute(sql,params)
        return [r[0] for r in cur.fetchall()]
    def scoped(table,column,ids):
        if not ids:
            return []
        return rows(f'SELECT to_jsonb(t) FROM {table} t WHERE {column} IN ({",".join(["%s"]*len(ids))}) ORDER BY t.id',tuple(ids))
    def snapshot():
        data={}
        identity=rows("SELECT jsonb_build_object('id',id,'kode',kode,'nama',nama,'id_cabang',id_cabang) FROM customer WHERE id=%s",(CUSTOMER,))
        require(identity==[{'id':CUSTOMER,'kode':'C1','nama':'Customer 1 (Test)','id_cabang':5}], 'Customer identity changed')
        data['customer']=identity
        data['plafon']=scoped('plafon','id_customer',[CUSTOMER])
        data['sales_order']=scoped('sales_order','id_plafon',[p['id'] for p in data['plafon']])
        require(0<len(data['sales_order'])<200,'Unexpected order scope')
        oids=[o['id'] for o in data['sales_order']]
        slots=','.join(['%s']*len(oids))
        fids=rows(f'''SELECT to_jsonb(id) FROM faktur WHERE id_sales_order IN ({slots})
            UNION SELECT to_jsonb(id_faktur) FROM faktur_detail WHERE id_sales_order IN ({slots})''',tuple(oids+oids))
        fids=sorted(set(fids))
        data['faktur']=scoped('faktur','id',fids)
        data['faktur_detail']=scoped('faktur_detail','id_faktur',fids)
        fslots=','.join(['%s']*len(fids))
        for table in ('setoran','setoran_customer','payment_voucher_usage','finance_customer_advance_usage'):
            data[table]=rows(f'''SELECT to_jsonb(t) FROM {table} t WHERE id_sales_order IN ({slots})
                OR id_faktur IN ({fslots}) ORDER BY id''',tuple(oids+fids))
        data['target_lph']=scoped('lph_detail','id_faktur',[INVOICE])
        data['target_claims']=scoped('finance_lph_claim','id_faktur',[INVOICE])
        data['target_returns']=rows('SELECT to_jsonb(r) FROM retur_request r WHERE id_sales_order IN(66062181,66062182) ORDER BY id_request')
        data['target_revisions']=scoped('batal_realisasi_request_invoice','id_faktur',[INVOICE])
        data['target_cn']=rows('SELECT to_jsonb(c) FROM credit_note c WHERE id_faktur=%s ORDER BY id_cn',(INVOICE,))
        # Include batch-only legacy receipts in the safety check as well.
        for table in ('setoran','setoran_customer'):
            extra=rows(f'SELECT to_jsonb(t) FROM {table} t WHERE id_order_batch=4 ORDER BY id')
            data[table]=sorted({r['id']:r for r in data[table]+extra}.values(),key=lambda r:r['id'])
        return data

    try:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL statement_timeout='15s'")
        before=snapshot()
        plan=build_plan(before)
        conn.rollback()
        print(json.dumps({'mode':'apply' if args.apply else 'dry-run',**plan}),flush=True)
        if not args.apply or not plan['changes']:
            return
        require(len(plan['changes'])<=6,'Unexpected write scope')
        backup=Path(tempfile.mkdtemp(prefix='customer-c1-invoice-20261006.',dir='/www/backup'))
        os.chmod(backup,0o700)
        def save(name,value):
            payload=json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True).encode()
            fd=os.open(str(backup/name),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(payload);stream.flush();os.fsync(stream.fileno())
            return hashlib.sha256(payload).hexdigest()
        sha=save('before.json',{'snapshot':before,'plan':plan,'authorization':'User confirmed combined invoice of two principals; unpaid, no revision/return; restore detail sum.'})
        print(json.dumps({'backup':str(backup),'before_sha256':sha}),flush=True)
        cur.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        cur.execute("SET LOCAL statement_timeout='10s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        cur.execute("SET LOCAL idle_in_transaction_session_timeout='15s'")
        for table in ('sales_order','plafon','faktur','faktur_detail'):
            ids=sorted(r['id'] for r in before[table])
            if ids:
                cur.execute(f'SELECT id FROM {table} WHERE id IN ({",".join(["%s"]*len(ids))}) ORDER BY id FOR UPDATE',tuple(ids))
                require(len(cur.fetchall())==len(ids),'Row vanished during lock')
        require(snapshot()==before,'Concurrent update detected; retry with new review')
        expected=copy.deepcopy(before)
        for entry in plan['changes']:
            table=entry['table']
            allowed={'faktur':{'total_penjualan','dpp','pajak','subtotal_penjualan','subtotal_diskon'},
                     'sales_order':{'total_order'},'plafon':{'sisa_bon'}}
            require(table in allowed and set(entry['after'])<=allowed[table],'Unexpected column update')
            assignments=','.join(f'{column}=%s' for column in entry['after'])
            cur.execute(f'UPDATE {table} SET {assignments} WHERE id=%s RETURNING id',tuple(entry['after'].values())+(entry['id'],))
            returned=cur.fetchall()
            require(len(returned)==1 and returned[0][0]==entry['id'],'Update count assertion failed')
            next(r for r in expected[table] if r['id']==entry['id']).update(entry['after'])
        after=snapshot()
        require(after==expected,'Unexpected side effect or concurrent data change')
        require(not build_plan(after)['changes'],'Repair is not idempotent')
        conn.commit()
        receipt={'status':'COMMITTED','committed_at':datetime.now(timezone.utc).isoformat(),'backup':str(backup),
                 'before_sha256':sha,**plan,'updated_rows':len(plan['changes'])}
        save('committed.json',receipt)
        print(json.dumps(receipt),flush=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close();conn.close()


if __name__=='__main__':
    main()
