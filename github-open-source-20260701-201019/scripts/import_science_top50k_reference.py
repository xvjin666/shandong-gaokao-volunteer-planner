# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "user_science_top50k_excel_2026_reference"
SOURCE_NAME = "用户提供 Excel：理科5万名前.xlsx"
SOURCE_TYPE = "user_curated_excel_reference"
CONFIDENCE = "user_curated_reference"
NOTE = "用户提供的理科5万名前 Excel 补充数据；用于补齐展示字段，正式填报前仍需以院校官方招生计划、推免公示和学科建设公开信息复核。"
TODAY = datetime.now().strftime("%Y-%m-%d")


DISCIPLINE_FIELDS = [
    "school_name",
    "major_keywords",
    "discipline",
    "assessment_grade",
    "postgraduate_recommend_rate",
    "source",
    "source_url",
    "updated_at",
    "assessment_round",
    "discipline_code",
    "source_id",
    "source_type",
    "confidence",
    "note",
]

RATE_FIELDS = [
    "rank",
    "school_level",
    "school_name",
    "school_aliases",
    "cohort",
    "recommend_quota",
    "postgraduate_recommend_rate",
    "rate_display",
    "source",
    "source_url",
    "source_id",
    "source_type",
    "confidence",
    "updated_at",
    "note",
]

PLAN_FIELDS = [
    "school_code",
    "school_name",
    "major_code",
    "major_name",
    "major_aliases",
    "plan_count_2026",
    "simulated_rank",
    "source",
    "source_id",
    "source_type",
    "confidence",
    "updated_at",
    "note",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import user-provided science top-50k reference workbook.")
    parser.add_argument("--source", default="理科5万名前.xlsx")
    parser.add_argument("--discipline-output", default="data/curated/discipline_quality.csv")
    parser.add_argument("--rate-output", default="data/curated/postgraduate_recommend_rates.csv")
    parser.add_argument("--plan-output", default="data/curated/science_top50k_reference.csv")
    parser.add_argument("--discipline-sources", default="data/curated/discipline_quality_sources.json")
    parser.add_argument("--rate-sources", default="data/curated/postgraduate_recommend_rate_sources.json")
    args = parser.parse_args()

    source_path = (ROOT / args.source).resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    sheets = pd.read_excel(source_path, sheet_name=None)
    rows = pd.concat([frame for frame in sheets.values() if not frame.empty], ignore_index=True)
    rows = rows.dropna(how="all")
    rows = rows[rows.get("院校名称").notna() & rows.get("26专业名称").notna()]

    backup_dir = ROOT / "backups" / f"science-top50k-import-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    discipline_path = ROOT / args.discipline_output
    rate_path = ROOT / args.rate_output
    plan_path = ROOT / args.plan_output
    for path in (discipline_path, rate_path, plan_path):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)

    existing_discipline = read_csv(discipline_path, DISCIPLINE_FIELDS)
    existing_rates = read_csv(rate_path, RATE_FIELDS)

    discipline_rows = merge_rows(
        existing_discipline,
        build_discipline_rows(rows),
        key_fields=("school_name", "assessment_round", "discipline", "assessment_grade", "major_keywords", "source_id"),
        fields=DISCIPLINE_FIELDS,
    )
    rate_rows = merge_rates(existing_rates, build_rate_rows(rows))
    plan_rows = build_plan_rows(rows)

    write_csv(discipline_path, DISCIPLINE_FIELDS, discipline_rows)
    write_csv(rate_path, RATE_FIELDS, rate_rows)
    write_csv(plan_path, PLAN_FIELDS, plan_rows)
    update_source_manifest(ROOT / args.discipline_sources, "discipline", len(discipline_rows) - len(existing_discipline), source_path)
    update_source_manifest(ROOT / args.rate_sources, "rate", len(rate_rows) - len(existing_rates), source_path)

    print(json.dumps({
        "source": str(source_path),
        "input_rows": int(len(rows)),
        "discipline_existing": len(existing_discipline),
        "discipline_total": len(discipline_rows),
        "discipline_added": len(discipline_rows) - len(existing_discipline),
        "rates_existing": len(existing_rates),
        "rates_total": len(rate_rows),
        "rates_added": len(rate_rows) - len(existing_rates),
        "plan_rows": len(plan_rows),
        "backup_dir": str(backup_dir),
    }, ensure_ascii=False, indent=2))


