#!/usr/bin/env python3
"""Create a reviewable UOM synchronization plan from staged sales usage.

The plan is read-only: it does not alter ``produk_uom``.  It lists only SKUs
used by August sales that are not ``uom_ready`` and describes the required
base/pack UOM expected from SQL Server.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path


REQUIRED_COLUMNS = {
    "source_system",
    "source_key_1",
    "source_key_2",
    "source_name",
    "source_base_uom",
    "source_pack_uom",
    "source_pack_factor",
    "target_product_count",
    "target_product_ids",
    "target_uom_configuration",
    "review_status",
}
OUTPUT_FIELDS = [
    "source_system",
    "principal_code",
    "sku",
    "source_product_name",
    "target_product_ids",
    "source_base_uom",
    "source_pack_uom",
    "source_pack_factor",
    "current_target_uom_configuration",
    "readiness_status",
    "recommended_action",
    "apply_after",
]


def recommendation(status: str) -> tuple[str, str]:
    if status == "missing_base_uom":
        return (
            "Pastikan UOM level 1 sesuai source_base_uom dengan faktor 1, lalu validasi/atur UOM pack level 2.",
            "product mapping disetujui dan backup PostgreSQL tersedia",
        )
    if status == "missing_or_wrong_pack_uom":
        return (
            "Pastikan UOM level 2 sesuai source_pack_uom dengan faktor source_pack_factor; jangan mengubah qty transaksi.",
            "product mapping disetujui dan backup PostgreSQL tersedia",
        )
    if status == "product_missing":
        return (
            "Buat atau mapping produk target lebih dulu, kemudian buat UOM level 1 dan level 2 dari source.",
            "principal dan product mapping disetujui",
        )
    if status == "product_ambiguous":
        return (
            "Pilih satu produk target yang benar terlebih dahulu; jangan menyalin UOM ke kandidat ganda.",
            "product mapping manual disetujui",
        )
    return ("Review manual diperlukan.", "review UOM")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input tidak ditemukan: {input_path}")
    if output_path.exists():
        raise SystemExit(f"Menolak menimpa file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    rows = 0
    with input_path.open(encoding="utf-8-sig", newline="") as input_handle:
        reader = csv.DictReader(input_handle)
        if reader.fieldnames is None:
            raise SystemExit("Input tidak memiliki header.")
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise SystemExit(f"Kolom input kurang: {', '.join(missing)}")
        with output_path.open("w", encoding="utf-8-sig", newline="") as output_handle:
            writer = csv.DictWriter(output_handle, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            for row in reader:
                status = row.get("review_status", "")
                if status.startswith("uom_ready"):
                    continue
                action, apply_after = recommendation(status)
                writer.writerow(
                    {
                        "source_system": row["source_system"],
                        "principal_code": row["source_key_2"],
                        "sku": row["source_key_1"],
                        "source_product_name": row.get("source_name", ""),
                        "target_product_ids": row.get("target_product_ids", ""),
                        "source_base_uom": row.get("source_base_uom", ""),
                        "source_pack_uom": row.get("source_pack_uom", ""),
                        "source_pack_factor": row.get("source_pack_factor", ""),
                        "current_target_uom_configuration": row.get("target_uom_configuration", ""),
                        "readiness_status": status,
                        "recommended_action": action,
                        "apply_after": apply_after,
                    }
                )
                counts[status] += 1
                rows += 1
    print(json.dumps({"input": str(input_path), "output": str(output_path), "rows": rows, "by_status": dict(sorted(counts.items()))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
