#!/usr/bin/env python
"""
Import scope hasil export SQL Server lama ke PostgreSQL Budimas baru.

Default mode adalah dry-run. Tambahkan --apply untuk benar-benar insert/update.
Urutan import:
1. principal -> 2. customer -> 3. sales/users -> 4. plafon -> 5. optional produk.
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


def norm_code(value: Any) -> str:
    return clean(value).upper()


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def bcrypt_hash(password: str) -> str:
    return bcrypt.hashpw((password or "budimas").encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def pg_url() -> str:
    return (
        f"postgresql+pg8000://{os.getenv('DB_USER', 'postgres')}:"
        f"{os.getenv('DB_PASS', '')}@{os.getenv('DB_HOST', '127.0.0.1')}:"
        f"{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'budimas-dev')}"
    )


class ScopeImporter:
    def __init__(self, conn, args):
        self.conn = conn
        self.args = args
        self.stats = {
            "principal_inserted": 0,
            "principal_existing": 0,
            "customer_inserted": 0,
            "customer_existing": 0,
            "sales_inserted": 0,
            "sales_existing": 0,
            "plafon_inserted": 0,
            "plafon_existing": 0,
            "product_inserted": 0,
            "product_existing": 0,
            "missing_customer_for_plafon": 0,
            "missing_principal_for_plafon": 0,
            "missing_sales_for_plafon": 0,
        }
        self.principal_by_code: dict[str, int] = {}
        self.customer_by_code: dict[str, int] = {}
        self.sales_by_code: dict[str, dict[str, int]] = {}

    def sync_sequences(self) -> None:
        for table_name, id_column in (
            ("principal", "id"),
            ("customer", "id"),
            ("users", "id"),
            ("sales", "id"),
            ("sales_detail", "id"),
            ("plafon", "id"),
            ("produk", "id"),
            ("produk_uom", "id"),
            ("produk_harga_jual", "id"),
        ):
            sequence_name = self.scalar(
                "SELECT pg_get_serial_sequence(:table_name, :id_column)",
                {"table_name": table_name, "id_column": id_column},
            )
            if not sequence_name:
                continue
            self.conn.execute(
                text("SELECT setval(:sequence_name, COALESCE((SELECT MAX(\"%s\") FROM %s), 0) + 1, false)" % (id_column, table_name)),
                {"sequence_name": sequence_name},
            )

    def scalar(self, sql: str, params: dict[str, Any]) -> Any:
        return self.conn.execute(text(sql), params).scalar()

    def row(self, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
        result = self.conn.execute(text(sql), params).mappings().first()
        return dict(result) if result else None

    def ensure_principal(self, row: dict[str, str]) -> int | None:
        code = clean(row.get("kode"))
        code_key = norm_code(code)
        if not code:
            return None
        existing = self.row(
            "SELECT id FROM principal WHERE lower(kode) = lower(:kode) AND id_perusahaan = :id_perusahaan LIMIT 1",
            {"kode": code, "id_perusahaan": self.args.id_perusahaan},
        )
        if existing:
            self.stats["principal_existing"] += 1
            self.principal_by_code[code_key] = existing["id"]
            return existing["id"]

        principal_id = self.scalar(
            """
            INSERT INTO principal (kode, nama, alamat, telepon, npwp, pic, id_perusahaan)
            VALUES (:kode, :nama, :alamat, :telepon, :npwp, :pic, :id_perusahaan)
            RETURNING id
            """,
            {
                "kode": code,
                "nama": clean(row.get("nama"))[:50],
                "alamat": clean(row.get("alamat")),
                "telepon": clean(row.get("telepon"))[:13],
                "npwp": clean(row.get("npwp"))[:25],
                "pic": clean(row.get("pic"))[:50],
                "id_perusahaan": self.args.id_perusahaan,
            },
        )
        self.stats["principal_inserted"] += 1
        self.principal_by_code[code_key] = principal_id
        return principal_id

    def ensure_customer(self, row: dict[str, str]) -> int | None:
        code = clean(row.get("kode"))
        code_key = norm_code(code)
        if not code:
            return None
        existing = self.row("SELECT id, id_cabang FROM customer WHERE lower(kode) = lower(:kode) LIMIT 1", {"kode": code})
        if existing:
            self.stats["customer_existing"] += 1
            if self.args.update_existing_scope and not existing.get("id_cabang"):
                self.conn.execute(
                    text("UPDATE customer SET id_cabang = :id_cabang WHERE id = :id"),
                    {"id_cabang": self.args.id_cabang, "id": existing["id"]},
                )
            self.customer_by_code[code_key] = existing["id"]
            return existing["id"]

        customer_id = self.scalar(
            """
            INSERT INTO customer (
              kode, nama, alamat, telepon, npwp, nama_wajib_pajak, alamat_wajib_pajak,
              id_cabang, longitude, latitude, id_tipe_harga, is_ppn
            )
            VALUES (
              :kode, :nama, :alamat, :telepon, :npwp, :nama_wajib_pajak, :alamat_wajib_pajak,
              :id_cabang, :longitude, :latitude, :id_tipe_harga, :is_ppn
            )
            RETURNING id
            """,
            {
                "kode": code[:30],
                "nama": clean(row.get("nama"))[:50],
                "alamat": clean(row.get("alamat"))[:100],
                "telepon": clean(row.get("telepon"))[:20],
                "npwp": clean(row.get("npwp"))[:25],
                "nama_wajib_pajak": clean(row.get("nama_wajib_pajak"))[:50],
                "alamat_wajib_pajak": clean(row.get("alamat_wajib_pajak"))[:100],
                "id_cabang": self.args.id_cabang,
                "longitude": clean(row.get("longitude"))[:25],
                "latitude": clean(row.get("latitude"))[:25],
                "id_tipe_harga": self.args.default_tipe_harga,
                "is_ppn": 1,
            },
        )
        self.stats["customer_inserted"] += 1
        self.customer_by_code[code_key] = customer_id
        return customer_id

    def ensure_sales(self, row: dict[str, str]) -> dict[str, int] | None:
        code = clean(row.get("kode"))
        code_key = norm_code(code)
        principal_code = norm_code(row.get("kode_principal"))
        sales_name = clean(row.get("nama"))[:40] or f"SALES {code}"
        if not code:
            return None
        existing = self.row(
            """
            SELECT s.id AS id_sales, s.id_user
            FROM sales s
            JOIN sales_detail sd ON sd.id_sales = s.id
            WHERE lower(sd.kode_sales) = lower(:kode)
            LIMIT 1
            """,
            {"kode": code},
        )
        if existing:
            self.stats["sales_existing"] += 1
            self.sales_by_code[code_key] = {"id_sales": existing["id_sales"], "id_user": existing["id_user"]}
            return self.sales_by_code[code_key]

        principal_id = self.principal_by_code.get(principal_code)
        user_row = self.row(
            """
            SELECT id
            FROM users
            WHERE lower(trim(nama)) = lower(trim(:nama))
            ORDER BY
              CASE WHEN COALESCE(id_perusahaan, :id_perusahaan) = :id_perusahaan THEN 0 ELSE 1 END,
              CASE WHEN COALESCE(id_cabang, :id_cabang) = :id_cabang THEN 0 ELSE 1 END,
              id DESC
            LIMIT 1
            """,
            {"nama": sales_name, "id_cabang": self.args.id_cabang, "id_perusahaan": self.args.id_perusahaan},
        )
        if user_row:
            user_id = user_row["id"]
            self.conn.execute(
                text(
                    """
                    UPDATE users
                    SET id_jabatan = :id_jabatan,
                        id_cabang = :id_cabang,
                        id_perusahaan = :id_perusahaan
                    WHERE id = :id
                    """
                ),
                {
                    "id": user_id,
                    "id_jabatan": self.args.sales_jabatan_id,
                    "id_cabang": self.args.id_cabang,
                    "id_perusahaan": self.args.id_perusahaan,
                },
            )
        else:
            user_id = self.scalar(
                """
                INSERT INTO users (nama, username, email, telepon, id_jabatan, id_cabang, id_perusahaan, password)
                VALUES (:nama, :username, :email, :telepon, :id_jabatan, :id_cabang, :id_perusahaan, :password)
                RETURNING id
                """,
                {
                    "nama": sales_name,
                    "username": f"old_{code}"[:25],
                    "email": f"sales_{code}@migration.local"[:100],
                    "telepon": clean(row.get("telepon"))[:13],
                    "id_jabatan": self.args.sales_jabatan_id,
                    "id_cabang": self.args.id_cabang,
                    "id_perusahaan": self.args.id_perusahaan,
                    "password": bcrypt_hash(code),
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
            {"id_sales": sales_id, "kode_sales": code_key},
        )
        if principal_id:
            self.conn.execute(
                text(
                    """
                    INSERT INTO sales_principal_assignment (id_sales, id_principal)
                    SELECT :id_sales, :id_principal
                    WHERE NOT EXISTS (
                      SELECT 1 FROM sales_principal_assignment
                      WHERE id_sales = :id_sales AND id_principal = :id_principal
                    )
                    """
                ),
                {"id_sales": sales_id, "id_principal": principal_id},
            )
        self.stats["sales_inserted"] += 1
        self.sales_by_code[code_key] = {"id_sales": sales_id, "id_user": user_id}
        return self.sales_by_code[code_key]

    def ensure_plafon(self, row: dict[str, str]) -> None:
        customer_id = self.customer_by_code.get(norm_code(row.get("kode_customer")))
        principal_id = self.principal_by_code.get(norm_code(row.get("kode_principal")))
        sales_code = norm_code(row.get("kode_sales"))
        sales_ref = self.sales_by_code.get(sales_code)

        if not customer_id:
            self.stats["missing_customer_for_plafon"] += 1
            return
        if not principal_id:
            self.stats["missing_principal_for_plafon"] += 1
            return
        if sales_code and not sales_ref:
            self.stats["missing_sales_for_plafon"] += 1
            return

        existing = self.scalar(
            """
            SELECT id FROM plafon
            WHERE id_customer = :id_customer
              AND id_principal = :id_principal
              AND COALESCE(id_sales, 0) = COALESCE(:id_sales, 0)
            LIMIT 1
            """,
            {
                "id_customer": customer_id,
                "id_principal": principal_id,
                "id_sales": sales_ref["id_sales"] if sales_ref else None,
            },
        )
        if existing:
            self.stats["plafon_existing"] += 1
            return

        limit_bon = as_float(row.get("limit_bon"), 0)
        term = as_int(row.get("term"), 0) or 0
        self.conn.execute(
            text(
                """
                INSERT INTO plafon (
                  id_customer, id_principal, id_sales, id_user, limit_bon, sisa_bon,
                  kode, id_tipe_harga, top, lock_order, tempo, tempo_label
                )
                VALUES (
                  :id_customer, :id_principal, :id_sales, :id_user, :limit_bon, :limit_bon,
                  :kode, :id_tipe_harga, :top, :lock_order, :tempo, :tempo_label
                )
                """
            ),
            {
                "id_customer": customer_id,
                "id_principal": principal_id,
                "id_sales": sales_ref["id_sales"] if sales_ref else None,
                "id_user": sales_ref["id_user"] if sales_ref else None,
                "limit_bon": limit_bon,
                "kode": f"{clean(row.get('kode_customer'))}-{clean(row.get('kode_principal'))}"[:25],
                "id_tipe_harga": self.args.default_tipe_harga,
                "top": term,
                "lock_order": clean(row.get("lock_order"))[:1] or "0",
                "tempo": term,
                "tempo_label": f"{term} Hari" if term else None,
            },
        )
        self.stats["plafon_inserted"] += 1

    def ensure_product(self, row: dict[str, str]) -> None:
        code = clean(row.get("kode_sku"))
        if not code:
            return
        existing = self.scalar("SELECT id FROM produk WHERE kode_sku = :kode LIMIT 1", {"kode": code})
        if existing:
            self.stats["product_existing"] += 1
            return
        principal_id = self.principal_by_code.get(clean(row.get("kode_principal")))
        if not principal_id:
            self.stats["product_existing"] += 1
            return
        product_id = self.scalar(
            """
            INSERT INTO produk (
              id_principal, id_status, kode_sku, nama, harga_beli, harga_jual,
              satuan, isiperbox, isiperkarton, ppn
            )
            VALUES (:id_principal, 1, :kode_sku, :nama, :harga_beli, :harga_jual, :satuan, 1, :per_unit, 11)
            RETURNING id
            """,
            {
                "id_principal": principal_id,
                "kode_sku": code[:25],
                "nama": clean(row.get("nama"))[:50],
                "harga_beli": as_float(row.get("harga_beli"), 0),
                "harga_jual": as_float(row.get("harga_a"), 0),
                "satuan": clean(row.get("satuan"))[:30] or "PCS",
                "per_unit": as_int(row.get("per_unit"), 1) or 1,
            },
        )
        self.conn.execute(
            text(
                """
                INSERT INTO produk_uom (kode, nama, level, id_produk, faktor_konversi, set_default_sales, set_default_storage)
                VALUES (:kode, :nama, 1, :id_produk, 1, 1, 1)
                """
            ),
            {"kode": clean(row.get("satuan"))[:20] or "PCS", "nama": clean(row.get("satuan"))[:50] or "PCS", "id_produk": product_id},
        )
        price_map = [(1, "harga_a"), (2, "harga_b"), (3, "harga_c"), (4, "harga_d"), (9, "harga_e")]
        for tipe_id, key in price_map:
            price = as_float(row.get(key), 0)
            if price:
                self.conn.execute(
                    text("INSERT INTO produk_harga_jual (id_produk, id_tipe_harga, harga) VALUES (:id_produk, :id_tipe_harga, :harga)"),
                    {"id_produk": product_id, "id_tipe_harga": tipe_id, "harga": price},
                )
        for external_key in ("master_kode", "nasional_kode", "kode_dms"):
            external_code = clean(row.get(external_key))
            if external_code and external_code != code:
                self.conn.execute(
                    text(
                        """
                        INSERT INTO produk_external_mapping (kode_external, id_produk, kode_sku, principal_code, source, is_active, created_at, updated_at)
                        SELECT :kode_external, :id_produk, :kode_sku, :principal_code, 'sqlserver', true, NOW(), NOW()
                        WHERE NOT EXISTS (
                          SELECT 1 FROM produk_external_mapping
                          WHERE kode_external = :kode_external AND source = 'sqlserver'
                        )
                        """
                    ),
                    {
                        "kode_external": external_code,
                        "id_produk": product_id,
                        "kode_sku": code,
                        "principal_code": clean(row.get("kode_principal")),
                    },
                )
        self.stats["product_inserted"] += 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, help="Folder hasil export_sqlserver_scope.ps1")
    parser.add_argument("--id-cabang", type=int)
    parser.add_argument("--id-perusahaan", type=int)
    parser.add_argument("--default-tipe-harga", type=int, default=2)
    parser.add_argument("--sales-jabatan-id", type=int, default=4)
    parser.add_argument("--sales-tipe-id", type=int, default=1)
    parser.add_argument("--include-products", action="store_true")
    parser.add_argument("--update-existing-scope", action="store_true")
    parser.add_argument("--limit-customers", type=int, default=0)
    parser.add_argument("--limit-sales", type=int, default=0)
    parser.add_argument("--limit-plafon", type=int, default=0)
    parser.add_argument("--limit-products", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    metadata_path = input_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig")) if metadata_path.exists() else {}
    args.id_cabang = args.id_cabang or as_int(metadata.get("id_cabang"))
    args.id_perusahaan = args.id_perusahaan or as_int(metadata.get("id_perusahaan"))
    if not args.id_cabang or not args.id_perusahaan:
        raise SystemExit("id_cabang dan id_perusahaan wajib tersedia dari metadata atau argumen.")

    engine = create_engine(pg_url())
    with engine.connect() as conn:
        trans = conn.begin()
        importer = ScopeImporter(conn, args)
        try:
            importer.sync_sequences()
            for row in load_csv(input_dir / "principals.csv"):
                importer.ensure_principal(row)
            customers = load_csv(input_dir / "customers.csv")
            sales_rows = load_csv(input_dir / "sales.csv")
            plafon_rows = load_csv(input_dir / "plafon.csv")
            product_rows = load_csv(input_dir / "products.csv")

            if args.limit_customers:
                customers = customers[: args.limit_customers]
            if args.limit_sales:
                sales_rows = sales_rows[: args.limit_sales]
            if args.limit_plafon:
                plafon_rows = plafon_rows[: args.limit_plafon]
            if args.limit_products:
                product_rows = product_rows[: args.limit_products]

            for row in customers:
                importer.ensure_customer(row)
            for row in sales_rows:
                importer.ensure_sales(row)
            for row in plafon_rows:
                importer.ensure_plafon(row)
            if args.include_products:
                for row in product_rows:
                    importer.ensure_product(row)

            if args.apply:
                trans.commit()
                mode = "APPLIED"
            else:
                trans.rollback()
                mode = "DRY_RUN_ROLLED_BACK"
        except Exception:
            trans.rollback()
            raise

    print(json.dumps({"mode": mode, "input_dir": str(input_dir), "stats": importer.stats}, indent=2))


if __name__ == "__main__":
    main()
