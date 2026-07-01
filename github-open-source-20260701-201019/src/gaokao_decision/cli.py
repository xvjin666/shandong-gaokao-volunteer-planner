from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .database import (
    connect,
    fetch_admissions,
    fetch_score_ranks,
    import_records,
    import_score_rank_records,
    init_db,
    list_batches,
)
from .importer import load_admissions
from .importer import load_score_ranks
from .models import CandidateProfile
from .plan import build_volunteer_plan
from .rank_conversion import build_score_band_plan
from .recommend import recommend
from .sdzk_parser import load_summer_score_rank_xls
from .validation import validate_records


def main() -> None:
    parser = argparse.ArgumentParser(description="山东高考志愿推荐内核 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    recommend_parser = subparsers.add_parser("recommend", help="生成可解释候选志愿")
    recommend_parser.add_argument("--admissions", required=True, help="CSV/XLSX admissions file")
    recommend_parser.add_argument("--score", type=int, required=True)
    recommend_parser.add_argument("--rank", type=int, required=True)
    recommend_parser.add_argument("--subjects", nargs="+", required=True)
    recommend_parser.add_argument("--interests", nargs="*", default=[])
    recommend_parser.add_argument("--avoid", nargs="*", default=[])
    recommend_parser.add_argument("--preferred-cities", nargs="*", default=[])
    recommend_parser.add_argument("--blocked-cities", nargs="*", default=[])
    recommend_parser.add_argument("--max-tuition", type=int)
    recommend_parser.add_argument("--allow-private", action="store_true")
    recommend_parser.add_argument("--allow-sino-foreign", action="store_true")
    recommend_parser.add_argument("--limit", type=int, default=20)
    recommend_parser.add_argument("--rejection-limit", type=int, default=20)

    validate_parser = subparsers.add_parser("validate", help="校验招生数据文件")
    validate_parser.add_argument("--admissions", required=True, help="CSV/XLSX admissions file")

    init_parser = subparsers.add_parser("init-db", help="初始化 SQLite 数据库")
    init_parser.add_argument("--db", required=True, help="SQLite database path")

    sample_parser = subparsers.add_parser("build-sample-db", help="用开源样例数据构建可运行 SQLite 数据库")
    sample_parser.add_argument("--db", default="data/sample/open_demo.sqlite", help="SQLite database path")
    sample_parser.add_argument("--admissions", default="data/sample/admissions_sample.csv", help="Sample admissions CSV/XLSX")
    sample_parser.add_argument("--score-ranks", default="data/sample/score_rank_sample.csv", help="Sample score-rank CSV/XLSX")

    import_parser = subparsers.add_parser("import-admissions", help="导入招生数据到 SQLite")
    import_parser.add_argument("--db", required=True, help="SQLite database path")
    import_parser.add_argument("--admissions", required=True, help="CSV/XLSX admissions file")
    import_parser.add_argument("--batch-name", help="导入批次名称")
    import_parser.add_argument("--allow-invalid", action="store_true", help="允许保存存在 error 级校验问题的数据")

    score_rank_parser = subparsers.add_parser("import-score-rank", help="导入一分一段表到 SQLite")
    score_rank_parser.add_argument("--db", required=True, help="SQLite database path")
    score_rank_parser.add_argument("--input", required=True, help="CSV/XLSX score-rank file, or archived official .xls")
    score_rank_parser.add_argument("--year", type=int, help="Default year for files without a year column; required for official .xls")
    score_rank_parser.add_argument("--source-id", help="Default source_id for files without a source_id column; required for official .xls")
    score_rank_parser.add_argument("--batch-name", help="导入批次名称")

    batches_parser = subparsers.add_parser("list-batches", help="列出数据库导入批次")
    batches_parser.add_argument("--db", required=True, help="SQLite database path")

    recommend_db_parser = subparsers.add_parser("recommend-db", help="从 SQLite 数据库生成推荐")
    recommend_db_parser.add_argument("--db", required=True, help="SQLite database path")
    add_candidate_arguments(recommend_db_parser)

    plan_parser = subparsers.add_parser("plan", help="从文件生成冲稳保志愿方案")
    plan_parser.add_argument("--admissions", required=True, help="CSV/XLSX admissions file")
    add_candidate_arguments(plan_parser)
    add_plan_arguments(plan_parser)

    plan_db_parser = subparsers.add_parser("plan-db", help="从 SQLite 数据库生成冲稳保志愿方案")
    plan_db_parser.add_argument("--db", required=True, help="SQLite database path")
    add_candidate_arguments(plan_db_parser)
    add_plan_arguments(plan_db_parser)

    band_plan_parser = subparsers.add_parser("rank-plan-db", help="按 2026 位次换算等效分并生成方案")
    band_plan_parser.add_argument("--db", required=True, help="SQLite database path")
    add_candidate_arguments(band_plan_parser)
    add_plan_arguments(band_plan_parser)
    band_plan_parser.add_argument("--band-width", type=int, default=20, help="等效分上下浮动区间，默认 20 分")

    args = parser.parse_args()
    if args.command == "recommend":
        records = load_admissions(args.admissions)
        emit_recommendations(records, build_candidate(args), args.limit, args.rejection_limit)
    elif args.command == "validate":
        records = load_admissions(args.admissions)
        print(json.dumps(asdict(validate_records(records)), ensure_ascii=False, indent=2))
    elif args.command == "init-db":
        with connect(args.db) as connection:
            init_db(connection)
        print(json.dumps({"db": args.db, "status": "initialized"}, ensure_ascii=False, indent=2))
    elif args.command == "build-sample-db":
        admission_records = load_admissions(args.admissions)
        score_rank_records = load_score_ranks(args.score_ranks)
        with connect(args.db) as connection:
            init_db(connection)
            admissions_batch_id, admissions_report = import_records(
                connection,
                admission_records,
                args.admissions,
                "open_sample_admissions",
            )
            score_rank_batch_id = import_score_rank_records(
                connection,
                score_rank_records,
                args.score_ranks,
                "open_sample_score_ranks",
            )
        print(
            json.dumps(
                {
                    "db": args.db,
                    "status": "sample database built",
                    "admissions_batch_id": admissions_batch_id,
                    "admissions_validation": asdict(admissions_report),
                    "score_rank_batch_id": score_rank_batch_id,
                    "score_rank_records": len(score_rank_records),
                    "data_notice": "内置样例数据为合成数据，仅用于演示多年度导入和算法流程，不代表真实录取结果。",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "import-admissions":
        records = load_admissions(args.admissions)
        with connect(args.db) as connection:
            batch_id, report = import_records(
                connection,
                records,
                args.admissions,
                args.batch_name,
                strict=not args.allow_invalid,
            )
        print(
            json.dumps(
                {"db": args.db, "batch_id": batch_id, "validation": asdict(report)},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "import-score-rank":
        if str(args.input).lower().endswith(".xls"):
            if args.year is None or not args.source_id:
                raise SystemExit("Official .xls score-rank imports require --year and --source-id.")
            records = load_summer_score_rank_xls(args.input, args.year, args.source_id)
        else:
            records = load_score_ranks(args.input, year=args.year, source_id=args.source_id)
        with connect(args.db) as connection:
            batch_id = import_score_rank_records(connection, records, args.input, args.batch_name)
        print(
            json.dumps(
                {"db": args.db, "batch_id": batch_id, "records": len(records)},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "list-batches":
        with connect(args.db) as connection:
            print(json.dumps({"db": args.db, "batches": list_batches(connection)}, ensure_ascii=False, indent=2))
    elif args.command == "recommend-db":
        with connect(args.db) as connection:
            records = fetch_admissions(connection)
        emit_recommendations(records, build_candidate(args), args.limit, args.rejection_limit)
    elif args.command == "plan":
        records = load_admissions(args.admissions)
        emit_plan(
            records,
            build_candidate(args),
            args.strategy,
            args.target_size,
            args.rejection_limit,
            parse_custom_quotas(args.custom_quotas),
        )
    elif args.command == "plan-db":
        with connect(args.db) as connection:
            records = fetch_admissions(connection)
        emit_plan(
            records,
            build_candidate(args),
            args.strategy,
            args.target_size,
            args.rejection_limit,
            parse_custom_quotas(args.custom_quotas),
        )
    elif args.command == "rank-plan-db":
        with connect(args.db) as connection:
            admissions = fetch_admissions(connection)
            score_ranks = fetch_score_ranks(connection)
        emit_rank_plan(
            admissions,
            score_ranks,
            build_candidate(args),
            args.strategy,
            args.target_size,
            args.band_width,
            args.rejection_limit,
            parse_custom_quotas(args.custom_quotas),
            parse_custom_risk_gaps(args.custom_risk_gaps),
        )


def add_candidate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--score", type=int, required=True)
    parser.add_argument("--rank", type=int, required=True)
    parser.add_argument("--subjects", nargs="+", required=True)
    parser.add_argument("--interests", nargs="*", default=[])
    parser.add_argument("--avoid", nargs="*", default=[])
    parser.add_argument("--preferred-cities", nargs="*", default=[])
    parser.add_argument("--blocked-cities", nargs="*", default=[])
    parser.add_argument("--max-tuition", type=int)
    parser.add_argument("--allow-private", action="store_true")
    parser.add_argument("--allow-sino-foreign", action="store_true")
    parser.add_argument("--require-known-subjects", action="store_true")
    parser.add_argument("--require-double-first-class", action="store_true")
    parser.add_argument("--require-985", action="store_true")
    parser.add_argument("--require-211", action="store_true")
    parser.add_argument("--require-public-undergraduate", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--rejection-limit", type=int, default=20)


def add_plan_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--strategy",
        choices=("aggressive", "balanced", "conservative", "custom"),
        default="balanced",
        help="志愿策略：激进、均衡、保守",
    )
    parser.add_argument("--target-size", type=int, default=96, help="目标志愿数量，山东普通类常规批默认 96")
    parser.add_argument("--custom-quotas", default="", help="自定义各档数量 JSON，例如 {\"冲\":16,\"稳\":30}")
    parser.add_argument("--custom-risk-gaps", default="", help="自定义分差 JSON，仅 rank-plan-db 使用")


def build_candidate(args: argparse.Namespace) -> CandidateProfile:
    return CandidateProfile(
        score=args.score,
        rank=args.rank,
        subjects=tuple(args.subjects),
        interests=tuple(args.interests),
        avoid_keywords=tuple(args.avoid),
        max_tuition=args.max_tuition,
        preferred_cities=tuple(args.preferred_cities),
        blocked_cities=tuple(args.blocked_cities),
        allow_private=args.allow_private,
        allow_sino_foreign=args.allow_sino_foreign,
        require_known_subjects=args.require_known_subjects,
        require_double_first_class=args.require_double_first_class,
        require_985=args.require_985,
        require_211=args.require_211,
        require_public_undergraduate=args.require_public_undergraduate,
    )


def parse_custom_quotas(value: str) -> dict[str, int] | None:
    return _parse_int_mapping(value, ("高冲", "冲", "稳中偏冲", "稳", "保", "强保"))


def parse_custom_risk_gaps(value: str) -> dict[str, int] | None:
    return _parse_int_mapping(value, ("challenge", "steady", "safe"))


def _parse_int_mapping(value: str, keys: tuple[str, ...]) -> dict[str, int] | None:
    if not value:
        return None
    try:
        raw = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON: {value}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("Custom argument must be a JSON object.")
    result: dict[str, int] = {}
    for key in keys:
        try:
            number = int(raw.get(key, 0))
        except (TypeError, ValueError):
            number = 0
        result[key] = max(0, number)
    return result if sum(result.values()) > 0 else None


def emit_recommendations(
    records: list,
    candidate: CandidateProfile,
    limit: int,
    rejection_limit: int,
) -> None:
    recommendations, rejections = recommend(records, candidate, limit=limit)
    visible_rejections = rejections[: max(0, rejection_limit)]
    payload = {
        "candidate": asdict(candidate),
        "record_count": len(records),
        "recommendations": [asdict(item) for item in recommendations],
        "rejections_total": len(rejections),
        "rejections_returned": len(visible_rejections),
        "rejections": [asdict(item) for item in visible_rejections],
        "disclaimer": "样例输出仅说明算法结构。正式填报必须使用官方真实数据、2026 招生计划和人工复核。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_plan(
    records: list,
    candidate: CandidateProfile,
    strategy: str,
    target_size: int,
    rejection_limit: int,
    custom_quotas: dict[str, int] | None = None,
) -> None:
    plan = build_volunteer_plan(
        records,
        candidate,
        strategy=strategy,
        target_size=target_size,
        custom_quotas=custom_quotas,
    )
    visible_rejections = plan.rejections[: max(0, rejection_limit)]
    payload = {
        "candidate": asdict(candidate),
        "record_count": len(records),
        "strategy": plan.strategy,
        "target_size": plan.target_size,
        "quotas": plan.quotas,
        "risk_counts": plan.risk_counts,
        "warnings": plan.warnings,
        "recommendations": [asdict(item) for item in plan.recommendations],
        "rejections_total": len(plan.rejections),
        "rejections_returned": len(visible_rejections),
        "rejections": [asdict(item) for item in visible_rejections],
        "disclaimer": "方案输出仅用于辅助决策。正式填报必须接入 2026 招生计划、选科要求、体检/备注限制，并人工复核。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def emit_rank_plan(
    admissions: list,
    score_ranks: list,
    candidate: CandidateProfile,
    strategy: str,
    target_size: int,
    band_width: int,
    rejection_limit: int,
    custom_quotas: dict[str, int] | None = None,
    custom_risk_gaps: dict[str, int] | None = None,
) -> None:
    band_plan = build_score_band_plan(
        admissions,
        score_ranks,
        candidate.rank,
        candidate,
        strategy=strategy,
        target_size=target_size,
        band_width=band_width,
        custom_quotas=custom_quotas,
        custom_risk_gaps=custom_risk_gaps,
    )
    plan = band_plan.plan
    visible_rejections = plan.rejections[: max(0, rejection_limit)]
    payload = {
        "candidate": asdict(candidate),
        "record_count": len(admissions),
        "score_rank_record_count": len(score_ranks),
        "equivalent_scores": [asdict(item) for item in band_plan.equivalent_scores],
        "band_matches": [asdict(item) for item in band_plan.band_matches],
        "strategy": plan.strategy,
        "target_size": plan.target_size,
        "risk_counts": plan.risk_counts,
        "warnings": plan.warnings,
        "recommendations": [asdict(item) for item in plan.recommendations],
        "rejections_total": len(plan.rejections),
        "rejections_returned": len(visible_rejections),
        "rejections": [asdict(item) for item in visible_rejections],
        "disclaimer": "按位次换算的一分一段等效分用于历史年份横向比较；正式填报仍必须接入 2026 招生计划、选科要求、招生章程和人工复核。",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