def read_csv(path: Path, fields: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {field: str(row.get(field, "") or "").strip() for field in fields}
            for row in reader
            if any(str(value or "").strip() for value in row.values())
        ]


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def merge_rows(
    existing: list[dict[str, str]],
    additions: list[dict[str, str]],
    *,
    key_fields: tuple[str, ...],
    fields: list[str],
) -> list[dict[str, str]]:
    result = list(existing)
    seen = {tuple(row.get(field, "") for field in key_fields) for row in existing}
    for row in additions:
        key = tuple(row.get(field, "") for field in key_fields)
        if key in seen:
            continue
        result.append({field: row.get(field, "") for field in fields})
        seen.add(key)
    return result


def merge_rates(existing: list[dict[str, str]], additions: list[dict[str, str]]) -> list[dict[str, str]]:
    result = list(existing)
    known = set()
    for row in existing:
        names = [row.get("school_name", ""), *str(row.get("school_aliases", "")).split("|")]
        known.update(normalize_school(name) for name in names if normalize_school(name))
    for row in additions:
        aliases = [row.get("school_name", ""), *str(row.get("school_aliases", "")).split("|")]
        normalized = {normalize_school(name) for name in aliases if normalize_school(name)}
        if known.intersection(normalized):
            continue
        result.append({field: row.get(field, "") for field in RATE_FIELDS})
        known.update(normalized)
    return result


def build_discipline_rows(rows: pd.DataFrame) -> list[dict[str, str]]:
    grouped: OrderedDict[tuple[str, str, str, str], dict[str, object]] = OrderedDict()
    for _, row in rows.iterrows():
        school = clean(row.get("院校名称"))
        category = clean(row.get("专业类别"))
        if not school or not category:
            continue
        for column, round_name, source_id in (
            ("第四轮学科评估", "第四轮", f"{SOURCE_ID}_fourth_round"),
            ("第五轮学科评估（待查）", "第五轮", f"{SOURCE_ID}_fifth_round_pending"),
        ):
            grade = clean(row.get(column))
            if not is_grade(grade):
                continue
            discipline = infer_discipline(row, category)
            key = (school, round_name, discipline, grade)
            entry = grouped.setdefault(key, {
                "school_name": school,
                "discipline": discipline,
                "assessment_grade": grade,
                "assessment_round": round_name,
                "source_id": source_id,
                "keywords": OrderedDict(),
            })
            for keyword in major_keywords(row, category, discipline):
                entry["keywords"].setdefault(keyword, None)

    output: list[dict[str, str]] = []
    for entry in grouped.values():
        keywords = list(entry["keywords"].keys())
        output.append({
            "school_name": str(entry["school_name"]),
            "major_keywords": ",".join(keywords[:80]),
            "discipline": str(entry["discipline"]),
            "assessment_grade": str(entry["assessment_grade"]),
            "postgraduate_recommend_rate": "",
            "source": SOURCE_NAME,
            "source_url": "",
            "updated_at": TODAY,
            "assessment_round": str(entry["assessment_round"]),
            "discipline_code": "",
            "source_id": str(entry["source_id"]),
            "source_type": SOURCE_TYPE,
            "confidence": CONFIDENCE,
            "note": NOTE,
        })
    return output


def build_rate_rows(rows: pd.DataFrame) -> list[dict[str, str]]:
    output: OrderedDict[str, dict[str, str]] = OrderedDict()
    for _, row in rows.iterrows():
        school = clean(row.get("院校名称"))
        if not school or school in output:
            continue
        rate = percent_value(row.get("保研率"))
        if rate is None:
            continue
        aliases = OrderedDict((name, None) for name in [school, base_school_name(school)] if name)
        output[school] = {
            "rank": int_text(row.get("院校排名")),
            "school_level": clean(row.get("院校档次")),
            "school_name": school,
            "school_aliases": "|".join(aliases.keys()),
            "cohort": "Excel未标注届别",
            "recommend_quota": "",
            "postgraduate_recommend_rate": f"{rate:.4g}",
            "rate_display": f"{rate:.2f}%",
            "source": SOURCE_NAME,
            "source_url": "",
            "source_id": f"{SOURCE_ID}_postgraduate_rate",
            "source_type": SOURCE_TYPE,
            "confidence": CONFIDENCE,
            "updated_at": TODAY,
            "note": NOTE,
        }
    return list(output.values())


