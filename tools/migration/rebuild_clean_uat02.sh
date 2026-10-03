#!/usr/bin/env bash
# Rebuild the isolated UAT02 master-import target from immutable server
# artifacts.  This script is intentionally stored locally and is NOT run by
# Codex.  Copy it to the PostgreSQL host only after review.
#
# Safety contract
# - Default mode is read-only (--dry-run).
# - The only mutable database name is the fixed UAT02 target below.
# - It never drops a database.  A pre-existing UAT02 is a hard stop.
# - It does not connect to SQL Server and never writes budimas_dev, the clean
#   v2 baseline, or UAT01.
# - It deliberately does NOT restore the old pre-master dump: its immutable
#   clean_target_attestation is bound to budimas_clean_20260902_v2, not UAT02.
#
# Modes:
#   ./rebuild_clean_uat02.sh                 # artifact/catalog audit only
#   ./rebuild_clean_uat02.sh --build-target  # create empty UAT02 + stage + fresh attestation + master dry-run
#   ./rebuild_clean_uat02.sh --preflight-existing-target # read-only audit of an already-created UAT02 seed
#   ./rebuild_clean_uat02.sh --prepare-existing-target   # extension + fresh attestation + master dry-run only
#   UAT02_RUN_DIR=/www/backups/.../uat02_rebuild_... \
#     ./rebuild_clean_uat02.sh --apply-master # requires fresh target-bound hold approval
#   UAT02_RUN_DIR=/www/backups/.../uat02_rebuild_... \
#     ./rebuild_clean_uat02.sh --verify

set -Eeuo pipefail
IFS=$'\n\t'

readonly TARGET_DB='budimas_clean_20260902_v2_uat02'
readonly BASELINE_DB='budimas_clean_20260902_v2'
readonly UAT01_DB='budimas_clean_20260902_v2_uat01'
readonly PRODUCTION_DB='budimas_dev'
readonly REGISTRY_SCHEMA='migration_clean_bdm_tmp_202609'
readonly BDM_STAGE_SCHEMA='legacy_bdm_solo_final_freeze_20260830'
readonly TMP_STAGE_SCHEMA='legacy_tmp_solo_final_freeze_20260830'
readonly EXPECTED_IMPORT_KEY='bdm-tmp-master-v2-uat02-20260902'

readonly PG_BIN="${PG_BIN:-/www/server/pgsql/bin}"
readonly PSQL="$PG_BIN/psql"
readonly PG_RESTORE="$PG_BIN/pg_restore"
readonly CREATEDB="$PG_BIN/createdb"
readonly PG_SOCKET="${PG_SOCKET:-/tmp}"
readonly ARTIFACT_DIR="${ARTIFACT_DIR:-/www/backups/budimas_migration_20260902}"

readonly SCHEMA_DUMP="$ARTIFACT_DIR/budimas_dev_schema_only_20260902T003000+0700.dump"
readonly REFERENCE_DUMP="$ARTIFACT_DIR/budimas_dev_reference_allowlist_20260902T003300+0700.dump"
readonly FREEZE_DUMP="$ARTIFACT_DIR/bdm_tmp_final_freeze_20260830_data_20260902T003100+0700.dump"
readonly BASE_REGISTRY_DDL="$ARTIFACT_DIR/20260902_create_clean_import_registry.sql"
readonly EXTEND_REGISTRY_DDL="$ARTIFACT_DIR/20260902_extend_clean_import_registry_master_maps.sql"
readonly IMPORTER="$ARTIFACT_DIR/import_clean_bdm_tmp_master.py"
readonly POLICY="$ARTIFACT_DIR/clean_import_policy.json"
readonly READINESS_REPORTER="$ARTIFACT_DIR/report_clean_master_readiness.py"
readonly CUSTOMER_POLICY="$ARTIFACT_DIR/customer_pricing_tax_bdm_tmp_20260902.approved.json"
readonly PRODUCT_TAX_POLICY="$ARTIFACT_DIR/product_tax_bdm_tmp_20260902.approved.json"
readonly SALES_POLICY="$ARTIFACT_DIR/sales_type_bdm_tmp_20260902.approved.json"
readonly PRICE_POLICY="$ARTIFACT_DIR/product_price_bdm_tmp_20260902.approved.json"
readonly PRIOR_APPROVED_HOLDS="$ARTIFACT_DIR/clean_master_v2_approved_policy_holds_20260902.json"
readonly PRIOR_APPROVED_DRYRUN="$ARTIFACT_DIR/clean_master_v2_approved_policy_dryrun_20260902.json"

readonly REFERENCE_TABLES=(
  wilayah1 wilayah2 wilayah3 wilayah4 perusahaan cabang perusahaan_cabang
  departemen jabatan fitur jabatan_akses sales_tipe status tipe_transaksi
  modul fitur_mal source_modul customer_tipe tipe_toko_customer
  produk_tipe_harga master_ppn produk_satuan produk_kategori rute
  rute_cabang armada_tipe
)

readonly EXPECTED_STAGE_TABLES=(
  __stage_run __stage_manifest principle customer sales stok barangsatuan plafon
  hjualsm djualsm hjualsmandroid djualsmandroid hbayarsm dbayarsm pembayaran
  hretursm dretursm hretursmandroid dretursmandroid hpembelian dpembelian
  stokopnameandroid kunjungansales
)

