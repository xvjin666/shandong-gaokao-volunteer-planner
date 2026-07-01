from __future__ import annotations

import re
from pathlib import Path

from .models import AdmissionRecord, ScoreRankRecord


MAJOR_FIELD = "专业代号及名称"
SCHOOL_FIELD = "院校代号及名称"
PLAN_FIELD = "投档计划数"
RANK_FIELD = "最低位次"
MAJOR_FIELDS = {MAJOR_FIELD, "专业"}
SCHOOL_FIELDS = {SCHOOL_FIELD, "院校"}
RANK_FIELDS = {RANK_FIELD, "投档最低位次"}


def load_regular_batch_round1_xls(path: str | Path, year: int, source_id: str) -> list[AdmissionRecord]:
    path = Path(path)
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Reading official SDZK .xls files requires pandas and xlrd.") from exc

    frame = pd.read_excel(path, header=None, dtype=str).fillna("")
    header_index, columns = _find_header(frame)
    rows = frame.iloc[header_index + 1 :]

    records: list[AdmissionRecord] = []
    for _, row in rows.iterrows():
        major_raw = _clean_cell(row.iloc[columns["major"]])
        school_raw = _clean_cell(row.iloc[columns["school"]])
        if not major_raw or not school_raw:
            continue
        if major_raw.startswith("注") or school_raw.startswith("注"):
            continue

        major_code, major_name = _split_prefixed_code(major_raw, expected_code_len=2)
        school_code, school_name = _split_prefixed_code(school_raw, expected_code_len=4)
        if not major_code or not school_code:
            continue

        plan_count = _to_int(row.iloc[columns["plan"]])
        min_rank = _to_int(row.iloc[columns["rank"]])
        if min_rank is None and plan_count is None:
            continue
        tags = _extract_tags(" ".join([major_name, school_name]))

        records.append(
            AdmissionRecord(
                year=year,
                source_id=source_id,
                school_code=school_code,
                school_name=school_name,
                major_code=major_code,
                major_name=major_name,
                min_score=None,
                min_rank=min_rank,
                plan_count=plan_count,
                subjects=_extract_subjects(major_name),
                school_type="中外合作" if "中外合作" in tags else "",
                tags=tags,
            )
        )

    return records


def load_summer_score_rank_xls(path: str | Path, year: int, source_id: str) -> list[ScoreRankRecord]:
    path = Path(path)
    try:
        import pandas as pd
    except ImportError:
        return _load_summer_score_rank_xls_with_xlrd(path, year, source_id)

    frame = pd.read_excel(path, header=None, dtype=str).fillna("")
    records: list[ScoreRankRecord] = []
    for _, row in frame.iterrows():
        score = _to_int(row.iloc[0])
        segment_count = _to_int(row.iloc[1]) if len(row) > 1 else None
        cumulative_count = _to_int(row.iloc[2]) if len(row) > 2 else None
        if score is None or segment_count is None or cumulative_count is None:
            continue
        records.append(
            ScoreRankRecord(
                year=year,
                source_id=source_id,
                score=score,
                segment_count=segment_count,
                cumulative_count=cumulative_count,
                subject_group="全体",
            )
        )
    return sorted(records, key=lambda item: item.score, reverse=True)


def _load_summer_score_rank_xls_with_xlrd(path: Path, year: int, source_id: str) -> list[ScoreRankRecord]:
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError("Reading official SDZK score-rank .xls files requires pandas or xlrd.") from exc

    book = xlrd.open_workbook(str(path))
    sheet = book.sheet_by_index(0)
    records: list[ScoreRankRecord] = []
    for row_index in range(sheet.nrows):
        row = sheet.row_values(row_index)
        if len(row) < 3:
            continue
        score = _to_int(row[0])
        segment_count = _to_int(row[1])
        cumulative_count = _to_int(row[2])
        if score is None or segment_count is None or cumulative_count is None:
            continue
        records.append(
            ScoreRankRecord(
                year=year,
                source_id=source_id,
                score=score,
                segment_count=segment_count,
                cumulative_count=cumulative_count,
                subject_group="全体",
            )
        )
    return sorted(records, key=lambda item: item.score, reverse=True)


def _find_header(frame) -> tuple[int, dict[str, int]]:
    for index, row in frame.iterrows():
        cells = [_clean_cell(value) for value in row.tolist()]
        major = _find_cell_index(cells, MAJOR_FIELDS)
        school = _find_cell_index(cells, SCHOOL_FIELDS)
        plan = _find_cell_index(cells, {PLAN_FIELD})
        rank = _find_cell_index(cells, RANK_FIELDS)
        if None not in {major, school, plan, rank}:
            return int(index), {
                "major": int(major),
                "school": int(school),
                "plan": int(plan),
                "rank": int(rank),
            }
    raise ValueError("Could not find SDZK table header row.")


def _find_cell_index(cells: list[str], candidates: set[str]) -> int | None:
    for index, cell in enumerate(cells):
        if cell in candidates:
            return index
    return None


def _split_prefixed_code(value: str, expected_code_len: int) -> tuple[str, str]:
    text = _clean_cell(value)
    if len(text) <= expected_code_len:
        return "", text
    code = text[:expected_code_len]
    name = text[expected_code_len:].strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", code):
        return "", text
    return code, name


SUBJECT_ORDER = ("物理", "化学", "生物", "思想政治", "历史", "地理")
SUBJECT_ALIASES = {
    "思想政治": ("思想政治", "政治"),
}
SUBJECT_REQUIREMENT_MARKERS = (
    "选考",
    "选科",
    "科目",
    "须选",
    "必选",
    "均须",
    "要求",
    "限",
)


def _extract_subjects(major_name: str) -> tuple[str, ...]:
    text = str(major_name or "")
    if "不限选考科目" in text or "不限" in text:
        return ("不限",)
    segments = _subject_requirement_segments(text)
    subjects: list[str] = []
    for segment in segments:
        for subject in SUBJECT_ORDER:
            aliases = SUBJECT_ALIASES.get(subject, (subject,))
            if any(alias in segment for alias in aliases) and subject not in subjects:
                subjects.append(subject)
    if subjects:
        return tuple(subjects)
    return ()


def _subject_requirement_segments(text: str) -> list[str]:
    segments: list[str] = []
    for match in re.finditer(r"[（(]([^）)]*)[）)]", text):
        segment = match.group(1)
        if any(marker in segment for marker in SUBJECT_REQUIREMENT_MARKERS):
            segments.append(segment)
    if any(marker in text for marker in SUBJECT_REQUIREMENT_MARKERS):
        segments.append(text)
    return segments


def _extract_tags(text: str) -> tuple[str, ...]:
    keywords = (
        "中外合作",
        "校企合作",
        "师范",
        "医学",
        "临床医学",
        "护理",
        "计算机",
        "软件",
        "人工智能",
        "电子",
        "电气",
        "自动化",
        "金融",
        "法学",
    )
    return tuple(keyword for keyword in keywords if keyword in text)


def _clean_cell(value: object) -> str:
    return str(value or "").replace("\u3000", " ").strip()


def _to_int(value: object) -> int | None:
    text = _clean_cell(value).replace(",", "")
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    top_match = re.fullmatch(r"前\s*(\d+)\s*名?", text)
    if top_match:
        return int(top_match.group(1))
    try:
        return int(text)
    except ValueError:
        return None
