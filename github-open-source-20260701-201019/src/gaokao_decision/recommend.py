from __future__ import annotations

import re

from .importer import group_by_option
from .models import AdmissionRecord, CandidateProfile, Recommendation, Rejection
from .scoring import (
    RiskThresholds,
    classify_risk,
    evidence_points,
    falsification_tests,
    fit_score,
    hard_filter,
    stability_score,
    success_probability,
    trend_label,
    weighted_reference_rank,
)
from .school_profiles import school_meta, school_tags


RISK_SORT_ORDER = {
    "高冲": 0,
    "冲": 1,
    "稳中偏冲": 2,
    "稳": 3,
    "保": 4,
    "强保": 5,
    "证据不足": 6,
}

GENERIC_EXPERIMENTAL_BASES = {
    "工科试验班",
    "工科试验班类",
    "试验班",
    "试验班类",
}


def recommend(
    records: list[AdmissionRecord],
    candidate: CandidateProfile,
    limit: int = 96,
    risk_thresholds: RiskThresholds | None = None,
) -> tuple[list[Recommendation], list[Rejection]]:
    recommendations: list[Recommendation] = []
    rejections: list[Rejection] = []
    record_pool = list(records)
    supplement_index = _build_supplement_index(record_pool)

    for option_key, option_records in group_by_option(record_pool).items():
        option_records = _supplement_historical_records(option_records, record_pool, supplement_index)
        rejection = hard_filter(option_records, candidate)
        if rejection:
            rejections.append(Rejection(option_key, rejection.option_name, rejection.reasons))
            continue

        reference_rank = weighted_reference_rank(option_records)
        risk_band, risk_score, rank_margin = classify_risk(candidate.rank, reference_rank, risk_thresholds)
        stability = stability_score(option_records)
        fit, fit_reasons = fit_score(option_records, candidate)
        success = success_probability(candidate.rank, reference_rank, risk_band, fit, stability, risk_thresholds)
        trend = trend_label(option_records)
        warnings = _warnings(option_records, trend, reference_rank)
        reasons = _reasons(risk_band, rank_margin, reference_rank, fit_reasons)
        latest = max(option_records, key=lambda item: item.year)
        profile_tags = school_tags(latest)
        total_score = _total_score(
            risk_score,
            fit,
            stability,
            risk_band,
            candidate.rank,
            reference_rank,
            profile_tags,
        )

        mapped_city, _ = school_meta(latest.school_name)
        recommendations.append(
            Recommendation(
                option_key=option_key,
                option_name=latest.option_name,
                risk_band=risk_band,
                total_score=round(total_score, 4),
                risk_score=round(risk_score, 4),
                success_probability=round(success, 4),
                fit_score=round(fit, 4),
                stability_score=round(stability, 4),
                weighted_reference_rank=round(reference_rank, 2) if reference_rank is not None else None,
                rank_margin=round(rank_margin, 2) if rank_margin is not None else None,
                trend=trend,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
                falsification_tests=falsification_tests(option_records, candidate),
                evidence=evidence_points(option_records),
                debug={
                    "latest_year": latest.year,
                    "school_code": latest.school_code,
                    "major_code": latest.major_code,
                    "legacy_option_key": latest.option_key,
                    "city": latest.city or mapped_city,
                    "school_type": latest.school_type,
                    "subjects": latest.subjects,
                    "tags": profile_tags,
                    "tuition": latest.tuition,
                    "latest_plan_count": latest.plan_count,
                    "plan_count_2026": None,
                },
            )
        )

    recommendations = _dedupe_recommendations(recommendations)
    ranked = sort_recommendations_for_candidate(recommendations, candidate)
    return _attach_comparisons(ranked[:limit]), rejections


def _dedupe_recommendations(recommendations: list[Recommendation]) -> list[Recommendation]:
    by_key: dict[str, Recommendation] = {}
    for item in recommendations:
        current = by_key.get(item.option_key)
        if current is None or _recommendation_completeness(item) > _recommendation_completeness(current):
            by_key[item.option_key] = item
    return list(by_key.values())