MODE="${1:---dry-run}"
if [[ $# -ne 1 ]] || [[ "$MODE" != '--dry-run' && "$MODE" != '--build-target' && "$MODE" != '--preflight-existing-target' && "$MODE" != '--prepare-existing-target' && "$MODE" != '--apply-master' && "$MODE" != '--verify' ]]; then
  printf '%s\n' 'Usage: rebuild_clean_uat02.sh [--dry-run|--build-target|--preflight-existing-target|--prepare-existing-target|--apply-master|--verify]' >&2
  exit 64
fi

die() {
  printf 'REFUSED: %s\n' "$*" >&2
  exit 2
}

note() {
  printf '%s\n' "$*"
}

require_root() {
  [[ "${EUID}" -eq 0 ]] || die 'Jalankan sebagai root pada host PostgreSQL agar koneksi lokal dijalankan sebagai postgres.'
}

require_file() {
  [[ -f "$1" && -r "$1" ]] || die "Artefak wajib tidak dapat dibaca: $1"
}

require_tool() {
  [[ -x "$1" ]] || die "Binary PostgreSQL tidak ditemukan/tidak executable: $1"
}

pg_admin() {
  runuser -u postgres -- "$PSQL" -X -v ON_ERROR_STOP=1 -h "$PG_SOCKET" -d postgres "$@"
}

pg_target() {
  runuser -u postgres -- "$PSQL" -X -v ON_ERROR_STOP=1 -h "$PG_SOCKET" -d "$TARGET_DB" "$@"
}

database_exists() {
  local database_name="$1"
  pg_admin -Atqc "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$database_name')"
}

require_database_state_for_build() {
  [[ "$(database_exists "$PRODUCTION_DB")" == 't' ]] || die "Database produksi $PRODUCTION_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$BASELINE_DB")" == 't' ]] || die "Baseline $BASELINE_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$UAT01_DB")" == 't' ]] || die "UAT01 $UAT01_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$TARGET_DB")" == 'f' ]] || die "Target $TARGET_DB sudah ada. Script tidak pernah drop/overwrite target; audit atau buat target baru."
}

require_database_state_for_existing_target() {
  [[ "$(database_exists "$PRODUCTION_DB")" == 't' ]] || die "Database produksi $PRODUCTION_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$BASELINE_DB")" == 't' ]] || die "Baseline $BASELINE_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$UAT01_DB")" == 't' ]] || die "UAT01 $UAT01_DB tidak ditemukan; hentikan."
  [[ "$(database_exists "$TARGET_DB")" == 't' ]] || die "Target $TARGET_DB belum ada. Jalankan --build-target terlebih dahulu."
}

assert_existing_seed_target_state() {
  # This is intentionally stricter than merely checking that a database has
  # the desired name.  It permits only the interrupted/pre-master state:
  # public schema/reference + final staging + *base* registry, with neither
  # extension/attestation nor source-owned master/transaction writes.
  pg_target -At -F $'\t' <<'SQL' | python3 -c '
import sys
bad=[]
for line in sys.stdin:
    name, actual, expected=line.rstrip("\n").split("\t")
    if int(actual) != int(expected):
        bad.append(f"{name}: actual={actual} expected={expected}")
if bad:
    raise SystemExit("Seed UAT02 bukan state pre-extension yang aman:\n" + "\n".join(bad))
print("OK: UAT02 berada pada state seed pre-extension yang dapat dilanjutkan.")
'
SELECT 'registry_base_schema', CASE WHEN to_regnamespace('migration_clean_bdm_tmp_202609') IS NOT NULL AND to_regclass('migration_clean_bdm_tmp_202609.import_run') IS NOT NULL THEN 1 ELSE 0 END, 1;
SELECT 'extension_not_installed', CASE WHEN to_regclass('migration_clean_bdm_tmp_202609.clean_target_attestation') IS NULL AND to_regclass('migration_clean_bdm_tmp_202609.product_price_source_map') IS NULL AND to_regclass('migration_clean_bdm_tmp_202609.plafon_source_map') IS NULL AND NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid='migration_clean_bdm_tmp_202609.product_uom_source_map'::regclass AND attname='source_uom_ordinal' AND attnum>0 AND NOT attisdropped) THEN 1 ELSE 0 END, 1;
SELECT 'registry.source_context', count(*), 0 FROM migration_clean_bdm_tmp_202609.source_context;
SELECT 'registry.principal_source_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.principal_source_map;
SELECT 'registry.customer_source_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.customer_source_map;
SELECT 'registry.sales_source_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.sales_source_map;
SELECT 'registry.product_source_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.product_source_map;
SELECT 'registry.product_uom_source_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.product_uom_source_map;
SELECT 'public.principal', count(*), 0 FROM public.principal;
SELECT 'public.customer', count(*), 0 FROM public.customer;
SELECT 'public.sales', count(*), 0 FROM public.sales;
SELECT 'public.produk', count(*), 0 FROM public.produk;
SELECT 'public.produk_uom', count(*), 0 FROM public.produk_uom;
SELECT 'public.produk_harga_jual', count(*), 0 FROM public.produk_harga_jual;
SELECT 'public.plafon', count(*), 0 FROM public.plafon;
SELECT 'public.sales_order', count(*), 0 FROM public.sales_order;
SELECT 'public.sales_order_detail', count(*), 0 FROM public.sales_order_detail;
SELECT 'public.faktur', count(*), 0 FROM public.faktur;
SELECT 'public.faktur_detail', count(*), 0 FROM public.faktur_detail;
SELECT 'stage.bdm_run_1_completed', count(*), 1 FROM legacy_bdm_solo_final_freeze_20260830.__stage_run WHERE id=1 AND source_system='bdm_solo_dist' AND status='completed' AND consistency_mode='maintenance_freeze_serializable';
SELECT 'stage.tmp_run_1_completed', count(*), 1 FROM legacy_tmp_solo_final_freeze_20260830.__stage_run WHERE id=1 AND source_system='tmp_solo_dist' AND status='completed' AND consistency_mode='maintenance_freeze_serializable';
SQL
}

