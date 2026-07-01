from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AdmissionRecord:
    year: int
    source_id: str
    school_code: str
    school_name: str
    major_code: str
    major_name: str
    min_score: int | None
    min_rank: int | None
    plan_count: int | None = None
    subjects: tuple[str, ...] = ()
    province: str = ""
    city: str = ""
    school_level: str = ""
    school_type: str = ""
    tuition: int | None = None
    tags: tuple[str, ...] = ()

    @property
    def option_key(self) -> str:
        return f"{self.school_code}:{self.major_code}"

    @property
    def option_name(self) -> str:
        return f"{self.school_name} / {self.major_name}"


@dataclass(frozen=True)
class ScoreRankRecord:
    year: int
    source_id: str
    score: int
    segment_count: int
    cumulative_count: int
    subject_group: str = "全体"


@dataclass(frozen=True)
class CandidateProfile:
    score: int
    rank: int
    subjects: tuple[str, ...]
    interests: tuple[str, ...] = ()
    avoid_keywords: tuple[str, ...] = ()
    max_tuition: int | None = None
    preferred_cities: tuple[str, ...] = ()
    blocked_cities: tuple[str, ...] = ()
    allow_private: bool = False
    allow_sino_foreign: bool = False
    require_known_subjects: bool = False
    require_double_first_class: bool = False
    require_985: bool = False
    require_211: bool = False
    require_public_undergraduate: bool = False


@dataclass(frozen=True)
class EvidencePoint:
    year: int
    source_id: str
    min_score: int | None
    min_rank: int | None
    plan_count: int | None


@dataclass(frozen=True)
class Recommendation:
    option_key: str
    option_name: str
    risk_band: str
    total_score: float
    risk_score: float
    success_probability: float
    fit_score: float
    stability_score: float
    weighted_reference_rank: float | None
    rank_margin: float | None
    trend: str
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    falsification_tests: tuple[str, ...]
    evidence: tuple[EvidencePoint, ...]
    comparisons: tuple[str, ...] = field(default_factory=tuple)
    debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Rejection:
    option_key: str
    option_name: str
    reasons: tuple[str, ...]
