"""Command line interface for the city industry research generator."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

from .ingest import build_evidence_from_urls, read_url_list
from .report_writer import (
    build_autonomous_web_research_prompt,
    build_llm_prompt,
    generate_with_openai,
    render_report_template,
    write_table_templates,
)
from .schemas import EvidenceCorpus
from .source_discovery import (
    render_source_discovery_plan,
    validate_evidence,
    write_evidence_template,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="city-industry-research",
        description="生成地级市支柱产业与新兴产业深度研究报告材料。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化某城市的研究目录")
    _add_city_args(init_parser)
    init_parser.add_argument("--out", required=True, help="输出目录")

    validate_parser = subparsers.add_parser("validate", help="校验证据库完整性")
    validate_parser.add_argument("--evidence", required=True, help="证据库 JSON")

    render_parser = subparsers.add_parser("render", help="根据证据库渲染报告模板")
    _add_city_args(render_parser)
    render_parser.add_argument("--evidence", required=True, help="证据库 JSON")
    render_parser.add_argument("--out", required=True, help="输出 Markdown 文件")

    prompt_parser = subparsers.add_parser("prompt", help="生成可交给大模型的研究提示词")
    _add_city_args(prompt_parser)
    prompt_parser.add_argument("--evidence", required=True, help="证据库 JSON")
    prompt_parser.add_argument("--out", required=True, help="输出提示词 Markdown 文件")

    ingest_parser = subparsers.add_parser("ingest", help="从官方 URL 列表抓取网页摘录并生成证据库")
    _add_city_args(ingest_parser)
    ingest_parser.add_argument("--urls", required=True, help="每行一个 URL 的 txt 文件")
    ingest_parser.add_argument("--out", required=True, help="输出证据库 JSON")
    ingest_parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="给本批来源添加证据标签，可多次传入，例如 --tag industry_plan --tag official_media",
    )

    generate_parser = subparsers.add_parser("generate", help="使用 OpenAI API 直接生成报告")
    _add_city_args(generate_parser)
    generate_parser.add_argument("--evidence", required=True, help="证据库 JSON")
    generate_parser.add_argument("--out", required=True, help="输出 Markdown 文件")
    generate_parser.add_argument("--model", default="", help="模型名称；也可用 OPENAI_MODEL 环境变量，默认 gpt-5.5")
    generate_parser.add_argument("--web-search", action="store_true", help="启用 OpenAI Web Search 工具自动检索官方来源")

    web_parser = subparsers.add_parser("web", help="启动本地交互式研究界面")
    web_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    web_parser.add_argument("--port", type=int, default=8787, help="监听端口")

    args = parser.parse_args(argv)

    if args.command == "init":
        return _cmd_init(args)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "render":
        return _cmd_render(args)
    if args.command == "prompt":
        return _cmd_prompt(args)
    if args.command == "ingest":
        return _cmd_ingest(args)
    if args.command == "generate":
        return _cmd_generate(args)
    if args.command == "web":
        return _cmd_web(args)

    parser.error("未知命令")
    return 2


def _add_city_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--city", required=True, help="地级市名称，例如：无锡市")
    parser.add_argument("--province", default="", help="省份名称，例如：江苏省")
    parser.add_argument("--year", type=int, default=date.today().year, help="报告年度，默认当前年份")


def _cmd_init(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "00_source_discovery_plan.md").write_text(
        render_source_discovery_plan(args.city, args.province, args.year),
        encoding="utf-8",
    )
    write_evidence_template(out_dir / "01_evidence_template.json", args.city, args.province, args.year)
    empty_corpus = EvidenceCorpus(city=args.city, province=args.province, report_year=args.year)
    (out_dir / "02_llm_research_prompt.md").write_text(
        build_llm_prompt(args.city, args.province, args.year, empty_corpus),
        encoding="utf-8",
    )
    (out_dir / "03_report_template.md").write_text(
        render_report_template(args.city, args.province, args.year, empty_corpus),
        encoding="utf-8",
    )
    write_table_templates(out_dir / "tables")
    print(f"已初始化研究目录：{out_dir}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    corpus = EvidenceCorpus.from_file(args.evidence)
    issues = validate_evidence(corpus)
    if not issues:
        print("证据库已覆盖核心来源类别。")
        return 0
    print("证据库仍有缺口：")
    for issue in issues:
        print(f"- {issue}")
    return 1


def _cmd_render(args: argparse.Namespace) -> int:
    corpus = EvidenceCorpus.from_file(args.evidence)
    city = args.city or corpus.city
    province = args.province or corpus.province
    year = args.year or corpus.report_year or date.today().year
    output = render_report_template(city, province, year, corpus)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(output, encoding="utf-8")
    print(f"已输出报告模板：{args.out}")
    return 0


def _cmd_prompt(args: argparse.Namespace) -> int:
    corpus = EvidenceCorpus.from_file(args.evidence)
    output = build_llm_prompt(args.city or corpus.city, args.province or corpus.province, args.year, corpus)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(output, encoding="utf-8")
    print(f"已输出研究提示词：{args.out}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    url_path = Path(args.urls)
    urls = read_url_list(url_path.read_text(encoding="utf-8").splitlines())
    evidence = build_evidence_from_urls(
        urls=urls,
        city=args.city,
        province=args.province,
        report_year=args.year,
        tags=args.tag,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已抓取 {len(urls)} 条 URL 并输出证据库：{args.out}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    corpus = EvidenceCorpus.from_file(args.evidence)
    if args.web_search:
        prompt = build_autonomous_web_research_prompt(args.city or corpus.city, args.province or corpus.province, args.year)
    else:
        prompt = build_llm_prompt(args.city or corpus.city, args.province or corpus.province, args.year, corpus)
    model = args.model or __import__("os").environ.get("OPENAI_MODEL", "gpt-5.5")
    output = generate_with_openai(prompt, model=model, web_search=args.web_search)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(output, encoding="utf-8")
    print(f"已生成报告：{args.out}")
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    from .webapp import run_web_app

    run_web_app(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
