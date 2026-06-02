"""Convert generated Markdown reports to styled Word documents."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from .citations import SourceReference, cited_external_sources, parse_source_registry


PAGE_WIDTH_DXA = 11906
PAGE_HEIGHT_DXA = 16838
PAGE_MARGIN_DXA = 1440
USABLE_WIDTH_DXA = PAGE_WIDTH_DXA - (PAGE_MARGIN_DXA * 2)
TABLE_WIDTH_DXA = USABLE_WIDTH_DXA - 120

Block = tuple[str, object]


def write_docx_from_markdown(markdown: str, output_path: str | Path, source_registry_markdown: str = "") -> Path:
    """Write a polished DOCX file from the subset of Markdown used by reports."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = _markdown_blocks(markdown)
    metadata = _report_metadata(blocks)
    source_references = parse_source_registry(source_registry_markdown) if source_registry_markdown else {}
    cited_sources = cited_external_sources(markdown, source_references)
    source_relationships = {
        source_id: f"rIdSource{index}"
        for index, source_id in enumerate(cited_sources, start=1)
    }
    document_xml = _document_xml(blocks, metadata, source_relationships)
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_relationships_xml())
        archive.writestr("docProps/core.xml", _core_properties_xml(metadata["title"]))
        archive.writestr("docProps/app.xml", _app_properties_xml())
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/_rels/document.xml.rels", _document_relationships_xml(source_relationships, cited_sources))
        archive.writestr("word/header1.xml", _header_xml(metadata["short_title"]))
        archive.writestr("word/footer1.xml", _footer_xml())
        archive.writestr("word/styles.xml", _styles_xml())
        archive.writestr("word/numbering.xml", _numbering_xml())
        archive.writestr("word/settings.xml", _settings_xml())
    return path


def _markdown_blocks(markdown: str) -> list[Block]:
    blocks: list[Block] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while index < len(lines):
                table_line = lines[index].strip()
                if not (table_line.startswith("|") and table_line.endswith("|")):
                    break
                table_lines.append(table_line)
                index += 1
            rows = _parse_markdown_table(table_lines)
            if rows:
                blocks.append(("table", rows))
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            blocks.append(("heading", (len(heading.group(1)), heading.group(2).strip())))
            index += 1
            continue

        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        if bullet:
            blocks.append(("bullet", bullet.group(1).strip()))
            index += 1
            continue

        numbered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if numbered:
            blocks.append(("numbered", numbered.group(1).strip()))
            index += 1
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if (
                not next_line
                or next_line.startswith("|")
                or re.match(r"^(#{1,4})\s+(.+)$", next_line)
                or re.match(r"^[-*]\s+(.+)$", next_line)
                or re.match(r"^\d+[.)]\s+(.+)$", next_line)
            ):
                break
            paragraph.append(next_line)
            index += 1
        blocks.append(("paragraph", " ".join(paragraph)))
    return blocks


