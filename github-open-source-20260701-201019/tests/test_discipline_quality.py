import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _serve_app_module():
    spec = importlib.util.spec_from_file_location("serve_app", ROOT / "scripts" / "serve_app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_fifth_round_discipline_quality_payload_is_preferred_when_structured():
    module = _serve_app_module()
    payload = module._discipline_quality_payload({"option_name": "山东大学 / 数学与应用数学"})

    assert payload["discipline"] == "数学"
    assert payload["assessment_grade"] == "A+"
    assert payload["assessment_round"] == "第五轮"
    assert payload["discipline_assessment"] == "第五轮 A+"
    assert payload["confidence"] == "network_compilation"


def test_excel_source_marker_is_not_shown_as_assessment_round():
    module = _serve_app_module()
    payload = module._discipline_quality_payload({"option_name": "北京邮电大学 / 计算机类"})

    assert payload["assessment_round"] in {"第四轮", "第五轮"}
    assert "Excel" not in payload["discipline_assessment"]
    assert "待核验" not in payload["discipline_assessment"]
    assert "补充" not in payload["discipline_assessment"]


def test_fourth_round_remains_available_when_fifth_round_has_no_school_match():
    module = _serve_app_module()
    payload = module._discipline_quality_payload({"option_name": "东北大学秦皇岛分校 / 数学类"})

    assert payload["discipline"] == "数学"
    assert payload["assessment_round"] == "第四轮"
    assert payload["confidence"] == "official"


def test_postgraduate_recommend_rate_payload_is_school_level():
    module = _serve_app_module()
    payload = module._discipline_quality_payload({"option_name": "北京大学 / 数学类"})

    assert payload["postgraduate_recommend_rate"] == "65.07"
    assert payload["postgraduate_recommend_rate_cohort"] == "2025届"
    assert payload["postgraduate_recommend_rate_confidence"] == "network_compilation"


def test_postgraduate_recommend_rate_can_show_without_discipline_match():
    module = _serve_app_module()
    payload = module._discipline_quality_payload({"option_name": "北京大学 / 未知专业"})

    assert "discipline_assessment" not in payload
    assert payload["postgraduate_recommend_rate"] == "65.07"


def test_fifth_round_source_is_not_marked_official_full_release():
    sources = json.loads((ROOT / "data" / "curated" / "discipline_quality_sources.json").read_text(encoding="utf-8"))
    fifth = next(
        item
        for item in sources["sources"]
        if item["source_id"] == "fifth_round_network_compilation_gaokaozhitongche_2023"
    )
    image_archive = next(
        item
        for item in sources["sources"]
        if item["source_id"] == "fifth_round_network_compilation_baai_datawhale_2025"
    )

    assert fifth["source_type"] == "network_compilation_not_official_full_release"
    assert fifth["structured_rows"] >= 200
    assert image_archive["image_count"] >= 1


def test_postgraduate_rate_source_policy():
    sources = json.loads((ROOT / "data" / "curated" / "postgraduate_recommend_rate_sources.json").read_text(encoding="utf-8"))
    main = sources["sources"][0]
    image_source = next(item for item in sources["sources"] if item["source_id"] == "zhihu_2026_335_postgraduate_recommend_rate_images")

    assert main["structured_rows"] == 200
    assert main["confidence"] == "network_compilation"
    assert image_source["source_type"] == "network_image_compilation_not_structured"
