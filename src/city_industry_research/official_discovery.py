"""Automatic authority-source discovery for city industry research."""

from __future__ import annotations

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import urllib.error
import urllib.request

from .ingest import fetch_url_text
from .source_discovery import SearchQuery, build_evidence_template, build_search_queries


OFFICIAL_DOMAIN_KEYWORDS = (
    "gov.cn",
    "stats.gov.cn",
    "ndrc.gov.cn",
    "miit.gov.cn",
    "mofcom.gov.cn",
    "chinatax.gov.cn",
    "samr.gov.cn",
    "mohrss.gov.cn",
    "mee.gov.cn",
    "most.gov.cn",
    "sasac.gov.cn",
    "pbc.gov.cn",
    "csrc.gov.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "cninfo.com.cn",
    "neeq.com.cn",
    "xinhuanet.com",
    "people.com.cn",
    "cctv.com",
    "china.com.cn",
    "ce.cn",
    "jschina.com.cn",
    "zjol.com.cn",
    "southcn.com",
    "iqilu.com",
    "mp.weixin.qq.com",
)


NOISE_DOMAINS = (
    "baidu.com",
    "bing.com",
    "google.com",
    "sogou.com",
    "so.com",
    "zhihu.com",
    "douyin.com",
    "bilibili.com",
    "weibo.com",
    "toutiao.com",
    "163.com",
    "sohu.com",
)


CATEGORY_TAGS = {
    "城市产业识别": ["industry_plan", "government_work_report"],
    "产业规模与统计": ["statistics_bulletin"],
    "技术突破与市场地位": ["industry_it", "official_media"],
    "上下游协同与生态": ["industry_plan", "development_reform"],
    "近三年政策与规划": ["government_work_report", "industry_plan", "development_reform"],
    "双碳与数字化": ["dual_carbon", "digital_transformation"],
    "人才与创新平台": ["talent_policy"],
    "企业榜单": ["tax_or_top_list"],
    "上市公司与资本市场": ["listed_company"],
    "外商投资企业": ["commerce_fdi"],
    "电气业务机会": ["development_reform", "dual_carbon", "digital_transformation"],
}


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str = ""
    query: str = ""
    category: str = ""
    source_rank: int = 0
    score: int = 0


class _SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if href:
            self._href = href
            self._text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = _clean_space(" ".join(self._text_parts))
        self.links.append((self._href, title))
        self._href = None
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)


