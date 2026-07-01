from gaokao_decision.models import AdmissionRecord
from scripts.serve_app import (
    _backtest_summary,
    _create_data_source_year,
    _data_source_records_payload,
    _data_sources_payload,
    _delete_data_source,
    _delete_uploaded_data_source,
    _export_data_source,
    _import_data_source,
    _save_uploaded_data_source,
    _template_response,
    _update_data_source_record,
)


def test_backtest_uses_stable_option_group_for_changed_annual_codes():
    records = [
        AdmissionRecord(2023, "test", "A422", "山东大学", "Z5", "网络空间安全", None, 7500, 75),
        AdmissionRecord(2024, "test", "A422", "山东大学", "ZT", "网络空间安全", None, 8000, 95),
        AdmissionRecord(2025, "test", "A422", "山东大学", "Y8", "网络空间安全", None, 7900, 96),
    ]

    summary = _backtest_summary(records)

    assert summary["sample_count"] == 1
    assert summary["median_abs_error"] == 150


def test_data_source_upload_list_and_delete(tmp_path):
    boundary = "----testboundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="category"\r\n\r\n'
        "admission\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="description"\r\n\r\n'
        "人工补充测试\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="test.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        "school_code,major_name\nA000,测试专业\n\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    item = _save_uploaded_data_source(tmp_path, f"multipart/form-data; boundary={boundary}", body)
    payload = _data_sources_payload(tmp_path)

    assert item["id"]
    assert payload["upload_count"] == 1
    assert any(entry.get("id") == item["id"] and entry.get("deletable") for entry in payload["items"])

    result = _delete_uploaded_data_source(tmp_path, str(item["id"]))
    payload = _data_sources_payload(tmp_path)

    assert result["deleted"] is True
    assert payload["upload_count"] == 0


def test_data_source_template_response_has_csv_bom():
    body, content_type, filename = _template_response("admission")

    assert filename.endswith(".csv")
    assert content_type.startswith("text/csv")
    assert body.startswith("\ufeffyear,source_id".encode("utf-8"))


def test_data_source_import_export_delete_database_year(tmp_path):
    db_path = tmp_path / "official.sqlite"
    boundary = "----importboundary"
    csv_body = (
        "year,source_id,school_code,school_name,major_code,major_name,min_score,min_rank,plan_count,subjects\n"
        "2025,test,A000,样例大学,01,软件工程,600,30000,10,物理|化学\n"
    ).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="data_type"\r\n\r\n'
        "admission\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="year"\r\n\r\n'
        "2025\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="mode"\r\n\r\n'
        "replace\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="admission.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode("utf-8") + csv_body + f"\r\n--{boundary}--\r\n".encode("utf-8")

    result = _import_data_source(tmp_path, db_path, f"multipart/form-data; boundary={boundary}", body)
    exported, content_type, filename = _export_data_source(tmp_path, db_path, "admission", 2025)
    delete_result = _delete_data_source(tmp_path, db_path, {"data_type": "admission", "year": 2025})

    assert result["records"] == 1
    assert filename == "admission_records_2025.csv"
    assert content_type.startswith("text/csv")
    assert "样例大学".encode("utf-8") in exported
    assert delete_result["records"] == 1


def test_data_sources_payload_has_fixed_yearly_requirements(tmp_path):
    db_path = tmp_path / "official.sqlite"
    payload = _data_sources_payload(tmp_path, db_path)
    items_2026 = [item for item in payload["yearly_items"] if item.get("year") == 2026]
    categories_2026 = {item.get("category"): item for item in items_2026}

    assert 2026 in payload["years"]
    assert "admission" in categories_2026
    assert "score_rank" in categories_2026
    assert "major_catalog" in categories_2026
    assert categories_2026["admission"]["status"] == "待导入"
    assert categories_2026["admission"]["importable"] is True
    assert categories_2026["admission"]["record_viewable"] is False


