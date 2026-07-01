from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


APP_VERSION = "0.1.0"
PRODUCT_ID = "shandong-gaokao-decision"
BUILD_CHANNEL = "open-source"


def project_root_from(path: Path | None = None) -> Path:
    if path is not None:
        resolved = path.resolve()
        if resolved.is_file():
            resolved = resolved.parent
        for parent in (resolved, *resolved.parents):
            if (parent / "src" / "gaokao_decision").exists() and (parent / "scripts").exists():
                return parent
            if (parent / "data" / "processed").exists() and (parent / "scripts" / "serve_app.py").exists():
                return parent
    return Path(__file__).resolve().parents[2]


def load_release_info(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root_from()
    path = root / "data" / "release_info.json"
    if not path.exists():
        return {
            "app_version": APP_VERSION,
            "product_id": PRODUCT_ID,
            "build_channel": BUILD_CHANNEL,
            "data_version": "未生成数据清单",
            "generated_at": "",
            "files": [],
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "app_version": APP_VERSION,
            "product_id": PRODUCT_ID,
            "build_channel": BUILD_CHANNEL,
            "data_version": "数据清单解析失败",
            "generated_at": "",
            "files": [],
        }


def system_info_payload(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root_from()
    return {
        "app_version": APP_VERSION,
        "product_id": PRODUCT_ID,
        "build_channel": BUILD_CHANNEL,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "release": load_release_info(root),
    }
