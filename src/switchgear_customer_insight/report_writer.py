"""Render prompts and templates for switchgear enterprise insight reports."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from .framework import FRAMEWORK, fields_by_module, module_names, write_field_register


SOURCE_PRIORITY = (
    "上市公司年报、季报、公告、交易所披露",
    "企业官网、ESG/质量/社会责任报告、产品与解决方案页面",
    "国家企业信用信息公示系统、认证认可与资质公示平台",
    "政府、园区、行业协会、招投标平台、官方媒体",
    "施耐德内部CRM、销售台账、价格与服务记录、访谈纪要",
)


def slugify_customer_name(name: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", name.strip()).strip("-")
    return slug or "customer"


def render_source_plan(customer_name: str) -> str:
    return f"""# {customer_name}企业洞察来源计划

## 研究目标

围绕盘厂企业洞察研究框架，形成可用于施耐德电气销售、技术、服务、渠道与管理层沟通的企业画像、机会地图和行动建议。

## 来源优先级

{chr(10).join(f"{idx}. {item}" for idx, item in enumerate(SOURCE_PRIORITY, start=1))}

## 公开资料检索清单

- 公司全称、统一社会信用代码、注册资本、注册地址、法定代表人、股东结构。
- 上市公司或集团财报：营业收入、净利润、现金流、员工、研发、产品线、客户集中度、供应商集中度、重大风险。
- 资质认证：CCC、CQC、UL、CE、VDE、ISO、承装修试、电力承包、特种设备等。
- 业务能力：低压/高压成套、配电箱、箱变、智能配电、自动化、能源管理、储能、充电基础设施。
- 渠道与客户：销售区域、标杆客户、项目案例、经销/直销体系、行业解决方案。
- 战略与需求：数字化、智能制造、绿色低碳、海外本土化、供应链升级、产品迭代。
- 风险：诉讼仲裁、监管处罚、经营异常、财务压力、应收账款、原材料波动、海外政策与汇率。

## 内部资料补充清单

- 与施耐德合作年限、合作模式、授权等级、授权柜体型号。
- 近三年施耐德采购额、产品结构、毛利、付款信用、合同履约和售后纠纷。
- 竞品采购比例、竞品胜出原因、施耐德丢单/赢单复盘。
- 采购负责人、技术负责人、生产负责人、销售负责人及其决策偏好。
- 未来12个月重点项目、技术改造、数字化/低碳预算。
"""


def render_research_prompt(customer_name: str, report_year: int | None = None) -> str:
    year = report_year or date.today().year
    source_lines = "\n".join(f"- {item}" for item in SOURCE_PRIORITY)
    field_lines = "\n".join(f"- {item.module} / {item.category} / {item.field}：{item.description}" for item in FRAMEWORK)
    return f"""你是施耐德电气盘厂企业研究顾问。请为“{customer_name}”撰写深度企业洞察报告，报告年度为 {year}。

研究原则：
1. 对公开事实优先使用权威来源，按以下顺序采信：
{source_lines}
2. 每个关键数字、判断、资质、风险和机会都必须标注来源编号。
3. 对公开资料无法确认的字段，明确写“待内部补充/需访谈核验”，不要猜测。
4. 报告要把企业视角和施耐德行动结合起来：不仅说明企业是谁，还要说明施耐德应如何进入、扩大、守住或修复关系。
5. 涉及采购、价格、满意度、决策链等内部敏感信息时，应列为CRM/销售访谈补充项。

输出结构：
# {customer_name}深度企业洞察报告

## 0. 高层摘要
- 企业定位与业务性质
- 对施耐德的价值判断
- 最值得优先推进的3-5个机会
- 最大风险与关系短板

## 1-9. 按字段框架逐项输出
每个模块需包含：已核验事实、判断、施耐德机会、待补充问题。

字段框架：
{field_lines}

## 10. 施耐德业务机会地图
按“短期切入/中期共创/长期战略合作”输出机会、目标部门、触发事件、推荐产品/解决方案、下一步动作。

## 11. 访谈提纲与内部数据需求
分别面向销售、技术、服务、渠道、财务/信用控制列出问题。

## 12. 来源附录
列出来源编号、标题、发布方、日期、链接、用于支撑的结论。
"""


def render_report_template(customer_name: str, report_year: int | None = None) -> str:
    year = report_year or date.today().year
    lines = [
        f"# {customer_name}深度企业洞察报告",
        "",
        f"- 报告年度：{year}",
        f"- 生成日期：{date.today().isoformat()}",
        "- 适用对象：施耐德电气盘厂客户部、销售、技术支持、服务与渠道管理团队",
        "- 口径说明：公开资料已核验；内部采购、满意度、授权等级、决策链等字段需由施耐德CRM、销售台账或客户访谈补充。",
        "",
        "## 0. 高层摘要",
        "",
        "- 企业定位：待研究。",
        "- 施耐德价值判断：待研究。",
        "- 优先机会：待研究。",
        "- 关键风险：待研究。",
        "",
    ]
    for module, fields in fields_by_module().items():
        lines.extend([f"## {module}", ""])
        current_category = ""
        for field in fields:
            if field.category != current_category:
                current_category = field.category
                lines.extend([f"### {current_category}", ""])
            lines.extend(
                [
                    f"#### {field.field}",
                    "",
                    f"- 框架说明：{field.description}",
                    "- 已核验事实：待补充。",
                    "- 判断：待补充。",
                    "- 施耐德机会：待补充。",
                    "- 来源/证据：待补充。",
                    "",
                ]
            )
    lines.extend(
        [
            "## 10. 施耐德业务机会地图",
            "",
            "| 优先级 | 机会主题 | 目标部门/角色 | 触发事件 | 推荐方案 | 下一步动作 |",
            "| --- | --- | --- | --- | --- | --- |",
            "| P1 | 待补充 | 待补充 | 待补充 | 待补充 | 待补充 |",
            "",
            "## 11. 访谈提纲与内部数据需求",
            "",
            "- 销售侧：合作年限、采购额、竞品比例、项目漏斗、客户满意度。",
            "- 技术侧：授权柜型、图纸标准、元器件偏好、数字化设计和调试痛点。",
            "- 服务侧：交付周期、质量投诉、备件响应、售后纠纷。",
            "- 信用侧：付款周期、逾期、授信、合同履约。",
            "",
            "## 12. 来源附录",
            "",
            "| 来源编号 | 来源名称 | 发布方 | 日期 | 链接 | 使用位置 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    return "\n".join(lines) + "\n"


def write_customer_project(customer_name: str, out_dir: str | Path, report_year: int | None = None) -> list[Path]:
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        output_dir / "00_source_plan.md",
        output_dir / "01_field_register.csv",
        output_dir / "02_research_prompt.md",
        output_dir / "03_report_template.md",
    ]
    outputs[0].write_text(render_source_plan(customer_name), encoding="utf-8")
    write_field_register(outputs[1])
    outputs[2].write_text(render_research_prompt(customer_name, report_year), encoding="utf-8")
    outputs[3].write_text(render_report_template(customer_name, report_year), encoding="utf-8")
    return outputs


def render_framework_summary() -> str:
    return "\n".join(f"- {name}" for name in module_names())
