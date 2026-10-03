#!/usr/bin/env bash
set -euo pipefail

LOCK_FILE="/tmp/budimas_legacy_master_sync.lock"
LOG_DIR="/var/log/budimas"
PYTHON="/root/budimas_legacy_import_venv/bin/python"
SCHEMA="legacy_master_import_server"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/legacy_master_sync_${STAMP}.log"

mkdir -p "${LOG_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "$(date '+%F %T') another legacy sync is running" | tee -a "${LOG_FILE}"
  exit 0
fi

{
  echo "== $(date '+%F %T') legacy sync start =="

  echo "-- backup current public tables"
  "${PYTHON}" - <<'PY'
import pg8000

tables = [
    "principal",
    "produk",
    "customer",
    "plafon",
    "users",
    "sales",
    "sales_detail",
    "wms_rack_master",
    "wms_stock_rak",
]
suffix = "20260717_legacy_merge"
conn = pg8000.connect(user="postgres", password="", host="127.0.0.1", port=5432, database="budimas_dev", timeout=60)
cur = conn.cursor()
for table in tables:
    backup = f"backup_{table}_{suffix}"
    cur.execute(f"DROP TABLE IF EXISTS {backup}")
    cur.execute(f"CREATE TABLE {backup} AS TABLE {table}")
    cur.execute(f"SELECT COUNT(*) FROM {backup}")
    print(f"{backup}\t{cur.fetchone()[0]}")
conn.commit()
conn.close()
PY

  echo "-- refresh staging from SQL Server"
  "${PYTHON}" /root/server_import_legacy_master.py "${SCHEMA}"

  echo "-- merge master principal/produk/customer/plafon"
  "${PYTHON}" /root/merge_legacy_master_to_public.py \
    --schema "${SCHEMA}" \
    --batch-code "legacy-master-sync-${STAMP}" \
    --apply

  echo "-- merge sales"
  "${PYTHON}" /root/merge_legacy_sales_to_public.py \
    --schema "${SCHEMA}" \
    --batch-code "legacy-sales-sync-${STAMP}" \
    --apply

  echo "-- merge WMS"
  "${PYTHON}" /root/merge_legacy_wms_to_public.py \
    --schema "${SCHEMA}" \
    --batch-code "legacy-wms-sync-${STAMP}" \
    --apply

  echo "-- final counts"
  "${PYTHON}" - <<'PY'
import pg8000

tables = [
    "principal",
    "produk",
    "customer",
    "plafon",
    "users",
    "sales",
    "sales_detail",
    "wms_rack_master",
    "wms_stock_rak",
]
conn = pg8000.connect(user="postgres", password="", host="127.0.0.1", port=5432, database="budimas_dev", timeout=60)
cur = conn.cursor()
for table in tables:
    cur.execute(f"SELECT COUNT(*), MAX(id) FROM {table}")
    count, max_id = cur.fetchone()
    print(f"{table}\tcount={count}\tmax_id={max_id}")
conn.close()
PY

  echo "== $(date '+%F %T') legacy sync done =="
} 2>&1 | tee -a "${LOG_FILE}"

find "${LOG_DIR}" -name "legacy_master_sync_*.log" -type f -mtime +14 -delete
