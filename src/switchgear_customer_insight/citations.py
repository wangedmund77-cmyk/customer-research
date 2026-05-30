"""Utilities for linking report citations to source registry entries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re


CITATION_PATTERN = re.compile(r"【([A-Za-z]{1,4}\d+)】")


@dataclass(frozen=True)
class SourceReference:
    id: str
    title: str
    publisher: str
    date: str
    url: str
    purpose: str

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


def load_source_references(path: str | Path | None) -> dict[str, SourceReference]:
    if not path:
        return {}
    source_path = Path(path)
    if not source_path.exists():
        return {}
    return parse_source_registry(source_path.read_text(encoding="utf-8"))


def parse_source_registry(markdown: str) -> dict[str, SourceReference]:
    references: dict[str, SourceReference] = {}
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.split("|")[1:-1]]
        if len(cells) < 5 or cells[0] in {"编号", "---"}:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        source_id = cells[0]
        if not re.fullmatch(r"[A-Za-z]{1,4}\d+", source_id):
            continue
        references[source_id] = SourceReference(
            id=source_id,
            title=cells[1] if len(cells) > 1 else "",
            publisher=cells[2] if len(cells) > 2 else "",
            date=cells[3] if len(cells) > 3 else "",
            url=cells[4] if len(cells) > 4 else "",
            purpose=cells[5] if len(cells) > 5 else "",
        )
    return references


def link_markdown_citations(markdown: str, references: dict[str, SourceReference]) -> str:
    def replace(match: re.Match[str]) -> str:
        source_id = match.group(1)
        reference = references.get(source_id)
        if not reference or not is_external_url(reference.url):
            return match.group(0)
        return f"[{match.group(0)}]({reference.url})"

    return CITATION_PATTERN.sub(replace, markdown)


def cited_external_sources(markdown: str, references: dict[str, SourceReference]) -> dict[str, SourceReference]:
    cited_ids = dict.fromkeys(CITATION_PATTERN.findall(markdown))
    return {
        source_id: references[source_id]
        for source_id in cited_ids
        if source_id in references and is_external_url(references[source_id].url)
    }


def is_external_url(value: str) -> bool:
    return value.startswith("https://") or value.startswith("http://")
