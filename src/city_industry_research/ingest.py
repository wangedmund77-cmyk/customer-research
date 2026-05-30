"""Ingest official URLs into an evidence corpus."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Iterable
from urllib.parse import urlparse
import urllib.request

from .source_discovery import build_evidence_template


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        text = _clean_space(data)
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif not self._skip_depth:
            self.text_parts.append(text)

    @property
    def title(self) -> str:
        return _clean_space(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return _clean_space(" ".join(self.text_parts))


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_url_list(lines: Iterable[str]) -> list[str]:
    urls: list[str] = []
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


def fetch_url_text(url: str, timeout_seconds: int = 30) -> tuple[str, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "city-industry-research/0.1 (+authority-source-research)",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read()

    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return (_filename_title(url), content_type, "PDF 文件已登记；请人工或用 PDF 工具抽取关键页摘录后补入 excerpt。")

    encoding = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, flags=re.I)
    if match:
        encoding = match.group(1)
    html = raw.decode(encoding, errors="replace")
    parser = _TextExtractor()
    parser.feed(html)
    title = parser.title or _filename_title(url)
    return title, content_type, parser.text


def build_evidence_from_urls(
    urls: list[str],
    city: str,
    province: str = "",
    report_year: int = 2026,
    tags: list[str] | None = None,
    max_excerpt_chars: int = 3000,
) -> dict:
    evidence = build_evidence_template(city=city, province=province, report_year=report_year)
    evidence["sources"] = []
    for index, url in enumerate(urls, start=1):
        try:
            title, content_type, text = fetch_url_text(url)
            excerpt = text[:max_excerpt_chars].strip()
            notes = ""
        except Exception as exc:  # noqa: BLE001 - store fetch errors as evidence gaps.
            title = _filename_title(url)
            content_type = ""
            excerpt = ""
            notes = f"抓取失败：{exc}"

        evidence["sources"].append(
            {
                "id": f"S{index:03d}",
                "title": title,
                "url": url,
                "publisher": _guess_publisher(url),
                "published_date": "",
                "source_type": _guess_source_type(url, content_type),
                "credibility": "official_candidate",
                "tags": tags or [],
                "excerpt": excerpt,
                "notes": notes,
            }
        )
    return evidence


def _guess_source_type(url: str, content_type: str) -> str:
    host = urlparse(url).netloc.lower()
    if "gov.cn" in host:
        return "government_website"
    if "cninfo.com.cn" in host or "sse.com.cn" in host or "szse.cn" in host:
        return "exchange_filing"
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return "pdf"
    return "official_candidate"


def _guess_publisher(url: str) -> str:
    return urlparse(url).netloc


def _filename_title(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or urlparse(url).netloc or url
