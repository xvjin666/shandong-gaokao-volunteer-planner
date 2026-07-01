from __future__ import annotations

from dataclasses import dataclass, replace

from .models import AdmissionRecord, Recommendation, ScoreRankRecord
from .plan import VolunteerPlan, build_volunteer_plan_from_recommendations
from .recommend import recommend, sort_recommendations_for_candidate
from .scoring import RiskThresholds
from .importer import ambiguous_stable_option_keys, option_group_key


@dataclass(frozen=True)
class EquivalentScore:
    year: int
    rank: int
    score: int
    cumulative_count: int
    segment_count: int
    source_id: str


@dataclass(frozen=True)
class ScoreBandMatch:
    year: int
    center_score: int
    low_score: int
    high_score: int
    matched_records: int
    matched_options: int


@dataclass(frozen=True)
class ScoreBandPlan:
    equivalent_scores: tuple[EquivalentScore, ...]
    band_matches: tuple[ScoreBandMatch, ...]
    candidate_recommendations: tuple[Recommendation, ...]
    plan: VolunteerPlan
    search_recommendations: tuple[Recommendation, ...] = ()
    score_band_candidate_count: int = 0
    coverage_guard_added: int = 0


COVERAGE_GUARD_RISK_BANDS = {"冲", "稳中偏冲", "稳", "保"}


def equivalent_scores_for_rank(
    score_ranks: list[ScoreRankRecord],
    rank: int,
    years: tuple[int, ...] = (2023, 2024, 2025),
) -> tuple[EquivalentScore, ...]:
    if rank <= 0:
        raise ValueError("Rank must be a positive integer.")
    results: list[EquivalentScore] = []
    for year in years:
        record = score_for_rank(score_ranks, year, rank)
        if record is None:
            continue
        results.append(
            EquivalentScore(
                year=year,
                rank=rank,
                score=record.score,
                cumulative_count=record.cumulative_count,
                segment_count=record.segment_count,
                source_id=record.source_id,
            )
        )
    return tuple(results)


def _score_rank_index(
    score_ranks: list[ScoreRankRecord],
    subject_group: str = "全体",
) -> dict[int, tuple[ScoreRankRecord, ...]]:
    index: dict[int, list[ScoreRankRecord]] = {}
    for item in score_ranks:
        if item.subject_group == subject_group:
            index.setdefault(item.year, []).append(item)
    return {
        year: tuple(sorted(rows, key=lambda item: item.score, reverse=True))
        for year, rows in index.items()
    }


def _score_for_rank_from_index(
    index: dict[int, tuple[ScoreRankRecord, ...]],
    year: int,
    rank: int,
) -> ScoreRankRecord | None:
    rows = index.get(year, ())
    for item in rows:
        if item.cumulative_count >= rank:
            return item
    return rows[-1] if rows else None


def score_for_rank(
    score_ranks: list[ScoreRankRecord],
    year: int,
    rank: int,
    subject_group: str = "全体",
) -> ScoreRankRecord | None:
    if rank <= 0:
        raise ValueError("Rank must be a positive integer.")
    return _score_for_rank_from_index(_score_rank_index(score_ranks, subject_group), year, rank)