validate_artifacts() {
  require_tool "$PSQL"
  require_tool "$PG_RESTORE"
  require_tool "$CREATEDB"
  command -v python3 >/dev/null 2>&1 || die 'python3 wajib tersedia untuk importer/verifikasi JSON.'

  local path
  for path in "$SCHEMA_DUMP" "$REFERENCE_DUMP" "$FREEZE_DUMP" "$BASE_REGISTRY_DDL" "$EXTEND_REGISTRY_DDL" "$IMPORTER" "$POLICY" "$READINESS_REPORTER" "$CUSTOMER_POLICY" "$PRODUCT_TAX_POLICY" "$SALES_POLICY" "$PRICE_POLICY" "$PRIOR_APPROVED_HOLDS" "$PRIOR_APPROVED_DRYRUN"; do
    require_file "$path"
  done

  python3 - "$POLICY" "$CUSTOMER_POLICY" "$PRODUCT_TAX_POLICY" "$SALES_POLICY" "$PRICE_POLICY" "$PRIOR_APPROVED_HOLDS" "$PRIOR_APPROVED_DRYRUN" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

policy_path, *other_paths = map(Path, sys.argv[1:])
policy = json.loads(policy_path.read_text(encoding='utf-8'))
if policy.get('target', {}).get('registry_schema') != 'migration_clean_bdm_tmp_202609':
    raise SystemExit('Policy registry schema tidak sesuai.')
expected_sources = {
    'bdm_solo_dist': ('legacy_bdm_solo_final_freeze_20260830', 'BMM', 'SLO', 'BDM-SLO/'),
    'tmp_solo_dist': ('legacy_tmp_solo_final_freeze_20260830', 'TMP', 'SLO', 'TMP-SLO/'),
}
for name, expected in expected_sources.items():
    source = policy.get('sources', {}).get(name, {})
    actual = (source.get('staging_schema'), source.get('company_code'), source.get('branch_code'), source.get('document_prefix'))
    if actual != expected:
        raise SystemExit(f'Policy source {name} tidak sesuai snapshot final: {actual!r}')
for path in other_paths[:4]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('approval_status') != 'approved':
        raise SystemExit(f'Policy belum approved: {path}')
approved_holds = json.loads(other_paths[4].read_text(encoding='utf-8'))
if approved_holds.get('format') != 'clean-master-hold-approval-envelope-v1':
    raise SystemExit('Format hold approval historis tidak sesuai.')
manifest = approved_holds.get('manifest', {})
approval = approved_holds.get('approval', {})
if manifest.get('target_database') != 'budimas_clean_20260902_v2':
    raise SystemExit('Hold approval historis bukan bukti v2 yang diharapkan.')
if approval.get('approval_status') != 'approved_skip' or approval.get('approved_manifest_sha256') != manifest.get('manifest_sha256'):
    raise SystemExit('Hold approval historis tidak lengkap atau checksum tidak cocok.')
expected_policy_sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
if manifest.get('policy_sha256') != expected_policy_sha:
    raise SystemExit('Policy clean_import_policy.json berubah dibanding evidence hold historis.')
previous = json.loads(other_paths[5].read_text(encoding='utf-8'))
if previous.get('target_database') != 'budimas_clean_20260902_v2':
    raise SystemExit('Dry-run historis bukan milik baseline v2.')
print('OK: policy approved dan evidence hold historis tervalidasi (hanya sebagai pembanding, bukan approval UAT02).')
PY
}

validate_archive_tocs() {
  "$PG_RESTORE" --list --schema=public "$SCHEMA_DUMP" | awk '
    /^[0-9]+;/ {
      if ($4 == "TABLE" && $5 == "DATA") { print "Schema archive tidak boleh memuat data public: " $0 > "/dev/stderr"; bad=1 }
      if ($4 == "TABLE" && $5 == "public" && $6 == "customer") { seen_customer=1 }
    }
    END { if (!seen_customer || bad) exit 1 }
  ' || die 'TOC schema public tidak lolos guard.'

  "$PG_RESTORE" --list "$REFERENCE_DUMP" | awk '
    BEGIN {
      split("wilayah1 wilayah2 wilayah3 wilayah4 perusahaan cabang perusahaan_cabang departemen jabatan fitur jabatan_akses sales_tipe status tipe_transaksi modul fitur_mal source_modul customer_tipe tipe_toko_customer produk_tipe_harga master_ppn produk_satuan produk_kategori rute rute_cabang armada_tipe", raw, " ")
      for (i in raw) allowed[raw[i]]=1
    }
    /^[0-9]+;/ {
      if ($4 != "TABLE" || $5 != "DATA" || $6 != "public" || !($7 in allowed)) { print "Reference archive di luar allow-list: " $0 > "/dev/stderr"; bad=1; next }
      seen[$7]++
    }
    END {
      for (name in allowed) if (seen[name] != 1) { print "Reference table hilang/duplikat: " name > "/dev/stderr"; bad=1 }
      if (bad) exit 1
    }
  ' || die 'TOC reference allow-list tidak persis sesuai kontrak.'

  "$PG_RESTORE" --list "$FREEZE_DUMP" | awk '
    BEGIN {
      bdm="legacy_bdm_solo_final_freeze_20260830"; tmp="legacy_tmp_solo_final_freeze_20260830"
      split("__stage_run __stage_manifest principle customer sales stok barangsatuan plafon hjualsm djualsm", raw, " ")
      for (i in raw) required[raw[i]]=1
    }
    /^[0-9]+;/ {
      if (($4 == "TABLE" && $5 == "DATA") || ($4 == "SEQUENCE" && $5 == "SET")) {
        if ($6 != bdm && $6 != tmp) { print "Freeze archive memuat schema lain: " $0 > "/dev/stderr"; bad=1; next }
        if ($4 == "TABLE") seen[$6 SUBSEP $7]++
      } else { print "Freeze archive bukan data/sequence final yang diharapkan: " $0 > "/dev/stderr"; bad=1 }
    }
    END {
      for (table in required) {
        if (seen[bdm SUBSEP table] != 1 || seen[tmp SUBSEP table] != 1) { print "Freeze table wajib tidak lengkap: " table > "/dev/stderr"; bad=1 }
      }
      if (bad) exit 1
    }
  ' || die 'TOC freeze BDM/TMP tidak lolos guard.'

  local schema
  for schema in "$BDM_STAGE_SCHEMA" "$TMP_STAGE_SCHEMA"; do
    "$PG_RESTORE" --list --schema="$schema" "$SCHEMA_DUMP" | awk -v expected_schema="$schema" '
      /^[0-9]+;/ {
        if ($4 == "TABLE" && $5 == "DATA") { bad=1 }
        if ($4 == "TABLE" && $5 == expected_schema && $6 == "__stage_run") seen=1
      }
      END { if (!seen || bad) exit 1 }
    ' || die "Definisi schema freeze $schema tidak ditemukan atau bukan schema-only."
  done
}

