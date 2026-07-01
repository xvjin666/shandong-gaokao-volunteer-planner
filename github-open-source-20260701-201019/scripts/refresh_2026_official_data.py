from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.parse import urljoin


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gaokao_decision.database import connect, import_score_rank_records  # noqa: E402
from gaokao_decision.sdzk_parser import load_summer_score_rank_xls  # noqa: E402


BASE_URL = "https://www.sdzk.cn/"
CHECK_PAGES = [
    "https://www.sdzk.cn/",
    "https://www.sdzk.cn/NewsList.aspx?BCID=1081&CID=1083",
    "https://www.sdzk.cn/NewsListM.aspx?BCID=2&CID=20",
    "https://www.sdzk.cn/NewsList.aspx?BCID=20&CID=1117",
    "https://www.sdzk.cn/NewsList.aspx?BCID=20&CID=1204",
    "https://www.sdzk.cn/NewsList.aspx?BCID=1&CID=16",
]
BUSINESS_PAGES = {
    "score_query": "https://www.sdzk.cn/Business.aspx?BID=1",
    "volunteer_entry": "https://www.sdzk.cn/Business.aspx?BID=4",
}
FILE_RE = re.compile(r"""href=["']([^"']+\.(?:xls|xlsx|pdf|doc|docx|zip))["']""", re.I)
IMAGE_RE = re.compile(r"""<img[^>]+src=["']([^"']+\.(?:png|jpg|jpeg|gif))["']""", re.I)
NEWS_LINK_RE = re.compile(r"""<a[^>]+href=["']([^"']*NewsInfo\.aspx\?NewsID=\d+[^"']*)["'][^>]*>(.*?)</a>""", re.I | re.S)


@dataclass(frozen=True)
class WatchItem:
    key: str
    source_id: str
    kind: str
    required_terms: tuple[str, ...]
    optional_terms: tuple[str, ...] = ()
    import_score_rank: bool = False
    plan_like: bool = False


WATCH_ITEMS = [
    WatchItem(
        key="score_rank",
        source_id="sdzk_2026_summer_score_rank",
        kind="夏季高考文化成绩一分一段表",
        required_terms=("2026", "夏季高考", "文化成绩", "一分一段表"),
        import_score_rank=True,
    ),
    WatchItem(
        key="score_lines",
        source_id="sdzk_2026_score_lines",
        kind="夏季高考各类别分数线",
        required_terms=("2026", "夏季高考", "分数线"),
    ),
    WatchItem(
        key="admission_plan",
        source_id="sdzk_2026_admission_plan",
        kind="普通高校分专业招生计划",
        required_terms=("2026", "招生计划"),
        optional_terms=("分专业", "院校专业计划", "常规批", "补充信息", "志愿"),
        plan_like=True,
    ),
    WatchItem(
        key="admission_schedule",
        source_id="sdzk_2026_admission_schedule",
        kind="普通高校招生录取工作进程表",
        required_terms=("山东省2026年普通高校招生录取工作进程表",),
    ),
    WatchItem(
        key="admission_opinion",
        source_id="sdzk_2026_admission_opinion",
        kind="普通高等学校招生录取工作意见",
        required_terms=("山东省2026年普通高等学校招生录取工作的意见",),
    ),
    WatchItem(
        key="volunteer_four_steps",
        source_id="sdzk_2026_volunteer_four_steps",
        kind="高考志愿填报四部曲",
        required_terms=("2026", "高考志愿填报四部曲"),
    ),
]


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 gaokao-decision-official-refresh/0.2",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def decode_page(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def clean_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_title(html: str) -> str:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    if match:
        return clean_html(match.group(1))
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    return clean_html(match.group(1)) if match else ""


def extract_date(html: str) -> str:
    match = re.search(r"发布时间[:：]\s*(\d{4}-\d{2}-\d{2})", html)
    return match.group(1) if match else ""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_bytes(path: Path, content: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(content),
        "sha256": sha256_bytes(content),
    }


def extension_from_url(url: str, fallback: str = ".bin") -> str:
    path = Path(url.split("?", 1)[0])
    return path.suffix or fallback


def find_news_pages(scan_start: int, scan_end: int) -> dict[str, str]:
    pages: dict[str, str] = {}
    for page_url in CHECK_PAGES:
        try:
            html = decode_page(fetch(page_url))
        except Exception as exc:
            print(f"跳过列表页 {page_url}: {exc}")
            continue
        for href, title_html in NEWS_LINK_RE.findall(html):
            url = urljoin(BASE_URL, href.replace("&amp;", "&"))
            title = clean_html(title_html)
            if "2026" in title or "高考" in title or "招生" in title:
                pages[url] = title

    for news_id in range(scan_start, scan_end + 1):
        pages.setdefault(f"https://www.sdzk.cn/NewsInfo.aspx?NewsID={news_id}", "")
    return pages