def _parse_markdown_table(lines: Iterable[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if not cells:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return []
    width = max(len(row) for row in rows)
    return [row + [""] * (width - len(row)) for row in rows]


def _report_metadata(blocks: list[Block]) -> dict[str, str | list[tuple[str, str]]]:
    title = "盘厂企业深度洞察报告"
    front_items: list[tuple[str, str]] = []
    for kind, payload in blocks:
        if kind == "heading":
            level, text = payload  # type: ignore[misc]
            if level == 1:
                title = str(text)
            if level >= 2:
                break
        elif kind == "bullet":
            key, value = _split_key_value(str(payload))
            front_items.append((key, value))
    customer = _front_value(front_items, "建议核验主体") or _front_value(front_items, "用户输入名称") or _customer_from_title(title)
    generated = _front_value(front_items, "生成日期") or datetime.now().strftime("%Y-%m-%d")
    version = _front_value(front_items, "报告版本") or "公开资料版"
    service = _front_value(front_items, "服务对象") or "施耐德电气盘厂客户部"
    short_title = f"{customer}洞察报告" if customer else "企业洞察报告"
    return {
        "title": title,
        "customer": customer,
        "generated": generated,
        "version": version,
        "service": service,
        "short_title": short_title,
        "front_items": front_items,
    }


def _split_key_value(text: str) -> tuple[str, str]:
    match = re.match(r"^([^：:]{2,24})[：:]\s*(.+)$", text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return "说明", text


def _front_value(items: list[tuple[str, str]], key: str) -> str:
    for item_key, value in items:
        if item_key == key:
            return value
    return ""


def _customer_from_title(title: str) -> str:
    return re.sub(r"(深度)?(客户|企业)?洞察报告$", "", title).strip() or title


def _document_xml(
    blocks: list[Block],
    metadata: dict[str, str | list[tuple[str, str]]],
    source_relationships: dict[str, str],
) -> str:
    body = []
    body.extend(_cover_page(metadata, source_relationships))
    body.extend(_toc_page(blocks, source_relationships))
    body.extend(_content_body(blocks, source_relationships))
    body.append(_section_properties())
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
        'xmlns:o="urn:schemas-microsoft-com:office:office" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
        'xmlns:v="urn:schemas-microsoft-com:vml" '
        'xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:w10="urn:schemas-microsoft-com:office:word" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
        'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
        'xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk" '
        'xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml" '
        'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
        'mc:Ignorable="w14 wp14">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )


def _cover_page(metadata: dict[str, str | list[tuple[str, str]]], source_relationships: dict[str, str]) -> list[str]:
    front_items = metadata["front_items"]
    assert isinstance(front_items, list)
    meta_rows = [
        ["企业名称", str(metadata["customer"])],
        ["服务对象", str(metadata["service"])],
        ["报告版本", str(metadata["version"])],
        ["生成日期", str(metadata["generated"])],
    ]
    extra_items = [[key, value] for key, value in front_items if key in {"关键限制", "用户输入名称"}]
    meta_rows.extend(extra_items[:2])
    return [
        _paragraph("Enterprise Insight Research", style="CoverKicker", source_relationships=source_relationships),
        _paragraph(str(metadata["customer"]), style="CoverTitle", source_relationships=source_relationships),
        _paragraph("深度企业洞察报告", style="CoverSubtitle", source_relationships=source_relationships),
        _paragraph("Schneider Electric · 盘厂企业研究", style="CoverByline", source_relationships=source_relationships),
        _spacer_paragraph(420),
        _key_value_table(meta_rows, source_relationships),
        _spacer_paragraph(280),
        _callout("使用提示", "本文档由企业洞察研究工作台根据既有研究报告生成，公开资料结论应结合施耐德内部采购、授权、项目和企业访谈数据复核。", source_relationships),
        _page_break(),
    ]


def _toc_page(blocks: list[Block], source_relationships: dict[str, str]) -> list[str]:
    toc_entries: list[tuple[int, str]] = []
    for kind, payload in blocks:
        if kind != "heading":
            continue
        level, text = payload  # type: ignore[misc]
        if level == 1:
            continue
        toc_entries.append((min(level - 1, 3), str(text)))
    body = [
        _paragraph("目录", style="TocTitle", source_relationships=source_relationships),
        _paragraph("以下章节已写入 Word 标题大纲，可在导航窗格中按章节浏览。", style="TocNote", source_relationships=source_relationships),
    ]
    for level, text in toc_entries:
        body.append(_paragraph(text, style=f"Toc{level}", source_relationships=source_relationships))
    body.append(_page_break())
    return body


def _content_body(blocks: list[Block], source_relationships: dict[str, str]) -> list[str]:
    body = []
    skipped_front = False
    chapter_count = 0
    for kind, payload in blocks:
        if kind == "heading":
            level, text = payload  # type: ignore[misc]
            if level == 1:
                skipped_front = True
                continue
            skipped_front = True
            style = f"Heading{min(level - 1, 3)}"
            page_break_before = level == 2 and chapter_count > 0
            if level == 2:
                chapter_count += 1
            body.append(_paragraph(str(text), style=style, page_break_before=page_break_before, source_relationships=source_relationships))
            continue
        if not skipped_front:
            continue
        if kind == "bullet":
            body.append(_paragraph(str(payload), list_kind="bullet", source_relationships=source_relationships))
        elif kind == "numbered":
            body.append(_paragraph(str(payload), list_kind="numbered", source_relationships=source_relationships))
        elif kind == "table":
            body.append(_table(payload, source_relationships=source_relationships))  # type: ignore[arg-type]
        else:
            body.append(_paragraph(str(payload), source_relationships=source_relationships))
    return body


def _paragraph(
    text: str,
    style: str = "",
    list_kind: str = "",
    page_break_before: bool = False,
    align: str = "",
    source_relationships: dict[str, str] | None = None,
) -> str:
    ppr_parts = []
    if style:
        ppr_parts.append(f'<w:pStyle w:val="{style}"/>')
    if page_break_before:
        ppr_parts.append("<w:pageBreakBefore/>")
    if list_kind:
        num_id = "1" if list_kind == "bullet" else "2"
        ppr_parts.append(f'<w:pStyle w:val="{list_kind.title()}List"/>')
        ppr_parts.append(f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>')
    if align:
        ppr_parts.append(f'<w:jc w:val="{align}"/>')
    ppr = f"<w:pPr>{''.join(ppr_parts)}</w:pPr>" if ppr_parts else ""
    return f"<w:p>{ppr}{''.join(_inline_runs(text, source_relationships or {}))}</w:p>"


def _spacer_paragraph(height: int) -> str:
    return f'<w:p><w:pPr><w:spacing w:before="{height}" w:after="0"/></w:pPr></w:p>'


def _page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _inline_runs(text: str, source_relationships: dict[str, str] | None = None) -> list[str]:
    citation_relationships = source_relationships or {}
    tokens = re.split(r"(\*\*.+?\*\*|`.+?`|【[A-Za-z]{1,4}\d+】)", text)
    runs = []
    for token in tokens:
        if not token:
            continue
        citation = re.fullmatch(r"【([A-Za-z]{1,4}\d+)】", token)
        if citation:
            relationship_id = citation_relationships.get(citation.group(1))
            runs.append(_hyperlink_run(token, relationship_id) if relationship_id else _run(token))
            continue
        bold = token.startswith("**") and token.endswith("**") and len(token) >= 4
        code = token.startswith("`") and token.endswith("`") and len(token) >= 2
        clean = token[2:-2] if bold else token[1:-1] if code else token
        lines = clean.split("\n")
        for line_index, line in enumerate(lines):
            if line_index:
                runs.append("<w:r><w:br/></w:r>")
            if line:
                runs.append(_run(line, bold=bold, code=code))
    return runs


def _hyperlink_run(text: str, relationship_id: str) -> str:
    escaped = escape(text)
    return (
        f'<w:hyperlink r:id="{relationship_id}" w:history="1">'
        '<w:r><w:rPr>'
        '<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Microsoft YaHei" w:cs="Arial"/>'
        '<w:color w:val="0563C1"/><w:u w:val="single"/>'
        '</w:rPr>'
        f"<w:t>{escaped}</w:t>"
        '</w:r></w:hyperlink>'
    )


def _run(text: str, bold: bool = False, code: bool = False, color: str = "") -> str:
    properties = [
        '<w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Microsoft YaHei" w:cs="Arial"/>',
    ]
    if bold:
        properties.append("<w:b/>")
        properties.append("<w:bCs/>")
    if code:
        properties[0] = '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:eastAsia="Microsoft YaHei" w:cs="Consolas"/>'
        properties.append('<w:shd w:fill="EEF2F4"/>')
    if color:
        properties.append(f'<w:color w:val="{color}"/>')
    escaped = escape(text)
    space = ' xml:space="preserve"' if text != text.strip() or "  " in text else ""
    return f"<w:r><w:rPr>{''.join(properties)}</w:rPr><w:t{space}>{escaped}</w:t></w:r>"


def _key_value_table(rows: list[list[str]], source_relationships: dict[str, str]) -> str:
    return _table(rows, widths=[1800, TABLE_WIDTH_DXA - 1800], compact=True, header=False, source_relationships=source_relationships)


def _callout(label: str, text: str, source_relationships: dict[str, str]) -> str:
    return (
        '<w:tbl><w:tblPr>'
        f'<w:tblW w:w="{TABLE_WIDTH_DXA}" w:type="dxa"/>'
        '<w:tblInd w:w="0" w:type="dxa"/><w:tblLayout w:type="fixed"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="B9D7CB"/>'
        '<w:left w:val="single" w:sz="12" w:color="0F6B4F"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="B9D7CB"/>'
        '<w:right w:val="single" w:sz="4" w:color="B9D7CB"/></w:tblBorders>'
        '<w:tblCellMar><w:top w:w="160" w:type="dxa"/><w:left w:w="180" w:type="dxa"/>'
        '<w:bottom w:w="160" w:type="dxa"/><w:right w:w="180" w:type="dxa"/></w:tblCellMar>'
        '</w:tblPr>'
        f'<w:tblGrid><w:gridCol w:w="{TABLE_WIDTH_DXA}"/></w:tblGrid>'
        '<w:tr><w:tc><w:tcPr>'
        f'<w:tcW w:w="{TABLE_WIDTH_DXA}" w:type="dxa"/><w:shd w:fill="F1F8F5"/>'
        '</w:tcPr>'
        f'{_paragraph(label, style="CalloutLabel", source_relationships=source_relationships)}{_paragraph(text, style="CalloutText", source_relationships=source_relationships)}'
        '</w:tc></w:tr></w:tbl>'
    )


def _table(
    rows: list[list[str]],
    widths: list[int] | None = None,
    compact: bool = False,
    header: bool = True,
    source_relationships: dict[str, str] | None = None,
) -> str:
    if not rows:
        return ""
    columns = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (columns - len(row)) for row in rows]
    column_widths = widths if widths and len(widths) == columns else _table_widths(normalized_rows)
    grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in column_widths)
    rendered_rows = []
    for row_index, row in enumerate(normalized_rows):
        cells = []
        for column_index, cell in enumerate(row):
            is_header = header and row_index == 0
            fill = "E6F2ED" if is_header else "FFFFFF"
            valign = "center" if is_header or _is_short_value(cell) else "top"
            cell_pr = (
                f'<w:tcPr><w:tcW w:w="{column_widths[column_index]}" w:type="dxa"/>'
                f'<w:vAlign w:val="{valign}"/>'
                '<w:tcMar><w:top w:w="130" w:type="dxa"/><w:left w:w="150" w:type="dxa"/>'
                '<w:bottom w:w="130" w:type="dxa"/><w:right w:w="150" w:type="dxa"/></w:tcMar>'
                f'<w:shd w:fill="{fill}"/></w:tcPr>'
            )
            text = cell.replace("<br>", "\n").replace("<br/>", "\n")
            style = "TableHeader" if is_header else "TableCellCompact" if compact else "TableCell"
            cells.append(f"<w:tc>{cell_pr}{_paragraph(text, style=style, source_relationships=source_relationships)}</w:tc>")
        rendered_rows.append(f"<w:tr>{''.join(cells)}</w:tr>")
    return (
        "<w:tbl><w:tblPr>"
        f'<w:tblW w:w="{sum(column_widths)}" w:type="dxa"/>'
        '<w:tblInd w:w="0" w:type="dxa"/>'
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblLook w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        '<w:tblBorders><w:top w:val="single" w:sz="4" w:color="CAD4DB"/>'
        '<w:left w:val="single" w:sz="4" w:color="CAD4DB"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="CAD4DB"/>'
        '<w:right w:val="single" w:sz="4" w:color="CAD4DB"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="CAD4DB"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="CAD4DB"/></w:tblBorders>'
        '<w:tblCellMar><w:top w:w="130" w:type="dxa"/><w:left w:w="150" w:type="dxa"/>'
        '<w:bottom w:w="130" w:type="dxa"/><w:right w:w="150" w:type="dxa"/></w:tblCellMar>'
        "</w:tblPr>"
        f"<w:tblGrid>{grid}</w:tblGrid>{''.join(rendered_rows)}</w:tbl>"
    )


def _table_widths(rows: list[list[str]]) -> list[int]:
    columns = len(rows[0])
    scores = []
    for column_index in range(columns):
        values = [row[column_index] for row in rows]
        max_len = max((_visual_length(value) for value in values), default=8)
        avg_len = sum(_visual_length(value) for value in values) / max(len(values), 1)
        scores.append(max(8, min(34, (max_len * 0.55) + (avg_len * 0.45))))
    total = sum(scores) or 1
    widths = [max(1100, int(TABLE_WIDTH_DXA * score / total)) for score in scores]
    delta = TABLE_WIDTH_DXA - sum(widths)
    widths[-1] += delta
    if widths[-1] < 900:
        shortage = 900 - widths[-1]
        widths[-1] = 900
        largest = max(range(columns - 1), key=lambda index: widths[index]) if columns > 1 else 0
        widths[largest] = max(1100, widths[largest] - shortage)
    return widths


def _visual_length(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def _is_short_value(text: str) -> bool:
    return _visual_length(text) <= 12 and "\n" not in text


def _section_properties() -> str:
    return (
        "<w:sectPr>"
        '<w:headerReference w:type="default" r:id="rIdHeader1"/>'
        '<w:footerReference w:type="default" r:id="rIdFooter1"/>'
        f'<w:pgSz w:w="{PAGE_WIDTH_DXA}" w:h="{PAGE_HEIGHT_DXA}"/>'
        f'<w:pgMar w:top="{PAGE_MARGIN_DXA}" w:right="{PAGE_MARGIN_DXA}" w:bottom="{PAGE_MARGIN_DXA}" '
        f'w:left="{PAGE_MARGIN_DXA}" w:header="708" w:footer="708" w:gutter="0"/>'
        '<w:cols w:space="708"/>'
        '<w:docGrid w:linePitch="312"/>'
        "</w:sectPr>"
    )


def _styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Microsoft YaHei" w:cs="Arial"/><w:color w:val="182129"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="140" w:line="360" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Microsoft YaHei" w:cs="Arial"/><w:color w:val="182129"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CoverKicker"><w:name w:val="Cover Kicker"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="720" w:after="180"/></w:pPr><w:rPr><w:b/><w:bCs/><w:caps/><w:color w:val="A96517"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CoverTitle"><w:name w:val="Cover Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display" w:eastAsia="Microsoft YaHei"/><w:b/><w:bCs/><w:color w:val="0F6B4F"/><w:sz w:val="42"/><w:szCs w:val="42"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CoverSubtitle"><w:name w:val="Cover Subtitle"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display" w:eastAsia="Microsoft YaHei"/><w:b/><w:bCs/><w:color w:val="1F5F8B"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CoverByline"><w:name w:val="Cover Byline"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:color w:val="65717B"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TocTitle"><w:name w:val="TOC Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="240"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="0F6B4F"/><w:sz w:val="34"/><w:szCs w:val="34"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TocNote"><w:name w:val="TOC Note"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="260"/></w:pPr><w:rPr><w:color w:val="65717B"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Toc1"><w:name w:val="TOC 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="90"/><w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9026"/></w:tabs></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="26333D"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Toc2"><w:name w:val="TOC 2"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="360"/><w:spacing w:after="70"/></w:pPr><w:rPr><w:color w:val="53616B"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Toc3"><w:name w:val="TOC 3"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720"/><w:spacing w:after="50"/></w:pPr><w:rPr><w:color w:val="65717B"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="420" w:after="200"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:ascii="Aptos Display" w:hAnsi="Aptos Display" w:eastAsia="Microsoft YaHei"/><w:b/><w:bCs/><w:color w:val="0F6B4F"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="260" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="1F5F8B"/><w:sz w:val="25"/><w:szCs w:val="25"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="180" w:after="90"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="A96517"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="BulletList"><w:name w:val="Bullet List"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="80" w:line="330" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="NumberedList"><w:name w:val="Numbered List"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="80" w:line="330" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TableHeader"><w:name w:val="Table Header"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="300" w:lineRule="auto"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="0F3F2F"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TableCell"><w:name w:val="Table Cell"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="300" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TableCellCompact"><w:name w:val="Table Cell Compact"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="280" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CalloutLabel"><w:name w:val="Callout Label"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="40"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="0F6B4F"/><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="CalloutText"><w:name w:val="Callout Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0" w:line="330" w:lineRule="auto"/></w:pPr><w:rPr><w:color w:val="26333D"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="HeaderText"><w:name w:val="Header Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="65717B"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="FooterText"><w:name w:val="Footer Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="0"/></w:pPr><w:rPr><w:color w:val="65717B"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>
</w:styles>"""


def _numbering_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="520" w:hanging="260"/></w:pPr><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hint="default"/></w:rPr></w:lvl></w:abstractNum>
  <w:abstractNum w:abstractNumId="2"><w:multiLevelType w:val="singleLevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="560" w:hanging="300"/></w:pPr></w:lvl></w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
  <w:num w:numId="2"><w:abstractNumId w:val="2"/></w:num>
</w:numbering>"""


def _header_xml(short_title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:p><w:pPr><w:pStyle w:val="HeaderText"/><w:jc w:val="right"/>'
        '<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="D5DCE1"/></w:pBdr>'
        '</w:pPr>'
        f'{_run("施耐德电气盘厂客户部 · " + short_title)}'
        '</w:p></w:hdr>'
    )


def _footer_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:p><w:pPr><w:pStyle w:val="FooterText"/><w:jc w:val="center"/></w:pPr>'
        f'{_run("第 ")}'
        '<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'
        f'{_run(" 页 / 共 ")}'
        '<w:fldSimple w:instr="NUMPAGES"><w:r><w:t>1</w:t></w:r></w:fldSimple>'
        f'{_run(" 页")}'
        '</w:p></w:ftr>'
    )


def _settings_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:updateFields w:val="true"/>
  <w:defaultTabStop w:val="720"/>
  <w:characterSpacingControl w:val="doNotCompress"/>
</w:settings>"""


def _content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
  <Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
</Types>"""


def _root_relationships_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""


def _document_relationships_xml(
    source_relationships: dict[str, str],
    cited_sources: dict[str, SourceReference],
) -> str:
    relationships = [
        '<Relationship Id="rIdHeader1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>',
        '<Relationship Id="rIdFooter1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>',
    ]
    for source_id, relationship_id in source_relationships.items():
        target = escape(cited_sources[source_id].url, {'"': "&quot;"})
        relationships.append(
            f'<Relationship Id="{relationship_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
            f'Target="{target}" TargetMode="External"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(relationships)}"
        "</Relationships>"
    )


def _core_properties_xml(title: str) -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{escape(title)}</dc:title>
  <dc:creator>Switchgear Enterprise Insight</dc:creator>
  <cp:lastModifiedBy>Switchgear Enterprise Insight</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>"""


def _app_properties_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Switchgear Enterprise Insight</Application>
</Properties>"""
