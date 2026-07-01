from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import AdmissionRecord, CandidateProfile, Recommendation, Rejection
from .recommend import recommend, sort_recommendations_for_candidate


STRATEGY_QUOTAS = {
    "aggressive": {
        "高冲": 8,
        "冲": 22,
        "稳中偏冲": 24,
        "稳": 24,
        "保": 14,
        "强保": 4,
    },
    "balanced": {
        "高冲": 2,
        "冲": 16,
        "稳中偏冲": 24,
        "稳": 30,
        "保": 19,
        "强保": 5,
    },
    "conservative": {
        "高冲": 0,
        "冲": 8,
        "稳中偏冲": 18,
        "稳": 35,
        "保": 25,
        "强保": 10,
    },
}


@dataclass(frozen=True)
class VolunteerPlan:
    strategy: str
    target_size: int
    quotas: dict[str, int]
    risk_counts: dict[str, int]
    recommendations: tuple[Recommendation, ...]
    rejections: tuple[Rejection, ...]
    warnings: tuple[str, ...]


def build_volunteer_plan(
    records: list[AdmissionRecord],
    candidate: CandidateProfile,
    strategy: str = "balanced",
    target_size: int = 96,
    custom_quotas: dict[str, int] | None = None,
) -> VolunteerPlan:
    recommendations, rejections = recommend(records, candidate, limit=100000)
    return build_volunteer_plan_from_recommendations(
        recommendations,
        rejections,
        candidate=candidate,
        strategy=strategy,
        target_size=target_size,
        custom_quotas=custom_quotas,
    )


def build_volunteer_plan_from_recommendations(
    recommendations: list[Recommendation],
    rejections: list[Rejection],
    candidate: CandidateProfile | None = None,
    strategy: str = "balanced",
    target_size: int = 96,
    custom_quotas: dict[str, int] | None = None,
) -> VolunteerPlan:
    if target_size <= 0:
        raise ValueError("target_size must be a positive integer.")
    if strategy == "custom":
        quotas = _normalize_custom_quotas(custom_quotas or {})
        target_size = sum(quotas.values())
    elif strategy in STRATEGY_QUOTAS:
        quotas = _scaled_quotas(STRATEGY_QUOTAS[strategy], target_size)
    else:
        raise ValueError(f"Unknown strategy: {strategy}. Expected one of {', '.join((*STRATEGY_QUOTAS, 'custom'))}")

    selected = _select_by_quota(recommendations, quotas, target_size)
    if candidate is not None:
        selected = sort_recommendations_for_candidate(selected, candidate)
    risk_counts = dict(Counter(item.risk_band for item in selected))
    warnings = _plan_warnings(risk_counts, quotas, len(selected), target_size)
    return VolunteerPlan(
        strategy=strategy,
        target_size=target_size,
        quotas=quotas,
        risk_counts=risk_counts,
        recommendations=tuple(selected),
        rejections=tuple(rejections),
        warnings=warnings,
    )


def _scaled_quotas(base_quotas: dict[str, int], target_size: int) -> dict[str, int]:
    if target_size <= 0:
        raise ValueError("target_size must be a positive integer.")
    base_total = sum(base_quotas.values())
    if base_total == target_size:
        return dict(base_quotas)
    scaled = {band: int(count * target_size / base_total) for band, count in base_quotas.items()}
    while sum(scaled.values()) < target_size:
        for band in base_quotas:
            scaled[band] += 1
            if sum(scaled.values()) == target_size:
                break
    return scaled


def _normalize_custom_quotas(custom_quotas: dict[str, int]) -> dict[str, int]:
    quotas: dict[str, int] = {}
    for band in ("高冲", "冲", "稳中偏冲", "稳", "保", "强保"):
        try:
            value = int(custom_quotas.get(band, 0))
        except (TypeError, ValueError):
            value = 0
        quotas[band] = max(0, value)
    if sum(quotas.values()) <= 0:
        raise ValueError("自定义方案至少需要设置 1 个志愿数量。")
    return quotas


def _select_by_quota(
    recommendations: list[Recommendation],
    quotas: dict[str, int],
    target_size: int,
) -> list[Recommendation]:
    selected: list[Recommendation] = []
    selected_keys: set[str] = set()
    by_band: dict[str, list[Recommendation]] = {}
    for item in recommendations:
        by_band.setdefault(item.risk_band, []).append(item)

    for band, quota in quotas.items():
        for item in by_band.get(band, [])[:quota]:
            if item.option_key not in selected_keys:
                selected.append(item)
                selected_keys.add(item.option_key)

    if len(selected) < target_size:
        for item in recommendations:
            if item.option_key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(item.option_key)
            if len(selected) == target_size:
                break

    return selected[:target_size]


def _plan_warnings(
    risk_counts: dict[str, int],
    quotas: dict[str, int],
    actual_size: int,
    target_size: int,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if actual_size < target_size:
        warnings.append(f"候选项不足：目标 {target_size} 个，实际只生成 {actual_size} 个。")
    for band, quota in quotas.items():
        actual = risk_counts.get(band, 0)
        if actual < quota:
            warnings.append(f"{band} 档不足：目标 {quota} 个，实际 {actual} 个。")
    if risk_counts.get("保", 0) + risk_counts.get("强保", 0) < max(8, target_size // 5):
        warnings.append("保底厚度不足：保和强保合计偏少，正式填报前必须补足。")
    return tuple(warnings)
