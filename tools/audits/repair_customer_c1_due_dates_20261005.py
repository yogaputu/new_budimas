"""Narrow, backed-up repair for C1's missing dates. Run on the API host.

Default is a read-only dry run. --apply changes only NULL due dates on existing
active orders for Customer 89330/C1/Solo, using the current 24-day master term.
No invoice amounts, stock, credit balances, or payment states are modified.
"""
import argparse
import hashlib
import json
import os
import shlex
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CUSTOMER_ID = 89330
BRANCH_ID = 5
PLAFON_IDS = [173127, 173129, 192927, 192928]
ACTIVE_STATES = (1, 2, 3, 4, 5, 6, 9, 10, 11)


def plan_missing_dates(orders, plafons):
    """Fail closed on unexpected scope, terms, or absent date basis."""
    by_id = {p['id']: p for p in plafons}
    plan = []
    for order in orders:
        master = by_id[order['id_plafon']]
        if master['id_customer'] != CUSTOMER_ID or order['id_cabang'] != BRANCH_ID:
            raise ValueError('Unexpected customer or branch')
        if order['status_order'] not in ACTIVE_STATES or order['tanggal_jatuh_tempo'] is not None:
            continue
        if master['tempo'] != 24:
            raise ValueError('Master term has changed; review before repair')
        base = order['tanggal_faktur'] or order['tanggal_order']
        if not base:
            raise ValueError('Missing order/invoice date')
        if isinstance(base, str):
            base = date.fromisoformat(base[:10])
        due = base + timedelta(days=24)
        plan.append({'id_sales_order':order['id'], 'no_order':order['no_order'],
                     'id_plafon':master['id'], 'base_date':base.isoformat(),
                     'before':None, 'after':due.isoformat(), 'term_days':24})
    return sorted(plan, key=lambda row: row['id_sales_order'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    import pg8000.dbapi
    root = Path('/www/wwwroot/API')
    settings = {}
    keys = ('DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASS', 'DB_NAME')
    for line in (root / '.env').read_text().splitlines():
        key, sep, value = line.strip().removeprefix('export ').partition('=')
        if sep and key.strip() in keys:
            settings[key.strip()] = ' '.join(shlex.split(value, comments=True))
    pid = (root / 'uwsgi.pid').read_text().strip()
    for item in (Path('/proc') / pid / 'environ').read_bytes().split(b'\0'):
        key, sep, value = item.partition(b'=')
        if sep and key.decode() in keys:
            settings[key.decode()] = value.decode()
    conn = pg8000.dbapi.connect(user=settings.get('DB_USER', 'postgres'),
        password=settings.get('DB_PASS', ''), host=settings.get('DB_HOST', '127.0.0.1'),
        port=int(settings.get('DB_PORT') or 5432),
        database=settings.get('DB_NAME', 'budimas_dev'), timeout=15)
    cur = conn.cursor()

    def rows(sql, params=()):
        cur.execute(sql, params)
        return [r[0] for r in cur.fetchall()]

    try:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        cur.execute("SET LOCAL statement_timeout='10s'")
        customer = rows("""SELECT jsonb_build_object('id',id,'kode',kode,'nama',nama,'id_cabang',id_cabang)
                         FROM customer WHERE id=%s""", (CUSTOMER_ID,))
        if customer != [{'id':CUSTOMER_ID, 'kode':'C1', 'nama':'Customer 1 (Test)', 'id_cabang':BRANCH_ID}]:
            raise RuntimeError('Customer identity changed')
        plafons = rows('SELECT to_jsonb(p) FROM plafon p WHERE id_customer=%s ORDER BY id', (CUSTOMER_ID,))
        if [p['id'] for p in plafons] != PLAFON_IDS:
            raise RuntimeError('Unexpected credit master scope')
        orders = rows("""SELECT to_jsonb(so) FROM sales_order so JOIN plafon p ON p.id=so.id_plafon
                         WHERE p.id_customer=%s AND so.id_cabang=%s
                         AND so.status_order IN(1,2,3,4,5,6,9,10,11)
                         AND so.tanggal_jatuh_tempo IS NULL ORDER BY so.id""", (CUSTOMER_ID,BRANCH_ID))
        plan = plan_missing_dates(orders, plafons)
        conn.rollback()
        print(json.dumps({'mode':'apply' if args.apply else 'dry-run', 'customer':customer[0],
                          'affected_order_count':len(plan), 'plan':plan}), flush=True)
        if not args.apply or not plan:
            return
        if len(plan)>50:
            raise RuntimeError('Unexpectedly broad repair')

        # Durable, scoped backup is written BEFORE acquiring any write locks.
        backup_root = Path('/www/backup')
        if not backup_root.is_dir():
            raise RuntimeError('Expected backup root missing')
        backup = Path(tempfile.mkdtemp(prefix='customer-c1-due-dates-20261005.', dir=backup_root))
        os.chmod(backup, 0o700)
        stamp = datetime.now(timezone.utc).isoformat()
        snapshot = {'created_at':stamp, 'purpose':'User-authorized missing due date repair for C1',
                    'customer':customer[0], 'plafons':plafons, 'sales_orders':orders, 'plan':plan}
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2).encode()

        def save_new(name, content):
            fd = os.open(str(backup/name), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())

        save_new('before.json', encoded)
        print(json.dumps({'backup':str(backup), 'before_sha256':hashlib.sha256(encoded).hexdigest()}), flush=True)
        cur.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        cur.execute("SET LOCAL statement_timeout='5s'")
        cur.execute("SET LOCAL lock_timeout='1s'")
        cur.execute("SET LOCAL idle_in_transaction_session_timeout='10s'")
        ids = [p['id_sales_order'] for p in plan]
        placeholders = ','.join(['%s']*len(ids))
        locked_orders = rows(f'SELECT to_jsonb(so) FROM sales_order so WHERE id IN ({placeholders}) ORDER BY id FOR UPDATE', tuple(ids))
        locked_plafons = rows('SELECT to_jsonb(p) FROM plafon p WHERE id_customer=%s ORDER BY id FOR SHARE', (CUSTOMER_ID,))
        if locked_orders != orders or locked_plafons != plafons:
            raise RuntimeError('Concurrent change detected; no update applied')
        updated = []
        for entry in plan:
            cur.execute("""UPDATE sales_order SET tanggal_jatuh_tempo=%s
                           WHERE id=%s AND id_plafon=%s AND id_cabang=%s
                           AND tanggal_jatuh_tempo IS NULL RETURNING id,tanggal_jatuh_tempo""",
                        (date.fromisoformat(entry['after']),entry['id_sales_order'],entry['id_plafon'],BRANCH_ID))
            result = cur.fetchall()
            if len(result)!=1 or result[0][1].isoformat()!=entry['after']:
                raise RuntimeError('Update assertion failed')
            updated.append({'id':result[0][0], 'tanggal_jatuh_tempo':result[0][1].isoformat()})
        after = rows(f'SELECT to_jsonb(so) FROM sales_order so WHERE id IN ({placeholders}) ORDER BY id', tuple(ids))
        for before, current in zip(orders,after):
            expected = dict(before)
            expected['tanggal_jatuh_tempo'] = next(p['after'] for p in plan if p['id_sales_order']==before['id'])
            if current != expected:
                raise RuntimeError('Unexpected additional column change')
        conn.commit()
        receipt = {'committed_at':datetime.now(timezone.utc).isoformat(), 'backup':str(backup),
                   'customer_id':CUSTOMER_ID, 'updated_count':len(updated), 'updated':updated,
                   'unchanged':['plafon balances','invoice/payment amounts and states','stock','other customers']}
        save_new('committed.json', json.dumps(receipt,indent=2).encode())
        print(json.dumps(receipt), flush=True)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
