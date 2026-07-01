from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "gaokao-decision-source-archiver/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def extension_from_url(url: str, default: str = ".bin") -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix
    return suffix or default


def write_bytes(path: Path, content: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": str(path),
        "bytes": len(content),
        "sha256": sha256_bytes(content),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive official SDZK source pages and attachments.")
    parser.add_argument("--sources", default="data/sources/sdzk_official_sources.json")
    parser.add_argument("--out-dir", default="data/raw/sdzk")
    args = parser.parse_args()

    source_path = Path(args.sources)
    out_dir = Path(args.out_dir)
    registry = json.loads(source_path.read_text(encoding="utf-8"))
    archive_entries: list[dict[str, object]] = []

    for item in registry["sources"]:
        source_id = item["source_id"]
        entry: dict[str, object] = {
            "source_id": source_id,
            "page_url": item["page_url"],
            "attachment_url": item.get("attachment_url"),
            "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }

        page_content = fetch(item["page_url"])
        entry["page"] = write_bytes(out_dir / f"{source_id}.html", page_content)

        attachment_url = item.get("attachment_url")
        if attachment_url:
            attachment_content = fetch(attachment_url)
            ext = extension_from_url(attachment_url)
            entry["attachment"] = write_bytes(out_dir / f"{source_id}{ext}", attachment_content)

        archive_entries.append(entry)

    manifest = {
        "registry": str(source_path),
        "archive_dir": str(out_dir),
        "entries": archive_entries,
    }
    manifest_path = out_dir / "archive_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

