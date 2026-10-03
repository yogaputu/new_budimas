#!/usr/bin/env python3
"""Prepare conservative reviewed-candidate CSVs for customer mappings.

The input is ``customer_candidates.csv`` from the August staging exporter.
Only a single candidate with an equal normalized customer name is prefilled:

* target-branch candidate -> ``approve_exact``
* unique candidate in another branch -> ``approve_cross_branch``

Everything else remains in a separate manual-review CSV.  This tool does not
connect to or mutate any database.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path


REQUIRED_COLUMNS = {
    "source_system",
    "entity_type",
    "source_key_1",
    "source_key_2",
    "source_name",
    "target_branch_candidate_count",
    "target_branch_candidate_ids",
    "target_branch_candidate_names",
    "target_global_candidate_count",
    "target_global_candidate_ids",
    "target_global_candidate_names",
    "review_status",
}
OUTPUT_FIELDS = [
    "source_system",
    "entity_type",
    "source_key_1",
    "source_key_2",
    "source_name",
    "review_status",
    "suggested_target_id",
    "decision",
    "approved_target_id",
    "reviewer_note",
    "candidate_scope",
    "name_match",
]


def normalized_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(character for character in text.casefold() if character.isalnum())


def single_id(raw: str) -> str:
    values = [part.strip() for part in (raw or "").split(",") if part.strip()]
    return values[0] if len(values) == 1 and values[0].isdigit() else ""


def target_name(raw: str, is_global: bool) -> str:
    # Global candidate values include an audit-only "[cabang N]" suffix.
    value = (raw or "").strip()
    if is_global:
        value = re.split(r"\s*\[cabang\s+", value, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    return value


def output_row(row: dict[str, str], target_id: str, decision: str, scope: str, match: bool) -> dict[str, str]:
    return {
        "source_system": row["source_system"],
        "entity_type": "customer",
        "source_key_1": row["source_key_1"],
        "source_key_2": "",
        "source_name": row.get("source_name", ""),
        "review_status": row.get("review_status", ""),
        "suggested_target_id": target_id,
        "decision": decision,
        "approved_target_id": target_id if decision else "",
        "reviewer_note": "" if match else "Nama customer sumber dan kandidat target belum cocok; review manual diperlukan.",
        "candidate_scope": scope,
        "name_match": "yes" if match else "no",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CSV customer candidates dari exporter.")
    parser.add_argument("--approved-output", required=True, help="CSV prefilled yang siap dipreflight.")
    parser.add_argument("--manual-output", required=True, help="CSV kandidat yang harus dicek manual.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    approved_path = Path(args.approved_output).expanduser().resolve()
    manual_path = Path(args.manual_output).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input tidak ditemukan: {input_path}")
    if approved_path == manual_path:
        raise SystemExit("Output approved dan manual harus berbeda.")
    for path in (approved_path, manual_path):
        if path.exists():
            raise SystemExit(f"Menolak menimpa file yang sudah ada: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)

    counts: Counter[str] = Counter()
    with input_path.open(encoding="utf-8-sig", newline="") as source_handle:
        reader = csv.DictReader(source_handle)
        if reader.fieldnames is None:
            raise SystemExit("Input tidak memiliki header.")
        missing = sorted(REQUIRED_COLUMNS - set(reader.fieldnames))
        if missing:
            raise SystemExit(f"Kolom input kurang: {', '.join(missing)}")
        with approved_path.open("w", encoding="utf-8-sig", newline="") as approved_handle, manual_path.open(
            "w", encoding="utf-8-sig", newline=""
        ) as manual_handle:
            approved_writer = csv.DictWriter(approved_handle, fieldnames=OUTPUT_FIELDS)
            manual_writer = csv.DictWriter(manual_handle, fieldnames=OUTPUT_FIELDS)
            approved_writer.writeheader()
            manual_writer.writeheader()
            for row in reader:
                status = row.get("review_status", "")
                source_name = normalized_name(row.get("source_name", ""))
                if status == "candidate_unique_in_target_branch":
                    candidate_id = single_id(row.get("target_branch_candidate_ids", ""))
                    candidate_name = target_name(row.get("target_branch_candidate_names", ""), is_global=False)
                    decision = "approve_exact"
                    scope = "target_branch"
                elif status == "only_outside_target_branch_requires_policy":
                    candidate_id = single_id(row.get("target_global_candidate_ids", ""))
                    candidate_name = target_name(row.get("target_global_candidate_names", ""), is_global=True)
                    decision = "approve_cross_branch"
                    scope = "cross_branch"
                else:
                    candidate_id = ""
                    candidate_name = ""
                    decision = ""
                    scope = "manual"

                match = bool(source_name and source_name == normalized_name(candidate_name))
                if candidate_id and match:
                    approved_writer.writerow(output_row(row, candidate_id, decision, scope, match=True))
                    counts[f"approved_{scope}"] += 1
                else:
                    suggested = candidate_id
                    manual_writer.writerow(output_row(row, suggested, "", scope, match=False))
                    counts[f"manual_{status}"] += 1

    summary = {
        "input": str(input_path),
        "approved_output": str(approved_path),
        "manual_output": str(manual_path),
        "counts": dict(sorted(counts.items())),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
