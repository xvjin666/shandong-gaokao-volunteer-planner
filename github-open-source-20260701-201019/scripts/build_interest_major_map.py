from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path


os.environ["GAOKAO_DISABLE_INTEREST_MAJOR_MAP"] = "1"

from gaokao_decision.database import connect, fetch_admissions
from gaokao_decision.scoring import (
    INTEREST_LABELS,
    INTEREST_MAJOR_MAP_VERSION,
    _interest_match_level,
)


CATALOG_PATH = Path("data/processed/undergraduate_majors_2026.json")
CATEGORY_LABEL_ALIASES = {
    "计算机类": ("计算机",),
    "统计学类": ("统计",),
    "金融学类": ("金融",),
    "新闻传播学类": ("新闻传播",),
    "设计学类": ("设计",),
    "体育学类": ("体育运动",),
    "食品科学与工程类": ("食品科学",),
    "图书情报与档案管理类": ("图书情报",),
}


def build_interest_major_map(db_path: Path, overrides_path: Path | None = None) -> dict[str, object]:
    with connect(db_path) as connection:
        records = fetch_admissions(connection)

    major_names = sorted({record.major_name for record in records})
    overrides = _load_manual_overrides(overrides_path)
    official_labels = _official_direct_labels_by_major(CATALOG_PATH)
    majors: dict[str, dict[str, list[str]]] = {}
    interest_summary: dict[str, dict[str, int]] = {}

    for major_name in major_names:
        direct: list[str] = []
        related: list[str] = []
        for interest in INTEREST_LABELS:
            level = _interest_match_level(interest, major_name)
            if level == "direct":
                direct.append(interest)
            elif level == "related":
                related.append(interest)
        for interest in _official_labels_for_admission_major(major_name, official_labels):
            if interest not in direct:
                direct.append(interest)
        related = [interest for interest in related if interest not in direct]
        if major_name in overrides:
            direct, related = overrides[major_name]
        majors[major_name] = {
            "direct": direct,
            "related": related,
        }

    for interest in INTEREST_LABELS:
        direct_count = sum(1 for entry in majors.values() if interest in entry["direct"])
        related_count = sum(1 for entry in majors.values() if interest in entry["related"])
        interest_summary[interest] = {
            "direct": direct_count,
            "related": related_count,
            "total": direct_count + related_count,
        }

    unmapped = [
        major
        for major, entry in majors.items()
        if not entry["direct"] and not entry["related"]
    ]

    return {
        "version": INTEREST_MAJOR_MAP_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_db": str(db_path),
        "interest_count": len(INTEREST_LABELS),
        "major_count": len(major_names),
        "mapped_major_count": len(major_names) - len(unmapped),
        "unmapped_major_count": len(unmapped),
        "manual_override_count": len(overrides),
        "interests": interest_summary,
        "majors": majors,
    }


def _load_manual_overrides(overrides_path: Path | None) -> dict[str, tuple[list[str], list[str]]]:
    if not overrides_path or not overrides_path.exists():
        return {}
    labels = set(INTEREST_LABELS)
    overrides: dict[str, tuple[list[str], list[str]]] = {}
    with overrides_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            major_name = str(row.get("major_name") or "").strip()
            if not major_name:
                continue
            action = str(row.get("action") or "map").strip()
            if action != "map":
                continue
            direct = _split_labels(row.get("direct_interests"), labels)
            related = _split_labels(row.get("related_interests"), labels)
            if direct or related:
                overrides[major_name] = (direct, [item for item in related if item not in direct])
    return overrides


def _official_direct_labels_by_major(catalog_path: Path) -> dict[str, list[str]]:
    if not catalog_path.exists():
        return {}
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows = payload.get("majors")
    if not isinstance(rows, list):
        return {}

    labels = set(INTEREST_LABELS)
    result: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        direct: list[str] = []
        category = str(row.get("category") or "").strip()
        discipline = str(row.get("discipline") or "").strip()
        candidates = [
            name,
            category,
            category.removesuffix("类"),
            discipline,
            *CATEGORY_LABEL_ALIASES.get(category, ()),
        ]
        for candidate in candidates:
            if candidate and candidate in labels and candidate not in direct:
                direct.append(candidate)
        if direct:
            result[name] = direct
    return result


def _official_labels_for_admission_major(
    major_name: str,
    official_labels: dict[str, list[str]],
) -> list[str]:
    normalized = _normalize_admission_major_name(major_name)
    if normalized in official_labels:
        return official_labels[normalized]
    for official_name, labels in official_labels.items():
        if normalized.startswith(official_name):
            return labels
    return []


def _normalize_admission_major_name(major_name: str) -> str:
    text = str(major_name or "").strip()
    for left, right in (("(", ")"), ("（", "）")):
        if left in text:
            text = text.split(left, 1)[0].strip()
    return text


def _split_labels(value: object, labels: set[str]) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    for separator in ("、", "|", "，", ",", ";", "；", "/"):
        text = text.replace(separator, "|")
    result: list[str] = []
    for part in (item.strip() for item in text.split("|")):
        if part and part in labels and part not in result:
            result.append(part)
    return result


def write_audit_files(payload: dict[str, object], audit_path: Path, unmapped_path: Path) -> None:
    majors = payload["majors"]
    if not isinstance(majors, dict):
        raise TypeError("payload majors must be a dict")

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow([
            "interest",
            "direct_count",
            "related_count",
            "total_count",
            "direct_examples",
            "related_examples",
        ])
        for interest in INTEREST_LABELS:
            direct_examples = [
                major
                for major, entry in majors.items()
                if interest in entry.get("direct", ())
            ][:20]
            related_examples = [
                major
                for major, entry in majors.items()
                if interest in entry.get("related", ())
            ][:20]
            writer.writerow([
                interest,
                sum(1 for entry in majors.values() if interest in entry.get("direct", ())),
                sum(1 for entry in majors.values() if interest in entry.get("related", ())),
                sum(
                    1
                    for entry in majors.values()
                    if interest in entry.get("direct", ()) or interest in entry.get("related", ())
                ),
                "、".join(direct_examples),
                "、".join(related_examples),
            ])

    with unmapped_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["major_name"])
        for major, entry in majors.items():
            if not entry.get("direct") and not entry.get("related"):
                writer.writerow([major])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build audited interest-to-major mapping.")
    parser.add_argument("--db", default="data/local/gaokao.sqlite")
    parser.add_argument("--output", default="data/processed/interest_major_map.json")
    parser.add_argument("--audit", default="data/processed/interest_major_map_audit.csv")
    parser.add_argument("--unmapped", default="data/processed/interest_major_unmapped_majors.csv")
    parser.add_argument("--overrides", default="data/curated/interest_major_overrides.csv")
    args = parser.parse_args()

    payload = build_interest_major_map(Path(args.db), Path(args.overrides))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_audit_files(payload, Path(args.audit), Path(args.unmapped))

    print(
        json.dumps(
            {
                "output": str(output_path),
                "audit": args.audit,
                "unmapped": args.unmapped,
                "major_count": payload["major_count"],
                "mapped_major_count": payload["mapped_major_count"],
                "unmapped_major_count": payload["unmapped_major_count"],
                "interest_count": payload["interest_count"],
                "manual_override_count": payload["manual_override_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
