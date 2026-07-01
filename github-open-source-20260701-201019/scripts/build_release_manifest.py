from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path

from gaokao_decision.commercial import APP_VERSION, BUILD_CHANNEL, PRODUCT_ID


DEFAULT_FILES = [
    "README.md",
    "DATA_SOURCES.md",
    "LICENSE",
    "SECURITY.md",
    "pyproject.toml",
    "data/sample/admissions_sample.csv",
    "data/sample/score_rank_sample.csv",
    "data/sources/sdzk_official_sources.json",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build open-source release manifest.")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--output", default="data/release_info.json", help="输出清单")
    parser.add_argument("--data-version", default="", help="自定义数据版本号")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    generated_at = datetime.now().isoformat(timespec="seconds")
    files = []
    for relative in DEFAULT_FILES:
        path = root / relative
        item = {"path": relative, "exists": path.exists()}
        if path.exists():
            item["size"] = path.stat().st_size
            item["sha256"] = sha256_file(path)
        files.append(item)

    data_version = args.data_version or f"open-sample-2023-2026-{datetime.now().strftime('%Y%m%d')}"
    payload = {
        "product_id": PRODUCT_ID,
        "build_channel": BUILD_CHANNEL,
        "app_version": APP_VERSION,
        "data_version": data_version,
        "generated_at": generated_at,
        "scope": "Open-source code and synthetic sample data only. Official raw pages, full official databases, curated third-party data, customer packages, credentials, and license materials are excluded.",
        "files": files,
    }
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"数据清单已生成：{output}")


if __name__ == "__main__":
    main()