def test_data_source_year_can_be_created_and_uses_year_paths(tmp_path):
    db_path = tmp_path / "official.sqlite"
    result = _create_data_source_year(tmp_path, {"year": 2027, "copy_previous": True, "base_year": 2026})
    payload = _data_sources_payload(tmp_path, db_path)
    items_2027 = [item for item in payload["yearly_items"] if item.get("year") == 2027]
    categories_2027 = {item.get("category"): item for item in items_2027}

    assert result["year"] == 2027
    assert 2027 in payload["years"]
    assert categories_2027["admission"]["status"] == "待导入"
    assert categories_2027["major_catalog"]["status"] == "待导入"
    assert categories_2027["major_catalog"]["path"].endswith("undergraduate_majors_2027.json")
    assert categories_2027["plan_supplement"]["path"].endswith("official_2027_plan_supplements.csv")


def test_data_source_records_view_and_update_database_row(tmp_path):
    db_path = tmp_path / "official.sqlite"
    boundary = "----recordboundary"
    csv_body = (
        "year,source_id,school_code,school_name,major_code,major_name,min_score,min_rank,plan_count,subjects\n"
        "2025,test,A000,样例大学,01,软件工程,600,30000,10,物理|化学\n"
    ).encode("utf-8")
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="data_type"\r\n\r\n'
        "admission\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="year"\r\n\r\n'
        "2025\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="mode"\r\n\r\n'
        "replace\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="admission.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
    ).encode("utf-8") + csv_body + f"\r\n--{boundary}--\r\n".encode("utf-8")

    _import_data_source(tmp_path, db_path, f"multipart/form-data; boundary={boundary}", body)
    payload = _data_source_records_payload(tmp_path, db_path, "admission", 2025, "软件", 1, 25)
    key = payload["rows"][0]["key"]
    result = _update_data_source_record(
        tmp_path,
        db_path,
        {"data_type": "admission", "key": key, "values": {"major_name": "计算机科学与技术", "min_rank": "28000"}},
    )
    updated = _data_source_records_payload(tmp_path, db_path, "admission", 2025, "计算机科学", 1, 25)

    assert result["updated"] is True
    assert updated["total"] == 1
    assert updated["rows"][0]["values"]["major_name"] == "计算机科学与技术"
    assert updated["rows"][0]["values"]["min_rank"] == "28000"


def test_data_source_records_view_and_update_csv_file(tmp_path):
    path = tmp_path / "data" / "curated" / "discipline_quality.csv"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\ufeffschool_name,discipline,assessment_grade,note\n样例大学,计算机科学与技术,B,原备注\n",
        encoding="utf-8",
    )

    payload = _data_source_records_payload(tmp_path, tmp_path / "official.sqlite", "discipline_quality", None, "样例", 1, 25)
    key = payload["rows"][0]["key"]
    result = _update_data_source_record(
        tmp_path,
        tmp_path / "official.sqlite",
        {"data_type": "discipline_quality", "key": key, "values": {"assessment_grade": "A", "note": "已复核"}},
    )
    updated = _data_source_records_payload(tmp_path, tmp_path / "official.sqlite", "discipline_quality", None, "已复核", 1, 25)

    assert result["updated"] is True
    assert result["backup"]
    assert updated["rows"][0]["values"]["assessment_grade"] == "A"
    assert updated["rows"][0]["values"]["note"] == "已复核"


def test_data_source_records_view_and_update_json_file(tmp_path):
    path = tmp_path / "data" / "processed" / "interest_major_map.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"majors": {"软件工程": {"direct": ["软件"], "related": ["计算机"]}}}\n',
        encoding="utf-8",
    )

    payload = _data_source_records_payload(tmp_path, tmp_path / "official.sqlite", "interest_map", None, "软件工程", 1, 25)
    key = payload["rows"][0]["key"]
    result = _update_data_source_record(
        tmp_path,
        tmp_path / "official.sqlite",
        {"data_type": "interest_map", "key": key, "values": {"direct": "计算机、软件", "related": "人工智能"}},
    )
    updated = _data_source_records_payload(tmp_path, tmp_path / "official.sqlite", "interest_map", None, "人工智能", 1, 25)

    assert result["updated"] is True
    assert updated["rows"][0]["values"]["direct"] == "计算机、软件"
    assert updated["rows"][0]["values"]["related"] == "人工智能"