print_artifact_checksums() {
  sha256sum "$SCHEMA_DUMP" "$REFERENCE_DUMP" "$FREEZE_DUMP" "$BASE_REGISTRY_DDL" "$EXTEND_REGISTRY_DDL" "$IMPORTER" "$POLICY" "$CUSTOMER_POLICY" "$PRODUCT_TAX_POLICY" "$SALES_POLICY" "$PRICE_POLICY" "$PRIOR_APPROVED_HOLDS"
}

dry_run() {
  require_root
  validate_artifacts
  require_database_state_for_build
  validate_archive_tocs
  note "OK: dry-run aman. $PRODUCTION_DB, $BASELINE_DB, dan $UAT01_DB hanya diverifikasi; $TARGET_DB belum ada."
  note 'Artefak yang akan dipakai (checksum):'
  print_artifact_checksums
  note 'Tidak ada pg_dump baru, koneksi SQL Server, CREATE/DROP/ALTER, atau write database pada mode ini.'
}

new_run_dir() {
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  RUN_DIR="$ARTIFACT_DIR/uat02_rebuild_$stamp"
  umask 077
  # Database tools run under the PostgreSQL OS account so peer
  # authentication does not depend on root's local pg_hba behavior.
  install -d -m 0700 -o postgres -g postgres "$RUN_DIR" \
    || die "Tidak dapat membuat run directory $RUN_DIR"
  print_artifact_checksums > "$RUN_DIR/artifact_sha256.txt"
  printf '%s\n' "$TARGET_DB" > "$RUN_DIR/target_database.txt"
}

target_session_guard() {
  pg_target <<SQL
DO \$\$
BEGIN
  IF current_database() <> '$TARGET_DB' THEN
    RAISE EXCEPTION 'Wrong target database: %', current_database();
  END IF;
  IF current_database() IN ('$PRODUCTION_DB', '$BASELINE_DB', '$UAT01_DB', 'postgres', 'template0', 'template1') THEN
    RAISE EXCEPTION 'Protected database selected: %', current_database();
  END IF;
END
\$\$;
SQL
}

restore_reference_sequences() {
  pg_target <<'SQL'
DO $$
DECLARE
  row record;
  max_value bigint;
BEGIN
  FOR row IN
    SELECT n.nspname AS schema_name, c.relname AS table_name, a.attname AS column_name,
           pg_get_serial_sequence(format('%I.%I', n.nspname, c.relname), a.attname) AS sequence_name
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_attribute a ON a.attrelid = c.oid
     WHERE n.nspname = 'public'
       AND c.relname = ANY (ARRAY[
         'wilayah1','wilayah2','wilayah3','wilayah4','perusahaan','cabang','perusahaan_cabang',
         'departemen','jabatan','fitur','jabatan_akses','sales_tipe','status','tipe_transaksi',
         'modul','fitur_mal','source_modul','customer_tipe','tipe_toko_customer','produk_tipe_harga',
         'master_ppn','produk_satuan','produk_kategori','rute','rute_cabang','armada_tipe'
       ])
       AND a.attnum > 0 AND NOT a.attisdropped
  LOOP
    IF row.sequence_name IS NULL THEN
      CONTINUE;
    END IF;
    EXECUTE format('SELECT max(%I)::bigint FROM %I.%I', row.column_name, row.schema_name, row.table_name)
       INTO max_value;
    IF max_value IS NOT NULL THEN
      PERFORM setval(row.sequence_name::regclass, max_value, true);
    END IF;
  END LOOP;
END
$$;
SQL
}

verify_reference_counts_against_baseline() {
  local table source_count target_count
  for table in "${REFERENCE_TABLES[@]}"; do
    source_count="$(runuser -u postgres -- "$PSQL" -X -v ON_ERROR_STOP=1 -h "$PG_SOCKET" -d "$BASELINE_DB" -Atqc "BEGIN TRANSACTION READ ONLY; SELECT count(*) FROM public.$table; COMMIT;")"
    target_count="$(pg_target -Atqc "BEGIN TRANSACTION READ ONLY; SELECT count(*) FROM public.$table; COMMIT;")"
    [[ "$source_count" == "$target_count" ]] || die "Reference count berbeda pada public.$table: baseline=$source_count target=$target_count"
  done
}

