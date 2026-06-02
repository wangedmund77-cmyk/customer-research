"""Local web interface for switchgear enterprise insight projects."""

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
from .petrochem_ka_data import PETROCHEM_TAGGING_SOURCES, find_petrochem_ka
from .report_writer import slugify_customer_name, write_customer_project


ROOT_DIR = Path.cwd()
STATIC_DIR = Path(__file__).with_name("static")
WEB_OUTPUT_DIR = ROOT_DIR / "outputs" / "switchgear_customer_web"
CHINT_REPORT_PATH = ROOT_DIR / "outputs" / "chint_electric_2026" / "浙江正泰电器股份有限公司_深度企业洞察报告.md"
CHINT_SOURCE_PATH = ROOT_DIR / "outputs" / "chint_electric_2026" / "source_registry.md"
ZHONGHUAN_REPORT_PATH = ROOT_DIR / "outputs" / "zhonghuan_electric_2026" / "江苏中环电气集团有限公司_深度企业洞察报告.md"
ZHONGHUAN_SOURCE_PATH = ROOT_DIR / "outputs" / "zhonghuan_electric_2026" / "source_registry.md"
TIANYU_REPORT_PATH = ROOT_DIR / "outputs" / "tianyu_electric_2026" / "福州天宇电气股份有限公司_深度企业洞察报告.md"
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
    print(f"盘厂企业洞察研究工作台已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务。")
    finally:
        server.server_close()


class CustomerInsightRequestHandler(SimpleHTTPRequestHandler):
    server_version = "SwitchgearEnterpriseInsight/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature.
        print(f"[enterprise-web] {self.address_string()} - {format % args}")

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
            self._json({"error": "企业名称不能为空。"}, status=400)
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
            filename = f"{slugify_customer_name(project.customer)}_深度企业洞察报告.docx"
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
    project.logs.append("已生成企业洞察研究项目基础文件。")

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
    elif petrochem_data := find_petrochem_ka(customer):
        source_registry_path = output_dir / "source_registry.md"
        source_registry_path.write_text(_petrochem_source_registry_markdown(petrochem_data), encoding="utf-8")
        report_path.write_text(_petrochem_report_markdown(customer, petrochem_data), encoding="utf-8")
        project.source_registry_path = str(source_registry_path)
        project.logs.append(f"已载入{petrochem_data['name']}石化/化工 KA 初版洞察画像。")
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


