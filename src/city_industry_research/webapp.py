"""Local web interface for city industry research."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from email.message import EmailMessage
import json
import os
from pathlib import Path
import re
import smtplib
import threading
import traceback
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from .ingest import build_evidence_from_urls, read_url_list
from .official_discovery import (
    build_evidence_from_discovered_sources,
    discover_official_sources,
    write_discovery_outputs,
)
from .report_writer import (
    build_autonomous_web_research_prompt,
    build_llm_prompt,
    extract_response_sources,
    generate_with_openai_response,
    render_report_template,
    write_table_templates,
)
from .schemas import EvidenceCorpus
from .source_discovery import render_source_discovery_plan, validate_evidence, write_evidence_template


ROOT_DIR = Path.cwd()
STATIC_DIR = Path(__file__).with_name("static")
WEB_OUTPUT_DIR = ROOT_DIR / "outputs" / "web"
EXPORT_QUEUE_DIR = ROOT_DIR / "outputs" / "export_requests"


@dataclass
class ResearchJob:
    id: str
    city: str
    province: str = ""
    year: int = datetime.now().year
    status: str = "queued"
    mode: str = "web_search"
    model: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    output_dir: str = ""
    report_path: str = ""
    prompt_path: str = ""
    evidence_path: str = ""
    discovery_path: str = ""
    sources_path: str = ""
    validation_path: str = ""
    report_preview: str = ""
    logs: list[str] = field(default_factory=list)
    validation_events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    export_requests: list[dict[str, Any]] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        self.logs.append(f"{self.updated_at} {message}")

    def record_validation(self, stage: str, status: str, detail: str, **metadata: Any) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        self.updated_at = timestamp
        self.validation_events.append(
            {
                "time": timestamp,
                "stage": stage,
                "status": status,
                "detail": detail,
                "metadata": metadata,
            }
        )

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["has_report"] = bool(self.report_path and Path(self.report_path).exists())
        return data


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ResearchJob] = {}
        self._lock = threading.Lock()

    def add(self, job: ResearchJob) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> ResearchJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: ResearchJob) -> None:
        with self._lock:
            job.updated_at = datetime.now().isoformat(timespec="seconds")
            self._jobs[job.id] = job


JOBS = JobStore()


def run_web_app(host: str = "127.0.0.1", port: int = 8787) -> None:
    WEB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), ResearchRequestHandler)
    print(f"城市产业深度研究界面已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务。")
    finally:
        server.server_close()


class ResearchRequestHandler(SimpleHTTPRequestHandler):
    server_version = "CityIndustryResearch/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature.
        print(f"[web] {self.address_string()} - {format % args}")

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook.
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self._serve_static("index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            filename = path.removeprefix("/static/")
            content_type = _content_type(filename)
            self._serve_static(filename, content_type)
            return
        if path == "/api/status":
            self._json(
                {
                    "ok": True,
                    "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
                    "default_model": os.environ.get("OPENAI_MODEL", ""),
                    "smtp_configured": _smtp_configured(),
                    "output_dir": str(WEB_OUTPUT_DIR),
                    "export_queue_dir": str(EXPORT_QUEUE_DIR),
                }
            )
            return
        if path.startswith("/api/jobs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:
                self._handle_get_job(parts[2])
                return
            if len(parts) == 4 and parts[3] == "report":
                self._handle_get_report(parts[2])
                return
        self._json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib hook.
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/research":
            self._handle_research()
            return
        if path.startswith("/api/jobs/"):
            parts = path.strip("/").split("/")
            if len(parts) == 5 and parts[3] == "export":
                if parts[4] == "email":
                    self._handle_export_email(parts[2])
                    return
                if parts[4] == "google-docs":
                    self._handle_export_google_docs(parts[2])
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

    def _text(self, payload: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_research(self) -> None:
        data = self._read_json()
        city = str(data.get("city") or "").strip()
        if not city:
            self._json({"error": "城市名称不能为空。"}, status=400)
            return
        province = str(data.get("province") or "").strip()
        year = int(data.get("year") or datetime.now().year)
        mode = str(data.get("mode") or "web_search")
        model = str(data.get("model") or os.environ.get("OPENAI_MODEL") or "gpt-5.5")
        job_id = f"{_slugify(province + '-' + city)}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        job = ResearchJob(id=job_id, city=city, province=province, year=year, mode=mode, model=model)
        JOBS.add(job)
        thread = threading.Thread(target=_run_research_job, args=(job, data), daemon=True)
        thread.start()
        self._json({"job": job.public_dict()})

    def _handle_get_job(self, job_id: str) -> None:
        job = JOBS.get(job_id)
        if not job:
            self._json({"error": "job_not_found"}, status=404)
            return
        self._json({"job": job.public_dict()})

    def _handle_get_report(self, job_id: str) -> None:
        job = JOBS.get(job_id)
        if not job or not job.report_path:
            self._json({"error": "report_not_found"}, status=404)
            return
        report = Path(job.report_path)
        if not report.exists():
            self._json({"error": "report_file_missing"}, status=404)
            return
        query = parse_qs(urlparse(self.path).query)
        if query.get("download") == ["1"]:
            self.send_response(200)
            self.send_header("Content-Type", "text/markdown; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{report.name}"')
            body = report.read_bytes()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._text(report.read_text(encoding="utf-8"), content_type="text/markdown; charset=utf-8")

    def _handle_export_email(self, job_id: str) -> None:
        job = JOBS.get(job_id)
        if not job or not job.report_path:
            self._json({"error": "report_not_ready"}, status=400)
            return
        data = self._read_json()
        to_email = str(data.get("to") or "").strip()
        subject = str(data.get("subject") or f"{job.province}{job.city}产业深度研究报告")
        if not to_email:
            self._json({"error": "收件人邮箱不能为空。"}, status=400)
            return
        result = _create_or_send_email_request(job, to_email, subject)
        job.export_requests.append(result)
        JOBS.update(job)
        self._json({"export": result, "job": job.public_dict()})

    def _handle_export_google_docs(self, job_id: str) -> None:
        job = JOBS.get(job_id)
        if not job or not job.report_path:
            self._json({"error": "report_not_ready"}, status=400)
            return
        data = self._read_json()
        title = str(data.get("title") or f"{job.province}{job.city}支柱产业与新兴产业研究报告")
        result = _create_google_docs_request(job, title)
        job.export_requests.append(result)
        JOBS.update(job)
        self._json({"export": result, "job": job.public_dict()})


def _run_research_job(job: ResearchJob, data: dict[str, Any]) -> None:
    try:
        job.status = "running"
        job.log("开始创建研究工作区。")
        job.record_validation("任务启动", "running", f"接收城市：{job.province}{job.city}；报告年度：{job.year}；模式：{job.mode}。")
        output_dir = WEB_OUTPUT_DIR / job.id
        output_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir = str(output_dir)

        plan_path = output_dir / "00_source_discovery_plan.md"
        evidence_path = output_dir / "01_evidence_template.json"
        prompt_path = output_dir / "02_llm_research_prompt.md"
        report_path = output_dir / "report.md"
        validation_path = output_dir / "04_validation_process.md"
        tables_dir = output_dir / "tables"

        plan_path.write_text(render_source_discovery_plan(job.city, job.province, job.year), encoding="utf-8")
        write_evidence_template(evidence_path, job.city, job.province, job.year)
        write_table_templates(tables_dir)
        job.evidence_path = str(evidence_path)
        job.validation_path = str(validation_path)
        job.log("已生成权威来源检索计划、证据模板和企业表格模板。")
        job.record_validation(
            "研究框架生成",
            "done",
            "已根据大纲生成权威来源检索计划、证据模板、企业表格模板。",
            plan_path=str(plan_path),
            evidence_path=str(evidence_path),
        )

        source_urls = read_url_list(str(data.get("source_urls") or "").splitlines())
        corpus = EvidenceCorpus(city=job.city, province=job.province, report_year=job.year)
        if data.get("mode") != "template":
            query_limit = int(data.get("query_limit") or 48)
            max_sources = int(data.get("max_sources") or 120)
            job.log(f"开始自动检索权威来源：最多 {query_limit} 个检索式、{max_sources} 条来源。")
            job.record_validation(
                "自动检索配置",
                "running",
                f"系统将自行搜索权威来源：检索式上限 {query_limit}，来源上限 {max_sources}。",
                query_limit=query_limit,
                max_sources=max_sources,
            )
            hits = discover_official_sources(
                city=job.city,
                province=job.province,
                report_year=job.year,
                query_limit=query_limit,
                max_sources=max_sources,
                progress_callback=lambda event: _record_discovery_event(job, event),
            )
            discovery_path = write_discovery_outputs(output_dir, job.city, job.province, job.year, hits)
            job.discovery_path = str(discovery_path)
            job.log(f"自动发现 {len(hits)} 条权威候选来源，正在抓取网页正文。")
            job.record_validation(
                "自动来源发现",
                "done",
                f"权威候选来源发现完成，共 {len(hits)} 条，已保存发现清单。",
                discovery_path=str(discovery_path),
                source_count=len(hits),
            )
            evidence = build_evidence_from_discovered_sources(
                city=job.city,
                province=job.province,
                report_year=job.year,
                hits=hits,
                progress_callback=lambda event: _record_discovery_event(job, event),
            )
            auto_evidence_path = output_dir / "01_evidence_auto_discovered.json"
            auto_evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
            job.evidence_path = str(auto_evidence_path)
            corpus = EvidenceCorpus.from_file(auto_evidence_path)
            job.log(f"已抓取 {len(corpus.sources)} 条自动发现来源并写入证据库。")
            _record_evidence_summary(job, corpus)

        if source_urls:
            job.log(f"正在抓取 {len(source_urls)} 条用户提供的官方来源链接。")
            job.record_validation(
                "补充来源抓取",
                "running",
                f"检测到 {len(source_urls)} 条用户补充链接，作为自动检索之外的补充证据。",
                source_count=len(source_urls),
            )
            supplemental_evidence = build_evidence_from_urls(
                urls=source_urls,
                city=job.city,
                province=job.province,
                report_year=job.year,
                tags=["supplemental_official_source"],
            )
            merged = _merge_evidence_files(Path(job.evidence_path), supplemental_evidence)
            merged_evidence_path = output_dir / "01_evidence_merged.json"
            merged_evidence_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
            job.evidence_path = str(merged_evidence_path)
            corpus = EvidenceCorpus.from_file(merged_evidence_path)
            job.log("补充来源链接已合并进证据库。")
            job.record_validation(
                "补充来源抓取",
                "done",
                "补充链接已合并进证据库。",
                evidence_path=str(merged_evidence_path),
                total_sources=len(corpus.sources),
            )
            _record_evidence_summary(job, corpus)

        validation_issues = validate_evidence(corpus)
        if validation_issues:
            job.record_validation(
                "证据完整性校验",
                "warning",
                f"证据库仍有 {len(validation_issues)} 个来源缺口，报告会标记待核验。",
                issue_count=len(validation_issues),
            )
            for issue in validation_issues:
                job.record_validation("证据缺口", "warning", issue)
        else:
            job.record_validation("证据完整性校验", "done", "证据库已覆盖核心来源类别。")

        has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
        if data.get("mode") == "template" or not has_openai_key:
            if not has_openai_key:
                job.log("未检测到 OPENAI_API_KEY，已生成可填写的报告模板。")
                job.record_validation("模型生成", "skipped", "未检测到 OPENAI_API_KEY，本次只生成报告模板和证据包。")
            else:
                job.record_validation("模型生成", "skipped", "用户选择只生成模板，本次不调用模型。")
            prompt = build_llm_prompt(job.city, job.province, job.year, corpus)
            report = render_report_template(job.city, job.province, job.year, corpus)
            prompt_path.write_text(prompt, encoding="utf-8")
            report_path.write_text(report, encoding="utf-8")
        else:
            use_model_web_search = bool(data.get("use_model_web_search", True))
            if use_model_web_search and not corpus.sources:
                job.log("自动抓取证据为空，改用模型联网搜索执行完整研究。")
                job.record_validation("模型生成", "running", "自动抓取证据为空，将改用模型联网搜索执行完整研究。")
                prompt = build_autonomous_web_research_prompt(job.city, job.province, job.year)
            else:
                job.log("正在基于自动发现证据生成报告；模型联网搜索将用于补足缺口。")
                job.record_validation(
                    "模型生成",
                    "running",
                    "开始调用模型生成报告；自动发现证据作为主依据，模型联网搜索用于补足缺口。",
                    model=job.model,
                    use_model_web_search=use_model_web_search,
                    source_count=len(corpus.sources),
                )
                prompt = build_llm_prompt(job.city, job.province, job.year, corpus)
            prompt_path.write_text(prompt, encoding="utf-8")
            report, raw_response = generate_with_openai_response(
                prompt=prompt,
                model=job.model,
                timeout_seconds=int(data.get("timeout_seconds") or 600),
                web_search=use_model_web_search,
            )
            report_path.write_text(report, encoding="utf-8")
            job.record_validation("模型生成", "done", "模型已返回报告正文，已写入 Markdown 文件。", report_path=str(report_path))
            sources = extract_response_sources(raw_response)
            if sources:
                sources_path = output_dir / "report.sources.json"
                sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
                job.sources_path = str(sources_path)
                job.log(f"已记录 {len(sources)} 条模型返回的来源引用。")
                job.record_validation(
                    "模型来源引用",
                    "done",
                    f"模型返回 {len(sources)} 条 URL 引用，已保存为来源清单。",
                    sources_path=str(sources_path),
                    source_count=len(sources),
                )

        report_text = report_path.read_text(encoding="utf-8")
        job.report_path = str(report_path)
        job.prompt_path = str(prompt_path)
        job.report_preview = report_text[:5000]
        job.status = "done"
        job.log("研究报告已生成。")
        job.record_validation("任务完成", "done", "研究报告已生成，可在界面预览、下载或导出。", report_path=str(report_path))
        _write_validation_process(job, validation_path)
    except Exception as exc:  # noqa: BLE001 - surface failure in the UI.
        job.status = "error"
        job.error = f"{exc}\n{traceback.format_exc()}"
        job.log(f"研究任务失败：{exc}")
        job.record_validation("任务失败", "error", f"研究任务失败：{exc}")
    finally:
        if job.validation_path:
            _write_validation_process(job, Path(job.validation_path))
        JOBS.update(job)


def _record_discovery_event(job: ResearchJob, event: dict[str, Any]) -> None:
    metadata = dict(event.get("metadata") or {})
    job.record_validation(
        stage=str(event.get("stage") or "自动验证"),
        status=str(event.get("status") or "running"),
        detail=str(event.get("detail") or ""),
        **metadata,
    )
    JOBS.update(job)


def _record_evidence_summary(job: ResearchJob, corpus: EvidenceCorpus) -> None:
    source_type_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    for source in corpus.sources:
        source_type_counts[source.source_type or "unknown"] = source_type_counts.get(source.source_type or "unknown", 0) + 1
        for tag in source.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    job.record_validation(
        "证据库汇总",
        "done",
        f"证据库当前包含 {len(corpus.sources)} 条来源。",
        source_count=len(corpus.sources),
        source_type_counts=source_type_counts,
        tag_counts=tag_counts,
    )


def _write_validation_process(job: ResearchJob, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {job.province}{job.city}深度研究验证过程",
        "",
        f"- 任务编号：{job.id}",
        f"- 状态：{job.status}",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "| 时间 | 阶段 | 状态 | 细节 |",
        "|---|---|---|---|",
    ]
    for event in job.validation_events:
        detail = str(event.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {event.get('time', '')} | {event.get('stage', '')} | {event.get('status', '')} | {detail} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = path.with_suffix(".json")
    json_path.write_text(json.dumps(job.validation_events, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_evidence_files(base_path: Path, supplemental_evidence: dict[str, Any]) -> dict[str, Any]:
    if base_path.exists():
        base = json.loads(base_path.read_text(encoding="utf-8"))
    else:
        base = {
            "sources": [],
            "industry_inventory": {"pillar_industries": [], "emerging_industries": []},
            "enterprise_records": [],
            "assumptions": [],
        }
    base_sources = list(base.get("sources") or [])
    next_index = len(base_sources) + 1
    for item in supplemental_evidence.get("sources") or []:
        copied = dict(item)
        copied["id"] = f"S{next_index:03d}"
        next_index += 1
        base_sources.append(copied)
    base["sources"] = base_sources
    return base


def _create_or_send_email_request(job: ResearchJob, to_email: str, subject: str) -> dict[str, Any]:
    report_text = Path(job.report_path).read_text(encoding="utf-8")
    request_id = f"email-{job.id}-{datetime.now().strftime('%H%M%S')}"
    if _smtp_configured():
        _send_email_via_smtp(to_email=to_email, subject=subject, body=report_text)
        return {
            "id": request_id,
            "type": "email",
            "status": "sent_via_smtp",
            "to": to_email,
            "subject": subject,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }

    request = {
        "id": request_id,
        "type": "email",
        "status": "handoff_required",
        "to": to_email,
        "subject": subject,
        "report_path": job.report_path,
        "instruction": "SMTP 未配置。可在 Codex 中使用 Gmail 连接器根据该请求创建草稿或发送邮件。",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = EXPORT_QUEUE_DIR / f"{request_id}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    request["request_path"] = str(path)
    return request


def _create_google_docs_request(job: ResearchJob, title: str) -> dict[str, Any]:
    request_id = f"gdocs-{job.id}-{datetime.now().strftime('%H%M%S')}"
    request = {
        "id": request_id,
        "type": "google_docs",
        "status": "handoff_required",
        "title": title,
        "report_path": job.report_path,
        "instruction": "Google Docs 需要 Drive 授权。可在 Codex 中使用 Google Drive 连接器根据该请求创建文档。",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path = EXPORT_QUEUE_DIR / f"{request_id}.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    request["request_path"] = str(path)
    return request


def _send_email_via_smtp(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or 587)
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    with smtplib.SMTP(host, port, timeout=60) as smtp:
        smtp.starttls()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _content_type(filename: str) -> str:
    if filename.endswith(".css"):
        return "text/css; charset=utf-8"
    if filename.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if filename.endswith(".html"):
        return "text/html; charset=utf-8"
    return "application/octet-stream"


def _slugify(value: str) -> str:
    value = re.sub(r"\s+", "-", value.strip())
    value = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "city"
