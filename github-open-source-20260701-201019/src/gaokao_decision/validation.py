from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .models import AdmissionRecord


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    option_key: str | None = None
    year: int | None = None


@dataclass(frozen=True)
class ValidationReport:
    total_records: int
    years: dict[int, int]
    source_ids: dict[str, int]
    duplicate_option_years: int
    missing_required_fields: int
    missing_min_rank: int
    missing_min_score: int
    missing_plan_count: int
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return any(issue.level == "error" for issue in self.issues)


REQUIRED_TEXT_FIELDS = (
    "source_id",
    "school_code",
    "school_name",
    "major_code",
    "major_name",
)


def validate_records(records: list[AdmissionRecord]) -> ValidationReport:
    issues: list[ValidationIssue] = []
    years = Counter(record.year for record in records)
    source_ids = Counter(record.source_id for record in records)
    option_years = Counter((record.option_key, record.year) for record in records)

    missing_required = 0
    missing_min_rank = 0
    missing_min_score = 0
    missing_plan_count = 0

    for record in records:
        missing = [field for field in REQUIRED_TEXT_FIELDS if not getattr(record, field)]
        if missing:
            missing_required += 1
            issues.append(
                ValidationIssue(
                    level="error",
                    code="missing_required_field",
                    message=f"缺少必填字段：{', '.join(missing)}",
                    option_key=record.option_key,
                    year=record.year,
                )
            )

        if record.source_id == "unknown_source":
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="unknown_source",
                    message="source_id 为 unknown_source，正式数据不可使用",
                    option_key=record.option_key,
                    year=record.year,
                )
            )

        if record.min_rank is None:
            missing_min_rank += 1
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="missing_min_rank",
                    message="缺少最低位次，推荐时只能降级为证据不足",
                    option_key=record.option_key,
                    year=record.year,
                )
            )

        if record.min_score is None:
            missing_min_score += 1

        if record.plan_count is None:
            missing_plan_count += 1

        if record.min_rank is not None and record.min_rank <= 0:
            issues.append(
                ValidationIssue(
                    level="error",
                    code="invalid_min_rank",
                    message="最低位次必须为正数",
                    option_key=record.option_key,
                    year=record.year,
                )
            )

        if record.min_score is not None and not 0 <= record.min_score <= 750:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="suspicious_min_score",
                    message="最低分不在 0-750 范围内，请核对字段映射",
                    option_key=record.option_key,
                    year=record.year,
                )
            )

    duplicate_count = sum(count - 1 for count in option_years.values() if count > 1)
    for (option_key, year), count in option_years.items():
        if count > 1:
            issues.append(
                ValidationIssue(
                    level="warning",
                    code="duplicate_option_year",
                    message=f"同一院校专业在同一年出现 {count} 次，需确认是否为不同备注或方向",
                    option_key=option_key,
                    year=year,
                )
            )

    return ValidationReport(
        total_records=len(records),
        years=dict(sorted(years.items())),
        source_ids=dict(sorted(source_ids.items())),
        duplicate_option_years=duplicate_count,
        missing_required_fields=missing_required,
        missing_min_rank=missing_min_rank,
        missing_min_score=missing_min_score,
        missing_plan_count=missing_plan_count,
        issues=tuple(issues),
    )