run_pre_extension_dry_run() {
  local report="$RUN_DIR/pre_extension_master_dryrun.json"
  runuser -u postgres -- python3 "$IMPORTER" \
    --dsn "dbname=$TARGET_DB host=$PG_SOCKET user=postgres" \
    --target-database "$TARGET_DB" \
    --policy "$POLICY" \
    --bdm-stage-run-id 1 --tmp-stage-run-id 1 \
    --customer-pricing-tax-policy-json "$CUSTOMER_POLICY" \
    --product-tax-policy-json "$PRODUCT_TAX_POLICY" \
    --sales-policy-json "$SALES_POLICY" \
    --price-policy-json "$PRICE_POLICY" \
    --report-json "$report" > "$RUN_DIR/pre_extension_master_dryrun.stdout.json"

  mapfile -t BASELINE_HASHES < <(python3 - "$report" "$PRIOR_APPROVED_HOLDS" <<'PY'
import json
import re
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
prior = json.load(open(sys.argv[2], encoding='utf-8'))['manifest']
observed = report.get('observed_baseline', {})

def snapshot_identity(stages):
    wanted = ('schema', 'run_id', 'snapshot_label', 'snapshot_sha256', 'manifest_sha256')
    return {
        name: {key: value.get(key) for key in wanted}
        for name, value in sorted((stages or {}).items())
        if isinstance(value, dict)
    }

for key in ('schema_sha256', 'reference_sha256'):
    value = observed.get(key)
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise SystemExit(f'Fingerprint {key} tidak valid dari pre-extension dry-run.')
if observed != prior.get('observed_baseline'):
    raise SystemExit('Fingerprint baseline UAT02 tidak sama dengan evidence master v2; jangan pasang attestation.')
if snapshot_identity(report.get('stages')) != snapshot_identity(prior.get('stages')):
    raise SystemExit('Identitas snapshot freeze UAT02 tidak sama dengan evidence master v2; jangan pasang attestation.')
for source, stage in (report.get('stages') or {}).items():
    if not isinstance(stage, dict) or stage.get('consistency_mode') != 'maintenance_freeze_serializable':
        raise SystemExit(f'Freeze consistency UAT02 tidak tervalidasi untuk {source}; jangan pasang attestation.')
print(observed['schema_sha256'])
print(observed['reference_sha256'])
PY
)
  [[ "${#BASELINE_HASHES[@]}" -eq 2 ]] || die 'Fingerprint pre-extension tidak dapat diperoleh.'
  BASELINE_SCHEMA_SHA="${BASELINE_HASHES[0]}"
  BASELINE_REFERENCE_SHA="${BASELINE_HASHES[1]}"
}

install_registry_extension() {
  runuser -u postgres -- env \
    PGOPTIONS="-c migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target -c migration_clean_bdm_tmp_202609.baseline_schema_sha256=$BASELINE_SCHEMA_SHA -c migration_clean_bdm_tmp_202609.baseline_reference_sha256=$BASELINE_REFERENCE_SHA" \
    "$PSQL" -X -v ON_ERROR_STOP=1 -h "$PG_SOCKET" -d "$TARGET_DB" -f "$EXTEND_REGISTRY_DDL"
}

compare_new_plan_with_prior_evidence() {
  python3 - "$RUN_DIR/master_dryrun_uat02.json" "$RUN_DIR/master_hold_manifest_uat02.pending.json" "$PRIOR_APPROVED_HOLDS" "$PRIOR_APPROVED_DRYRUN" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding='utf-8'))
pending = json.load(open(sys.argv[2], encoding='utf-8'))
prior_holds = json.load(open(sys.argv[3], encoding='utf-8'))
prior_report = json.load(open(sys.argv[4], encoding='utf-8'))
manifest = pending.get('manifest', {})
old_manifest = prior_holds.get('manifest', {})

def snapshot_identity(stages):
    wanted = ('schema', 'run_id', 'snapshot_label', 'snapshot_sha256', 'manifest_sha256')
    return {
        name: {key: value.get(key) for key in wanted}
        for name, value in sorted((stages or {}).items())
        if isinstance(value, dict)
    }

if snapshot_identity(manifest.get('stages')) != snapshot_identity(old_manifest.get('stages')):
    raise SystemExit('Identitas snapshot freeze UAT02 berbeda dari evidence master v2; jangan import master.')
for source, stage in (manifest.get('stages') or {}).items():
    if not isinstance(stage, dict) or stage.get('consistency_mode') != 'maintenance_freeze_serializable':
        raise SystemExit(f'Freeze consistency UAT02 tidak tervalidasi untuk {source}; jangan import master.')
if report.get('target_database') != 'budimas_clean_20260902_v2_uat02':
    raise SystemExit('Dry-run baru menunjuk target yang salah.')
if manifest.get('target_database') != report.get('target_database'):
    raise SystemExit('Pending hold manifest tidak terikat ke target UAT02.')
if pending.get('approval', {}).get('approval_status') != 'pending_review':
    raise SystemExit('Pending hold envelope tidak berada pada state review.')
for key in ('policy_sha256', 'observed_baseline', 'hold_entries_sha256', 'hold_occurrences'):
    if manifest.get(key) != old_manifest.get(key):
        raise SystemExit(f'Evidence UAT02 berbeda dari approval historis pada {key}; jangan import master.')
if report.get('actions') != prior_report.get('actions'):
    raise SystemExit('Rencana tindakan master UAT02 berbeda dari dry-run v2; jangan import master.')
if report.get('holds', {}).get('total') != old_manifest.get('hold_occurrences'):
    raise SystemExit('Jumlah hold UAT02 berbeda dari manifest historis.')
print('OK: policies, snapshot freeze, baseline, action plan, dan exact hold entries sama dengan evidence v2.')
PY
}