def build_plan_rows(rows: pd.DataFrame) -> list[dict[str, str]]:
    output: OrderedDict[tuple[str, str, str, str], dict[str, str]] = OrderedDict()
    for _, row in rows.iterrows():
        school = clean(row.get("院校名称"))
        major = clean(row.get("26专业名称"))
        if not school or not major:
            continue
        plan_count = int_text(row.get("2026计划"))
        if not plan_count:
            continue
        aliases = OrderedDict()
        for value in (major, clean(row.get("25专业信息")), base_major_name(major), base_major_name(clean(row.get("25专业信息")))):
            if value:
                aliases.setdefault(value, None)
        key = (clean(row.get("院校代码")), school, clean(row.get("专业代码")), major)
        output[key] = {
            "school_code": clean(row.get("院校代码")),
            "school_name": school,
            "major_code": clean(row.get("专业代码")),
            "major_name": major,
            "major_aliases": "|".join(aliases.keys()),
            "plan_count_2026": plan_count,
            "simulated_rank": int_text(row.get("模拟位次")),
            "source": SOURCE_NAME,
            "source_id": f"{SOURCE_ID}_plan_count_2026",
            "source_type": SOURCE_TYPE,
            "confidence": CONFIDENCE,
            "updated_at": TODAY,
            "note": NOTE,
        }
    return list(output.values())


def major_keywords(row: pd.Series, category: str, discipline: str) -> list[str]:
    keywords: OrderedDict[str, None] = OrderedDict()
    for value in (category, discipline, clean(row.get("26专业名称")), clean(row.get("25专业信息")), base_major_name(clean(row.get("26专业名称"))), base_major_name(clean(row.get("25专业信息")))):
        add_keyword(keywords, value)
    for column in ("本专业硕士点", "本专业博士点"):
        for part in split_parts(clean(row.get(column))):
            add_keyword(keywords, part)
            add_keyword(keywords, part.replace("（专）", "").replace("(专)", ""))
    for column in ("26专业名称", "25专业信息"):
        for part in split_parts(extract_parenthetical(clean(row.get(column)))):
            add_keyword(keywords, part)
    return list(keywords.keys())


def infer_discipline(row: pd.Series, category: str) -> str:
    for column in ("本专业博士点", "本专业硕士点"):
        parts = [
            part
            for part in split_parts(clean(row.get(column)))
            if part and "（专）" not in part and "(专)" not in part and len(part) >= 2
        ]
        if len(parts) == 1:
            return parts[0]
    return category


def add_keyword(target: OrderedDict[str, None], value: str) -> None:
    text = clean(value)
    if not text or len(text) < 2:
        return
    if text in {"专业", "方向", "校区", "含", "等专业", "理工类专业任选"}:
        return
    if len(text) > 80:
        return
    target.setdefault(text, None)


def split_parts(value: str) -> list[str]:
    text = clean(value)
    if not text:
        return []
    text = re.sub(r"[;；、，,/]", "|", text)
    text = re.sub(r"\s+", "", text)
    return [item.strip() for item in text.split("|") if item.strip()]


def extract_parenthetical(value: str) -> str:
    parts = re.findall(r"[（(]([^（）()]*)[）)]", clean(value))
    return "；".join(parts)


def base_major_name(value: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", clean(value)).strip()


def percent_value(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = clean(value).replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number <= 0:
        return None
    return number * 100 if number <= 1 else number


def int_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    try:
        number = float(str(value).strip())
    except ValueError:
        return ""
    if not math.isfinite(number):
        return ""
    return str(int(round(number)))


def clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def is_grade(value: str) -> bool:
    return value in {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-"}


def normalize_school(value: str) -> str:
    text = clean(value).replace("（", "(").replace("）", ")").replace(" ", "")
    return re.sub(r"\(校本部\)$", "", text)


def base_school_name(value: str) -> str:
    return re.sub(r"[（(].*?[）)]", "", clean(value)).strip()


def update_source_manifest(path: Path, kind: str, added_rows: int, source_path: Path) -> None:
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    sources = payload.setdefault("sources", [])
    source_id = f"{SOURCE_ID}_{kind}"
    sources = [source for source in sources if source.get("source_id") != source_id]
    sources.append({
        "source_id": source_id,
        "source": SOURCE_NAME,
        "source_type": SOURCE_TYPE,
        "confidence": CONFIDENCE,
        "local_path": str(source_path.relative_to(ROOT)),
        "structured_rows_added": added_rows,
        "updated_at": TODAY,
        "note": NOTE,
    })
    payload["sources"] = sources
    payload["generated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
