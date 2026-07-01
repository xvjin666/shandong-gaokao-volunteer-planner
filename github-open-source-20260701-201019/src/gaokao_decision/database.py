from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .models import AdmissionRecord, ScoreRankRecord
from .validation import ValidationReport, validate_records


SCHEMA_VERSION = 2


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS metadata (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  source_path TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  total_records INTEGER NOT NULL,
  report_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admission_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
  year INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  school_code TEXT NOT NULL,
  school_name TEXT NOT NULL,
  major_code TEXT NOT NULL,
  major_name TEXT NOT NULL,
  min_score INTEGER,
  min_rank INTEGER,
  plan_count INTEGER,
  subjects TEXT NOT NULL DEFAULT '',
  province TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  school_level TEXT NOT NULL DEFAULT '',
  school_type TEXT NOT NULL DEFAULT '',
  tuition INTEGER,
  tags TEXT NOT NULL DEFAULT '',
  option_key TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admission_option_year
  ON admission_records(option_key, year);

CREATE INDEX IF NOT EXISTS idx_admission_year_rank
  ON admission_records(year, min_rank);

CREATE INDEX IF NOT EXISTS idx_admission_source
  ON admission_records(source_id);

CREATE TABLE IF NOT EXISTS score_rank_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  import_batch_id INTEGER NOT NULL REFERENCES import_batches(id),
  year INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  score INTEGER NOT NULL,
  segment_count INTEGER NOT NULL,
  cumulative_count INTEGER NOT NULL,
  subject_group TEXT NOT NULL DEFAULT '全体'
);

CREATE INDEX IF NOT EXISTS idx_score_rank_year_group
  ON score_rank_records(year, subject_group, score);
"""


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    connection.commit()


def import_records(
    connection: sqlite3.Connection,
    records: list[AdmissionRecord],
    source_path: str,
    batch_name: str | None = None,
    strict: bool = True,
) -> tuple[int, ValidationReport]:
    init_db(connection)
    report = validate_records(records)
    if strict and report.has_errors:
        raise ValueError("Admissions import failed validation; rerun with explicit allow-invalid mode to store it.")
    name = batch_name or Path(source_path).stem
    imported_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    import json

    cursor = connection.execute(
        """
        INSERT INTO import_batches(name, source_path, imported_at, total_records, report_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, source_path, imported_at, len(records), json.dumps(asdict(report), ensure_ascii=False)),
    )
    batch_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO admission_records(
          import_batch_id, year, source_id, school_code, school_name, major_code, major_name,
          min_score, min_rank, plan_count, subjects, province, city, school_level, school_type,
          tuition, tags, option_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [_record_to_row(record, batch_id) for record in records],
    )
    connection.commit()
    return batch_id, report


def fetch_admissions(connection: sqlite3.Connection) -> list[AdmissionRecord]:
    init_db(connection)
    rows = connection.execute(
        """
        SELECT year, source_id, school_code, school_name, major_code, major_name,
               min_score, min_rank, plan_count, subjects, province, city,
               school_level, school_type, tuition, tags
        FROM admission_records
        ORDER BY year, school_code, major_code
        """
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def import_score_rank_records(
    connection: sqlite3.Connection,
    records: list[ScoreRankRecord],
    source_path: str,
    batch_name: str | None = None,
) -> int:
    init_db(connection)
    name = batch_name or Path(source_path).stem
    imported_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    import json

    report = {
        "total_records": len(records),
        "years": sorted({record.year for record in records}),
        "source_ids": sorted({record.source_id for record in records}),
        "min_score": min((record.score for record in records), default=None),
        "max_score": max((record.score for record in records), default=None),
    }
    cursor = connection.execute(
        """
        INSERT INTO import_batches(name, source_path, imported_at, total_records, report_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, source_path, imported_at, len(records), json.dumps(report, ensure_ascii=False)),
    )
    batch_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO score_rank_records(
          import_batch_id, year, source_id, score, segment_count, cumulative_count, subject_group
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                batch_id,
                record.year,
                record.source_id,
                record.score,
                record.segment_count,
                record.cumulative_count,
                record.subject_group,
            )
            for record in records
        ],
    )
    connection.commit()
    return batch_id


def fetch_score_ranks(connection: sqlite3.Connection) -> list[ScoreRankRecord]:
    init_db(connection)
    rows = connection.execute(
        """
        SELECT year, source_id, score, segment_count, cumulative_count, subject_group
        FROM score_rank_records
        ORDER BY year, score DESC
        """
    ).fetchall()
    return [
        ScoreRankRecord(
            year=int(row["year"]),
            source_id=row["source_id"],
            score=int(row["score"]),
            segment_count=int(row["segment_count"]),
            cumulative_count=int(row["cumulative_count"]),
            subject_group=row["subject_group"],
        )
        for row in rows
    ]


def list_batches(connection: sqlite3.Connection) -> list[dict[str, object]]:
    init_db(connection)
    rows = connection.execute(
        """
        SELECT id, name, source_path, imported_at, total_records
        FROM import_batches
        ORDER BY id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _record_to_row(record: AdmissionRecord, batch_id: int) -> tuple[object, ...]:
    return (
        batch_id,
        record.year,
        record.source_id,
        record.school_code,
        record.school_name,
        record.major_code,
        record.major_name,
        record.min_score,
        record.min_rank,
        record.plan_count,
        _join_terms(record.subjects),
        record.province,
        record.city,
        record.school_level,
        record.school_type,
        record.tuition,
        _join_terms(record.tags),
        record.option_key,
    )


def _row_to_record(row: sqlite3.Row) -> AdmissionRecord:
    return AdmissionRecord(
        year=int(row["year"]),
        source_id=row["source_id"],
        school_code=row["school_code"],
        school_name=row["school_name"],
        major_code=row["major_code"],
        major_name=row["major_name"],
        min_score=row["min_score"],
        min_rank=row["min_rank"],
        plan_count=row["plan_count"],
        subjects=_split_terms(row["subjects"]),
        province=row["province"],
        city=row["city"],
        school_level=row["school_level"],
        school_type=row["school_type"],
        tuition=row["tuition"],
        tags=_split_terms(row["tags"]),
    )


def _join_terms(values: Iterable[str]) -> str:
    return "|".join(value for value in values if value)


def _split_terms(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split("|") if part)
