import argparse
import os
import re

from sqlalchemy import create_engine, text


def build_engine():
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASS", "")
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = os.environ.get("DB_PORT", "5432")
    database = os.environ.get("DB_NAME", "budimas-dev")
    return create_engine(f"postgresql+pg8000://{user}:{password}@{host}:{port}/{database}")


def make_code(name):
    raw = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip().upper()).strip("_")
    return (raw or "SUBBRAND")[:60]


def constraint_exists(conn, table_name, constraint_name):
    return bool(conn.execute(
        text("""
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = :table_name
              AND c.conname = :constraint_name
            LIMIT 1
        """),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).first())


def column_exists(conn, table_name, column_name):
    return bool(conn.execute(
        text("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
        """),
        {"table_name": table_name, "column_name": column_name},
    ).first())


def ensure_schema(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS produk_subbrand (
            id SERIAL PRIMARY KEY,
            id_brand INTEGER NULL,
            kode VARCHAR(80),
            nama VARCHAR(160) NOT NULL,
            keterangan TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    if not constraint_exists(conn, "produk_subbrand", "fk_produk_subbrand_brand"):
        conn.execute(text("""
            ALTER TABLE produk_subbrand
            ADD CONSTRAINT fk_produk_subbrand_brand
            FOREIGN KEY (id_brand) REFERENCES produk_brand(id)
            ON DELETE SET NULL
        """))

    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_produk_subbrand_brand_name
        ON produk_subbrand (COALESCE(id_brand, 0), LOWER(TRIM(nama)))
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_produk_subbrand_brand ON produk_subbrand(id_brand)"))

    conn.execute(text("ALTER TABLE produk ADD COLUMN IF NOT EXISTS id_subbrand INTEGER NULL"))
    if not constraint_exists(conn, "produk", "fk_produk_subbrand"):
        conn.execute(text("""
            ALTER TABLE produk
            ADD CONSTRAINT fk_produk_subbrand
            FOREIGN KEY (id_subbrand) REFERENCES produk_subbrand(id)
            ON DELETE SET NULL
        """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_produk_id_subbrand ON produk(id_subbrand)"))

    if column_exists(conn, "trade_promo_program_rule", "id"):
        conn.execute(text("ALTER TABLE trade_promo_program_rule ADD COLUMN IF NOT EXISTS id_subbrand INTEGER NULL"))
        conn.execute(text("ALTER TABLE trade_promo_program_rule ADD COLUMN IF NOT EXISTS id_brand INTEGER NULL"))
        conn.execute(text("""
            ALTER TABLE trade_promo_program_rule
            ADD COLUMN IF NOT EXISTS matching_mode VARCHAR(40) NOT NULL DEFAULT 'subbrand'
        """))
        if not constraint_exists(conn, "trade_promo_program_rule", "fk_trade_promo_rule_subbrand"):
            conn.execute(text("""
                ALTER TABLE trade_promo_program_rule
                ADD CONSTRAINT fk_trade_promo_rule_subbrand
                FOREIGN KEY (id_subbrand) REFERENCES produk_subbrand(id)
                ON DELETE SET NULL
            """))
        if not constraint_exists(conn, "trade_promo_program_rule", "fk_trade_promo_rule_brand"):
            conn.execute(text("""
                ALTER TABLE trade_promo_program_rule
                ADD CONSTRAINT fk_trade_promo_rule_brand
                FOREIGN KEY (id_brand) REFERENCES produk_brand(id)
                ON DELETE SET NULL
            """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_trade_promo_rule_subbrand ON trade_promo_program_rule(id_subbrand)"))

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trade_promo_rule_product (
            id SERIAL PRIMARY KEY,
            program_rule_id INTEGER NOT NULL,
            id_produk BIGINT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    if not constraint_exists(conn, "trade_promo_rule_product", "fk_trade_promo_rule_product_rule"):
        conn.execute(text("""
            ALTER TABLE trade_promo_rule_product
            ADD CONSTRAINT fk_trade_promo_rule_product_rule
            FOREIGN KEY (program_rule_id) REFERENCES trade_promo_program_rule(id)
            ON DELETE CASCADE
        """))
    if not constraint_exists(conn, "trade_promo_rule_product", "fk_trade_promo_rule_product_produk"):
        conn.execute(text("""
            ALTER TABLE trade_promo_rule_product
            ADD CONSTRAINT fk_trade_promo_rule_product_produk
            FOREIGN KEY (id_produk) REFERENCES produk(id)
            ON DELETE CASCADE
        """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_trade_promo_rule_product
        ON trade_promo_rule_product(program_rule_id, id_produk)
    """))


def seed_subbrands_from_trade_rules(conn):
    source_rows = conn.execute(text("""
        SELECT DISTINCT
            NULLIF(TRIM(COALESCE(subbrand, brand, rule_group)), '') AS nama
        FROM trade_promo_program_rule
        WHERE NULLIF(TRIM(COALESCE(subbrand, brand, rule_group)), '') IS NOT NULL
        ORDER BY 1
    """)).mappings().fetchall()

    inserted_or_found = 0
    natur_brand = conn.execute(
        text("SELECT id FROM produk_brand WHERE nama ILIKE 'NATUR E' ORDER BY id LIMIT 1")
    ).scalar()

    for row in source_rows:
        name = row["nama"]
        brand_id = natur_brand if natur_brand and name.lower().startswith(("natur-e", "natur e")) else None
        conn.execute(
            text("""
                INSERT INTO produk_subbrand (id_brand, kode, nama, keterangan, updated_at)
                VALUES (:id_brand, :kode, :nama, 'Seed dari trade promo program', CURRENT_TIMESTAMP)
                ON CONFLICT (COALESCE(id_brand, 0), LOWER(TRIM(nama))) DO UPDATE SET
                    kode = EXCLUDED.kode,
                    keterangan = COALESCE(produk_subbrand.keterangan, EXCLUDED.keterangan),
                    updated_at = CURRENT_TIMESTAMP
            """),
            {"id_brand": brand_id, "kode": make_code(name), "nama": name},
        )
        inserted_or_found += 1

    conn.execute(text("""
        UPDATE trade_promo_program_rule r
        SET id_subbrand = ps.id,
            id_brand = ps.id_brand,
            matching_mode = 'subbrand'
        FROM produk_subbrand ps
        WHERE LOWER(TRIM(ps.nama)) = LOWER(TRIM(COALESCE(r.subbrand, r.brand, r.rule_group)))
          AND (r.id_subbrand IS DISTINCT FROM ps.id OR r.id_brand IS DISTINCT FROM ps.id_brand)
    """))
    return inserted_or_found


def report(conn):
    counts = {}
    for table in ["produk_subbrand", "trade_promo_program", "trade_promo_program_rule", "trade_promo_rule_product"]:
        counts[table] = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    mapped_rules = conn.execute(text("""
        SELECT COUNT(*)
        FROM trade_promo_program_rule
        WHERE id_subbrand IS NOT NULL
    """)).scalar()
    counts["trade_promo_rules_with_subbrand"] = mapped_rules
    return counts


def main():
    parser = argparse.ArgumentParser(description="Upgrade product subbrand schema for trade promo programs.")
    parser.add_argument("--apply", action="store_true", help="Commit schema changes. Without this flag changes are rolled back.")
    args = parser.parse_args()

    engine = build_engine()
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ensure_schema(conn)
            seeded = seed_subbrands_from_trade_rules(conn)
            counts = report(conn)
            if args.apply:
                trans.commit()
                mode = "APPLIED"
            else:
                trans.rollback()
                mode = "DRY_RUN_ROLLBACK"
        except Exception:
            trans.rollback()
            raise

    print({"mode": mode, "seeded_or_updated_subbrands": seeded, "counts": counts})


if __name__ == "__main__":
    main()