build_target() {
  [[ "${I_UNDERSTAND_UAT02_BUILD:-}" == "CREATE-$TARGET_DB-ONLY" ]] || die "Set I_UNDERSTAND_UAT02_BUILD=CREATE-$TARGET_DB-ONLY untuk mode build."
  dry_run
  new_run_dir
  trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "Build berhenti; target parsial dipertahankan untuk audit: %s\\n" "$RUN_DIR" >&2; fi' EXIT

  note "Membuat target baru saja: $TARGET_DB"
  runuser -u postgres -- "$CREATEDB" -h "$PG_SOCKET" --template=template0 "$TARGET_DB"
  target_session_guard
  pg_target -c 'CREATE EXTENSION IF NOT EXISTS plpgsql;'

  note 'Restore schema public dari dump schema-only; tidak ada TABLE DATA public yang direstore.'
  runuser -u postgres -- "$PG_RESTORE" --exit-on-error --single-transaction --no-owner --no-privileges --schema=public --dbname="$TARGET_DB" "$SCHEMA_DUMP"
  target_session_guard

  note 'Restore data referensi exact allow-list saja.'
  runuser -u postgres -- "$PG_RESTORE" --exit-on-error --single-transaction --data-only --no-owner --no-privileges --dbname="$TARGET_DB" "$REFERENCE_DUMP"
  restore_reference_sequences
  verify_reference_counts_against_baseline

  note 'Restore definisi dan data snapshot freeze BDM/TMP saja.'
  runuser -u postgres -- "$PG_RESTORE" --exit-on-error --single-transaction --no-owner --no-privileges --schema="$BDM_STAGE_SCHEMA" --dbname="$TARGET_DB" "$SCHEMA_DUMP"
  runuser -u postgres -- "$PG_RESTORE" --exit-on-error --single-transaction --no-owner --no-privileges --schema="$TMP_STAGE_SCHEMA" --dbname="$TARGET_DB" "$SCHEMA_DUMP"
  runuser -u postgres -- "$PG_RESTORE" --exit-on-error --single-transaction --data-only --no-owner --no-privileges --schema="$BDM_STAGE_SCHEMA" --schema="$TMP_STAGE_SCHEMA" --dbname="$TARGET_DB" "$FREEZE_DUMP"

  note 'Pasang base registry baru; tidak ada registry/attestation yang disalin dari v2.'
  runuser -u postgres -- env PGOPTIONS='-c migration_clean_bdm_tmp_202609.allow_ddl=acknowledge-clean-target' \
    "$PSQL" -X -v ON_ERROR_STOP=1 -h "$PG_SOCKET" -d "$TARGET_DB" -f "$BASE_REGISTRY_DDL"
  run_pre_extension_dry_run
  install_registry_extension

  runuser -u postgres -- python3 "$READINESS_REPORTER" \
    --pg-database "$TARGET_DB" --pg-user postgres --pg-host "$PG_SOCKET" \
    --policy "$POLICY" --output "$RUN_DIR/master_readiness_uat02.json" --fail-if-not-ready > "$RUN_DIR/master_readiness_uat02.stdout.json"

  note 'Jalankan master importer hanya dalam mode dry-run dan buat envelope hold baru milik UAT02.'
  runuser -u postgres -- python3 "$IMPORTER" \
    --dsn "dbname=$TARGET_DB host=$PG_SOCKET user=postgres" \
    --target-database "$TARGET_DB" \
    --policy "$POLICY" \
    --bdm-stage-run-id 1 --tmp-stage-run-id 1 \
    --customer-pricing-tax-policy-json "$CUSTOMER_POLICY" \
    --product-tax-policy-json "$PRODUCT_TAX_POLICY" \
    --sales-policy-json "$SALES_POLICY" \
    --price-policy-json "$PRICE_POLICY" \
    --write-hold-manifest "$RUN_DIR/master_hold_manifest_uat02.pending.json" \
    --report-json "$RUN_DIR/master_dryrun_uat02.json" > "$RUN_DIR/master_dryrun_uat02.stdout.json"
  compare_new_plan_with_prior_evidence

  note "BUILD COMPLETE (master belum ditulis): $RUN_DIR"
  note "Jangan pakai approval envelope v2 secara langsung. Review dan approve envelope baru: $RUN_DIR/master_hold_manifest_uat02.pending.json"
  trap - EXIT
}

preflight_existing_target() {
  require_root
  validate_artifacts
  require_database_state_for_existing_target
  assert_existing_seed_target_state
  verify_reference_counts_against_baseline
  note "OK: preflight read-only UAT02 selesai. Tidak ada database atau artefak yang ditulis."
}

prepare_existing_target() {
  [[ "${I_UNDERSTAND_UAT02_PREPARE:-}" == "PREPARE-$TARGET_DB-ONLY" ]] || die "Set I_UNDERSTAND_UAT02_PREPARE=PREPARE-$TARGET_DB-ONLY untuk memasang extension pre-master."
  preflight_existing_target
  new_run_dir
  trap 'rc=$?; if [[ $rc -ne 0 ]]; then printf "Prepare berhenti; target dipertahankan untuk audit: %s\\n" "$RUN_DIR" >&2; fi' EXIT

  run_pre_extension_dry_run
  install_registry_extension
  runuser -u postgres -- python3 "$READINESS_REPORTER" \
    --pg-database "$TARGET_DB" --pg-user postgres --pg-host "$PG_SOCKET" \
    --policy "$POLICY" --output "$RUN_DIR/master_readiness_uat02.json" --fail-if-not-ready > "$RUN_DIR/master_readiness_uat02.stdout.json"
  runuser -u postgres -- python3 "$IMPORTER" \
    --dsn "dbname=$TARGET_DB host=$PG_SOCKET user=postgres" \
    --target-database "$TARGET_DB" \
    --policy "$POLICY" \
    --bdm-stage-run-id 1 --tmp-stage-run-id 1 \
    --customer-pricing-tax-policy-json "$CUSTOMER_POLICY" \
    --product-tax-policy-json "$PRODUCT_TAX_POLICY" \
    --sales-policy-json "$SALES_POLICY" \
    --price-policy-json "$PRICE_POLICY" \
    --write-hold-manifest "$RUN_DIR/master_hold_manifest_uat02.pending.json" \
    --report-json "$RUN_DIR/master_dryrun_uat02.json" > "$RUN_DIR/master_dryrun_uat02.stdout.json"
  compare_new_plan_with_prior_evidence
  note "PREPARE COMPLETE (master belum ditulis): $RUN_DIR"
  note "Approval historis v2 hanya pembanding. Review/approve envelope baru: $RUN_DIR/master_hold_manifest_uat02.pending.json"
  trap - EXIT
}

require_run_dir() {
  RUN_DIR="${UAT02_RUN_DIR:-}"
  [[ -n "$RUN_DIR" ]] || die 'UAT02_RUN_DIR wajib menunjuk run directory hasil --build-target.'
  [[ -d "$RUN_DIR" ]] || die "UAT02_RUN_DIR tidak ditemukan: $RUN_DIR"
  case "$RUN_DIR" in
    "$ARTIFACT_DIR"/uat02_rebuild_*) ;;
    *) die 'UAT02_RUN_DIR harus berada di artifact directory uat02_rebuild_*.' ;;
  esac
  require_file "$RUN_DIR/master_dryrun_uat02.json"
  require_file "$RUN_DIR/master_hold_manifest_uat02.pending.json"
}