def _recommendation_completeness(item: Recommendation) -> tuple[int, int, float]:
    valid_rank_years = sum(1 for point in item.evidence if point.min_rank is not None)
    plan_years = sum(1 for point in item.evidence if point.plan_count is not None)
    return (valid_rank_years, plan_years, float(item.total_score))


def _supplement_historical_records(
    option_records: list[AdmissionRecord],
    all_records: list[AdmissionRecord],
    supplement_index: dict[tuple[str, str, str, str], list[AdmissionRecord]] | None = None,
) -> list[AdmissionRecord]:
    if not option_records:
        return option_records
    by_year: dict[int, AdmissionRecord] = {
        record.year: record
        for record in sorted(option_records, key=lambda item: (item.year, item.major_code))
    }
    if len(by_year) >= 3:
        return sorted(by_year.values(), key=lambda item: item.year)

    latest = max(option_records, key=lambda item: item.year)
    family_key = _supplement_family_key(latest)
    if not family_key:
        return sorted(by_year.values(), key=lambda item: item.year)

    if supplement_index is None:
        supplement_index = _build_supplement_index(all_records)
    index_key = _supplement_index_key(latest, family_key)
    for candidate in supplement_index.get(index_key, []):
        if candidate.year in by_year:
            continue
        by_year[candidate.year] = candidate
    return sorted(by_year.values(), key=lambda item: item.year)


def _build_supplement_index(records: list[AdmissionRecord]) -> dict[tuple[str, str, str, str], list[AdmissionRecord]]:
    index: dict[tuple[str, str, str, str], list[AdmissionRecord]] = {}
    for record in records:
        family_key = _supplement_family_key(record)
        if not family_key:
            continue
        index.setdefault(_supplement_index_key(record, family_key), []).append(record)
    return index


def _supplement_index_key(record: AdmissionRecord, family_key: str) -> tuple[str, str, str, str]:
    return (
        record.school_code.strip(),
        record.school_type.strip(),
        record.school_name.strip(),
        family_key,
    )


def _supplement_family_key(record: AdmissionRecord) -> str:
    base = _major_base_without_parentheses(record.major_name)
    if not base:
        return ""
    if base in GENERIC_EXPERIMENTAL_BASES:
        return ""
    return "|".join([record.school_code.strip(), record.school_type.strip(), base])


def _major_base_without_parentheses(value: str) -> str:
    text = "".join(str(value or "").split())
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = text.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III")
    return text.strip()


def _total_score(
    risk_score: float,
    fit: float,
    stability: float,
    risk_band: str,
    candidate_rank: int,
    reference_rank: float | None,
    tags: tuple[str, ...],
) -> float:
    band_desirability = {
        "高冲": 0.22,
        "冲": 0.72,
        "稳中偏冲": 0.92,
        "稳": 1.00,
        "保": 0.82,
        "强保": 0.55,
        "证据不足": 0.15,
    }.get(risk_band, risk_score)
    elite_weight = _elite_selectivity_weight(candidate_rank)
    selectivity = _selectivity_score(reference_rank)
    tier = _school_tier_score(tags)
    return (
        band_desirability * 0.30
        + fit * 0.35
        + stability * 0.15
        + selectivity * elite_weight
        + tier * 0.08
    )


def sort_recommendations_for_candidate(
    recommendations: list[Recommendation],
    candidate: CandidateProfile,
) -> list[Recommendation]:
    if _elite_selectivity_weight(candidate.rank) <= 0:
        return sorted(recommendations, key=lambda item: _standard_recommendation_sort_key(item))
    return sorted(recommendations, key=lambda item: _elite_recommendation_sort_key(item))


def _standard_recommendation_sort_key(item: Recommendation) -> tuple[float, ...]:
    reference_rank = (
        float("inf")
        if item.weighted_reference_rank is None
        else float(item.weighted_reference_rank)
    )
    return (
        RISK_SORT_ORDER.get(item.risk_band, len(RISK_SORT_ORDER)),
        -float(item.total_score),
        reference_rank,
    )


