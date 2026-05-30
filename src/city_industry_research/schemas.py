"""Data structures for source-backed city industry research."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass
class SourceRecord:
    id: str
    title: str
    url: str
    publisher: str = ""
    published_date: str = ""
    source_type: str = ""
    credibility: str = "official"
    excerpt: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> "SourceRecord":
        source_id = str(data.get("id") or f"S{index:03d}")
        tags = data.get("tags") or []
        if isinstance(tags, str):
            tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
        return cls(
            id=source_id,
            title=str(data.get("title") or ""),
            url=str(data.get("url") or ""),
            publisher=str(data.get("publisher") or ""),
            published_date=str(data.get("published_date") or ""),
            source_type=str(data.get("source_type") or ""),
            credibility=str(data.get("credibility") or "official"),
            excerpt=str(data.get("excerpt") or ""),
            tags=list(tags),
            notes=str(data.get("notes") or ""),
        )

    def citation(self) -> str:
        pieces = [self.id, self.title]
        if self.publisher:
            pieces.append(self.publisher)
        if self.published_date:
            pieces.append(self.published_date)
        if self.url:
            pieces.append(self.url)
        return " | ".join(piece for piece in pieces if piece)

    def to_prompt_block(self, max_excerpt_chars: int = 1800) -> str:
        excerpt = self.excerpt.strip()
        if len(excerpt) > max_excerpt_chars:
            excerpt = excerpt[:max_excerpt_chars].rstrip() + "..."
        tags = ", ".join(self.tags)
        return (
            f"[{self.id}]\n"
            f"标题：{self.title}\n"
            f"发布方：{self.publisher}\n"
            f"日期：{self.published_date}\n"
            f"类型：{self.source_type}\n"
            f"标签：{tags}\n"
            f"链接：{self.url}\n"
            f"摘录：{excerpt}\n"
        )


@dataclass
class EvidenceCorpus:
    city: str = ""
    province: str = ""
    report_year: int | None = None
    pillar_industries: list[dict[str, Any]] = field(default_factory=list)
    emerging_industries: list[dict[str, Any]] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    enterprise_records: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "EvidenceCorpus":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        inventory = data.get("industry_inventory") or {}
        sources = [
            SourceRecord.from_dict(item, index)
            for index, item in enumerate(data.get("sources") or [], start=1)
        ]
        return cls(
            city=str(data.get("city") or ""),
            province=str(data.get("province") or ""),
            report_year=data.get("report_year"),
            pillar_industries=list(inventory.get("pillar_industries") or []),
            emerging_industries=list(inventory.get("emerging_industries") or []),
            sources=sources,
            enterprise_records=list(data.get("enterprise_records") or []),
            assumptions=list(data.get("assumptions") or []),
        )

    def source_tags(self) -> set[str]:
        return {tag for source in self.sources for tag in source.tags}

    def prompt_sources(self) -> str:
        if not self.sources:
            return "暂无证据源。报告只能输出结构模板和来源缺口，不能编造数据。"
        return "\n\n".join(source.to_prompt_block() for source in self.sources)

    def source_appendix_markdown(self) -> str:
        if not self.sources:
            return "暂无来源。"
        rows = ["| 编号 | 标题 | 发布方 | 日期 | 链接 | 标签 |", "|---|---|---|---|---|---|"]
        for source in self.sources:
            tags = ", ".join(source.tags)
            rows.append(
                f"| {source.id} | {source.title} | {source.publisher} | "
                f"{source.published_date} | {source.url} | {tags} |"
            )
        return "\n".join(rows)
