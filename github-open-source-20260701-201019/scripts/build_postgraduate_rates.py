from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCE = {
    "source_id": "cacsc_2025_postgraduate_recommend_rate_ranking",
    "source": "2025年全国高校保研率排行榜",
    "source_url": "https://cacsc.com.cn/2025/2025%E5%B9%B4%E5%85%A8%E5%9B%BD%E9%AB%98%E6%A0%A1%E4%BF%9D%E7%A0%94%E7%8E%87%E6%8E%92%E8%A1%8C%E6%A6%9C.html",
    "source_type": "network_compilation",
    "cohort": "2025届",
    "confidence": "network_compilation",
    "note": "该表为网络整理榜单，字段为2025届推免名额和保研率；非教育部统一官方全量发布，填报前仍需以院校推免公示和毕业生人数口径复核。",
}

SUPPLEMENTAL_SOURCES = [
    {
        "source_id": "houbaoyan_2025_top15_postgraduate_recommend_rate",
        "source": "后保研：2025保研率排行榜前15名",
        "source_url": "https://www.houbaoyan.cn/articles/baoyan-ratio-2025",
        "source_type": "network_article_top15_reference",
        "cohort": "2025届",
        "note": "仅作为对照归档，未覆盖主表。",
    },
    {
        "source_id": "zhihu_2026_335_postgraduate_recommend_rate_images",
        "source": "知乎专栏：2026届全国高校保研率排行榜335所图片榜单",
        "source_url": "https://zhuanlan.zhihu.com/p/1971167853530052243",
        "source_type": "network_image_compilation_not_structured",
        "cohort": "2026届",
        "note": "页面为图片榜单且本机无可靠中文OCR，暂不自动结构化入库，避免误识别污染正式数据。",
    },
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value)
    return html.unescape(text).replace("\xa0", " ").strip()


def school_aliases(name: str) -> str:
    aliases: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in aliases:
            aliases.append(value)

    add(name)
    normalized = name.replace("（", "(").replace("）", ")")
    add(normalized)
    add(re.sub(r"\(校本部\)$", "", normalized))
    add(re.sub(r"\(主校区\)$", "", normalized))
    if "北京大学" in normalized and "医学部" in normalized:
        add("北京大学医学部")
    if "复旦大学" in normalized and "上海医学院" in normalized:
        add("复旦大学上海医学院")
    if "上海交通大学" in normalized and "医学院" in normalized:
        add("上海交通大学医学院")
    if "山东大学" in normalized and "威海" in normalized:
        add("山东大学威海分校")
        add("山东大学(威海)")
    return "|".join(aliases)


def parse_cacsc_table(path: Path, updated_at: str) -> list[dict[str, str]]:
    html_text = path.read_text(encoding="utf-8", errors="ignore")
    row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)
    cell_re = re.compile(r"<td[^>]*>(.*?)</td>", re.I | re.S)
    rows: list[dict[str, str]] = []
    for row_html in row_re.findall(html_text):
        cells = [clean_text(cell) for cell in cell_re.findall(row_html)]
        if len(cells) != 5:
            continue
        rank, school_level, school_name, quota, rate = cells
        if not rank.isdigit() or not school_name:
            continue
        rate_value = rate.replace("%", "").strip()
        rows.append(
            {
                "rank": str(int(rank)),
                "school_level": school_level,
                "school_name": school_name,
                "school_aliases": school_aliases(school_name),
                "cohort": SOURCE["cohort"],
                "recommend_quota": quota,
                "postgraduate_recommend_rate": rate_value,
                "rate_display": f"{rate_value}%",
                "source": SOURCE["source"],
                "source_url": SOURCE["source_url"],
                "source_id": SOURCE["source_id"],
                "source_type": SOURCE["source_type"],
                "confidence": SOURCE["confidence"],
                "updated_at": updated_at,
                "note": SOURCE["note"],
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "rank",
        "school_level",
        "school_name",
        "school_aliases",
        "cohort",
        "recommend_quota",
        "postgraduate_recommend_rate",
        "rate_display",
        "source",
        "source_url",
        "source_id",
        "source_type",
        "confidence",
        "updated_at",
        "note",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sources(path: Path, raw_main: Path, rows: list[dict[str, str]]) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "policy": "保研率采用学校层面网络整理数据，不作为教育部统一官方数据；系统展示时用于参考，正式填报前需按院校推免公示口径复核。",
        "sources": [
            {
                **SOURCE,
                "local_path": str(raw_main.relative_to(ROOT)),
                "sha256": sha256_file(raw_main),
                "structured_rows": len(rows),
                "rate_min": min((float(row["postgraduate_recommend_rate"]) for row in rows), default=None),
                "rate_max": max((float(row["postgraduate_recommend_rate"]) for row in rows), default=None),
            },
            *SUPPLEMENTAL_SOURCES,
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build curated postgraduate recommendation-rate data.")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--raw", default="data/raw/postgraduate_rates/cacsc_2025_rate_ranking.html")
    parser.add_argument("--output", default="data/curated/postgraduate_recommend_rates.csv")
    parser.add_argument("--sources-output", default="data/curated/postgraduate_recommend_rate_sources.json")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    raw = root / args.raw
    updated_at = datetime.now().date().isoformat()
    rows = parse_cacsc_table(raw, updated_at)
    rows.sort(key=lambda row: int(row["rank"]))
    output = root / args.output
    write_csv(output, rows)
    write_sources(root / args.sources_output, raw, rows)
    print(f"postgraduate rate rows: {len(rows)} -> {output}")


if __name__ == "__main__":
    main()