def _petrochem_source_registry_markdown(data: dict[str, Any]) -> str:
    lines = [
        f"# {data['name']}企业洞察来源登记",
        "",
        "| 编号 | 来源 | 发布方/载体 | 日期 | 链接 | 主要用途 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    seen: set[str] = set()
    for source in [*data.get("sources", []), *PETROCHEM_TAGGING_SOURCES]:
        source_id = str(source.get("id", ""))
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        lines.append(
            "| {id} | {title} | {publisher} | {date} | {url} | {purpose} |".format(
                id=source_id,
                title=source.get("title", ""),
                publisher=source.get("publisher", ""),
                date=source.get("date", ""),
                url=source.get("url", ""),
                purpose=source.get("purpose", ""),
            )
        )
    return "\n".join(lines) + "\n"


def _petrochem_report_markdown(customer: str, data: dict[str, Any]) -> str:
    profile = data["profile"]
    facts = data["facts"]
    source_ids = _petrochem_source_ids(data)
    tagging = _project_tagging_model(customer)
    first_citation = _petrochem_citation(source_ids[:2])
    rows = _structured_field_lookup(customer)
    lines = [
        f"# {customer}深度企业洞察报告",
        "",
        "## 高层摘要",
        "",
        (
            f"{profile['short_name']}属于{profile['account_type']}，公开资料显示其业务重心为{facts['business']}。"
            f"对施耐德而言，优先经营主题是{profile['recommended_focus']}。"
            f"当前画像基于企业官网、上市公告、政府网站和行业权威报道形成，施耐德内部采购、授权、满意度、信用和关键人信息仍需补齐。{first_citation}"
        ),
        "",
        "## 施耐德业务机会地图",
        "",
        "| 优先级 | 机会主题 | 推荐切入方案 | 下一步动作 | 依据 |",
        "| --- | --- | --- | --- | --- |",
        f"| P1 | 关键装置供配电可靠性 | 中低压配电、MCC、变频、保护与电能质量包 | 锁定重点基地/项目，做一次电气资产健康度访谈 | {facts['projects']} {_petrochem_citation(source_ids[:2])} |",
        f"| P1 | 数字化与能效管理 | EcoStruxure Power、能源可视化、配电监控、预测维护 | 以公辅、变电所、MCC室和高耗能装置做场景清单 | {facts['digital']} {_petrochem_citation(source_ids[1:3])} |",
        f"| P2 | 绿色低碳与ESG | 能源管理、碳数据、绿色工厂改造和服务包 | 对接ESG/安环/能源管理部门，形成低碳项目包 | {facts['green']} {_petrochem_citation(source_ids[-2:])} |",
        f"| P2 | 建设/扩建项目转运营 | 开车备件、现场服务、系统调试和运维框架 | 对在建或新投产项目建立90天服务清单 | {facts['strategy']} {_petrochem_citation(source_ids[:3])} |",
        "",
        "## 项目打标与调研重点",
        "",
        (
            f"{tagging.get('headline', '按客户角色、项目阶段、技术层级和证据材料建立项目标签。')}"
            f"油气化工KA建议不要只按集团公司名管理，而要落到基地、装置、电气包、EPC/设计院、采购主体和运维责任人。"
            f"{_petrochem_citation(tagging.get('source_ids', []))}"
        ),
        "",
        "### 项目标签",
        "",
        "| 标签组 | 建议标签 | 判断依据 |",
        "| --- | --- | --- |",
    ]
    for group in tagging.get("tag_groups", []):
        lines.append(
            f"| {_md_cell(group.get('name', ''))} | {_md_cell('、'.join(group.get('tags', [])))} | {_md_cell(group.get('why', ''))} |"
        )
    lines.extend(
        [
            "",
            "### 三层两闭环调研清单",
            "",
            "| 层级 | 重点调研 | 证据材料 |",
            "| --- | --- | --- |",
        ]
    )
    for item in tagging.get("solution_map", []):
        lines.append(
            f"| {_md_cell(item.get('layer', ''))} | {_md_cell(item.get('focus', ''))} | {_md_cell(item.get('evidence', ''))} |"
        )
    lines.extend(
        [
            "",
            "### 下一步必须追问",
            "",
        ]
    )
    for focus in tagging.get("research_focus", []):
        lines.append(f"- {focus.get('topic', '调研重点')}：{'；'.join(focus.get('questions', []))}")
    lines.extend(
        [
            "",
            "## 90天行动建议",
            "",
            "| 周期 | 目标 | 动作 | 交付物 |",
            "| --- | --- | --- | --- |",
            "| 0-30天 | 完成主体和项目口径确认 | 区分集团、上市公司、项目公司、基地和采购主体，建立客户编码映射 | 主体-基地-采购主体表 |",
            "| 0-30天 | 补齐施耐德内部合作数据 | 拉通CRM/ERP、渠道授权、服务工单、应收和历史项目BOM | 采购与合作画像 |",
            "| 31-60天 | 形成重点基地机会池 | 按炼化、化工、新材料、公辅、码头/储运、变电所拆分场景 | 机会清单与优先级 |",
            "| 61-90天 | 推进客户访谈和技术澄清 | 对采购、技术、设备、安环、能源管理、项目管理做访谈 | 关键人地图与解决方案包 |",
            "",
        ]
    )
    for module, fields in fields_by_module().items():
        lines.extend(["", f"## {_module_display_name(module)}", ""])
        lines.extend(["| 类别 | 字段 | 洞察结论 | 说明 | 来源 |", "| --- | --- | --- | --- | --- |"])
        for field in fields:
            row = rows.get(field.field, {})
            value = _supplement_current_value(row) or "待核验"
            citations = _petrochem_citation(row.get("source_ids", []))
            lines.append(
                f"| {field.category} | {field.field} | {value} | {field.description} | {citations or '待补'} |"
            )
    return "\n".join(lines).replace("\n\n\n", "\n\n") + "\n"


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
        category_map: dict[str, list[dict[str, str]]] = {}
        for item in fields:
            category_map.setdefault(item.category, []).append(
                {
                    "field": item.field,
                    "description": item.description,
                }
            )
        catalog.append(
            {
                "module": module,
                "name": _module_display_name(module),
                "field_count": len(fields),
                "categories": [
                    {
                        "name": category,
                        "field_count": len(items),
                        "fields": items,
                    }
                    for category, items in category_map.items()
                ],
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
    if _is_chint_customer(project.customer):
        supply_field_count = sum(len(section.get("rows", [])) for section in supply_procurement)
        for item in module_summary:
            if item["name"] == "供应链与采购模块":
                item["field_count"] = supply_field_count
                item["explicit_count"] = supply_field_count
                item["internal_count"] = 0
                item["interview_count"] = 0
                item["public_gap_count"] = 0
                item["completion"] = 100 if supply_field_count else 0
    customer_resources = _customer_resources(project.customer)
    sales_market = _customer_sales_market(project.customer)
    org_decision = _customer_org_decision(project.customer)
    org_decision_blueprint = _customer_org_decision_blueprint(project.customer)
    strategy_needs = _customer_strategy_needs(project.customer)
    pain_opportunities = _customer_pain_opportunities(project.customer)
    risk_assessment = _customer_risk_assessment(project.customer)
    competitor_summary = _customer_competitor_summary(project.customer)
    supplement_plan = _customer_supplement_plan(project.customer)
    project_tagging = _project_tagging_model(project.customer)
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
        "org_decision_blueprint": org_decision_blueprint,
        "strategy_needs": strategy_needs,
        "pain_opportunities": pain_opportunities,
        "risk_assessment": risk_assessment,
        "competitor_summary": competitor_summary,
        "supplement_plan": supplement_plan,
        "project_tagging": project_tagging,
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return dict(petrochem_data["profile"])
    if _is_chint_customer(customer):
        return {
            "short_name": "正泰电器",
            "account_type": "盘厂KA/竞合型大客户",
            "relationship": "既是低压与智能配电核心竞品，也可能出现在终端项目、成套/OEM、系统集成和业主品牌库链路中，需要按项目入口拆分竞合边界",
            "opportunity_level": "选择性",
            "risk_level": "高",
            "recommended_focus": "项目入口、柜型/BOM、业主/设计院/EPC规格影响、授权/采购边界、FAT/SAT交付证据、共同终端项目赢丢单复盘",
        }
    if _is_zhonghuan_customer(customer):
        return {
            "short_name": "中环电气",
            "account_type": "项目型重点盘厂客户",
            "relationship": "以招投标、项目交付和多品类电气配套为核心的区域型盘厂客户",
            "opportunity_level": "中高",
            "risk_level": "中",
            "recommended_focus": "施耐德授权状态、近三年采购额、业主/设计院指定品牌、标准BOM、公共建筑与工业可靠配电",
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_portrait(customer, petrochem_data, opportunities, risks, gaps)
    if _is_chint_customer(customer):
        portrait = {
            "headline": "低压电器龙头与盘厂生态型KA：竞合并存、项目链路经营",
            "tags": ["盘厂KA", "竞合型大客户", "低压/成套", "OEM控制柜", "智能配电", "终端项目入口"],
            "business_role": "正泰不是普通采购客户，也不应只作为单一竞品看待。它同时具备低压元器件、低压成套、智能配电、OEM控制柜、行业解决方案、绿色能源和终端项目案例能力，施耐德需要按项目、柜型、BOM和终端业主链路拆分经营。",
            "relationship_strategy": "正泰自有品牌强的常规低压和分销场景应以监测和防守为主；业主/设计院/EPC指定、国际认证、关键负载、智能配电、复杂交付和第三方可信服务场景，则要以盘厂KA方式前移经营规格、BOM、测试调试和生命周期价值。",
            "needs": ["识别正泰参与的终端项目入口与柜型范围", "补齐授权/采购/历史交易和项目BOM边界", "建立业主、设计院、EPC、盘厂、系统集成商影响链", "围绕FAT/SAT、点表、通信、调试和服务证明施耐德价值"],
            "pain_points": ["正泰自有低压品牌容易在常规BOM中替代施耐德", "终端项目链路长，需提前进入业主/设计院/EPC技术协议", "公开资料无法直接证明施耐德授权或采购关系，需内部系统核验", "数据中心、新能源、油气、轨交等复杂场景对交付、调试和服务证据要求更高"],
            "decision_chain": [
                {"role": "正泰集团/上市公司战略层", "focus": "决定低压、绿色能源、全球化和数字平台的资源投向"},
                {"role": "智慧电器/行业销售/渠道团队", "focus": "影响项目入口、价格策略、终端客户和分销/盘厂触达"},
                {"role": "研发/质量/认证/标准团队", "focus": "决定高可靠、通信、认证、FAT/SAT和智能配电能力边界"},
                {"role": "业主/设计院/EPC/系统集成商", "focus": "决定施耐德能否在规格、品牌库和BOM阶段前置进入"},
            ],
            "next_questions": ["正泰哪些项目可按盘厂/OEM/系统集成链路经营，而不是只做竞品监测？", "哪些终端业主或设计院仍指定施耐德关键元件、柜型或数字化方案？", "哪些项目BOM、点表、FAT/SAT和服务资料能证明施耐德不可替代？"],
        }
    elif _is_zhonghuan_customer(customer):
        portrait = {
            "headline": "项目招投标驱动、具备多品类成套交付能力的重点区域盘厂客户",
            "tags": ["项目型盘厂", "施耐德授权", "Prisma E", "MVnex", "BlokSeT", "标准BOM机会"],
            "business_role": "官网明确其为成套电器设备骨干企业，产品覆盖母线槽、高低压开关柜、配电箱、桥架、支吊架、接地装置和箱式变电站；价值集中在业主/设计院项目入口、授权柜型和多品类电气配套能力。",
            "relationship_strategy": "先做主数据、授权状态和近三年采购额核验，再围绕公共建筑、化工/环保、供热、水利、轨交/母线槽和电子厂房配电项目建立机会池。",
            "needs": ["Prisma E/MVnex/BlokSeT授权范围核验", "近三年采购额和SKU核验", "项目品牌规范复盘", "标准BOM与技术包", "智能配电/能效切入"],
            "pain_points": ["非上市企业财务和客户集中度透明度低", "授权证书有效期和实际采购额仍需内部核验", "多品类项目容易造成图纸/BOM重复沟通", "关键采购/技术/生产负责人仍需访谈识别"],
            "decision_chain": [
                {"role": "董事长/总经理", "focus": "项目资源、重大采购、信用边界和关联主体协同"},
                {"role": "市场/销售/驻外办事处", "focus": "招标文件、业主指定品牌、总包关系和项目报价"},
                {"role": "技术部", "focus": "柜体方案、元器件选型、图纸、型式试验和项目规范"},
                {"role": "采购/生产/质保", "focus": "价格、交期、供应商准入、排产、检验和售后责任"},
            ],
            "next_questions": ["是否为施耐德授权盘厂或协议厂？", "近三年采购额、SKU、账期和逾期情况如何？", "哪些项目可由业主/设计院指定施耐德？", "是否可以共建低压柜/配电箱标准BOM？"],
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


def _customer_competitor_summary(customer: str) -> dict[str, Any]:
    if _is_chint_customer(customer):
        return {
            "title": "正泰电器盘厂KA企业洞察摘要",
            "subtitle": "由9大模块压缩成施耐德盘厂KA经营摘要",
            "one_sentence": "正泰电器不是普通采购客户，也不只是竞品；它同时具备低压元件龙头、成套/系统方案、OEM控制柜、终端项目案例和数字能源能力。施耐德应按“盘厂KA/竞合型项目”经营：拆分正泰自有品牌强势场景与施耐德可切入的业主指定、设计院/EPC规格、国际认证、关键负载、智能配电、交付服务场景。",
            "chain_eyebrow": "KA Project Chain",
            "chain_heading": "施耐德盘厂KA经营链路",
            "chain_badge": "正泰项目场景",
            "actions_heading": "施耐德推进动作",
            "module_takeaways": [
                {
                    "module": "01 基础信息模块",
                    "signal": "主体分层",
                    "takeaway": "正泰是A股上市的低压电器与智慧能源核心主体，控制权和集团生态稳定；对施耐德应按竞合型盘厂KA建档：自有品牌竞争、终端项目链路、关联主体和可能采购/授权关系必须分开。",
                    "source_ids": ["S1", "S5", "S20"],
                },
                {
                    "module": "02 业务能力模块",
                    "signal": "项目能力",
                    "takeaway": "能力已从低压元件延伸到低压成套柜、智能配电、新能源、储能、数据中心、电网和OEM控制柜。盘厂KA经营要把产品能力转成项目入口、柜型范围、BOM和交付责任，而不是只看公司规模。",
                    "source_ids": ["S1", "S3", "S15", "S45", "S54"],
                },
                {
                    "module": "03 供应链与采购模块",
                    "signal": "采购边界",
                    "takeaway": "公开资料未证明正泰电器本体为施耐德授权盘厂；且正泰自有低压/智能配电品牌强。应以内部CRM、授权系统、采购额、项目BOM和历史赢丢单核验真实合作边界，避免把竞品主体误当普通采购客户。",
                    "source_ids": ["S1", "S3", "S42", "SE8"],
                },
                {
                    "module": "04 客户资源模块",
                    "signal": "终端入口",
                    "takeaway": "官网案例覆盖华为、中国移动、维谛、南网、中石油长庆油田、中铁隧道、武汉天河机场、宁夏中卫云数据中心等共同终端场景。应逐一反推业主、设计院、EPC、柜厂/OEM和集成商角色，识别施耐德可前置的规格节点。",
                    "source_ids": ["S21", "S22", "S25", "S29", "S37", "S38", "S51", "S54"],
                },
                {
                    "module": "05 销售与市场模块",
                    "signal": "通路结构",
                    "takeaway": "正泰强分销网络、行业客户、区域/产品/行业三位一体营销和海外本土化并行。施耐德经营正泰相关项目时，需要把分销现货、盘厂BOM、行业KA、海外认证和终端项目招投标分开打法。",
                    "source_ids": ["S4", "S19", "S44", "S45"],
                },
                {
                    "module": "06 组织架构与决策链模块",
                    "signal": "影响链",
                    "takeaway": "正泰项目决策不只在采购端，关键在集团/上市公司战略、智慧电器产品线、行业销售、研发质量认证、区域/海外团队，以及外部业主、设计院、EPC、系统集成商共同影响。关键人信息应用于项目链路判断，不宜直接假设为采购触点。",
                    "source_ids": ["S40", "S41", "S43", "S44"],
                },
                {
                    "module": "07 发展战略与需求模块",
                    "signal": "需求画像",
                    "takeaway": "智慧电器、绿色能源、泰无界、正泰物联、零碳园区、海外服务和数据中心能力说明其需求与能力集中在智能配电、能碳管理、关键负载和全球本地化。施耐德机会应从第三方可信、国际客户规范、复杂项目交付和生命周期服务切入。",
                    "source_ids": ["S45", "S46", "S47", "S52", "S53"],
                },
                {
                    "module": "08 痛点与机会模块",
                    "signal": "施耐德窗口",
                    "takeaway": "窗口不在普通低压价格战，而在业主/设计院/EPC前置规格、BOM冻结、FAT/SAT、关键负载可靠性、Power Build/Power Commission、EcoStruxure数字服务、备件SLA和运维结果证明。",
                    "source_ids": ["S20", "S31", "S34", "SE1", "SE2", "SE8"],
                },
                {
                    "module": "09 风险评估模块",
                    "signal": "最大风险",
                    "takeaway": "最大风险是边界混淆：若未识别正泰自有品牌、关联主体、项目BOM和终端规格位置，施耐德可能在盘厂/业主/设计院链路中被持续替代，也可能误判真实可合作空间。",
                    "source_ids": ["S30", "S34", "S45", "S51"],
                },
            ],
            "substitution_chain": [
                {
                    "step": "1. 客户角色分层",
                    "question": "正泰在这个项目里到底是什么角色？",
                    "insight": "先把正泰拆成四类角色：自有低压/智能配电竞品、成套/OEM控制柜供应链节点、终端行业项目参与方、绿色能源/数字平台方案方。不同角色对应不同经营动作和边界。",
                    "source_ids": ["S21", "S37", "S38", "S51", "S54"],
                },
                {
                    "step": "2. 项目入口识别",
                    "question": "正泰在哪类终端项目中出现？",
                    "insight": "重点识别数据中心/通信、新能源/储能、电网、油气采油采气、轨交/机场、工业OEM、建筑楼宇和智能配电项目；这些场景应回填业主、设计院、EPC、盘厂/OEM、系统集成商和施耐德历史项目关系。",
                    "source_ids": ["S21", "S25", "S37", "S38", "S51", "S54"],
                },
                {
                    "step": "3. 规格影响链",
                    "question": "谁能决定施耐德是否进入BOM？",
                    "insight": "按业主品牌库、设计院上图、EPC/总包技术协议、盘厂标准BOM、正泰技术方案和现场服务要求建立影响链；招标前技术沟通、单线图、点表、通信接口和测试资料是前置节点。",
                    "source_ids": ["S37", "S38", "SE8"],
                },
                {
                    "step": "4. 施耐德价值锚点",
                    "question": "哪些环节值得施耐德投入？",
                    "insight": "优先投向高可靠、国际认证、关键负载、复杂智能配电、数字化运维、BOM/SLD准确性、FAT/SAT、服务SLA和生命周期TCO；普通标准品低价场景只做选择性参与。",
                    "source_ids": ["SE1", "SE2", "SE6", "SE8"],
                },
                {
                    "step": "5. 机会闭环",
                    "question": "下一步要补什么证据？",
                    "insight": "补齐内部采购/授权状态、客户编码、历史报价和赢丢单；外部补项目BOM、柜型照片、技术协议、点表/接口、调试记录、FAT/SAT节点和售后评价，形成可复盘的盘厂KA项目台账。",
                    "source_ids": ["S1", "S21", "SE8"],
                },
            ],
            "judgements": [
                {
                    "title": "关系判断",
                    "text": "正泰应按盘厂KA/竞合型企业经营：既不能忽略其核心竞品属性，也不能把所有项目都归为不能合作。关键是按项目、柜型、BOM、终端业主和规格影响链拆分。",
                    "source_ids": ["S1", "S20"],
                },
                {
                    "title": "能力判断",
                    "text": "正泰的项目能力来自低压产品、成套/控制柜、渠道、数字平台、绿色能源和终端案例组合；施耐德要在复杂项目、可靠性、认证、数字服务和交付闭环上证明差异。",
                    "source_ids": ["S3", "S45", "S52", "S53"],
                },
                {
                    "title": "项目判断",
                    "text": "数据中心、新能源、油气采油采气、电网、轨交/机场、工业OEM和盘厂BOM是正泰已经出现或高度相关的项目入口，必须建立共同终端客户地图。",
                    "source_ids": ["S34", "S45", "S51"],
                },
                {
                    "title": "经营判断",
                    "text": "施耐德动作要前移到业主/设计院/EPC技术规范和BOM阶段，后移到FAT/SAT、调试报告、服务SLA和复盘复制，避免只在采购询价阶段被动比价。",
                    "source_ids": ["S31", "SE1", "SE2"],
                },
            ],
            "actions": [
                {
                    "priority": "P1",
                    "action": "建立正泰盘厂KA项目台账",
                    "owner": "销售/渠道/行业团队",
                    "detail": "按终端客户、项目名称、行业场景、正泰角色、柜型/BOM、业主/设计院/EPC、施耐德历史关系和下一步动作建档。",
                },
                {
                    "priority": "P1",
                    "action": "核验授权与采购边界",
                    "owner": "客户经理/渠道授权/商务",
                    "detail": "拉通CRM、客户编码、授权系统、报价和订单，区分正泰本体、关联公司、项目例外采购和自有品牌竞争场景。",
                },
                {
                    "priority": "P1",
                    "action": "前移规格经营",
                    "owner": "技术销售/设计院团队",
                    "detail": "围绕单线图、保护配合、通信点表、智能配电、关键负载、认证资料和FAT/SAT要求，提前进入业主、设计院和EPC技术沟通。",
                },
                {
                    "priority": "P2",
                    "action": "准备盘厂KA价值包",
                    "owner": "行业市场/解决方案团队",
                    "detail": "形成BOM/SLD、Power Build、Power Commission、EcoStruxure、关键负载可靠性、备件SLA和TCO材料，可直接用于项目澄清和技术交流。",
                },
                {
                    "priority": "P2",
                    "action": "复盘共同终端项目",
                    "owner": "客户经理/竞争情报",
                    "detail": "优先复盘华为、数据中心、油气采油采气、远景能源、南网、中铁、机场等公开案例与施耐德客户池的重叠度。",
                },
            ],
            "watchlist": [
                "正泰是否在共同终端客户项目中作为业主指定、设计院推荐、EPC技术协议或盘厂BOM默认品牌出现",
                "正泰是否以OEM控制柜、数据中心低压柜、油气控制柜、智能配电系统而非单一元件进入项目",
                "施耐德是否存在正泰本体或关联主体的授权/采购/项目例外关系",
                "正泰泰无界/正泰物联是否被客户作为数字化配电或能碳管理平台选项",
                "正泰海外本地化、UL/IEC认证和北美数据中心订单是否改变国际项目品牌选择",
            ],
        }
    if _is_zhonghuan_customer(customer):
        return {
            "title": "中环电气企业洞察摘要",
            "subtitle": "由9大模块压缩成施耐德盘厂客户经营摘要",
            "one_sentence": "中环电气应按“项目型重点盘厂客户+施耐德授权盘厂线索”经营：官网显示其创建于2002年、厂区约3.2万平方米，产品覆盖母线槽、高低压开关柜、配电箱、电缆桥架、支吊架、接地装置和箱式变电站，并公开列示施耐德Prisma E、MVnex、BlokSeT授权合作证书；施耐德机会应落在授权范围核验、标准BOM、业主/设计院指定、智能配电、能效和项目服务闭环。",
            "chain_eyebrow": "Project Chain",
            "chain_heading": "施耐德项目经营链路",
            "chain_badge": "中环电气场景",
            "actions_heading": "施耐德推进动作",
            "module_takeaways": [
                {
                    "module": "01 基础信息模块",
                    "signal": "主体定位",
                    "takeaway": "工商主体成立于2006年，官网公司简介称企业创建于2002年、位于扬中市新坝工业园区，厂区占地约3.2万平方米、建筑面积约1.8万平方米、固定资产3500余万元；需在CRM中区分工商主体、官网历史沿革和关联主体。",
                    "source_ids": ["ZH1", "ZH15"],
                },
                {
                    "module": "02 业务能力模块",
                    "signal": "多品类项目能力",
                    "takeaway": "官网产品体系覆盖CCX母线槽、MNS低压开关柜、KYN61-40.5高压开关柜、配电箱、电缆桥架、综合支吊架、接地装置和箱式变电站；这说明施耐德应以项目包、授权柜型和标准BOM切入，而不是只按单一元器件销售。",
                    "source_ids": ["ZH15", "ZH16"],
                },
                {
                    "module": "03 供应链与采购模块",
                    "signal": "授权合作确认",
                    "takeaway": "官网荣誉资质列示施耐德Prisma E标准化低压成套分配电设备、MVnex智能中压开关柜、BlokSeT预智低压成套设备授权合作证书，同时列示西门子授权；施耐德内部仍需补齐证书有效期、授权范围、采购额、主采SKU、竞品比例和账期。",
                    "source_ids": ["ZH17"],
                },
                {
                    "module": "04 客户资源模块",
                    "signal": "项目客户牵引",
                    "takeaway": "官网称产品广泛应用于电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信等领域并畅销全国；外部项目线索进一步指向山东裕龙石化、常州新东化工、中车宝鸡时代、中国电建核电工程等场景，适合做分行业机会池。",
                    "source_ids": ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"],
                },
                {
                    "module": "05 销售与市场模块",
                    "signal": "项目招投标驱动",
                    "takeaway": "官网明确“畅销全国各地”，外部招采线索显示其参与供配电设备、配电箱、低压开关柜、仪表桥架、港口电气、污水处理、数字融合中心等项目，市场不是单一区域小客户，而是跨省项目型交付网络。",
                    "source_ids": ["ZH15", "ZH2", "ZH3", "ZH4"],
                },
                {
                    "module": "06 组织架构与决策链模块",
                    "signal": "职能链清晰但关键人缺失",
                    "takeaway": "官网组织框架栏目未披露可读取的组织图，联系方式页面公开联系人蒋子烨、手机、电话和邮箱；采购/技术/生产/销售负责人、项目授权和品牌替换权仍需客户经理访谈补齐。",
                    "source_ids": ["ZH1", "ZH18"],
                },
                {
                    "module": "07 发展战略与需求模块",
                    "signal": "数字化与资质背书",
                    "takeaway": "官网披露已通过ISO9001、ISO14001、ISO18001等体系认证，荣誉资质栏目列示环境、职业健康安全、质量、社会责任、售后服务、碳排放、碳足迹、能源管理等认证；施耐德可把智能配电、能效、EcoFit和数字化运维放到质量、服务和低碳管理叙事中。",
                    "source_ids": ["ZH15", "ZH17"],
                },
                {
                    "module": "08 痛点与机会模块",
                    "signal": "施耐德窗口",
                    "takeaway": "中环的痛点集中在多产品线标准化、授权范围与有效期核验、跨行业技术规范、交付质量和关键人信息不透明；施耐德机会是前置设计院/业主规范，围绕Prisma E、MVnex、BlokSeT授权建立标准BOM、培训技术团队、以服务和质量闭环降低总包风险。",
                    "source_ids": ["ZH16", "ZH17", "ZH2", "SE1", "SE2"],
                },
                {
                    "module": "09 风险评估模块",
                    "signal": "商务风险边界",
                    "takeaway": "非上市企业公开财务、现金流、客户集中度和付款信用不可见，且项目型业务可能有账期与验收周期；推进前必须把授信、逾期、付款节点、项目主体和售后责任边界打标。",
                    "source_ids": ["ZH2", "ZH3", "ZH13", "ZH17"],
                },
            ],
            "substitution_chain": [
                {
                    "step": "1. 主体与能力确认",
                    "question": "中环到底是哪类客户？",
                    "insight": "它不是正泰式全国低压竞品，而是扬中电气产业集群里的项目型成套/配套制造客户：官网显示创建于2002年，厂区约3.2万平方米、建筑面积约1.8万平方米，产品覆盖母线槽、高低压开关柜、配电箱、电缆桥架、支吊架、接地装置和箱式变电站。",
                    "source_ids": ["ZH15", "ZH16"],
                },
                {
                    "step": "2. 项目入口识别",
                    "question": "机会应该从哪里进？",
                    "insight": "优先从供热锅炉、水利泵站、化工/环保、公共建筑/配电箱、轨交/母线槽、电子厂房、港口电气和央企供应商项目切入，逐项确认是否存在业主指定、设计院标准或总包品牌库。",
                    "source_ids": ["ZH2", "ZH3", "ZH4", "ZH5"],
                },
                {
                    "step": "3. 规格影响链",
                    "question": "谁决定用不用施耐德？",
                    "insight": "决策链通常由业主/设计院/总包先定技术边界，中环销售获取项目，技术部校核图纸和品牌，采购部比价与确认交期，生产/质保负责出厂和交付；施耐德要前移到设计院和项目技术澄清阶段。",
                    "source_ids": ["ZH3", "ZH4", "ZH9"],
                },
                {
                    "step": "4. 施耐德价值",
                    "question": "如何避免只比价格？",
                    "insight": "把价值从元器件单价转到官网可核验的施耐德授权柜型、可靠性、选型效率、标准BOM、智能仪表/配电监控、EcoFit改造、FAT/SAT支持和现场服务响应，尤其适合化工、供热、水利、公共建筑和轨交项目。",
                    "source_ids": ["ZH17", "ZH3", "ZH4", "SE1", "SE2", "SE4"],
                },
                {
                    "step": "5. 推进闭环",
                    "question": "下一步怎么落地？",
                    "insight": "先拉通施耐德内部交易和授权数据，再选3类项目做样板：公共建筑配电箱/低压柜、化工或供热可靠配电、轨交/母线槽联动项目；每类沉淀技术规格、BOM、报价包、交付和售后证据。",
                    "source_ids": ["KB1", "KB2", "ZH2", "ZH3"],
                },
            ],
            "judgements": [
                {
                    "title": "定位判断",
                    "text": "中环应按“项目型重点盘厂客户”经营，价值来自项目入口和成套交付能力，而不是全国性品牌竞争。",
                    "source_ids": ["ZH2", "ZH3", "ZH9"],
                },
                {
                    "title": "能力判断",
                    "text": "官网披露多品类产品线、数控设备、母线加工设备和ISO/3C/体系认证，说明具备工程配套制造基础，但证书编号、有效期、产能和质量数据仍需核验。",
                    "source_ids": ["ZH15", "ZH16", "ZH17"],
                },
                {
                    "title": "机会判断",
                    "text": "供热、水利、化工、公共建筑、轨交、电子厂房和港口电气项目是施耐德最适合前置规格和标准BOM的场景。",
                    "source_ids": ["ZH2", "ZH3", "ZH4"],
                },
                {
                    "title": "风险判断",
                    "text": "最大风险是公开财务与施耐德历史交易不可见，若只在采购询价阶段进入，容易被竞品价格、业主指定或总包商务条件替代。",
                    "source_ids": ["ZH2", "ZH3", "ZH13"],
                },
            ],
            "actions": [
                {
                    "priority": "P1",
                    "action": "拉通中环主数据和授权状态",
                    "owner": "渠道/客户经理",
                    "detail": "核验江苏中环电气集团、安装公司、智能电气等关联主体客户编码，确认是否为协议厂/授权盘厂及授权柜型。",
                },
                {
                    "priority": "P1",
                    "action": "复盘近三年采购与赢丢单",
                    "owner": "销售运营/商务",
                    "detail": "抓取采购额、SKU、项目号、毛利、账期、逾期、竞品品牌和丢单原因，区分低压元件、柜体授权、智能仪表和服务机会。",
                },
                {
                    "priority": "P1",
                    "action": "建立项目机会池",
                    "owner": "客户经理/行业销售",
                    "detail": "按公共建筑、化工/环保、供热、水利、轨交/母线槽、港口/电子厂房六类项目打标，识别业主/设计院/总包品牌库。",
                },
                {
                    "priority": "P2",
                    "action": "共建标准BOM和技术包",
                    "owner": "技术销售/渠道技术",
                    "detail": "为低压柜、配电箱、MNS/KYN类项目准备施耐德元器件选型、替代清单、智能仪表、配电监控和FAT/SAT模板。",
                },
                {
                    "priority": "P2",
                    "action": "组织一次技术与服务访谈",
                    "owner": "客户经理/服务团队",
                    "detail": "拜访技术、采购、生产、质保和销售负责人，补齐关键人、交付痛点、售后边界、质量问题和客户满意度。",
                },
            ],
            "watchlist": [
                "中环是否具备有效低压成套CCC自我声明、高压型式试验报告和施耐德授权柜型",
                "近三年中环及关联主体对施耐德采购额、SKU、账期和逾期变化",
                "中环在哪些业主/设计院/总包品牌库中具备入围或指定地位",
                "ABB、西门子、正泰、德力西、常熟开关、良信等竞品在其项目BOM中的替代比例",
                "2025以后南京国博电子、华越镍钴、港口、污水处理和公共建筑项目能否形成复制机会",
            ],
        }
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data and petrochem_data.get("name") == "东方盛虹/盛虹炼化":
        return {
            "title": "东方盛虹企业洞察摘要",
            "subtitle": "由9大模块压缩成施耐德盘厂KA视角的决策摘要",
            "one_sentence": "东方盛虹是盛虹集团核心上市平台和连云港炼化新材料基地型KA：2025年业绩低位修复，2026年一季度归母净利润14.32亿元、经营现金流35.34亿元，但资产负债率仍高；施耐德应把机会落到盛虹炼化、斯尔邦、虹港、石化港储、POE/POSM等具体基地和装置，围绕连续生产可靠性、智能配电、能效、检修备件和服务SLA形成项目机会池。",
            "chain_eyebrow": "Opportunity Chain",
            "chain_heading": "施耐德机会链路",
            "chain_badge": "东方盛虹场景",
            "actions_heading": "施耐德推进动作",
            "module_takeaways": [
                {
                    "module": "01 基础信息模块",
                    "signal": "关系定位",
                    "takeaway": "东方盛虹是盛虹集团核心上市平台，控股股东和实际控制人清晰，旗下盛虹炼化、斯尔邦、虹港、石化港储等主体众多；经营时要拆分上市公司、基地、项目公司和EPC/盘厂路径。",
                    "source_ids": ["SH1", "SH2"],
                },
                {
                    "module": "02 业务能力模块",
                    "signal": "基地规模",
                    "takeaway": "其1600万吨/年炼化一体化、MTO、PDH、EVA、POE、丙烯腈和聚酯化纤形成连续生产型大基地；10万吨/年POE工业化装置投产后，高端材料装置对稳定供电、质量一致性和洁净生产要求进一步提高。",
                    "source_ids": ["SH1", "SH3", "SH6", "SH9"],
                },
                {
                    "module": "03 供应链与采购模块",
                    "signal": "采购入口",
                    "takeaway": "公开资料能确认原料端长约+现货采购和采购系统智能化升级；电气侧仍缺少业主品牌库、项目BOM、EPC规范、合格供应商、历史装机和近三年施耐德采购额，需要作为信息补充重点。",
                    "source_ids": ["SH1", "SH7"],
                },
                {
                    "module": "04 客户资源模块",
                    "signal": "下游牵引",
                    "takeaway": "EVA覆盖光伏胶膜头部企业，丙烯腈进入碳纤维主流客户，聚酯外销40余个国家和地区；POE投产强化光伏胶膜和高端材料客户牵引，下游质量要求会倒逼基地稳定、能效和质量一致性。",
                    "source_ids": ["SH1", "SH2", "SH9"],
                },
                {
                    "module": "05 销售与市场模块",
                    "signal": "价值敏感",
                    "takeaway": "销售以直销和长期框架为主，市场周期压力使其采购端对价格、交付和现金流敏感；2026年一季度盈利改善说明价差和行业景气修复，但品牌报告仍提示需求疲弱与价格压力，施耐德要用停机损失、能耗收益和开车保障证明TCO价值。",
                    "source_ids": ["SH1", "SH8", "SH10"],
                },
                {
                    "module": "06 组织架构与决策链模块",
                    "signal": "多层决策",
                    "takeaway": "上市公司高层提供战略与资金方向，真正影响电气项目的是基地项目建设、采购、设备、电仪、安环、生产运行、EPC/设计院和盘厂承包商组成的链路。",
                    "source_ids": ["SH1", "KB2"],
                },
                {
                    "module": "07 发展战略与需求模块",
                    "signal": "数智低碳",
                    "takeaway": "公司已上线流程工业智能大模型平台并推进智能工厂、AI、能效和绿色材料；POE、POSM、多元醇等高端材料放量会把智能配电、能源管理、电气资产健康和电气数据接入工业大模型变成高价值入口。",
                    "source_ids": ["SH1", "SH2", "SH9", "SE1", "SE2"],
                },
                {
                    "module": "08 痛点与机会模块",
                    "signal": "机会窗口",
                    "takeaway": "2025年扣非亏损和高杠杆说明降本增效压力仍在，2026年一季度盈利修复说明客户更有动力复制有效技改；机会应落在检修窗口、开车保障、能效、备件、停机风险和高可靠供电。",
                    "source_ids": ["SH1", "SH7", "SH8", "SE4"],
                },
                {
                    "module": "09 风险评估模块",
                    "signal": "风险边界",
                    "takeaway": "盈利改善不等于商务风险消失；资产负债率仍约81%，安全环保、连续生产停机、EPC履约、项目账期和付款信用仍是推进前必须打标的边界条件。",
                    "source_ids": ["SH1", "SH7", "SH3"],
                },
            ],
            "substitution_chain": [
                {
                    "step": "1. 经营事实",
                    "question": "客户现在最重要的变化是什么？",
                    "insight": "2025年公司营收1,255.87亿元、扣非净利润-5.43亿元，但2026年一季度营收320.22亿元、归母净利润14.32亿元、经营现金流35.34亿元，周期底部后的盈利修复为技改、能效和可靠性项目提供了更清晰的商业窗口。",
                    "source_ids": ["SH1", "SH7", "SH8"],
                },
                {
                    "step": "2. 项目入口",
                    "question": "机会应该落到哪里？",
                    "insight": "优先拆分盛虹炼化、斯尔邦、虹港、石化港储、聚酯化纤、公辅变电所、MCC室、储运码头、POE、POSM及多元醇项目；不要只按“东方盛虹集团”做泛化经营。",
                    "source_ids": ["SH1", "SH3", "SH6", "SH9"],
                },
                {
                    "step": "3. 决策链",
                    "question": "谁影响电气方案？",
                    "insight": "业主采购、设备、电仪、生产运行、安环、EPC/设计院、盘厂成套和自动化包商共同影响方案；横河案例说明自动化包商已深度进入盛虹炼化，施耐德电气方案必须和控制、数据、点表及运维边界联动。",
                    "source_ids": ["SH4", "KB2"],
                },
                {
                    "step": "4. 施耐德价值",
                    "question": "如何避免只比价格？",
                    "insight": "围绕连续生产和高端材料装置，把价值从柜体价格转到关键负载可靠性、停机损失、电能质量、能耗优化、预测维护、FAT/SAT、备件SLA和人员培训，并接入其AI/智能工厂/设备预测维护场景。",
                    "source_ids": ["SH1", "SH9", "SE1", "SE2", "SE3"],
                },
                {
                    "step": "5. 推进闭环",
                    "question": "如何转成项目？",
                    "insight": "先做基地电气资产盘点、装机品牌图谱和检修窗口表，再选择1个装置或公辅变电所做智能配电/能效/备件试点；沉淀BOM、点表、FAT/SAT、培训和验收证据后复制到其他基地。",
                    "source_ids": ["KB1", "KB2", "SE4"],
                },
            ],
            "judgements": [
                {
                    "title": "经营判断",
                    "text": "东方盛虹2026年一季度盈利和现金流显著改善，但2025年扣非亏损和约81%资产负债率说明商务风险仍需前置评审。",
                    "source_ids": ["SH1", "SH7", "SH8"],
                },
                {
                    "title": "场景判断",
                    "text": "机会不是泛泛的“化工客户”，而是盛虹炼化、斯尔邦、虹港、石化港储、POE/POSM、公辅变电所和MCC室等具体装置/项目包。",
                    "source_ids": ["SH1", "SH3", "SH6", "SH9"],
                },
                {
                    "title": "需求判断",
                    "text": "高端材料放量、流程工业智能大模型和预测维护场景，使智能配电、电气资产健康、能效管理和电气数据接入成为施耐德高价值入口。",
                    "source_ids": ["SH1", "SH2", "SH9", "SE2"],
                },
                {
                    "title": "行动判断",
                    "text": "下一步应先补齐装机品牌、业主品牌库、EPC/设计院规范、盘厂BOM、检修窗口和付款路径，再选择可复制的智能配电/能效试点。",
                    "source_ids": ["SH1", "SH4", "KB2"],
                },
            ],
            "actions": [
                {
                    "priority": "P1",
                    "action": "建立东方盛虹项目地图",
                    "owner": "KA经理/行业销售",
                    "detail": "按盛虹炼化、斯尔邦、虹港、石化港储、化纤基地、POSM及多元醇、检修技改、公辅变电所拆分机会池。",
                },
                {
                    "priority": "P1",
                    "action": "补齐装机与品牌库",
                    "owner": "销售/渠道/盘厂团队",
                    "detail": "收集业主品牌库、EPC技术协议、盘厂BOM、柜内照片、历史采购额和竞品品牌，形成可追踪替换/增量清单。",
                },
                {
                    "priority": "P1",
                    "action": "做智能配电价值包",
                    "owner": "技术销售/解决方案团队",
                    "detail": "围绕MCC室、公辅变电所、关键装置和能源管理，准备PME/PO、网关、温度/弧光监测、预测维护和能效收益材料。",
                },
                {
                    "priority": "P2",
                    "action": "同步商务风险评审",
                    "owner": "商务信用/法务",
                    "detail": "结合资产负债率、担保、项目主体、EPC付款路径和历史账期，设定授信、付款节点、验收证据和违约保护条款。",
                },
                {
                    "priority": "P2",
                    "action": "设计90天拜访计划",
                    "owner": "KA经理/服务团队",
                    "detail": "分别拜访采购、设备、电仪、安环、生产运行和EPC/盘厂，输出资产健康诊断、备件清单、检修窗口和试点装置。",
                },
            ],
            "watchlist": [
                "东方盛虹是否启动新的POSM、多元醇、EVA/POE、丙烯腈、PTA或公辅技改项目",
                "盛虹炼化/斯尔邦是否把智能工厂、AI、能效管理需求延伸到电气系统数据",
                "施耐德是否进入业主品牌库、EPC技术协议、盘厂BOM和备件框架",
                "竞品品牌在MCC、低压柜、变频、电能质量和自动化包中的装机份额",
                "客户财务杠杆、授信、付款节点、检修窗口和项目验收风险变化",
            ],
        }
    return {
        "title": f"{customer}摘要页",
        "subtitle": "由9大模块压缩的企业洞察摘要",
        "one_sentence": "当前企业尚未配置专属竞品替代链路摘要，可先使用9大模块信息开展关系定位、项目入口、决策链、风险和行动建议梳理。",
        "method_note": "建议按项目入口、客户价值、决策链、替代风险和下一步动作组织摘要。",
        "module_takeaways": [],
        "substitution_chain": [],
        "judgements": [],
        "actions": [],
        "watchlist": [],
    }


def _customer_basic_info(customer: str) -> list[dict[str, Any]]:
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_basic_info(petrochem_data)
    if _is_chint_customer(customer):
        return [
            _basic_row("企业名称", "浙江正泰电器股份有限公司", "成套厂全称/上市公司主体", ["S1"]),
            _basic_row("统一社会信用代码", "91330000142944445H", "企业唯一标识", ["S1"]),
            _basic_row("成立时间", "1997-08-05", "企业经营年限", ["S1"]),
            _basic_row("注册资本", "2,148,968,976 元", "反映企业规模", ["S1"]),
            _basic_row("企业性质", "境内民营上市公司；控股股东为正泰集团股份有限公司。对施耐德而言，应按“盘厂KA/竞合型大客户”管理：自有低压品牌与施耐德竞争，但其终端项目、成套/OEM、系统方案和关联主体链路仍需按项目拆分经营", "民营上市平台/竞合型盘厂KA主体", ["S1", "S20"]),
            _basic_row(
                "股权结构",
                "正泰集团直接持股 41.18%；浙江正泰新能源投资有限公司 8.39%；南存辉直接持股 3.45%；最终控制人为南存辉。控制权稳定，盘厂KA经营需同时看上市公司本体、正泰集团、正泰新能源/正泰安能、正泰物联、正泰电气等关联主体在具体项目中的角色",
                "主要股东及持股比例",
                ["S1", "S2"],
            ),
            _basic_row("法人代表", "南存辉；正泰盘厂KA研究重点不是单一采购负责人，而是集团战略、低压电器、绿色能源、全球化、项目销售和终端品牌库如何共同影响施耐德进入BOM", "企业法定代表人/董事长线索", ["S1", "S5"]),
            _basic_row("注册地址", "浙江省乐清市北白象镇正泰工业园区正泰路 1 号", "企业注册地", ["S1"]),
            _basic_row(
                "实际经营地址",
                "公开年报披露的注册/办公地址同为浙江省乐清市北白象镇正泰工业园区正泰路 1 号；盘厂KA经营需把乐清总部、国内制造基地、海外制造基地、区域销售组织、行业项目团队和关联工程/系统主体拆开建档",
                "生产基地/办公地址",
                ["S1", "S3", "S5", "S8"],
            ),
        ]
    if _is_zhonghuan_customer(customer):
        return [
            _basic_row("企业名称", "江苏中环电气集团有限公司", "成套厂全称", ["ZH1"]),
            _basic_row("统一社会信用代码", "91321182782724213T", "企业唯一标识", ["ZH1"]),
            _basic_row("成立时间", "工商主体成立于2006-03-13；官网公司简介称企业创建于2002年，需在客户主数据中区分工商成立日和品牌/企业创建年份", "企业经营年限", ["ZH1", "ZH15"]),
            _basic_row("注册资本", "20,018 万元", "反映企业规模", ["ZH1"]),
            _basic_row("企业性质", "在业；电气机械和器材制造业；官网定位为生产成套电器设备的骨干企业，对施耐德应按授权线索明确的项目型盘厂客户经营", "公开页面未披露完整工商企业类型", ["ZH1", "ZH2", "ZH15", "ZH17"]),
            _basic_row("股权结构", "公开资料未披露主要股东及持股比例，需工商底档或客户访谈补齐", "主要股东及持股比例", []),
            _basic_row("法人代表", "王永贵", "法定负责人", ["ZH1", "ZH5"]),
            _basic_row("注册地址", "江苏省扬中市新坝工业园区（南自路）", "企业注册地", ["ZH1"]),
            _basic_row("实际经营地址", "官网联系方式：江苏省扬中市新坝工业园区（南自路）；官网披露占地约3.2万平方米、建筑面积约1.8万平方米、固定资产3500余万元，公开联系人蒋子烨、手机15262975888、电话0511-88399111/88399333、邮箱zhonghuandianqi@sina.com", "生产基地/办公地址", ["ZH15", "ZH18"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_certifications(petrochem_data)
    if _is_chint_customer(customer):
        return [
            _certification_row(
                "低压成套设备生产资质",
                "正泰质量信用报告披露公司自第一张CCC认证证书起，已陆续获得CCC证书980余张，并有CQC自愿认证、“浙江制造”、泰尔认证等产品认证证书30余张，覆盖全部低压电器产品；盘厂KA视角下，这些资质说明其可在终端项目BOM中以自有品牌参与，需持续跟踪低压成套开关设备/控制设备证书清单、有效期和生产地址",
                "资质与认证",
                ["S12", "CNCA1", "CQC1"],
            ),
            _certification_row("高压成套设备资质", "公开资料未直接披露浙江正泰电器股份有限公司本体高压成套设备资质；但正泰集团/正泰电气等关联主体可能覆盖输配电设备。需区分低压元器件、低压成套、中压/高压设备和关联主体，判断施耐德在中压、授权柜型和高端成套上的项目切入边界", "资质与认证", ["CQC1", "S5"]),
            _certification_row("ISO体系认证", "巨潮披露的正泰电器2024年年报列明ISO9001:2015、ISO10012:2003、QC080000:2017、ISO14001:2015、ISO45001:2018等体系认证；体系认证增强其进入工业、数据中心、海外和央国企项目的可信度，施耐德应在关键负载、国际认证、FAT/SAT证据和服务闭环上做更高层级比较", "ISO9001/14001/45001等", ["S14", "CNCA1"]),
            _certification_row("特种设备生产许可证", "公开资料未披露；盘厂KA判断上应关注其储能、光伏、综合能源和客户侧改造项目中是否通过关联工程主体补齐施工、运维和特种设备资质", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "未检索到浙江正泰电器股份有限公司本体电力工程施工总承包资质；若项目由正泰关联工程主体承接，需另按主体查询住建资质，以判断其是否能从元件/成套延伸到EPC、运维和客户侧改造场景", "资质名称与等级", []),
            _certification_row("承装修试资质", "未检索到浙江正泰电器股份有限公司本体承装/承修/承试许可；需用国家能源局资质系统复核正泰关联工程主体资质，判断其是否具备参与客户侧配电运维、改造和调试服务的能力", "资质名称与等级", ["NEA1"]),
            _certification_row("施耐德授权等级", "公开资料未证明正泰电器本体为施耐德授权盘厂；若历史存在授权、采购或项目例外，应严格按主体、柜型、项目、BOM和终端业主拆分，避免把正泰自有品牌竞争场景误判为施耐德合作机会", "协议厂/授权盘厂/战略合作伙伴", []),
        ]
    if _is_zhonghuan_customer(customer):
        return [
            _certification_row("低压成套设备生产资质", "官网公司简介披露严格按ISO9001质量体系运行，并通过中国质量认证中心强制性3C认证；产品页披露MNS型低压开关柜、配电箱，授权页列示施耐德Prisma E和BlokSeT授权合作证书。证书编号、有效期和获证组织仍需在CNCA/CQC及施耐德内部授权系统核验", "资质与认证", ["ZH15", "ZH16", "ZH17", "CNCA1", "CQC1"]),
            _certification_row("高压成套设备资质", "官网产品页披露KYN61-40.5高压开关柜，授权页列示施耐德MVnex智能中压开关柜授权；威海高压柜项目也显示供货/投标能力。高压型式试验报告编号、授权有效期和适用范围仍需客户或施耐德系统复核", "资质与认证", ["ZH16", "ZH17", "ZH3", "CQC1"]),
            _certification_row("ISO体系认证", "官网公司简介披露已通过ISO9001、ISO14001、ISO18001等体系认证；荣誉资质-体系认证栏目列示环境管理、职业健康安全、质量管理、社会责任、售后服务、碳排放、碳足迹、能源管理等认证。证书编号和有效期仍需CNCA或客户证书扫描件核验", "ISO9001/14001/45001等", ["ZH15", "ZH17", "CNCA1"]),
            _certification_row("特种设备生产许可证", "公开资料未披露，需客户提供或通过监管/资质平台核验", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "公开资料显示其业务含电气工程安装、建设工程施工等线索；具体电力承包施工资质等级待核验", "资质名称与等级", ["ZH2"]),
            _certification_row("承装修试资质", "未检索到江苏中环电气集团有限公司承装/承修/承试等级；国家能源局资质和信用信息系统提供承装修试许可证查询入口，需按企业名称复核是否持证、许可类别和等级", "资质名称与等级", ["NEA1"]),
            _certification_row("施耐德授权等级", "官网荣誉资质-授权合作证书栏目列示：施耐德Prisma E标准化低压成套分配电设备、施耐德MVnex智能中压开关柜授权、施耐德BlokSeT预智低压成套设备授权。需施耐德内部核验证书有效期、授权组织、授权柜型范围和年度采购/协议状态", "协议厂/授权盘厂/战略合作伙伴", ["ZH17"]),
        ]
    if _is_tianyu_customer(customer):
        return [
            _certification_row("低压成套设备生产资质", "引江济淮项目公示显示低压开关柜部分提供强制性认证产品符合性自我声明；CQC输配电认证覆盖低压成套设备及配件、低压成套开关设备，完整证书清单和有效期需在CNCA/CQC继续核验", "资质与认证", ["TY4", "CNCA1", "CQC1"]),
            _certification_row("高压成套设备资质", "引江济淮项目公示显示35kV、10kV开关柜所投产品具备有效型式试验报告；CQC输配电认证覆盖高压设备及电器、高压成套开关设备，建议进一步核验证书编号、试验报告编号和适用型号", "资质与认证", ["TY4", "CQC1"]),
            _certification_row("ISO体系认证", "中国传动网历史资料显示天宇电气按ISO9001:2000建立质量体系并通过中国机械工业质量体系认证中心（现中联认证中心）审核；当前ISO9001/14001/45001有效证书编号、覆盖范围和有效期仍需在CNCA或客户证书清单复核", "ISO9001/14001/45001等", ["TY9", "CNCA1"]),
            _certification_row("特种设备生产许可证", "公开资料未披露，需按变压器、GIS、开关柜等具体产品和监管要求核验", "资质名称与等级", []),
            _certification_row("电力承包施工资质", "经营范围许可项含建设工程施工等，具体电力承包施工资质等级待核验", "资质名称与等级", ["TY3"]),
            _certification_row("承装修试资质", "经营范围许可项含输电、供电、受电电力设施安装维修试验；国家能源局资质和信用信息系统提供承装修试许可证公开查询入口，需进一步核验是否持证、许可类别、等级和有效期", "资质名称与等级", ["TY3", "NEA1"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_scale_finance(petrochem_data)
    if _is_chint_customer(customer):
        return {
            "enterprise_scale": [
                _metric_row("员工总数", "30,214 人；规模足以支撑全国渠道、制造和项目交付，是施耐德在中国低压市场必须长期对标的本土组织能力", "在职员工数量", ["S1"]),
                _metric_row("技术人员数量", "技术人员 4,692 人、研发人员 2,679 人；说明其不是低端代工型对手，而是具备产品迭代、认证、行业应用和数字化平台投入的研发型竞品", "设计、研发、技术支持人员", ["S1", "S20"]),
                _metric_row("生产人员数量", "17,793 人；大规模生产团队叠加智能制造投入，构成其低成本、快速供货和国产替代的制造基础", "生产一线员工", ["S1", "S3"]),
                _metric_row("销售人员数量", "3,891 人；再叠加分销网络与行业团队，竞争关键不只是产品，而是渠道触达和终端客户覆盖", "销售团队规模", ["S1", "S4"]),
                _metric_row("厂房面积", "公开资料未披露具体厂房面积；竞争研究需按乐清基地、国内制造基地、海外制造基地和关联成套主体拆分产能，不宜只看上市公司地址", "生产场地面积（㎡）", []),
                _metric_row("生产基地数量", "公开资料显示拥有20+个海外制造基地，集团层面国内外制造基地较多；这是其对施耐德海外项目和本地化交付构成威胁的重要变量", "有几个生产基地", ["S3", "S5"]),
                _metric_row("年产能", "2025年配电电器产量8,295.41万台、终端电器39,408.26万台、控制电器21,474.34万台；产能规模强化其常规低压元器件价格战和快速交付能力，成套柜体产能需按关联主体另核验", "年产高低压柜体数量/产值", ["S1"]),
            ],
            "financial_status": [
                _metric_row("年营业收入", "2025年591.45亿元、2024年645.19亿元；虽然收入下滑，但体量远高于一般盘厂，应作为施耐德中国低压与新能源相关业务的战略级竞品池管理", "最近三年营业收入", ["S1"]),
                _metric_row("净利润", "2025年归母净利润45.01亿元、2024年38.74亿元；利润韧性支持其持续价格竞争、渠道补贴、研发投入和海外扩张", "最近三年净利润", ["S1"]),
                _metric_row("资产负债率", "2025年约66.13%、2024年约63.28%；负债率上行主要提示光伏和能源资产周期风险，但短期不削弱其低压竞争能力", "财务健康度指标", ["S1"]),
                _metric_row("现金流状况", "2025年经营性现金流230.90亿元、2024年152.02亿元，现金流改善明显；这意味着其具备较强渠道、库存和项目垫资能力，施耐德防守时需关注账期/价格组合竞争", "经营性现金流是否健康", ["S1"]),
            ],
        }
    if _is_zhonghuan_customer(customer):
        return {
            "enterprise_scale": [
                _metric_row("员工总数", "官网未披露员工总数；招聘公司介绍披露约280人，建议现场走访时复核社保人数、生产/技术/销售结构和劳务外包口径", "在职员工数量", ["ZH9", "ZH15"]),
                _metric_row("技术人员数量", "官网未披露具体人数；但官网披露其具备母线行业技术输出、矿用电气自研产品和多项体系认证，省平台披露高新技术企业、创新型中小企业、知识产权贯标和省三星级上云企业线索，说明具备技术/数字化管理基础", "设计、研发、技术支持人员", ["ZH15", "ZH16", "ZH14"]),
                _metric_row("生产人员数量", "公开资料未披露生产一线人数；官网披露主要工装设备包括数控多位高速转塔冲床、数控电液式剪板机、数控电液式折边机等，并拥有母线加工设备和铆接装配生产线，需现场核验产线人员和设备稼动", "生产一线员工", ["ZH15"]),
                _metric_row("销售人员数量", "公开资料未披露具体人数；招聘页披露市场部、驻外办事处、销售部，项目线索显示其具备跨省招采响应能力", "销售团队规模", ["ZH2", "ZH3", "ZH9"]),
                _metric_row("厂房面积", "官网披露占地约3.2万平方米、建筑面积约1.8万平方米、固定资产3500余万元；需现场核验生产/仓储/办公分区", "生产场地面积（㎡）", ["ZH15"]),
                _metric_row("生产基地数量", "官网和工商地址均指向江苏省扬中市新坝工业园区（南自路）；招聘介绍披露下设4个子公司，是否存在异地生产或安装服务主体需工商和客户访谈核验", "有几个生产基地", ["ZH1", "ZH15", "ZH9"]),
                _metric_row("年产能", "官网未披露高压柜、低压柜、配电箱、母线槽年产能；可用数控设备、母线加工设备、厂区面积和项目台账作侧影，仍需客户访谈核验", "年产高低压柜体数量/产值", ["ZH15", "ZH16"]),
            ],
            "financial_status": [
                _metric_row("年营业收入", "非上市公司公开资料未披露；公开项目金额和2024-2025招采线索只能作为规模侧影，不能替代财务报表", "最近三年营业收入", ["ZH2", "ZH3"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_business_capability(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "正泰在配电电器、终端电器、电动机控制与保护、电源电器、电气材料等低压/配电元器件上与施耐德重叠；其数据中心方案进一步覆盖塑壳/框架断路器、低压成套柜、中压配电系统及750kV及以下输配电产品。盘厂KA视角下，应把其产品拆成元件、成套柜、控制柜、智能配电和行业方案五类，分别判断施耐德进入BOM的空间", "高压柜/低压柜/箱变/配电箱等", ["S15", "S16", "S54", "SE3", "S20"]),
                    _business_row("产品线覆盖", "正泰已形成“元器件+成套+行业解决方案+能源运营”的链条：低压元器件、终端配电、低压成套柜、中压配电、智能配电监控、建筑/数据中心、电网、储能和工商业分布式储能。施耐德机会不在泛泛替代正泰全线，而在业主指定、设计院规范、国际认证、关键负载、通信点表、FAT/SAT和生命周期服务场景", "全产品线", ["S15", "S16", "S17", "S18", "S54", "SE1", "SE2"]),
                    _business_row("主营行业领域", "正泰官方方案与年报覆盖建筑、电网、数据中心/通信、储能、新能源、工商业、轨交、锂电、半导体和海外市场；这些也是施耐德中国低压、智能配电、数据中心和能源管理的重点战场。应按行业建立项目入口标签：终端业主、设计院、EPC、盘厂/OEM、系统集成商和服务责任人", "建筑/工业/电力/新能源等", ["S1", "S16", "S17", "S18", "SE2"]),
                    _business_row("业务收入结构", "年报披露低压电器219.19亿元、光伏业务362.74亿元、逆变器及储能23.90亿元；低压业务是与施耐德直接重叠的核心盘，光伏/储能/综合能源会带来新增配电与能效项目入口。地区收入中华东235.69亿元、华中107.65亿元、海外99.51亿元，说明盘厂KA项目应同时关注国内优势区、海外认证和全球本地化交付", "各业务板块收入占比", ["S1", "S7", "S20"]),
                ],
            },
            {
                "category": "技术能力",
                "rows": [
                    _business_row("设计团队规模", "年报披露研发人员2,679人、技术人员4,692人；盘厂KA研究应重点识别其低压新品、行业方案、数据中心、储能、海外认证和项目技术支持团队，以及这些团队是否参与业主/设计院/EPC技术澄清", "电气设计人员数量", ["S1", "S20"]),
                    _business_row("设计软件使用", "公开资料未披露EPLAN/CAD/三维设计使用情况；需要从正泰参与项目的设计院图纸、标准BOM、柜型图、单线图、通信点表和施耐德赢丢单资料反推其设计工具链和数字化选型能力", "EPLAN/CAD/三维设计等", []),
                    _business_row("研发投入占比", "2025年研发费用13.26亿元，占营业收入约2.24%；其研发投入和昆仑/诺雅克、智能框架控制、泰无界平台等产品上攻，会影响盘厂项目中客户对国产品牌和数字化方案的接受度", "研发费用/营业收入", ["S1", "S20"]),
                    _business_row("专利数量", "公开报告显示持续进行专利与产品创新布局；需要补齐低压断路器、智能配电、储能、数据中心、通信协议、柜体结构、海外认证相关专利/新品节奏，并映射到具体终端项目机会", "发明专利/实用新型/外观设计", ["S1"]),
                    _business_row("技术合作方", "公开资料未披露具体设计院或高校合作方；需从大型项目、行业白皮书、设计院品牌库、终端业主规范和EPC技术协议中识别其技术生态，判断其是否已经进入施耐德传统优势规范", "与哪些设计院/高校合作", ["S19"]),
                ],
            },
            {
                "category": "生产能力",
                "rows": [
                    _business_row("生产设备水平", "累计投入超过23亿元推进智能制造，建成多类数字化产线，并具备检测、校准和在线质控能力；这意味着其常规低压产品在成本、交期和一致性上有规模优势，施耐德要把交付优势落到BOM准确、齐套、调试报告和服务SLA", "自动化程度/设备先进性", ["S3"]),
                    _business_row("质量控制体系", "具备质量检测中心、数字化质控点、质量信用和全流程质量管理线索；质量短板不宜简单假设为正泰弱点，施耐德需证明在高可靠、关键负载、国际认证、FAT/SAT、热风险/弧光风险和生命周期服务上的差异", "检测设备、质检流程", ["S3", "S12", "SE1"]),
                    _business_row("生产周期", "公开资料未披露从下单到交付的平均周期；需通过项目复盘比较正泰与施耐德在常规低压、成套柜、控制柜、数据中心、新能源和海外认证项目中的交期、齐套与变更响应差异", "从下单到交付的平均周期", []),
                    _business_row("准时交付率", "公开资料未披露历史准时交付比例；需用项目BOM、订单齐套率、FAT/SAT节点、现场到货和售后记录验证正泰是否以交期和本地化库存形成优势", "历史订单准时交付比例", []),
                    _business_row("质量合格率", "公开资料未披露一次合格率；应关注终端客户是否在关键负载、海外认证、数据中心、储能安全和油气/轨交连续运行场景中仍偏好施耐德", "产品一次合格率", []),
                ],
            },
            {
                "category": "项目经验",
                "rows": [
                    _business_row("代表性项目", "正泰官网客户成功案例库可核验 183 个案例，已披露的标杆包括：华为战略合作（5G高密嵌入式开关电源、UPS柜、汇流箱、数据中心锂电柜、精密空调柜、箱变等场景）、远景能源风电主控柜系统解决方案、牧原动环监控系统、中石油长庆油田采油采气项目、中国中铁隧道集团全国集采配电箱项目、福建电力分布式光伏群调群控试点、山东电力低压分布式光伏并网方案等。对施耐德而言，这些案例应作为盘厂KA项目入口库，逐一补业主、设计院、EPC、柜型/BOM、正泰角色和施耐德可切入点", "历史标杆项目案例", ["S21", "S22", "S23", "S24", "S25", "S26", "S27", "S28"]),
                    _business_row("项目类型分布", "官网案例库按行业披露：新能源18个、5G&通信24个、电网16个、工业27个、OEM48个、建筑39个、轨交9个、基础设施2个。类型分布与施耐德低压配电、智能配电、数据中心、工业OEM和新能源储能的重点行业高度重叠，应作为正泰盘厂KA项目标签：终端项目、OEM控制柜、低压柜、智能配电、通信点表、FAT/SAT、服务SLA", "建筑/工业/市政/电力等占比", ["S21", "S54"]),
                    _business_row("项目地域分布", "官网案例覆盖全国集采、电网省级试点、山东/福建/河北/湖南/北京/雄安等区域项目，以及华为、远景、牧原、维谛、中石油长庆油田、中国中铁等全国性或行业龙头客户；结合公司服务全球140+国家和地区，正泰项目地域已从华东基本盘扩展到全国行业项目与海外场景。施耐德应按区域叠加本地盘厂、分销、设计院和终端KA关系", "业务覆盖省份/城市", ["S3", "S21", "S22", "S23", "S24", "S25", "S26", "S27", "S29"]),
                    _business_row("大型项目经验", "官网案例未逐项披露合同金额，无法直接确认500万+金额口径；但中国中铁隧道集团全国集采配电箱、中石油长庆油田采油采气、华为战略合作、维谛合作、远景风电主控柜、福建/山东电力分布式光伏等案例具备行业级/集团级项目属性。施耐德应将这些案例纳入大项目台账，再用中标公告、内部赢丢单和客户访谈补齐金额、份额、柜型、BOM和正泰胜出原因", "500万+项目经验", ["S22", "S23", "S25", "S26", "S27", "S28", "S29"]),
                    _business_row("行业标杆客户", "官网可核验的标杆客户包括华为、维谛、远景能源、牧原集团、中石油长庆油田、中国中铁隧道集团，以及国网/南网相关试点和山东、福建、河北、湖南等电网项目。应逐一判断其是施耐德共同客户、正泰优势客户还是潜在盘厂KA项目入口，并补充设计院/业主品牌库位置", "服务过的知名客户", ["S21", "S22", "S23", "S24", "S25", "S26", "S27", "S28", "S29"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "官网公司简介和产品页确认产品包括：电缆桥架、母线槽、低压开关柜、高压开关柜、配电箱、综合支吊架、接地装置、箱式变电站、矿用电器、车载断电仪、仪表仪器、管阀件等成套电气和工程配套产品", "高压柜/低压柜/箱变/配电箱等", ["ZH15", "ZH16"]),
                    _business_row("产品线覆盖", "官网产品与服务栏目覆盖8类主产品：CCX母线槽、MNS低压开关柜、KYN61-40.5高压开关柜、配电箱、电缆桥架、综合支吊架、接地装置、箱式变电站；经营范围还出现风电母线、太阳能支吊架、光伏变电站设备等新能源工程配套线索", "全产品线", ["ZH16", "ZH2"]),
                    _business_row("主营行业领域", "官网披露产品广泛应用于电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信等领域；外部项目线索补充供热、水利、居民小区供配电改造、化工/环保、轨交/中车、电建/核电供应商、电子厂房和港口电气等场景", "建筑/工业/电力/新能源等", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _business_row("业务收入结构", "非上市公司未披露各业务板块收入占比；现阶段可用招采平台项目品类判断业务重心：配电箱、低压开关柜、桥架、仪表桥架、港口电气、污水处理、公共建筑/电子厂房配电等项目线索更密集，仍需客户访谈或财务资料补齐", "各业务板块收入占比", ["ZH2", "ZH3", "ZH11", "ZH12"]),
                ],
            },
            {
                "category": "技术能力",
                "rows": [
                    _business_row("设计团队规模", "公开资料未披露电气设计人员数量；官网披露母线行业技术输出、自主研发生产轻型组合式支吊架、矿用电气自研产品，结合高新技术企业和项目技术评分可作为技术能力侧影", "电气设计人员数量", ["ZH15", "ZH16", "ZH3", "ZH10"]),
                    _business_row("设计软件使用", "公开资料未披露 EPLAN/CAD/三维设计使用情况，需技术访谈或图纸流程审核确认", "EPLAN/CAD/三维设计等", []),
                    _business_row("研发投入占比", "公开资料未披露研发费用及营业收入口径，需客户财务或高企申报材料核验", "研发费用/营业收入", []),
                    _business_row("专利数量", "官网综合支吊架详情称该产品拥有完全自主知识产权，省中小企业平台披露通过省级企业知识产权管理标准化绩效评价，但未列示专利数量；需补查国家知识产权局或客户证书清单", "发明专利/实用新型/外观设计", ["ZH16", "ZH14"]),
                    _business_row("技术合作方", "公开资料未披露具体设计院或高校合作方，建议在项目复盘中核验设计院、总包和业主技术接口", "与哪些设计院/高校合作", []),
                ],
            },
            {
                "category": "生产能力",
                "rows": [
                    _business_row("生产设备水平", "官网披露主要工装设备包括数控多位高速转塔冲床、数控电液式剪板机、数控电液式折边机等自动化数控测量设备，且拥有从铜排生产到高品质母线出厂的加工设备和铆接装配生产线；结合3.2万平方米厂区与3500余万元固定资产，可判断具备钣金/柜体/母线加工基础", "自动化程度/设备先进性", ["ZH15"]),
                    _business_row("质量控制体系", "官网披露严格按ISO9001质量体系运行并通过CQC强制性3C认证，已通过ISO9001/14001/18001等体系认证；荣誉资质还列示售后服务、碳排放、碳足迹、能源管理等认证。完整检测设备、一次合格率和质检流程仍需现场审核", "检测设备、质检流程", ["ZH15", "ZH17"]),
                    _business_row("生产周期", "公开资料未披露平均生产周期，需按高压柜、低压柜、母线槽、配电箱不同品类访谈核验", "从下单到交付的平均周期", []),
                    _business_row("准时交付率", "公开资料未披露准时交付率，需施耐德订单履约记录、项目验收记录和客户生产计划补齐", "历史订单准时交付比例", []),
                    _business_row("质量合格率", "公开资料未披露产品一次合格率，需客户质检记录、型式试验和售后质量数据补齐", "产品一次合格率", []),
                ],
            },
            {
                "category": "项目经验",
                "rows": [
                    _business_row("代表性项目", "官网案例展示栏目未展示可读取项目名称；外部项目线索包括文登168MW燃煤热水锅炉配套高压开关柜候选、淮河入海水道二期高低压开关柜及变压器采购候选、合肥居民小区供配电改造框架、山东裕龙石化污水处理厂、常州新东化工、宝鸡时代母线槽、南京国博电子配电箱、华越镍钴仪表桥架、港口电气等", "历史标杆项目案例", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH11", "ZH12"]),
                    _business_row("项目类型分布", "高压柜、低压柜/变压器、配电箱、桥架/仪表桥架、母线槽、配电工程、居民小区改造、化工/环保、轨交/母线槽、电子厂房、港口电气、电建/央企供应商等", "建筑/工业/市政/电力等占比", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH11"]),
                    _business_row("项目地域分布", "公开线索覆盖山东、北京、福建、安徽、湖北、江苏、内蒙古、浙江等地，并有淮安水利、常州公共资源、南京电子厂房、港口和化工项目线索；区域真实收入占比仍需内部订单核验", "业务覆盖省份/城市", ["ZH2", "ZH3", "ZH11", "ZH12"]),
                    _business_row("大型项目经验", "合肥居民小区供配电设施改造框架项目2,274.8172万元等；淮河入海水道二期项目体现高低压开关柜及变压器政府采购候选能力，500万以上项目需进一步清单化", "500万+项目经验", ["ZH3", "ZH11"]),
                    _business_row("行业标杆客户", "官网披露产品应用于电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信等领域；可识别客户/场景包括中国电建核电工程合格供应商线索、中车智能交通项目、山东裕龙石化、常州新东化工、山鹰系项目、洛阳双瑞、南京国博电子、华越镍钴等", "服务过的知名客户", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5", "ZH7"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "主营业务",
                "rows": [
                    _business_row("主营产品类型", "中国电气装备集团官方报道和许继体系资料显示，天宇电气以主变、箱变、高低压开关柜/开关成套设备为核心，包含互感器、环氧树脂浇注绝缘件、组合式变压器等；高校就业资料补充35kV及以下高低压开关柜和10kV及以下组合式变压器口径", "高压柜/低压柜/箱变/配电箱等", ["TY1", "TY2", "TY15"]),
                    _business_row("产品线覆盖", "覆盖主变、箱变、高低压开关柜、低压柜、互感器、绝缘件、组合式变压器，并通过许继/中国电气装备体系延伸到新能源箱变、海上风电塔筒环网柜、变压器/GIS候选品类及智能制造服务场景", "全产品线", ["TY1", "TY2", "TY4", "TY5", "TY16"]),
                    _business_row("主营行业领域", "官方与项目线索覆盖电网/配电网、水利工程、海上风电和新能源、数据中心/变压器应用、110kV变电站、煤化工、钢铁、锂电前驱体、渔光互补、增量配电网及海外项目等", "建筑/工业/电力/新能源等", ["TY1", "TY4", "TY5", "TY16"]),
                    _business_row("业务收入结构", "中国电气装备集团官方报道披露主变、箱变两大产品收入突破10亿元，并披露2025年营业收入近23亿元、新签合同额30多亿元；但未披露高低压柜、变压器、箱变等板块占比，需财务口径或客户访谈补齐", "各业务板块收入占比", ["TY1"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_supply_procurement(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "竞品采购情况",
                "rows": [
                    _supply_row("主要竞品品牌", "深度检索后未发现权威公开资料显示正泰电器本体批量采购施耐德、ABB、西门子、伊顿等低压元器件作为生产投入；公开资料更支持“竞品品牌在终端客户/盘厂BOM中与正泰竞争”的判断。正泰招股书把全产品线竞争者列为德力西、ABB、施耐德、罗格朗、西门子等，局部竞争者包括常熟开关、上海人民、良信、伊顿、海格等；第三方研究也显示石油石化、通讯、轨交、电子厂房、数据中心、高端商业楼宇等高端场景主要供应商仍是施耐德、ABB、西门子。盘厂KA口径下，应按“正泰自有品牌+施耐德/ABB/西门子高端规范+德力西/良信/常熟等国产替代+盘柜厂BOM影响”四层管理", "西门子/ABB/施耐德/德力西/良信/常熟等", ["S1", "S55", "S56", "S34"]),
                    _supply_row("竞品采购比例", "公开年报只披露2025年前五名供应商采购额80.59亿元、占年度采购总额14.93%，其中关联方采购44.86亿元、占8.31%，未披露施耐德、ABB、西门子等竞品品牌采购比例；因此不能填具体比例。建议改成项目BOM口径测算：对正泰参与的终端项目逐项统计施耐德、ABB、西门子、德力西、良信、常熟开关等品牌在断路器、接触器、继电器、仪表、网关、低压柜/控制柜中的金额、台套、关键回路位置和品牌库等级。上游交叉证据方面，苏州未来电器招股资料显示其同时向正泰、西门子、ABB、施耐德等供应低压断路器附件，说明部分附件供应链存在交叉，但这不能等同于正泰采购竞品整机", "竞品采购额占总采购比例", ["S1", "S30", "S31", "S34", "S57"]),
                    _supply_row("竞品使用原因", "正泰相关终端客户选择施耐德/ABB/西门子等竞品，通常不是因为正泰本体采购这些品牌，而是项目规格驱动：一是国际业主、设计院或EPC在高端项目中指定品牌；二是ACB、关键负载、石油石化、轨交、电子制造、数据中心、高端商业楼宇等场景更重视品牌背书、可靠性、国际认证、FAT/SAT和全生命周期服务；三是公开招标文件中常见施耐德、西门子、ABB或同档次以上品牌写入高低压柜、智能框架断路器、塑壳断路器、封闭母线等推荐品牌；四是盘柜厂和设计院通过柜型、BOM、技术协议、点表和验收资料把品牌选择转化为采购结果", "价格/技术/服务/关系等", ["S31", "S32", "S33", "S34", "S56", "S58"]),
                    _supply_row("竞品优势感知", "从正泰作为盘厂KA的业务需求看，竞品优势不能只按品牌泛泛判断，而应落到项目BOM、关键回路、柜型授权、调试工具、数字化运维和终端业主规范。下方对比表把施耐德与 ABB、西门子、伊顿及国产品牌放在同一业务场景下比较：施耐德更适合用高可靠低压配电、授权柜型、项目设计/调试工具和全生命周期服务切入；竞争对手在既有品牌库、价格、交期、本地渠道或特定柜型生态上仍有防守压力", "认为竞品哪些方面更有优势", ["S3", "S4", "S19", "S21", "S30", "S31", "S56", "S58", "SE1", "SE2", "SE3", "SE5", "SE6", "SE8", "ABB1", "ABB2", "SI1", "SI2", "SI3", "ET1", "ET2", "ET3"], comparison_rows=_chint_competitor_solution_comparison()),
                ],
            },
            {
                "category": "其他供应商",
                "rows": [
                    _supply_row("其他器件供应商", "排除施耐德、ABB、西门子、伊顿、德力西、良信、常熟开关等主要竞品整机品牌后，正泰的非竞品供应链重点应看四层：银点/电接触材料，铜材、钢材、塑料等大宗原材料，低压断路器附件/熔断片/复合铆钉等专业零部件，以及正泰物联/数字化产品所需电子元器件、网关、仪表和传感部件。公开信用评级资料披露低压板块原料种类超10万种，银、铜材、钢材、塑料合计约占该板块成本50%；银点前五大供应商采购金额占比超95%，铜材前五大约80%，钢材和塑料前五大约40%-45%。宏丰股份招股书可作为历史可验证样例：其为正泰提供银触点、电接触材料、复合铆钉、复合带材、熔断片等关键零部件，曾稳居正泰前五名供应商并签订长期采购合同；苏州未来电器则证明断路器附件供应链存在专业化外部供应商和多品牌交叉供货。下方非竞品供应链分层表用于把这些线索从竞品采购中拆出来管理", "其他核心供应商", ["S1", "S57", "S62", "S63"], supplier_segments=_chint_non_competitor_supplier_segments()),
                    _supply_row("柜体供应商", "全网检索后，正泰柜体供应不能简单判断为“外购柜体”。公开证据更支持“自有/关联成套能力 + 授权箱体产品 + 盘厂伙伴生态 + 部分外协钣金/母排/附件”的混合模式：正泰官网有POWGRID-S授权低压配电箱及控制箱、PZ30箱体等成套/箱体产品；数据中心方案明确低压配电系统含低压成套柜，并提到元器件及柜体品牌统一；盘厂合作伙伴页面披露正泰牵头低压动力配电及控制箱设计导则，为柜体尺寸、壳体制造、接线安装及验收提供统一标准；质量信用报告还披露可对低压成套柜开展短路、温升、EMC、环境等系统级实验。结论：正泰在低压箱体/成套柜上具备较强自有与生态组织能力，外部柜体供应商应重点核验钣金壳体、母排、喷涂、桥架、线束和项目盘厂，而不是把柜体供应商写成施耐德主要竞品品牌", "是否自产柜体或外购", ["S16", "S54", "S62", "S64", "S65", "S66", "S68"], evidence_title="柜体供应商证据链", evidence_subtitle="区分自制/关联主体/盘厂生态/外协件", evidence_rows=_chint_cabinet_supplier_evidence()),
                    _supply_row("供应链稳定性", "供应渠道需分成采购端和销售/交付端两条线。采购端：正泰2025年前五名供应商采购额80.59亿元，占年度采购总额14.93%，集团总供应商集中度不高，但银点、铜材等关键材料集中度较高；采购云和供应商大会显示其在供应商准入、寻源透明、研采供协同、环保/变更/错混料管控上持续数字化。销售/交付端：官网披露500+一级网点、5000+规模二级网点和10万+终端渠道，营销云、泰乐购、ECP覆盖客户、采购、销售、库存、应收等模块；蓝海行动进一步通过区域销售总公司、营销云、智慧分拨中心、全国骨干仓配网络、区总前置仓和配送型服务商体系提升供货响应。结论：正泰常规低压供货渠道稳定且下沉能力强；施耐德应在高端项目用品牌库、授权柜型、关键回路、调试报告、备件SLA和FAT/SAT资料来对冲其渠道与交付优势", "是否有稳定供货渠道", ["S1", "S4", "S42", "S59", "S60", "S61", "S62", "S67"], evidence_title="供应渠道与交付网络", evidence_subtitle="采购端供应商治理 + 销售端渠道/物流体系", evidence_rows=_chint_supply_channel_evidence()),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "施耐德合作情况",
                "rows": [
                    _supply_row("合作年限", "官网授权合作证书栏目确认存在施耐德授权合作证书，但未披露合作起始年份；需由施耐德CRM、客户经理和历史订单补齐合作年限", "与施耐德合作多少年", ["ZH17"]),
                    _supply_row("合作模式", "官网列示施耐德Prisma E标准化低压成套分配电设备、MVnex智能中压开关柜、BlokSeT预智低压成套设备授权合作证书，说明至少存在授权盘厂/授权柜型合作线索；需核验证书有效期、授权组织、协议价格、年度框架和项目指定关系", "协议厂/授权盘厂/普通客户", ["ZH17"]),
                    _supply_row("历史采购额", "公开资料未披露近三年施耐德采购额；建议按中环及可能关联主体抓取采购额、SKU、项目号、毛利、账期、逾期，并映射到公共建筑、化工、轨交、供热、水利等项目场景", "近三年施耐德产品采购额", []),
                    _supply_row("采购增长率", "公开资料未披露采购额同比；需用施耐德近三年订单和项目台账计算，并剔除一次性大项目波动", "采购额同比增长率", []),
                    _supply_row("主要采购产品", "官网未披露实际采购SKU；结合施耐德Prisma E、MVnex、BlokSeT授权，应重点核验断路器、接触器、继电器、智能仪表、通信模块、配电监控、低压/中压柜体授权系统和服务支持采购", "断路器/接触器/变频器/软启等", ["ZH17"]),
                    _supply_row("授权柜体型号", "官网确认施耐德Prisma E、MVnex、BlokSeT授权合作证书；未见Okken证书线索，需核验授权范围、证书有效期和是否仍处于活跃授权状态", "BlokSeT/Okken/MVnex等", ["ZH17"]),
                    _supply_row("合作满意度", "公开资料未披露对施耐德服务与技术支持满意度；需结合服务记录、报价响应、交付投诉和技术支持复盘访谈", "对施耐德服务、技术支持的满意度", []),
                ],
            },
            {
                "category": "竞品采购情况",
                "rows": [
                    _supply_row("主要竞品品牌", "官网授权合作证书栏目列示西门子授权，同时官网高压柜产品页提到国产或进口知名品牌元件可按用户或设计院要求选用；仍需复盘ABB、正泰、德力西、人民电器、常熟开关、良信、伊顿等在近两年项目中的替代原因", "西门子/ABB/正泰/德力西等", ["ZH16", "ZH17"]),
                    _supply_row("竞品采购比例", "公开资料无法确认竞品采购额占比；需从项目 BOM、采购台账和施耐德赢丢单记录反推", "竞品采购额占总采购比例", []),
                    _supply_row("竞品使用原因", "官网高压柜产品页明确可根据用户或设计院要求选用其他品牌产品，说明业主/设计院指定是品牌选择关键因素；项目型成套业务还受招标技术规范、价格评分、交付周期、本地服务和总包商务偏好影响", "价格/技术/服务/关系等", ["ZH16", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _supply_row("竞品优势感知", "竞品优势可能集中在本地交付、价格得分、既有项目关系、扬中电气产业集群配套和短交期；施耐德需前置到业主/设计院规范和总包品牌库阶段", "认为竞品哪些方面更有优势", ["ZH2", "ZH3"]),
                ],
            },
            {
                "category": "其他供应商",
                "rows": [
                    _supply_row("其他器件供应商", "公开资料未披露核心器件供应商；洛阳双瑞预付供应商清单列示中环为设备供应商，金额 544 万元，占预付款期末余额 2.99%", "其他核心供应商", ["ZH7"]),
                    _supply_row("柜体供应商", "官网产品线覆盖开关柜、配电箱、桥架、母线槽、箱式变电站等，且披露数控钣金设备和母线加工/铆接装配生产线，推测具备柜体/配套产品自制能力；自产/外购比例需现场核验", "是否自产柜体或外购", ["ZH15", "ZH16"]),
                    _supply_row("供应链稳定性", "公开资料未披露稳定供货渠道；跨区域项目、央企合格供应商线索、守合同重信用和AAA资信说明有项目准入基础，但仍需信用、交付和售后记录核验", "是否有稳定供货渠道", ["ZH3", "ZH5", "ZH13", "ZH14"]),
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


def _chint_competitor_solution_comparison() -> list[dict[str, Any]]:
    return [
        {
            "business_need": "常规低压元器件与工业OEM回路",
            "demand_trigger": "正泰在常规低压、工业OEM和长尾渠道中重视成本、现货、渠道覆盖、BOM替代性和快速响应。",
            "schneider_solution": "ComPacT NSX/NSXm、Acti9、TeSys、EcoStruxure Power Commission；强调保护配合、品牌背书、调试报告和数字化维护。",
            "competitor_solution": "ABB Tmax XT/SACE、西门子 3VA、伊顿 NZM；国产德力西、良信、常熟开关等更偏价格、渠道和短交期竞争。",
            "schneider_strength": "在高可靠保护、软件调试、项目文档和国际业主认可上更有利，适合切入关键回路和标准化BOM。",
            "schneider_gap": "常规回路价格、交期和渠道下沉不一定占优，需避开纯价格战，用规范、质量和生命周期成本证明价值。",
            "source_ids": ["S4", "S56", "SE3", "SE6", "SI2", "ET1"],
        },
        {
            "business_need": "高端ACB、进线/母联与关键负载",
            "demand_trigger": "数据中心、机场、轨交、石油石化、高端商业楼宇等项目更看重高分断、选择性保护、通信、可靠性和验收资料。",
            "schneider_solution": "MasterPacT MTZ、MicroLogic X、EcoStruxure Power Commission、BlokSeT；覆盖保护、测量、通信、维护诊断和调试交付。",
            "competitor_solution": "ABB SACE Emax 2/Ekip、Siemens SENTRON 3WA/3WL、Eaton IZM；均在高端ACB与关键配电场景形成同档竞争。",
            "schneider_strength": "ACB市场心智、数字化控制单元、配电柜调试闭环和服务网络强，适合前置到业主品牌库和设计院技术规范。",
            "schneider_gap": "ABB/西门子在部分国际业主、老项目替换和既有柜型生态中有存量优势，需提前锁定品牌库和替换策略。",
            "source_ids": ["S31", "S56", "S58", "SE6", "SE9", "ABB1", "SI1", "ET3"],
        },
        {
            "business_need": "低压成套、MCC和授权柜型",
            "demand_trigger": "盘厂项目需要柜型验证、弧光/温升/分隔、抽屉单元、BOM准确性、FAT/SAT资料和可复制交付。",
            "schneider_solution": "BlokSeT/Prisma/低压配电系统，叠加 EcoStruxure Power Commission 和中压 Power Build 的配置、BOM、SLD、技术规格输出。",
            "competitor_solution": "ABB MNS/MNS Digital、Siemens SIVACON S8/SIMARIS、Eaton xEnergy；强调模块化、数字监测、弧光防护和授权盘厂生态。",
            "schneider_strength": "适合用授权柜型、标准化BOM、调试报告、技术文件和服务SLA帮助盘厂提升高端项目中标确定性。",
            "schneider_gap": "ABB MNS、西门子 SIVACON、伊顿 xEnergy 在部分业主规范和授权生态中同样强势，施耐德需把柜型价值与项目交付效率讲清。",
            "source_ids": ["S34", "SE5", "SE6", "SE8", "ABB2", "SI3", "ET2"],
        },
        {
            "business_need": "数据中心、通信与智算高可靠供配电",
            "demand_trigger": "正泰已有华为、维谛、中国移动、中国铁塔和宁夏中卫云数据中心等公开案例，说明其正在强化数据中心/通信场景。",
            "schneider_solution": "数据中心供配电、UPS、关键电源、EcoStruxure 监控与服务，叠加 MasterPacT/ComPacT/BlokSeT 做低压关键回路。",
            "competitor_solution": "ABB MNS/Ability、西门子 SIVACON/SENTRON、伊顿 xEnergy/IZM/NZM 均能覆盖关键负载配电与监控；国产品牌以交期和国产化适配争夺项目。",
            "schneider_strength": "数据中心端到端方案、关键负载经验、监控服务和全球客户背书强，适合从业主规范和运维可用性切入。",
            "schneider_gap": "正泰在通信客户和国产化场景有案例积累，施耐德需用可靠性、能效、运维和服务闭环证明溢价。",
            "source_ids": ["S22", "S29", "S35", "S36", "S51", "SE2", "ABB2", "SI3", "ET2"],
        },
        {
            "business_need": "石油石化、轨交、机场等高可靠工程",
            "demand_trigger": "这类项目通常存在业主/设计院推荐品牌、EPC技术协议、验收资料、可靠性和长期备件服务约束。",
            "schneider_solution": "MasterPacT/ComPacT、BlokSeT、EcoStruxure Power、现场服务与备件SLA，适合锁定关键回路、智能框架和项目验收文件。",
            "competitor_solution": "ABB、西门子、伊顿在同类高端工程中具备国际品牌、认证和柜型生态；正泰以中石油长庆油田、中国中铁、武汉天河机场等案例补强国产高端背书。",
            "schneider_strength": "在高端BOM、国际规范、关键负载运维和设计院技术澄清上有优势，可把品牌库变成项目采购入口。",
            "schneider_gap": "正泰的央企/基础设施案例会增强业主信心；施耐德需持续提供项目级证据，而不是只讲品牌。",
            "source_ids": ["S25", "S26", "S39", "S56", "S58", "SE5", "SE7"],
        },
        {
            "business_need": "智能配电、能效管理与预测维护",
            "demand_trigger": "终端客户希望从一次设备采购转向可视、可测、可调、可维护；正泰也在泰无界、正泰物联和南网智能配电案例中强化数字化。",
            "schneider_solution": "EcoStruxure Power、Power Monitoring/Power Operation、EcoStruxure Power Commission、数字服务与预测性分析。",
            "competitor_solution": "ABB Ability Energy Manager/MNS Digital，西门子 SIMARIS control/SIVACON/SENTRON，伊顿 Power Xpert/DIAGNOSE/xEnergy，国产方案聚焦物联平台和能碳管理。",
            "schneider_strength": "端到端架构、开放通信、调试报告、资产健康与服务中心能力强，适合以运行价值和风险降低说服业主。",
            "schneider_gap": "正泰本土物联平台和价格优势会在国产化/成本敏感场景形成压力，需把数字化价值绑定到停机损失、能效和安全。",
            "source_ids": ["S37", "S38", "S52", "S53", "SE6", "SE7", "ABB2", "SI3", "ET2"],
        },
        {
            "business_need": "盘厂设计、报价、生产与交付效率",
            "demand_trigger": "盘厂KA更关心从方案、报价、BOM、SLD、技术规格、订货、装配、调试到验收的效率和错误率。",
            "schneider_solution": "EcoStruxure Power Build Medium Voltage、EcoStruxure Power Commission、标准化授权柜体、Track/Kitting、FAT/SAT资料包和服务支持。",
            "competitor_solution": "西门子 SIMARIS Suite/SIVACON、ABB Empower/MNS、伊顿 xEnergy Configurator；国产品牌更多靠本地工程师、快速报价和灵活交付。",
            "schneider_strength": "可把工具链、柜型授权、调试报告和售后闭环绑定为盘厂效率提升方案，适合从项目早期设计和报价阶段介入。",
            "schneider_gap": "若只卖单个元件，难以对抗正泰和国产品牌的价格/交期；需把工具和服务嵌入盘厂日常流程。",
            "source_ids": ["S54", "KB1", "SE6", "SE8", "ABB1", "SI1", "SI3", "ET2"],
        },
    ]


def _chint_non_competitor_supplier_segments() -> list[dict[str, Any]]:
    return [
        {
            "segment": "银点/电接触材料",
            "public_evidence": "宏丰股份招股书披露其向正泰电器提供银触点、电接触功能复合材料、复合铆钉、复合带材、熔断片等，并曾稳居正泰前五名供应商，2011年签订5年长期采购合同。",
            "business_meaning": "银点和电接触材料直接影响断路器、接触器、继电器、开关等低压产品可靠性，是非整机竞品但极关键的上游。",
            "se_implication": "对施耐德销售不是竞品替代问题，而是质量、温升、寿命、错混料、变更管控和FAT/SAT证据问题；可在高端BOM中强调关键材料与验证标准。",
            "source_ids": ["S63"],
        },
        {
            "segment": "铜材/银点/钢材/塑料",
            "public_evidence": "信用评级资料披露低压板块原料种类超10万种，银、铜材、钢材、塑料合计约占成本50%；银点前五大供应商占比超95%，铜材前五大约80%，钢材和塑料前五大约40%-45%。",
            "business_meaning": "这类原材料决定正泰常规低压的成本、价格弹性和交期基础；其中银点、铜材集中度高，对价格波动和供应连续性敏感。",
            "se_implication": "施耐德要避免和正泰在常规低压上纯价格对打，可把材料价格波动、质量一致性和全生命周期可靠性转成高端项目价值论证。",
            "source_ids": ["S62"],
        },
        {
            "segment": "低压断路器附件/结构件",
            "public_evidence": "苏州未来电器招股书显示其低压断路器附件供应链可同时服务正泰、施耐德、西门子、ABB等客户，说明附件环节存在专业化供应商和多品牌共用供应生态。",
            "business_meaning": "附件、机构件、熔断片、冲件等不是主品牌竞品，但会影响交付齐套、产品一致性、认证和售后质量。",
            "se_implication": "当终端项目关注可靠性和认证时，可从附件一致性、追溯、关键件质量协议和变更审批切入，而不是只比较整机价格。",
            "source_ids": ["S57"],
        },
        {
            "segment": "物联网/电子元件/仪表传感",
            "public_evidence": "正泰物联供应商大会披露采购与质量负责人强调数字化供应链、供应商质量管理，以及环保管控、变更管控、错混料管控；正泰物联产品覆盖电能管理、配电监控、电气安全、新能源、智能网关等。",
            "business_meaning": "智能配电、网关、仪表和传感器供应链决定正泰从元件向数字化方案升级的速度，也会放大软件、通信和数据质量要求。",
            "se_implication": "施耐德应以EcoStruxure、通信点表、调试报告、数据质量和预测维护服务建立差异，而不是只用硬件品牌竞争。",
            "source_ids": ["S42", "S53"],
        },
        {
            "segment": "采购云/数字化采购生态",
            "public_evidence": "正泰物联会议披露采购云平台重构升级、研采供协同降本；外部采购数字化案例称正泰产业链涉及超5000家供应商、年采购金额逾300亿元，正在推进供应商管理、寻源、数据集成和合规透明化。",
            "business_meaning": "供应商池大、品类多、区域复杂，平台化采购会增强正泰成本管控、寻源透明和交付协同能力。",
            "se_implication": "施耐德需要前移到设计院/业主规格和项目BOM，后移到调试、服务和备件SLA，避免在采购平台询价阶段才被动比价。",
            "source_ids": ["S42", "S61"],
        },
        {
            "segment": "柜体/钣金/母排与成套关联主体",
            "public_evidence": "正泰集团信用评级资料披露正泰电气高压板块覆盖变压器、充气柜、中压开关、高压开关、低压成套开关设备、电线电缆、电力自动化系统等；正泰盘厂合作伙伴页面强调全产业链服务、标准化柜体尺寸、接线安装和验收。",
            "business_meaning": "柜体并非简单外采项，需区分集团内成套能力、项目盘厂、外协钣金/母排和业主指定柜型。",
            "se_implication": "施耐德应把机会落在授权柜型、关键回路元件、数字化调试、FAT/SAT资料和业主验收标准，而不是只判断是否外购柜体。",
            "source_ids": ["S54", "S62"],
        },
        {
            "segment": "可持续供应链/绿色采购",
            "public_evidence": "正泰官网供应链社会责任资料披露其建设覆盖商业行为、采购管理、伙伴治理、权益保障等维度的供应链社会责任管控体系；可持续发展页面提出2030年供应商可持续采购、评估认证和减碳承诺目标。",
            "business_meaning": "绿色采购会影响供应商准入、主要供应商考核和海外/国际客户项目认证。",
            "se_implication": "施耐德可在绿色工厂、碳数据、能源管理、ISO体系和供应商减碳材料方面形成差异化话题。",
            "source_ids": ["S50", "S59"],
        },
    ]


def _chint_cabinet_supplier_evidence() -> list[dict[str, Any]]:
    return [
        {
            "segment": "自有低压箱体/成套产品",
            "public_evidence": "正泰官网产品页列示POWGRID-S授权低压配电箱及控制箱，定位为面向国内分配电市场研发的低压成套产品；PZ30系列页面列示明/暗装式配电箱箱体。",
            "judgement": "正泰并非只采购外部柜体，至少在低压配电箱/控制箱层面有自有产品与标准化箱体体系。",
            "se_implication": "施耐德要切入这类场景，需前置到终端业主标准、设计院图纸和关键元件BOM，而不是等柜体外协环节。",
            "source_ids": ["S64", "S65"],
        },
        {
            "segment": "低压成套柜解决方案",
            "public_evidence": "正泰数据中心低压配电室方案披露可提供从塑壳断路器、框架断路器到低压成套柜的低压配电系统，并强调元器件及柜体品牌统一。",
            "judgement": "在数据中心等项目型场景，正泰会以元件+柜体+系统方案形式竞争，而非单纯低压元件供货。",
            "se_implication": "施耐德机会在高可靠、智能化、监控点表、关键回路和服务SLA，要按系统方案对系统方案来打。",
            "source_ids": ["S16"],
        },
        {
            "segment": "盘厂伙伴生态",
            "public_evidence": "正泰盘厂合作伙伴页面披露其牵头盘厂编制低压动力配电及控制箱设计导则，统一柜体尺寸、壳体制造、接线安装及验收标准。",
            "judgement": "正泰可以通过盘厂生态组织柜体制造和项目交付，外部盘厂既是供应节点也是市场触达节点。",
            "se_implication": "施耐德需要识别哪些盘厂同时在正泰生态和施耐德授权生态中出现，按授权柜型和项目BOM做边界管理。",
            "source_ids": ["S54"],
        },
        {
            "segment": "关联成套主体能力",
            "public_evidence": "正泰集团债券/评级资料披露正泰电气高压板块覆盖变压器、充气柜、中压开关、高压开关、组合电器、低压成套开关设备、电线电缆、电力自动化系统等。",
            "judgement": "集团内部存在覆盖中低压成套和输配电设备的关联主体，柜体能力需要按上市公司本体、正泰电气、区域盘厂和项目公司拆开核验。",
            "se_implication": "施耐德内部CRM/订单应按法人主体、授权范围、项目号和柜型照片核验，避免把关联主体能力误判为外部供应商。",
            "source_ids": ["S62"],
        },
        {
            "segment": "质量/测试能力",
            "public_evidence": "正泰质量信用报告披露可对低压成套柜开展系统级短路、温升、EMC、环境等实验，并持续推进质量数字化。",
            "judgement": "其柜体/成套能力不仅是钣金加工，还包含系统级验证和质量体系支撑。",
            "se_implication": "施耐德要用IEC/GB测试证据、授权柜型验证、FAT/SAT和数字化调试报告形成更高门槛。",
            "source_ids": ["S68"],
        },
        {
            "segment": "外协柜体/钣金/母排",
            "public_evidence": "公开资料未披露正泰本体外协柜体、钣金、母排、喷涂、桥架、线束供应商名单；现有证据只支持“可能存在外协环节”，不能直接填具体供应商名称。",
            "judgement": "外协供应商名单仍属于内部补充项，需从采购台账、供应商准入清单、项目BOM、柜体铭牌和出厂资料核验。",
            "se_implication": "后续访谈应追问柜体外协比例、关键外协供应商、质量索赔、变更审批和项目交付责任边界。",
            "source_ids": ["S1", "S54", "S62"],
        },
    ]


def _chint_supply_channel_evidence() -> list[dict[str, Any]]:
    return [
        {
            "segment": "分销渠道覆盖",
            "public_evidence": "正泰官网分销商页面披露500+一级网点、5000+规模二级网点、超100000家终端渠道。",
            "judgement": "常规低压和标准箱体具备很强下沉覆盖和现货服务能力，是正泰相对施耐德的重要供应渠道优势。",
            "se_implication": "施耐德不要在长尾通用市场做纯价格消耗，应选择关键负载、业主指定和服务价值场景。",
            "source_ids": ["S4"],
        },
        {
            "segment": "数字化下单/库存协同",
            "public_evidence": "官网分销商页面披露营销云、泰乐购、ECP等系统覆盖客户、采购、销售、库存、应收账款等模块；财联社报道也提到泰乐购支持产品查询、订单下达、订单追踪、库存查询。",
            "judgement": "正泰对分销客户的订单、库存和应收协同已经平台化，能提升渠道响应和客户粘性。",
            "se_implication": "施耐德应把项目前期配置、报价、调试、报告和备件服务工具链前置，避免只在询价环节被比交期与价格。",
            "source_ids": ["S4", "S67"],
        },
        {
            "segment": "区域销售总公司",
            "public_evidence": "蓝海行动报道披露正泰通过区域销售总公司、区域行业业务销售公司、省级科创平台等方式推进渠道扁平化、集约化、平台化。",
            "judgement": "区域销售总公司增强正泰区域价格、库存、客户资源和行业项目协同能力。",
            "se_implication": "施耐德区域销售需建立共同终端项目地图，提前锁定设计院、业主品牌库和EPC技术协议。",
            "source_ids": ["S67"],
        },
        {
            "segment": "智慧物流/前置仓",
            "public_evidence": "财联社报道披露正泰扩建智慧分拨中心，形成全国物流核心骨干仓配网络，并规划区总前置仓和配送型服务商体系，加强最后一公里服务能力。",
            "judgement": "常规物料和标准化箱体的交付响应能力较强，特别适合区域短交期、维修替换和分销项目。",
            "se_implication": "施耐德需以关键物料齐套、项目级交期承诺、备件SLA和现场服务响应来对冲。",
            "source_ids": ["S67"],
        },
        {
            "segment": "采购云/供应商治理",
            "public_evidence": "正泰物联供应商会议提到采购云平台升级、数字化供应链、研采供协同降本；采购数字化案例称其产业链涉及超5000家供应商、年采购金额逾300亿元。",
            "judgement": "正泰采购端供应商池大、品类多，平台化采购有助于降低寻源不透明和跨区域协同成本。",
            "se_implication": "施耐德若被放入采购云询价，就容易陷入价格比较；更应在项目技术规范阶段形成不可替代条件。",
            "source_ids": ["S42", "S61"],
        },
        {
            "segment": "关键材料稳定性",
            "public_evidence": "正泰集团评级资料披露低压板块银点前五大供应商采购金额占比超95%，铜材前五大约80%，钢材和塑料前五大约40%-45%。",
            "judgement": "集团总供应商集中度不高，但银点、铜材等关键材料存在结构性集中和价格波动暴露。",
            "se_implication": "在高端项目中可把供应链稳定、材料一致性、追溯和变更管控作为风险议题，而不是只讨论元件价格。",
            "source_ids": ["S62"],
        },
        {
            "segment": "可持续供应链准入",
            "public_evidence": "正泰供应链社会责任页面披露其将ESG表现纳入采购决策与供应商管理，并以可持续采购政策约束商业伙伴。",
            "judgement": "绿色采购和供应商ESG会影响其海外/国际客户项目和大型业主准入。",
            "se_implication": "施耐德可围绕低碳配电、碳数据、绿色工厂和供应链减碳材料建立差异化沟通。",
            "source_ids": ["S59"],
        },
    ]


def _supply_row(
    field_name: str,
    value: str,
    description: str,
    source_ids: list[str],
    comparison_rows: list[dict[str, Any]] | None = None,
    supplier_segments: list[dict[str, Any]] | None = None,
    evidence_title: str = "",
    evidence_subtitle: str = "",
    evidence_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    row = {
        "field": field_name,
        "value": value,
        "description": description,
        "source_ids": source_ids,
    }
    if comparison_rows:
        row["comparison_rows"] = comparison_rows
    if supplier_segments:
        row["supplier_segments"] = supplier_segments
    if evidence_rows:
        row["evidence_title"] = evidence_title
        row["evidence_subtitle"] = evidence_subtitle
        row["evidence_rows"] = evidence_rows
    return row


def _customer_resources(customer: str) -> list[dict[str, Any]]:
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_resources(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "客户结构",
                "rows": [
                    _resource_row("主要客户类型", "正泰客户类型与施耐德重点客户高度重叠：终端业主、总包/集成商、设计院规范影响方、行业大客户、经销商/分销商、海外本土渠道和项目客户并存。盘厂KA视角需建立“共同终端客户/正泰优势客户/施耐德可前置规格客户/需内部核验客户”四类清单", "终端业主/总包/设计院/经销商", ["S1", "S4", "SE1"]),
                    _resource_row("客户行业分布", "电力、电网、新能源、数据中心、通信、建筑楼宇、轨道交通、工业OEM、锂电池、充电桩、半导体、储能、海外电力与基建等，均是施耐德关键战场；应按行业标注终端业主、柜型/BOM、设计院/EPC、系统集成商和服务责任人", "建筑/工业/电力/新能源/交通等", ["S1", "SE2"]),
                    _resource_row("客户地域分布", "服务全球140+国家和地区；国内重点收入区域包括华东、华中、华北、华南等，海外覆盖欧洲、亚太、西亚非、拉美、北美。正泰海外本地化会改变施耐德全球服务优势的使用方式，应按区域叠加认证、交付和本地服务差异", "主要服务区域", ["S1", "S3", "S5"]),
                    _resource_row("头部客户名单", "正泰年报未披露前十大客户名称，但官网客户成功案例可核验代表性客户与合作项目：华为战略合作，覆盖5G高密嵌入式开关电源、UPS柜、汇流箱、数据中心锂电柜、精密空调柜、箱变等；中国移动战略合作，应用CB系列小型断路器、NC5交流接触器、JZX-22F小型电磁继电器；维谛合作项目，面向关键数字基础设施场景供应断路器和塑壳断路器；中国铁塔成都分公司2021年户外机柜智能控制节能设备改造项目；远景能源风电主控柜系统解决方案；牧原集团动环监控系统；中石油长庆油田采油采气项目，覆盖采油控制柜、升压站、净化厂、管道输送中心等；中国中铁隧道集团全国集采配电箱项目；南网负荷管理系统方案和南网智能配电系统方案，涉及深圳供电局、南网数字集团和南网V3.0智能配电系统；福建电力分布式光伏群调群控试点、山东电力低压分布式光伏并网方案；武汉天河机场第三跑道配套机坪及设施工程低压柜项目。建议进一步映射这些客户是否为施耐德现有KA、共同客户或正泰优势客户", "前10大客户名称及行业", ["S21", "S22", "S23", "S24", "S25", "S26", "S27", "S28", "S29", "S35", "S36", "S37", "S38", "S39"]),
                    _resource_row("头部客户收入占比", "2025年前五名客户销售额228.51亿元，占年度销售总额38.64%；其中关联方销售额27.80亿元，占4.70%；客户集中度中等，说明正泰既有大客户突破也有渠道长尾能力。施耐德不能只盯少数KA，还要把盘厂BOM、分销、行业项目和关联方项目一起看", "前10大客户收入贡献", ["S1"]),
                ],
            },
            {
                "category": "客户关系",
                "rows": [
                    _resource_row("客户粘性", "低压分销渠道包括500+一级网点、5000+规模二级网点和超100,000家终端渠道，经销商“亿元俱乐部”超过50家；这种渠道粘性会影响盘厂BOM和长尾项目品牌选择，施耐德需要在关键项目和授权/标准柜型中形成非价格粘性", "客户复购率/合作年限", ["S1", "S4", "S19"]),
                    _resource_row("客户获取方式", "正泰以“分销网络+行业大客户+海外本土化+集团能源生态”获客，国内依靠渠道覆盖和重点客户深耕，海外依靠区域本土化、能源/电力项目和数据中心项目；施耐德需用设计院规范、业主标准、技术澄清、FAT/SAT和高端服务前置经营", "招投标/关系介绍/市场开发等", ["S1", "S4", "SE2"]),
                    _resource_row("客户满意度", "公开资料未披露系统满意度；官网质量信用资料披露客服热线、官网、微信公众号、小程序等服务闭环，说明其在服务触点上持续补强。施耐德需在共同终端客户中访谈响应、交付、调试、售后和运维评价，判断正泰项目链路的真实满意度", "客户对其服务/产品质量的评价", ["S12", "S19"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "客户结构",
                "rows": [
                    _resource_row("主要客户类型", "官网披露产品应用于电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信等领域；外部线索补充政府/公共事业、化工/环保、居民小区供配电、轨交/装备制造、电子厂房、港口电气、央企供应链和项目总包/业主类客户", "终端业主/总包/设计院/经销商", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户行业分布", "官网行业覆盖包括电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信；公开项目进一步指向公共事业、造纸、化工/石化/环保、住宅与公共建筑、轨交/装备制造、电子信息制造、港口、水利、电建/核电工程供应链等", "建筑/工业/电力/新能源/交通等", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户地域分布", "官网称产品畅销全国各地；公开项目线索覆盖山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等，区域强关系需围绕扬中/镇江及重点项目省份继续访谈", "主要服务区域", ["ZH15", "ZH2", "ZH3"]),
                    _resource_row("头部客户名单", "公开资料未披露前十大客户；可识别项目/客户线索包括山东裕龙石化、常州新东化工、山鹰系项目、合肥居民小区供配电改造、中车宝鸡时代、中国电建核电工程、洛阳双瑞、南京国博电子、华越镍钴、港口/污水处理项目业主等", "前10大客户名称及行业", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH7"]),
                    _resource_row("头部客户收入占比", "非上市公司公开资料未披露前十客户收入贡献；公开项目金额仅可作规模侧影，如合肥居民小区供配电设施改造框架项目2,274.8172万元等，需结合内部订单和客户访谈补齐", "前10大客户收入贡献", ["ZH3"]),
                ],
            },
            {
                "category": "客户关系",
                "rows": [
                    _resource_row("客户粘性", "公开资料未披露客户复购率和合作年限；央企合格供货商清单、跨项目中标/候选线索，以及守合同重信用/AAA资信荣誉说明其具备项目准入基础，但需内部项目复盘确认粘性", "客户复购率/合作年限", ["ZH3", "ZH5", "ZH13", "ZH14"]),
                    _resource_row("客户获取方式", "官网未披露销售渠道细节；结合招采线索，以招投标、央企供应商准入、项目型成交为主，部分项目可能由业主/设计院规范、总包采购和区域关系共同驱动", "招投标/关系介绍/市场开发等", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _resource_row("客户满意度", "官网称产品畅销全国各地并深受用户好评，但未披露系统满意度数据；威海项目评分、守合同重信用和质量管理荣誉可作项目资信侧影，仍需访谈业主/总包与施耐德销售团队", "客户对其服务/产品质量的评价", ["ZH15", "ZH3", "ZH13", "ZH14"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_sales_market(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "销售体系",
                "rows": [
                    _sales_row("销售团队规模", "2025年年报披露销售人员3,891人，经销商“亿元俱乐部”规模扩充至50家以上；正泰销售组织会同时影响分销现货、盘厂BOM、行业项目和海外交付，施耐德需按通路和项目阶段拆分触点", "销售人员数量", ["S1", "S4"]),
                    _sales_row("销售模式", "直销、经销/分销、行业大客户、海外本土化渠道与项目型销售并行；其打法覆盖施耐德从分销到KA项目的主要通路，应按“分销现货、盘厂/OEM、终端KA、海外认证、数字化方案”建立项目经营图", "直销/经销/代理", ["S1", "S4", "S20"]),
                    _sales_row("销售区域划分", "国内以华东、华中、华北、华南等区域经营，海外覆盖欧洲、亚太、西亚非、拉美、北美，并推进全球区域本土化；施耐德需按区域比较正泰报价、交期、认证、服务能力和设计院/EPC影响力", "如何划分销售区域", ["S1", "S5"]),
                    _sales_row("销售渠道", "拥有500+一级网点、5000+规模二级网点和超100,000家终端渠道，同时发展欧洲专业批发商、海外区域渠道、微信公众号、官网、小程序等触点；这会影响施耐德分销份额、盘厂BOM默认品牌和长尾项目触达", "自有渠道/合作渠道", ["S1", "S4", "S11", "S12"]),
                    _sales_row("招投标能力", "公开资料未披露投标成功率；但电网、新能源、数据中心、轨交、海外电力等项目线索显示其具备行业项目销售能力。施耐德应沉淀正泰参与项目的招标条款、报价区间、品牌库位置、柜型/BOM和赢丢原因", "投标成功率、标书制作能力", ["S1", "S19"]),
                ],
            },
            {
                "category": "市场覆盖",
                "rows": [
                    _sales_row("覆盖省份", "国内业务覆盖全国主要区域，集团制造与业务布局涉及温州、上海、嘉兴、沈阳、咸阳、济南、合肥、武汉、南阳、盐城等；对施耐德应形成省区级正泰强弱热力图", "业务覆盖哪些省份", ["S1", "S5"]),
                    _sales_row("重点市场", "华东、华中和海外为收入高贡献区域；海外重点拓展欧洲、亚太、西亚非、拉美、北美，北美聚焦数据中心项目。施耐德防守重点是华东/华中分销、海外认证和北美数据中心相关项目", "核心市场区域", ["S1", "SE2"]),
                    _sales_row("市场定位", "正泰已从中低端/大众市场向中高端、行业项目和海外市场上移；行业研究认为施耐德仍在高端市场具优势，但正泰产品线、研发和渠道能力正在追赶。盘厂KA经营要分清常规低压、关键负载、国际认证、智能配电和服务型项目的定位差异", "高端/中端/低端市场", ["S19", "S20"]),
                    _sales_row("品牌影响力", "年报称正泰在国内低压电器工业OEM、建筑、个人用户三大细分市场位列第一；官网白皮书新闻披露其在能源电力、工业OEM和国产低压出口等维度表现突出。对施耐德而言，它既是品牌替代力量，也是终端项目链路中必须画像的盘厂生态型KA", "在当地市场的知名度", ["S1", "S12", "S19"]),
                ],
            },
            {
                "category": "价格策略",
                "rows": [
                    _sales_row("价格水平", "公开资料未披露具体价格水平；结合规模化制造、原材料成本、分销网络和本土品牌定位，正泰在常规低压项目预计具备较强价格能力，需用施耐德项目报价、BOM和成交复盘验证。关键项目不应只比较单价，还要比较调试、停机、认证和运维成本", "相对市场均价的高低", ["S20"]),
                    _sales_row("价格敏感度", "正泰对常规低压价格竞争敏感且有能力主动降价抢份额；施耐德应避免在标准品上硬拼价格，把资源集中到业主指定、海外认证、数据中心、关键电源、智能配电、软件服务和生命周期价值", "对价格竞争的态度", ["S1", "SE1", "SE2"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "销售体系",
                "rows": [
                    _sales_row("销售团队规模", "公开资料未披露销售人员数量；招聘页披露市场部、驻外办事处和销售部，项目线索显示其至少具备跨区域招采响应能力", "销售人员数量", ["ZH2", "ZH3", "ZH9"]),
                    _sales_row("销售模式", "以项目型直销、招投标、总包/业主项目采购和央企供应商准入为主；公开资料未确认经销/代理体系，施耐德应按项目经理/销售负责人/总包接口人进行角色打标", "直销/经销/代理", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH9"]),
                    _sales_row("销售区域划分", "公开资料未披露内部销售区域划分；公开项目跨山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地，推测按区域项目和行业客户并行推进", "如何划分销售区域", ["ZH2", "ZH3"]),
                    _sales_row("销售渠道", "官网未披露经销/代理体系；可识别渠道包括公共资源交易、机电设备采购平台、中车/电建等供应商体系、项目总包链条和区域驻外办事处；施耐德应把设计院/业主品牌库作为前置渠道", "自有渠道/合作渠道", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5", "ZH9"]),
                    _sales_row("招投标能力", "公开项目包含威海高压开关柜第一中标候选、淮河入海水道二期高低压开关柜及变压器候选、合肥居民小区供配电改造框架、中车母线槽候选、电建核电合格供应商，以及2024-2025配电箱、低压柜、仪表桥架、港口电气、污水处理等招采线索；投标成功率未公开", "投标成功率、标书制作能力", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH11"]),
                ],
            },
            {
                "category": "市场覆盖",
                "rows": [
                    _sales_row("覆盖省份", "官网称产品畅销全国各地；公开项目/采购线索覆盖山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地，并有淮安、常州、南京、港口、化工等项目线索；具体收入覆盖省份需内部订单和客户访谈核验", "业务覆盖哪些省份", ["ZH15", "ZH2", "ZH3", "ZH11", "ZH12"]),
                    _sales_row("重点市场", "官网披露电力石化、轻纺、机电、煤炭、能源、交通、冶金、建筑、通信等应用市场；外部线索补充公共事业/供热、水利、造纸、化工/石化/环保、居民小区供配电改造、轨交/装备制造、电子厂房、港口电气、央企电建供应链", "核心市场区域", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5"]),
                    _sales_row("市场定位", "更偏项目交付型成套/配套供应商和母线/柜体/桥架完整产品链制造商，官网称其为生产成套电器设备骨干企业、母线制造商；不是全国性低压元器件品牌龙头，施耐德经营重点应放在授权柜型、项目指定和标准BOM", "高端/中端/低端市场", ["ZH15", "ZH16", "ZH17"]),
                    _sales_row("品牌影响力", "公开资料未披露品牌知名度排名；在扬中电气产业集群、区域工程和特定项目准入中具备一定影响力，高企、创新型中小企业、上云企业、守合同重信用、AAA资信等荣誉可增强区域信用背书", "在当地市场的知名度", ["ZH2", "ZH3", "ZH10", "ZH14"]),
                ],
            },
            {
                "category": "价格策略",
                "rows": [
                    _sales_row("价格水平", "公开资料不能确认价格水平；项目型招投标客户通常面对总包/业主比价，建议用历史报价、中标价、竞品报价和施耐德赢丢单复盘验证", "相对市场均价的高低", ["ZH2", "ZH3"]),
                    _sales_row("价格敏感度", "预计价格敏感度较高；但在高压柜、化工、电建、轨交、公共设施等项目中，认证、供货履约、业主指定、智能配电能力和售后响应也会影响成交", "对价格竞争的态度", ["ZH3", "ZH4", "ZH5", "SE1"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_org_decision(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "公开资料可确认上市公司董事会、战略与可持续发展委员会、可持续发展办公室三级治理架构；盘厂KA经营需另建项目影响图：智慧电器、绿色能源、国际营销、行业项目、研发/质量、供应链、生产/服务、渠道团队，以及外部业主/设计院/EPC/系统集成商", "部门设置、汇报关系", ["S1", "S13"]),
                    _org_row("决策层级", "建议按集团战略层、上市公司经营层、事业部/子公司经营层、区域/行业项目层四层分析内部动作；施耐德经营还需叠加终端业主、设计院、EPC/总包、盘厂/OEM、分销商和服务团队的外部影响链", "决策流程有几级", ["S1", "S3", "S13"]),
                    _org_row("关键部门", "重点不只是采购部，而是决定项目进入方式的部门：智慧电器产品线、区域/行业销售、国际业务、数据中心/新能源项目团队、研发技术、质量认证、供应链、渠道管理和服务团队", "采购部、技术部、生产部、销售部", ["S1", "S3", "S12", "S13"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "公开确认的上市公司决策层包括南存辉（董事长、执行公司事务的董事、正泰集团董事长）、陈国良（董事、总裁，曾任低压电器事业部、企管部、销售中心等负责人）、朱信敏（董事、正泰集团总裁）、陆川（董事，绿色能源板块关键负责人）、南尔（董事、副总裁，诺雅克/海外高端低压链路）、林贻明（职工董事、副总裁、财务总监）和潘洁（副总裁、董事会秘书）。盘厂KA研究应把这些人作为战略、产品、海外和行业项目方向的观察点，而不是直接采购触点", "姓名、背景、管理风格", ["S1", "S40"]),
                    _org_row("采购负责人", "正泰电器本体采购负责人姓名和授权边界未在年报或官网直接披露；公开线索可确认倪逢湖为正泰集团采购部总经理，正泰物联会议还披露采购部负责人和质量管理部负责人参与供应链建设专题。该线索仅可作为集团采购规则、供应商质量准入和研采供协同候选触点，不能直接等同正泰电器本体采购决策人，需用施耐德内部拜访和项目台账核验", "姓名、职位、决策权限", ["S42"]),
                    _org_row("技术负责人", "可公开确认的技术/标准候选触点包括何胜（正泰低压智能电器研究院院长）、李俐（正泰电器总裁助理、集团研究院副院长线索）、徐晓东（正泰电器市场部副总经理、高级工程师，SAC/TC205全国建筑物电气装置标准化技术委员会副主任委员）和南尔（诺雅克/海外高端低压经历）。施耐德应重点研究其低压新品、智能配电、标准化、海外认证、数据中心/新能源方案，以及这些能力如何影响设计院/EPC规范", "姓名、职位、技术偏好", ["S40", "S41", "S43"]),
                    _org_row("生产负责人", "未找到正泰电器生产负责人姓名的权威公开披露；生产/质量候选触点包括吕俊海（正泰电器质量管理部总经理）和李俐（质量管理数字化、智能制造调研交流中被公开提及）。生产侧仍需补齐乐清、松江、海外制造基地以及低压元件、成套、检测校准、交付排产负责人，用于判断其交期、齐套、FAT/SAT和本地化服务能力", "姓名、职位、生产管理风格", ["S12", "S42", "S43"]),
                    _org_row("销售负责人", "销售/市场公开线索包括陈国良（现任总裁，曾任销售中心总经理，并在高中低压一体化营销大会作中国区营销工作主题报告）、李明（正泰集团市场部总经理）和徐晓东（正泰电器市场部副总经理）。区域负责人和行业负责人未逐一公开，应按区域、行业、海外、数据中心/新能源项目制继续拆分，因为这些团队决定正泰进入终端项目、盘厂BOM和设计院/EPC链路的路径", "姓名、职位、市场策略", ["S40", "S41", "S44"]),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "应按“项目影响流程”拆解：终端/项目需求提出后，业主、设计院、EPC/总包、盘厂/OEM、系统集成商和正泰销售/技术团队共同影响BOM与品牌库；价格、交期、国产化、认证、服务承诺和FAT/SAT资料共同推动选择结果", "谁提议-谁评估-谁批准", ["S1", "S4", "S19"]),
                    _org_row("技术选型流程", "技术选型主导方可能是终端业主、设计院、总包品牌库、正泰技术部门标准BOM、海外认证规范或数据中心/储能安全要求；施耐德必须前移到规范阶段，通过SLD、BOM、保护配合、通信点表、调试报告和认证材料争取进入", "技术评审参与方", ["S1", "S3", "SE2", "SE8"]),
                    _org_row("决策周期", "公开资料未披露标准周期；建议按盘厂KA项目阶段拆分：线索/设计院入图、技术澄清、项目询报价、BOM冻结、FAT/预调试、现场SAT/投运、售后复盘七类周期", "从需求到采购决策的周期", []),
                    _org_row("决策影响因素", "价格、自有品牌、国产替代、渠道关系、交期、业主/设计院指定、认证/合规、质量、服务、全球项目支持共同影响；施耐德关键是把认证、可靠性、BOM准确性、FAT/SAT和服务SLA权重前置", "价格/质量/服务/关系等权重", ["S1", "S3", "S13", "S20", "SE8"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "官网设有组织框架栏目，但页面未披露可读取的组织图；招聘介绍披露公司由董事长和总经理领导，下设市场部、驻外办事处、人事部、技术部、采购部、生产部、质保部、销售部、财务部、办公室，并下设4个子公司，完整汇报关系仍需客户确认", "部门设置、汇报关系", ["ZH15", "ZH9", "ZH14"]),
                    _org_row("决策层级", "建议按经营负责人、市场/销售/驻外办事处、技术设计、采购商务、生产/质保五层拆解；招投标项目还要前置业主、设计院、总包和央企供应商准入影响", "决策流程有几级", ["ZH2", "ZH3", "ZH4", "ZH5", "ZH9"]),
                    _org_row("关键部门", "公开可确认市场部、驻外办事处、技术部、采购部、生产部、质保部、销售部等职能；施耐德需补齐各部门负责人、项目授权额度、价格审批、品牌替换权和质量放行边界", "采购部、技术部、生产部、销售部", ["ZH9", "ZH14"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "公开主体信息确认法定负责人王永贵；招聘介绍口径显示公司由董事长和总经理领导，需访谈确认王永贵是否兼任最终经营审批人及其项目决策风格", "姓名、背景、管理风格", ["ZH1", "ZH5", "ZH9"]),
                    _org_row("采购负责人", "采购部职能可由招聘介绍确认，但负责人未公开；需确认价格、账期、交付、竞品替代、年度框架和重大项目采购的审批权限", "姓名、职位、决策权限", ["ZH9"]),
                    _org_row("技术负责人", "技术部职能可由招聘介绍确认，负责人未公开；需确认柜体方案、元器件品牌边界、标准图纸、智能配电需求和业主/设计院指定品牌替换权", "姓名、职位、技术偏好", ["ZH3", "ZH4", "ZH9"]),
                    _org_row("生产负责人", "生产部和质保部职能可由招聘介绍确认；负责人未公开，需核验高压柜、低压柜、母线槽、桥架、配电箱的排产、质检、出厂试验和交付责任", "姓名、职位、生产管理风格", ["ZH9", "ZH14"]),
                    _org_row("销售负责人", "官网联系方式公开联系人蒋子烨及手机、电话、邮箱，可作为商务入口线索；销售部、市场部和驻外办事处职能由招聘介绍确认，需进一步确认区域项目负责人、央企准入维护人、总包关系维护人和招投标策略负责人", "姓名、职位、市场策略", ["ZH18", "ZH2", "ZH5", "ZH9"]),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "项目/销售获取招标或总包需求，技术部校核品牌与参数，采购部组织询价比价和交期确认，生产/质保评估交付风险，经营负责人按项目金额和客户等级批准；具体授权表、价格审批阈值和施耐德替代权限需访谈补齐", "谁提议-谁评估-谁批准", ["ZH3", "ZH4", "ZH9"]),
                    _org_row("技术选型流程", "官网高压柜产品页明确可根据用户或设计院要求选用其他品牌产品，说明业主/设计院规范、总包品牌库、客户技术部、央企合格供应商准入和供应商授权共同影响技术选型；施耐德应确认是否进入常规BOM、设计院偏好、项目指定品牌清单和智能配电方案包", "技术评审参与方", ["ZH16", "ZH3", "ZH4", "ZH5", "ZH9", "SE1"]),
                    _org_row("决策周期", "公开资料未披露标准周期；建议区分桥架/母线槽、配电箱、低压柜、高压柜和央企项目五类，按投标截止、技术澄清、生产排产、交货节点反推周期", "从需求到采购决策的周期", ["ZH2", "ZH3"]),
                    _org_row("决策影响因素", "预计价格、交期、账期、质量、业主指定、设计院规范、本地服务、央企合格供应商准入和项目履约风险共同影响；化工/轨交/水利项目质量与资信权重更高", "价格/质量/服务/关系等权重", ["ZH3", "ZH4", "ZH5", "ZH14"]),
                ],
            },
        ]
    if _is_tianyu_customer(customer):
        return [
            {
                "category": "组织架构",
                "rows": [
                    _org_row("公司组织架构图", "中国电气装备/许继体系内企业；公开报道显示天宇推行阿米巴经营，拆分出 9 个业务单元并公开竞聘业务单元经理；MOM 平台覆盖销售、设计、排产、采购、供应链、仓储、生产全过程", "部门设置、汇报关系", ["TY1", "TY2", "TY8", "TY15"]),
                    _org_row("决策层级", "建议按集团/许继体系、天宇董事长/经营层、9个业务单元、销售/项目、设计技术、采购/供应链、生产/质量/服务七类节点管理；集团供应链和年度物料清单可能影响外部品牌准入", "决策流程有几级", ["TY1", "TY2", "TY6", "TY8"]),
                    _org_row("关键部门", "关键部门包括 9 个业务单元、销售、设计、排产、采购、供应链、仓储、生产、质量/质检、设备/信息运维和项目服务；MOM 数据可成为识别真实流程责任人的线索", "采购部、技术部、生产部、销售部", ["TY1", "TY2", "TY6", "TY15"]),
                ],
            },
            {
                "category": "关键决策人",
                "rows": [
                    _org_row("董事长/总经理", "张红彬为法定代表人/董事长线索，并在集团报道中作为天宇经营改革、文化建设和战略目标的核心发声人；适合作为高层关系与年度合作框架赞助人", "姓名、背景、管理风格", ["TY1", "TY3"]),
                    _org_row("采购负责人", "公开资料未披露采购负责人；采购节点被 MOM 平台覆盖，需确认年度中标物料清单、供应商准入、价格、账期、交期和集团协同采购的审批权限", "姓名、职位、决策权限", ["TY2", "TY6"]),
                    _org_row("技术负责人", "公开资料未披露技术负责人；低压柜岗位显示技术侧参与方案优化、报价审核、元器件型号确认和非年度招标物料提请招标，是施耐德标准BOM切入关键", "姓名、职位、技术偏好", ["TY6"]),
                    _org_row("生产负责人", "公开资料未披露生产负责人；MOM 覆盖排产、仓储、生产全过程，智能制造升级和质量攻坚线索显示生产/质量负责人需重点沟通交付、出厂检验和质量闭环", "姓名、职位、生产管理风格", ["TY1", "TY2"]),
                    _org_row("销售负责人", "公开资料未披露销售负责人；业务单元经理、金牌营销员机制和MOM销售流程表明销售/经营责任下沉，需按新能源、储能、化工、水利等行业项目确认实际负责人", "姓名、职位、市场策略", ["TY1", "TY2"]),
                ],
            },
            {
                "category": "决策流程",
                "rows": [
                    _org_row("采购决策流程", "项目/销售获取招标文件和业主规范，设计技术做方案优化、报价审核和元器件型号确认，采购/供应链按年度中标物料、价格、交期和准入执行，业务单元对利润、回款、质量、交付负责，MOM 数据贯穿流程", "谁提议-谁评估-谁批准", ["TY1", "TY2", "TY6"]),
                    _org_row("技术选型流程", "低压柜设计岗位负责前端方案优化、报价审核，并根据年度中标物料供应商确认项目元器件型号；非指定且不在年度招标范围内的元器件需提请招标，说明准入前置价值很高", "技术评审参与方", ["TY6"]),
                    _org_row("决策周期", "公开资料未披露标准周期；大型项目受招标节点、年度物料准入、MOM排产和项目交期影响，引江济淮项目交货期覆盖 2025 年 3 月至 2026 年 6 月，可用项目节点反推", "从需求到采购决策的周期", ["TY2", "TY4"]),
                    _org_row("决策影响因素", "年度中标物料清单、业主指定、价格/成本、交期、质量、售后、集团供应链协同、MOM交付数据和业务单元利润共同影响；施耐德需前移到准入、技术标准和项目排产环节", "价格/质量/服务/关系等权重", ["TY1", "TY2", "TY6"]),
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


def _customer_org_decision_blueprint(customer: str) -> dict[str, Any]:
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        src = _petrochem_detail_src(petrochem_data)
        account_type = petrochem_data.get("profile", {}).get("account_type", "油气化工KA")
        return {
            "title": f"{account_type} 多角色决策链",
            "decision_path": [
                {
                    "stage": "项目/装置需求",
                    "owner": "基地、项目公司、生产运行或检维修团队",
                    "signal": "先识别新建、技改、检修备件、开车保运或年度框架采购入口。",
                    "source_ids": src,
                },
                {
                    "stage": "技术与安全评审",
                    "owner": "设备、电仪、工艺、安环、EPC/设计院",
                    "signal": "关键负载、连续生产、安全合规、通信协议、保护配合和品牌库共同影响选型。",
                    "source_ids": src,
                },
                {
                    "stage": "商务与准入",
                    "owner": "采购、供应链、招标平台、项目管理",
                    "signal": "需核验集团准入、框架协议、EPC包绑定、供货周期和现场服务承诺。",
                    "source_ids": src,
                },
                {
                    "stage": "最终批准与交付",
                    "owner": "授权领导、项目负责人、基地管理层",
                    "signal": "批准权通常随金额、项目级别和安全风险上移，开车节点会放大交付确定性权重。",
                    "source_ids": src,
                },
            ],
            "priority_contacts": [
                {"role": "项目入口人", "status": "P1", "evidence": "项目公司/基地项目负责人", "action": "确认在建、技改、检修和备件项目清单", "source_ids": src},
                {"role": "技术否决人", "status": "P1", "evidence": "设备/电仪/EPC技术负责人", "action": "共建单线图、品牌库、保护配合和通讯点表", "source_ids": src},
                {"role": "采购推进人", "status": "P1", "evidence": "采购/招标/供应链负责人", "action": "确认准入、框架、价格、账期和交期边界", "source_ids": src},
                {"role": "运行影响人", "status": "P2", "evidence": "生产运行/检维修/安环负责人", "action": "量化停机风险、备件和现场响应价值", "source_ids": src},
            ],
            "decision_rules": [
                "新建项目优先锁定EPC/设计院与项目公司技术规范",
                "技改检修优先锁定基地设备/电仪与检维修窗口",
                "年度框架优先锁定集团准入、采购策略和历史装机评价",
            ],
            "missing_data": ["基地级组织图", "项目负责人名单", "设备/电仪负责人", "采购授权表", "品牌库/准入状态"],
        }
    if _is_chint_customer(customer):
        return {
            "title": "正泰：盘厂KA/竞合型项目链路图",
            "decision_path": [
                {"stage": "角色分层", "owner": "客户经理、行业销售、渠道授权、竞争情报", "signal": "先判断正泰在项目中是自有品牌竞品、成套/OEM节点、终端项目参与方、系统集成/数字平台方，还是存在关联主体采购例外。", "source_ids": ["S1", "S5", "S13"]},
                {"stage": "项目入口", "owner": "区域销售、行业大客户、经销商网络、海外团队", "signal": "重点入口包括数据中心/通信、新能源/储能、油气采油采气、电网、轨交/机场、工业OEM、建筑楼宇和智能配电。", "source_ids": ["S1", "S4", "S19", "S21"]},
                {"stage": "规格与BOM影响", "owner": "业主、设计院、EPC/总包、盘厂/OEM、研发技术、质量认证、产品线", "signal": "通过业主品牌库、设计院上图、EPC技术协议、盘厂标准BOM、通信点表、认证、交期和服务承诺决定施耐德是否进入项目。", "source_ids": ["S1", "S3", "S12", "S20", "SE8"]},
                {"stage": "施耐德经营动作", "owner": "施耐德行业销售、设计院团队、应用工程、服务和数字化团队", "signal": "在关键负载、国际认证、智能配电、EcoStruxure、Power Build、Power Commission、FAT/SAT和生命周期服务上前置锁定项目价值。", "source_ids": ["SE1", "SE2", "SE3", "SE8"]},
            ],
            "priority_contacts": [
                {"role": "主体/边界核验人", "status": "P1", "evidence": "正泰本体与集团关联主体较多，公开资料不能证明施耐德授权关系", "action": "用CRM、授权系统、历史订单和客户编码核验主体、柜型、SKU和项目例外", "source_ids": ["S1", "S5"]},
                {"role": "行业/区域项目入口人", "status": "P1", "evidence": "区域、行业、渠道网络和官网项目案例显示其进入多个施耐德重点行业", "action": "从共同终端客户、官网案例、施耐德赢丢单和经销商反馈反查项目入口", "source_ids": ["S1", "S4", "S21"]},
                {"role": "技术质量/标准影响人", "status": "P1", "evidence": "公开资料显示研发、质量、认证和标准能力持续增强", "action": "跟踪其新产品、认证、设计院入库、标准BOM、点表接口和FAT/SAT资料", "source_ids": ["S3", "S12", "S20"]},
                {"role": "共同终端客户关键人", "status": "P1", "evidence": "数据中心、新能源、油气、工业OEM、建筑等客户重叠度高", "action": "对共同终端客户建立品牌偏好、规格影响人、BOM位置、服务评价和施耐德切入点", "source_ids": ["S1", "S21", "SE2"]},
            ],
            "decision_rules": [
                "常规低压元件默认正泰自有品牌强，施耐德只做高价值选择性参与",
                "设计院/业主/EPC品牌库和盘厂BOM是盘厂KA经营第一战场",
                "数据中心、海外认证、关键负载、油气/轨交、智能配电、软件服务和全生命周期服务是施耐德差异化主阵地",
                "所有与正泰相关的采购/授权/项目例外都要同步做主体、技术资料、价格和客户转化风险隔离",
            ],
            "missing_data": ["正泰参与施耐德赢丢单项目清单", "正泰本体/关联主体授权与采购边界", "共同终端客户品牌库", "项目BOM/柜型/点表资料", "设计院/EPC入库情况", "FAT/SAT与售后评价", "施耐德可切入高价值场景"],
        }
    if _is_zhonghuan_customer(customer):
        return {
            "title": "中环：经营负责人牵引的项目型盘厂决策链",
            "decision_path": [
                {"stage": "项目线索/招标", "owner": "销售部、市场部、驻外办事处", "signal": "项目来自公共资源、央企合格供应商、总包/EPC和区域招投标渠道。", "source_ids": ["ZH2", "ZH3", "ZH4", "ZH5", "ZH9"]},
                {"stage": "技术澄清", "owner": "技术部、设计/项目团队", "signal": "根据业主/设计院规范、总包品牌库和产品类型校核元器件品牌与参数。", "source_ids": ["ZH3", "ZH4", "ZH9"]},
                {"stage": "商务采购", "owner": "采购部、财务部、经营负责人", "signal": "围绕价格、账期、交期、竞品替代和项目利润做比价与授权审批。", "source_ids": ["ZH2", "ZH9"]},
                {"stage": "排产交付", "owner": "生产部、质保部、售后/项目团队", "signal": "高压柜、母线槽、桥架、配电箱等产品线需区分排产、质检和交付责任。", "source_ids": ["ZH9", "ZH14"]},
            ],
            "priority_contacts": [
                {"role": "最终审批人", "status": "已确认线索", "evidence": "王永贵为法定负责人，招聘页披露董事长/总经理领导口径", "action": "拜访时核验是否兼任最终商务审批和战略客户拍板人", "source_ids": ["ZH1", "ZH9"]},
                {"role": "项目入口人", "status": "待补", "evidence": "销售部/市场部/驻外办事处存在，但负责人未公开", "action": "按威海、淮安、常州、中车/电建项目反查项目经理", "source_ids": ["ZH2", "ZH3", "ZH4", "ZH9"]},
                {"role": "技术把关人", "status": "待补", "evidence": "技术部存在，负责人未公开", "action": "先从高压柜、母线槽、桥架/配电箱三类项目约技术澄清会", "source_ids": ["ZH9"]},
                {"role": "采购与质保", "status": "待补", "evidence": "采购部、质保部存在，负责人未公开", "action": "补齐施耐德准入、竞品替代、出厂检验和服务响应边界", "source_ids": ["ZH9", "ZH14"]},
            ],
            "decision_rules": [
                "公共资源和央企项目先看业主/设计院/总包技术规范",
                "桥架/母线槽类项目价格和交期权重高，高低压柜项目质量与品牌指定权重更高",
                "经营负责人可能对重大项目报价、账期和品牌替换有最终影响",
            ],
            "missing_data": ["部门负责人名单", "项目经理名单", "采购授权额度", "技术澄清流程", "施耐德/竞品历史采购"],
        }
    if _is_tianyu_customer(customer):
        return {
            "title": "天宇：集团体系 + 阿米巴业务单元 + MOM流程链",
            "decision_path": [
                {"stage": "集团/年度策略", "owner": "中国电气装备/许继体系、天宇经营层", "signal": "集团供应链、年度目标、质量修复和战略行业决定外部品牌准入边界。", "source_ids": ["TY1", "TY8"]},
                {"stage": "业务单元经营", "owner": "9个业务单元、业务单元经理、销售/项目团队", "signal": "阿米巴机制让利润、回款、质量、交付责任下沉到业务单元。", "source_ids": ["TY1"]},
                {"stage": "设计与采购联动", "owner": "设计技术、采购/供应链、年度中标物料管理", "signal": "低压柜设计岗位参与报价审核和元器件型号确认，非年度物料需提请招标。", "source_ids": ["TY2", "TY6"]},
                {"stage": "排产/质量/交付", "owner": "排产、仓储、生产、质量、服务", "signal": "MOM平台贯通销售、设计、排产、采购、供应链、仓储和生产，适合按数据节点定位责任人。", "source_ids": ["TY2"]},
            ],
            "priority_contacts": [
                {"role": "高层赞助人", "status": "已确认线索", "evidence": "张红彬为法定代表人/董事长线索", "action": "围绕年度目标、质量零重大事件和智能制造效率建立合作主题", "source_ids": ["TY1", "TY3"]},
                {"role": "业务单元经理", "status": "待补", "evidence": "公开资料确认9个业务单元和经理竞聘机制，但名单未公开", "action": "按新能源、储能、化工、水利等项目逐一补齐业务单元负责人", "source_ids": ["TY1"]},
                {"role": "设计技术负责人", "status": "待补", "evidence": "低压柜设计职责明确，姓名未公开", "action": "围绕标准BOM、年度中标物料、替代审批做技术会", "source_ids": ["TY6"]},
                {"role": "采购/供应链负责人", "status": "待补", "evidence": "采购和供应链在MOM流程中明确存在", "action": "补齐年度物料清单、准入、价格、交期和集团协同采购规则", "source_ids": ["TY2", "TY6"]},
            ],
            "decision_rules": [
                "年度中标物料清单是施耐德进入标准BOM的关键前置",
                "业务单元利润、回款、质量和交付会影响品牌替换接受度",
                "MOM流程可用于定位真实责任人和量化交付效率价值",
            ],
            "missing_data": ["9个业务单元名单", "业务单元经理", "年度中标物料清单", "采购负责人", "设计负责人", "MOM关键节点责任人"],
        }
    return {
        "title": "待补组织与决策链",
        "decision_path": [],
        "priority_contacts": [],
        "decision_rules": [],
        "missing_data": ["组织架构图", "关键部门", "关键人", "采购流程", "技术选型流程"],
    }


def _customer_strategy_needs(customer: str) -> list[dict[str, Any]]:
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_strategy_needs(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "战略方向",
                "rows": [
                    _strategy_row("短期目标", "正泰当前经营主线是“智慧电器+绿色能源”双轮驱动，并以“全球化、数智化、绿色化”为短期增长抓手。智慧电器侧重点是全球区域本土化、“区域-行业-产品”三位一体营销、“532+1”渠道生态、行业客户突破和“泰无界”数智互联平台；绿色能源侧重点是户用光伏、电站交易、逆变器储能、虚拟电厂与绿证业务。盘厂KA视角下，这些目标会转化为数据中心、新能源、智能配电、海外认证和终端项目的新增入口", "1-2年内的发展目标", ["S1", "S45"]),
                    _strategy_row("中长期规划", "中长期方向可概括为五条：产业一体化、全球本土化、数字正泰/平台化、新型电力系统、零碳能源生态。正泰集团层面明确践行“产业化、科技化、国际化、数字化、平台化”战略，并构建绿色能源、智能电气、智能家居三大产业生态及产业培育、科创孵化平台；正泰电器则从低压元件龙头向全球智慧能源解决方案商升级。施耐德需要判断哪些场景是正泰自有闭环，哪些场景因业主规范、国际认证或关键负载仍可进入", "3-5年发展战略", ["S1", "S5", "S45"]),
                    _strategy_row("业务扩张计划", "业务扩张聚焦高景气和高价值场景：新型电力系统、风光储充、数据中心/算力中心、智能配网、光储直柔、轨交、锂电池、充电桩、半导体、智慧城市基建、节能降碳和综合能源服务。2025年报道提到正泰推出AI智能框架控制系统、风光储专用断路器、5G基站专供产品，并在北美以“北美接单-总部设计-越南制造”模式拿下超大型算力中心订单；这些场景是施耐德盘厂KA项目库需要优先打标的机会/风险入口", "是否计划拓展新业务领域", ["S1", "S45", "S49", "SE2"]),
                    _strategy_row("区域扩张计划", "区域扩张呈现“全球营销+本土制造+本地服务”结构：欧洲巩固核心批发商和新能源/电梯客户，亚太、西亚非扩大分销和本土技术方案，北美聚焦数据中心与墨西哥工业园，拉美培育工业客户；官网还披露2026年海外在线客服首站落地亚太。施耐德应按国家/区域核验正泰认证、交付、服务能力，并选择国际业主规范和关键负载场景前置经营", "是否计划拓展新市场区域", ["S3", "S5", "S45", "S47", "SE2"]),
                ],
            },
            {
                "category": "数字化转型",
                "rows": [
                    _strategy_row("数字化现状", "正泰已具备较完整的制造与能源数字化底座：官网披露累计投入20多亿元建设6大类数字化车间，产线全流程数字监控覆盖生产、设备、质量、能耗等关键质控点；年报和报道披露“泰无界”数智互联平台、AI场景应用、精准运营决策、数字化变革和能源数智运营。它已经不是普通数字化采购方，而是把数字化作为产品、渠道、制造和能源运营能力", "ERP/MES/CRM等系统使用情况", ["S1", "S3", "S12", "S45"]),
                    _strategy_row("数字化需求", "实际需求画像应是“继续强化自研平台+补齐国际场景能力”：包括开放协议与数据互通、边缘计算+云端协同、智能断路器/智能量测开关、微电网/虚拟电厂、数据中心高可靠配电监控、海外本土交付系统、供应链质量追溯和AI辅助运营。施耐德若切入，应避免直接替换其平台，而是找国际业主标准、EcoStruxure开放生态、第三方可信运维、关键负载可靠性、通信点表和跨国认证场景", "对数字化工厂、智能生产的需求", ["S1", "S45", "S49", "SE1", "SE2"]),
                    _strategy_row("数字化预算", "公开资料没有披露年度预算，但正泰官网披露智能制造累计投入20多亿元，集团简介披露年均研发投入占销售4%-12%，2025年报道还显示“数字正泰建设”被列为未来新动能。这说明数字化投入是持续战略预算，不是一次性系统采购；施耐德应以高价值场景共创、国际项目背书和标杆试点方式比较价值", "数字化转型投入预算", ["S3", "S5", "S45"]),
                ],
            },
            {
                "category": "绿色低碳",
                "rows": [
                    _strategy_row("双碳目标", "正泰已把零碳纳入核心战略：公开“零碳宣言”显示2028年实现运营碳中和（含碳抵消），2035年实现运营净零碳排放并建立价值链碳排放管理体系；2025年温州大桥园区、智能工控园区、量测园区、上海诺雅克园区、物联技术园区通过组织碳中和及零碳工厂双认证。绿色低碳是正泰对外获客和对内制造升级的共同抓手", "是否制定碳减排目标", ["S13", "S46", "S48", "S50"]),
                    _strategy_row("绿色产品需求", "绿色产品需求集中在“源-网-荷-储”与客户侧零碳场景：户用光伏、电站开发/交易、逆变器与储能、光储充、风光储专用断路器、直流配电、BIPV、零碳园区、虚拟电厂、绿证、电力交易和综合能源服务。正泰可能用“光伏+储能+低压配电+数字平台”打包进入终端客户；施耐德要在关键负载可靠性、国际认证、能效管理、第三方可信平台和跨品牌集成上形成项目价值", "对环保型产品的需求", ["S1", "S18", "S45", "S49", "SE1"]),
                    _strategy_row("ESG评级", "2025可持续发展报告披露正泰已获得/披露多类ESG表现：EcoVadis银牌、商道ESG评级A-、Wind ESG评级A、MSCI ESG评级BBB、标普CSA 48分，并参与企业ESG、碳中和路线图、供应链ESG管理等团体标准建设。盘厂KA项目中可把ESG转成业主低碳指标、供应链碳披露、绿色产品认证和能效改造机会", "企业ESG评级情况", ["S50", "S13", "SE1"]),
                ],
            },
            {
                "category": "电气升级需求",
                "rows": [
                    _strategy_row("智能配电需求", "正泰的智能配电需求已转化为产品化能力：AI智能框架控制系统、智能量测开关、边缘计算+云端协同微型断路器、InModule高参数智能低压柜、南网智能配电和储能项目、光储直柔国家重点研发课题等均指向智能配电升级。施耐德应从标准规范、关键负载、软件生态、网络安全、点表接口、FAT/SAT和国际业主认证维度做项目切入", "对智能配电柜、物联网的需求", ["S1", "S37", "S38", "S45", "S49", "SE1"]),
                    _strategy_row("能效管理需求", "能效管理既是正泰内部降本需求，也是其对外解决方案：五大零碳园区、光伏/储能/充电/数智平台组合、虚拟电厂、电力交易、绿证和能源数智运营都说明其需要持续优化能耗监测、碳数据、分布式能源调度和运维效率。施耐德的切入口应是第三方审计可信度、国际数据中心/工业客户规范、复杂场景能效诊断、跨品牌系统集成和服务闭环", "对能耗监测、节能改造的需求", ["S45", "S46", "S48", "S50", "SE1"]),
                    _strategy_row("设备更新需求", "公开资料未披露单一设备更新清单，但可推断更新重点在三类：一是智能工厂和质量检测体系迭代，二是海外本土化制造/适配点升级（新加坡、捷克、越南等），三是数据中心、新能源、轨交和北美UL/IEC认证场景的高端低压产品迭代。施耐德可进入的空间多在国际认证、客户指定、关键可靠性、第三方平台、改造项目和服务SLA场景", "现有设备更新换代计划", ["S3", "S45", "S47"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "战略方向",
                "rows": [
                    _strategy_row("短期目标", "正式战略未公开；对施耐德而言，短期应先核验授权状态、近三年采购额、项目行业分布、竞品替代情况和关键人地图，并建立按项目类型划分的机会池", "1-2年内的发展目标", []),
                    _strategy_row("中长期规划", "官网未披露正式3-5年战略，但企业宗旨强调优质产品、信誉和“诚信、和谐、谦学、共赢”；结合官网产品链和授权证书，推测重点为巩固母线槽、高低压柜、配电箱、桥架、支吊架和箱式变电站等工程项目型业务，并借助ISO/3C/低碳/能源管理等体系认证提升项目准入背书", "3-5年发展战略", ["ZH15", "ZH16", "ZH17"]),
                    _strategy_row("业务扩张计划", "官网产品线已包含箱式变电站、接地装置、综合支吊架和矿用电气，经营范围还指向光伏变电站设备、风电母线、抗震支吊架、综合支吊架、地铁预埋槽道、电子厂房配电、港口电气和工业仪表桥架等新场景扩展", "是否计划拓展新业务领域", ["ZH15", "ZH16", "ZH2"]),
                    _strategy_row("区域扩张计划", "公开项目线索已跨山东、安徽、江苏、北京、福建、湖北、内蒙古、浙江等地；是否有明确区域扩张计划需客户访谈核验", "是否计划拓展新市场区域", ["ZH2", "ZH3"]),
                ],
            },
            {
                "category": "数字化转型",
                "rows": [
                    _strategy_row("数字化现状", "省中小企业平台披露其2023年被认定为江苏省三星级上云企业；官网高压柜产品页披露可配置微机综合保护装置、测量仪表、智能操控装置，并可实现远程监控和测量。ERP/MES/CRM等内部系统名称仍需现场走访或客户访谈核验", "ERP/MES/CRM等系统使用情况", ["ZH14", "ZH16"]),
                    _strategy_row("数字化需求", "结合上云企业和高压柜远程监控能力，可优先切入智能配电监控、能效管理、EcoFit改造、配电数据上云和服务闭环，面向供热、化工、住宅改造、公共建筑项目形成标准方案", "对数字化工厂、智能生产的需求", ["ZH16", "ZH3", "ZH14", "SE1", "SE2"]),
                    _strategy_row("数字化预算", "公开资料未披露数字化转型预算，需通过项目计划、技改预算、设备采购和客户访谈补齐", "数字化转型投入预算", []),
                ],
            },
            {
                "category": "绿色低碳",
                "rows": [
                    _strategy_row("双碳目标", "公开资料未披露企业碳减排目标或双碳路线图，需客户访谈或 ESG/环保资料补查", "是否制定碳减排目标", []),
                    _strategy_row("绿色产品需求", "官网荣誉资质-体系认证栏目列示碳排放管理、碳足迹、能源管理等认证，经营范围中的风电母线、太阳能支吊架、光伏变电站设备也是新能源工程配套线索；可围绕公共设施和工业客户节能改造、化工和住宅改造中的能效监测形成绿色方案切入", "对环保型产品的需求", ["ZH17", "ZH2", "ZH3"]),
                    _strategy_row("ESG评级", "公开资料未披露第三方ESG评级；官网有社会责任栏目和社会责任管理体系认证线索，需补查评级、信用报告或客户提供的ESG/社会责任资料", "企业ESG评级情况", ["ZH17"]),
                ],
            },
            {
                "category": "电气升级需求",
                "rows": [
                    _strategy_row("智能配电需求", "官网高压柜产品页披露微机综合保护、测量仪表、智能操控装置、远程监控和测量能力；高低压柜项目、公共设施、化工、住宅改造、轨交、港口和电子厂房场景中存在智能仪表、配电监控、标准BOM、配电数据上云和品牌指定切入空间", "对智能配电柜、物联网的需求", ["ZH16", "ZH2", "ZH3", "ZH4", "SE1"]),
                    _strategy_row("能效管理需求", "工业客户和公共设施节能改造、供热锅炉、化工污水、居民小区供配电改造、电子厂房和港口电气项目适合引入能耗监测和能效管理", "对能耗监测、节能改造的需求", ["ZH2", "ZH3"]),
                    _strategy_row("设备更新需求", "老旧配电柜、配电箱更新和存量设备替换可用EcoFit改造切入；中环自身数控设备和上云企业线索也说明其具备生产装备与管理系统升级基础，具体更新计划需从项目库和客户访谈补齐", "现有设备更新换代计划", ["ZH14"]),
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
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_pain_opportunities(petrochem_data)
    if _is_chint_customer(customer):
        playbook = _chint_schneider_pain_playbook()
        return [
            {
                "category": "业务痛点",
                "rows": [
                    _pain_row("生产效率痛点", "正泰官网披露数据中心方案覆盖低压配电系统和列头柜实时监控，宁夏中卫云数据中心案例强调24小时不间断与全链协同；这说明其正在进入对交付节拍、系统联调、在线监测和服务响应要求更高的关键负载场景。叠加全球化、本地化制造与新能源业务扩张，项目设计、装配、齐套、预调试、FAT/SAT和跨区域交付效率会成为盘厂KA项目验证点", "施耐德机会：在复杂交付、跨国认证、数据中心快速部署和智能配电项目中，用BOM/SLD标准化、预制化配置、调试服务、备件保障和专家服务建立差异", "生产过程中效率低下的环节", _source_union(["S1", "S16", "S47", "S51", "SE2"], playbook["生产效率痛点"]["source_ids"]), playbook["生产效率痛点"]),
                    _pain_row("质量管控痛点", "正泰公开披露质量信用与多体系管理，但其数据中心、储能、微电网、海外认证和关键负载项目对连续供电、安全、弧光/温升风险、点表接口、FAT/SAT证据提出更高要求；盘厂KA视角下，质量比较应从产品证书延伸到项目交付和长期运行证据", "施耐德机会：强化关键负载案例、出厂测试、现场服务、可靠性数据和生命周期服务，把质量从“证书”提升为“风险成本+验收证据”比较", "质量问题的频发点", _source_union(["S1", "S3", "S12", "S16", "S51", "SE2"], playbook["质量管控痛点"]["source_ids"]), playbook["质量管控痛点"]),
                    _pain_row("供应链痛点", "年报提示低压电器主要原材料包含铜、银、钢材、塑料等，成本波动和运输成本会影响盈利；同时正泰正在推进全球服务体系、亚太在线客服和区域本土化，海外监管、关税、原产地规则、认证差异和跨境服务一致性会影响项目交付稳定性。盘厂项目还需关注齐套、分批到货、变更追踪和现场窗口", "施耐德机会：在海外项目、合规认证、BOM冻结、Kitting/齐套、Track & Trace、全球备件和服务SLA上建立交付确定性价值", "供货、库存、物流等问题", _source_union(["S1", "S45", "S47", "SE1"], playbook["供应链痛点"]["source_ids"]), playbook["供应链痛点"]),
                    _pain_row("人才痛点", "正泰从低压元件向数据中心、储能、微电网、智慧配电和海外本地化扩张，公开材料显示其数智化、全球服务和国家重点研发方向持续加码；这些场景需要懂低压保护、通信、软件、认证、运维、调试和行业方案的复合型团队，项目复制能力会成为高端场景瓶颈之一", "施耐德机会：用设计院/EPC技术日、业主培训、项目澄清会、Power Build/Power Commission演示和服务专家网络形成前置影响", "人才招聘、培养、流失问题", _source_union(["S1", "S45", "S47", "S49", "S52", "SE1"], playbook["人才痛点"]["source_ids"]), playbook["人才痛点"]),
                ],
            },
            {
                "category": "技术痛点",
                "rows": [
                    _pain_row("设计能力痛点", "正泰已把数据中心、工商业储能、光储直柔、配电物联、台区拓扑识别和能碳管理作为解决方案方向；这些场景对跨标准设计、保护配合、通信互联、BOM一致性、认证合规和软件接口提出更高要求，也是业主/设计院/EPC最容易验证的能力点", "施耐德机会：前置设计院规范、保护配合、通信架构、点表接口、验证报告和国际认证资料，避免只在采购阶段被动比价", "设计效率、标准化程度问题", _source_union(["S1", "S16", "S18", "S49", "S52", "S53", "SE2", "SE3"], playbook["设计能力痛点"]["source_ids"]), playbook["设计能力痛点"]),
                    _pain_row("技术成本痛点", "低压业务原材料成本占比高，正泰自有品牌具备价格、渠道和本地化规模优势，会压缩施耐德标准品空间；但高可靠数据中心、智慧配电、油气/轨交和海外认证场景会把成本从单件采购价扩展到调试、故障、运维、停机、认证失败和复盘复制成本", "施耐德机会：用TCO、能效收益、故障损失、调试周期、维保SLA、数字化洞察和项目验收成本证明高端价值", "成本优化能力不足", _source_union(["S1", "S20", "S31", "SE1"], playbook["技术成本痛点"]["source_ids"]), playbook["技术成本痛点"]),
                    _pain_row("技术人才痛点", "弱电网适应、储能并网、光储直柔、智能配电平台和海外认证需要跨电气、软件、通信、测试和运维的人才；正泰公开强调数智绿色双轮驱动与泰无界/EmpowerX平台，说明其技术人才结构要从产品研发扩展到平台化方案交付和项目验收", "施耐德机会：面向业主、设计院、EPC和盘厂生态做技术培训，强化施耐德标准、调试工具和规范影响力", "技术人员能力不足", _source_union(["S1", "S45", "S49", "S52", "SE1"], playbook["技术人才痛点"]["source_ids"]), playbook["技术人才痛点"]),
                ],
            },
            {
                "category": "市场痛点",
                "rows": [
                    _pain_row("市场竞争压力", "正泰年报将市场竞争列为风险；低压行业公开资料显示正泰与施耐德在中国低压市场形成直接竞争，正泰在能源电力、工业OEM、数据中心、新能源等场景加速突破。施耐德面对的是竞合型盘厂KA：常规低压多为竞争，特定终端项目则要按业主/设计院/EPC规格和BOM经营", "施耐德机会：聚焦高端客户指定、海外认证、关键负载、数据中心、软件服务、生命周期服务和项目交付证据，不在常规低压价格战中消耗资源", "来自竞品的压力", _source_union(["S1", "S19", "S20", "S31", "SE2"], playbook["市场竞争压力"]["source_ids"]), playbook["市场竞争压力"]),
                    _pain_row("客户需求变化", "客户需求升级到光储充、储能、微电网、数据中心高可靠配电、能源运维、能碳管理和数字化管理；正泰已通过数据中心方案、工商业储能、泰无界/EmpowerX和智慧配电平台布局，项目需求已从单一元件扩展到智能柜、通信、数据和服务结果", "施耐德机会：把智能配电、能效管理、电能质量、资产顾问、服务合同和项目验收打包成客户成果，而不是单件产品对比", "客户需求升级带来的挑战", _source_union(["S1", "S16", "S18", "S45", "S52", "S53", "SE1", "SE2"], playbook["客户需求变化"]["source_ids"]), playbook["客户需求变化"]),
                    _pain_row("行业政策变化", "国产替代、双碳、新能源政策、算力基础设施建设、海外监管、关税、原产地规则和地缘风险会重塑品牌选择；部分政策有利于正泰的国产品牌、本地化制造和绿色能源布局。施耐德必须把项目价值从“外资品牌”转成“本土化高可靠能力+全球合规能力+验收服务能力”", "施耐德机会：突出本土化能力、合规认证、关键负载安全、国际客户认可、全球服务网络和项目交付证据，选择性参与政策友好场景", "政策调整带来的影响", _source_union(["S1", "S5", "S46", "S48", "S50", "SE1"], playbook["行业政策变化"]["source_ids"]), playbook["行业政策变化"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "业务痛点",
                "rows": [
                    _pain_row("生产效率痛点", "官网产品线覆盖母线槽、高低压柜、配电箱、桥架、支吊架、接地装置、箱式变电站等，多品类逐单报价和技术沟通容易拉长交付周期；2024-2025项目线索又覆盖配电箱、低压开关柜、仪表桥架、港口电气、电子厂房等多场景，说明报价、图纸、BOM和排产需要更强标准化", "围绕Prisma E、MVnex、BlokSeT建立标准报价包、标准BOM、授权柜/元器件组合和项目类型模板，减少重复选型与沟通；优先做配电箱/低压柜、化工可靠配电、轨交/母线槽三类样板", "生产过程中效率低下的环节", ["ZH16", "ZH17", "ZH2", "ZH3"]),
                    _pain_row("质量管控痛点", "官网披露ISO9001、ISO14001、ISO18001、CQC强制性3C、质量/售后/碳/能源等体系认证线索，但公开资料仍缺少一次合格率、现场质检流程和项目质量复盘；化工、供热、轨交、电建、水利和电子厂房标准差异仍需重点审核", "用现场审核、FAT/SAT、出厂检验清单、行业质量模板和服务响应机制做风险分级，把施耐德价值落到可靠性与验收证据", "质量问题的频发点", ["ZH15", "ZH17", "ZH3", "ZH4", "ZH5"]),
                    _pain_row("供应链痛点", "官网确认存在施耐德授权合作证书，同时列示西门子授权；官网高压柜产品页也明确可按用户或设计院要求选择其他品牌，说明采购链条受业主/设计院/总包品牌库影响大，需要内部订单与项目BOM补齐竞品比例", "提前进入业主/设计院规范，绑定交期、服务、授权和质量闭环形成非价格壁垒；用赢丢单复盘识别竞品替代理由", "供货、库存、物流等问题", ["ZH16", "ZH17", "ZH2", "ZH3"]),
                    _pain_row("人才痛点", "官网未披露设计、研发、生产和销售人员结构；官网联系方式只提供商务入口联系人，组织框架页未披露可读组织图。虽然官网技术/认证线索说明有一定基础，但关键采购、技术、生产和销售负责人仍不透明", "通过技术日、选型培训、现场审核和关键人访谈识别采购/技术/生产/销售负责人，并将施耐德授权柜型能力转化为可复制项目包", "人才招聘、培养、流失问题", ["ZH15", "ZH16", "ZH17", "ZH18"]),
                ],
            },
            {
                "category": "技术痛点",
                "rows": [
                    _pain_row("设计能力痛点", "官网产品详情显示MNS低压柜以25mm模数C型型材和标准模块设计，KYN61-40.5可配置智能操控/测量/远程监控，CCX母线槽涉及100%-200%中性线和谐波需求；多产品线和多行业项目对图纸、BOM、保护配合和智能监控标准化提出压力", "共建图纸库、BOM模板、低压柜/配电箱标准方案、智能仪表和快速替代清单，提高技术澄清效率", "设计效率、标准化程度问题", ["ZH16", "ZH17", "ZH2", "ZH3"]),
                    _pain_row("技术成本痛点", "招投标业务技术、商务、资信评分并重，价格竞争强，施耐德若只在采购询价阶段进入容易被低价替代；公共建筑和常规配电箱项目尤其容易被单价牵引", "以前置规范、TCO、质量风险降低、能效收益和售后响应证明价值，避免单纯比价", "成本优化能力不足", ["ZH2", "ZH3", "SE1"]),
                    _pain_row("技术人才痛点", "公开资料未披露技术人员能力结构；官网授权和产品线覆盖中低压、母线、桥架、箱变、智能监控等多领域，可能需要更强的施耐德授权柜型、行业方案和标准化设计支持", "提供化工、公共建筑、轨交、电建、港口和电子厂房等行业应用包，以及半天技术训练营/选型工作坊", "技术人员能力不足", ["ZH16", "ZH17", "ZH3", "ZH4", "ZH5"]),
                ],
            },
            {
                "category": "市场痛点",
                "rows": [
                    _pain_row("市场竞争压力", "官网授权合作证书同时出现施耐德和西门子，说明中环具备多品牌授权/合作选择；区域同类盘厂、桥架、母线槽厂商密集，项目招投标中价格替代空间大，施耐德进入晚会被竞品品牌、总包商务或业主指定压缩", "锁定业主指定、授权柜型、服务响应和质量闭环，提升非价格竞争力；把施耐德从询价品牌变成项目规范品牌", "来自竞品的压力", ["ZH17", "ZH2", "ZH3", "SE1"]),
                    _pain_row("客户需求变化", "官网应用行业覆盖电力石化、煤炭、能源、交通、冶金、建筑、通信等，外部项目覆盖供热、造纸、化工、住宅改造、轨交、电建、港口和电子厂房，需求正从单品供货转向安全、可靠、能效、可追溯验收和运维", "将低压开关柜、智能仪表、配电监控、能效管理和服务SLA打包成行业方案", "客户需求升级带来的挑战", ["ZH15", "ZH2", "ZH3", "ZH4", "ZH5", "SE2"]),
                    _pain_row("行业政策变化", "公共资源招投标、央企合格供应商准入、工程项目合规、节能改造和质量信用要求会持续影响品牌入围与成交路径", "补齐资质、授权、合规文件、项目业绩包、绿色能效材料和服务承诺，前置到招标技术规范", "政策调整带来的影响", ["ZH3", "ZH5", "ZH13", "ZH14"]),
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


def _pain_row(field_name: str, pain: str, opportunity: str, description: str, source_ids: list[str], playbook: dict[str, Any] | None = None) -> dict[str, Any]:
    playbook = playbook or {}
    return {
        "field": field_name,
        "value": pain,
        "pain": pain,
        "opportunity": opportunity,
        "description": description,
        "source_ids": source_ids,
        "schneider_advantage": playbook.get("advantage", ""),
        "schneider_playbook": playbook.get("playbook", ""),
        "playbook_output": playbook.get("output", ""),
        "playbook_stage": playbook.get("stage", ""),
    }


def _customer_risk_assessment(customer: str) -> list[dict[str, Any]]:
    petrochem_data = find_petrochem_ka(customer)
    if petrochem_data:
        return _petrochem_risk_assessment(petrochem_data)
    if _is_chint_customer(customer):
        return [
            {
                "category": "经营风险",
                "rows": [
                    _risk_assessment_row("财务风险", "对施耐德而言，正泰财务风险不是主要合作信用问题，而是项目经营边界问题。2025年资产负债率约66.13%，较2024年约63.28%上升；光伏业务收入同比下降15.62%、光伏电站工程承包收入同比下降35.04%，周期压力可能促使其更重视低压、渠道、终端项目和海外订单的现金流贡献", "资金链、负债、回款风险", ["S1"]),
                    _risk_assessment_row("法律风险", "2025年报披露近三年受证券监管机构处罚情况为不适用，本年度无重大诉讼、仲裁事项；上市公司层面合规风险较低。施耐德应把风险重点放在竞品信息合规、渠道报价合规、授权/非授权主体边界和技术资料/IP边界", "诉讼、行政处罚记录", ["S1"]),
                    _risk_assessment_row("经营稳定性", "正泰具备规模、渠道、现金流和多业务基础，短期经营稳定性强；盘厂KA风险主要来自其长期份额扩张、国产替代、海外本地化、数据中心/新能源高端突破，以及施耐德未识别项目BOM和终端规格位置导致的持续替代", "是否存在经营异常", ["S1", "S19", "S20"]),
                ],
            },
            {
                "category": "信用风险",
                "rows": [
                    _risk_assessment_row("付款信用", "若存在施耐德采购关系，需按正泰本体及关联主体查询应收、账期、逾期和授信；若无采购关系，也要记录项目中正泰是否通过账期、价格、渠道返利或国产替代政策影响终端客户BOM", "历史付款是否准时", []),
                    _risk_assessment_row("合同履约", "公开资料未发现施耐德相关合同履约争议，上市公司年报披露本年度无重大诉讼仲裁；需用施耐德项目库复盘正泰参与项目的交付、FAT/SAT、验收和服务表现，判断其在高端场景的真实履约能力", "合同履约情况", ["S1"]),
                    _risk_assessment_row("售后纠纷", "公开资料未披露与施耐德相关售后纠纷；官网质量信用资料显示其建设客服热线、官网、微信公众号、小程序等服务闭环。盘厂KA风险在于正泰服务能力持续补齐后，会降低施耐德服务溢价；机会在于用关键负载SLA、备件和数字服务形成可量化差异", "售后问题处理情况", ["S12", "SE1"]),
                ],
            },
        ]
    if _is_zhonghuan_customer(customer):
        return [
            {
                "category": "经营风险",
                "rows": [
                    _risk_assessment_row("财务风险", "公开资料未显示财务报表、负债率、现金流和利润情况；非上市企业信息透明度较低，项目型招投标、总包和工程项目可能存在账期长、验收慢、回款节奏不稳定的问题。推进前需同步核验授信、关联主体、付款节点和项目业主付款路径", "资金链、负债、回款风险", ["ZH2", "ZH3"]),
                    _risk_assessment_row("法律风险", "本轮公开资料未形成重大诉讼、行政处罚、经营异常的充分证据结论；由于公开渠道有限，不能据此判断无风险，仍需补查国家企业信用信息公示系统、裁判文书、执行信息和信用中国", "诉讼、行政处罚记录", []),
                    _risk_assessment_row("经营稳定性", "官网产品和资质线索覆盖开关柜、桥架、母线槽、配电箱、箱式变电站等多品类，体系认证、AAA资信、守合同重信用、施耐德授权等可作为信用侧正面线索；但同区域同类厂商较多，价格竞争、交付稳定性、证书有效期和质量一致性仍需重点核验", "是否存在经营异常", ["ZH15", "ZH16", "ZH17", "ZH2", "ZH13", "ZH14"]),
                ],
            },
            {
                "category": "信用风险",
                "rows": [
                    _risk_assessment_row("付款信用", "公开资料未披露付款信用、授信额度和历史账期；需由施耐德内部系统补齐应收、逾期、授信、回款争议、项目客户编码和关联主体账期差异", "历史付款是否准时", []),
                    _risk_assessment_row("合同履约", "官网资质体系、AAA资信、守合同重信用和施耐德授权提供履约信用侧正面线索，公开项目显示其具备候选/供应商准入线索；但仍未披露完整项目履约评价，需核验招投标黑名单、供应商处罚、项目验收、准时交付、质量整改和总包评价记录", "合同履约情况", ["ZH17", "ZH3", "ZH4", "ZH5", "ZH13", "ZH14"]),
                    _risk_assessment_row("售后纠纷", "公开资料未披露与施耐德产品装配、调试、售后相关的历史问题；需调取施耐德服务工单、质量投诉、现场整改、FAT/SAT问题和售后纠纷记录", "售后问题处理情况", []),
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


def _petrochem_source_ids(data: dict[str, Any]) -> list[str]:
    return [str(source.get("id", "")) for source in data.get("sources", []) if source.get("id")]


def _petrochem_src(data: dict[str, Any], *indexes: int) -> list[str]:
    source_ids = _petrochem_source_ids(data)
    if not indexes:
        return source_ids[:2]
    selected = [source_ids[index] for index in indexes if 0 <= index < len(source_ids)]
    return selected or source_ids[:1]


def _petrochem_citation(source_ids: list[str]) -> str:
    return " ".join(f"【{source_id}】" for source_id in source_ids if source_id)


def _petrochem_fact(data: dict[str, Any], key: str) -> str:
    return str(data.get("facts", {}).get(key, "待核验"))


def _petrochem_details(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("public_details", {})


def _petrochem_detail(data: dict[str, Any], key: str, fallback_key: str = "", default: str = "待核验") -> str:
    details = _petrochem_details(data)
    if details.get(key):
        return str(details[key])
    if fallback_key:
        return _petrochem_fact(data, fallback_key)
    return default


def _petrochem_detail_src(data: dict[str, Any]) -> list[str]:
    details = _petrochem_details(data)
    source_ids = details.get("source_ids")
    if isinstance(source_ids, list) and source_ids:
        return [str(source_id) for source_id in source_ids]
    return _petrochem_src(data)


def _source_union(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for source_id in group:
            if source_id and source_id not in merged:
                merged.append(source_id)
    return merged


def _chint_schneider_pain_playbook() -> dict[str, dict[str, Any]]:
    return {
        "生产效率痛点": {
            "stage": "线索识别 -> 交付验证",
            "advantage": "施耐德在数据中心、低压配电、UPS/关键电源、监控和服务上可形成系统交付能力；Power Commission可用于低压配电柜配置、测试、调试和报告，适合把盘厂项目从交货比价转成调试与验收效率比较。",
            "playbook": "对正泰相关的数据中心、智算中心、储能、油气、轨交和海外项目，建立“盘厂项目交付包”：把业主关注点从交期/单价转到BOM冻结、齐套/Kitting、FAT/SAT、在线监测、UPS/低压联调、备件SLA和调试报告；优先在设计院/EPC阶段锁定关键负载标准。",
            "output": "项目交付清单、BOM冻结表、FAT/SAT节点表、服务SLA样板、盘厂KA项目问诊表",
            "source_ids": ["SE2", "SE6", "KB1"],
        },
        "质量管控痛点": {
            "stage": "技术协议 -> FAT/SAT",
            "advantage": "BlokSeT MB/iPMCC官方资料强调低压/MCC安全、可靠、连接能力、实时热监测、弧光防护和预测维护；施耐德低压产品体系覆盖MasterPacT、ComPacT、BlokSeT、EcoStruxure Power Commission等，可把质量比较从证书扩展到运行风险。",
            "playbook": "在正泰参与的高端项目中，要求技术协议写入热风险、弧光风险、保护整定、通讯数据、调试报告、FAT/SAT和投运后健康检查；把“合格证/认证”转为“关键负载停机风险+长期运行证据”比较。",
            "output": "质量风险对比页、FAT/SAT检查表、热/弧光监测点表、投运健康报告模板",
            "source_ids": ["SE3", "SE5", "SE6", "KB1"],
        },
        "供应链痛点": {
            "stage": "报价/商务 -> 项目交付",
            "advantage": "施耐德可把全球服务、数字服务、备件、配置工具和本土服务结合起来，形成比单纯元器件采购更稳定的交付确定性；Power Build可输出配置、单线图、BOM、规格和订货文件，减少跨区域项目BOM偏差。",
            "playbook": "面对正泰全球本地化和低价打法，施耐德不要直接拼单价，而是做“供应链确定性证明”：列出BOM冻结、关键元器件可得性、Kitting/齐套、备件路径、认证边界、交付变更流程和服务响应SLA；在海外/国际客户项目中突出合规和服务连续性。",
            "output": "供应链确定性对比表、BOM冻结清单、认证/原产地核验清单、备件路径、项目变更RACI",
            "source_ids": ["SE7", "SE8", "KB1"],
        },
        "人才痛点": {
            "stage": "市场影响 -> 技术赋能",
            "advantage": "施耐德数字服务依托预测分析、AI、远程监控和Connected Services Hub，可把专家能力转为客户可感知的资产健康与远程诊断；研修院方法强调按角色、阶段、层级和证据做项目打标。",
            "playbook": "把培训对象放在业主、设计院、EPC、数据中心运维和盘厂生态，而不是正泰内部：通过半天技术日讲关键负载、智能配电、Power Build、Power Commission、PME/数字服务和生命周期服务，让项目关键人形成施耐德标准语言。",
            "output": "设计院/EPC技术日材料、角色培训计划、项目打标表、关键人影响地图",
            "source_ids": ["SE7", "SE6", "KB1"],
        },
        "设计能力痛点": {
            "stage": "概念设计 -> 技术澄清",
            "advantage": "施耐德低压产品与EcoStruxure Power、BlokSeT/Prisma、Power Build、Power Commission可把设计从元件清单提升为系统架构，提前锁定保护配合、通讯点表、单线图、BOM和调试边界。",
            "playbook": "对正泰相关的数据中心、储能、微电网、油气和海外项目，在设计院/EPC澄清会前输出“施耐德高可靠电气包模板”：单线图、关键断路器、柜型建议、通讯架构、点表接口、调试报告和认证材料，先锁规范再进报价。",
            "output": "设计院澄清包、SLD/BOM模板、保护配合材料、通讯点表",
            "source_ids": ["SE3", "SE8", "SE6", "KB1"],
        },
        "技术成本痛点": {
            "stage": "方案阶段 -> 商务决策",
            "advantage": "施耐德数字服务可用资产健康、电能质量、远程诊断和预测维护把成本比较转为运行结果；数据中心方案与低压配电产品体系可把TCO、停机损失和运维效率纳入商务决策。",
            "playbook": "针对正泰低价和本土渠道优势，建立三列表：一次采购价、故障/停机/认证风险、调试与运维成本。常规回路选择性参与，关键负载、数据中心、油气/轨交、海外认证和智能配电项目必须用TCO材料支撑规格前置。",
            "output": "TCO对比表、故障损失假设、运维SLA价值页、关键/非关键回路分级表",
            "source_ids": ["SE2", "SE3", "SE7", "KB1"],
        },
        "技术人才痛点": {
            "stage": "项目定义 -> 复盘复制",
            "advantage": "施耐德可用研修院三层两闭环方法、Power Commission调试工具和数字服务专家网络，把跨电气、软件、通信、调试和运维的能力缺口转为项目角色分工与服务补位。",
            "playbook": "对每个正泰相关项目做RACI：谁负责硬件选型、软件配置、FAT、预调试、现场放线、集成调试、SAT和培训交付；缺口由施耐德应用工程师、服务团队或伙伴补位，降低业主对单纯低价方案的安全感。",
            "output": "项目RACI、能力缺口表、联合调试计划、复盘复制模板",
            "source_ids": ["SE6", "SE7", "KB1"],
        },
        "市场竞争压力": {
            "stage": "机会分级 -> 商务防守",
            "advantage": "施耐德应避免在常规低压价格战中消耗资源，优势放在高端ACB、关键负载、数据中心、智能配电、全球服务、生命周期服务和国际客户认可；这些场景能把项目从“国产低价”转为“运行风险和业务结果”。",
            "playbook": "建立正泰盘厂KA机会分级：常规低价回路只做选择性参与；高可靠/国际认证/智能配电回路必须前置业主/EPC/设计院规范，绑定MasterPacT/ComPacT、BlokSeT、EcoStruxure Power、服务SLA和数字化报表。",
            "output": "正泰项目分级表、不可替代价值清单、业主/EPC规格前置话术",
            "source_ids": ["SE2", "SE3", "SE5", "SE7", "KB1"],
        },
        "客户需求变化": {
            "stage": "场景洞察 -> 方案打包",
            "advantage": "EcoStruxure Power、低压配电产品、数字服务和数据中心方案可把智能配电、能效、电能质量、告警、资产健康和预测维护连接成客户成果，对标正泰的泰无界/EmpowerX和智慧配电叙事。",
            "playbook": "在光储充、数据中心、微电网和智慧配电机会中，不做单产品比价，改做“客户成果包”：安全供电、能效管理、电能质量、告警闭环、资产健康、运维SLA；用结果KPI压过正泰的平台宣传。",
            "output": "客户成果包、KPI清单、EcoStruxure场景图、正泰平台对比页",
            "source_ids": ["SE1", "SE2", "SE3", "SE7", "KB1"],
        },
        "行业政策变化": {
            "stage": "战略沟通 -> 项目落地",
            "advantage": "施耐德可用中国本土化能力、全球合规经验、能效与低碳方案、关键负载可靠性和数字服务，对冲国产替代与双碳政策带来的品牌选择压力。",
            "playbook": "面对国产替代、双碳和算力基础设施政策，不用“外资品牌”叙事防守，改用“本土化制造+全球合规+关键负载安全+能效数据”组合；优先选择国际客户、海外出海、数据中心和高可靠工商业项目做标杆。",
            "output": "政策友好场景清单、合规证明包、低碳/能效价值页、标杆项目筛选表",
            "source_ids": ["SE1", "SE2", "SE7", "KB1"],
        },
    }


def _md_cell(value: Any) -> str:
    return str(value or "").replace("|", "/").replace("\n", "<br>")


def _project_tagging_model(customer: str) -> dict[str, Any]:
    data = find_petrochem_ka(customer)
    if not data:
        return {}
    details = _petrochem_details(data)
    facts = data.get("facts", {})
    profile = data.get("profile", {})
    return {
        "headline": "按研修院知识库：角色 + 阶段 + 层级 + 证据打标。",
        "source_ids": ["KB1", "KB2", "SE1", "SE2", "SE3", "SE4", "ISO1"],
        "tag_groups": [
            {
                "name": "客户角色",
                "tags": _petrochem_role_tags(data),
                "why": "油气化工KA通常不是单一采购人，需拆分终端业主、项目公司、EPC/设计院、盘厂成套、系统集成和运维责任方。",
            },
            {
                "name": "项目入口",
                "tags": _petrochem_entry_tags(data),
                "why": details.get("business_projects") or facts.get("projects") or profile.get("recommended_focus", ""),
            },
            {
                "name": "阶段标签",
                "tags": _petrochem_phase_tags(data),
                "why": "用项目阶段决定下一步材料包和动作：线索期确认角色与时间，方案/选型期锁定架构，调试/交付期关注通讯、点表、FAT/SAT和培训。",
            },
            {
                "name": "技术深度",
                "tags": ["互联互通产品层", "边缘控制层", "应用分析与服务层", "能效/运维/能碳服务"],
                "why": "不能把带通讯元件直接等同于完整智能配电，需看软件平台、数据点表、调试验收和运维闭环。",
            },
            {
                "name": "行业场景",
                "tags": _petrochem_scene_tags(data),
                "why": "按基地与装置拆分场景，优先看公辅变电所、MCC室、关键连续生产装置、储运码头和高耗能单元。",
            },
            {
                "name": "证据标签",
                "tags": ["技术协议", "系统架构图", "点表/IP表", "BOM/柜内照片", "FAT/SAT记录", "培训记录", "竣工验收/客户签字"],
                "why": "项目打标必须能回到证据链，避免只凭公司名称或销售判断定性。",
            },
        ],
        "research_focus": [
            {
                "topic": "项目入口与阶段",
                "questions": [
                    "当前对应哪个基地、装置、项目包或技改任务",
                    "谁发起、谁设计、谁采购、谁验收、谁运维",
                    "当前卡在线索、方案、选型、报价、制造、调试、交付还是运维",
                ],
            },
            {
                "topic": "电气架构与智能配电资格",
                "questions": [
                    "低压、中压、MCC、变频、UPS、公辅变电所和关键负载边界是什么",
                    "智能元件金额是否超过总元件金额20%",
                    "是否包含PME/PSO/POI Plus/千里眼/T300/TH110/PD110/环境监测/弧光监测等要素",
                ],
            },
            {
                "topic": "交付闭环",
                "questions": [
                    "硬件和软件分别由谁采购",
                    "谁负责盘厂安装、预调试、现场放线、集成调试和SAT",
                    "是否有FAT/SAT、培训、竣工验收和Kitting/Track & Trace要求",
                ],
            },
            {
                "topic": "能效/碳与运维价值",
                "questions": [
                    "是否有能源基线、ISO 50001、能效考核或碳数据目标",
                    "哪些装置存在电能质量、停机损失、备件或维护窗口压力",
                    "客户是否愿意从一次项目转为服务框架和资产健康管理",
                ],
            },
            {
                "topic": "生态角色",
                "questions": [
                    "设计院/EPC对品牌入图和技术规范的影响有多大",
                    "盘厂/成套厂是否具备通讯、点表、调试和软件交付能力",
                    "竞品装机基础、DCS/仪表包、变压器/中压柜供应商分别是谁",
                ],
            },
        ],
        "solution_map": [
            {
                "layer": "互联互通产品层",
                "focus": "中低压柜、MTZ/NSX、测量模块、通讯模块、网关、温度/局放/弧光/环境监测",
                "evidence": "BOM、柜内照片、通讯器件清单、一次/二次图纸",
            },
            {
                "layer": "边缘控制层",
                "focus": "PME、PSO、POI Plus、T300、千里眼、站控/顺控、PM Box与网关协议",
                "evidence": "系统架构图、点表/IP表、通讯协议、报警逻辑和调试记录",
            },
            {
                "layer": "应用分析与服务层",
                "focus": "电力顾问、云能效顾问、运维顾问、能碳管理、报表告警、培训和持续服务",
                "evidence": "运维SLA、能源基线、ISO 50001/能效目标、服务工单和月报",
            },
            {
                "layer": "交付与证据闭环",
                "focus": "硬件采购、软件采购、盘厂预调试、现场安装、集成调试、SAT、培训、验收归档",
                "evidence": "技术协议、FAT/SAT记录、培训签到、竣工验收报告、客户签字和案例复盘材料",
            },
        ],
        "next_outputs": ["客户项目标签卡", "角色-采购路径图", "技术架构/点表清单", "FAT/SAT/培训/验收证据包", "90天访谈与机会池"],
    }


def _petrochem_role_tags(data: dict[str, Any]) -> list[str]:
    text = _petrochem_search_text(data)
    tags = ["终端业主", "EPC/总包", "设计院", "盘厂/成套厂", "运维方"]
    if re.search(r"合资|壳牌|Shell|阿美|BASF|Exxon|外资", text, re.I):
        tags.append("合资/外资标准方")
    if re.search(r"园区|基地|大亚湾|湛江|惠州|舟山|连云港|宁东|盘锦", text):
        tags.append("园区平台/基地业主")
    if re.search(r"海上|管道|油气田|站场", text):
        tags.append("站场/平台运维方")
    return _unique_strings(tags)


def _petrochem_entry_tags(data: dict[str, Any]) -> list[str]:
    text = _petrochem_search_text(data)
    tags = ["新建/扩建项目", "存量技改", "智能配电升级", "绿色低碳/能效", "运维服务"]
    if re.search(r"投产|开车|中交|竣工|一期|二期|三期|扩建|在建|开工", text):
        tags.append("建设转运营")
    if re.search(r"海上|油气田|管道|站场", text):
        tags.append("海上平台/油气站场")
    if re.search(r"码头|储运|港口|罐区", text):
        tags.append("储运/码头公辅")
    if re.search(r"煤化工|煤制|轻烃|乙烯|烯烃|芳烃|炼化", text):
        tags.append("高耗能装置能效")
    return _unique_strings(tags)


def _petrochem_phase_tags(data: dict[str, Any]) -> list[str]:
    text = _petrochem_search_text(data)
    if re.search(r"投产|开车|中交|竣工|一期|二期|三期|扩建|在建|开工|一体化基地", text):
        return [
            "方案/选型",
            "硬件采购",
            "软件采购",
            "FAT",
            "预调试",
            "现场安装",
            "集成调试",
            "SAT",
            "培训交付",
            "验收归档",
            "运维服务",
        ]
    return ["线索识别", "方案阶段", "选型阶段", "报价/商务", "制造/集成", "调试/交付", "运维服务", "复盘复制"]


def _petrochem_scene_tags(data: dict[str, Any]) -> list[str]:
    text = _petrochem_search_text(data)
    tags = ["公辅/变电所", "MCC/关键负载", "智能配电", "能效/碳管理"]
    if re.search(r"炼化|炼油|炼厂", text):
        tags.append("炼化一体化")
    if re.search(r"乙烯|烯烃|聚烯烃|芳烃", text):
        tags.append("乙烯/烯烃")
    if re.search(r"新材料|聚氨酯|工程塑料|精细化工|化工材料", text):
        tags.append("化工新材料")
    if re.search(r"码头|储运|罐区|港口", text):
        tags.append("储运/码头")
    if re.search(r"海上|油气田", text):
        tags.append("海上平台/油气田")
    if re.search(r"煤化工|煤制|宁东", text):
        tags.append("煤化工")
    return _unique_strings(tags)


def _petrochem_search_text(data: dict[str, Any]) -> str:
    chunks: list[str] = []
    for section_name in ("name", "aliases"):
        value = data.get(section_name)
        if isinstance(value, list):
            chunks.extend(str(item) for item in value)
        elif value:
            chunks.append(str(value))
    for section_name in ("profile", "facts", "public_details"):
        section = data.get(section_name, {})
        if isinstance(section, dict):
            chunks.extend(str(value) for value in section.values())
    return " ".join(chunks)


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _petrochem_portrait(
    customer: str,
    data: dict[str, Any],
    opportunities: list[dict[str, str]],
    risks: list[str],
    gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = data["profile"]
    facts = data["facts"]
    portrait = {
        "headline": f"{profile['short_name']}是{profile['account_type']}，适合按基地、装置和项目制经营",
        "tags": ["石化/化工KA", profile["opportunity_level"] + "机会", profile["risk_level"] + "风险", "基地型经营", "内部数据待补"],
        "business_role": f"该客户的核心业务为{facts['business']}，对配电可靠性、装置连续生产、安全环保和能效管理要求高。",
        "relationship_strategy": f"优先围绕{profile['recommended_focus']}切入；公开资料用于建立机会方向，成交推进仍需施耐德内部交易和客户访谈闭环。",
        "needs": [
            "关键装置供配电可靠性",
            "新建/扩建项目开车与运维",
            "能源管理和电气资产健康",
            "安环合规与绿色低碳",
        ],
        "pain_points": [
            facts["risk"],
            "施耐德历史采购、授权、满意度和关键人信息需内部拉通",
            "集团、上市公司、项目公司和基地采购主体需要拆分管理",
        ],
        "decision_chain": [
            {"role": "集团/项目公司高层", "focus": "战略合作、重点基地、投资项目和安全底线"},
            {"role": "设备/电仪/技术部门", "focus": "供配电可靠性、标准选型、备件、保护配合和系统集成"},
            {"role": "采购/供应链", "focus": "供应商准入、框架协议、价格、交期和本地服务"},
            {"role": "安环/能源管理/数字化", "focus": "节能降碳、合规、能源可视化和资产健康"},
        ],
        "next_questions": [
            "施耐德在该客户哪些基地/项目已有采购和服务记录？",
            "当前在建、技改和开车项目对应的电气包负责人是谁？",
            "哪些装置存在故障、备件、能效或电能质量痛点？",
        ],
    }
    portrait["top_opportunities"] = _portrait_top_opportunities(opportunities)
    portrait["top_risks"] = risks[:3]
    portrait["must_fill_fields"] = [
        {"field": gap["field"], "module": gap["module_name"], "status": gap["status"]} for gap in gaps[:5]
    ]
    return portrait


def _petrochem_basic_info(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_src(data)
    return [
        _basic_row("企业名称", _petrochem_fact(data, "entity"), "集团/上市公司/项目公司主体", src),
        _basic_row("统一社会信用代码", "需按具体采购主体和项目公司工商底档补齐", "企业唯一标识", []),
        _basic_row("成立时间", "集团、上市公司或项目公司成立时间需按签约主体区分；公开资料已确认其业务和项目背景", "企业经营年限", src),
        _basic_row("注册资本", "需按具体签约主体工商底档补齐，集团/项目公司口径不宜混用", "反映企业规模", []),
        _basic_row("企业性质", _petrochem_fact(data, "nature"), "国企/民企/外资/合资", src),
        _basic_row("股权结构", _petrochem_fact(data, "ownership"), "主要股东及持股比例", src),
        _basic_row("法人代表", "需按具体采购或签约主体工商底档补齐", "企业法定代表人", []),
        _basic_row("注册地址", "需按集团、上市公司、基地公司或项目公司主体分别补齐", "企业注册地", []),
        _basic_row("实际经营地址", _petrochem_fact(data, "projects"), "生产基地/办公地址", src),
    ]


def _petrochem_certifications(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_src(data)
    return [
        _certification_row("低压成套设备生产资质", "该KA通常为终端业主/炼化化工企业，不是盘厂生产资质评价对象；需核验其EPC、盘厂、运维承包商短名单", "资质与认证", []),
        _certification_row("高压成套设备资质", "该KA通常采购高低压成套设备而非自行对外生产；需核验基地电气运维资质、承包商准入和设备包标准", "资质与认证", []),
        _certification_row("ISO体系认证", "公开资料可确认其ESG、安环、质量或集团治理线索；ISO9001/14001/45001证书编号与有效期需客户或基地资料补齐", "ISO9001/14001/45001等", src),
        _certification_row("特种设备生产许可证", "炼化/化工项目涉及压力容器、危化、安全生产等合规边界；需按项目公司和装置许可清单核验", "资质名称与等级", src),
        _certification_row("电力承包施工资质", "终端业主一般通过EPC/施工/运维承包商执行，需核验其准入承包商及施耐德可合作的电气施工伙伴", "资质名称与等级", []),
        _certification_row("承装修试资质", "需核验厂区电气运维团队或外包单位的承装/承修/承试资质等级和服务边界", "资质名称与等级", []),
        _certification_row("施耐德授权等级", "不适用盘厂授权口径；需改为核验施耐德是否进入业主品牌库、框架协议、项目合格供应商和EPC技术规范", "协议厂/授权盘厂/战略合作伙伴", []),
    ]


def _petrochem_scale_finance(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    src = _petrochem_src(data)
    return {
        "enterprise_scale": [
            _metric_row("员工总数", "公开资料未必披露项目公司口径；需按集团、基地和项目公司拆分补齐", "在职员工数量", []),
            _metric_row("技术人员数量", "大型炼化/化工企业具备电仪、设备、工艺、安环、数字化等专业团队，具体人数需访谈或组织资料补齐", "设计、研发、技术支持人员", src),
            _metric_row("生产人员数量", "连续生产基地生产、设备、电仪与外委运维人员口径需按基地补齐", "生产一线员工", []),
            _metric_row("销售人员数量", "终端业主销售体系与盘厂口径不同；可按化工品/能源销售或客户经理体系补充", "销售团队规模", []),
            _metric_row("厂房面积", _petrochem_fact(data, "projects"), "生产场地面积（㎡）", src),
            _metric_row("生产基地数量", _petrochem_fact(data, "scale"), "有几个生产基地", src),
            _metric_row("年产能", _petrochem_fact(data, "products"), "年产高低压柜体数量/产值；石化KA改按装置/产品产能理解", src),
        ],
        "financial_status": [
            _metric_row("年营业收入", _petrochem_fact(data, "finance"), "最近三年营业收入", src),
            _metric_row("净利润", _petrochem_fact(data, "finance"), "最近三年净利润", src),
            _metric_row("资产负债率", "上市公司可由年报补齐，项目公司和合资公司需工商/审计/授信资料核验", "财务健康度指标", src),
            _metric_row("现金流状况", "需结合年报经营现金流、项目资本开支、施耐德账期和回款记录判断", "经营性现金流是否健康", src),
        ],
    }


def _petrochem_business_capability(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "主营业务",
            "rows": [
                _business_row("主营产品类型", _petrochem_detail(data, "business_products", "products"), "高压柜/低压柜/箱变/配电箱等；石化KA改按终端装置与化工产品理解", src),
                _business_row("产品线覆盖", _petrochem_detail(data, "business_products", "business"), "全产品线", src),
                _business_row("主营行业领域", _petrochem_detail(data, "resources", "market"), "建筑/工业/电力/新能源等", src),
                _business_row("业务收入结构", _petrochem_detail(data, "business_revenue", "finance"), "各业务板块收入占比", src),
            ],
        },
        {
            "category": "技术能力",
            "rows": [
                _business_row("设计团队规模", "大型项目通常由业主技术、电仪、设计院/EPC和供应商联合完成；客户内部电气设计人数需访谈补齐。公开技术能力线索：" + _petrochem_detail(data, "business_technology", "digital"), "电气设计人员数量", src),
                _business_row("设计软件使用", "公开资料未披露EPLAN/CAD/三维设计等工具；需访谈业主电仪团队、EPC和盘厂承包商", "EPLAN/CAD/三维设计等", []),
                _business_row("研发投入占比", _petrochem_detail(data, "business_technology", "digital"), "研发费用/营业收入", src),
                _business_row("专利数量", "化工和新材料企业通常具备专利储备，但本初版未逐项检索知识产权数量，需补查国家知识产权平台和年报附注", "发明专利/实用新型/外观设计", []),
                _business_row("技术合作方", "重点合作方包括设计院、EPC、设备包商、自动化/DCS、电气成套和运维承包商，具体名单需项目访谈补齐", "与哪些设计院/高校合作", []),
            ],
        },
        {
            "category": "生产能力",
            "rows": [
                _business_row("生产设备水平", _petrochem_detail(data, "business_projects", "scale"), "自动化程度/设备先进性", src),
                _business_row("质量控制体系", "连续生产和危化场景对联锁、供电、检维修、备件和安环质量闭环要求高；公开技术线索显示：" + _petrochem_detail(data, "business_technology", "digital"), "检测设备、质检流程", src),
                _business_row("生产周期", "连续流程型生产不适用盘厂下单交付周期口径；可改按项目建设、检修窗口和备件响应周期管理", "从下单到交付的平均周期", []),
                _business_row("准时交付率", "需按施耐德历史订单、EPC交付节点、项目开车和检修窗口验证", "历史订单准时交付比例", []),
                _business_row("质量合格率", "需以设备故障率、开车一次成功率、停机事件、售后质量和现场服务记录衡量", "产品一次合格率", []),
            ],
        },
        {
            "category": "项目经验",
            "rows": [
                _business_row("代表性项目", _petrochem_detail(data, "business_projects", "projects"), "历史标杆项目案例", src),
                _business_row("项目类型分布", "炼油、乙烯、芳烃、聚烯烃、新材料、公辅、储运、码头、变电所、数字化和绿色低碳项目；客户公开项目线索：" + _petrochem_detail(data, "business_projects", "projects"), "建筑/工业/市政/电力等占比", src),
                _business_row("项目地域分布", _petrochem_detail(data, "sales_market", "market"), "业务覆盖省份/城市", src),
                _business_row("大型项目经验", _petrochem_detail(data, "business_projects", "projects"), "500万+项目经验", src),
                _business_row("行业标杆客户", "该KA本身即行业标杆终端业主；其下游客户和合作伙伴线索：" + _petrochem_detail(data, "resources", "market"), "服务过的知名客户", src),
            ],
        },
    ]


def _petrochem_supply_procurement(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "施耐德合作情况",
            "rows": [
                _supply_row("合作年限", "公开资料未披露与施耐德合作年限，需CRM/ERP、框架协议和客户经理记录补齐", "与施耐德合作多少年", []),
                _supply_row("合作模式", _petrochem_detail(data, "procurement_mode"), "协议厂/授权盘厂/普通客户；石化KA应改按业主品牌库/EPC规范/项目供应商管理", src),
                _supply_row("历史采购额", "需按集团、基地、项目公司、EPC和经销商供货路径拉通近三年采购额", "近三年施耐德产品采购额", []),
                _supply_row("采购增长率", "需以近三年施耐德订单、项目开车、技改和检修备件数据计算", "采购额同比增长率", []),
                _supply_row("主要采购产品", _petrochem_detail(data, "procurement_products"), "断路器/接触器/变频器/软启等", src),
                _supply_row("授权柜体型号", "业主口径不直接等同盘厂授权；需核验BlokSeT/Okken/MVnex等是否进入业主/EPC规范和盘厂承包商授权范围", "BlokSeT/Okken/MVnex等", []),
                _supply_row("合作满意度", "需通过设备、电仪、采购、项目和服务团队访谈补齐对施耐德价格、交付、技术支持和售后响应评价", "对施耐德服务、技术支持的满意度", []),
            ],
        },
        {
            "category": "竞品采购情况",
            "rows": [
                _supply_row("主要竞品品牌", _petrochem_detail(data, "competitors"), "西门子/ABB/正泰/德力西等", src),
                _supply_row("竞品采购比例", "公开资料无法判断，需由项目BOM、供应商清单和施耐德赢丢单复盘测算", "竞品采购额占总采购比例", []),
                _supply_row("竞品使用原因", _petrochem_detail(data, "decision_factors"), "价格/技术/服务/关系等", src),
                _supply_row("竞品优势感知", "竞品可能在既有装置装机基础、项目包绑定、本地价格和EPC关系上有优势；客户决策因素：" + _petrochem_detail(data, "decision_factors"), "认为竞品哪些方面更有优势", src),
            ],
        },
        {
            "category": "其他供应商",
            "rows": [
                _supply_row("其他器件供应商", "需梳理EPC、设计院、主机包、DCS、仪表、变压器、中压柜、低压柜、UPS、变频和服务承包商名单；公开采购生态：" + _petrochem_detail(data, "procurement_mode"), "其他核心供应商", src),
                _supply_row("柜体供应商", "终端业主通常通过授权盘厂/EPC/成套厂采购柜体；需识别已入围盘厂和施耐德可影响的设计规范", "是否自产柜体或外购", []),
                _supply_row("供应链稳定性", "大型连续生产基地对备件、保供和检修窗口响应极敏感；公开痛点线索：" + _petrochem_detail(data, "pain_business"), "是否有稳定供货渠道", src),
            ],
        },
    ]


def _petrochem_resources(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "客户结构",
            "rows": [
                _resource_row("主要客户类型", _petrochem_detail(data, "resources", "market"), "终端业主/总包/设计院/经销商", src),
                _resource_row("客户行业分布", _petrochem_detail(data, "resources", "market"), "建筑/工业/电力/新能源/交通等", src),
                _resource_row("客户地域分布", _petrochem_detail(data, "sales_market", "scale"), "主要服务区域", src),
                _resource_row("头部客户名单", _petrochem_detail(data, "resources", "market") + "；公开资料通常不完整披露前十大终端客户，需年报客户集中度或销售访谈补齐。", "前10大客户名称及行业", src),
                _resource_row("头部客户收入占比", "上市公司年报可补充客户集中度，合资/项目公司需内部或客户资料补齐", "前10大客户收入贡献", []),
            ],
        },
        {
            "category": "客户关系",
            "rows": [
                _resource_row("客户粘性", "能源化工产品通常具备长期供销、框架、直销和大客户关系；公开市场线索：" + _petrochem_detail(data, "sales_market", "market"), "客户复购率/合作年限", src),
                _resource_row("客户获取方式", _petrochem_detail(data, "sales_market", "market"), "招投标/关系介绍/市场开发等", src),
                _resource_row("客户满意度", "公开资料未披露系统满意度，需由其终端客户反馈、质量投诉和销售服务资料补充；对施耐德经营可先关注该KA内部满意度", "客户对其服务/产品质量的评价", []),
            ],
        },
    ]


def _petrochem_sales_market(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "销售体系",
            "rows": [
                _sales_row("销售团队规模", "终端客户销售人员口径需按能源、化工品、新材料、区域销售或合资公司补齐", "销售人员数量", []),
                _sales_row("销售模式", _petrochem_detail(data, "sales_market", "market"), "直销/经销/代理", src),
                _sales_row("销售区域划分", _petrochem_detail(data, "sales_market", "market"), "如何划分销售区域", src),
                _sales_row("销售渠道", _petrochem_detail(data, "sales_market", "market"), "自有渠道/合作渠道", src),
                _sales_row("招投标能力", "作为终端业主更多体现为采购招标能力；作为产品销售方则需按化工品销售体系补齐", "投标成功率、标书制作能力", []),
            ],
        },
        {
            "category": "市场覆盖",
            "rows": [
                _sales_row("覆盖省份", _petrochem_detail(data, "sales_market", "scale"), "业务覆盖哪些省份", src),
                _sales_row("重点市场", _petrochem_detail(data, "resources", "market"), "核心市场区域", src),
                _sales_row("市场定位", _petrochem_detail(data, "strategy", "strategy"), "高端/中端/低端市场", src),
                _sales_row("品牌影响力", f"{data['profile']['short_name']}为行业重点客户，公开资料显示其项目或产业地位较强", "在当地市场的知名度", src),
            ],
        },
        {
            "category": "价格策略",
            "rows": [
                _sales_row("价格水平", "化工品价格受周期、油价/煤价/轻烃价差、供需和合约影响；公开市场压力：" + _petrochem_detail(data, "pain_market"), "相对市场均价的高低", src),
                _sales_row("价格敏感度", "采购端对电气设备价格敏感，但关键负载、安全、连续生产和开车节点更看重可靠性、服务和全生命周期成本；决策因素：" + _petrochem_detail(data, "decision_factors"), "对价格竞争的态度", src),
            ],
        },
    ]


def _petrochem_org_decision(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "组织架构",
            "rows": [
                _org_row("公司组织架构图", _petrochem_detail(data, "org_chain"), "部门设置、汇报关系", src),
                _org_row("决策层级", _petrochem_detail(data, "org_chain"), "决策流程有几级", src),
                _org_row("关键部门", _petrochem_detail(data, "org_chain"), "采购部、技术部、生产部、销售部", src),
            ],
        },
        {
            "category": "关键决策人",
            "rows": [
                _org_row("董事长/总经理", "公开资料可从年报/官网补齐集团高层；对施耐德成交更关键的是基地总经理、项目负责人和设备/电仪负责人", "姓名、背景、管理风格", src),
                _org_row("采购负责人", "需客户经理和项目访谈补齐采购负责人姓名、权限、准入流程和价格决策边界", "姓名、职位、决策权限", []),
                _org_row("技术负责人", "需确认电仪、设备、设计院/EPC技术负责人及其对品牌、标准、保护和通信方案的偏好", "姓名、职位、技术偏好", []),
                _org_row("生产负责人", "需确认生产运行、检维修和装置负责人，其关注点通常是停机风险、备件、开车和故障响应", "姓名、职位、生产管理风格", []),
                _org_row("销售负责人", "若作为化工产品销售方需补齐销售负责人；施耐德经营该KA时优先关注采购/设备/项目链条", "姓名、职位、市场策略", []),
            ],
        },
        {
            "category": "决策流程",
            "rows": [
                _org_row("采购决策流程", _petrochem_detail(data, "procurement_mode") + "；通常由需求部门提出，技术/设备评审，采购组织招采，安环/项目/EPC参与，最终按授权层级批准。", "谁提议-谁评估-谁批准", src),
                _org_row("技术选型流程", _petrochem_detail(data, "decision_factors"), "技术评审参与方", src),
                _org_row("决策周期", "需按新建项目、年度框架、技改、检修备件和紧急抢修五类周期拆分", "从需求到采购决策的周期", []),
                _org_row("决策影响因素", _petrochem_detail(data, "decision_factors"), "价格/质量/服务/关系等权重", src),
            ],
        },
    ]


def _petrochem_strategy_needs(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "战略方向",
            "rows": [
                _strategy_row("短期目标", _petrochem_detail(data, "strategy", "strategy"), "1-2年内的发展目标", src),
                _strategy_row("中长期规划", _petrochem_detail(data, "strategy", "strategy"), "3-5年发展战略", src),
                _strategy_row("业务扩张计划", _petrochem_detail(data, "business_projects", "projects"), "是否计划拓展新业务领域", src),
                _strategy_row("区域扩张计划", _petrochem_detail(data, "sales_market", "market"), "是否计划拓展新市场区域", src),
            ],
        },
        {
            "category": "数字化转型",
            "rows": [
                _strategy_row("数字化现状", _petrochem_detail(data, "digital", "digital"), "ERP/MES/CRM等系统使用情况", src),
                _strategy_row("数字化需求", _petrochem_detail(data, "digital", "digital"), "对数字化工厂、智能生产的需求", src),
                _strategy_row("数字化预算", "公开资料通常不披露预算，需从年度技改、智能工厂、信息化和项目资本开支中核验", "数字化转型投入预算", []),
            ],
        },
        {
            "category": "绿色低碳",
            "rows": [
                _strategy_row("双碳目标", _petrochem_detail(data, "green", "green"), "是否制定碳减排目标", src),
                _strategy_row("绿色产品需求", _petrochem_detail(data, "green", "green"), "对环保型产品的需求", src),
                _strategy_row("ESG评级", "上市公司可补充ESG评级和报告，合资/项目公司需从集团或当地政府披露资料补齐", "企业ESG评级情况", src),
            ],
        },
        {
            "category": "电气升级需求",
            "rows": [
                _strategy_row("智能配电需求", _petrochem_detail(data, "electrical_needs"), "对智能配电柜、物联网的需求", src),
                _strategy_row("能效管理需求", _petrochem_detail(data, "electrical_needs"), "对能耗监测、节能改造的需求", src),
                _strategy_row("设备更新需求", "需按在建开车、年度检修、技改、老旧装置替换和国产化项目核验设备更新计划", "现有设备更新换代计划", []),
            ],
        },
    ]


def _schneider_pain_playbook() -> dict[str, dict[str, Any]]:
    return {
        "生产效率痛点": {
            "stage": "方案阶段 -> 运维服务",
            "advantage": "EcoStruxure Power and Process 面向流程工业统一电力与过程，官方资料强调可改善过程能耗、减少非计划停机并提升盈利；PME可把能耗、电能质量和电气健康数据转成可行动分析。",
            "playbook": "选盛虹炼化/斯尔邦1个高耗能装置或MCC室做30天诊断：采集负载、电能质量、停机事件和检修记录，形成“停机损失+能耗浪费+备件响应”TCO表，再提出MCC/变频/PME/服务SLA组合。",
            "output": "装置级TCO测算表、能耗异常清单、优先改造回路、90天试点方案",
            "source_ids": ["SE4", "SE2", "KB1"],
        },
        "质量管控痛点": {
            "stage": "选型阶段 -> FAT/SAT",
            "advantage": "BlokSeT MB/iPMCC强调低压/MCC安全、可靠和连接能力，包含实时热监测、弧光防护和预测维护；Power Commission可用于低压断路器和数字化配电柜的配置、测试、调试和报告。",
            "playbook": "把质量议题前移到技术协议：关键回路采用BlokSeT/MCC可靠性语言，要求温度/湿度/弧光监测、保护整定复核、FAT/SAT报告和投运后30/90天健康检查，避免只看出厂合格证。",
            "output": "FAT/SAT检查表、热风险监测点表、保护整定复核表、投运健康报告模板",
            "source_ids": ["SE5", "SE6", "KB1"],
        },
        "供应链痛点": {
            "stage": "报价/商务阶段 -> 制造/集成",
            "advantage": "研修院知识库强调盘厂项目要抓业主、EPC、设计院、盘厂、系统集成和运维边界；Power Build 可输出中压柜配置、SLD、BOM、技术规格和订货文件，降低配置与BOM错误。",
            "playbook": "组织一次“业主-EPC/设计院-盘厂-自动化包商”四方BOM冻结会：明确施耐德柜内元件、通讯网关、数据点、备件、交期、变更审批和现场调试边界；对关键物料做Kitting/分批交付清单。",
            "output": "BOM冻结清单、接口责任矩阵、备件安全库存、变更审批表",
            "source_ids": ["SE8", "KB1", "KB2"],
        },
        "人才痛点": {
            "stage": "调试/交付阶段 -> 运维服务",
            "advantage": "施耐德数字服务结合预测分析、AI、远程监控和Connected Services Hub，可支持资产健康、远程诊断和主动运维；研修院课程可把客户团队按三层两闭环补齐能力。",
            "playbook": "为电仪、设备、安环、能源管理和数字化团队做半天联合工作坊：先讲互联互通产品、边缘控制、应用服务三层，再用Power Commission/PME/资产健康案例演示数据如何进入运维闭环。",
            "output": "角色培训计划、数据点责任表、远程诊断流程、运维SLA样板",
            "source_ids": ["SE7", "SE6", "KB1"],
        },
        "设计能力痛点": {
            "stage": "线索识别 -> 选型阶段",
            "advantage": "施耐德可用选型指南、BlokSeT/Prisma/Power Build、PME/PO和EcoStruxure架构把方案从元件清单提升为系统架构，帮助设计院/EPC提前确定单线图、BOM、保护配合和通讯点表。",
            "playbook": "在设计院/EPC澄清会前输出一版“关键装置电气包模板”：单线图、柜型建议、断路器保护配合、通讯架构、仪表/电气数据接口、FAT/SAT边界，先锁规范再进报价。",
            "output": "技术澄清包、SLD/BOM模板、通讯点表、设计院问诊清单",
            "source_ids": ["SE8", "SE1", "KB1"],
        },
        "技术成本痛点": {
            "stage": "方案阶段 -> 商务决策",
            "advantage": "PME支持能源可视化、正式审计、指标分析、成本分摊和节能验证；Power and Process强调从TOTEX角度改善能耗、减少停机和提升盈利，适合对抗单纯低价采购。",
            "playbook": "不要只报柜体价，改做三列商务对比：一次采购价、停机/检修风险、能耗和运维成本。用PME/ISO 50001口径给出可验证KPI：电能质量事件、能耗异常、节能验证和故障响应时间。",
            "output": "TCO对比表、节能验证KPI、运维成本假设、商务价值页",
            "source_ids": ["SE2", "SE4", "ISO1"],
        },
        "技术人才痛点": {
            "stage": "项目定义 -> 复盘复制",
            "advantage": "研修院项目模式强调角色+阶段+层级+证据打标，智能配电项目按互联互通产品、边缘控制、应用分析与服务三层交付，可减少客户内部和承包商能力差异。",
            "playbook": "把技术人才缺口转成项目打标表：每个项目标注谁负责硬件安装、软件配置、FAT、预调试、现场放线、集成调试、SAT、培训交付；缺口处由施耐德专家/服务伙伴补位。",
            "output": "项目角色RACI、三层能力缺口表、联合调试计划、复盘复制模板",
            "source_ids": ["KB1", "SE1", "SE6"],
        },
        "市场竞争压力": {
            "stage": "线索识别 -> 商务决策",
            "advantage": "施耐德优势不在常规低价，而在关键负载可靠性、全球流程工业经验、智能配电、生命周期服务和电力过程一体化；这些能把竞争从价格转向风险和业务结果。",
            "playbook": "对每个机会打“低价可替代/高可靠不可替代”标签：常规回路只做选择性参与，关键装置、MCC室、公辅变电所、码头储运和连续生产负载优先争取业主/EPC规范前置。",
            "output": "机会分级表、不可替代价值清单、业主/EPC规范前置材料",
            "source_ids": ["SE4", "SE5", "SE7", "KB1"],
        },
        "客户需求变化": {
            "stage": "方案阶段 -> 运维服务",
            "advantage": "EcoStruxure Power的三层架构、PME、Power Operation和数字服务可把智能配电、能效、电能质量、告警、资产健康和预测维护连接到客户现有工业数据体系。",
            "playbook": "围绕东方盛虹流程工业智能大模型，提出“电气数据接入包”：明确采集哪些断路器、仪表、温度、弧光、电能质量和告警数据，由PME/PO形成报表和API/接口边界。",
            "output": "电气数据接入清单、PME/PO场景图、告警分级、API/接口边界",
            "source_ids": ["SE1", "SE2", "SE3", "SE7"],
        },
        "行业政策变化": {
            "stage": "战略沟通 -> 复盘复制",
            "advantage": "施耐德在能源管理、ISO 50001、能效审计、碳与能源数据、Power and Process低碳场景上有完整叙事，能把政策合规变成绿色工厂和能效项目。",
            "playbook": "对接安环/能源管理/ESG团队，先做能源与电气健康基线，再选择一个绿色工厂或公辅系统做试点；输出合规报表、能效改善和可复制样板，而不是只卖设备。",
            "output": "能源基线、绿色工厂电气改造清单、合规报表、样板项目复盘",
            "source_ids": ["SE4", "SE2", "ISO1", "KB1"],
        },
    }


def _petrochem_pain_opportunities(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    risk = _petrochem_detail(data, "risk_stability", "risk")
    efficiency_pain = _petrochem_detail(data, "pain_business_efficiency", "pain_business")
    quality_pain = _petrochem_detail(data, "pain_business_quality", "pain_technical")
    supply_chain_pain = _petrochem_detail(data, "pain_business_supply_chain", "procurement_mode") + "；大型基地备件、进口设备、本地服务和EPC多包接口复杂。"
    details = data.get("public_details") or {}
    talent_pain = str(
        details.get(
            "pain_business_talent",
            "电仪、数字化、能源管理和安全运维需要复合型人才，项目扩建和装置爬坡会放大人才缺口",
        )
    )
    playbook = _schneider_pain_playbook()
    return [
        {
            "category": "业务痛点",
            "rows": [
                _pain_row("生产效率痛点", efficiency_pain, "把降本增效从“价格”转成“停机损失、能耗、检修效率和开车保障”的TCO比较", "生产过程中效率低下的环节", _source_union(src, playbook["生产效率痛点"]["source_ids"]), playbook["生产效率痛点"]),
                _pain_row("质量管控痛点", quality_pain, "把质量管控从“出厂合格”升级为“柜体/MCC可靠性、热风险、弧光风险、FAT/SAT和长期运行证据”", "质量问题的频发点", _source_union(src, playbook["质量管控痛点"]["source_ids"]), playbook["质量管控痛点"]),
                _pain_row("供应链痛点", supply_chain_pain, "建立业主-EPC-设计院-盘厂-自动化包商共同认可的BOM、交付边界、备件和数据接口闭环", "供货、库存、物流等问题", _source_union(src, playbook["供应链痛点"]["source_ids"]), playbook["供应链痛点"]),
                _pain_row("人才痛点", talent_pain, "用研修院打法把客户团队从传统电仪维护带到智能配电、能效、HSE和预测维护的项目化能力", "人才招聘、培养、流失问题", _source_union(src if "pain_business_talent" in details else [], playbook["人才痛点"]["source_ids"]), playbook["人才痛点"]),
            ],
        },
        {
            "category": "技术痛点",
            "rows": [
                _pain_row("设计能力痛点", _petrochem_detail(data, "decision_factors"), "共建业主标准、典型单线图、BOM模板、保护配合和通信架构", "设计效率、标准化程度问题", _source_union(src, playbook["设计能力痛点"]["source_ids"]), playbook["设计能力痛点"]),
                _pain_row("技术成本痛点", _petrochem_detail(data, "pain_market"), "用TCO、能效收益、故障损失规避和检修效率解释施耐德价值", "成本优化能力不足", _source_union(src, playbook["技术成本痛点"]["source_ids"]), playbook["技术成本痛点"]),
                _pain_row("技术人才痛点", "智能化、低碳和高可靠电气系统需要跨专业能力，客户内部和承包商能力差异会影响落地", "提供现场诊断、培训、联合方案设计和样板间/试点工程", "技术人员能力不足", playbook["技术人才痛点"]["source_ids"], playbook["技术人才痛点"]),
            ],
        },
        {
            "category": "市场痛点",
            "rows": [
                _pain_row("市场竞争压力", risk, "聚焦关键负载、高可靠、智能化和服务能力，避开单纯低价竞争", "来自竞品的压力", _source_union(src, playbook["市场竞争压力"]["source_ids"]), playbook["市场竞争压力"]),
                _pain_row("客户需求变化", _petrochem_detail(data, "electrical_needs"), "以智能配电、能效管理、服务框架和电气资产健康切入", "客户需求升级带来的挑战", _source_union(src, playbook["客户需求变化"]["source_ids"]), playbook["客户需求变化"]),
                _pain_row("行业政策变化", _petrochem_detail(data, "green", "green"), "准备合规、节能、国产化适配和关键场景可靠性材料", "政策调整带来的影响", _source_union(src, playbook["行业政策变化"]["source_ids"]), playbook["行业政策变化"]),
            ],
        },
    ]


def _petrochem_risk_assessment(data: dict[str, Any]) -> list[dict[str, Any]]:
    src = _petrochem_detail_src(data)
    return [
        {
            "category": "经营风险",
            "rows": [
                _risk_assessment_row("财务风险", _petrochem_detail(data, "risk_finance", "finance"), "资金链、负债、回款风险", src),
                _risk_assessment_row("法律风险", "需补查国家企业信用信息公示系统、信用中国、裁判文书、环保处罚和项目环评验收；公开资料仅能提供项目/公告侧线索", "诉讼、行政处罚记录", []),
                _risk_assessment_row("经营稳定性", _petrochem_detail(data, "risk_stability", "risk"), "是否存在经营异常", src),
            ],
        },
        {
            "category": "信用风险",
            "rows": [
                _risk_assessment_row("付款信用", "公开资料不披露对施耐德付款信用，需应收账款、授信、逾期、账期和争议记录补齐", "历史付款是否准时", []),
                _risk_assessment_row("合同履约", "需按施耐德历史项目、EPC交付节点、验收、变更、索赔和服务工单评估履约质量", "合同履约情况", []),
                _risk_assessment_row("售后纠纷", "需补齐设备故障、质量投诉、备件短缺、现场响应和售后争议记录", "售后问题处理情况", []),
            ],
        },
    ]


SUPPLEMENT_INTERNAL_FIELDS = {
    "合作年限",
    "合作模式",
    "历史采购额",
    "采购增长率",
    "主要采购产品",
    "授权柜体型号",
    "合作满意度",
    "竞品采购比例",
    "竞品使用原因",
    "竞品优势感知",
    "价格水平",
    "价格敏感度",
    "数字化预算",
    "付款信用",
    "合同履约",
    "售后纠纷",
    "客户满意度",
    "客户粘性",
    "采购负责人",
    "技术负责人",
    "生产负责人",
    "销售负责人",
    "采购决策流程",
    "技术选型流程",
    "决策周期",
    "决策影响因素",
    "生产周期",
    "准时交付率",
    "质量合格率",
    "设计软件使用",
    "技术合作方",
    "专利数量",
    "年产能",
    "现金流状况",
    "设备更新需求",
}


SUPPLEMENT_STRONG_GAP_PATTERN = re.compile(
    r"待核验|未披露|无法确认|不能确认|需客户|需内部|需访谈|需.*补齐|待补|未公开|未直接披露|无法.*确认"
)
SUPPLEMENT_SOFT_GAP_PATTERN = re.compile(r"需.*核验|建议|推测|待.*复核|仍需|需.*确认")


def _customer_supplement_plan(customer: str) -> dict[str, Any]:
    rows = _structured_field_lookup(customer)
    items: list[dict[str, Any]] = []
    module_summary: list[dict[str, Any]] = []
    total_counts = {"较完整": 0, "部分完整": 0, "需补充": 0}
    for module, fields in fields_by_module().items():
        counts = {"较完整": 0, "部分完整": 0, "需补充": 0}
        for field in fields:
            row = rows.get(field.field)
            status = _supplement_status(field, row)
            counts[status] += 1
            total_counts[status] += 1
            if status == "较完整":
                continue
            items.append(
                {
                    "module": field.module,
                    "module_name": _module_display_name(field.module),
                    "category": field.category,
                    "field": field.field,
                    "description": field.description,
                    "status": status,
                    "priority": _field_priority(field),
                    "owner": _supplement_owner(field),
                    "data_source": _supplement_data_source(field),
                    "action": _supplement_action(field, row, status),
                    "current_value": _supplement_current_value(row),
                    "source_ids": (row or {}).get("source_ids", []),
                }
            )
        module_summary.append(
            {
                "module": module,
                "name": _module_display_name(module),
                "field_count": len(fields),
                "complete_count": counts["较完整"],
                "partial_count": counts["部分完整"],
                "gap_count": counts["需补充"],
            }
        )
    items.sort(key=lambda item: (_supplement_priority_rank(item["priority"]), _supplement_status_rank(item["status"]), item["module"], item["category"]))
    return {
        "counts": total_counts,
        "module_summary": module_summary,
        "items": items,
    }


def _structured_field_lookup(customer: str) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in _customer_basic_info(customer):
        rows[row["field"]] = row
    for row in _customer_certifications(customer):
        rows[row["field"]] = row
    for group in _customer_scale_finance(customer).values():
        for row in group:
            rows[row["field"]] = row
    for section_func in (
        _customer_business_capability,
        _customer_supply_procurement,
        _customer_resources,
        _customer_sales_market,
        _customer_org_decision,
        _customer_strategy_needs,
        _customer_pain_opportunities,
        _customer_risk_assessment,
    ):
        for section in section_func(customer):
            for row in section.get("rows", []):
                rows[row["field"]] = row
    return rows


def _supplement_status(field: InsightField, row: dict[str, Any] | None) -> str:
    if not row:
        return "需补充"
    value = _supplement_current_value(row)
    source_ids = row.get("source_ids", [])
    if not value or value.strip() in {"待核验", "公开资料未披露", "暂无"}:
        return "需补充"
    if field.field in SUPPLEMENT_INTERNAL_FIELDS:
        return "部分完整" if source_ids and not value.startswith("公开资料未披露") else "需补充"
    if SUPPLEMENT_STRONG_GAP_PATTERN.search(value):
        return "部分完整" if source_ids else "需补充"
    if SUPPLEMENT_SOFT_GAP_PATTERN.search(value):
        return "部分完整"
    return "较完整" if source_ids else "部分完整"


def _supplement_current_value(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    return str(row.get("value") or row.get("pain") or "")


def _supplement_owner(field: InsightField) -> str:
    if field.module.startswith("3."):
        return "施耐德销售/渠道/ERP/CRM"
    if field.module.startswith("6."):
        return "客户经理/关键人访谈"
    if field.module.startswith("8."):
        return "客户访谈/技术服务团队"
    if field.module.startswith("9."):
        return "商务信用/法务/售后"
    if field.category in {"资质认证", "企业规模", "财务状况"}:
        return "公开研究/客户经理/客户资料"
    if field.field in SUPPLEMENT_INTERNAL_FIELDS:
        return "施耐德内部系统/客户访谈"
    return "公开研究/客户经理"


def _supplement_data_source(field: InsightField) -> str:
    if field.module.startswith("3."):
        return "CRM/ERP订单、渠道授权系统、项目BOM、赢丢单复盘、采购访谈"
    if field.module.startswith("6."):
        return "客户经理拜访纪要、组织架构图、关键人访谈、项目复盘"
    if field.module.startswith("9."):
        return "应收账款、授信、逾期、法务记录、售后服务工单、质量投诉"
    if field.category == "资质认证":
        return "客户证书清单、CCC/CQC/型式试验、资质平台、施耐德授权系统"
    if field.category == "财务状况":
        return "年报/审计报表、授信材料、工商年报、内部信用资料"
    if field.category == "企业规模":
        return "官网/招聘资料、环评/项目资料、现场走访、客户访谈"
    if field.module.startswith("4."):
        return "项目清单、客户访谈、销售台账、公开中标信息"
    if field.module.startswith("7."):
        return "官网/公告/ESG、技改项目、战略访谈、预算/项目计划"
    return "官网、政府/公共资源、行业平台、招聘资料、客户访谈"


def _supplement_action(field: InsightField, row: dict[str, Any] | None, status: str) -> str:
    prefix = "补齐" if status == "需补充" else "核验"
    if field.module.startswith("3."):
        return f"{prefix}施耐德交易、授权、BOM、竞品和满意度数据，形成客户采购画像。"
    if field.module.startswith("6."):
        return f"{prefix}关键人姓名、角色权限、采购/技术决策流程和决策周期。"
    if field.module.startswith("9."):
        return f"{prefix}付款、履约、法务、售后和质量闭环记录，判断经营风险。"
    if field.category == "资质认证":
        return f"{prefix}证书编号、等级、有效期、授权范围和对应法人主体。"
    if field.category in {"企业规模", "财务状况"}:
        return f"{prefix}{field.field}的最新口径、年度变化和证据来源。"
    if field.module.startswith("4."):
        return f"{prefix}头部客户、客户集中度、复购和满意度，补强客户资源画像。"
    if field.module.startswith("7."):
        return f"{prefix}战略计划、数字化预算、双碳/ESG和设备更新项目。"
    if field.module.startswith("8."):
        return f"{prefix}真实业务痛点、技术痛点和施耐德可切入机会。"
    return f"{prefix}{field.field}，补充可追溯证据和客户访谈结论。"


def _supplement_priority_rank(priority: str) -> int:
    return {"P1": 0, "P2": 1, "P3": 2}.get(priority, 9)


def _supplement_status_rank(status: str) -> int:
    return {"需补充": 0, "部分完整": 1, "较完整": 2}.get(status, 9)


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