def build_score_band_plan(
    admissions: list[AdmissionRecord],
    score_ranks: list[ScoreRankRecord],
    rank: int,
    candidate,
    strategy: str = "balanced",
    target_size: int = 96,
    band_width: int = 20,
    custom_quotas: dict[str, int] | None = None,
    custom_risk_gaps: dict[str, int] | None = None,
) -> ScoreBandPlan:
    if band_width < 0:
        raise ValueError("band_width must be non-negative.")
    score_index = _score_rank_index(score_ranks)
    risk_thresholds = (
        _risk_thresholds_from_score_gaps(score_index, rank, custom_risk_gaps)
        if strategy == "custom"
        else None
    )
    equivalents = tuple(
        EquivalentScore(
            year=year,
            rank=rank,
            score=record.score,
            cumulative_count=record.cumulative_count,
            segment_count=record.segment_count,
            source_id=record.source_id,
        )
        for year in (2023, 2024, 2025)
        for record in [_score_for_rank_from_index(score_index, year, rank)]
        if record is not None
    )
    equivalent_by_year = {item.year: item for item in equivalents}
    matched_options: set[str] = set()
    band_matches: list[ScoreBandMatch] = []
    ambiguous_keys = ambiguous_stable_option_keys(admissions)
    admissions_by_year: dict[int, list[AdmissionRecord]] = {}
    for record in admissions:
        admissions_by_year.setdefault(record.year, []).append(record)
    admission_score_cache: dict[tuple[int, int], ScoreRankRecord | None] = {}

    for equivalent in equivalents:
        low = equivalent.score - band_width
        high = equivalent.score + band_width
        year_records = admissions_by_year.get(equivalent.year, [])
        matched_records: list[AdmissionRecord] = []
        for record in year_records:
            if record.min_rank is None:
                continue
            cache_key = (record.year, record.min_rank)
            if cache_key not in admission_score_cache:
                admission_score_cache[cache_key] = _score_for_rank_from_index(score_index, record.year, record.min_rank)
            admission_score_record = admission_score_cache[cache_key]
            if admission_score_record is None:
                continue
            if low <= admission_score_record.score <= high:
                matched_records.append(record)
                matched_options.add(option_group_key(record, ambiguous_keys))
        band_matches.append(
            ScoreBandMatch(
                year=equivalent.year,
                center_score=equivalent.score,
                low_score=low,
                high_score=high,
                matched_records=len(matched_records),
                matched_options=len({option_group_key(record, ambiguous_keys) for record in matched_records}),
            )
        )

    filtered_admissions = [record for record in admissions if option_group_key(record, ambiguous_keys) in matched_options]
    used_full_pool = False
    if not filtered_admissions:
        filtered_admissions = admissions
        used_full_pool = True
    recommendations, rejections = recommend(
        filtered_admissions,
        candidate,
        limit=100000,
        risk_thresholds=risk_thresholds,
    )
    score_band_candidate_count = len(recommendations)
    coverage_guard_added = 0
    full_recommendations: list[Recommendation] | None = None
    if not used_full_pool:
        full_recommendations, _ = recommend(
            admissions,
            candidate,
            limit=100000,
            risk_thresholds=risk_thresholds,
        )
        recommendations, coverage_guard_added = _merge_with_coverage_guard(
            recommendations,
            full_recommendations,
            candidate,
        )
    search_candidate = replace(candidate, interests=())
    if not candidate.interests and used_full_pool:
        search_recommendations = recommendations
    elif not candidate.interests and full_recommendations is not None:
        search_recommendations = full_recommendations
    else:
        search_recommendations, _ = recommend(
            admissions,
            search_candidate,
            limit=100000,
            risk_thresholds=risk_thresholds,
        )
    plan = build_volunteer_plan_from_recommendations(
        recommendations,
        rejections,
        candidate=candidate,
        strategy=strategy,
        target_size=target_size,
        custom_quotas=custom_quotas,
    )
    return ScoreBandPlan(
        equivalent_scores=equivalents,
        band_matches=tuple(band_matches),
        candidate_recommendations=tuple(recommendations),
        plan=plan,
        search_recommendations=tuple(search_recommendations),
        score_band_candidate_count=score_band_candidate_count,
        coverage_guard_added=coverage_guard_added,
    )


def _risk_thresholds_from_score_gaps(
    score_index: dict[int, tuple[ScoreRankRecord, ...]],
    rank: int,
    gaps: dict[str, int] | None,
) -> RiskThresholds | None:
    if not gaps:
        return None
    years = sorted(score_index)
    if not years:
        return None
    base_year = 2026 if 2026 in score_index else years[-1]
    base_score_record = _score_for_rank_from_index(score_index, base_year, rank)
    if base_score_record is None:
        return None

    challenge_gap = _positive_gap(gaps.get("challenge"), 12)
    steady_gap = _positive_gap(gaps.get("steady"), 12)
    safe_gap = _positive_gap(gaps.get("safe"), steady_gap)
    base_score = base_score_record.score
    rows = score_index.get(base_year, ())

    high_challenge_rank = _rank_for_score_from_index(rows, base_score + challenge_gap)
    lean_steady_rank = _rank_for_score_from_index(rows, base_score - max(1, round(steady_gap * 0.35)))
    steady_rank = _rank_for_score_from_index(rows, base_score - steady_gap)
    strong_safe_score_gap = max(safe_gap * 2, safe_gap + max(3, round(safe_gap * 0.5)))
    safe_rank = _rank_for_score_from_index(rows, base_score - strong_safe_score_gap)

    hard = max(1.0, float(rank - high_challenge_rank))
    soft = 0.0
    steady_lean = max(1.0, float(lean_steady_rank - rank))
    steady = max(steady_lean + 1.0, float(steady_rank - rank))
    safe = max(steady + 1.0, float(safe_rank - rank))
    return hard, soft, steady_lean, steady, safe


def _rank_for_score_from_index(rows: tuple[ScoreRankRecord, ...], score: int) -> int:
    if not rows:
        return 0
    for item in rows:
        if item.score <= score:
            return item.cumulative_count
    return rows[-1].cumulative_count


def _positive_gap(value: object, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(0, number)


def _merge_with_coverage_guard(
    score_band_recommendations: list[Recommendation],
    full_recommendations: list[Recommendation],
    candidate,
) -> tuple[list[Recommendation], int]:
    merged_by_key = {item.option_key: item for item in score_band_recommendations}
    added = 0
    for item in full_recommendations:
        if item.option_key in merged_by_key:
            continue
        if item.risk_band not in COVERAGE_GUARD_RISK_BANDS:
            continue
        merged_by_key[item.option_key] = _mark_coverage_guard(item)
        added += 1
    merged = sort_recommendations_for_candidate(list(merged_by_key.values()), candidate)
    return merged, added


def _mark_coverage_guard(item: Recommendation) -> Recommendation:
    debug = dict(item.debug)
    debug["coverage_guard"] = True
    reasons = tuple((*item.reasons, "防漏补充：未落入等效分±分数带，但综合参考位次仍属于可比较区间"))
    return Recommendation(
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
        reasons=reasons,
        warnings=item.warnings,
        falsification_tests=item.falsification_tests,
        evidence=item.evidence,
        comparisons=item.comparisons,
        debug=debug,
    )
