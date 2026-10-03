import json
import os
from datetime import date

from sqlalchemy import create_engine, text


DB_URL = (
    f"postgresql+pg8000://{os.environ.get('DB_USER', 'postgres')}:"
    f"{os.environ.get('DB_PASS', '')}@"
    f"{os.environ.get('DB_HOST', '127.0.0.1')}:"
    f"{os.environ.get('DB_PORT', '5432')}/"
    f"{os.environ.get('DB_NAME', 'budimas-dev')}"
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS unified_promo_program (
    id SERIAL PRIMARY KEY,
    kode_promo VARCHAR(80) UNIQUE NOT NULL,
    nama_promo VARCHAR(180) NOT NULL,
    promo_type VARCHAR(40) NOT NULL DEFAULT 'discount',
    benefit_scope VARCHAR(40) NOT NULL DEFAULT 'invoice',
    id_cabang INTEGER NULL,
    id_perusahaan INTEGER NULL,
    id_principal INTEGER NULL,
    id_customer INTEGER NULL,
    budget_limit NUMERIC(18, 2) NOT NULL DEFAULT 0,
    budget_used NUMERIC(18, 2) NOT NULL DEFAULT 0,
    periode_mulai DATE NULL,
    periode_selesai DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    keterangan TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified_promo_rule (
    id SERIAL PRIMARY KEY,
    promo_id INTEGER NOT NULL REFERENCES unified_promo_program(id) ON DELETE CASCADE,
    nama_rule VARCHAR(180) NULL,
    target_type VARCHAR(40) NOT NULL DEFAULT 'all',
    id_produk INTEGER NULL,
    id_brand INTEGER NULL,
    id_subbrand INTEGER NULL,
    id_principal INTEGER NULL,
    id_customer INTEGER NULL,
    qty_uom VARCHAR(20) NOT NULL DEFAULT 'karton',
    min_qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    max_qty NUMERIC(18, 4) NULL,
    min_subtotal NUMERIC(18, 2) NOT NULL DEFAULT 0,
    max_subtotal NUMERIC(18, 2) NULL,
    benefit_type VARCHAR(40) NOT NULL DEFAULT 'percent',
    benefit_value NUMERIC(18, 4) NOT NULL DEFAULT 0,
    free_product_id INTEGER NULL,
    free_qty NUMERIC(18, 4) NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS unified_promo_usage (
    id SERIAL PRIMARY KEY,
    promo_id INTEGER NOT NULL REFERENCES unified_promo_program(id),
    rule_id INTEGER NULL REFERENCES unified_promo_rule(id),
    id_sales_order INTEGER NULL,
    id_faktur INTEGER NULL,
    id_customer INTEGER NULL,
    id_principal INTEGER NULL,
    nominal NUMERIC(18, 2) NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'ready',
    source VARCHAR(40) NOT NULL DEFAULT 'sales_order',
    catatan TEXT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    used_at TIMESTAMP WITHOUT TIME ZONE NULL
);
"""


PROMOS = [
    {
        "kode_promo": "UAT-GODREJ-RELASI-PCT-202605",
        "nama_promo": "UAT Godrej Relasi Mart Diskon Bertingkat",
        "promo_type": "discount",
        "benefit_scope": "invoice",
        "id_cabang": 5,
        "id_perusahaan": 1,
        "id_principal": 6,
        "id_customer": 90951,
        "budget_limit": 1_000_000,
        "periode_mulai": "2026-05-01",
        "periode_selesai": "2026-05-31",
        "status": "active",
        "keterangan": "Data UAT: cabang SOLO, BMM, PT GODREJ, customer RELASI MART.",
        "rules": [
            {
                "nama_rule": "STELLA 2-4 pcs diskon 1%",
                "target_type": "product",
                "id_produk": 4614,
                "qty_uom": "pieces",
                "min_qty": 2,
                "max_qty": 5,
                "benefit_type": "percent",
                "benefit_value": 1,
                "priority": 10,
            },
            {
                "nama_rule": "STELLA 5-9 pcs diskon 2%",
                "target_type": "product",
                "id_produk": 4614,
                "qty_uom": "pieces",
                "min_qty": 5,
                "max_qty": 10,
                "benefit_type": "percent",
                "benefit_value": 2,
                "priority": 20,
            },
            {
                "nama_rule": "STELLA 10 pcs ke atas diskon 3%",
                "target_type": "product",
                "id_produk": 4614,
                "qty_uom": "pieces",
                "min_qty": 10,
                "max_qty": None,
                "benefit_type": "percent",
                "benefit_value": 3,
                "priority": 30,
            },
        ],
    },
    {
        "kode_promo": "UAT-ENERGIZER-RALALI-NOM-202605",
        "nama_promo": "UAT Energizer Ralali Cashback Nominal",
        "promo_type": "cashback",
        "benefit_scope": "payment",
        "id_cabang": 5,
        "id_perusahaan": 1,
        "id_principal": 5,
        "id_customer": 65691,
        "budget_limit": 500_000,
        "periode_mulai": "2026-05-01",
        "periode_selesai": "2026-05-31",
        "status": "active",
        "keterangan": "Data UAT: cabang SOLO, BMM, PT ENERGIZER, customer ralali.com.",
        "rules": [
            {
                "nama_rule": "WORK LIGHT 2-4 pcs cashback 1000/pcs",
                "target_type": "product",
                "id_produk": 7039,
                "qty_uom": "pieces",
                "min_qty": 2,
                "max_qty": 5,
                "benefit_type": "nominal_per_qty",
                "benefit_value": 1000,
                "priority": 10,
            },
            {
                "nama_rule": "WORK LIGHT 5-9 pcs cashback 2000/pcs",
                "target_type": "product",
                "id_produk": 7039,
                "qty_uom": "pieces",
                "min_qty": 5,
                "max_qty": 10,
                "benefit_type": "nominal_per_qty",
                "benefit_value": 2000,
                "priority": 20,
            },
            {
                "nama_rule": "WORK LIGHT 10 pcs ke atas cashback 3000/pcs",
                "target_type": "product",
                "id_produk": 7039,
                "qty_uom": "pieces",
                "min_qty": 10,
                "max_qty": None,
                "benefit_type": "nominal_per_qty",
                "benefit_value": 3000,
                "priority": 30,
            },
        ],
    },
]


def execute_many(conn, sql):
    for statement in [part.strip() for part in sql.split(";") if part.strip()]:
        conn.execute(text(statement))


def upsert_promo(conn, promo):
    promo_id = conn.execute(
        text(
            """
            INSERT INTO unified_promo_program (
                kode_promo, nama_promo, promo_type, benefit_scope,
                id_cabang, id_perusahaan, id_principal, id_customer,
                budget_limit, budget_used, periode_mulai, periode_selesai,
                status, keterangan, created_at, updated_at
            )
            VALUES (
                :kode_promo, :nama_promo, :promo_type, :benefit_scope,
                :id_cabang, :id_perusahaan, :id_principal, :id_customer,
                :budget_limit, 0, :periode_mulai, :periode_selesai,
                :status, :keterangan, NOW(), NOW()
            )
            ON CONFLICT (kode_promo) DO UPDATE SET
                nama_promo = EXCLUDED.nama_promo,
                promo_type = EXCLUDED.promo_type,
                benefit_scope = EXCLUDED.benefit_scope,
                id_cabang = EXCLUDED.id_cabang,
                id_perusahaan = EXCLUDED.id_perusahaan,
                id_principal = EXCLUDED.id_principal,
                id_customer = EXCLUDED.id_customer,
                budget_limit = EXCLUDED.budget_limit,
                periode_mulai = EXCLUDED.periode_mulai,
                periode_selesai = EXCLUDED.periode_selesai,
                status = EXCLUDED.status,
                keterangan = EXCLUDED.keterangan,
                updated_at = NOW()
            RETURNING id
            """
        ),
        {key: value for key, value in promo.items() if key != "rules"},
    ).scalar_one()

    conn.execute(text("DELETE FROM unified_promo_rule WHERE promo_id = :promo_id"), {"promo_id": promo_id})
    for rule in promo["rules"]:
        conn.execute(
            text(
                """
                INSERT INTO unified_promo_rule (
                    promo_id, nama_rule, target_type, id_produk, id_brand, id_subbrand,
                    id_principal, id_customer, qty_uom, min_qty, max_qty,
                    min_subtotal, max_subtotal, benefit_type, benefit_value,
                    free_product_id, free_qty, priority, is_active, created_at, updated_at
                )
                VALUES (
                    :promo_id, :nama_rule, :target_type, :id_produk, NULL, NULL,
                    NULL, NULL, :qty_uom, :min_qty, :max_qty,
                    0, NULL, :benefit_type, :benefit_value,
                    NULL, 0, :priority, TRUE, NOW(), NOW()
                )
                """
            ),
            {"promo_id": promo_id, **rule},
        )
    return promo_id


def main():
    engine = create_engine(DB_URL)
    summary = {"seeded_at": date.today().isoformat(), "promos": []}
    with engine.begin() as conn:
        execute_many(conn, SCHEMA_SQL)
        for promo in PROMOS:
            promo_id = upsert_promo(conn, promo)
            summary["promos"].append(
                {
                    "id": promo_id,
                    "kode_promo": promo["kode_promo"],
                    "nama_promo": promo["nama_promo"],
                    "rules": len(promo["rules"]),
                }
            )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