def watch_matches(title: str, watch: WatchItem) -> bool:
    if not title:
        return False
    if not all(term in title for term in watch.required_terms):
        return False
    if watch.optional_terms and not any(term in title for term in watch.optional_terms):
        return False
    if watch.plan_like and any(term in title for term in ("成人高考", "专升本", "注册入学", "军队院校", "公安院校")):
        return False
    return True


def first_watch_for(title: str) -> WatchItem | None:
    for watch in WATCH_ITEMS:
        if watch_matches(title, watch):
            return watch
    return None


def archive_news(
    watch: WatchItem,
    url: str,
    html: str,
    raw_dir: Path,
    download_assets: bool,
) -> dict[str, object]:
    page_file = write_bytes(raw_dir / f"{watch.source_id}.html", html.encode("utf-8"))
    attachments: list[dict[str, object]] = []
    attachment_urls: list[str] = []
    for index, href in enumerate(dict.fromkeys(FILE_RE.findall(html)).keys(), start=1):
        attachment_url = urljoin(BASE_URL, href)
        attachment_urls.append(attachment_url)
        ext = extension_from_url(attachment_url)
        suffix = "" if index == 1 else f"_{index}"
        try:
            content = fetch(attachment_url)
            attachments.append(
                {
                    "url": attachment_url,
                    **write_bytes(raw_dir / f"{watch.source_id}{suffix}{ext}", content),
                }
            )
        except Exception as exc:
            attachments.append({"url": attachment_url, "error": str(exc)})

    images: list[dict[str, object]] = []
    if download_assets:
        for index, src in enumerate(dict.fromkeys(IMAGE_RE.findall(html)).keys(), start=1):
            image_url = urljoin(BASE_URL, src)
            if "/images/" in image_url or "logo" in image_url.lower() or "fileTypeImages" in image_url:
                continue
            ext = extension_from_url(image_url, ".png")
            try:
                content = fetch(image_url)
                images.append({"url": image_url, **write_bytes(raw_dir / f"{watch.source_id}_image_{index}{ext}", content)})
            except Exception as exc:
                images.append({"url": image_url, "error": str(exc)})

    return {
        "source_id": watch.source_id,
        "page_url": url,
        "kind": watch.kind,
        "page": page_file,
        "attachment_urls": attachment_urls,
        "attachments": attachments,
        "images": images,
    }