def _elite_recommendation_sort_key(item: Recommendation) -> tuple[float, ...]:
    reference_rank = (
        float("inf")
        if item.weighted_reference_rank is None
        else float(item.weighted_reference_rank)
    )
    return (
        RISK_SORT_ORDER.get(item.risk_band, len(RISK_SORT_ORDER)),
        reference_rank,
        -_school_tier_score(tuple(item.debug.get("tags", ()))),
        -float(item.total_score),
    )


def _elite_selectivity_weight(candidate_rank: int) -> float:
    if candidate_rank <= 500:
        return 0.34
    if candidate_rank <= 2000:
        return 0.24
    if candidate_rank <= 8000:
        return 0.14
    return 0.0


def _selectivity_score(reference_rank: float | None) -> float:
    if reference_rank is None or reference_rank <= 0:
        return 0.0
    if reference_rank <= 500:
        return 1.0
    if reference_rank <= 2000:
        return 0.88
    if reference_rank <= 8000:
        return 0.68
    if reference_rank <= 20000:
        return 0.42
    if reference_rank <= 50000:
        return 0.22
    return 0.08


def _school_tier_score(tags: tuple[str, ...]) -> float:
    tag_set = set(tags)
    if "985" in tag_set:
        return 1.0
    if "211" in tag_set:
        return 0.78
    if "双一流" in tag_set:
        return 0.62
    return 0.0


def _reasons(
    risk_band: str,
    rank_margin: float | None,
    reference_rank: float | None,
    fit_reasons: list[str],
) -> list[str]:
    reasons = list(fit_reasons)
    if reference_rank is not None and rank_margin is not None:
        if rank_margin >= 0:
            reasons.append(f"综合参考位次约 {reference_rank:.0f}，比考生位次安全 {rank_margin:.0f} 位")
        else:
            reasons.append(f"综合参考位次约 {reference_rank:.0f}，比考生位次高 {-rank_margin:.0f} 位，属于{risk_band}")
    else:
        reasons.append("历史位次证据不足，只能作为高不确定候选")
    return reasons


def _warnings(records: list[AdmissionRecord], trend: str, reference_rank: float | None) -> list[str]:
    warnings: list[str] = []
    latest = max(records, key=lambda item: item.year)
    if reference_rank is None:
        warnings.append("缺少有效最低位次，不能可靠估计录取风险")
    if not latest.subjects:
        warnings.append("缺少选科要求结构化数据，正式填报前必须核对官方选科要求")
    valid_rank_years = {record.year for record in records if record.min_rank is not None}
    if len(valid_rank_years) == 1:
        warnings.append("单年样本：参考位次按该年 100% 计算，但历史证据不足，需人工复核")
    if trend == "连续变难":
        warnings.append("近年最低位次连续前移，热度上升，风险需上调")
    plan_counts = [record.plan_count for record in records if record.plan_count is not None]
    if len(plan_counts) >= 2 and plan_counts[-1] < min(plan_counts[:-1]):
        warnings.append("最近一年计划数低于前序年份，需关注 2026 计划")
    return warnings


def _attach_comparisons(recommendations: list[Recommendation]) -> list[Recommendation]:
    by_band: dict[str, list[str]] = {}
    for item in recommendations:
        by_band.setdefault(item.risk_band, []).append(item.option_name)
    comparison_names = {band: names[:8] for band, names in by_band.items()}

    enriched: list[Recommendation] = []
    for item in recommendations:
        alternatives = [name for name in comparison_names.get(item.risk_band, []) if name != item.option_name][:3]
        enriched.append(
            Recommendation(
                option_key=item.option_key,
                option_name=item.option_name,
                risk_band=item.risk_band,
                total_score=item.total_score,
                risk_score=item.risk_score,
                success_probability=item.success_probability,
                fit_score=item.fit_score,
                stability_score=item.stability_score,
                weighted_reference_rank=item.weighted_reference_rank,
                rank_margin=item.rank_margin,
                trend=item.trend,
                reasons=item.reasons,
                warnings=item.warnings,
                falsification_tests=item.falsification_tests,
                evidence=item.evidence,
                comparisons=tuple(alternatives),
                debug=item.debug,
            )
        )
    return enriched
