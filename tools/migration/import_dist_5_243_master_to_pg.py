#!/usr/bin/env python3
"""
Import master data exported from SQL Server DIST (192.168.5.243) into Budimas PostgreSQL.

Run this script from the API project root on the server so it can import apps.conn.db.
Default mode is dry-run. Pass --apply to commit changes and create backup tables first.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from apps.conn import db


DEFAULT_SOURCE_NAME = "sqlserver_dist_5_243"
CUSTOMER_MAPPING_SOURCE = "sales_order_import"
DEFAULT_COMPANY_ID = 2
DEFAULT_BRANCH_BY_AREA = {
    "KLT": 7,
    "WNG": 6,
}
DEFAULT_BRANCH_ID = 5
BACKUP_TABLES = (
    "principal",
    "produk",
    "produk_brand",
    "produk_kategori",
    "produk_subbrand",
    "produk_uom",
    "produk_harga_jual",
    "produk_external_mapping",
    "customer",
    "customer_external_mapping",
    "users",
    "sales",
    "sales_detail",
    "sales_principal_assignment",
    "plafon",
)


def clean(value: Any, limit: int | None = None) -> str:
    result = "" if value is None else str(value).strip()
    return result[:limit] if limit else result


def norm(value: Any) -> str:
    return clean(value).upper()


def as_bool(value: Any) -> bool:
    return norm(value) not in {"0", "N", "NO", "FALSE", "TIDAK"}


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = clean(value)
        if not raw:
            return default
        return float(raw.replace(",", "."))
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        raw = clean(value)
        if not raw:
            return default
        return int(round(float(raw.replace(",", "."))))
    except (TypeError, ValueError):
        return default


def load_csv(input_dir: Path, name: str) -> list[dict[str, str]]:
    path = input_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing export file: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_branch_map(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in clean(value).split(","):
        if not item.strip():
            continue
        if ":" not in item:
            raise ValueError(f"Invalid branch map item: {item}")
        key, branch_id = item.split(":", 1)
        parsed_id = as_int(branch_id)
        if not key.strip() or not parsed_id:
            raise ValueError(f"Invalid branch map item: {item}")
        result[norm(key)] = parsed_id
    return result


def branch_id_from_area(kode_area: Any, branch_map: dict[str, int], default_branch_id: int) -> int:
    return branch_map.get(norm(kode_area), default_branch_id)


def append_csv_id(current: Any, new_id: int) -> str:
    values: list[str] = []
    for item in clean(current).split(","):
        item = item.strip()
        if item and item not in values:
            values.append(item)
    new_value = str(new_id)
    if new_value not in values:
        values.append(new_value)
    return ",".join(values)


class DistMasterImporter:
    def __init__(self, conn, args):
        self.conn = conn
        self.args = args
        self.source_name = args.source_name
        self.target_company_id = args.company_id
        self.branch_map = parse_branch_map(args.branch_map)
        self.default_branch_id = args.default_branch_id
        self.branch_ids_csv = ",".join(
            str(branch_id)
            for branch_id in sorted({self.default_branch_id, *self.branch_map.values()})
        )
        self.principal_by_code: dict[str, int] = {}
        self.customer_by_code: dict[str, int] = {}
        self.sales_by_code: dict[str, dict[str, int]] = {}
        self.product_by_code: dict[str, int] = {}
        self.brand_by_name: dict[str, int] = {}
        self.category_by_name: dict[str, int] = {}
        self.subbrand_by_key: dict[str, int] = {}
        self.stats: dict[str, int] = {
            "principal_inserted": 0,
            "principal_updated": 0,
            "customer_inserted": 0,
            "customer_updated": 0,
            "customer_mapping_upserted": 0,
            "sales_inserted": 0,
            "sales_existing": 0,
            "sales_assignment_upserted": 0,
            "brand_inserted": 0,
            "category_inserted": 0,
            "subbrand_inserted": 0,
            "product_inserted": 0,
            "product_updated": 0,
            "product_mapping_upserted": 0,
            "product_mapping_exact_corrected": 0,
            "uom_upserted": 0,
            "price_upserted": 0,
            "plafon_inserted": 0,
            "plafon_updated": 0,
            "plafon_skipped_missing_customer": 0,
            "plafon_skipped_missing_principal": 0,
            "plafon_skipped_missing_sales": 0,
        }

    def scalar(self, sql: str, params: dict[str, Any] | None = None) -> Any:
        return self.conn.execute(text(sql), params or {}).scalar()

    def row(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        result = self.conn.execute(text(sql), params or {}).mappings().first()
        return dict(result) if result else None

    def rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return [dict(row) for row in self.conn.execute(text(sql), params or {}).mappings()]

    def sync_sequences(self) -> None:
        for table_name, column_name in (
            ("principal", "id"),
            ("produk", "id"),
            ("produk_brand", "id"),
            ("produk_kategori", "id"),
            ("produk_subbrand", "id"),
            ("produk_uom", "id"),
            ("produk_harga_jual", "id"),
            ("produk_external_mapping", "id"),
            ("customer", "id"),
            ("customer_external_mapping", "id"),
            ("users", "id"),
            ("sales", "id"),
            ("sales_detail", "id"),
            ("sales_principal_assignment", "id"),
            ("plafon", "id"),
        ):
            sequence_name = self.scalar(
                "SELECT pg_get_serial_sequence(:table_name, :column_name)",
                {"table_name": table_name, "column_name": column_name},
            )
            if not sequence_name:
                continue
            self.conn.execute(
                text(
                    f"""
                    SELECT setval(
                        CAST(:sequence_name AS regclass),
                        COALESCE((SELECT MAX({column_name}) FROM {table_name}), 0) + 1,
                        false
                    )
                    """
                ),
                {"sequence_name": sequence_name},
            )

    def create_backups(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.conn.execute(text("CREATE SCHEMA IF NOT EXISTS backup_migration"))
        for table_name in BACKUP_TABLES:
            backup_name = f"{table_name}_{stamp}"
            self.conn.execute(
                text(f'CREATE TABLE backup_migration."{backup_name}" AS TABLE public."{table_name}"')
            )
        return stamp

    def load_existing_maps(self) -> None:
        for row in self.rows(
            """
            SELECT id, kode
            FROM principal
            WHERE id_perusahaan = :id_perusahaan AND NULLIF(TRIM(kode), '') IS NOT NULL
            ORDER BY id
            """,
            {"id_perusahaan": self.target_company_id},
        ):
            self.principal_by_code.setdefault(norm(row["kode"]), row["id"])

        for row in self.rows("SELECT id, kode FROM customer WHERE NULLIF(TRIM(kode), '') IS NOT NULL ORDER BY id"):
            self.customer_by_code.setdefault(norm(row["kode"]), row["id"])

        for row in self.rows(
            """
            SELECT s.id AS id_sales, s.id_user, sd.kode_sales
            FROM sales s
            JOIN sales_detail sd ON sd.id_sales = s.id
            WHERE NULLIF(TRIM(sd.kode_sales), '') IS NOT NULL
            ORDER BY s.id
            """
        ):
            self.sales_by_code.setdefault(
                norm(row["kode_sales"]),
                {"id_sales": row["id_sales"], "id_user": row["id_user"]},
            )

        for row in self.rows("SELECT id, kode_sku FROM produk WHERE NULLIF(TRIM(kode_sku), '') IS NOT NULL ORDER BY id"):
            self.product_by_code.setdefault(norm(row["kode_sku"]), row["id"])

        for row in self.rows("SELECT id, nama FROM produk_brand WHERE NULLIF(TRIM(nama), '') IS NOT NULL ORDER BY id"):
            self.brand_by_name.setdefault(norm(row["nama"]), row["id"])

        for row in self.rows("SELECT id, nama FROM produk_kategori WHERE NULLIF(TRIM(nama), '') IS NOT NULL ORDER BY id"):
            self.category_by_name.setdefault(norm(row["nama"]), row["id"])

        for row in self.rows(
            """
            SELECT id, id_brand, nama
            FROM produk_subbrand
            WHERE NULLIF(TRIM(nama), '') IS NOT NULL
            ORDER BY id
            """
        ):
            key = f"{row.get('id_brand') or 0}:{norm(row['nama'])}"
            self.subbrand_by_key.setdefault(key, row["id"])

    def ensure_principal(self, source: dict[str, str]) -> int | None:
        code = clean(source.get("kode"), 25)
        if not code:
            return None

        params = {
            "kode": code,
            "nama": clean(source.get("nama"), 50) or code,
            "alamat": clean(source.get("alamat")),
            "telepon": clean(source.get("telepon"), 13),
            "npwp": clean(source.get("npwp"), 25),
            "no_rekening": clean(source.get("no_rekening"), 30),
            "pic": clean(source.get("pic"), 50),
            "aktif": as_bool(source.get("active")),
            "id_perusahaan": self.target_company_id,
        }

        existing = self.row(
            """
            SELECT id
            FROM principal
            WHERE id_perusahaan = :id_perusahaan AND LOWER(TRIM(kode)) = LOWER(TRIM(:kode))
            ORDER BY CASE WHEN LOWER(TRIM(COALESCE(nama, ''))) = LOWER(TRIM(:nama)) THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            params,
        )
        if existing:
            self.conn.execute(
                text(
                    """
                    UPDATE principal
                    SET nama = :nama,
                        alamat = NULLIF(:alamat, ''),
                        telepon = NULLIF(:telepon, ''),
                        npwp = NULLIF(:npwp, ''),
                        no_rekening = NULLIF(:no_rekening, ''),
                        pic = NULLIF(:pic, ''),
                        aktif = :aktif,
                        id_perusahaan = :id_perusahaan
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing["id"]},
            )
            principal_id = existing["id"]
            self.stats["principal_updated"] += 1
        else:
            principal_id = self.scalar(
                """
                INSERT INTO principal (kode, nama, alamat, telepon, npwp, no_rekening, pic, aktif, id_perusahaan)
                VALUES (:kode, :nama, NULLIF(:alamat, ''), NULLIF(:telepon, ''), NULLIF(:npwp, ''),
                        NULLIF(:no_rekening, ''), NULLIF(:pic, ''), :aktif, :id_perusahaan)
                RETURNING id
                """,
                params,
            )
            self.stats["principal_inserted"] += 1

        self.principal_by_code[norm(code)] = principal_id
        return principal_id

    def ensure_brand(self, name: str) -> int | None:
        clean_name = clean(name, 25)
        if not clean_name:
            return None
        key = norm(clean_name)
        if key in self.brand_by_name:
            return self.brand_by_name[key]
        brand_id = self.scalar("INSERT INTO produk_brand (nama) VALUES (:nama) RETURNING id", {"nama": clean_name})
        self.brand_by_name[key] = brand_id
        self.stats["brand_inserted"] += 1
        return brand_id

    def ensure_category(self, name: str) -> int | None:
        clean_name = clean(name, 25) or "LAINNYA"
        key = norm(clean_name)
        if key in self.category_by_name:
            return self.category_by_name[key]
        category_id = self.scalar("INSERT INTO produk_kategori (nama) VALUES (:nama) RETURNING id", {"nama": clean_name})
        self.category_by_name[key] = category_id
        self.stats["category_inserted"] += 1
        return category_id

    def ensure_subbrand(self, brand_id: int | None, code: str, name: str) -> int | None:
        clean_name = clean(name or code, 160)
        if not clean_name:
            return None
        key = f"{brand_id or 0}:{norm(clean_name)}"
        if key in self.subbrand_by_key:
            return self.subbrand_by_key[key]
        subbrand_id = self.scalar(
            """
            INSERT INTO produk_subbrand (id_brand, kode, nama, keterangan, is_active, updated_at)
            VALUES (:id_brand, NULLIF(:kode, ''), :nama, :keterangan, TRUE, NOW())
            RETURNING id
            """,
            {
                "id_brand": brand_id,
                "kode": clean(code, 30),
                "nama": clean_name,
                "keterangan": self.source_name,
            },
        )
        self.subbrand_by_key[key] = subbrand_id
        self.stats["subbrand_inserted"] += 1
        return subbrand_id

    def ensure_customer_mapping(self, external_code: str, customer_id: int, customer_code: str) -> None:
        external_code = clean(external_code, 80)
        if not external_code:
            return
        self.conn.execute(
            text(
                """
                INSERT INTO customer_external_mapping (
                    kode_external, id_customer, kode_customer, source, is_active, created_at, updated_at
                )
                VALUES (:kode_external, :id_customer, :kode_customer, :source, TRUE, NOW(), NOW())
                ON CONFLICT (kode_external, source)
                DO UPDATE SET
                    id_customer = EXCLUDED.id_customer,
                    kode_customer = EXCLUDED.kode_customer,
                    is_active = TRUE,
                    updated_at = NOW()
                """
            ),
            {
                "kode_external": external_code,
                "id_customer": customer_id,
                "kode_customer": customer_code,
                "source": CUSTOMER_MAPPING_SOURCE,
            },
        )
        self.stats["customer_mapping_upserted"] += 1

    def ensure_customer(self, source: dict[str, str]) -> int | None:
        code = clean(source.get("kode"), 30)
        if not code:
            return None
        branch_id = branch_id_from_area(source.get("kode_area"), self.branch_map, self.default_branch_id)
        params = {
            "kode": code,
            "nama": clean(source.get("nama"), 50) or code,
            "alamat": clean(source.get("alamat"), 100),
            "telepon": clean(source.get("telepon"), 20),
            "npwp": clean(source.get("npwp"), 25),
            "nama_wajib_pajak": clean(source.get("nama_wajib_pajak"), 50),
            "alamat_wajib_pajak": clean(source.get("alamat_wajib_pajak"), 100),
            "longitude": clean(source.get("longitude"), 25),
            "latitude": clean(source.get("latitude"), 25),
            "id_cabang": branch_id,
            "id_perusahaan": self.target_company_id,
        }
        existing = self.row("SELECT * FROM customer WHERE LOWER(TRIM(kode)) = LOWER(TRIM(:kode)) LIMIT 1", {"kode": code})
        if existing:
            params["id_cabang_list"] = append_csv_id(existing.get("id_cabang_list"), branch_id)
            params["id_perusahaan_list"] = append_csv_id(existing.get("id_perusahaan_list"), self.target_company_id)
            self.conn.execute(
                text(
                    """
                    UPDATE customer
                    SET nama = :nama,
                        alamat = NULLIF(:alamat, ''),
                        telepon = NULLIF(:telepon, ''),
                        npwp = NULLIF(:npwp, ''),
                        nama_wajib_pajak = NULLIF(:nama_wajib_pajak, ''),
                        alamat_wajib_pajak = NULLIF(:alamat_wajib_pajak, ''),
                        longitude = NULLIF(:longitude, ''),
                        latitude = NULLIF(:latitude, ''),
                        id_cabang = :id_cabang,
                        id_cabang_list = :id_cabang_list,
                        id_perusahaan_list = :id_perusahaan_list,
                        id_tipe_harga = COALESCE(id_tipe_harga, 1),
                        is_ppn = COALESCE(is_ppn, 0)
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing["id"]},
            )
            customer_id = existing["id"]
            self.stats["customer_updated"] += 1
        else:
            customer_id = self.scalar(
                """
                INSERT INTO customer (
                    kode, nama, alamat, telepon, npwp, nama_wajib_pajak, alamat_wajib_pajak,
                    longitude, latitude, id_cabang, id_cabang_list, id_perusahaan_list,
                    id_tipe_harga, is_ppn
                )
                VALUES (
                    :kode, :nama, NULLIF(:alamat, ''), NULLIF(:telepon, ''), NULLIF(:npwp, ''),
                    NULLIF(:nama_wajib_pajak, ''), NULLIF(:alamat_wajib_pajak, ''),
                    NULLIF(:longitude, ''), NULLIF(:latitude, ''),
                    :id_cabang, :id_cabang_list, :id_perusahaan_list, 1, 0
                )
                RETURNING id
                """,
                {
                    **params,
                    "id_cabang_list": str(branch_id),
                    "id_perusahaan_list": str(self.target_company_id),
                },
            )
            self.stats["customer_inserted"] += 1

        self.customer_by_code[norm(code)] = customer_id
        self.ensure_customer_mapping(code, customer_id, code)
        for external_key in ("qr_code", "kode_outlet_scylla"):
            external_code = clean(source.get(external_key))
            if external_code and external_code != code:
                self.ensure_customer_mapping(external_code, customer_id, code)
        return customer_id

    def ensure_sales(self, source: dict[str, str]) -> dict[str, int] | None:
        code = clean(source.get("kode"), 40)
        if not code:
            return None
        code_key = norm(code)
        principal_id = self.principal_by_code.get(norm(source.get("kode_principal")))
        existing = self.row(
            """
            SELECT s.id AS id_sales, s.id_user
            FROM sales s
            JOIN sales_detail sd ON sd.id_sales = s.id
            WHERE LOWER(TRIM(sd.kode_sales)) = LOWER(TRIM(:kode))
            ORDER BY s.id
            LIMIT 1
            """,
            {"kode": code},
        )
        if existing:
            self.stats["sales_existing"] += 1
            result = {"id_sales": existing["id_sales"], "id_user": existing["id_user"]}
            self.sales_by_code[code_key] = result
            if principal_id:
                self.ensure_sales_assignment(result["id_sales"], principal_id)
            return result

        name = clean(source.get("nama"), 40) or f"SALES {code}"[:40]
        username = f"dist_{code}".lower().replace(" ", "_")[:25]
        user_id = self.scalar(
            """
            INSERT INTO users (
                nama, username, email, telepon, id_jabatan, id_cabang, id_perusahaan,
                id_cabang_list, id_perusahaan_list, password
            )
            VALUES (
                :nama, :username, :email, NULLIF(:telepon, ''), :id_jabatan, :id_cabang, :id_perusahaan,
                :id_cabang_list, :id_perusahaan_list, :password
            )
            RETURNING id
            """,
            {
                "nama": name,
                "username": username,
                "email": f"{username}@migration.local"[:100],
                "telepon": clean(source.get("telepon"), 13),
                "id_jabatan": self.args.sales_jabatan_id,
                "id_cabang": self.default_branch_id,
                "id_perusahaan": self.target_company_id,
                "id_cabang_list": self.branch_ids_csv,
                "id_perusahaan_list": str(self.target_company_id),
                "password": self.args.default_password,
            },
        )
        sales_id = self.scalar(
            """
            INSERT INTO sales (id_user, id_principal, id_tipe, plafon_limit)
            VALUES (:id_user, :id_principal, :id_tipe, 0)
            RETURNING id
            """,
            {"id_user": user_id, "id_principal": principal_id, "id_tipe": self.args.sales_tipe_id},
        )
        self.conn.execute(
            text("INSERT INTO sales_detail (id_sales, kode_sales) VALUES (:id_sales, :kode_sales)"),
            {"id_sales": sales_id, "kode_sales": code},
        )
        if principal_id:
            self.ensure_sales_assignment(sales_id, principal_id)
        result = {"id_sales": sales_id, "id_user": user_id}
        self.sales_by_code[code_key] = result
        self.stats["sales_inserted"] += 1
        return result

    def ensure_sales_assignment(self, sales_id: int, principal_id: int) -> None:
        exists = self.scalar(
            """
            SELECT id FROM sales_principal_assignment
            WHERE id_sales = :id_sales AND id_principal = :id_principal
            LIMIT 1
            """,
            {"id_sales": sales_id, "id_principal": principal_id},
        )
        if exists:
            return
        self.conn.execute(
            text(
                """
                INSERT INTO sales_principal_assignment (id_sales, id_principal)
                VALUES (:id_sales, :id_principal)
                """
            ),
            {"id_sales": sales_id, "id_principal": principal_id},
        )
        self.stats["sales_assignment_upserted"] += 1

    def ensure_product_mapping(self, external_code: str, product_id: int, sku: str, principal_code: str) -> None:
        external_code = clean(external_code, 80)
        if not external_code:
            return
        exact_product_id = self.product_by_code.get(norm(external_code))
        if norm(external_code) != norm(sku) and exact_product_id and exact_product_id != product_id:
            return
        self.conn.execute(
            text(
                """
                INSERT INTO produk_external_mapping (
                    kode_external, id_produk, kode_sku, principal_code, source, is_active, created_at, updated_at
                )
                VALUES (:kode_external, :id_produk, :kode_sku, :principal_code, :source, TRUE, NOW(), NOW())
                ON CONFLICT (kode_external, source)
                DO UPDATE SET
                    id_produk = EXCLUDED.id_produk,
                    kode_sku = EXCLUDED.kode_sku,
                    principal_code = EXCLUDED.principal_code,
                    is_active = TRUE,
                    updated_at = NOW()
                """
            ),
            {
                "kode_external": external_code,
                "id_produk": product_id,
                "kode_sku": sku,
                "principal_code": principal_code,
                "source": self.source_name,
            },
        )
        self.stats["product_mapping_upserted"] += 1

    def correct_exact_product_mappings(self) -> None:
        result = self.conn.execute(
            text(
                """
                WITH exact_product AS (
                    SELECT DISTINCT ON (LOWER(TRIM(p.kode_sku)))
                        LOWER(TRIM(p.kode_sku)) AS sku_key,
                        p.id AS id_produk,
                        p.kode_sku,
                        pr.kode AS principal_code
                    FROM produk p
                    LEFT JOIN principal pr ON pr.id = p.id_principal
                    WHERE NULLIF(TRIM(p.kode_sku), '') IS NOT NULL
                    ORDER BY LOWER(TRIM(p.kode_sku)), p.id
                )
                UPDATE produk_external_mapping pem
                SET id_produk = ep.id_produk,
                    kode_sku = ep.kode_sku,
                    principal_code = ep.principal_code,
                    is_active = TRUE,
                    updated_at = NOW()
                FROM exact_product ep
                WHERE pem.source = :source
                  AND LOWER(TRIM(pem.kode_external)) = ep.sku_key
                  AND pem.id_produk <> ep.id_produk
                """
            ),
            {"source": self.source_name},
        )
        self.stats["product_mapping_exact_corrected"] += result.rowcount or 0

    def ensure_uom(self, product_id: int, code: str, name: str, level: int, factor: int) -> None:
        existing = self.scalar(
            "SELECT id FROM produk_uom WHERE id_produk = :id_produk AND level = :level LIMIT 1",
            {"id_produk": product_id, "level": level},
        )
        params = {
            "id_produk": product_id,
            "kode": clean(code, 30) or ("PCS" if level == 1 else f"UOM{level}"),
            "nama": clean(name, 50) or clean(code, 50) or ("PCS" if level == 1 else f"UOM {level}"),
            "level": level,
            "factor": max(int(factor or 1), 1),
            "default_sales": 1 if level == 1 else 0,
            "default_storage": 1 if level == 1 else 0,
        }
        if existing:
            self.conn.execute(
                text(
                    """
                    UPDATE produk_uom
                    SET kode = :kode,
                        nama = :nama,
                        faktor_konversi = :factor,
                        set_default_sales = :default_sales,
                        set_default_storage = :default_storage
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing},
            )
        else:
            self.conn.execute(
                text(
                    """
                    INSERT INTO produk_uom (
                        kode, nama, level, id_produk, faktor_konversi, set_default_sales, set_default_storage
                    )
                    VALUES (:kode, :nama, :level, :id_produk, :factor, :default_sales, :default_storage)
                    """
                ),
                params,
            )
        self.stats["uom_upserted"] += 1

    def ensure_price(self, product_id: int, tipe_id: int, price: float) -> None:
        if price <= 0:
            return
        existing = self.scalar(
            """
            SELECT id FROM produk_harga_jual
            WHERE id_produk = :id_produk AND id_tipe_harga = :id_tipe_harga
            ORDER BY id
            LIMIT 1
            """,
            {"id_produk": product_id, "id_tipe_harga": tipe_id},
        )
        if existing:
            self.conn.execute(text("UPDATE produk_harga_jual SET harga = :harga WHERE id = :id"), {"id": existing, "harga": price})
        else:
            self.conn.execute(
                text(
                    """
                    INSERT INTO produk_harga_jual (id_produk, id_tipe_harga, harga)
                    VALUES (:id_produk, :id_tipe_harga, :harga)
                    """
                ),
                {"id_produk": product_id, "id_tipe_harga": tipe_id, "harga": price},
            )
        self.stats["price_upserted"] += 1

    def ensure_product(self, source: dict[str, str]) -> int | None:
        sku = clean(source.get("kode_sku"), 25)
        if not sku:
            return None
        principal_id = self.principal_by_code.get(norm(source.get("kode_principal")))
        if not principal_id:
            return None

        brand_id = self.ensure_brand(source.get("nama_brand") or source.get("brand"))
        category_id = self.ensure_category(source.get("food") or source.get("kategori_lama") or "LAINNYA")
        subbrand_id = self.ensure_subbrand(brand_id, source.get("subbrand"), source.get("nama_subbrand") or source.get("subbrand"))
        per_unit = as_int(source.get("per_unit"), 1) or 1
        params = {
            "id_principal": principal_id,
            "id_brand": brand_id,
            "id_kategori": category_id,
            "id_subbrand": subbrand_id,
            "kode_sku": sku,
            "kode_ean": clean(source.get("nasional_kode"), 25),
            "nama": clean(source.get("nama"), 50) or sku,
            "harga_beli": as_float(source.get("harga_beli")),
            "harga_jual": as_float(source.get("harga_a")),
            "satuan": clean(source.get("satuan"), 30) or "PCS",
            "isi": per_unit,
            "keterangan": clean(
                " | ".join(
                    item
                    for item in (
                        self.source_name,
                        clean(source.get("jenis")),
                        clean(source.get("kategori_lama")),
                        clean(source.get("master_kode")),
                    )
                    if item
                ),
                50,
            ),
        }
        existing_id = self.product_by_code.get(norm(sku))
        if existing_id:
            self.conn.execute(
                text(
                    """
                    UPDATE produk
                    SET id_principal = :id_principal,
                        id_brand = :id_brand,
                        id_kategori = :id_kategori,
                        id_subbrand = :id_subbrand,
                        id_status = 1,
                        kode_ean = NULLIF(:kode_ean, ''),
                        nama = :nama,
                        harga_beli = :harga_beli,
                        harga_jual = :harga_jual,
                        satuan = :satuan,
                        isiperbox = :isi,
                        isiperkarton = :isi,
                        ppn = COALESCE(ppn, 11),
                        keterangan = NULLIF(:keterangan, '')
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing_id},
            )
            product_id = existing_id
            self.stats["product_updated"] += 1
        else:
            product_id = self.scalar(
                """
                INSERT INTO produk (
                    id_principal, id_brand, id_kategori, id_subbrand, id_status,
                    kode_sku, kode_ean, nama, harga_beli, harga_jual,
                    satuan, isiperbox, isiperkarton, ppn, keterangan
                )
                VALUES (
                    :id_principal, :id_brand, :id_kategori, :id_subbrand, 1,
                    :kode_sku, NULLIF(:kode_ean, ''), :nama, :harga_beli, :harga_jual,
                    :satuan, :isi, :isi, 11, NULLIF(:keterangan, '')
                )
                RETURNING id
                """,
                params,
            )
            self.product_by_code[norm(sku)] = product_id
            self.stats["product_inserted"] += 1

        self.ensure_uom(product_id, params["satuan"], params["satuan"], 1, 1)
        if per_unit > 1:
            carton_code = clean(source.get("nama_unit"), 30) or "CT"
            self.ensure_uom(product_id, carton_code, carton_code, 2, per_unit)

        for tipe_id, key in ((1, "harga_a"), (2, "harga_b"), (3, "harga_c"), (4, "harga_d"), (9, "harga_e")):
            self.ensure_price(product_id, tipe_id, as_float(source.get(key)))

        principal_code = clean(source.get("kode_principal"), 30)
        for external_code in {
            sku,
            clean(source.get("master_kode")),
            clean(source.get("nasional_kode")),
            clean(source.get("kode_dms")),
        }:
            self.ensure_product_mapping(external_code, product_id, sku, principal_code)
        return product_id

    def ensure_plafon(self, source: dict[str, str]) -> None:
        customer_id = self.customer_by_code.get(norm(source.get("kode_customer")))
        principal_id = self.principal_by_code.get(norm(source.get("kode_principal")))
        sales_code = clean(source.get("kode_sales"))
        sales_ref = self.sales_by_code.get(norm(sales_code)) if sales_code else None

        if not customer_id:
            self.stats["plafon_skipped_missing_customer"] += 1
            return
        if not principal_id:
            self.stats["plafon_skipped_missing_principal"] += 1
            return
        if sales_code and not sales_ref:
            self.stats["plafon_skipped_missing_sales"] += 1
            return

        params = {
            "id_customer": customer_id,
            "id_principal": principal_id,
            "id_sales": sales_ref["id_sales"] if sales_ref else None,
            "id_user": sales_ref["id_user"] if sales_ref else None,
            "limit_bon": as_float(source.get("limit_bon")),
            "kode": f"{clean(source.get('kode_customer'), 20)}-{clean(source.get('kode_principal'), 10)}"[:25],
            "top": as_int(source.get("term"), 0) or 0,
            "lock_order": clean(source.get("lock_order"), 1) or "0",
        }
        existing = self.scalar(
            """
            SELECT id
            FROM plafon
            WHERE id_customer = :id_customer
              AND id_principal = :id_principal
              AND COALESCE(id_sales, 0) = COALESCE(:id_sales, 0)
            LIMIT 1
            """,
            params,
        )
        if existing:
            self.conn.execute(
                text(
                    """
                    UPDATE plafon
                    SET id_user = :id_user,
                        limit_bon = :limit_bon,
                        sisa_bon = COALESCE(sisa_bon, :limit_bon),
                        kode = :kode,
                        id_tipe_harga = COALESCE(id_tipe_harga, 1),
                        top = :top,
                        lock_order = :lock_order,
                        tempo = :top,
                        tempo_label = CASE WHEN :top > 0 THEN (CAST(:top AS text) || ' Hari') ELSE tempo_label END
                    WHERE id = :id
                    """
                ),
                {**params, "id": existing},
            )
            self.stats["plafon_updated"] += 1
        else:
            self.conn.execute(
                text(
                    """
                    INSERT INTO plafon (
                        id_customer, id_principal, id_sales, id_user, limit_bon, sisa_bon,
                        kode, id_tipe_harga, top, lock_order, tempo, tempo_label
                    )
                    VALUES (
                        :id_customer, :id_principal, :id_sales, :id_user, :limit_bon, :limit_bon,
                        :kode, 1, :top, :lock_order, :top,
                        CASE WHEN :top > 0 THEN (CAST(:top AS text) || ' Hari') ELSE NULL END
                    )
                    """
                ),
                params,
            )
            self.stats["plafon_inserted"] += 1

    def import_all(self, data: dict[str, list[dict[str, str]]]) -> None:
        self.sync_sequences()
        self.load_existing_maps()

        for row in data["principals"]:
            self.ensure_principal(row)
        for row in data["customers"]:
            self.ensure_customer(row)
        for row in data["sales"]:
            self.ensure_sales(row)
        for row in data["products"]:
            self.ensure_product(row)
        self.correct_exact_product_mappings()
        for row in data["plafon"]:
            self.ensure_plafon(row)
        self.sync_sequences()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-backup", action="store_true")
    parser.add_argument("--source-name", default=DEFAULT_SOURCE_NAME)
    parser.add_argument("--company-id", type=int, default=DEFAULT_COMPANY_ID)
    parser.add_argument("--default-branch-id", type=int, default=DEFAULT_BRANCH_ID)
    parser.add_argument(
        "--branch-map",
        default=",".join(f"{key}:{value}" for key, value in DEFAULT_BRANCH_BY_AREA.items()),
    )
    parser.add_argument("--sales-jabatan-id", type=int, default=4)
    parser.add_argument("--sales-tipe-id", type=int, default=1)
    parser.add_argument("--default-password", default="budimas")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    data = {
        "principals": load_csv(input_dir, "principals"),
        "customers": load_csv(input_dir, "customers"),
        "sales": load_csv(input_dir, "sales"),
        "products": load_csv(input_dir, "products"),
        "plafon": load_csv(input_dir, "plafon"),
    }

    with db.connect() as conn:
        trans = conn.begin()
        importer = DistMasterImporter(conn, args)
        backup_stamp = None
        try:
            if args.apply and not args.skip_backup:
                backup_stamp = importer.create_backups()
            importer.import_all(data)
            if args.apply:
                trans.commit()
                mode = "APPLIED"
            else:
                trans.rollback()
                mode = "DRY_RUN_ROLLED_BACK"
        except Exception:
            trans.rollback()
            raise

    print(
        json.dumps(
            {
                "mode": mode,
                "source": importer.source_name,
                "company_id": importer.target_company_id,
                "default_branch_id": importer.default_branch_id,
                "branch_map": importer.branch_map,
                "input_dir": str(input_dir),
                "backup_stamp": backup_stamp,
                "source_rows": {key: len(value) for key, value in data.items()},
                "stats": importer.stats,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
