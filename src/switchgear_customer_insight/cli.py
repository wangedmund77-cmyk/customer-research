"""CLI for switchgear customer insight report projects."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from .report_writer import (
    render_framework_summary,
    render_report_template,
    render_research_prompt,
    render_source_plan,
    slugify_customer_name,
    write_customer_project,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="switchgear-customer-insight",
        description="生成施耐德盘厂大客户深度洞察报告项目材料。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="按客户名称初始化洞察项目目录")
    _add_customer_args(init_parser)
    init_parser.add_argument("--out", default="", help="输出目录；默认 outputs/customer_insights/<客户名>")

    prompt_parser = subparsers.add_parser("prompt", help="只生成可交给大模型的研究提示词")
    _add_customer_args(prompt_parser)
    prompt_parser.add_argument("--out", required=True, help="输出 Markdown 文件")

    template_parser = subparsers.add_parser("template", help="只生成报告模板")
    _add_customer_args(template_parser)
    template_parser.add_argument("--out", required=True, help="输出 Markdown 文件")

    source_parser = subparsers.add_parser("source-plan", help="只生成来源计划")
    _add_customer_args(source_parser)
    source_parser.add_argument("--out", required=True, help="输出 Markdown 文件")

    web_parser = subparsers.add_parser("web", help="启动本地网站工作台")
    web_parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    web_parser.add_argument("--port", type=int, default=8790, help="监听端口")

    subparsers.add_parser("framework", help="列出当前盘厂客户洞察模块")

    args = parser.parse_args(argv)

    if args.command == "init":
        out = args.out or str(Path("outputs") / "customer_insights" / slugify_customer_name(args.customer))
        files = write_customer_project(args.customer, out, args.year)
        for path in files:
            print(path)
        return 0
    if args.command == "prompt":
        _write_text(args.out, render_research_prompt(args.customer, args.year))
        return 0
    if args.command == "template":
        _write_text(args.out, render_report_template(args.customer, args.year))
        return 0
    if args.command == "source-plan":
        _write_text(args.out, render_source_plan(args.customer))
        return 0
    if args.command == "web":
        from .webapp import run_web_app

        run_web_app(host=args.host, port=args.port)
        return 0
    if args.command == "framework":
        print(render_framework_summary())
        return 0

    parser.error("未知命令")
    return 2


def _add_customer_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--customer", required=True, help="客户全称，例如：浙江正泰电器股份有限公司")
    parser.add_argument("--year", type=int, default=date.today().year, help="报告年度，默认当前年份")


def _write_text(path: str, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
