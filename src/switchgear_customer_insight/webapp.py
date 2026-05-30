"""Local web interface for switchgear customer insight projects."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import traceback
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .citations import link_markdown_citations, load_source_references
from .docx_writer import write_docx_from_markdown
from .framework import FRAMEWORK, InsightField, fields_by_module, module_names
from .report_writer import slugify_customer_name, write_customer_project


ROOT_DIR = Path.cwd()
STATIC_DIR = Path(__file__).with_name("static")
WEB_OUTPUT_DIR = ROOT_DIR / "outputs" / "switchgear_customer_web"
CHINT_REPORT_PATH = ROOT_DIR / "outputs" / "chint_electric_2026" / "浙江正泰电器股份有限公司_深度客户洞察报告.md"
CHINT_SOURCE_PATH = ROOT_DIR / "outputs" / "chint_electric_2026" / "source_registry.md"
ZHONGHUAN_REPORT_PATH = ROOT_DIR / "outputs" / "zhonghuan_electric_2026" / "江苏中环电气集团有限公司_深度客户洞察报告.md"
ZHONGHUAN_SOURCE_PATH = ROOT_DIR / "outputs" / "zhonghuan_electric_2026" / "source_registry.md"
TIANYU_REPORT_PATH = ROOT_DIR / "outputs" / "tianyu_electric_2026" / "福州天宇电气股份有限公司_深度客户洞察报告.md"
TIANYU_SOURCE_PATH = ROOT_DIR / "outputs" / "tianyu_electric_2026" / "source_registry.md"


@dataclass
class CustomerProject:
    id: str
    customer: str
    year: int
    status: str = "done"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    output_dir: str = ""
    source_plan_path: str = ""
    field_register_path: str = ""
    prompt_path: str = ""
    template_path: str = ""
    report_path: str = ""
    word_report_path: str = ""
    source_registry_path: str = ""
    report_preview: str = ""
    logs: list[str] = field(default_factory=list)
    error: str = ""

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["has_report"] = bool(self.report_path and Path(self.report_path).exists())
        data["has_word_report"] = bool(self.word_report_path)
        data["has_prompt"] = bool(self.prompt_path and Path(self.prompt_path).exists())
        data["has_field_register"] = bool(self.field_register_path and Path(self.field_register_path).exists())
        source_references = load_source_references(self.source_registry_path)
        data["source_references"] = {source_id: reference.public_dict() for source_id, reference in source_references.items()}
        data["insight_dashboard"] = _build_insight_dashboard(self, source_count=len(source_references))
        data["framework_matrix"] = data["insight_dashboard"]["framework_matrix"]
        return data


PROJECTS: dict[str, CustomerProject] = {}


def run_web_app(host: str = "127.0.0.1", port: int = 8790) -> None:
    WEB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), CustomerInsightRequestHandler)
    print(f"盘厂大客户洞察工作台已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务。")
    finally:
        server.server_close()


class CustomerInsightRequestHandler(SimpleHTTPRequestHandler):
    server_version = "SwitchgearCustomerInsight/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature.
        print(f"[customer-web] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook.
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            filename = path.removeprefix("/static/")
            self._serve_static(filename, _content_type(filename))
            return
        if path == "/api/status":
            self._json(
                {
                    "ok": True,
                    "output_dir": str(WEB_OUTPUT_DIR),
                    "modules": module_names(),
                    "framework": _framework_catalog(),
                    "field_count": len(FRAMEWORK),
                    "has_chint_report": CHINT_REPORT_PATH.exists(),
                    "has_zhonghuan_report": ZHONGHUAN_REPORT_PATH.exists(),
                    "has_tianyu_report": TIANYU_REPORT_PATH.exists(),
                }
            )
            return
        if path.startswith("/api/projects/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                self._handle_project(parts[2])
                return
            if len(parts) == 4:
                self._handle_project_file(parts[2], parts[3], parsed.query)
                return
        self._json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook.
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/projects":
            self._handle_create_project()
            return
        self._json({"error": "not_found"}, status=404)

    def _serve_static(self, filename: str, content_type: str) -> None:
        path = (STATIC_DIR / filename).resolve()
        if STATIC_DIR.resolve() not in path.parents and path != STATIC_DIR.resolve():
            self._json({"error": "invalid_static_path"}, status=400)
            return
        if not path.exists() or not path.is_file():
            self._json({"error": "static_file_not_found"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, payload: str, filename: str = "", status: int = 200) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/markdown; charset=utf-8")
        if filename:
            self.send_header("Content-Disposition", _attachment_header(filename))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _binary(self, payload: bytes, content_type: str, filename: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", _attachment_header(filename))
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _handle_create_project(self) -> None:
        data = self._read_json()
        customer = str(data.get("customer") or "").strip()
        if not customer:
            self._json({"error": "客户名称不能为空。"}, status=400)
            return
        year = int(data.get("year") or datetime.now().year)
        try:
            project = create_customer_project(customer=customer, year=year, internal_notes=str(data.get("internal_notes") or ""))
        except Exception as exc:  # noqa: BLE001 - expose local web error.
            project_id = f"{slugify_customer_name(customer)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            project = CustomerProject(id=project_id, customer=customer, year=year, status="error", error=f"{exc}\n{traceback.format_exc()}")
        PROJECTS[project.id] = project
        self._json({"project": project.public_dict()})

    def _handle_project(self, project_id: str) -> None:
        project = PROJECTS.get(project_id)
        if not project:
            self._json({"error": "project_not_found"}, status=404)
            return
        self._json({"project": project.public_dict()})

    def _handle_project_file(self, project_id: str, kind: str, query: str) -> None:
        project = PROJECTS.get(project_id)
        if not project:
            self._json({"error": "project_not_found"}, status=404)
            return
        if kind == "report-docx":
            path = _ensure_report_docx(project)
            if not path or not path.exists():
                self._json({"error": "file_not_found"}, status=404)
                return
            filename = f"{slugify_customer_name(project.customer)}_深度客户洞察报告.docx"
            self._binary(
                path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                filename=filename,
            )
            return
        path = _file_for_kind(project, kind)
        if not path or not path.exists():
            self._json({"error": "file_not_found"}, status=404)
            return
        if parse_qs(query).get("download") == ["1"]:
            text = path.read_text(encoding="utf-8")
            if kind == "report":
                text = link_markdown_citations(text, load_source_references(project.source_registry_path))
            self._text(text, filename=path.name)
            return
        self._text(path.read_text(encoding="utf-8"))


def create_customer_project(customer: str, year: int, internal_notes: str = "") -> CustomerProject:
    project_id = f"{slugify_customer_name(customer)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    output_dir = WEB_OUTPUT_DIR / project_id
    files = write_customer_project(customer, output_dir, year)

    project = CustomerProject(
        id=project_id,
        customer=customer,
        year=year,
        output_dir=str(output_dir),
        source_plan_path=str(files[0]),
        field_register_path=str(files[1]),
        prompt_path=str(files[2]),
        template_path=str(files[3]),
    )
    project.logs.append("已生成客户洞察项目基础文件。")

    notes_path = output_dir / "internal_notes.md"
    if internal_notes.strip():
        notes_path.write_text(f"# 内部补充信息\n\n{internal_notes.strip()}\n", encoding="utf-8")
        project.logs.append("已保存内部补充信息。")

    report_path = output_dir / "report.md"
    matched_report = _matched_completed_report(customer)
    if matched_report:
        report_source, registry_source, label = matched_report
        shutil.copyfile(report_source, report_path)
        if registry_source.exists():
            source_registry_path = output_dir / "source_registry.md"
            shutil.copyfile(registry_source, source_registry_path)
            project.source_registry_path = str(source_registry_path)
        project.logs.append(f"已载入{label}首版深度洞察报告。")
    else:
        shutil.copyfile(files[3], report_path)
        project.logs.append("已生成逐字段报告模板，等待补充公开研究或内部数据。")

    project.report_path = str(report_path)
    project.word_report_path = str(report_path.with_suffix(".docx"))
    project.report_preview = report_path.read_text(encoding="utf-8")[:8000]
    return project


def _is_chint_customer(customer: str) -> bool:
    normalized = customer.replace("（", "(").replace("）", ")")
    lowered = normalized.lower()
    return ("正泰" in normalized and "电器" in normalized) or "chint" in lowered


def _is_zhonghuan_customer(customer: str) -> bool:
    normalized = customer.replace("（", "(").replace("）", ")")
    return "中环" in normalized and "电气" in normalized


def _is_tianyu_customer(customer: str) -> bool:
    normalized = customer.replace("（", "(").replace("）", ")")
    lowered = normalized.lower()
    return ("天宇" in normalized and "电气" in normalized) or "tianyu electric" in lowered


def _matched_completed_report(customer: str) -> tuple[Path, Path, str] | None:
    if _is_chint_customer(customer) and CHINT_REPORT_PATH.exists():
        return CHINT_REPORT_PATH, CHINT_SOURCE_PATH, "正泰电器"
    if _is_zhonghuan_customer(customer) and ZHONGHUAN_REPORT_PATH.exists():
        return ZHONGHUAN_REPORT_PATH, ZHONGHUAN_SOURCE_PATH, "中环电气集团"
    if _is_tianyu_customer(customer) and TIANYU_REPORT_PATH.exists():
        return TIANYU_REPORT_PATH, TIANYU_SOURCE_PATH, "天宇电气"
    return None


def _file_for_kind(project: CustomerProject, kind: str) -> Path | None:
    mapping = {
        "report": project.report_path,
        "report-docx": project.word_report_path,
        "prompt": project.prompt_path,
        "template": project.template_path,
        "source-plan": project.source_plan_path,
        "field-register": project.field_register_path,
        "source-registry": project.source_registry_path,
    }
    value = mapping.get(kind)
    return Path(value) if value else None


def _framework_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for module, fields in fields_by_module().items():
        catalog.append(
            {
                "module": module,
                "name": _module_display_name(module),
                "field_count": len(fields),
                "categories": sorted({item.category for item in fields}),
            }
        )
    return catalog


def _build_insight_dashboard(project: CustomerProject, source_count: int = 0) -> dict[str, Any]:
    report_text = ""
    if project.report_path and Path(project.report_path).exists():
        report_text = Path(project.report_path).read_text(encoding="utf-8")
    matrix = _framework_matrix(report_text)
    module_summary = _module_summary(matrix)
    status_counts: dict[str, int] = {}
    for item in matrix:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    opportunities = _extract_markdown_table(report_text, "施耐德业务机会地图", limit=6)
    actions = _extract_markdown_table(report_text, "90天行动建议", limit=5)
    if not actions:
        actions = _actions_from_opportunities(opportunities)
    profile = _customer_profile(project.customer)
    gaps = _priority_gaps(matrix, limit=8)
    risks = _extract_risk_points(report_text)
    summary = _extract_section_preview(report_text, "高层摘要", limit=420)
    portrait = _customer_portrait(project.customer, opportunities, risks, gaps)
    basic_info = _customer_basic_info(project.customer)
    certifications = _customer_certifications(project.customer)
    scale_finance = _customer_scale_finance(project.customer)
    business_capability = _customer_business_capability(project.customer)
    supply_procurement = _customer_supply_procurement(project.customer)
    customer_resources = _customer_resources(project.customer)
    sales_market = _customer_sales_market(project.customer)
    org_decision = _customer_org_decision(project.customer)
    strategy_needs = _customer_strategy_needs(project.customer)
    pain_opportunities = _customer_pain_opportunities(project.customer)
    risk_assessment = _customer_risk_assessment(project.customer)
    explicit_count = sum(1 for item in matrix if item["status"] in {"已写入报告", "已识别缺口"})
    internal_count = sum(1 for item in matrix if item["status"] == "需内部数据")
    interview_count = sum(1 for item in matrix if item["status"] == "需客户访谈")
    return {
        "profile": profile,
        "basic_info": basic_info,
        "certifications": certifications,
        "scale_finance": scale_finance,
        "business_capability": business_capability,
        "supply_procurement": supply_procurement,
        "customer_resources": customer_resources,
        "sales_market": sales_market,
        "org_decision": org_decision,
        "strategy_needs": strategy_needs,
        "pain_opportunities": pain_opportunities,
        "risk_assessment": risk_assessment,
        "portrait": portrait,
        "summary": summary,
        "source_count": source_count,
        "kpis": [
            {"label": "大纲字段", "value": str(len(FRAMEWORK)), "note": "Excel 框架字段全量纳入"},
            {"label": "模块覆盖", "value": f"{len(module_summary)}/9", "note": "基础、业务、采购、客户、市场、决策、战略、机会、风险"},
            {"label": "报告显性处理", "value": f"{explicit_count}/{len(FRAMEWORK)}", "note": "字段名已写入或已明确标注缺口"},
            {"label": "内部/访谈待补", "value": str(internal_count + interview_count), "note": "需施耐德内部数据或客户访谈闭环"},
            {"label": "来源引用", "value": str(source_count), "note": "报告引用来源可点击追溯"},
        ],
        "module_summary": module_summary,
        "status_counts": status_counts,
        "opportunities": opportunities,
        "actions": actions,
        "risks": risks,
        "gaps": gaps,
        "framework_matrix": matrix,
    }


def _framework_matrix(report_text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in FRAMEWORK:
        status, owner, evidence = _field_status(item, report_text)
        rows.append(
            {
                "module": item.module,
                "module_name": _module_display_name(item.module),
                "category": item.category,
                "field": item.field,
                "description": item.description,
                "status": status,
                "owner": owner,
                "evidence": evidence,
                "priority": _field_priority(item),
            }
        )
    return rows


def _field_status(item: InsightField, report_text: str) -> tuple[str, str, str]:
    if item.field in report_text:
        window = _context_window(report_text, item.field)
        if _has_gap_language(window):
            return "已识别缺口", _field_owner(item), "报告已指出该字段需内部补充或访谈核验"
        return "已写入报告", "公开研究/报告", "报告正文已显性覆盖该字段"
    if _needs_internal_data(item):
        return "需内部数据", _field_owner(item), "公开资料通常无法确认，需从 CRM/ERP/授权/信用/售后系统补齐"
    if _needs_interview(item):
        return "需客户访谈", _field_owner(item), "涉及真实流程、偏好、满意度或痛点，需拜访核验"
    return "需公开补查", "公开研究/客户经理", "建议继续补查官网、招投标、工商、资质、招聘或公告材料"


def _context_window(text: str, target: str, size: int = 120) -> str:
    index = text.find(target)
    if index < 0:
        return ""
    return text[max(0, index - size) : index + len(target) + size]


def _has_gap_language(text: str) -> bool:
    return any(word in text for word in ("未披露", "无法确认", "待内部补充", "需访谈", "需内部", "公开资料不足", "待核验"))


def _needs_internal_data(item: InsightField) -> bool:
    keywords = (
        "施耐德",
        "合作年限",
        "合作模式",
        "采购额",
        "采购增长率",
        "主要采购产品",
        "授权",
        "满意度",
        "竞品采购比例",
        "竞品使用原因",
        "竞品优势",
        "竞品劣势",
        "付款信用",
        "合同履约",
        "售后纠纷",
        "头部客户收入占比",
        "客户粘性",
        "复购率",
        "价格敏感度",
        "价格水平",
        "数字化预算",
    )
    value = f"{item.module} {item.category} {item.field} {item.description}"
    return any(keyword in value for keyword in keywords)


def _needs_interview(item: InsightField) -> bool:
    keywords = (
        "负责人",
        "管理风格",
        "技术偏好",
        "决策流程",
        "决策周期",
        "决策影响因素",
        "客户获取方式",
        "客户满意度",
        "痛点",
        "需求",
        "短期目标",
        "中长期规划",
        "扩张计划",
        "数字化现状",
        "绿色产品",
        "设备更新",
    )
    value = f"{item.module} {item.category} {item.field} {item.description}"
    return any(keyword in value for keyword in keywords)


def _field_owner(item: InsightField) -> str:
    if item.module.startswith("3."):
        return "施耐德销售/渠道/采购数据"
    if item.module.startswith("6."):
        return "客户经理/关键人访谈"
    if item.module.startswith("8."):
        return "客户访谈/技术服务"
    if item.module.startswith("9."):
        return "商务信用/售后/法务"
    if _needs_internal_data(item):
        return "施耐德内部系统"
    if _needs_interview(item):
        return "客户访谈"
    return "公开研究"


def _field_priority(item: InsightField) -> str:
    if item.module.startswith(("3.", "6.", "8.", "9.")):
        return "P1"
    if item.module.startswith(("4.", "7.")):
        return "P2"
    return "P3"


def _module_summary(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for module, fields in fields_by_module().items():
        module_rows = [row for row in matrix if row["module"] == module]
        explicit = sum(1 for row in module_rows if row["status"] in {"已写入报告", "已识别缺口"})
        internal = sum(1 for row in module_rows if row["status"] == "需内部数据")
        interview = sum(1 for row in module_rows if row["status"] == "需客户访谈")
        public_gap = sum(1 for row in module_rows if row["status"] == "需公开补查")
        summary.append(
            {
                "module": module,
                "name": _module_display_name(module),
                "field_count": len(fields),
                "explicit_count": explicit,
                "internal_count": internal,
                "interview_count": interview,
                "public_gap_count": public_gap,
                "completion": round((explicit / len(fields)) * 100) if fields else 0,
            }
        )
    return summary


def _module_display_name(module: str) -> str:
    return re.sub(r"^\d+\.\s*", "", module).strip()


def _priority_gaps(matrix: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    priority_rank = {"P1": 0, "P2": 1, "P3": 2}
    status_rank = {"需内部数据": 0, "需客户访谈": 1, "需公开补查": 2, "已识别缺口": 3, "已写入报告": 4}
    gaps = [row for row in matrix if row["status"] not in {"已写入报告"}]
    gaps.sort(key=lambda row: (priority_rank.get(row["priority"], 9), status_rank.get(row["status"], 9), row["module"]))
    return gaps[:limit]


def _extract_markdown_table(text: str, heading_keyword: str, limit: int = 6) -> list[dict[str, str]]:
    if not text:
        return []
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.startswith("##") and heading_keyword in line:
            start = index
            break
    if start < 0:
        return []
    table_lines: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("##") and table_lines:
            break
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines.append(stripped)
        elif table_lines:
            break
    rows = _parse_markdown_table(table_lines)
    if len(rows) < 2:
        return []
    headers = rows[0]
    data_rows = rows[1 : limit + 1]
    return [{headers[index]: value for index, value in enumerate(row[: len(headers)])} for row in data_rows]


def _parse_markdown_table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _actions_from_opportunities(opportunities: list[dict[str, str]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for item in opportunities[:5]:
        actions.append(
            {
                "周期": item.get("优先级", "P1"),
                "目标": item.get("机会主题", ""),
                "动作": item.get("下一步动作", item.get("推荐方案", "")),
                "交付物": item.get("推荐切入方案", item.get("推荐方案", "机会推进记录")),
            }
        )
    return actions


def _extract_section_preview(text: str, heading_keyword: str, limit: int = 420) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.startswith("##") and heading_keyword in line:
            start = index + 1
            break
    if start < 0:
        return ""
    chunks: list[str] = []
    for line in lines[start:]:
        stripped = line.strip()
        if re.match(r"^#{1,2}\s+", stripped):
            break
        if stripped and not stripped.startswith("|") and not re.fullmatch(r"[-*]\s*", stripped):
            chunks.append(re.sub(r"^[-*]\s+", "", stripped))
        if len(" ".join(chunks)) >= limit:
            break
    preview = " ".join(chunks)
    return preview[:limit].rstrip() + ("..." if len(preview) > limit else "")


def _extract_risk_points(text: str) -> list[str]:
    section = _extract_section_body(text, "风险评估模块")
    risks: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            risks.append(stripped.removeprefix("- ").strip())
        elif stripped.startswith("|") and "风险" in stripped and not re.search(r"\|\s*-{3,}", stripped):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) >= 2 and cells[0] not in {"风险", "字段", "维度"}:
                risks.append("：".join(cells[:2]))
        if len(risks) >= 5:
            break
    if risks:
        return risks
    fallback = _extract_section_preview(text, "风险评估模块", limit=240)
    return [fallback] if fallback else []


def _extract_section_body(text: str, heading_keyword: str) -> str:
    lines = text.splitlines()
    start = -1
    for index, line in enumerate(lines):
        if line.startswith("##") and heading_keyword in line:
            start = index + 1
            break
    if start < 0:
        return ""
    body: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    return "\n".join(body)


def _customer_profile(customer: str) -> dict[str, str]:
    if _is_chint_customer(customer):
        return {
            "short_name": "正泰电器",
            "account_type": "竞合型战略客户",
            "relationship": "既是潜在大客户，也是低压电器自有品牌竞争方",
            "opportunity_level": "高",
            "risk_level": "中高",
            "recommended_focus": "海外认证、数据中心、储能光储充、智能配电和服务协同",
        }
    if _is_zhonghuan_customer(customer):
        return {
            "short_name": "中环电气",
            "account_type": "项目型重点盘厂客户",
            "relationship": "以招投标和项目交付为核心的成套/工程客户",
            "opportunity_level": "中高",
            "risk_level": "中",
            "recommended_focus": "授权状态、近三年采购额、项目指定品牌、公共建筑与工业可靠配电",
        }
    if _is_tianyu_customer(customer):
        return {
            "short_name": "天宇电气",
            "account_type": "国资集团型成套/一次设备客户",
            "relationship": "中国电气装备/许继体系内客户，存在集团内部供应链边界",
            "opportunity_level": "高",
            "risk_level": "中高",
            "recommended_focus": "年度物料准入、新能源/水利/化工项目、低压柜标准BOM和工厂能效",
        }
    return {
        "short_name": customer,
        "account_type": "待分型盘厂客户",
        "relationship": "需先完成主体核验和施耐德内部交易拉通",
        "opportunity_level": "待评估",
        "risk_level": "待评估",
        "recommended_focus": "先补齐客户主数据、授权状态、采购额、项目线索和关键人地图",
    }


def _customer_portrait(
    customer: str,
    opportunities: list[dict[str, str]],
    risks: list[str],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    if _is_chint_customer(customer):
        portrait = {
            "headline": "规模大、能力强、竞合属性明显的战略级盘厂/低压电器客户",
            "tags": ["竞合型", "海外项目", "储能/光储充", "数据中心", "自有品牌强"],
            "business_role": "既可能作为施耐德高端元器件和解决方案客户，也可能在常规低压元件上形成直接竞争。",
            "relationship_strategy": "避免用常规价格战切入，优先从业主指定、国际认证、高可靠场景、服务响应和数字化方案建立合作边界。",
            "needs": ["海外认证与国际业主认可", "储能和光储充安全配电", "数据中心高可靠配电", "工厂能效与智能运维"],
            "pain_points": ["常规低压元件竞争激烈", "集团内部供应链和自有品牌替代强", "不同关联主体采购与信用需拆分管理"],
            "decision_chain": [
                {"role": "集团/业务单元高层", "focus": "战略合作边界、重点行业和海外项目"},
                {"role": "技术/质量", "focus": "认证、可靠性、标准图纸和质量闭环"},
                {"role": "采购/供应链", "focus": "价格、交期、年度框架和供应稳定性"},
                {"role": "项目/海外团队", "focus": "业主指定、合规认证、现场服务和交付风险"},
            ],
            "next_questions": ["哪些海外或高可靠项目必须使用国际品牌？", "施耐德是否已进入标准BOM或授权柜型？", "最近两年丢单的主要竞品和原因是什么？"],
        }
    elif _is_zhonghuan_customer(customer):
        portrait = {
            "headline": "项目招投标驱动、公开信息透明度有限的重点区域盘厂客户",
            "tags": ["项目型", "招投标", "高低压柜", "母线槽/桥架", "资料待补强"],
            "business_role": "价值集中在项目入口和区域工程网络，适合用项目指定品牌、标准BOM和服务响应撬动合作。",
            "relationship_strategy": "先做主数据、授权状态和近三年采购额核验，再围绕公共建筑、化工、电力改造、母线槽联动项目建立机会池。",
            "needs": ["授权状态和采购额核验", "项目品牌规范复盘", "可靠配电和服务响应", "改造类项目标准报价包"],
            "pain_points": ["非上市企业信息透明度低", "项目型业务账期和现金流不确定", "竞品价格和本地关系竞争明显"],
            "decision_chain": [
                {"role": "法人/总经理", "focus": "项目资源、重大采购和信用边界"},
                {"role": "技术负责人", "focus": "柜体方案、元器件选型、图纸和项目规范"},
                {"role": "采购负责人", "focus": "价格、交期、供应商准入和账期"},
                {"role": "项目经理/销售", "focus": "招标文件、业主指定品牌和现场交付"},
            ],
            "next_questions": ["是否为施耐德授权盘厂或协议厂？", "近三年采购额、SKU、账期和逾期情况如何？", "哪些项目可由业主/设计院指定施耐德？"],
        }
    elif _is_tianyu_customer(customer):
        portrait = {
            "headline": "国资集团体系内、项目和制造升级双驱动的高价值成套客户",
            "tags": ["国资体系", "许继/中国电气装备", "新能源/水利/化工", "年度物料准入", "智能制造"],
            "business_role": "兼具客户、生态伙伴和内部供应链竞争边界，需要围绕准入、项目指定和高可靠场景经营。",
            "relationship_strategy": "优先核验施耐德是否进入年度中标物料和合格供应商清单，再以低压柜标准BOM、重点项目澄清和工厂能效场景切入。",
            "needs": ["年度物料/合格供应商准入", "新能源和重大工程项目配电", "低压柜设计效率提升", "智能制造工厂能效升级"],
            "pain_points": ["集团内部供应链协同强", "成本敏感和低价中标压力", "供应商准入流程较长", "质量与售后责任需边界清晰"],
            "decision_chain": [
                {"role": "高层/业务单元", "focus": "增长目标、重点行业和集团协同边界"},
                {"role": "采购/供应链", "focus": "年度中标物料、集采平台和价格机制"},
                {"role": "低压柜设计/技术", "focus": "元器件型号确认、标准BOM和替代清单"},
                {"role": "生产/质量/服务", "focus": "交付、质量修复、现场调试和售后责任"},
            ],
            "next_questions": ["施耐德哪些品类已进入年度物料清单？", "业主指定品牌和集团内部产品的边界是什么？", "哪些新能源、水利、化工项目适合联合技术澄清？"],
        }
    else:
        portrait = {
            "headline": "待完成主体核验和内部交易拉通的盘厂客户",
            "tags": ["待核验", "待分型", "需内部数据", "需访谈"],
            "business_role": "需先判断客户规模、产品能力、施耐德合作基础和项目资源，再确定经营分层。",
            "relationship_strategy": "先补齐主体信息、采购额、授权状态、关键人、项目线索和信用记录，再决定是否列为重点客户。",
            "needs": ["客户主数据核验", "历史采购与授权状态", "项目线索梳理", "关键人地图"],
            "pain_points": ["公开资料不足", "内部交易未拉通", "决策链和项目机会不清晰"],
            "decision_chain": [
                {"role": "客户经理", "focus": "主体、联系人和历史关系"},
                {"role": "渠道/授权管理", "focus": "授权等级和柜型"},
                {"role": "商务信用", "focus": "账期、逾期和履约风险"},
            ],
            "next_questions": ["客户在施耐德系统中的编码是什么？", "近三年采购额和产品结构如何？", "是否存在授权盘厂关系？"],
        }
    portrait["top_opportunities"] = _portrait_top_opportunities(opportunities)
    portrait["top_risks"] = risks[:3]
    portrait["must_fill_fields"] = [
        {"field": gap["field"], "module": gap["module_name"], "status": gap["status"]} for gap in gaps[:5]
    ]
    return portrait


def _customer_basic_info(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            _basic_row("企业名称", "浙江正泰电器股份有限公司", "成套厂全称/上市公司主体", ["S1"]),
            _basic_row("统一社会信用代码", "91330000142944445H", "企业唯一标识", ["S1"]),
            _basic_row("成立时间", "1997-08-05", "企业经营年限", ["S1"]),
            _basic_row("注册资本", "2,148,968,976 元", "反映企业规模", ["S1"]),
            _basic_row("企业性质", "境内民营上市公司；控股股东为正泰集团股份有限公司", "民营上市平台客户", ["S1"]),
            _basic_row(
                "股权结构",
                "正泰集团直接持股 41.18%；浙江正泰新能源投资有限公司 8.39%；南存辉直接持股 3.45%；最终控制人为南存辉",
                "主要股东及持股比例",
                ["S1", "S2"],
            ),
            _basic_row("法人代表", "南存辉", "企业法定代表人/董事长线索", ["S1"]),
            _basic_row("注册地址", "浙江省乐清市北白象镇正泰工业园区正泰路 1 号", "企业注册地", ["S1"]),
            _basic_row(
                "实际经营地址",
                "公开年报披露的注册/办公地址同为浙江省乐清市北白象镇正泰工业园区正泰路 1 号；具体生产基地和项目对接厂区需按业务核验",
                "生产基地/办公地址",
                ["S1", "S3", "S5", "S8"],
            ),
        ]
    if _is_zhonghuan_customer(customer):
        return [
            _basic_row("企业名称", "江苏中环电气集团有限公司", "成套厂全称", ["ZH1"]),
            _basic_row("统一社会信用代码", "91321182782724213T", "企业唯一标识", ["ZH1"]),
            _basic_row("成立时间", "2006-03-13", "企业经营年限", ["ZH1"]),
            _basic_row("注册资本", "20,018 万元", "反映企业规模", ["ZH1"]),
            _basic_row("企业性质", "在业；电气机械和器材制造业；非上市项目型盘厂客户", "公开页面未披露完整工商企业类型", ["ZH1", "ZH2"]),
            _basic_row("股权结构", "公开资料未披露主要股东及持股比例，需工商底档或客户访谈补齐", "主要股东及持股比例", []),
            _basic_row("法人代表", "王永贵", "法定负责人", ["ZH1", "ZH5"]),
            _basic_row("注册地址", "江苏省扬中市新坝工业园区（南自路）", "企业注册地", ["ZH1"]),
            _basic_row("实际经营地址", "江苏省扬中市新坝工业园区（南自路）；招聘公司介绍补充披露占地约3.2万平方米、建筑面积约1.8万平方米", "生产基地/办公地址", ["ZH1", "ZH9"]),
        ]
    if _is_tianyu_customer(customer):
        return [
            _basic_row("企业名称", "福州天宇电气股份有限公司", "成套厂全称", ["TY3", "TY6", "TY11"]),
            _basic_row("统一社会信用代码", "91350100798359919L", "企业唯一标识；来自公开工商信息，建议以国家企业信用信息公示系统复核", []),
            _basic_row("成立时间", "公开工商信息显示 2007-01-22；招聘/高校就业资料存在“成立于1996年”的历史沿革口径，需区分工商成立日与原福州开关/变压器厂整合历史", "企业经营年限，需区分工商成立日与历史沿革", ["TY6", "TY12", "TY15"]),
            _basic_row("注册资本", "32,790.72 万元", "反映企业规模", ["TY3"]),
            _basic_row("企业性质", "股份有限公司（非上市、国有控股）；中国电气装备集团所属许继集团体系内企业，历史资料显示其曾为国家电网许继集团体系制造基地", "国资集团型客户", ["TY1", "TY3", "TY6", "TY12", "TY14", "TY15"]),
            _basic_row("股权结构", "许继集团体系内企业；公开资料显示同受中国电气装备集团控制，具体直接股东和持股比例需以工商底档复核", "主要股东及持股比例", ["TY1", "TY3", "TY8"]),
            _basic_row("法人代表", "张红彬", "法定代表人/董事长线索", ["TY1", "TY3"]),
            _basic_row("注册地址", "福建省福州市闽侯县南屿镇尧溪路 28 号", "企业注册地", ["TY3"]),
            _basic_row("实际经营地址", "福建省福州市闽侯县南屿镇尧溪路 28 号；智能制造升级项目亦指向该地点，高校就业资料补充南屿生物医药与机电产业园地址线索", "生产基地/办公地址", ["TY3", "TY7", "TY15"]),
        ]
    return [
        _basic_row("企业名称", customer, "成套厂全称", []),
        _basic_row("统一社会信用代码", "待核验", "企业唯一标识", []),
        _basic_row("成立时间", "待核验", "企业经营年限", []),
        _basic_row("注册资本", "待核验", "反映企业规模", []),
        _basic_row("企业性质", "待核验", "国企/民企/外资/合资", []),
        _basic_row("股权结构", "待核验", "主要股东及持股比例", []),
        _basic_row("法人代表", "待核验", "企业法定代表人", []),
        _basic_row("注册地址", "待核验", "企业注册地", []),
        _basic_row("实际经营地址", "待核验", "生产基地/办公地址", []),
    ]


def _basic_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_certifications(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            _certification_row(
                "低压成套设备生产资质",
                "公开资料显示正泰具备低压电器、成套柜体及多国认证能力；具体低压成套设备生产资质、CCC/CQC和型式试验清单需按主体核验",
                "资质与认证",
                ["S1", "S3"],
            ),
            _certification_row("高压成套设备资质", "公开报告未直接披露正泰电器本体高压成套设备资质，需区分正泰集团/关联主体后核验", "资质与认证", []),
            _certification_row("ISO体系认证", "年报披露轨交系列产品通过 ISO/TS 22163 铁路质量体系认证；官网质量信用资料可作为质量体系和服务体系复核入口，ISO9001/14001/45001完整证书清单仍需按主体核验", "ISO9001/14001/45001等", ["S1", "S12"]),
            _certification_row("特种设备生产许可证", "公开资料未披露，需按具体产品和法人主体核验", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "公开资料未披露，需核验是否由关联工程主体承接", "资质名称与等级", []),
            _certification_row("承装修试资质", "公开资料未披露，需核验承装/承修/承试资质等级及有效期", "资质名称与等级", []),
            _certification_row("施耐德授权等级", "公开资料未披露，需施耐德渠道/授权系统核验协议厂、授权盘厂、战略合作伙伴及授权柜型", "协议厂/授权盘厂/战略合作伙伴", []),
        ]
    if _is_zhonghuan_customer(customer):
        return [
            _certification_row("低压成套设备生产资质", "经营范围和公开项目线索覆盖开关柜、配电箱等；低压成套CCC/CQC、型式试验和生产资质清单待核验", "资质与认证", ["ZH1", "ZH2"]),
            _certification_row("高压成套设备资质", "威海高压开关柜项目显示其具备高压柜项目供货/投标线索；具体高压成套资质和型式试验报告待核验", "资质与认证", ["ZH3"]),
            _certification_row("ISO体系认证", "公开资料未直接披露ISO9001/14001/45001证书；江苏省中小企业公共服务平台披露其质量管理和荣誉资质线索，可先作为管理能力侧影，但不能替代ISO证书", "ISO9001/14001/45001等", ["ZH6", "ZH14"]),
            _certification_row("特种设备生产许可证", "公开资料未披露，需客户提供或通过监管/资质平台核验", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "公开资料显示其业务含电气工程安装、建设工程施工等线索；具体电力承包施工资质等级待核验", "资质名称与等级", ["ZH2"]),
            _certification_row("承装修试资质", "公开资料未披露承装/承修/承试资质等级，需客户访谈或资质平台核验", "资质名称与等级", []),
            _certification_row("施耐德授权等级", "公开资料未披露，需施耐德内部核验是否为协议厂/授权盘厂及授权柜型", "协议厂/授权盘厂/战略合作伙伴", []),
        ]
    if _is_tianyu_customer(customer):
        return [
            _certification_row("低压成套设备生产资质", "引江济淮项目公示显示低压开关柜部分提供强制性认证产品符合性自我声明；完整低压成套证书清单需核验", "资质与认证", ["TY4"]),
            _certification_row("高压成套设备资质", "引江济淮项目公示显示35kV、10kV开关柜所投产品具备有效型式试验报告", "资质与认证", ["TY4"]),
            _certification_row("ISO体系认证", "公开资料未披露ISO9001/14001/45001完整证书；ESG报告、国资集团资料和校园招聘资料可作为治理与管理体系侧影，证书清单及有效期仍需客户提供", "ISO9001/14001/45001等", ["TY11", "TY15"]),
            _certification_row("特种设备生产许可证", "公开资料未披露，需按变压器、GIS、开关柜等具体产品和监管要求核验", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "经营范围许可项含建设工程施工等，具体电力承包施工资质等级待核验", "资质名称与等级", ["TY3"]),
            _certification_row("承装修试资质", "经营范围许可项含输电、供电、受电电力设施安装维修试验；具体承装/承修/承试等级待核验", "资质名称与等级", ["TY3"]),
            _certification_row("施耐德授权等级", "公开资料未披露，需施耐德内部核验授权盘厂/协议厂身份、授权柜型、有效期和年度指标", "协议厂/授权盘厂/战略合作伙伴", []),
        ]
    return [
        _certification_row("低压成套设备生产资质", "待核验", "资质与认证", []),
        _certification_row("高压成套设备资质", "待核验", "资质与认证", []),
        _certification_row("ISO体系认证", "待核验", "ISO9001/14001/45001等", []),
        _certification_row("特种设备生产许可证", "待核验", "资质名称与等级", []),
        _certification_row("电力承包施工资质", "待核验", "资质名称与等级", []),
        _certification_row("承装修试资质", "待核验", "资质名称与等级", []),
        _certification_row("施耐德授权等级", "待核验", "协议厂/授权盘厂/战略合作伙伴", []),
    ]


def _certification_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_scale_finance(customer: str) -> dict[str, list[dict[str, Any]]]:
    if _is_chint_customer(customer):
        return {
            "enterprise_scale": [
                _metric_row("员工总数", "30,214 人", "在职员工数量", ["S1"]),
                _metric_row("技术人员数量", "技术人员 4,692 人；研发人员 2,679 人", "设计、研发、技术支持人员", ["S1"]),
                _metric_row("生产人员数量", "17,793 人", "生产一线员工", ["S1"]),
                _metric_row("销售人员数量", "3,891 人", "销售团队规模", ["S1"]),
                _metric_row("厂房面积", "公开资料未披露具体厂房面积，需按正泰电器及关联生产主体核验", "生产场地面积（㎡）", []),
                _metric_row("生产基地数量", "公开资料显示拥有 20+ 个海外制造基地，集团层面国内外制造基地较多；具体正泰电器成套相关基地需拆分核验", "有几个生产基地", ["S3", "S5"]),
                _metric_row("年产能", "2025年配电电器产量 8,295.41 万台、终端电器 39,408.26 万台、控制电器 21,474.34 万台；成套柜体产能需另核验", "年产高低压柜体数量/产值", ["S1"]),
            ],
            "financial_status": [
                _metric_row("年营业收入", "2025 年 591.45 亿元；2024 年 645.19 亿元", "最近三年营业收入", ["S1"]),
                _metric_row("净利润", "2025 年归母净利润 45.01 亿元；2024 年 38.74 亿元", "最近三年净利润", ["S1"]),
                _metric_row("资产负债率", "2025 年约 66.13%；2024 年约 63.28%", "财务健康度指标", ["S1"]),
                _metric_row("现金流状况", "2025 年经营性现金流 230.90 亿元；2024 年 152.02 亿元，现金流改善明显", "经营性现金流是否健康", ["S1"]),
            ],
        }
    if _is_zhonghuan_customer(customer):
        return {
            "enterprise_scale": [
                _metric_row("员工总数", "公开资料未披露，需客户访谈或工商/社保/招聘侧信息补齐", "在职员工数量", []),
                _metric_row("技术人员数量", "公开资料未披露；高新技术企业线索可作为技术能力侧影，但不能替代人数", "设计、研发、技术支持人员", ["ZH6"]),
                _metric_row("生产人员数量", "公开资料未披露，需现场或客户访谈核验", "生产一线员工", []),
                _metric_row("销售人员数量", "公开资料未披露；项目线索显示其至少具备跨区域招采响应能力", "销售团队规模", ["ZH2", "ZH3"]),
                _metric_row("厂房面积", "招聘公司介绍披露占地约3.2万平方米、建筑面积约1.8万平方米；需现场核验生产/仓储/办公分区", "生产场地面积（㎡）", ["ZH9"]),
                _metric_row("生产基地数量", "公开主体地址为江苏省扬中市新坝工业园区（南自路），招聘介绍同时披露下设4个子公司；是否有异地生产基地待核验", "有几个生产基地", ["ZH1", "ZH9"]),
                _metric_row("年产能", "公开资料未披露高压柜、低压柜、配电箱、母线槽年产能；需客户访谈核验", "年产高低压柜体数量/产值", []),
            ],
            "financial_status": [
                _metric_row("年营业收入", "非上市公司公开资料未披露；公开项目金额只能作为规模侧影，不能替代财务报表", "最近三年营业收入", ["ZH3"]),
                _metric_row("净利润", "公开资料未披露，需客户访谈或内部授信资料补齐", "最近三年净利润", []),
                _metric_row("资产负债率", "公开资料未披露，需财务报表或授信资料核验", "财务健康度指标", []),
                _metric_row("现金流状况", "公开资料未披露；项目型业务可能存在账期和回款压力，需施耐德内部信用记录核验", "经营性现金流是否健康", []),
            ],
        }
    if _is_tianyu_customer(customer):
        return {
            "enterprise_scale": [
                _metric_row("员工总数", "公开资料未披露最新员工总数，需客户访谈或集团资料补齐", "在职员工数量", []),
                _metric_row("技术人员数量", "公开资料未披露具体人数；低压柜设计岗位和国家级企业技术中心线索显示具备技术团队", "设计、研发、技术支持人员", ["TY6", "TY12"]),
                _metric_row("生产人员数量", "公开资料未披露；智能制造升级资料显示生产效率提升和自动化改造推进中", "生产一线员工", ["TY2"]),
                _metric_row("销售人员数量", "公开资料未披露；集团报道显示推行阿米巴经营和金牌营销员机制", "销售团队规模", ["TY1"]),
                _metric_row("厂房面积", "招聘公司主页和高校就业资料均披露占地面积约210,000平方米；智能制造工厂升级地点指向闽侯南屿基地，需以不动产/环评资料复核", "生产场地面积（㎡）", ["TY7", "TY12", "TY15"]),
                _metric_row("生产基地数量", "公开资料主要指向福州闽侯南屿基地；招聘公司主页、高校就业资料和环评资料共同支持该生产基地线索，是否有其他生产基地待核验", "有几个生产基地", ["TY3", "TY7", "TY12", "TY15"]),
                _metric_row("年产能", "公开资料未披露柜体年产能；2025年新签合同额 30 多亿元、主变/箱变收入突破形成产能压力线索", "年产高低压柜体数量/产值", ["TY1"]),
            ],
            "financial_status": [
                _metric_row("年营业收入", "2025 年集团媒体口径近 23 亿元；2024 年公告口径 12.34 亿元；深交所关联交易公告可用于交叉验证历史财务口径", "最近三年营业收入", ["TY1", "TY3", "TY13"]),
                _metric_row("净利润", "2025 年集团媒体口径 1.6 亿元；2024 年公告口径 0.13 亿元；深交所公告补充证券披露交叉验证", "最近三年净利润", ["TY1", "TY3", "TY13"]),
                _metric_row("资产负债率", "按2024年总资产18.70亿元、净资产4.16亿元推算约77.8%，需以正式财务报表复核；证券公告可用于年度交叉验证", "财务健康度指标", ["TY3", "TY13"]),
                _metric_row("现金流状况", "公开资料未披露经营性现金流；项目扩张期现金流和回款节奏需内部信用/客户访谈核验", "经营性现金流是否健康", []),
            ],
        }
    return {
        "enterprise_scale": [
            _metric_row("员工总数", "待核验", "在职员工数量", []),
            _metric_row("技术人员数量", "待核验", "设计、研发、技术支持人员", []),
            _metric_row("生产人员数量", "待核验", "生产一线员工", []),
            _metric_row("销售人员数量", "待核验", "销售团队规模", []),
            _metric_row("厂房面积", "待核验", "生产场地面积（㎡）", []),
            _metric_row("生产基地数量", "待核验", "有几个生产基地", []),
            _metric_row("年产能", "待核验", "年产高低压柜体数量/产值", []),
        ],
        "financial_status": [
            _metric_row("年营业收入", "待核验", "最近三年营业收入", []),
            _metric_row("净利润", "待核验", "最近三年净利润", []),
            _metric_row("资产负债率", "待核验", "财务健康度指标", []),
            _metric_row("现金流状况", "待核验", "经营性现金流是否健康", []),
        ],
    }


def _metric_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_business_capability(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "低压电器、光伏电站开发运营、EPC、户用光伏、逆变器与储能；低压分产品包括终端电器、配电电器、控制电器、仪器仪表、建筑电器", "高压柜/低压柜/箱变/配电箱等", ["S1"]),
                    _business_row("产品线覆盖", "智慧电器与绿色能源两大主线，覆盖低压电器、智能配电、新能源、储能、微电网、能源运维等", "全产品线", ["S1", "S3"]),
                    _business_row("主营行业领域", "电力、新能源、数据中心、轨交、锂电、充电桩、半导体、储能及海外市场", "建筑/工业/电力/新能源等", ["S1", "S3"]),
                    _business_row("业务收入结构", "2025 年低压电器 219.19 亿元、光伏业务 362.74 亿元、逆变器及储能 23.90 亿元；地区收入包含华东 235.69 亿元、华中 107.65 亿元、海外 99.51 亿元等", "各业务板块收入占比", ["S1"]),
                ],
            },
            {
                "category": "技术能力",
                "rows": [
                    _business_row("设计团队规模", "年报披露研发人员 2,679 人、技术人员 4,692 人；电气设计人员口径需客户访谈拆分", "电气设计人员数量", ["S1"]),
                    _business_row("设计软件使用", "公开资料未披露 EPLAN/CAD/三维设计使用情况，需通过技术访谈确认", "EPLAN/CAD/三维设计等", []),
                    _business_row("研发投入占比", "2025 年研发费用 13.26 亿元，占营业收入约 2.24%", "研发费用/营业收入", ["S1"]),
                    _business_row("专利数量", "公开报告显示持续进行专利与产品创新布局，但本项目尚未摘录有效专利数量，需以年报附注、知识产权平台或企查查补充", "发明专利/实用新型/外观设计", []),
                    _business_row("技术合作方", "公开资料未披露具体设计院或高校合作方，建议在客户访谈中核验联合研发、设计院入围和项目标准图纸来源", "与哪些设计院/高校合作", []),
                ],
            },
            {
                "category": "生产能力",
                "rows": [
                    _business_row("生产设备水平", "累计投入超过 23 亿元推进智能制造，建成多类数字化产线，并具备检测、校准和在线质控能力", "自动化程度/设备先进性", ["S3"]),
                    _business_row("质量控制体系", "具备质量检测中心、数字化质控点、质量信用和全流程质量管理线索；官网质量信用资料还披露客服热线、官网、微信公众号、小程序等服务闭环，适合进一步核验成套柜体检测设备与出厂试验流程", "检测设备、质检流程", ["S3", "S12"]),
                    _business_row("生产周期", "公开资料未披露从下单到交付的平均周期，需按低压柜、配电箱、箱变等品类访谈核验", "从下单到交付的平均周期", []),
                    _business_row("准时交付率", "公开资料未披露历史订单准时交付比例，需施耐德订单履约数据和客户生产计划访谈补齐", "历史订单准时交付比例", []),
                    _business_row("质量合格率", "公开资料未披露产品一次合格率，需客户质量记录、施耐德售后/投诉记录或现场审核补齐", "产品一次合格率", []),
                ],
            },
            {
                "category": "项目经验",
                "rows": [
                    _business_row("代表性项目", "华为上板开关、牧原智能单元箱、远景风电专供、库柏 UL 数据中心专供、UL 储能机型等线索", "历史标杆项目案例", ["S1"]),
                    _business_row("项目类型分布", "电网、新能源、数据中心、轨交、锂电池、充电桩、半导体、储能和海外项目等", "建筑/工业/市政/电力等占比", ["S1"]),
                    _business_row("项目地域分布", "公开资料显示服务全球 140+ 国家和地区，并覆盖欧洲、亚太、西亚非、拉美、北美等海外区域", "业务覆盖省份/城市", ["S1", "S3"]),
                    _business_row("大型项目经验", "具备北美数据中心、海外能源与新能源项目经验；500 万以上成套项目清单需从施耐德内部商机和客户项目清单核验", "500万+项目经验", ["S1"]),
                    _business_row("行业标杆客户", "汇川储能、青山控股、珠海泰坦、华为、牧原、远景、库柏等公开线索", "服务过的知名客户", ["S1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "开关柜、桥架、母线槽、配电箱、支吊架、接地装置、仪器仪表管阀件等输配电和电气配套产品", "高压柜/低压柜/箱变/配电箱等", ["ZH1", "ZH2", "ZH9"]),
                    _business_row("产品线覆盖", "高低压成套/配电箱、母线槽/桥架、电气工程安装与建筑智能化业务线索较明确；招聘介绍补充接地装置、仪表管阀件等产品线", "全产品线", ["ZH1", "ZH2", "ZH9"]),
                    _business_row("主营行业领域", "公共建筑、居民小区供配电改造、化工/石化/环保、轨交/中车、电建/核电供应商准入等", "建筑/工业/电力/新能源等", ["ZH3", "ZH4", "ZH5"]),
                    _business_row("业务收入结构", "非上市公司公开资料未披露各业务板块收入占比，现阶段只能用公开项目金额和品类分布作规模侧影", "各业务板块收入占比", ["ZH3"]),
                ],
            },
            {
                "category": "技术能力",
                "rows": [
                    _business_row("设计团队规模", "公开资料未披露电气设计人员数量；高新技术企业政府名单和项目技术评分可作为技术能力侧影", "电气设计人员数量", ["ZH3", "ZH6", "ZH10"]),
                    _business_row("设计软件使用", "公开资料未披露 EPLAN/CAD/三维设计使用情况，需技术访谈或图纸流程审核确认", "EPLAN/CAD/三维设计等", []),
                    _business_row("研发投入占比", "公开资料未披露研发费用及营业收入口径，需客户财务或高企申报材料核验", "研发费用/营业收入", []),
                    _business_row("专利数量", "公开资料未披露发明专利、实用新型和外观设计数量，需补查知识产权平台或客户证书清单", "发明专利/实用新型/外观设计", []),
                    _business_row("技术合作方", "公开资料未披露具体设计院或高校合作方，建议在项目复盘中核验设计院、总包和业主技术接口", "与哪些设计院/高校合作", []),
                ],
            },
            {
                "category": "生产能力",
                "rows": [
                    _business_row("生产设备水平", "公开资料未披露自动化程度和关键设备清单；产品覆盖开关柜、桥架、母线槽、配电箱等，厂区与固定资产规模可作产能侧影，需现场审核补充设备先进性", "自动化程度/设备先进性", ["ZH1", "ZH2", "ZH9"]),
                    _business_row("质量控制体系", "公开资料未披露完整检测设备和质检流程；威海项目综合技术、商务和资信评分，以及江苏省中小企业公共服务平台披露的质量管理荣誉可作为项目交付能力侧影", "检测设备、质检流程", ["ZH3", "ZH14"]),
                    _business_row("生产周期", "公开资料未披露平均生产周期，需按高压柜、低压柜、母线槽、配电箱不同品类访谈核验", "从下单到交付的平均周期", []),
                    _business_row("准时交付率", "公开资料未披露准时交付率，需施耐德订单履约记录、项目验收记录和客户生产计划补齐", "历史订单准时交付比例", []),
                    _business_row("质量合格率", "公开资料未披露产品一次合格率，需客户质检记录、型式试验和售后质量数据补齐", "产品一次合格率", []),
                ],
            },
            {
                "category": "项目经验",
                "rows": [
                    _business_row("代表性项目", "文登 168MW 燃煤热水锅炉配套高压开关柜候选、淮河入海水道二期高低压开关柜及变压器采购候选、合肥居民小区供配电改造框架、山东裕龙石化污水处理厂、常州新东化工、宝鸡时代母线槽等", "历史标杆项目案例", ["ZH3", "ZH4", "ZH11", "ZH12"]),
                    _business_row("项目类型分布", "高压柜、低压柜/变压器、配电工程、居民小区改造、化工/环保、轨交/母线槽、电建/央企供应商等", "建筑/工业/市政/电力等占比", ["ZH3", "ZH4", "ZH5", "ZH11"]),
                    _business_row("项目地域分布", "公开线索覆盖山东、北京、福建、安徽、湖北、江苏、内蒙古、浙江等地，新增淮安水利政府项目和常州公共资源项目线索", "业务覆盖省份/城市", ["ZH2", "ZH3", "ZH11", "ZH12"]),
                    _business_row("大型项目经验", "合肥居民小区供配电设施改造框架项目 2,274.8172 万元等；淮河入海水道二期项目体现高低压开关柜及变压器政府采购候选能力，500 万以上项目需进一步清单化", "500万+项目经验", ["ZH3", "ZH11"]),
                    _business_row("行业标杆客户", "中国电建核电工程合格供应商线索、中车智能交通项目、山东裕龙石化等", "服务过的知名客户", ["ZH3", "ZH4", "ZH5"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "高低压开关柜、互感器、箱变、环氧树脂浇注绝缘件、变压器及配套设备，并延伸到储能技术服务、充电桩销售等；高校就业资料补充35kV及以下高低压开关柜和10kV及以下组合式变压器口径", "高压柜/低压柜/箱变/配电箱等", ["TY3", "TY6", "TY12", "TY15"]),
                    _business_row("产品线覆盖", "覆盖主变/箱变、高低压柜、开关成套设备、变压器/GIS 候选品类，以及储能、充电桩和工程服务线索；“榕牌”变压器、“福开”牌开关成套设备是历史品牌资产", "全产品线", ["TY1", "TY3", "TY5", "TY6", "TY15"]),
                    _business_row("主营行业领域", "水利、新能源、煤化工、钢铁、锂电前驱体、渔光互补、增量配电网、110kV 变电站、海外项目等", "建筑/工业/电力/新能源等", ["TY4", "TY5", "TY6"]),
                    _business_row("业务收入结构", "集团报道显示主变、箱变两大产品收入突破 10 亿元；2025 年营业收入近 23 亿元、新签合同额 30 多亿元，详细板块占比未披露", "各业务板块收入占比", ["TY1"]),
                ],
            },
            {
                "category": "技术能力",
                "rows": [
                    _business_row("设计团队规模", "公开资料未披露人数；招聘信息显示低压柜电气设计岗位覆盖方案优化、报价审核、元器件型号确认等职责", "电气设计人员数量", ["TY6", "TY12"]),
                    _business_row("设计软件使用", "公开资料未披露 EPLAN/CAD/三维设计使用情况；低压柜电气设计岗位职责可作为设计能力线索", "EPLAN/CAD/三维设计等", ["TY6", "TY12"]),
                    _business_row("研发投入占比", "公开资料未披露研发费用及营业收入口径，需客户财务或集团研发统计补齐", "研发费用/营业收入", []),
                    _business_row("专利数量", "公开资料未披露专利数量；集团报道显示“十四五”期间 5 项新产品研制成功", "发明专利/实用新型/外观设计", ["TY1"]),
                    _business_row("技术合作方", "公开资料未披露具体设计院或高校合作方；集团/许继体系内技术协同和设计院接口需访谈核验", "与哪些设计院/高校合作", []),
                ],
            },
            {
                "category": "生产能力",
                "rows": [
                    _business_row("生产设备水平", "具备激光切割、自动上下料、自动喷粉、机器人焊接、2400kV 雷电冲击系统、局放屏蔽试验间、工频耐压装置；关键工序数控化率 95%+，效率提升 50%+", "自动化程度/设备先进性", ["TY2"]),
                    _business_row("质量控制体系", "MOM 平台覆盖销售、设计、排产、采购、供应链、仓储、生产，并打通 SAP/MES/WMS/SRM；质量修复进展需继续跟踪", "检测设备、质检流程", ["TY1", "TY2"]),
                    _business_row("生产周期", "公开资料未披露平均生产周期；引江济淮项目交货期线索覆盖 2025 年 3 月至 2026 年 6 月，需按品类复盘", "从下单到交付的平均周期", ["TY4"]),
                    _business_row("准时交付率", "公开资料未披露准时交付率，需施耐德订单履约、集团供应链和客户交付数据补齐", "历史订单准时交付比例", []),
                    _business_row("质量合格率", "公开资料未披露产品一次合格率，需客户质量记录、售后质量数据和现场审核补齐", "产品一次合格率", []),
                ],
            },
            {
                "category": "项目经验",
                "rows": [
                    _business_row("代表性项目", "南水北调、核电建设、三峡工程、北京奥运、上海世博，以及引江济淮二期、铜陵绿色能源基地等", "历史标杆项目案例", ["TY4", "TY5", "TY6"]),
                    _business_row("项目类型分布", "水利、新能源、煤化工、钢铁、锂电前驱体、渔光互补、增量配电网、110kV 变电站、海外出口等", "建筑/工业/市政/电力等占比", ["TY4", "TY5", "TY6"]),
                    _business_row("项目地域分布", "公开资料显示出口 20+ 国家和地区；国内公开项目线索覆盖安徽、铜陵等，更多区域需按订单和项目库梳理", "业务覆盖省份/城市", ["TY4", "TY5", "TY6"]),
                    _business_row("大型项目经验", "引江济淮电气设备采购 4 标投标报价 5,663.30 万元；铜陵 110kV 变压器/GIS 项目候选等", "500万+项目经验", ["TY4", "TY5"]),
                    _business_row("行业标杆客户", "南水北调、核电、三峡、北京奥运、上海世博等项目线索，并处于中国电气装备/许继体系客户生态", "服务过的知名客户", ["TY6", "TY8", "TY15"]),
                ],
            },
        ]
    return [
        {
            "category": "主营业务",
            "rows": [
                _business_row("主营产品类型", "待核验", "高压柜/低压柜/箱变/配电箱等", []),
                _business_row("产品线覆盖", "待核验", "全产品线", []),
                _business_row("主营行业领域", "待核验", "建筑/工业/电力/新能源等", []),
                _business_row("业务收入结构", "待核验", "各业务板块收入占比", []),
            ],
        },
        {
            "category": "技术能力",
            "rows": [
                _business_row("设计团队规模", "待核验", "电气设计人员数量", []),
                _business_row("设计软件使用", "待核验", "EPLAN/CAD/三维设计等", []),
                _business_row("研发投入占比", "待核验", "研发费用/营业收入", []),
                _business_row("专利数量", "待核验", "发明专利/实用新型/外观设计", []),
                _business_row("技术合作方", "待核验", "与哪些设计院/高校合作", []),
            ],
        },
        {
            "category": "生产能力",
            "rows": [
                _business_row("生产设备水平", "待核验", "自动化程度/设备先进性", []),
                _business_row("质量控制体系", "待核验", "检测设备、质检流程", []),
                _business_row("生产周期", "待核验", "从下单到交付的平均周期", []),
                _business_row("准时交付率", "待核验", "历史订单准时交付比例", []),
                _business_row("质量合格率", "待核验", "产品一次合格率", []),
            ],
        },
        {
            "category": "项目经验",
            "rows": [
                _business_row("代表性项目", "待核验", "历史标杆项目案例", []),
                _business_row("项目类型分布", "待核验", "建筑/工业/市政/电力等占比", []),
                _business_row("项目地域分布", "待核验", "业务覆盖省份/城市", []),
                _business_row("大型项目经验", "待核验", "500万+项目经验", []),
                _business_row("行业标杆客户", "待核验", "服务过的知名客户", []),
            ],
        },
    ]


def _business_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_supply_procurement(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "施耐德合作情况",
                "rows": [
                    _supply_row("合作年限", "公开资料未披露正泰电器与施耐德合作年限；需从施耐德 CRM/ERP、渠道/授权系统和客户经理访谈补齐", "与施耐德合作多少年", []),
                    _supply_row("合作模式", "公开资料未披露协议厂/授权盘厂/普通客户身份；需拆分正泰电器、正泰电气、正泰电源、正泰安能、正泰智能电气等关联主体后核验", "协议厂/授权盘厂/普通客户", []),
                    _supply_row("历史采购额", "公开资料未披露近三年施耐德产品采购额；建议按关联主体、项目、SKU、毛利、账期、逾期拉通 CRM/ERP 数据", "近三年施耐德产品采购额", []),
                    _supply_row("采购增长率", "公开资料未披露采购额同比；需以近三年施耐德历史采购数据计算，并拆分常规采购、项目采购、海外项目采购", "采购额同比增长率", []),
                    _supply_row("主要采购产品", "公开资料未披露实际采购品类；潜在切入应聚焦高端断路器、智能配电、海外认证、客户指定品牌、数据中心和关键电源场景", "断路器/接触器/变频器/软启等", ["S1"]),
                    _supply_row("授权柜体型号", "公开资料未披露 BlokSeT/Okken/MVnex 等授权柜体型号；需渠道/授权系统核验授权范围、有效期和关联主体", "BlokSeT/Okken/MVnex等", []),
                    _supply_row("合作满意度", "公开资料未披露对施耐德服务、技术支持满意度；需销售复盘、客户投诉、现场服务和售后争议记录补齐", "对施耐德服务、技术支持的满意度", []),
                ],
            },
            {
                "category": "竞品采购情况",
                "rows": [
                    _supply_row("主要竞品品牌", "正泰自身即低压电器头部品牌，常规低压元件首先面对正泰自有品牌替代；高端项目再与 ABB、西门子、伊顿等国际品牌竞争", "西门子/ABB/正泰/德力西等", ["S1"]),
                    _supply_row("竞品采购比例", "公开资料未披露竞品采购比例；需通过施耐德赢丢单、项目 BOM 和客户采购台账计算", "竞品采购额占总采购比例", []),
                    _supply_row("竞品使用原因", "常规低压元件可能因自有品牌、成本和供应链协同胜出；国际品牌可能因业主指定、认证、数据中心/海外规范胜出", "价格/技术/服务/关系等", ["S1"]),
                    _supply_row("竞品优势感知", "正泰自有品牌优势在价格、规模化供应、渠道和集团协同；国际品牌优势在高端认证、可靠性、海外服务和业主认可", "认为竞品哪些方面更有优势", ["S1", "S3"]),
                    _supply_row("竞品劣势感知", "自有品牌在国际认证、高端业主背书和全球服务网络上可能弱于施耐德等国际品牌；具体需赢丢单复盘确认", "认为竞品哪些方面不足", ["S1"]),
                ],
            },
            {
                "category": "其他供应商",
                "rows": [
                    _supply_row("其他器件供应商", "低压业务原材料成本占 86.63%，配电/控制电器等原材料占比约 90%；采购重点可能包括铜、银、钢材、塑料、电子元器件、光伏/储能系统部件", "其他核心供应商", ["S1"]),
                    _supply_row("柜体供应商", "正泰具备自有低压电器、成套柜体和系统化能力；成套柜体自产/外购比例需按正泰电气等关联主体核验", "是否自产柜体或外购", ["S1", "S3"]),
                    _supply_row("供应链稳定性", "2025 年前五名供应商采购额 80.59 亿元，占采购总额 14.93%；关联方采购 44.86 亿元，占 8.31%，供应商集中度不极端但集团协同明显", "是否有稳定供货渠道", ["S1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "施耐德合作情况",
                "rows": [
                    _supply_row("合作年限", "公开资料未披露中环电气与施耐德合作年限；需由施耐德 CRM、客户经理和历史订单补齐", "与施耐德合作多少年", []),
                    _supply_row("合作模式", "公开资料未披露其是否为协议厂、授权盘厂或普通客户；需核验授权、协议价格、年度框架和关联主体客户编码", "协议厂/授权盘厂/普通客户", []),
                    _supply_row("历史采购额", "公开资料未披露近三年施耐德采购额；建议按中环及可能关联主体抓取采购额、SKU、项目号、毛利、账期和逾期", "近三年施耐德产品采购额", []),
                    _supply_row("采购增长率", "公开资料未披露采购额同比；需用施耐德近三年订单和项目台账计算，并剔除一次性大项目波动", "采购额同比增长率", []),
                    _supply_row("主要采购产品", "公开资料未披露实际采购品类；应重点核验断路器、接触器、继电器、变频器、软启动、智能仪表、配电监控和柜体授权系统", "断路器/接触器/变频器/软启等", []),
                    _supply_row("授权柜体型号", "公开资料未披露 BlokSeT/Okken/MVnex 等授权柜体型号；需核验是否存在施耐德授权柜型、协议价格或年度框架", "BlokSeT/Okken/MVnex等", []),
                    _supply_row("合作满意度", "公开资料未披露对施耐德服务与技术支持满意度；需结合服务记录、报价响应、交付投诉和技术支持复盘访谈", "对施耐德服务、技术支持的满意度", []),
                ],
            },
            {
                "category": "竞品采购情况",
                "rows": [
                    _supply_row("主要竞品品牌", "需重点复盘 ABB、西门子、正泰、德力西、人民电器、常熟开关、良信、伊顿等在近两年项目中的替代原因", "西门子/ABB/正泰/德力西等", []),
                    _supply_row("竞品采购比例", "公开资料无法确认竞品采购额占比；需从项目 BOM、采购台账和施耐德赢丢单记录反推", "竞品采购额占总采购比例", []),
                    _supply_row("竞品使用原因", "项目型成套业务中，竞品选择大概率受业主/设计院指定、招标技术规范、价格评分、交付周期、本地服务和总包商务偏好影响", "价格/技术/服务/关系等", ["ZH3", "ZH4", "ZH5"]),
                    _supply_row("竞品优势感知", "竞品优势可能集中在本地交付、价格得分、既有项目关系和扬中电气产业集群配套；施耐德需前置到项目规范阶段", "认为竞品哪些方面更有优势", ["ZH2", "ZH3"]),
                    _supply_row("竞品劣势感知", "低价或非授权品牌在高可靠、业主背书、技术支持和长期运维上可能弱于施耐德；需通过关键项目赢丢单访谈验证", "认为竞品哪些方面不足", []),
                ],
            },
            {
                "category": "其他供应商",
                "rows": [
                    _supply_row("其他器件供应商", "公开资料未披露核心器件供应商；洛阳双瑞预付供应商清单列示中环为设备供应商，金额 544 万元，占预付款期末余额 2.99%", "其他核心供应商", ["ZH7"]),
                    _supply_row("柜体供应商", "经营范围和项目线索覆盖开关柜、配电箱、桥架、母线槽等，推测具备柜体/配套产品自制能力；自产/外购比例需现场核验", "是否自产柜体或外购", ["ZH1", "ZH2", "ZH3"]),
                    _supply_row("供应链稳定性", "公开资料未披露稳定供货渠道；跨区域项目和央企合格供应商线索说明有项目准入基础，但需信用、交付和售后记录核验", "是否有稳定供货渠道", ["ZH3", "ZH5"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "施耐德合作情况",
                "rows": [
                    _supply_row("合作年限", "公开资料未披露天宇电气与施耐德合作年限；需从施耐德 CRM、客户编码和历史订单中核验", "与施耐德合作多少年", []),
                    _supply_row("合作模式", "公开资料未披露其是否为协议厂、授权盘厂或普通客户；需核验施耐德授权状态、授权产品和有效期", "协议厂/授权盘厂/普通客户", []),
                    _supply_row("历史采购额", "公开资料未披露近三年施耐德采购额；建议按福州天宇及关联主体抓取采购额、SKU、毛利、账期、逾期和售后服务记录", "近三年施耐德产品采购额", []),
                    _supply_row("采购增长率", "公开资料未披露采购额同比；需以施耐德订单数据计算，并结合新签合同快速增长期的项目节奏解释波动", "采购额同比增长率", ["TY1"]),
                    _supply_row("主要采购产品", "公开资料未披露实际采购品类；需核验 ACB、MCCB、MCB、接触器、继电器、变频器、软启动、无功补偿、仪表、网关、配电监控系统", "断路器/接触器/变频器/软启等", ["TY6"]),
                    _supply_row("授权柜体型号", "公开资料未披露 BlokSeT/Okken/MVnex 等授权柜体型号；需核验授权范围与低压柜标准 BOM 是否绑定", "BlokSeT/Okken/MVnex等", []),
                    _supply_row("合作满意度", "公开资料未披露对施耐德服务、技术支持满意度；需以服务响应、质量问题、报价速度和项目技术支持记录补齐", "对施耐德服务、技术支持的满意度", []),
                ],
            },
            {
                "category": "竞品采购情况",
                "rows": [
                    _supply_row("主要竞品品牌", "替代压力来自中国电气装备/许继/平高/西电体系内部产品，以及 ABB、西门子、伊顿、日立能源、正泰、良信、常熟开关、德力西、人民电器等", "西门子/ABB/正泰/德力西等", ["TY6", "TY8"]),
                    _supply_row("竞品采购比例", "公开资料无法确认竞品采购比例；需用年度中标物料清单、项目 BOM、采购台账和赢丢单记录测算", "竞品采购额占总采购比例", ["TY6"]),
                    _supply_row("竞品使用原因", "选型可能受年度中标物料供应商清单、项目指定品牌、集团供应链协同、价格、交付和认证共同影响", "价格/技术/服务/关系等", ["TY6", "TY8"]),
                    _supply_row("竞品优势感知", "集团内部产品优势在准入、协同、成本和交付；国际品牌优势在高压/中压/变压器项目指定、认证和可靠性；国内低压品牌优势在价格和供货", "认为竞品哪些方面更有优势", ["TY6", "TY8"]),
                    _supply_row("竞品劣势感知", "内部或国产品牌在国际认证、全球服务和高端可靠性背书上可能弱于施耐德；国际品牌则可能受价格和交期约束", "认为竞品哪些方面不足", ["TY6"]),
                ],
            },
            {
                "category": "其他供应商",
                "rows": [
                    _supply_row("其他器件供应商", "岗位职责显示存在年度中标物料供应商清单和非指定元器件提请招标机制；具体核心供应商名单未公开，需采购访谈核验", "其他核心供应商", ["TY6"]),
                    _supply_row("柜体供应商", "天宇生产高低压开关柜、箱变、变压器等成套设备，具备柜体制造基础；自产/外购比例和关键钣金外协需现场核验", "是否自产柜体或外购", ["TY3", "TY6"]),
                    _supply_row("供应链稳定性", "MOM 平台覆盖销售、设计、排产、采购、供应链、仓储、生产，并打通 SAP/MES/WMS/SRM；集团体系和年度物料机制有助于供货稳定", "是否有稳定供货渠道", ["TY2", "TY6"]),
                ],
            },
        ]
    return [
        {
            "category": "施耐德合作情况",
            "rows": [
                _supply_row("合作年限", "待核验", "与施耐德合作多少年", []),
                _supply_row("合作模式", "待核验", "协议厂/授权盘厂/普通客户", []),
                _supply_row("历史采购额", "待核验", "近三年施耐德产品采购额", []),
                _supply_row("采购增长率", "待核验", "采购额同比增长率", []),
                _supply_row("主要采购产品", "待核验", "断路器/接触器/变频器/软启等", []),
                _supply_row("授权柜体型号", "待核验", "BlokSeT/Okken/MVnex等", []),
                _supply_row("合作满意度", "待核验", "对施耐德服务、技术支持的满意度", []),
            ],
        },
        {
            "category": "竞品采购情况",
            "rows": [
                _supply_row("主要竞品品牌", "待核验", "西门子/ABB/正泰/德力西等", []),
                _supply_row("竞品采购比例", "待核验", "竞品采购额占总采购比例", []),
                _supply_row("竞品使用原因", "待核验", "价格/技术/服务/关系等", []),
                _supply_row("竞品优势感知", "待核验", "认为竞品哪些方面更有优势", []),
                _supply_row("竞品劣势感知", "待核验", "认为竞品哪些方面不足", []),
            ],
        },
        {
            "category": "其他供应商",
            "rows": [
                _supply_row("其他器件供应商", "待核验", "其他核心供应商", []),
                _supply_row("柜体供应商", "待核验", "是否自产柜体或外购", []),
                _supply_row("供应链稳定性", "待核验", "是否有稳定供货渠道", []),
            ],
        },
    ]


def _supply_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_resources(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "客户结构",
                "rows": [
                    _resource_row("主要客户类型", "终端业主、总包/集成商、设计院规范影响方、行业大客户、经销商/分销商、海外本土渠道和项目客户并存", "终端业主/总包/设计院/经销商", ["S1", "S4"]),
                    _resource_row("客户行业分布", "电力、电网、新能源、数据中心、通信、建筑楼宇、轨道交通、工业 OEM、锂电池、充电桩、半导体、储能、海外电力与基建等", "建筑/工业/电力/新能源/交通等", ["S1"]),
                    _resource_row("客户地域分布", "服务全球 140+ 国家和地区；国内重点收入区域包括华东、华中、华北、华南等，海外覆盖欧洲、亚太、西亚非、拉美、北美", "主要服务区域", ["S1", "S3"]),
                    _resource_row("头部客户名单", "年报未披露前十大客户名称；公开项目/行业线索可识别汇川储能、青山控股、珠海泰坦、华为、牧原、远景、库柏等重点客户或应用场景", "前10大客户名称及行业", ["S1"]),
                    _resource_row("头部客户收入占比", "2025 年前五名客户销售额 228.51 亿元，占年度销售总额 38.64%；其中关联方销售额 27.80 亿元，占 4.70%；不存在单个客户销售比例超过 50% 的情形", "前10大客户收入贡献", ["S1"]),
                ],
            },
            {
                "category": "客户关系",
                "rows": [
                    _resource_row("客户粘性", "低压分销渠道包括 500+ 一级网点合作伙伴、5000+ 规模二级网点合作伙伴和超 100,000 家终端渠道，经销商“亿元俱乐部”超过 50 家；具体复购率和合作年限未公开", "客户复购率/合作年限", ["S1", "S4"]),
                    _resource_row("客户获取方式", "以“分销网络 + 行业大客户 + 海外本土化 + 集团能源生态”为核心，国内依靠渠道覆盖和重点客户深耕，海外依靠区域本土化、能源/电力项目和数据中心项目", "招投标/关系介绍/市场开发等", ["S1", "S4"]),
                    _resource_row("客户满意度", "公开资料未披露客户对正泰服务和产品质量的系统评价；官网质量信用资料披露客服热线、官网、微信公众号、小程序等全媒体服务闭环，可作为服务触点侧影，仍需补充施耐德共同终端客户、业主指定项目和历史投诉/售后反馈", "客户对其服务/产品质量的评价", ["S12"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "客户结构",
                "rows": [
                    _resource_row("主要客户类型", "政府/公共事业/供热项目、造纸与工业企业、化工/石化/环保客户、居民小区供配电改造、轨交/装备制造、央企供应链和项目总包/业主类客户", "终端业主/总包/设计院/经销商", ["ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户行业分布", "公共事业、造纸、化工/石化/环保、住宅与公共建筑、轨交/装备制造、电建/核电工程供应链等", "建筑/工业/电力/新能源/交通等", ["ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户地域分布", "公开项目线索覆盖山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等；区域强关系需围绕扬中/镇江及重点项目省份继续访谈", "主要服务区域", ["ZH2", "ZH3"]),
                    _resource_row("头部客户名单", "公开资料未披露前十大客户；可识别项目/客户线索包括山东裕龙石化、常州新东化工、山鹰系项目、合肥居民小区供配电改造、中车宝鸡时代、中国电建核电工程、洛阳双瑞等", "前10大客户名称及行业", ["ZH3", "ZH4", "ZH5", "ZH7"]),
                    _resource_row("头部客户收入占比", "非上市公司公开资料未披露前十客户收入贡献；公开项目金额仅可作规模侧影，如合肥居民小区供配电设施改造框架项目 2,274.8172 万元等", "前10大客户收入贡献", ["ZH3"]),
                ],
            },
            {
                "category": "客户关系",
                "rows": [
                    _resource_row("客户粘性", "公开资料未披露客户复购率和合作年限；央企合格供货商清单、跨项目中标/候选线索，以及守合同重信用/AAA资信荣誉说明其具备项目准入基础，但需内部项目复盘确认粘性", "客户复购率/合作年限", ["ZH3", "ZH5", "ZH13", "ZH14"]),
                    _resource_row("客户获取方式", "以招投标、央企供应商准入、项目型成交为主，部分项目可能由业主/设计院规范、总包采购和区域关系共同驱动", "招投标/关系介绍/市场开发等", ["ZH2", "ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户满意度", "公开资料未披露客户满意度；威海项目评分、守合同重信用和质量管理荣誉可作项目资信侧影，但不能替代客户满意度，需访谈业主/总包与施耐德销售团队", "客户对其服务/产品质量的评价", ["ZH3", "ZH13", "ZH14"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "客户结构",
                "rows": [
                    _resource_row("主要客户类型", "国家重点工程终端业主、央国企/集团工程客户、水利与电网客户、新能源项目业主、工业客户、海外客户、总包和设计院规范影响方", "终端业主/总包/设计院/经销商", ["TY4", "TY5", "TY6", "TY15"]),
                    _resource_row("客户行业分布", "水利、核电、新能源/光伏/风光储、煤化工、钢铁、锂电材料、增量配电网、110kV 变电站、海外项目等", "建筑/工业/电力/新能源/交通等", ["TY4", "TY5", "TY6"]),
                    _resource_row("客户地域分布", "公开资料显示出口 20+ 国家和地区；国内线索包括引江济淮、铜陵绿色能源基地等项目，历史应用覆盖南水北调、三峡、北京奥运、上海世博等国家级场景", "主要服务区域", ["TY4", "TY5", "TY6", "TY15"]),
                    _resource_row("头部客户名单", "公开资料未披露前十大客户；可识别重点工程/客户线索包括南水北调、核电建设、三峡工程、北京奥运、上海世博、引江济淮、铜陵绿色能源基地、林洋五河、信义北海合浦、美锦煤化工、天津钢铁等", "前10大客户名称及行业", ["TY4", "TY5", "TY6", "TY15"]),
                    _resource_row("头部客户收入占比", "公开资料未披露前十大客户收入贡献；集团报道披露 2025 年新签合同额 30 多亿元、营业收入近 23 亿元，可反映整体订单活跃度但不能替代客户集中度", "前10大客户收入贡献", ["TY1"]),
                ],
            },
            {
                "category": "客户关系",
                "rows": [
                    _resource_row("客户粘性", "公开资料未披露复购率和合作年限；其年度中标物料供应商机制和大型工程项目线索显示客户关系偏项目/准入型，需补齐终端业主和集团客户复购清单", "客户复购率/合作年限", ["TY1", "TY6"]),
                    _resource_row("客户获取方式", "主要通过大型项目招投标、集团/行业客户准入、终端业主指定和区域/行业销售获取订单；低压柜岗位信息显示存在年度中标物料供应商和项目元器件型号确认机制", "招投标/关系介绍/市场开发等", ["TY1", "TY6"]),
                    _resource_row("客户满意度", "公开满意度未披露；集团报道显示 2018 年曾因产品质量问题被主要客户“拉黑”三年，2025 年重大质量事件为零，客户满意度需结合售后、验收和复购数据复核", "客户对其服务/产品质量的评价", ["TY1"]),
                ],
            },
        ]
    return [
        {
            "category": "客户结构",
            "rows": [
                _resource_row("主要客户类型", "待核验", "终端业主/总包/设计院/经销商", []),
                _resource_row("客户行业分布", "待核验", "建筑/工业/电力/新能源/交通等", []),
                _resource_row("客户地域分布", "待核验", "主要服务区域", []),
                _resource_row("头部客户名单", "待核验", "前10大客户名称及行业", []),
                _resource_row("头部客户收入占比", "待核验", "前10大客户收入贡献", []),
            ],
        },
        {
            "category": "客户关系",
            "rows": [
                _resource_row("客户粘性", "待核验", "客户复购率/合作年限", []),
                _resource_row("客户获取方式", "待核验", "招投标/关系介绍/市场开发等", []),
                _resource_row("客户满意度", "待核验", "客户对其服务/产品质量的评价", []),
            ],
        },
    ]


def _resource_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_sales_market(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "销售体系",
                "rows": [
                    _sales_row("销售团队规模", "2025 年年报披露销售人员 3,891 人；经销商“亿元俱乐部”规模扩充至 50 家以上", "销售人员数量", ["S1"]),
                    _sales_row("销售模式", "直销、经销/分销、行业大客户、海外本土化渠道与项目型销售并行；年报披露按销售模式统计主营业务收入", "直销/经销/代理", ["S1", "S4"]),
                    _sales_row("销售区域划分", "国内以华东、华中、华北、华南等区域经营，海外覆盖欧洲、亚太、西亚非、拉美、北美，并推进全球区域本土化", "如何划分销售区域", ["S1"]),
                    _sales_row("销售渠道", "拥有 500+ 一级网点合作伙伴、5000+ 规模二级网点合作伙伴和超 100,000 家终端渠道；同时发展欧洲专业批发商、海外区域渠道、官方微信公众号服务号/订阅号、官网、小程序等数字化触点", "自有渠道/合作渠道", ["S1", "S4", "S11", "S12"]),
                    _sales_row("招投标能力", "公开资料未披露投标成功率；从电网、新能源、数据中心、轨交、海外电力项目等场景看，具备行业项目销售与标杆项目交付能力", "投标成功率、标书制作能力", ["S1"]),
                ],
            },
            {
                "category": "市场覆盖",
                "rows": [
                    _sales_row("覆盖省份", "国内业务覆盖全国主要区域，集团制造与业务布局涉及温州、上海、嘉兴、沈阳、咸阳、济南、合肥、武汉、南阳、盐城等；具体省份清单需内部销售区域表核验", "业务覆盖哪些省份", ["S1", "S5"]),
                    _sales_row("重点市场", "华东、华中和海外为收入高贡献区域；海外重点拓展欧洲、亚太、西亚非、拉美、北美，北美聚焦数据中心项目", "核心市场区域", ["S1"]),
                    _sales_row("市场定位", "国内低压电器规模型龙头，覆盖大众到中高端市场；在高端场景需通过认证、可靠性和数字化服务与国际品牌竞争", "高端/中端/低端市场", ["S1"]),
                    _sales_row("品牌影响力", "年报称正泰在国内低压电器工业 OEM、建筑、个人用户三大细分市场位列第一，并持续强化品牌影响力；质量信用和多渠道服务资料增强客户服务可信度", "在当地市场的知名度", ["S1", "S12"]),
                ],
            },
            {
                "category": "价格策略",
                "rows": [
                    _sales_row("价格水平", "公开资料未披露具体价格水平；结合规模化制造、原材料成本和分销网络优势，常规低压产品预计具备较强成本竞争力，需用项目报价复盘验证", "相对市场均价的高低", []),
                    _sales_row("价格敏感度", "对常规低压元件价格敏感度高；对业主指定、海外认证、数据中心、关键电源和数字化服务等场景的价值敏感度更高", "对价格竞争的态度", ["S1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "销售体系",
                "rows": [
                    _sales_row("销售团队规模", "公开资料未披露销售人员数量；项目线索显示其至少具备跨区域招采响应能力", "销售人员数量", ["ZH2", "ZH3"]),
                    _sales_row("销售模式", "以项目型直销、招投标、总包/业主项目采购和央企供应商准入为主；是否存在经销/代理体系未披露", "直销/经销/代理", ["ZH2", "ZH3", "ZH4", "ZH5"]),
                    _sales_row("销售区域划分", "公开资料未披露内部销售区域划分；公开项目跨山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地，可能按区域项目和行业客户并行推进", "如何划分销售区域", ["ZH2", "ZH3"]),
                    _sales_row("销售渠道", "公开资料未披露自有渠道/合作渠道体系；可识别渠道包括公共资源交易、机电设备采购平台、中车/电建等供应商体系和项目总包链条", "自有渠道/合作渠道", ["ZH2", "ZH3", "ZH4", "ZH5"]),
                    _sales_row("招投标能力", "公开项目包含威海高压开关柜第一中标候选、淮河入海水道二期高低压开关柜及变压器候选、合肥居民小区供配电改造框架、中车母线槽候选和电建核电合格供应商线索；投标成功率未公开", "投标成功率、标书制作能力", ["ZH3", "ZH4", "ZH5", "ZH11"]),
                ],
            },
            {
                "category": "市场覆盖",
                "rows": [
                    _sales_row("覆盖省份", "公开项目/采购线索覆盖山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地，并新增淮安、常州等政府公共资源项目线索，具体业务覆盖省份需内部订单和客户访谈核验", "业务覆盖哪些省份", ["ZH2", "ZH3", "ZH11", "ZH12"]),
                    _sales_row("重点市场", "重点场景包括公共事业/供热、造纸、化工/石化/环保、居民小区供配电改造、轨交/装备制造、央企电建供应链", "核心市场区域", ["ZH3", "ZH4", "ZH5"]),
                    _sales_row("市场定位", "更偏项目交付型成套/配套供应商，能在桥架、母线槽、开关柜、配电箱之间做组合投标；不是全国性低压元器件品牌龙头", "高端/中端/低端市场", ["ZH1", "ZH2"]),
                    _sales_row("品牌影响力", "公开资料未披露品牌知名度排名；在扬中电气产业集群、区域工程和特定项目准入中具备一定影响力，江苏省中小企业公共服务平台披露的高企、守合同重信用、AAA资信等荣誉可增强区域信用背书", "在当地市场的知名度", ["ZH2", "ZH3", "ZH14"]),
                ],
            },
            {
                "category": "价格策略",
                "rows": [
                    _sales_row("价格水平", "公开资料不能确认价格水平；项目型招投标客户通常需面对总包/业主比价，建议用历史报价、中标价和竞品报价复盘验证", "相对市场均价的高低", []),
                    _sales_row("价格敏感度", "预计价格敏感度较高；但在高压柜、化工、电建、轨交、公共设施等项目中，认证、供货履约、品牌指定和售后响应也会影响成交", "对价格竞争的态度", ["ZH3", "ZH4", "ZH5"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "销售体系",
                "rows": [
                    _sales_row("销售团队规模", "公开资料未披露销售人员数量；集团报道显示推行阿米巴经营和金牌营销员机制，9 个业务单元经理承担经营责任", "销售人员数量", ["TY1"]),
                    _sales_row("销售模式", "大型项目招投标、集团/行业客户准入、终端业主指定、区域/行业销售和海外出口并行；低压柜设计流程中存在年度中标物料供应商机制", "直销/经销/代理", ["TY1", "TY4", "TY5", "TY6"]),
                    _sales_row("销售区域划分", "公开资料未披露内部销售区域；项目线索跨福建、安徽、天津、山西、广西、四川、云南、河南等，并有海外出口", "如何划分销售区域", ["TY4", "TY5", "TY6"]),
                    _sales_row("销售渠道", "以国资集团/许继体系、公开招投标、行业客户准入、终端业主指定和海外项目渠道为主；是否有经销/代理渠道未披露", "自有渠道/合作渠道", ["TY1", "TY6", "TY8"]),
                    _sales_row("招投标能力", "引江济淮电气设备采购 4 标第一中标候选，投标报价 5,663.30 万元；铜陵 110kV 变压器/GIS 项目候选，说明具备大型项目投标能力", "投标成功率、标书制作能力", ["TY4", "TY5"]),
                ],
            },
            {
                "category": "市场覆盖",
                "rows": [
                    _sales_row("覆盖省份", "公开线索覆盖福建、安徽、天津、山西、广西、四川、云南、河南等，并出口 20+ 国家和地区；完整覆盖省份需订单数据补齐", "业务覆盖哪些省份", ["TY4", "TY5", "TY6"]),
                    _sales_row("重点市场", "水利、新能源、煤化工、钢铁、锂电前驱体、增量配电网、110kV 变电站、海外项目和中国电气装备/许继体系内项目", "核心市场区域", ["TY4", "TY5", "TY6", "TY8"]),
                    _sales_row("市场定位", "中国电气装备/许继体系内的一次设备与成套平台，主攻变压器、箱变、高低压开关柜及配套工程项目，定位偏中高端项目型制造商", "高端/中端/低端市场", ["TY1", "TY3", "TY6"]),
                    _sales_row("品牌影响力", "公司介绍称曾为国内电气行业百强企业之一，产品应用于南水北调、核电、三峡、北京奥运、上海世博等重点工程；国资集团背书和“榕牌/福开”历史品牌增强品牌信用", "在当地市场的知名度", ["TY6", "TY8", "TY15"]),
                ],
            },
            {
                "category": "价格策略",
                "rows": [
                    _sales_row("价格水平", "公开资料不能确认价格策略；2024 年低利润和项目型业务说明价格/成本压力明显，需通过中标价、毛利和竞品报价核验", "相对市场均价的高低", ["TY3"]),
                    _sales_row("价格敏感度", "对成本和价格较敏感；但新能源、化工、钢铁、水利、电网等大型项目中，质量、认证、交付、售后和业主指定品牌也会显著影响成交", "对价格竞争的态度", ["TY1", "TY4", "TY5"]),
                ],
            },
        ]
    return [
        {
            "category": "销售体系",
            "rows": [
                _sales_row("销售团队规模", "待核验", "销售人员数量", []),
                _sales_row("销售模式", "待核验", "直销/经销/代理", []),
                _sales_row("销售区域划分", "待核验", "如何划分销售区域", []),
                _sales_row("销售渠道", "待核验", "自有渠道/合作渠道", []),
                _sales_row("招投标能力", "待核验", "投标成功率、标书制作能力", []),
            ],
        },
        {
            "category": "市场覆盖",
            "rows": [
                _sales_row("覆盖省份", "待核验", "业务覆盖哪些省份", []),
                _sales_row("重点市场", "待核验", "核心市场区域", []),
                _sales_row("市场定位", "待核验", "高端/中端/低端市场", []),
                _sales_row("品牌影响力", "待核验", "在当地市场的知名度", []),
            ],
        },
        {
            "category": "价格策略",
            "rows": [
                _sales_row("价格水平", "待核验", "相对市场均价的高低", []),
                _sales_row("价格敏感度", "待核验", "对价格竞争的态度", []),
            ],
        },
    ]


def _sales_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_org_decision(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "公开资料可确认上市公司董事会、战略与可持续发展委员会，以及与正泰集团、正泰电源、正泰安能等关联主体的治理联系；完整部门设置和汇报关系需内部/访谈补齐", "部门设置、汇报关系", ["S1"]),
                    _org_row("决策层级", "建议按集团/上市公司高层、事业部/子公司经营层、采购/技术/生产/服务团队三层决策链管理；具体采购授权层级未公开", "决策流程有几级", ["S1"]),
                    _org_row("关键部门", "公开资料无法确认具体采购部、技术部、生产部、销售部负责人；建议优先建立采购、技术/质量、生产/服务、行业/海外项目团队联系人地图", "采购部、技术部、生产部、销售部", ["S1"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "董事长为南存辉；高层沟通宜围绕全球化、绿色低碳、能源安全、本土制造和数字化效率展开。总经理/业务单元经营负责人需进一步核验", "姓名、背景、管理风格", ["S1"]),
                    _org_row("采购负责人", "公开资料未披露采购负责人姓名、职位和权限；需从施耐德历史采购、供应商准入和年度框架数据反查", "姓名、职位、决策权限", []),
                    _org_row("技术负责人", "公开资料未披露具体技术负责人；技术沟通应关注海外认证、数据中心可靠配电、储能安全、标准图纸和质量闭环", "姓名、职位、技术偏好", []),
                    _org_row("生产负责人", "公开资料未披露生产负责人；生产侧需核验不同基地的交付、质量、排产和售后责任边界", "姓名、职位、生产管理风格", []),
                    _org_row("销售负责人", "公开资料未披露具体销售负责人；可先按区域/行业/海外项目团队拆分对接，销售中心和渠道负责人需内部补齐", "姓名、职位、市场策略", []),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "待内部核验。建议按需求提出、技术评审、商务比价、质量准入、最终批准五步复盘，并区分常规物料、项目物料和海外认证物料", "谁提议-谁评估-谁批准", []),
                    _org_row("技术选型流程", "需核验技术选型是由终端业主、设计院、总包、正泰技术部门还是海外项目规范主导；施耐德切入点在业主指定、认证和高可靠场景", "技术评审参与方", []),
                    _org_row("决策周期", "公开资料未披露从需求到采购决策的周期；需区分常规采购、项目采购、海外项目采购和业主指定采购", "从需求到采购决策的周期", []),
                    _org_row("决策影响因素", "预计价格、品牌、认证、交期、质量、服务、客户指定和集团协同共同影响；权重需通过赢丢单复盘和关键人访谈确认", "价格/质量/服务/关系等权重", ["S1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "公开资料未披露完整组织架构图；仅能确认企业主体、法人/负责人线索、荣誉资质和项目型业务特征，部门设置与汇报关系需客户访谈补齐", "部门设置、汇报关系", ["ZH1", "ZH5", "ZH14"]),
                    _org_row("决策层级", "推测项目决策随招投标类型变化：业主/设计院规范前置，技术/设计校核，采购/商务比价，总经理或实际经营负责人审批；实际层级待核验", "决策流程有几级", ["ZH2", "ZH3", "ZH4", "ZH5"]),
                    _org_row("关键部门", "建议重点确认技术/设计、采购、项目/销售、生产/质量、售后负责人；平台资料披露其质量管理荣誉但未披露部门负责人和权限边界", "采购部、技术部、生产部、销售部", ["ZH14"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "公开资料仅确认法人/负责人线索王永贵；其具体职务、背景和管理风格需工商底档、客户经理或拜访访谈核验", "姓名、背景、管理风格", ["ZH1", "ZH5"]),
                    _org_row("采购负责人", "公开资料未披露采购负责人；需确认其对价格、账期、交付、竞品替代和年度框架的决策权限", "姓名、职位、决策权限", []),
                    _org_row("技术负责人", "公开资料未披露技术负责人；需确认柜体方案、元器件品牌边界、标准图纸、智能配电需求和品牌替换权", "姓名、职位、技术偏好", []),
                    _org_row("生产负责人", "公开资料未披露生产负责人；需核验高压柜、低压柜、母线槽、桥架、配电箱的排产、质检和交付责任", "姓名、职位、生产管理风格", []),
                    _org_row("销售负责人", "公开资料未披露销售负责人；需确认其区域项目、央企准入、总包关系和招投标策略", "姓名、职位、市场策略", []),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "推测招投标项目由业主/设计院规范前置，总包与采购部门比价，技术部校核品牌和参数，最终由经营负责人或授权人员批准；需访谈确认", "谁提议-谁评估-谁批准", ["ZH3", "ZH4"]),
                    _org_row("技术选型流程", "技术选型可能受业主/设计院规范、总包品牌库、客户技术部和供应商授权共同影响；需确认施耐德是否已进入常规 BOM 或指定品牌清单", "技术评审参与方", ["ZH3", "ZH4", "ZH5"]),
                    _org_row("决策周期", "公开资料未披露决策周期；高压柜/公共事业、化工、住宅改造、母线槽项目周期可能差异较大，需按项目复盘", "从需求到采购决策的周期", []),
                    _org_row("决策影响因素", "预计价格、交期、账期、质量、业主指定、设计院规范、本地服务和项目履约风险共同影响；权重需通过赢丢单复盘确认", "价格/质量/服务/关系等权重", ["ZH3", "ZH4", "ZH5"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "中国电气装备/许继体系内企业；公开报道显示天宇推行阿米巴经营，把原两个事业部拆分为 9 个业务单元并公开竞聘业务单元经理；高校就业资料补充其导师制、轮岗和岗位培养机制，完整组织架构图需内部补齐", "部门设置、汇报关系", ["TY1", "TY8", "TY15"]),
                    _org_row("决策层级", "建议按董事长/总经理层、业务单元经理、技术/设计、采购/供应链、质量/生产/服务五类节点管理；集团供应链和年度物料清单可能影响外部品牌准入", "决策流程有几级", ["TY1", "TY6", "TY8"]),
                    _org_row("关键部门", "关键部门包括 9 个业务单元、技术/设计、采购/供应链、生产/质量/服务、销售/项目团队；高校就业资料显示招聘电气、机械、工艺、质检、设备、信息运维等岗位，具体负责人和审批权限未公开", "采购部、技术部、生产部、销售部", ["TY1", "TY6", "TY15"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "张红彬为法定代表人/董事长线索，并在集团报道中作为天宇经营改革和战略目标的核心发声人；适合作为高层关系重点对象", "姓名、背景、管理风格", ["TY1", "TY3"]),
                    _org_row("采购负责人", "公开资料未披露采购负责人；需确认年度中标物料清单、供应商准入、价格、账期和交付承诺的审批权限", "姓名、职位、决策权限", ["TY6"]),
                    _org_row("技术负责人", "公开资料未披露技术负责人；低压柜岗位显示技术侧参与方案优化、报价审核和项目元器件型号确认，是施耐德标准 BOM 切入关键", "姓名、职位、技术偏好", ["TY6"]),
                    _org_row("生产负责人", "公开资料未披露生产负责人；智能制造升级和质量攻坚线索显示生产/质量负责人需重点沟通交付、出厂检验和质量闭环", "姓名、职位、生产管理风格", ["TY1", "TY2"]),
                    _org_row("销售负责人", "公开资料未披露销售负责人；业务单元经理和金牌营销员机制表明销售/经营责任下沉，需按行业项目确认实际负责人", "姓名、职位、市场策略", ["TY1"]),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "基于公开岗位职责，项目/销售获取招标文件和业主规范，技术部门做方案优化与元器件型号确认，采购/供应链按年度中标物料、价格、交期和准入执行，业务单元对利润、回款、质量、交付负责", "谁提议-谁评估-谁批准", ["TY1", "TY6"]),
                    _org_row("技术选型流程", "低压柜设计岗位负责前端方案优化、报价审核，并根据年度中标物料供应商确认项目元器件型号；非指定且不在年度招标范围内的元器件需提请招标", "技术评审参与方", ["TY6"]),
                    _org_row("决策周期", "公开资料未披露从需求到采购决策周期；大型项目可能受招标节点、年度物料准入和项目交期影响，引江济淮项目交货期覆盖 2025 年 3 月至 2026 年 6 月", "从需求到采购决策的周期", ["TY4"]),
                    _org_row("决策影响因素", "年度中标物料清单、业主指定、价格/成本、交期、质量、售后、集团供应链协同和业务单元利润共同影响；施耐德需前移到准入和技术标准环节", "价格/质量/服务/关系等权重", ["TY1", "TY6"]),
                ],
            },
        ]
    return [
        {
            "category": "组织架构",
            "rows": [
                _org_row("公司组织架构图", "待核验", "部门设置、汇报关系", []),
                _org_row("决策层级", "待核验", "决策流程有几级", []),
                _org_row("关键部门", "待核验", "采购部、技术部、生产部、销售部", []),
            ],
        },
        {
            "category": "关键决策人",
            "rows": [
                _org_row("董事长/总经理", "待核验", "姓名、背景、管理风格", []),
                _org_row("采购负责人", "待核验", "姓名、职位、决策权限", []),
                _org_row("技术负责人", "待核验", "姓名、职位、技术偏好", []),
                _org_row("生产负责人", "待核验", "姓名、职位、生产管理风格", []),
                _org_row("销售负责人", "待核验", "姓名、职位、市场策略", []),
            ],
        },
        {
            "category": "决策流程",
            "rows": [
                _org_row("采购决策流程", "待核验", "谁提议-谁评估-谁批准", []),
                _org_row("技术选型流程", "待核验", "技术评审参与方", []),
                _org_row("决策周期", "待核验", "从需求到采购决策的周期", []),
                _org_row("决策影响因素", "待核验", "价格/质量/服务/关系等权重", []),
            ],
        },
    ]


def _org_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_strategy_needs(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "战略方向",
                "rows": [
                    _strategy_row("短期目标", "围绕智慧电器与绿色能源两大主线推进，智慧电器强调“区域、行业、产品”三位一体营销、全球区域本土化、数智互联平台和关键应用技术；券商研报也将低压电器稳步增长和新能源增量作为观察重点", "1-2年内的发展目标", ["S1", "S10"]),
                    _strategy_row("中长期规划", "未来 3-5 年方向可归纳为全球区域本土化、新型电力系统、数字化平台、轻资产和平台化、高端行业突破；证券研究视角支持从低压电器+新能源双主线跟踪机会", "3-5年发展战略", ["S1", "S10"]),
                    _strategy_row("业务扩张计划", "围绕风光储充、数据中心、轨交、智能配电、光储直柔、户用光伏、电站运营、逆变器储能和综合能源服务扩张", "是否计划拓展新业务领域", ["S1"]),
                    _strategy_row("区域扩张计划", "在重点国家推进制造、研发、供应链和服务闭环；海外拓展欧洲、亚太、西亚非、拉美、北美等市场，北美聚焦数据中心项目", "是否计划拓展新市场区域", ["S1", "S3"]),
                ],
            },
            {
                "category": "数字化转型",
                "rows": [
                    _strategy_row("数字化现状", "已有数字化车间、智能质控、能源数字化平台和智慧运维能力；“泰无界”平台覆盖智慧配电、微电网、运维和能源数智运营，服务侧还具备官网、微信公众号、小程序等触点", "ERP/MES/CRM等系统使用情况", ["S1", "S3", "S12"]),
                    _strategy_row("数字化需求", "需要围绕协议开放、数据互通、国际业主标准合规、智慧配电、微电网和能源运维增强互联互通，施耐德可做互补型方案而非简单平台替代", "对数字化工厂、智能生产的需求", ["S1"]),
                    _strategy_row("数字化预算", "公开资料未披露年度数字化转型预算；官网披露正泰电器累计投入超过 23 亿元推进智能制造，可作为投入意愿侧影", "数字化转型投入预算", ["S3"]),
                ],
            },
            {
                "category": "绿色低碳",
                "rows": [
                    _strategy_row("双碳目标", "年报披露公司成立碳达峰碳中和工作领导小组，并通过“绿色能源系统+各类用能场景”推进产业融合", "是否制定碳减排目标", ["S1"]),
                    _strategy_row("绿色产品需求", "绿色能源业务覆盖户用光伏、光伏电站、逆变器与储能、综合能源服务，对微电网、储能安全、能效管理和低碳园区有显性需求", "对环保型产品的需求", ["S1"]),
                    _strategy_row("ESG评级", "公开年报披露 ESG/可持续发展相关治理和实践，但本项目未摘录第三方 ESG 评级；需补查评级机构或 ESG 报告", "企业ESG评级情况", ["S1"]),
                ],
            },
            {
                "category": "电气升级需求",
                "rows": [
                    _strategy_row("智能配电需求", "显性需求包括智能配电、微电网、储能、光储充、弱电网适应、数据中心高可靠配电、轨交认证、海外认证和能源运维", "对智能配电柜、物联网的需求", ["S1"]),
                    _strategy_row("能效管理需求", "针对正泰工厂、海外制造基地、数据中心和共同客户项目，可提出能效诊断、配电监测、关键配电可靠性、微电网和光储充一体化试点", "对能耗监测、节能改造的需求", ["S1", "S3"]),
                    _strategy_row("设备更新需求", "公开资料未披露现有设备更新换代计划、预算和优先厂区；建议围绕乐清基地、海外制造基地和数据中心相关项目访谈核验", "现有设备更新换代计划", []),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "战略方向",
                "rows": [
                    _strategy_row("短期目标", "正式战略未公开；对施耐德而言，短期应先核验授权状态、近三年采购额、项目行业分布和竞品替代情况，并建立项目机会池", "1-2年内的发展目标", []),
                    _strategy_row("中长期规划", "推测重点为巩固桥架、母线槽、开关柜、配电箱等工程项目型业务，扩大跨省招投标和央企/国企供应商准入，并借助高新技术企业、守合同重信用和AAA资信荣誉提升技术与信用背书", "3-5年发展战略", ["ZH2", "ZH6", "ZH14"]),
                    _strategy_row("业务扩张计划", "经营和项目线索指向光伏变电站设备、风电母线、抗震支吊架、综合支吊架、地铁预埋槽道等新场景扩展", "是否计划拓展新业务领域", ["ZH2"]),
                    _strategy_row("区域扩张计划", "公开项目线索已跨山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地；是否有明确区域扩张计划需客户访谈核验", "是否计划拓展新市场区域", ["ZH2", "ZH3"]),
                ],
            },
            {
                "category": "数字化转型",
                "rows": [
                    _strategy_row("数字化现状", "公开资料未披露 ERP/MES/CRM、数字化工厂或智能生产系统使用情况；已知质量管理荣誉说明具备规范化管理基础，但数字系统需现场走访或客户访谈核验", "ERP/MES/CRM等系统使用情况", ["ZH14"]),
                    _strategy_row("数字化需求", "结合项目类型，可优先切入智能配电监控、能效管理和 EcoFit 改造，面向供热、化工、住宅改造、公共建筑项目形成标准方案", "对数字化工厂、智能生产的需求", ["ZH3"]),
                    _strategy_row("数字化预算", "公开资料未披露数字化转型预算，需通过项目计划、技改预算、设备采购和客户访谈补齐", "数字化转型投入预算", []),
                ],
            },
            {
                "category": "绿色低碳",
                "rows": [
                    _strategy_row("双碳目标", "公开资料未披露企业碳减排目标或双碳路线图，需客户访谈或 ESG/环保资料补查", "是否制定碳减排目标", []),
                    _strategy_row("绿色产品需求", "可围绕公共设施和工业客户节能改造、光伏/风电/电建项目配电可靠性、化工和住宅改造中的能效监测形成绿色方案切入", "对环保型产品的需求", ["ZH2", "ZH3"]),
                    _strategy_row("ESG评级", "公开资料未披露 ESG 评级，需补查第三方评级、信用报告或客户提供的 ESG/社会责任资料", "企业ESG评级情况", []),
                ],
            },
            {
                "category": "电气升级需求",
                "rows": [
                    _strategy_row("智能配电需求", "高低压柜项目、公共设施、化工、住宅改造和轨交场景中存在智能仪表、配电监控、标准 BOM 和品牌指定切入空间", "对智能配电柜、物联网的需求", ["ZH3", "ZH4"]),
                    _strategy_row("能效管理需求", "工业客户和公共设施节能改造、供热锅炉、化工污水、居民小区供配电改造等项目适合引入能耗监测和能效管理", "对能耗监测、节能改造的需求", ["ZH3"]),
                    _strategy_row("设备更新需求", "老旧配电柜、配电箱更新和存量设备替换可用 EcoFit 改造切入；具体设备更新计划需从项目库和客户访谈补齐", "现有设备更新换代计划", []),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "战略方向",
                "rows": [
                    _strategy_row("短期目标", "2025 年新签合同 30 多亿元、收入近 23 亿元、利润 1.6 亿元；短期重点在订单增长、质量修复、组织效率和重点行业项目交付", "1-2年内的发展目标", ["TY1"]),
                    _strategy_row("中长期规划", "集团报道提出“十五五”末实现订货 75 亿元、收入 50 亿元、利润 6 亿元，未来 3-5 年将继续扩大市场、产能、质量和组织效率", "3-5年发展战略", ["TY1"]),
                    _strategy_row("业务扩张计划", "做强做大变压器、箱变、高低压柜，并面向新能源、储能、光伏、锂电、化工、钢铁、水利等项目提升行业方案能力；历史资料显示其具备35kV及以下高低压柜、10kV及以下组合变压器等研发制造基础", "是否计划拓展新业务领域", ["TY1", "TY4", "TY5", "TY15"]),
                    _strategy_row("区域扩张计划", "项目线索覆盖福建、安徽、天津、山西、广西、四川、云南、河南等，并出口 20+ 国家和地区；区域扩张节奏需结合订单库核验", "是否计划拓展新市场区域", ["TY4", "TY5", "TY6", "TY15"]),
                ],
            },
            {
                "category": "数字化转型",
                "rows": [
                    _strategy_row("数字化现状", "MOM 平台覆盖销售、设计、排产、采购、供应链、仓储、生产全过程，并打通 SAP/MES/WMS/SRM，实现数据共享、实时统计与分析", "ERP/MES/CRM等系统使用情况", ["TY2"]),
                    _strategy_row("数字化需求", "需要围绕智能制造扩产提供工厂配电可靠性、能耗监测、配电资产管理、预测性维护，以及项目端智能配电监控和通信运维能力", "对数字化工厂、智能生产的需求", ["TY2", "TY7"]),
                    _strategy_row("数字化预算", "公开资料未披露数字化转型预算；智能制造工厂整体升级改造环评线索说明存在持续技改投入，具体预算需客户访谈核验", "数字化转型投入预算", ["TY7"]),
                ],
            },
            {
                "category": "绿色低碳",
                "rows": [
                    _strategy_row("双碳目标", "公开资料未披露公司层面碳减排目标；但绿色制造和环保绩效改善线索明确，需访谈确认是否有集团双碳指标下达", "是否制定碳减排目标", ["TY2", "TY8"]),
                    _strategy_row("绿色产品需求", "表面处理线采用沸石转轮+RTO 蓄热燃烧等技术，环保绩效达到国家 A 级水平；新能源、储能、光伏项目和绿色制造场景带来绿色配电需求", "对环保型产品的需求", ["TY2", "TY4", "TY5"]),
                    _strategy_row("ESG评级", "许继集团官网已披露福州天宇电气2024年ESG报告入口，可作为绿色低碳、治理和合规资料补充；第三方ESG评级仍需继续补查", "企业ESG评级情况", ["TY8", "TY11"]),
                ],
            },
            {
                "category": "电气升级需求",
                "rows": [
                    _strategy_row("智能配电需求", "低压柜/配电柜/控制柜设计、高可靠供电项目、箱变和低压柜项目可升级为带监控、通信、运维服务的智能配电方案", "对智能配电柜、物联网的需求", ["TY4", "TY5", "TY6"]),
                    _strategy_row("能效管理需求", "智能工厂扩产、喷涂、焊接、试验、仓储物流等高耗能环节适合引入能源可视化、能效诊断和配电资产管理", "对能耗监测、节能改造的需求", ["TY2", "TY7"]),
                    _strategy_row("设备更新需求", "智能制造工厂整体升级改造、自动化设备和低压柜标准化 BOM 带来断路器、接触器、变频器、软启动、电能质量治理等升级机会", "现有设备更新换代计划", ["TY2", "TY6", "TY7"]),
                ],
            },
        ]
    return [
        {
            "category": "战略方向",
            "rows": [
                _strategy_row("短期目标", "待核验", "1-2年内的发展目标", []),
                _strategy_row("中长期规划", "待核验", "3-5年发展战略", []),
                _strategy_row("业务扩张计划", "待核验", "是否计划拓展新业务领域", []),
                _strategy_row("区域扩张计划", "待核验", "是否计划拓展新市场区域", []),
            ],
        },
        {
            "category": "数字化转型",
            "rows": [
                _strategy_row("数字化现状", "待核验", "ERP/MES/CRM等系统使用情况", []),
                _strategy_row("数字化需求", "待核验", "对数字化工厂、智能生产的需求", []),
                _strategy_row("数字化预算", "待核验", "数字化转型投入预算", []),
            ],
        },
        {
            "category": "绿色低碳",
            "rows": [
                _strategy_row("双碳目标", "待核验", "是否制定碳减排目标", []),
                _strategy_row("绿色产品需求", "待核验", "对环保型产品的需求", []),
                _strategy_row("ESG评级", "待核验", "企业ESG评级情况", []),
            ],
        },
        {
            "category": "电气升级需求",
            "rows": [
                _strategy_row("智能配电需求", "待核验", "对智能配电柜、物联网的需求", []),
                _strategy_row("能效管理需求", "待核验", "对能耗监测、节能改造的需求", []),
                _strategy_row("设备更新需求", "待核验", "现有设备更新换代计划", []),
            ],
        },
    ]


def _strategy_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_pain_opportunities(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "业务痛点",
                "rows": [
                    _pain_row("生产效率痛点", "海外、数据中心、储能等项目复杂度提升，叠加主要基地劳动力成本和供给压力，项目设计、装配、调试和交付效率需要继续提升", "用标准化选型、数字化调试、装配培训和快速备件响应降低工程人力消耗", "生产过程中效率低下的环节", ["S1"]),
                    _pain_row("质量管控痛点", "公开资料未披露质量问题频发点；但高端终端客户、海外认证、储能安全和数据中心可靠性要求持续提升，质量闭环需聚焦关键场景；官网质量信用资料显示其在客服与回访闭环上持续建设", "提供出厂测试清单、装配工艺培训、现场服务复盘和高可靠元器件组合", "质量问题的频发点", ["S1", "S3", "S12"]),
                    _pain_row("供应链痛点", "铜、银、钢材、塑料等原材料成本占低压业务成本比重高，海外监管、关税、原产地规则和地缘风险也影响跨境项目交付", "建立框架协议、替代选型、保供计划和海外认证/服务支持机制", "供货、库存、物流等问题", ["S1"]),
                    _pain_row("人才痛点", "年报提示生产基地劳动力成本与供给紧平衡；新能源、储能、微电网和海外认证场景也需要复合型技术与项目人才", "用技术日、认证培训、选型工具和标准 BOM 降低对个别专家的依赖", "人才招聘、培养、流失问题", ["S1"]),
                ],
            },
            {
                "category": "技术痛点",
                "rows": [
                    _pain_row("设计能力痛点", "数据中心、储能、微电网、光储充和海外项目对跨标准设计、保护配合、通信互联和认证合规要求更高", "共建行业标准图纸库、选型库和海外/数据中心/储能标准方案", "设计效率、标准化程度问题", ["S1"]),
                    _pain_row("技术成本痛点", "低压业务原材料成本占比高，自有品牌具备价格和规模优势，高端外部元器件必须证明全生命周期价值", "用 TCO、能效收益、减少返工、缩短调试周期和降低故障风险来解释施耐德价值", "成本优化能力不足", ["S1"]),
                    _pain_row("技术人才痛点", "公开资料未披露具体技术能力缺口；弱电网适应、储能并网、海外认证和数字化运维需要跨领域能力", "面向技术、质量、生产团队做认证培训、保护配合培训和数字化运维工作坊", "技术人员能力不足", ["S1"]),
                ],
            },
            {
                "category": "市场痛点",
                "rows": [
                    _pain_row("市场竞争压力", "年报将市场竞争列为风险，国际企业占据高端市场，国内企业在中端/大众市场差异化竞争，常规低压价格敏感", "聚焦高端客户指定、海外认证、关键负载可靠性和服务差异化场景", "来自竞品的压力", ["S1"]),
                    _pain_row("客户需求变化", "客户需求正在升级到光储充、储能、微电网、数据中心高可靠配电、能源运维和数字化管理；券商研究也强调低压电器稳步增长和新能源业务增量", "以智能配电、微电网、能效管理、电能质量和运维服务包进入联合项目", "客户需求升级带来的挑战", ["S1", "S10"]),
                    _pain_row("行业政策变化", "海外监管、关税、原产地规则、地缘风险及新能源政策周期会影响项目选择和交付节奏", "提供目标市场合规、认证、全球服务和本地化交付支持", "政策调整带来的影响", ["S1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "业务痛点",
                "rows": [
                    _pain_row("生产效率痛点", "项目型业务多，产品覆盖开关柜、桥架、母线槽、配电箱、支吊架等，多品类逐单报价和技术沟通容易拉长交付周期", "建立标准报价包、标准 BOM 和授权柜/元器件组合，减少重复选型与沟通", "生产过程中效率低下的环节", ["ZH2", "ZH3"]),
                    _pain_row("质量管控痛点", "公开资料缺少完整检测设备、一次合格率和现场质检流程；但平台披露质量管理和荣誉资质，化工、供热、轨交、电建等场景标准差异仍需重点审核", "用现场审核、出厂检验清单、行业质量模板和服务响应机制做风险分级", "质量问题的频发点", ["ZH3", "ZH4", "ZH5", "ZH14"]),
                    _pain_row("供应链痛点", "扬中电气产业集群供应链成熟但同类供应商密集，项目交付、价格和本地服务会同时影响品牌选择", "提前进入业主/设计院规范，绑定交期、服务、授权和质量闭环形成非价格壁垒", "供货、库存、物流等问题", ["ZH2", "ZH3"]),
                    _pain_row("人才痛点", "公开资料未披露设计、研发、生产和销售人员规模；高新技术企业、荣誉资质和质量管理线索说明有技术与管理基础，但人员结构透明度仍不足", "通过技术日、选型培训和现场审核识别关键人，并将技术能力转化为可复制项目包", "人才招聘、培养、流失问题", ["ZH6", "ZH14"]),
                ],
            },
            {
                "category": "技术痛点",
                "rows": [
                    _pain_row("设计能力痛点", "产品线宽、行业项目差异大，开关柜、母线槽、桥架和配电箱联动设计对图纸标准化提出压力", "共建图纸库、BOM 模板、低压柜/配电箱标准方案和快速替代清单", "设计效率、标准化程度问题", ["ZH1", "ZH2", "ZH3"]),
                    _pain_row("技术成本痛点", "招投标业务技术、商务、资信评分并重，价格竞争强，施耐德若只在采购询价阶段进入容易被低价替代", "以前置规范、TCO、质量风险降低和售后响应证明价值，避免单纯比价", "成本优化能力不足", ["ZH3"]),
                    _pain_row("技术人才痛点", "公开资料未披露技术人员能力结构；多行业项目要求差异大，可能需要更强的行业方案和标准化设计支持", "提供化工、公共建筑、轨交、电建等行业应用包和半天技术训练营", "技术人员能力不足", ["ZH3", "ZH4", "ZH5"]),
                ],
            },
            {
                "category": "市场痛点",
                "rows": [
                    _pain_row("市场竞争压力", "区域同类盘厂、桥架、母线槽厂商密集，项目招投标中价格替代空间大", "锁定业主指定、授权柜型、服务响应和质量闭环，提升非价格竞争力", "来自竞品的压力", ["ZH2", "ZH3"]),
                    _pain_row("客户需求变化", "客户覆盖供热、造纸、化工、住宅改造、轨交和电建等，正从单品供货转向安全、可靠、能效和运维需求", "将低压开关柜、智能仪表、配电监控和能效管理打包成行业方案", "客户需求升级带来的挑战", ["ZH3", "ZH4", "ZH5"]),
                    _pain_row("行业政策变化", "公共资源招投标、央企合格供应商准入和工程项目合规要求会持续影响品牌入围与成交路径", "补齐资质、授权、合规文件和项目业绩包，前置到招标技术规范", "政策调整带来的影响", ["ZH3", "ZH5"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "业务痛点",
                "rows": [
                    _pain_row("生产效率痛点", "2025 年新签合同额 30 多亿元，且“十五五”末订货目标 75 亿元，快速扩张会放大设计、排产、采购和交付压力", "用年度框架、标准 BOM、快速报价和技术支持缩短重大项目交付周期", "生产过程中效率低下的环节", ["TY1", "TY2"]),
                    _pain_row("质量管控痛点", "2018 年曾因质量问题被主要客户拉黑三年，2025 年重大质量事件为零，说明质量修复有效但仍需巩固", "用高可靠元器件、装配指导、出厂检验、现场服务和质量复盘帮助稳定质量口碑", "质量问题的频发点", ["TY1"]),
                    _pain_row("供应链痛点", "岗位职责显示存在年度中标物料供应商和非指定元器件提请招标机制，集团内部供应链协同也会影响外部品牌进入", "优先推动施耐德进入年度合格/中标物料清单，并绑定业主指定和项目规范", "供货、库存、物流等问题", ["TY6", "TY8"]),
                    _pain_row("人才痛点", "快速经营改善、阿米巴经营、金牌营销员、低压柜设计岗位和校园招聘培养机制表明人才能力要跟上订单扩张与项目复杂度", "面向采购、技术、低压柜设计和项目团队做选型、标准 BOM、调试和质量培训", "人才招聘、培养、流失问题", ["TY1", "TY6", "TY15"]),
                ],
            },
            {
                "category": "技术痛点",
                "rows": [
                    _pain_row("设计能力痛点", "低压柜设计岗位覆盖前端方案优化、报价审核和元器件型号确认，年度物料清单机制会影响设计效率与标准化", "共建低压柜标准 BOM、选型工具、元件替代清单和行业方案模板", "设计效率、标准化程度问题", ["TY6"]),
                    _pain_row("技术成本痛点", "2024 年营收 12.34 亿元、净利润 0.13 亿元，成本和盈利压力明显，施耐德方案必须解释价值而不只是高单价", "用全生命周期成本、减少返工、缩短调试周期和降低故障损失来证明收益", "成本优化能力不足", ["TY3"]),
                    _pain_row("技术人才痛点", "新产品研制、智能制造升级、低压柜设计和多行业项目要求提升，对技术团队跨专业能力提出更高要求；校园招聘资料显示电气、机械、工艺、质检、设备、信息运维等岗位培养需求", "开展 GB7251/GB14048、智能配电、通信网关、能效管理和项目调试培训", "技术人员能力不足", ["TY1", "TY2", "TY6", "TY15"]),
                ],
            },
            {
                "category": "市场痛点",
                "rows": [
                    _pain_row("市场竞争压力", "天宇处于中国电气装备/许继体系内，外部品牌既面对集团内部产品协同，也面对 ABB、西门子、伊顿、正泰等竞品", "聚焦业主指定、国际项目、高可靠场景和智能化服务，避开纯价格竞争", "来自竞品的压力", ["TY6", "TY8"]),
                    _pain_row("客户需求变化", "项目覆盖水利、新能源、煤化工、钢铁、锂电前驱体、渔光互补、增量配电网和 110kV 变电站等，对可靠供电、智能监测和能效升级需求提高", "形成新能源升压站、锂电材料、煤化工/钢铁、水利泵站等行业标准方案", "客户需求升级带来的挑战", ["TY4", "TY5", "TY6"]),
                    _pain_row("行业政策变化", "国资采购、集团供应链、工程招投标、环保审批和智能制造扩产政策会影响外部品牌准入与项目节奏", "准备准入资料、授权文件、合规证明、环保/能效价值材料，并前置到集团和项目规范", "政策调整带来的影响", ["TY3", "TY7", "TY8"]),
                ],
            },
        ]
    return [
        {
            "category": "业务痛点",
            "rows": [
                _pain_row("生产效率痛点", "待核验", "待补充施耐德机会", "生产过程中效率低下的环节", []),
                _pain_row("质量管控痛点", "待核验", "待补充施耐德机会", "质量问题的频发点", []),
                _pain_row("供应链痛点", "待核验", "待补充施耐德机会", "供货、库存、物流等问题", []),
                _pain_row("人才痛点", "待核验", "待补充施耐德机会", "人才招聘、培养、流失问题", []),
            ],
        },
        {
            "category": "技术痛点",
            "rows": [
                _pain_row("设计能力痛点", "待核验", "待补充施耐德机会", "设计效率、标准化程度问题", []),
                _pain_row("技术成本痛点", "待核验", "待补充施耐德机会", "成本优化能力不足", []),
                _pain_row("技术人才痛点", "待核验", "待补充施耐德机会", "技术人员能力不足", []),
            ],
        },
        {
            "category": "市场痛点",
            "rows": [
                _pain_row("市场竞争压力", "待核验", "待补充施耐德机会", "来自竞品的压力", []),
                _pain_row("客户需求变化", "待核验", "待补充施耐德机会", "客户需求升级带来的挑战", []),
                _pain_row("行业政策变化", "待核验", "待补充施耐德机会", "政策调整带来的影响", []),
            ],
        },
    ]


def _pain_row(field_name: str, pain: str, opportunity: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": pain,
        "pain": pain,
        "opportunity": opportunity,
        "description": description,
        "source_ids": source_ids,
    }


def _customer_risk_assessment(customer: str) -> list[dict[str, Any]]:
    if _is_chint_customer(customer):
        return [
            {
                "category": "经营风险",
                "rows": [
                    _risk_assessment_row("财务风险", "整体经营稳健，但 2025 年资产负债率约 66.13%，较 2024 年约 63.28% 上升；光伏业务收入同比下降 15.62%，光伏电站工程承包收入同比下降 35.04%，需关注资金、负债和周期波动", "资金链、负债、回款风险", ["S1"]),
                    _risk_assessment_row("法律风险", "2025 年报披露近三年受证券监管机构处罚情况为不适用，本年度无重大诉讼、仲裁事项；公司、控股股东和实际控制人诚信状况良好，上市公司层面公开合规风险较低", "诉讼、行政处罚记录", ["S1"]),
                    _risk_assessment_row("经营稳定性", "正泰电器具备规模、渠道和多业务基础，但需关注光伏周期、海外监管/关税/地缘风险及客户集中度；前五名客户销售额占 38.64%，未出现单一客户超过 50%", "是否存在经营异常", ["S1"]),
                ],
            },
            {
                "category": "信用风险",
                "rows": [
                    _risk_assessment_row("付款信用", "公开资料未披露其对施耐德历史付款是否准时；需按正泰电器本部及关联主体分别查询施耐德应收账款、账期、逾期、授信额度和回款争议", "历史付款是否准时", []),
                    _risk_assessment_row("合同履约", "公开资料未发现施耐德相关合同履约争议；上市公司年报披露本年度无重大诉讼仲裁，但具体采购合同履约仍需施耐德订单、交付和验收记录核验", "合同履约情况", ["S1"]),
                    _risk_assessment_row("售后纠纷", "公开资料未披露与施耐德相关售后纠纷、质量索赔或服务争议；官网质量信用资料显示其建设客服热线、官网、微信公众号、小程序等服务闭环，但施耐德侧仍需用服务工单、投诉、备件、现场响应和质量闭环记录补齐", "售后问题处理情况", ["S12"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "经营风险",
                "rows": [
                    _risk_assessment_row("财务风险", "公开资料未显示财务报表、负债率、现金流和利润情况；非上市企业信息透明度较低，项目型招投标、总包和工程项目可能存在账期长、回款节奏慢的问题", "资金链、负债、回款风险", ["ZH3"]),
                    _risk_assessment_row("法律风险", "本轮公开资料未形成重大诉讼、行政处罚、经营异常的充分证据结论；由于公开渠道有限，不能据此判断无风险，仍需补查国家企业信用信息公示系统、裁判文书、执行信息和信用中国", "诉讼、行政处罚记录", []),
                    _risk_assessment_row("经营稳定性", "经营范围和公开项目覆盖开关柜、桥架、母线槽、配电箱等多品类，多行业交付标准差异较大；守合同重信用、AAA资信和质量管理荣誉可作为信用侧正面线索，但同区域同类厂商较多，价格竞争和交付稳定性仍需重点核验", "是否存在经营异常", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH13", "ZH14"]),
                ],
            },
            {
                "category": "信用风险",
                "rows": [
                    _risk_assessment_row("付款信用", "公开资料未披露付款信用、授信额度和历史账期；需由施耐德内部系统补齐应收、逾期、授信、回款争议和项目客户编码", "历史付款是否准时", []),
                    _risk_assessment_row("合同履约", "公开项目显示其具备候选/供应商准入线索，守合同重信用、AAA资信和质量管理荣誉提供履约信用侧正面线索，但仍未披露完整项目履约评价；需核验招投标黑名单、供应商处罚、项目验收、准时交付和质量整改记录", "合同履约情况", ["ZH3", "ZH4", "ZH5", "ZH13", "ZH14"]),
                    _risk_assessment_row("售后纠纷", "公开资料未披露与施耐德产品装配、调试、售后相关的历史问题；需调取施耐德服务工单、质量投诉、现场整改和售后纠纷记录", "售后问题处理情况", []),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "经营风险",
                "rows": [
                    _risk_assessment_row("财务风险", "2024 年公开财务显示收入 12.34 亿元、净利润 0.13 亿元，净利率偏低；2025 年集团报道显示收入近 23 亿元、利润 1.6 亿元，改善明显；深交所关联交易公告可作为历史财务与交易口径的补充交叉验证", "资金链、负债、回款风险", ["TY1", "TY3", "TY13"]),
                    _risk_assessment_row("法律风险", "许继电气公告称天宇电气不是失信被执行人；公开资料未发现重大诉讼、重大处罚或失信风险线索；ESG报告入口和环评公示可继续用于环保合规复核，扩产和表面处理环节需持续关注", "诉讼、行政处罚记录", ["TY3", "TY7", "TY11", "TY13"]),
                    _risk_assessment_row("经营稳定性", "天宇背靠中国电气装备/许继体系，集团支撑较强，历史资料显示其具备国家重点工程和出口项目基础；但快速扩张、集团内部协同、历史质量修复和低价中标压力可能影响项目交付与外部品牌合作边界", "是否存在经营异常", ["TY1", "TY8", "TY15"]),
                ],
            },
            {
                "category": "信用风险",
                "rows": [
                    _risk_assessment_row("付款信用", "公开资料未披露其对施耐德历史付款、逾期、争议和授信情况；国资和集团采购规则可能影响付款流程，需施耐德内部信用记录和合同台账核验", "历史付款是否准时", ["TY3", "TY8"]),
                    _risk_assessment_row("合同履约", "公开项目线索覆盖引江济淮、绿色能源基地等大型项目，历史资料覆盖南水北调、核电、三峡、北京奥运、上海世博等工程，低压柜设计岗位也显示年度物料和项目招采机制；需按重大项目核验交付周期、验收、合同变更和集团集采履约评价", "合同履约情况", ["TY4", "TY5", "TY6", "TY15"]),
                    _risk_assessment_row("售后纠纷", "2018 年曾因质量问题被主要客户拉黑三年，2025 年重大质量事件为零，说明质量改善明显但仍需跟踪；施耐德侧需核验项目售后投诉、质量索赔、现场事故或技术争议", "售后问题处理情况", ["TY1"]),
                ],
            },
        ]
    return [
        {
            "category": "经营风险",
            "rows": [
                _risk_assessment_row("财务风险", "待核验", "资金链、负债、回款风险", []),
                _risk_assessment_row("法律风险", "待核验", "诉讼、行政处罚记录", []),
                _risk_assessment_row("经营稳定性", "待核验", "是否存在经营异常", []),
            ],
        },
        {
            "category": "信用风险",
            "rows": [
                _risk_assessment_row("付款信用", "待核验", "历史付款是否准时", []),
                _risk_assessment_row("合同履约", "待核验", "合同履约情况", []),
                _risk_assessment_row("售后纠纷", "待核验", "售后问题处理情况", []),
            ],
        },
    ]


def _risk_assessment_row(field_name: str, value: str, description: str, source_ids: list[str]) -> dict[str, Any]:
    return {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }


def _portrait_top_opportunities(opportunities: list[dict[str, str]]) -> list[str]:
    values: list[str] = []
    for item in opportunities[:3]:
        title = item.get("机会主题") or item.get("目标") or ""
        action = item.get("下一步动作") or item.get("推荐方案") or item.get("推荐切入方案") or ""
        if title and action:
            values.append(f"{title}：{action}")
        elif title:
            values.append(title)
    return values


def _ensure_report_docx(project: CustomerProject) -> Path | None:
    report_path = Path(project.report_path) if project.report_path else None
    if not report_path or not report_path.exists():
        return None
    word_path = Path(project.word_report_path) if project.word_report_path else report_path.with_suffix(".docx")
    writer_path = Path(__file__).with_name("docx_writer.py")
    citations_path = Path(__file__).with_name("citations.py")
    source_registry_path = Path(project.source_registry_path) if project.source_registry_path else None
    source_mtimes = [report_path.stat().st_mtime, writer_path.stat().st_mtime, citations_path.stat().st_mtime]
    if source_registry_path and source_registry_path.exists():
        source_mtimes.append(source_registry_path.stat().st_mtime)
    newest_source_mtime = max(source_mtimes)
    if not word_path.exists() or word_path.stat().st_mtime < newest_source_mtime:
        source_registry = source_registry_path.read_text(encoding="utf-8") if source_registry_path and source_registry_path.exists() else ""
        write_docx_from_markdown(report_path.read_text(encoding="utf-8"), word_path, source_registry_markdown=source_registry)
    project.word_report_path = str(word_path)
    return word_path


def _attachment_header(filename: str) -> str:
    ascii_name = re.sub(r"[^0-9A-Za-z_.-]+", "_", filename).strip("_") or "download"
    if ascii_name.startswith(".") or "." not in ascii_name:
        suffix = Path(filename).suffix or ".bin"
        ascii_name = f"download{suffix}"
    return f"attachment; filename={ascii_name}; filename*=UTF-8''{quote(filename)}"


def _content_type(filename: str) -> str:
    if filename.endswith(".html"):
        return "text/html; charset=utf-8"
    if filename.endswith(".css"):
        return "text/css; charset=utf-8"
    if filename.endswith(".js"):
        return "text/javascript; charset=utf-8"
    if filename.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"