verify_target() {
  require_root
  require_database_state_for_existing_target
  require_run_dir
  local report="$RUN_DIR/master_post_import_verify.json"
  runuser -u postgres -- python3 "$IMPORTER" \
    --dsn "dbname=$TARGET_DB host=$PG_SOCKET user=postgres" \
    --target-database "$TARGET_DB" \
    --policy "$POLICY" \
    --bdm-stage-run-id 1 --tmp-stage-run-id 1 \
    --customer-pricing-tax-policy-json "$CUSTOMER_POLICY" \
    --product-tax-policy-json "$PRODUCT_TAX_POLICY" \
    --sales-policy-json "$SALES_POLICY" \
    --price-policy-json "$PRICE_POLICY" \
    --report-json "$report" > "$RUN_DIR/master_post_import_verify.stdout.json"

  mapfile -t VERIFY_HASHES < <(python3 - "$report" <<'PY'
import json
import re
import sys
r=json.load(open(sys.argv[1], encoding='utf-8'))
if r.get('target_database') != 'budimas_clean_20260902_v2_uat02': raise SystemExit('Target verify salah.')
if r.get('structural_blockers'): raise SystemExit('Importer read-only menemukan structural blocker; lihat report.')
o=r.get('observed_baseline', {})
for k in ('schema_sha256','reference_sha256'):
  if not isinstance(o.get(k), str) or not re.fullmatch(r'[0-9a-f]{64}', o[k]): raise SystemExit('Fingerprint verify tidak valid.')
print(o['schema_sha256']); print(o['reference_sha256'])
PY
)
  [[ "${#VERIFY_HASHES[@]}" -eq 2 ]] || die 'Fingerprint verify tidak dapat dibaca.'

  pg_target -v expected_schema_sha="${VERIFY_HASHES[0]}" -v expected_reference_sha="${VERIFY_HASHES[1]}" -At -F $'\t' <<'SQL' > "$RUN_DIR/master_post_import_invariants.tsv"
SELECT 'attestation_exactly_one', count(*), 1 FROM migration_clean_bdm_tmp_202609.clean_target_attestation;
SELECT 'attestation_identity', CASE WHEN EXISTS (SELECT 1 FROM migration_clean_bdm_tmp_202609.clean_target_attestation WHERE target_database = current_database() AND target_kind = 'bluegreen_clean') THEN 1 ELSE 0 END, 1;
SELECT 'attestation_schema', CASE WHEN EXISTS (SELECT 1 FROM migration_clean_bdm_tmp_202609.clean_target_attestation WHERE baseline_schema_sha256 = :'expected_schema_sha') THEN 1 ELSE 0 END, 1;
SELECT 'attestation_reference', CASE WHEN EXISTS (SELECT 1 FROM migration_clean_bdm_tmp_202609.clean_target_attestation WHERE baseline_reference_sha256 = :'expected_reference_sha') THEN 1 ELSE 0 END, 1;
SELECT 'source_context', count(*), 2 FROM migration_clean_bdm_tmp_202609.source_context;
SELECT 'master_import_committed', count(*), 1 FROM migration_clean_bdm_tmp_202609.import_run WHERE phase='master' AND status='committed';
SELECT 'public.principal', count(*), 63 FROM public.principal;
SELECT 'public.customer', count(*), 40946 FROM public.customer;
SELECT 'public.sales', count(*), 447 FROM public.sales;
SELECT 'public.sales_detail', count(*), 447 FROM public.sales_detail;
SELECT 'public.sales_principal_assignment', count(*), 447 FROM public.sales_principal_assignment;
SELECT 'public.produk', count(*), 20502 FROM public.produk;
SELECT 'public.produk_uom', count(*), 39433 FROM public.produk_uom;
SELECT 'public.produk_harga_jual', count(*), 102510 FROM public.produk_harga_jual;
SELECT 'public.plafon', count(*), 26214 FROM public.plafon;
SELECT 'registry.principal_source_map', count(*), 63 FROM migration_clean_bdm_tmp_202609.principal_source_map;
SELECT 'registry.customer_source_map', count(*), 43208 FROM migration_clean_bdm_tmp_202609.customer_source_map;
SELECT 'registry.customer_shared_exact', count(*) - count(DISTINCT id_customer), 2262 FROM migration_clean_bdm_tmp_202609.customer_source_map;
SELECT 'registry.sales_source_map', count(*), 447 FROM migration_clean_bdm_tmp_202609.sales_source_map;
SELECT 'registry.product_source_map', count(*), 20502 FROM migration_clean_bdm_tmp_202609.product_source_map;
SELECT 'registry.product_uom_source_map', count(*), 39433 FROM migration_clean_bdm_tmp_202609.product_uom_source_map;
SELECT 'registry.product_price_source_map', count(*), 102510 FROM migration_clean_bdm_tmp_202609.product_price_source_map;
SELECT 'registry.plafon_source_map', count(*), 26214 FROM migration_clean_bdm_tmp_202609.plafon_source_map;
SELECT 'registry.master_holds', count(*), 11930 FROM migration_clean_bdm_tmp_202609.import_hold WHERE phase='master';
SELECT 'orphan.customer_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.customer_source_map m LEFT JOIN public.customer t ON t.id=m.id_customer WHERE t.id IS NULL;
SELECT 'orphan.principal_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.principal_source_map m LEFT JOIN public.principal t ON t.id=m.id_principal WHERE t.id IS NULL;
SELECT 'orphan.sales_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.sales_source_map m LEFT JOIN public.sales t ON t.id=m.id_sales WHERE t.id IS NULL;
SELECT 'orphan.product_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.product_source_map m LEFT JOIN public.produk t ON t.id=m.id_produk WHERE t.id IS NULL;
SELECT 'orphan.uom_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.product_uom_source_map m LEFT JOIN public.produk_uom t ON t.id=m.id_produk_uom WHERE t.id IS NULL;
SELECT 'orphan.price_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.product_price_source_map m LEFT JOIN public.produk_harga_jual t ON t.id=m.id_produk_harga_jual WHERE t.id IS NULL;
SELECT 'orphan.plafon_map', count(*), 0 FROM migration_clean_bdm_tmp_202609.plafon_source_map m LEFT JOIN public.plafon t ON t.id=m.id_plafon WHERE t.id IS NULL;
SELECT 'transactions.sales_order', count(*), 0 FROM public.sales_order;
SELECT 'transactions.sales_order_detail', count(*), 0 FROM public.sales_order_detail;
SELECT 'transactions.faktur', count(*), 0 FROM public.faktur;
SELECT 'transactions.faktur_detail', count(*), 0 FROM public.faktur_detail;
SQL
  python3 - "$RUN_DIR/master_post_import_invariants.tsv" "$report" "$PRIOR_APPROVED_DRYRUN" "$RUN_DIR/master_hold_manifest_uat02.pending.json" <<'PY'
import json
import sys
from pathlib import Path

bad=[]
for line in Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    name, actual, expected = line.split('\t')
    if int(actual) != int(expected): bad.append(f'{name}: actual={actual} expected={expected}')
report=json.load(open(sys.argv[2], encoding='utf-8'))
prior=json.load(open(sys.argv[3], encoding='utf-8'))
pending=json.load(open(sys.argv[4], encoding='utf-8'))['manifest']
if report.get('actions') != prior.get('actions'): bad.append('post-import action plan berbeda dari evidence v2')
if report.get('holds', {}).get('total') != pending.get('hold_occurrences'): bad.append('post-import hold count berbeda dari hold envelope UAT02')
if bad: raise SystemExit('Verifikasi gagal:\n' + '\n'.join(bad))
print('OK: count master, maps, orphan check, attestation, hold, dan transaksi kosong tervalidasi.')
PY
  note "VERIFY COMPLETE: $RUN_DIR/master_post_import_invariants.tsv"
}

