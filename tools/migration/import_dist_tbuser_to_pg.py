#!/usr/bin/env python
"""
Import legacy dbo.TBUser accounts from exported SQL Server DIST CSV files.

The script is intentionally conservative:
- imports active TBUser rows only,
- merges repeated UserId values across source servers into one application user,
- updates only legacy users (email @legacy.local) when a username already exists,
- keeps existing sales-linked users as Sales role,
- stores combined company/branch scope in users.id_perusahaan_list/id_cabang_list.

Default mode is dry-run. Use --apply to commit.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import bcrypt
from sqlalchemy import text


try:
    from apps.conn import db
except Exception:  # pragma: no cover - fallback for local env usage
    from sqlalchemy import create_engine

    def _pg_url() -> str:
        return (
            f"postgresql+pg8000://{os.getenv('DB_USER', 'postgres')}:"
            f"{os.getenv('DB_PASS', '')}@{os.getenv('DB_HOST', '127.0.0.1')}:"
            f"{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'budimas-dev')}"
        )

    db = create_engine(_pg_url())


SOURCE_SCOPE = {
    "5_243": {"source_name": "sqlserver_dist_5_243", "id_perusahaan": 2, "id_cabang": 5},
    "5_242": {"source_name": "sqlserver_dist_5_242", "id_perusahaan": 1, "id_cabang": 7},
    "2_216": {"source_name": "sqlserver_dist_2_216", "id_perusahaan": 2, "id_cabang": 6},
    "2_215": {"source_name": "sqlserver_dist_2_215", "id_perusahaan": 1, "id_cabang": 6},
}

ACTIVE_VALUES = {"1", "Y", "TRUE", "YA", "AKTIF", "ACTIVE"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def clip(value: Any, max_len: int) -> str:
    return clean(value)[:max_len]


def active(value: Any) -> bool:
    return clean(value).upper() in ACTIVE_VALUES


def normalize_key(value: Any) -> str:
    return re.sub(r"\s+", "", clean(value)).upper()


def email_for(username: str) -> str:
    safe = re.sub(r"[^a-z0-9._-]+", ".", username.lower()).strip(".")
    return f"{safe or 'legacy-user'}@legacy.local"[:100]


def hash_password(password: str) -> str:
    return bcrypt.hashpw((password or "budimas").encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def infer_jabatan_id(user_id: str, names: list[str], user_man: bool) -> int:
    haystack = " ".join([user_id, *names]).lower()
    if user_man:
        return 11  # SUPER USER
    keyword_map = (
        (("spv", "supervisor", "spvs"), 7),
        (("gudang", "gdg"), 9),
        (("faktur", "fkt"), 21),
        (("pajak", "pjk", "accounting", "account", "akt", "acc"), 17),
        (("hutang",), 18),
        (("klaim", "klm"), 19),
        (("kasir",), 16),
        (("tagihan", "piutang"), 15),
        (("driver", "drv"), 6),
        (("picking", "pick"), 12),
        (("shipping", "ship", "delivery", "deliver"), 13),
    )
    for keywords, jabatan_id in keyword_map:
        if any(keyword in haystack for keyword in keywords):
            return jabatan_id
    return 5  # ADMIN CABANG


def load_rows(csv_paths: list[Path]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    stats = {
        "csv_files": len(csv_paths),
        "source_rows": 0,
        "active_rows": 0,
        "inactive_rows": 0,
        "skipped_no_userid": 0,
        "unknown_source_rows": 0,
        "by_source": defaultdict(lambda: {"rows": 0, "active": 0}),
    }

    for path in csv_paths:
        source_key = path.stem.replace("tbuser_", "")
        scope = SOURCE_SCOPE.get(source_key)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                stats["source_rows"] += 1
                stats["by_source"][source_key]["rows"] += 1
                if not scope:
                    stats["unknown_source_rows"] += 1
                    continue
                user_id_raw = clean(row.get("user_id"))
                user_key = normalize_key(user_id_raw)
                if not user_key:
                    stats["skipped_no_userid"] += 1
                    continue
                if not active(row.get("active")):
                    stats["inactive_rows"] += 1
                    continue
                stats["active_rows"] += 1
                stats["by_source"][source_key]["active"] += 1

                item = grouped.setdefault(
                    user_key,
                    {
                        "user_key": user_key,
                        "username": user_id_raw[:25],
                        "names": [],
                        "user_man": False,
                        "sources": set(),
                        "company_ids": set(),
                        "branch_ids": set(),
                    },
                )
                name = clean(row.get("user_name")) or clean(row.get("operator_name"))
                if name and name not in item["names"]:
                    item["names"].append(name)
                item["user_man"] = item["user_man"] or clean(row.get("user_man")).upper() == "Y"
                item["sources"].add(source_key)
                item["company_ids"].add(int(scope["id_perusahaan"]))
                item["branch_ids"].add(int(scope["id_cabang"]))

    stats["unique_active_users"] = len(grouped)
    stats["by_source"] = dict(stats["by_source"])
    return grouped, stats


def joined_ids(values: set[int]) -> str:
    return ",".join(str(value) for value in sorted(values))


def create_backup(conn) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup_migration"))
    conn.execute(
        text(f"CREATE TABLE backup_migration.users_before_tbuser_{stamp} AS TABLE public.users")
    )
    return stamp


def sync_sequence(conn) -> None:
    sequence_name = conn.execute(text("SELECT pg_get_serial_sequence('users', 'id')")).scalar()
    if sequence_name:
        conn.execute(
            text("SELECT setval(:sequence_name, COALESCE((SELECT MAX(id) FROM users), 0) + 1, false)"),
            {"sequence_name": sequence_name},
        )


def find_existing_user(conn, username: str) -> dict[str, Any] | None:
    rows = conn.execute(
        text(
            """
            SELECT u.id, u.username, u.email, u.id_jabatan, u.id_cabang, u.id_perusahaan,
                   u.id_cabang_list, u.id_perusahaan_list,
                   EXISTS (SELECT 1 FROM sales s WHERE s.id_user = u.id) AS linked_sales
            FROM users u
            WHERE lower(u.username) = lower(:username)
            ORDER BY CASE WHEN lower(COALESCE(u.email, '')) LIKE '%@legacy.local' THEN 0 ELSE 1 END,
                     u.id
            """
        ),
        {"username": username},
    ).mappings().all()
    if not rows:
        return None
    legacy = [dict(row) for row in rows if clean(row.get("email")).lower().endswith("@legacy.local")]
    if legacy:
        return legacy[0]
    return {"non_legacy_conflict": True, **dict(rows[0])}


def first_existing_scope(existing_value: Any, fallback: Any) -> set[int]:
    result: set[int] = set()
    for raw in clean(existing_value).split(","):
        raw = raw.strip()
        if raw.isdigit():
            result.add(int(raw))
    if not result and fallback not in (None, ""):
        try:
            result.add(int(fallback))
        except (TypeError, ValueError):
            pass
    return result


def import_users(grouped: dict[str, dict[str, Any]], default_password: str, apply: bool) -> dict[str, Any]:
    stats = {
        "mode": "APPLIED" if apply else "DRY_RUN_ROLLBACK",
        "backup_stamp": None,
        "inserted": 0,
        "updated": 0,
        "skipped_non_legacy_conflict": 0,
        "kept_sales_role": 0,
        "by_jabatan": defaultdict(int),
        "by_scope": defaultdict(int),
    }

    conn = db.connect() if hasattr(db, "connect") else db.engine.connect()
    trans = conn.begin()
    try:
        if apply:
            stats["backup_stamp"] = create_backup(conn)
        sync_sequence(conn)
        default_hash = hash_password(default_password)

        for user in grouped.values():
            username = clip(user["username"], 25)
            if not username:
                continue
            company_ids = set(user["company_ids"])
            branch_ids = set(user["branch_ids"])
            jabatan_id = infer_jabatan_id(username, user["names"], user["user_man"])
            nama = clip(user["names"][0] if user["names"] else username, 40)
            primary_company = sorted(company_ids)[0] if company_ids else None
            primary_branch = sorted(branch_ids)[0] if branch_ids else None
            existing = find_existing_user(conn, username)

            if existing and existing.get("non_legacy_conflict"):
                stats["skipped_non_legacy_conflict"] += 1
                continue

            if existing:
                merged_company_ids = company_ids | first_existing_scope(existing.get("id_perusahaan_list"), existing.get("id_perusahaan"))
                merged_branch_ids = branch_ids | first_existing_scope(existing.get("id_cabang_list"), existing.get("id_cabang"))
                update_jabatan_id = jabatan_id
                if existing.get("linked_sales") or int(existing.get("id_jabatan") or 0) == 4:
                    update_jabatan_id = 4
                    stats["kept_sales_role"] += 1
                conn.execute(
                    text(
                        """
                        UPDATE users
                        SET nama = :nama,
                            email = COALESCE(NULLIF(email, ''), :email),
                            id_jabatan = :id_jabatan,
                            id_cabang = COALESCE(id_cabang, :id_cabang),
                            id_perusahaan = COALESCE(id_perusahaan, :id_perusahaan),
                            id_cabang_list = :id_cabang_list,
                            id_perusahaan_list = :id_perusahaan_list
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": existing["id"],
                        "nama": nama,
                        "email": email_for(username),
                        "id_jabatan": update_jabatan_id,
                        "id_cabang": primary_branch,
                        "id_perusahaan": primary_company,
                        "id_cabang_list": joined_ids(merged_branch_ids),
                        "id_perusahaan_list": joined_ids(merged_company_ids),
                    },
                )
                stats["updated"] += 1
                stats["by_jabatan"][str(update_jabatan_id)] += 1
                stats["by_scope"][f"P{joined_ids(merged_company_ids)}|C{joined_ids(merged_branch_ids)}"] += 1
                continue

            conn.execute(
                text(
                    """
                    INSERT INTO users (
                        nama, email, telepon, no_rekening, npwp, nama_wp, alamat_wp,
                        id_jabatan, id_cabang, id_perusahaan, id_cabang_list, id_perusahaan_list,
                        username, password, nik, alamat, tanggal_lahir
                    )
                    VALUES (
                        :nama, :email, '', NULL, NULL, NULL, NULL,
                        :id_jabatan, :id_cabang, :id_perusahaan, :id_cabang_list, :id_perusahaan_list,
                        :username, :password, NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "nama": nama,
                    "email": email_for(username),
                    "id_jabatan": jabatan_id,
                    "id_cabang": primary_branch,
                    "id_perusahaan": primary_company,
                    "id_cabang_list": joined_ids(branch_ids),
                    "id_perusahaan_list": joined_ids(company_ids),
                    "username": username,
                    "password": default_hash,
                },
            )
            stats["inserted"] += 1
            stats["by_jabatan"][str(jabatan_id)] += 1
            stats["by_scope"][f"P{joined_ids(company_ids)}|C{joined_ids(branch_ids)}"] += 1

        if apply:
            trans.commit()
        else:
            trans.rollback()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()

    stats["by_jabatan"] = dict(stats["by_jabatan"])
    stats["by_scope"] = dict(stats["by_scope"])
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--default-password", default=os.getenv("TBUSER_DEFAULT_PASSWORD", "budimas"))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    csv_paths = sorted(Path(args.input_dir).glob("tbuser_*.csv"))
    grouped, load_stats = load_rows(csv_paths)
    import_stats = import_users(grouped, args.default_password, args.apply)
    print(json.dumps({"load": load_stats, "import": import_stats}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