def update_source_registry(found_items: dict[str, dict[str, object]], sources_path: Path) -> None:
    if sources_path.exists():
        registry = json.loads(sources_path.read_text(encoding="utf-8"))
    else:
        registry = {
            "province": "山东省",
            "exam_type": "夏季高考普通类",
            "authority": "山东省教育招生考试院",
            "sources": [],
        }
    sources = registry.setdefault("sources", [])
    by_id = {item.get("source_id"): item for item in sources}
    for item in found_items.values():
        source_id = item["source_id"]
        source = {
            "source_id": source_id,
            "year": 2026,
            "kind": item.get("kind", ""),
            "page_url": item.get("page_url", ""),
            "attachment_url": (item.get("attachment_urls") or [None])[0],
            "published_at": item.get("published_at", ""),
            "status": "confirmed",
        }
        if source_id in by_id:
            by_id[source_id].update(source)
        else:
            sources.append(source)
    sources_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def import_score_rank_if_available(item: dict[str, object], db_path: Path, force: bool) -> dict[str, object]:
    attachments = item.get("attachments") or []
    xls_files = [
        ROOT / attachment["path"]
        for attachment in attachments
        if isinstance(attachment, dict)
        and "path" in attachment
        and str(attachment["path"]).lower().endswith((".xls", ".xlsx"))
    ]
    if not xls_files:
        return {"imported": False, "reason": "未发现一分一段 xls/xlsx 附件"}

    source_id = str(item["source_id"])
    records = load_summer_score_rank_xls(xls_files[0], 2026, source_id)
    official_rows = [(record.score, record.segment_count, record.cumulative_count) for record in records]
    processed_path = ROOT / "data" / "processed" / "sdzk" / f"{source_id}.csv"
    processed_info = write_score_rank_csv(processed_path, records)
    with connect(db_path) as connection:
        existing_rows = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT score, segment_count, cumulative_count
                FROM score_rank_records
                WHERE year = 2026 AND source_id = ?
                ORDER BY score DESC
                """,
                (source_id,),
            ).fetchall()
        ]
        existing = len(existing_rows)
        if existing and not force and existing_rows == official_rows:
            return {
                "imported": False,
                "reason": f"数据库已存在 {existing} 条 2026 一分一段记录，且与本次官方附件逐项一致",
                "records": existing,
                "source_file": str(xls_files[0].relative_to(ROOT)),
                "processed": processed_info,
                "verified_against_attachment": True,
            }
        if existing:
            connection.execute(
                "DELETE FROM score_rank_records WHERE year = 2026 AND source_id = ?",
            (source_id,),
            )
            connection.commit()

        batch_id = import_score_rank_records(connection, records, str(xls_files[0]), "sdzk-2026-score-rank")
        return {
            "imported": True,
            "batch_id": batch_id,
            "records": len(records),
            "source_file": str(xls_files[0].relative_to(ROOT)),
            "processed": processed_info,
            "replaced_existing_records": existing,
        }


def write_score_rank_csv(path: Path, records: list[object]) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["year", "source_id", "score", "segment_count", "cumulative_count", "subject_group"])
        for record in records:
            writer.writerow(
                [
                    record.year,
                    record.source_id,
                    record.score,
                    record.segment_count,
                    record.cumulative_count,
                    record.subject_group,
                ]
            )
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_bytes(path.read_bytes()),
    }


def business_status(url: str) -> dict[str, object]:
    try:
        html = decode_page(fetch(url))
    except Exception as exc:
        return {"url": url, "available": False, "error": str(exc)}
    text = clean_html(html)
    unavailable = "当前时段，无" in text
    summary_match = re.search(r"当前时段，无[^。]*。?", text)
    return {
        "url": url,
        "available": not unavailable,
        "summary": "已开放" if not unavailable else (summary_match.group(0) if summary_match else text[:80]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh official 2026 SDZK public data and status.")
    parser.add_argument("--root", default=str(ROOT), help="项目根目录")
    parser.add_argument("--db", default="data/local/gaokao.sqlite", help="SQLite 数据库")
    parser.add_argument("--raw-dir", default="data/raw/sdzk", help="官方原始文件归档目录")
    parser.add_argument("--status-output", default="data/processed/official_2026_status.json", help="状态 JSON 输出")
    parser.add_argument("--sources", default="data/sources/sdzk_official_sources.json", help="官方来源登记文件")
    parser.add_argument("--scan-start", type=int, default=7240, help="扫描 NewsID 起点")
    parser.add_argument("--scan-end", type=int, default=7300, help="扫描 NewsID 终点")
    parser.add_argument("--no-source-update", action="store_true", help="不更新 sources JSON")
    parser.add_argument("--force-score-rank", action="store_true", help="重新导入已存在的 2026 一分一段记录")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    raw_dir = root / args.raw_dir
    status_path = root / args.status_output
    sources_path = root / args.sources
    db_path = root / args.db
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    found_items: dict[str, dict[str, object]] = {}
    latest_titles: list[dict[str, str]] = []

    for url, list_title in find_news_pages(args.scan_start, args.scan_end).items():
        try:
            content = fetch(url)
        except Exception:
            continue
        html = decode_page(content)
        title = extract_title(html) or list_title
        if not title or title == "山东省教育招生考试院官网":
            continue
        if "2026" in title and len(latest_titles) < 40:
            latest_titles.append({"title": title, "url": url})
        watch = first_watch_for(title)
        if not watch:
            continue
        if watch.key in found_items:
            continue
        archive = archive_news(watch, url, html, raw_dir, download_assets=True)
        archive["title"] = title
        archive["published_at"] = extract_date(html)
        found_items[watch.key] = archive

    imports: dict[str, object] = {}
    score_item = found_items.get("score_rank")
    if score_item:
        imports["score_rank"] = import_score_rank_if_available(score_item, db_path, args.force_score_rank)

    if not args.no_source_update:
        update_source_registry(found_items, sources_path)

    items: dict[str, dict[str, object]] = {}
    for watch in WATCH_ITEMS:
        if watch.key in found_items:
            payload = dict(found_items[watch.key])
            payload["found"] = True
            if watch.key in imports:
                payload["import"] = imports[watch.key]
            items[watch.key] = payload
        else:
            items[watch.key] = {
                "found": False,
                "source_id": watch.source_id,
                "kind": watch.kind,
                "summary": "本次官方公开页扫描未发现。",
            }

    status = {
        "checked_at": checked_at,
        "authority": "山东省教育招生考试院",
        "scope": "2026 山东夏季高考普通类公开数据状态核验",
        "business": {key: business_status(url) for key, url in BUSINESS_PAGES.items()},
        "items": items,
        "latest_titles": latest_titles,
        "check_pages": CHECK_PAGES,
        "scan_range": [args.scan_start, args.scan_end],
        "note": "只归档山东省教育招生考试院公开页面能访问到的内容；未发现不等于以后不会发布，正式填报前仍需再次刷新核验。",
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_bytes(raw_dir / "official_2026_refresh_manifest.json", json.dumps(status, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
