from __future__ import annotations

import csv
from pathlib import Path
from collections import Counter
from typing import Iterable

from .models import AdmissionRecord, ScoreRankRecord


COLUMN_ALIASES = {
    "year": ("year", "年份"),
    "source_id": ("source_id", "来源", "数据来源"),
    "school_code": ("school_code", "院校代号", "院校代码", "学校代码"),
    "school_name": ("school_name", "院校名称", "学校名称"),
    "major_code": ("major_code", "专业代号", "专业代码"),
    "major_name": ("major_name", "专业名称", "专业"),
    "min_score": ("min_score", "最低分", "投档最低分"),
    "min_rank": ("min_rank", "最低位次", "投档最低位次", "位次"),
    "plan_count": ("plan_count", "计划数", "投档计划数", "招生计划"),
    "subjects": ("subjects", "选科要求", "科目要求"),
    "province": ("province", "省份"),
    "city": ("city", "城市", "办学地点"),
    "school_level": ("school_level", "院校层次", "学校层次"),
    "school_type": ("school_type", "办学性质", "学校性质"),
    "tuition": ("tuition", "学费"),
    "tags": ("tags", "标签", "备注"),
}


SCORE_RANK_COLUMN_ALIASES = {
    "year": ("year", "年份"),
    "source_id": ("source_id", "来源", "数据来源"),
    "score": ("score", "分数", "成绩"),
    "segment_count": ("segment_count", "本段人数", "本段", "同分人数", "人数"),
    "cumulative_count": ("cumulative_count", "累计人数", "累计", "累计位次", "最低位次"),
    "subject_group": ("subject_group", "科类", "类别", "选科组"),
}


def load_admissions(path: str | Path) -> list[AdmissionRecord]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return _load_csv(path)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _load_excel(path)
    if path.suffix.lower() == ".xls":
        raise ValueError(
            "The official .xls file should be archived first and converted to CSV/XLSX before import. "
            "This avoids silent parsing errors in old Excel formats."
        )
    raise ValueError(f"Unsupported admissions file: {path}")


def load_score_ranks(
    path: str | Path,
    year: int | None = None,
    source_id: str | None = None,
) -> list[ScoreRankRecord]:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return _load_score_rank_csv(path, year=year, source_id=source_id)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _load_score_rank_excel(path, year=year, source_id=source_id)
    raise ValueError(
        f"Unsupported score-rank file: {path}. Use CSV/XLSX for open data imports; "
        "use the SDZK parser command for archived official .xls files."
    )


def _load_csv(path: Path) -> list[AdmissionRecord]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_record_from_row(_normalize_row(row)) for row in reader]


def _load_score_rank_csv(
    path: Path,
    year: int | None = None,
    source_id: str | None = None,
) -> list[ScoreRankRecord]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [_score_rank_from_row(_normalize_score_rank_row(row), year, source_id) for row in reader]


def _load_excel(path: Path) -> list[AdmissionRecord]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Excel import requires pandas in the active Python environment.") from exc

    frame = pd.read_excel(path)
    rows = frame.fillna("").to_dict(orient="records")
    return [_record_from_row(_normalize_row(row)) for row in rows]


def _load_score_rank_excel(
    path: Path,
    year: int | None = None,
    source_id: str | None = None,
) -> list[ScoreRankRecord]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Excel import requires pandas in the active Python environment.") from exc

    frame = pd.read_excel(path)
    rows = frame.fillna("").to_dict(orient="records")
    return [_score_rank_from_row(_normalize_score_rank_row(row), year, source_id) for row in rows]


def _normalize_row(row: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    source = {str(key).strip(): value for key, value in row.items()}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in source:
                normalized[canonical] = source[alias]
                break
    return normalized


def _normalize_score_rank_row(row: dict[str, object]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    source = {str(key).strip(): value for key, value in row.items()}
    for canonical, aliases in SCORE_RANK_COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in source:
                normalized[canonical] = source[alias]
                break
    return normalized


def _record_from_row(row: dict[str, object]) -> AdmissionRecord:
    return AdmissionRecord(
        year=_to_int(row.get("year"), required=True),
        source_id=str(row.get("source_id") or "unknown_source").strip(),
        school_code=str(row.get("school_code") or "").strip(),
        school_name=str(row.get("school_name") or "").strip(),
        major_code=str(row.get("major_code") or "").strip(),
        major_name=str(row.get("major_name") or "").strip(),
        min_score=_to_int(row.get("min_score")),
        min_rank=_to_int(row.get("min_rank")),
        plan_count=_to_int(row.get("plan_count")),
        subjects=_split_terms(row.get("subjects")),
        province=str(row.get("province") or "").strip(),
        city=str(row.get("city") or "").strip(),
        school_level=str(row.get("school_level") or "").strip(),
        school_type=str(row.get("school_type") or "").strip(),
        tuition=_to_int(row.get("tuition")),
        tags=_split_terms(row.get("tags")),
    )


def _score_rank_from_row(
    row: dict[str, object],
    default_year: int | None = None,
    default_source_id: str | None = None,
) -> ScoreRankRecord:
    year = _to_int(row.get("year")) or default_year
    if year is None:
        raise ValueError("Score-rank row is missing required year.")
    return ScoreRankRecord(
        year=year,
        source_id=str(row.get("source_id") or default_source_id or "unknown_source").strip(),
        score=_to_int(row.get("score"), required=True),
        segment_count=_to_int(row.get("segment_count"), required=True),
        cumulative_count=_to_int(row.get("cumulative_count"), required=True),
        subject_group=str(row.get("subject_group") or "全体").strip() or "全体",
    )


def _split_terms(value: object) -> tuple[str, ...]:
    text = str(value or "").strip()
    if not text:
        return ()
    for separator in ("|", "、", "，", ",", ";", "；", "/"):
        text = text.replace(separator, "|")
    return tuple(part.strip() for part in text.split("|") if part.strip())


def _to_int(value: object, required: bool = False) -> int | None:
    if value is None or value == "":
        if required:
            raise ValueError("Required integer field is empty.")
        return None
    text = str(value).strip().replace(",", "")
    if text.endswith(".0"):
        text = text[:-2]
    try:
        return int(text)
    except ValueError:
        if required:
            raise
        return None


def group_by_option(records: Iterable[AdmissionRecord]) -> dict[str, list[AdmissionRecord]]:
    record_list = list(records)
    ambiguous_keys = ambiguous_stable_option_keys(record_list)
    grouped: dict[str, list[AdmissionRecord]] = {}
    for record in record_list:
        grouped.setdefault(option_group_key(record, ambiguous_keys), []).append(record)
    return grouped


def stable_option_key(record: AdmissionRecord) -> str:
    return option_base_key(record)


def option_base_key(record: AdmissionRecord) -> str:
    return "|".join(
        [
            record.school_code.strip(),
            _normalize_option_text(record.major_name),
            record.school_type.strip(),
        ]
    )


def ambiguous_stable_option_keys(records: Iterable[AdmissionRecord]) -> set[str]:
    counts = Counter((option_base_key(record), record.year) for record in records)
    return {key for (key, _year), count in counts.items() if count > 1}


def option_group_key(record: AdmissionRecord, ambiguous_keys: set[str]) -> str:
    base_key = option_base_key(record)
    if base_key in ambiguous_keys:
        return f"{base_key}|{record.option_key}"
    return base_key


def _normalize_option_text(value: str) -> str:
    return "".join(str(value).split())
