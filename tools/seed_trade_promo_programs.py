import argparse
import os
from datetime import date

from sqlalchemy import create_engine, text


PROGRAMS = [
    {
        "kode_program": "TP-MULTIBRAND-CB-STRATA-2026",
        "nama_program": "Program Cashback Strata Multi Brand 2026",
        "principal_name": None,
        "perusahaan_name": "PT Budimas Makmur Mulia",
        "periode_mulai": date(2026, 1, 1),
        "periode_selesai": date(2026, 12, 31),
        "channel": None,
        "objective": "Program cashback bertingkat berdasarkan pembelian karton.",
        "source_note": "Input dari foto tabel Subbrand / Strata / Cash Back.",
        "rules": [
            ("MKL Hanger / MKL Jar / MKL Refill", None, "MKL Hanger / MKL Jar / MKL Refill", None, "CTN", 10, 25, "percent_cashback", 1, "%"),
            ("MKL Hanger / MKL Jar / MKL Refill", None, "MKL Hanger / MKL Jar / MKL Refill", None, "CTN", 25, 50, "percent_cashback", 2, "%"),
            ("MKL Hanger / MKL Jar / MKL Refill", None, "MKL Hanger / MKL Jar / MKL Refill", None, "CTN", 50, None, "percent_cashback", 3, "%"),
            ("Hardlolly / Excl Frio", None, "Hardlolly / Excl Frio", None, "CTN", 5, 10, "percent_cashback", 1, "%"),
            ("Hardlolly / Excl Frio", None, "Hardlolly / Excl Frio", None, "CTN", 10, 20, "percent_cashback", 1.5, "%"),
            ("Hardlolly / Excl Frio", None, "Hardlolly / Excl Frio", None, "CTN", 20, None, "percent_cashback", 2, "%"),
            ("Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "CTN", 2, 5, "percent_cashback", 1, "%"),
            ("Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "CTN", 5, 10, "percent_cashback", 1.5, "%"),
            ("Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "Milkita Pasta / Milkita Candy Bag / Milkita Candy Rcg", None, "CTN", 10, None, "percent_cashback", 2, "%"),
            ("Frio", None, "Frio", None, "CTN", 2, 5, "nominal_cashback_per_ctn", 1000, "Rp/ctn"),
            ("Frio", None, "Frio", None, "CTN", 5, 10, "nominal_cashback_per_ctn", 2000, "Rp/ctn"),
            ("Frio", None, "Frio", None, "CTN", 10, None, "nominal_cashback_per_ctn", 3000, "Rp/ctn"),
            ("Milkita Bite GT", None, "Milkita Bite GT", None, "CTN", 2, 5, "nominal_cashback_per_ctn", 1000, "Rp/ctn"),
            ("Milkita Bite GT", None, "Milkita Bite GT", None, "CTN", 5, 10, "nominal_cashback_per_ctn", 2000, "Rp/ctn"),
            ("Milkita Bite GT", None, "Milkita Bite GT", None, "CTN", 10, None, "nominal_cashback_per_ctn", 3000, "Rp/ctn"),
            ("Pino", None, "Pino", None, "CTN", 2, 5, "nominal_cashback_per_ctn", 1000, "Rp/ctn"),
            ("Pino", None, "Pino", None, "CTN", 5, 10, "nominal_cashback_per_ctn", 2000, "Rp/ctn"),
            ("Pino", None, "Pino", None, "CTN", 10, None, "nominal_cashback_per_ctn", 3000, "Rp/ctn"),
            ("Super / Zuper", None, "Super / Zuper", None, "CTN", 2, 5, "nominal_cashback_per_ctn", 1000, "Rp/ctn"),
            ("Super / Zuper", None, "Super / Zuper", None, "CTN", 5, 10, "nominal_cashback_per_ctn", 2000, "Rp/ctn"),
            ("Super / Zuper", None, "Super / Zuper", None, "CTN", 10, None, "nominal_cashback_per_ctn", 3000, "Rp/ctn"),
        ],
    },
    {
        "kode_program": "TP-FRIO-ZUPER-CB-PCT-2026",
        "nama_program": "Program Diskon Cashback Frio Pino Zuper 2026",
        "principal_name": None,
        "perusahaan_name": "PT Budimas Makmur Mulia",
        "periode_mulai": date(2026, 1, 1),
        "periode_selesai": date(2026, 12, 31),
        "channel": None,
        "objective": "Program cashback persentase berdasarkan strata karton.",
        "source_note": "Input dari foto tabel Diskon Cashback Frio, Bites, Pino, dan Super Zuper.",
        "rules": [
            ("Frio All", None, "Frio All", None, "CTN", 2, 5, "percent_cashback", 0.8, "%"),
            ("Frio All", None, "Frio All", None, "CTN", 5, 10, "percent_cashback", 1.6, "%"),
            ("Frio All", None, "Frio All", None, "CTN", 10, None, "percent_cashback", 2.4, "%"),
            ("Bites GT", None, "Bites GT", None, "CTN", 2, 5, "percent_cashback", 0.72, "%"),
            ("Bites GT", None, "Bites GT", None, "CTN", 5, 10, "percent_cashback", 1.45, "%"),
            ("Bites GT", None, "Bites GT", None, "CTN", 10, None, "percent_cashback", 2.19, "%"),
            ("Pino GT All", None, "Pino GT All", None, "CTN", 2, 5, "percent_cashback", 1.22, "%"),
            ("Pino GT All", None, "Pino GT All", None, "CTN", 5, 10, "percent_cashback", 2.44, "%"),
            ("Pino GT All", None, "Pino GT All", None, "CTN", 10, None, "percent_cashback", 3.66, "%"),
            ("Zuper 20x30RCG", None, "Zuper 20x30RCG", None, "CTN", 2, 5, "percent_cashback", 0.9, "%"),
            ("Zuper 20x30RCG", None, "Zuper 20x30RCG", None, "CTN", 5, 10, "percent_cashback", 1.88, "%"),
            ("Zuper 20x30RCG", None, "Zuper 20x30RCG", None, "CTN", 10, None, "percent_cashback", 2.82, "%"),
            ("Zuper 20x40 BAG", None, "Zuper 20x40 BAG", None, "CTN", 2, 5, "percent_cashback", 0.83, "%"),
            ("Zuper 20x40 BAG", None, "Zuper 20x40 BAG", None, "CTN", 5, 10, "percent_cashback", 1.66, "%"),
            ("Zuper 20x40 BAG", None, "Zuper 20x40 BAG", None, "CTN", 10, None, "percent_cashback", 2.49, "%"),
            ("Zuper Jar 100PC", None, "Zuper Jar 100PC", None, "CTN", 2, 5, "percent_cashback", 0.7, "%"),
            ("Zuper Jar 100PC", None, "Zuper Jar 100PC", None, "CTN", 5, 10, "percent_cashback", 1.4, "%"),
            ("Zuper Jar 100PC", None, "Zuper Jar 100PC", None, "CTN", 10, None, "percent_cashback", 2.1, "%"),
        ],
    },
    {
        "kode_program": "TP-DARYA-VARIA-TORNADO-2026",
        "nama_program": "Memo Program TORNADO Natur-E RSD Downline 2026",
        "principal_name": "Darya-Varia Laboratoria / PT Anugerah Pharmindo Lestari",
        "perusahaan_name": "PT Budimas Makmur Mulia",
        "periode_mulai": date(2026, 1, 1),
        "periode_selesai": date(2026, 12, 31),
        "channel": "RSD",
        "objective": "Sales generator; budget charging discount; all outlet.",
        "source_note": "Input dari foto memo Program TORNADO Darya-Varia.",
        "rules": [],
    },
    {
        "kode_program": "TP-DOLPHIN-NATURE-DISKON-REGULER-2026",
        "nama_program": "Pengajuan Diskon Reguler Produk Dolphin Natur-E 2026",
        "principal_name": "Dolphin / Darya-Varia",
        "perusahaan_name": "PT Budimas Makmur Mulia",
        "periode_mulai": date(2026, 1, 1),
        "periode_selesai": date(2026, 12, 31),
        "channel": None,
        "objective": "Diskon reguler per produk.",
        "source_note": "Input dari foto Pengajuan Diskon Reguler 5.88%.",
        "rules": [
            ("NATUR-E 100", "NATUR-E 100", None, "NATUR E SKIN START FACE CREAM (GN)", "PCS", 1, None, "percent_discount", 15, "%"),
            ("NATUR-E 100", "NATUR-E 100", None, "NATUR E SKIN START HBL MOIST 100 ML (GN)", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E 100", "NATUR-E 100", None, "NATUR E SKIN START HBL MOIST 245 ML (DVL)", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E 300", "NATUR-E 300", None, "NATUR E ACT BEAUTY PROTECT&GLOW 100", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E 300", "NATUR-E 300", None, "NATUR E ACT BEAUTY PROTECT&GLOW 245", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E 300", "NATUR-E 300", None, "NATUR E ACT BEAUTY PROTECT&GLOW 245 (RB)", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR E ADVANCED HAND & BODY SERUM 100ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED HAND & BODY SERUM 180ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED I B ESSENCE TONER 100ML", "PCS", 1, None, "percent_discount", 15, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED INT DC FACIAL WASH 50ML", "PCS", 1, None, "percent_discount", 15, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED INT FIRMING SERUM 20ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED INT MOIST GEL 30ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E ADVANCE", "NATUR-E ADVANCE", None, "NATUR-E ADVANCED INT UL SUN PROTECT 40ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("NATUR-E CG", "NATUR-E CG", None, "NATUR-E CERAGLOW MOISTURIZER 30 ML", "PCS", 1, None, "percent_discount", 20, "%"),
            ("NATUR-E CG", "NATUR-E CG", None, "NATUR-E CERAGLOW SERUM 20 ML", "PCS", 1, None, "percent_discount", 20, "%"),
            ("NATUR-E HG", "NATUR-E HG", None, "NATUR-E HYALUGLOW MOISTURIZER 30 ML", "PCS", 1, None, "percent_discount", 20, "%"),
            ("NATUR-E HG", "NATUR-E HG", None, "NATUR-E HYALUGLOW SERUM 20 ML", "PCS", 1, None, "percent_discount", 20, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE HAND & BODY SERUM 180 ML", "PCS", 1, None, "percent_discount", 5, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE RAD CLARIFYING TONER 100ML", "PCS", 1, None, "percent_discount", 15, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE RAD MIR BOOSTER SERUM 20ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE RAD MIR MOIST GEL 30ML", "PCS", 1, None, "percent_discount", 10, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE RAD PURIF FACIAL WASH 50ML", "PCS", 1, None, "percent_discount", 15, "%"),
            ("Natur-E White", "Natur-E White", None, "NATUR-E WHITE RAD UL SUN PROTECTION 40ML", "PCS", 1, None, "percent_discount", 10, "%"),
        ],
    },
]


def build_engine():
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASS", "")
    host = os.environ.get("DB_HOST", "127.0.0.1")
    port = os.environ.get("DB_PORT", "5432")
    database = os.environ.get("DB_NAME", "budimas-dev")
    return create_engine(f"postgresql+pg8000://{user}:{password}@{host}:{port}/{database}")


def ensure_tables(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trade_promo_program (
            id SERIAL PRIMARY KEY,
            kode_program VARCHAR(80) UNIQUE NOT NULL,
            nama_program VARCHAR(255) NOT NULL,
            principal_name VARCHAR(255),
            perusahaan_name VARCHAR(255),
            periode_mulai DATE,
            periode_selesai DATE,
            channel VARCHAR(80),
            objective TEXT,
            status VARCHAR(30) NOT NULL DEFAULT 'active',
            source_note TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS trade_promo_program_rule (
            id SERIAL PRIMARY KEY,
            program_id INTEGER NOT NULL REFERENCES trade_promo_program(id) ON DELETE CASCADE,
            rule_group VARCHAR(160),
            brand VARCHAR(160),
            subbrand VARCHAR(160),
            product_name VARCHAR(255),
            uom VARCHAR(30) NOT NULL DEFAULT 'CTN',
            min_qty NUMERIC(12, 3) NOT NULL DEFAULT 0,
            max_qty NUMERIC(12, 3),
            max_exclusive BOOLEAN NOT NULL DEFAULT TRUE,
            benefit_type VARCHAR(40) NOT NULL,
            benefit_value NUMERIC(14, 4) NOT NULL,
            benefit_unit VARCHAR(40),
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_trade_promo_program_rule_program
        ON trade_promo_program_rule(program_id)
    """))


def seed_program(conn, program):
    program_id = conn.execute(
        text("""
            INSERT INTO trade_promo_program (
                kode_program, nama_program, principal_name, perusahaan_name,
                periode_mulai, periode_selesai, channel, objective, status,
                source_note, updated_at
            )
            VALUES (
                :kode_program, :nama_program, :principal_name, :perusahaan_name,
                :periode_mulai, :periode_selesai, :channel, :objective, 'active',
                :source_note, CURRENT_TIMESTAMP
            )
            ON CONFLICT (kode_program) DO UPDATE SET
                nama_program = EXCLUDED.nama_program,
                principal_name = EXCLUDED.principal_name,
                perusahaan_name = EXCLUDED.perusahaan_name,
                periode_mulai = EXCLUDED.periode_mulai,
                periode_selesai = EXCLUDED.periode_selesai,
                channel = EXCLUDED.channel,
                objective = EXCLUDED.objective,
                status = EXCLUDED.status,
                source_note = EXCLUDED.source_note,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """),
        {
            "kode_program": program["kode_program"],
            "nama_program": program["nama_program"],
            "principal_name": program["principal_name"],
            "perusahaan_name": program["perusahaan_name"],
            "periode_mulai": program["periode_mulai"],
            "periode_selesai": program["periode_selesai"],
            "channel": program["channel"],
            "objective": program["objective"],
            "source_note": program["source_note"],
        },
    ).scalar_one()

    conn.execute(text("DELETE FROM trade_promo_program_rule WHERE program_id = :program_id"), {"program_id": program_id})
    for rule in program["rules"]:
        conn.execute(
            text("""
                INSERT INTO trade_promo_program_rule (
                    program_id, rule_group, brand, subbrand, product_name, uom,
                    min_qty, max_qty, max_exclusive, benefit_type, benefit_value,
                    benefit_unit, notes
                )
                VALUES (
                    :program_id, :rule_group, :brand, :subbrand, :product_name, :uom,
                    :min_qty, :max_qty, TRUE, :benefit_type, :benefit_value,
                    :benefit_unit, :notes
                )
            """),
            {
                "program_id": program_id,
                "rule_group": rule[0],
                "brand": rule[1],
                "subbrand": rule[2],
                "product_name": rule[3],
                "uom": rule[4],
                "min_qty": rule[5],
                "max_qty": rule[6],
                "benefit_type": rule[7],
                "benefit_value": rule[8],
                "benefit_unit": rule[9],
                "notes": None,
            },
        )
    return program_id, len(program["rules"])


def main():
    parser = argparse.ArgumentParser(description="Seed trade promo programs from manual promo sheets.")
    parser.add_argument("--apply", action="store_true", help="Commit the seed. Without this flag, changes are rolled back.")
    args = parser.parse_args()

    engine = build_engine()
    stats = []
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            ensure_tables(conn)
            for program in PROGRAMS:
                program_id, rule_count = seed_program(conn, program)
                stats.append({"id": program_id, "kode_program": program["kode_program"], "rules": rule_count})
            if args.apply:
                trans.commit()
                mode = "APPLIED"
            else:
                trans.rollback()
                mode = "DRY_RUN_ROLLBACK"
        except Exception:
            trans.rollback()
            raise

    print({"mode": mode, "programs": stats, "total_rules": sum(item["rules"] for item in stats)})


if __name__ == "__main__":
    main()
