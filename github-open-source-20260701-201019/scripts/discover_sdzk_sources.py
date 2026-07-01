from __future__ import annotations

import argparse
import json
import re
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin


class AttachmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.attachments: list[dict[str, str]] = []
        self._in_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        if tag.lower() == "h1":
            self._in_h1 = True
        if tag.lower() == "a":
            href = attrs_map.get("href", "")
            if re.search(r"\.(xls|xlsx|csv|doc|docx)$", href, re.I):
                self.attachments.append({"href": href, "title": attrs_map.get("title", "")})

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self.title += data.strip()


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def inspect_page(url: str) -> dict[str, object]:
    parser = AttachmentParser()
    parser.feed(fetch(url))
    return {
        "page_url": url,
        "title": parser.title,
        "attachments": [
            {"url": urljoin(url, item["href"]), "title": item["title"]} for item in parser.attachments
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover attachments from SDZK news pages.")
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    print(json.dumps([inspect_page(url) for url in args.urls], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