def discover_official_sources(
    city: str,
    province: str = "",
    report_year: int = 2026,
    query_limit: int = 48,
    results_per_query: int = 8,
    max_sources: int = 120,
    sleep_seconds: float = 0.15,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[SearchHit]:
    """Search the open web and keep authority-source candidates."""

    queries = build_search_queries(city=city, province=province, report_year=report_year)[:query_limit]
    _emit_progress(
        progress_callback,
        stage="检索准备",
        status="running",
        detail=f"生成 {len(queries)} 个权威来源检索式，准备自动搜索。",
        total_queries=len(queries),
    )
    seen: set[str] = set()
    hits: list[SearchHit] = []
    for query_index, query in enumerate(queries, start=1):
        _emit_progress(
            progress_callback,
            stage="权威来源搜索",
            status="running",
            detail=f"检索式 {query_index}/{len(queries)}：{query.query}",
            category=query.category,
            query=query.query,
        )
        raw_hits = search_query(query, max_results=results_per_query)
        _emit_progress(
            progress_callback,
            stage="搜索结果解析",
            status="done",
            detail=f"检索式返回 {len(raw_hits)} 条候选结果，开始筛选权威域名。",
            category=query.category,
            query=query.query,
            raw_hits=len(raw_hits),
        )
        accepted_for_query = 0
        for rank, hit in enumerate(raw_hits, start=1):
            cleaned_url = normalize_result_url(hit.url)
            if not cleaned_url or cleaned_url in seen:
                continue
            score = score_authority_url(cleaned_url, hit.title, hit.snippet, city, query)
            if score < 2:
                continue
            seen.add(cleaned_url)
            accepted_for_query += 1
            hits.append(
                SearchHit(
                    url=cleaned_url,
                    title=hit.title,
                    snippet=hit.snippet,
                    query=query.query,
                    category=query.category,
                    source_rank=rank,
                    score=score,
                )
            )
            _emit_progress(
                progress_callback,
                stage="权威来源筛选",
                status="accepted",
                detail=f"保留来源：{hit.title or cleaned_url}",
                category=query.category,
                query=query.query,
                url=cleaned_url,
                title=hit.title,
                score=score,
            )
            if len(hits) >= max_sources:
                sorted_hits = sorted(hits, key=lambda item: item.score, reverse=True)
                _emit_progress(
                    progress_callback,
                    stage="来源发现完成",
                    status="done",
                    detail=f"达到来源上限，累计保留 {len(sorted_hits)} 条权威候选来源。",
                    accepted_sources=len(sorted_hits),
                )
                return sorted_hits
        if accepted_for_query == 0:
            _emit_progress(
                progress_callback,
                stage="权威来源筛选",
                status="skipped",
                detail="该检索式未筛到符合权威域名规则的新来源。",
                category=query.category,
                query=query.query,
            )
        if sleep_seconds:
            time.sleep(sleep_seconds)
    sorted_hits = sorted(hits, key=lambda item: item.score, reverse=True)
    _emit_progress(
        progress_callback,
        stage="来源发现完成",
        status="done",
        detail=f"全部检索式执行完毕，累计保留 {len(sorted_hits)} 条权威候选来源。",
        accepted_sources=len(sorted_hits),
    )
    return sorted_hits


def search_query(query: SearchQuery, max_results: int = 8) -> list[SearchHit]:
    hits = _search_bing(query, max_results=max_results)
    if len(hits) < max_results // 2:
        hits.extend(_search_duckduckgo(query, max_results=max_results - len(hits)))
    deduped: list[SearchHit] = []
    seen: set[str] = set()
    for hit in hits:
        normalized = normalize_result_url(hit.url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(hit)
    return deduped[:max_results]


def build_evidence_from_discovered_sources(
    city: str,
    province: str,
    report_year: int,
    hits: list[SearchHit],
    max_excerpt_chars: int = 5000,
    fetch_timeout_seconds: int = 12,
    max_workers: int = 8,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    evidence = build_evidence_template(city=city, province=province, report_year=report_year)
    _emit_progress(
        progress_callback,
        stage="网页正文抓取",
        status="running",
        detail=f"开始并发抓取 {len(hits)} 条权威候选来源正文。",
        source_count=len(hits),
        max_workers=max_workers,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        evidence["sources"] = list(
            executor.map(
                lambda item: _source_record_from_hit(
                    item[0],
                    item[1],
                    max_excerpt_chars=max_excerpt_chars,
                    fetch_timeout_seconds=fetch_timeout_seconds,
                    progress_callback=progress_callback,
                ),
                enumerate(hits, start=1),
            )
        )
    success_count = sum(1 for source in evidence["sources"] if source.get("excerpt"))
    _emit_progress(
        progress_callback,
        stage="网页正文抓取",
        status="done",
        detail=f"正文抓取完成：{success_count}/{len(hits)} 条来源获得摘录。",
        source_count=len(hits),
        success_count=success_count,
    )
    return evidence


def _source_record_from_hit(
    index: int,
    hit: SearchHit,
    max_excerpt_chars: int,
    fetch_timeout_seconds: int,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    try:
        title, content_type, text = fetch_url_text(hit.url, timeout_seconds=fetch_timeout_seconds)
        excerpt = text[:max_excerpt_chars].strip()
        notes = f"自动检索：{hit.category}；检索式：{hit.query}；搜索排名：{hit.source_rank}；权威评分：{hit.score}"
        _emit_progress(
            progress_callback,
            stage="网页正文抓取",
            status="done",
            detail=f"S{index:03d} 抓取成功：{title or hit.title}",
            source_id=f"S{index:03d}",
            url=hit.url,
            title=title or hit.title,
            excerpt_chars=len(excerpt),
        )
    except Exception as exc:  # noqa: BLE001 - preserve source candidate and failure reason.
        title = hit.title or hit.url
        content_type = ""
        excerpt = hit.snippet
        notes = f"自动检索但抓取失败：{exc}；检索式：{hit.query}；权威评分：{hit.score}"
        _emit_progress(
            progress_callback,
            stage="网页正文抓取",
            status="warning",
            detail=f"S{index:03d} 抓取失败，保留搜索摘要：{title}",
            source_id=f"S{index:03d}",
            url=hit.url,
            title=title,
            error=str(exc),
        )

    tags = CATEGORY_TAGS.get(hit.category, ["official_media"])
    return {
        "id": f"S{index:03d}",
        "title": title or hit.title,
        "url": hit.url,
        "publisher": urlparse(hit.url).netloc,
        "published_date": "",
        "source_type": _source_type_from_url(hit.url, content_type),
        "credibility": "official_candidate",
        "tags": tags,
        "excerpt": excerpt,
        "notes": notes,
    }


def _emit_progress(
    progress_callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    status: str,
    detail: str,
    **metadata: Any,
) -> None:
    if not progress_callback:
        return
    progress_callback(
        {
            "stage": stage,
            "status": status,
            "detail": detail,
            "metadata": metadata,
        }
    )


def write_discovery_outputs(
    output_dir: str | Path,
    city: str,
    province: str,
    report_year: int,
    hits: list[SearchHit],
) -> Path:
    path = Path(output_dir) / "01_discovered_sources.json"
    payload = {
        "city": city,
        "province": province,
        "report_year": report_year,
        "sources": [hit.__dict__ for hit in hits],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def score_authority_url(url: str, title: str, snippet: str, city: str, query: SearchQuery) -> int:
    host = urlparse(url).netloc.lower()
    text = f"{title} {snippet} {url}".lower()
    score = 0
    if any(noise in host for noise in NOISE_DOMAINS):
        return 0
    is_authority_domain = any(domain in host for domain in OFFICIAL_DOMAIN_KEYWORDS)
    if not is_authority_domain:
        return 0
    if is_authority_domain:
        score += 5
    if "gov.cn" in host:
        score += 5
    if "mp.weixin.qq.com" in host:
        score += 3
    if "cninfo.com.cn" in host or "sse.com.cn" in host or "szse.cn" in host:
        score += 4
    if city and city.replace("市", "") in text:
        score += 2
    if "政府" in title or "官方" in title or "发布" in title:
        score += 1
    if any(keyword in text for keyword in ["统计公报", "政府工作报告", "产业规划", "行动方案", "纳税百强", "百强企业"]):
        score += 2
    if query.category in {"上市公司与资本市场", "企业榜单"} and any(
        keyword in text for keyword in ["年报", "公告", "名单", "榜单", "市值"]
    ):
        score += 1
    return score


def normalize_result_url(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in ("u", "url", "uddg"):
            if params.get(key):
                url = params[key][0]
                break
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if "uddg" in params:
        url = params["uddg"][0]
    if "url" in params and parsed.netloc.endswith("bing.com"):
        url = params["url"][0]
    url = unquote(url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    host = parsed.netloc.lower()
    if any(noise in host for noise in NOISE_DOMAINS):
        return ""
    return url.split("#", 1)[0]


def _search_bing(query: SearchQuery, max_results: int) -> list[SearchHit]:
    url = "https://www.bing.com/search?q=" + quote_plus(query.query) + f"&count={max_results}"
    return _search_html(url, query, max_results=max_results)


def _search_duckduckgo(query: SearchQuery, max_results: int) -> list[SearchHit]:
    url = "https://duckduckgo.com/html/?q=" + quote_plus(query.query)
    return _search_html(url, query, max_results=max_results)


def _search_html(url: str, query: SearchQuery, max_results: int) -> list[SearchHit]:
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 city-industry-research/0.1",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
            },
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        return []

    parser = _SearchResultParser()
    parser.feed(html)
    hits: list[SearchHit] = []
    for href, title in parser.links:
        normalized = normalize_result_url(href)
        if not normalized or not title:
            continue
        if _looks_like_search_navigation(normalized, title):
            continue
        hits.append(SearchHit(url=normalized, title=title, query=query.query, category=query.category))
        if len(hits) >= max_results:
            break
    return hits


def _looks_like_search_navigation(url: str, title: str) -> bool:
    host = urlparse(url).netloc.lower()
    lowered = title.lower()
    if any(noise in host for noise in NOISE_DOMAINS):
        return True
    if lowered in {"images", "videos", "maps", "news", "网页", "图片", "视频", "地图"}:
        return True
    return False


def _source_type_from_url(url: str, content_type: str) -> str:
    host = urlparse(url).netloc.lower()
    if "gov.cn" in host:
        return "government_website"
    if "mp.weixin.qq.com" in host:
        return "official_wechat"
    if any(domain in host for domain in ("xinhuanet.com", "people.com.cn", "cctv.com", "ce.cn")):
        return "official_media"
    if any(domain in host for domain in ("cninfo.com.cn", "sse.com.cn", "szse.cn", "bse.cn")):
        return "exchange_filing"
    if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
        return "pdf"
    return "official_candidate"


def _clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
