from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path

from gaokao_decision.sdzk_parser import load_regular_batch_round1_xls
from gaokao_decision.validation import validate_records


FIELDS = (
    "year",
    "source_id",
    "school_code",
    "school_name",
    "major_code",
    "major_name",
    "min_score",
    "min_rank",
    "plan_count",
    "subjects",
    "province",
    "city",
    "school_level",
    "school_type",
    "tuition",
    "tags",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert SDZK official round-1 .xls to normalized CSV.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    records = load_regular_batch_round1_xls(args.input, args.year, args.source_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["subjects"] = "|".join(record.subjects)
            row["tags"] = "|".join(record.tags)
            writer.writerow({field: row.get(field) for field in FIELDS})

    report = validate_records(records)
    print(
        f"converted={len(records)} output={output} "
        f"missing_rank={report.missing_min_rank} missing_score={report.missing_min_score} "
        f"issues={len(report.issues)}"
    )


if __name__ == "__main__":
    main()