apply_master() {
  [[ "${I_UNDERSTAND_UAT02_MASTER_APPLY:-}" == "APPLY-$TARGET_DB-ONLY" ]] || die "Set I_UNDERSTAND_UAT02_MASTER_APPLY=APPLY-$TARGET_DB-ONLY untuk import master."
  require_root
  require_database_state_for_existing_target
  require_run_dir
  validate_artifacts
  local approved_holds="${UAT02_APPROVED_HOLDS:-}"
  [[ -n "$approved_holds" ]] || die 'UAT02_APPROVED_HOLDS wajib menunjuk envelope UAT02 yang baru dan diset approved_skip.'
  require_file "$approved_holds"

  mapfile -t APPLY_VALUES < <(python3 - "$RUN_DIR/master_dryrun_uat02.json" "$approved_holds" <<'PY'
import json
import re
import sys

report=json.load(open(sys.argv[1], encoding='utf-8'))
approval=json.load(open(sys.argv[2], encoding='utf-8'))
manifest=approval.get('manifest', {})
decision=approval.get('approval', {})
if manifest.get('target_database') != 'budimas_clean_20260902_v2_uat02': raise SystemExit('Approval bukan milik target UAT02.')
if decision.get('approval_status') != 'approved_skip': raise SystemExit('Approval UAT02 belum approved_skip.')
if decision.get('approved_manifest_sha256') != manifest.get('manifest_sha256'): raise SystemExit('Approval SHA tidak cocok.')
if manifest.get('manifest_sha256') != json.load(open(sys.argv[1].replace('master_dryrun_uat02.json','master_hold_manifest_uat02.pending.json'), encoding='utf-8')).get('manifest',{}).get('manifest_sha256'):
    raise SystemExit('Inner manifest UAT02 diubah; gunakan pending manifest exact dari build.')
for key in ('schema_sha256','reference_sha256'):
    value=report.get('observed_baseline',{}).get(key)
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}', value): raise SystemExit('Fingerprint dry-run tidak valid.')
plan=report.get('plan_sha256')
sha=manifest.get('manifest_sha256')
if not isinstance(plan,str) or not re.fullmatch(r'[0-9a-f]{64}',plan): raise SystemExit('Plan SHA tidak valid.')
if not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha): raise SystemExit('Manifest SHA tidak valid.')
print(report['observed_baseline']['schema_sha256']); print(report['observed_baseline']['reference_sha256']); print(plan); print(sha)
PY
)
  [[ "${#APPLY_VALUES[@]}" -eq 4 ]] || die 'Tidak dapat membaca approval/apply fingerprint UAT02.'

  runuser -u postgres -- python3 "$IMPORTER" \
    --dsn "dbname=$TARGET_DB host=$PG_SOCKET user=postgres" \
    --target-database "$TARGET_DB" \
    --policy "$POLICY" \
    --bdm-stage-run-id 1 --tmp-stage-run-id 1 \
    --customer-pricing-tax-policy-json "$CUSTOMER_POLICY" \
    --product-tax-policy-json "$PRODUCT_TAX_POLICY" \
    --sales-policy-json "$SALES_POLICY" \
    --price-policy-json "$PRICE_POLICY" \
    --apply --import-key "$EXPECTED_IMPORT_KEY" \
    --baseline-schema-sha256 "${APPLY_VALUES[0]}" \
    --baseline-reference-sha256 "${APPLY_VALUES[1]}" \
    --reviewed-plan-sha256 "${APPLY_VALUES[2]}" \
    --approved-hold-manifest-json "$approved_holds" \
    --approved-hold-manifest-sha256 "${APPLY_VALUES[3]}" \
    --acknowledge-approved-holds > "$RUN_DIR/master_apply_uat02.json"
  verify_target
}

case "$MODE" in
  --dry-run) dry_run ;;
  --build-target) build_target ;;
  --preflight-existing-target) preflight_existing_target ;;
  --prepare-existing-target) prepare_existing_target ;;
  --apply-master) apply_master ;;
  --verify) verify_target ;;
esac
