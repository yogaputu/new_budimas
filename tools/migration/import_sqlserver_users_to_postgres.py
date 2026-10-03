#!/usr/bin/env python
"""
Import user lama dari export dbo.TBUser SQL Server ke PostgreSQL.

Input CSV dibuat dari tools/migration/export_sqlserver_scope.ps1 style export atau
query langsung yang menghasilkan kolom:
user_id,user_name,password_plain,role_name,user_man,active,user_edit,user_delete,spesial,operator_name

Default adalah dry-run. Tambahkan --apply untuk commit.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

import bcrypt
from sqlalchemy import create_engine, text


def clean(value: Any) -> str:
    return str(value or "").strip()


def clip(value: Any, max_len: int) -> str:
    return clean(value)[:max_len]


def pg_url() -> str:
    return (
        f"postgresql+pg8000://{os.getenv('DB_USER', 'postgres')}:"
        f"{os.getenv('DB_PASS', '')}@{os.getenv('DB_HOST', '127.0.0.1')}:"
        f"{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'budimas-dev')}"
    )


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bcrypt_hash(password: str) -> str:
    plain = password or "budimas"
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def infer_jabatan_id(row: dict[str, str], default_jabatan_id: int) -> int:
    role = clean(row.get("role_name")).lower()
    name = clean(row.get("user_name")).lower()

    if role == "sa" or clean(row.get("user_man")).upper() == "Y":
        return 11  # SUPER USER
    if role == "operator":
        return 5  # ADMIN CABANG

    keyword_map = (
        (("spv", "supervisor"), 7),
        (("gdg", "gudang"), 9),
        (("fkt", "faktur"), 21),
        (("pjk", "pajak", "accounting", "akun"), 17),
        (("hutang",), 18),
        (("klaim",), 19),
        (("kasir",), 16),
        (("driver", "drv"), 6),
        (("helper",), 23),
        (("picking", "pick"), 12),
        (("shipping", "delivery", "deliver"), 13),
        (("piutang",), 15),
    )
    for keywords, jabatan_id in keyword_map:
        if any(keyword in name for keyword in keywords):
            return jabatan_id

    return default_jabatan_id


def sync_sequence(conn) -> None:
    sequence_name = conn.execute(
        text("SELECT pg_get_serial_sequence('users', 'id')")
    ).scalar()
    if sequence_name:
        conn.execute(
            text("SELECT setval(:sequence_name, COALESCE((SELECT MAX(id) FROM users), 0) + 1, false)"),
            {"sequence_name": sequence_name},
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=".tmp_audit/sqlserver_users/tbuser.csv")
    parser.add_argument("--id-cabang", type=int, default=5)
    parser.add_argument("--id-perusahaan", type=int, default=1)
    parser.add_argument("--default-jabatan-id", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = load_csv(Path(args.input))
    engine = create_engine(pg_url())
    stats = {
        "source_rows": len(rows),
        "inserted": 0,
        "updated": 0,
        "skipped_no_username": 0,
        "hashed_passwords": 0,
        "inactive_source_rows": 0,
        "by_jabatan": {},
    }

    conn = engine.connect()
    trans = conn.begin()
    try:
        sync_sequence(conn)

        for row in rows:
            username = clip(row.get("user_id"), 25)
            if not username:
                stats["skipped_no_username"] += 1
                continue

            active = clean(row.get("active"))
            if active == "0":
                stats["inactive_source_rows"] += 1

            jabatan_id = infer_jabatan_id(row, args.default_jabatan_id)
            stats["by_jabatan"][str(jabatan_id)] = stats["by_jabatan"].get(str(jabatan_id), 0) + 1

            password = bcrypt_hash(clean(row.get("password_plain")))
            stats["hashed_passwords"] += 1

            payload = {
                "nama": clip(row.get("user_name") or username, 40),
                "email": f"{username.lower()}@legacy.local"[:100],
                "telepon": "",
                "no_rekening": None,
                "npwp": None,
                "nama_wp": None,
                "alamat_wp": None,
                "id_jabatan": jabatan_id,
                "id_cabang": args.id_cabang,
                "username": username,
                "password": password,
                "nik": None,
                "alamat": None,
                "tanggal_lahir": None,
                "id_perusahaan": args.id_perusahaan,
            }

            existing = conn.execute(
                text(
                    """
                    SELECT u.id,
                           EXISTS (SELECT 1 FROM sales s WHERE s.id_user = u.id) AS linked_sales
                    FROM users u
                    WHERE lower(u.username) = lower(:username)
                    LIMIT 1
                    """
                ),
                {"username": username},
            ).mappings().first()

            if existing:
                update_payload = dict(payload)
                if existing.get("linked_sales"):
                    update_payload["id_jabatan"] = 4
                conn.execute(
                    text(
                        """
                        UPDATE users
                        SET nama = :nama,
                            email = :email,
                            telepon = :telepon,
                            id_jabatan = :id_jabatan,
                            id_cabang = :id_cabang,
                            id_perusahaan = :id_perusahaan,
                            password = :password
                        WHERE id = :id
                        """
                    ),
                    {**update_payload, "id": existing["id"]},
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO users (
                          nama, email, telepon, no_rekening, npwp, nama_wp, alamat_wp,
                          id_jabatan, id_cabang, username, password, nik, alamat,
                          tanggal_lahir, id_perusahaan
                        )
                        VALUES (
                          :nama, :email, :telepon, :no_rekening, :npwp, :nama_wp, :alamat_wp,
                          :id_jabatan, :id_cabang, :username, :password, :nik, :alamat,
                          :tanggal_lahir, :id_perusahaan
                        )
                        """
                    ),
                    payload,
                )
                stats["inserted"] += 1

        if not args.apply:
            trans.rollback()
        else:
            trans.commit()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()

    print(json.dumps({"mode": "APPLIED" if args.apply else "DRY_RUN_ROLLBACK", "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
