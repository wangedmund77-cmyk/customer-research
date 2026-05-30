"""Authority-source discovery plan generation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import quote_plus

from .blueprint import SOURCE_TAG_REQUIREMENTS
from .schemas import EvidenceCorpus


@dataclass(frozen=True)
class SearchQuery:
    category: str
    purpose: str
    query: str
    preferred_sources: tuple[str, ...]

    def bing_url(self) -> str:
        return "https://www.bing.com/search?q=" + quote_plus(self.query)


def build_search_queries(city: str, province: str = "", report_year: int = 2026) -> list[SearchQuery]:
    """Build a broad official-source query set for one prefecture-level city."""

    place = f"{province} {city}".strip()
    recent_years = f"{report_year - 3}..{report_year}"
    official = ("市政府官网", "部门官网", "区县/园区官网", "官方媒体", "官方微信公众号")

    query_specs: list[tuple[str, str, list[str], tuple[str, ...]]] = [
        (
            "城市产业识别",
            "识别全部支柱产业、新兴产业、未来产业和重点产业链。",
            [
                f"{place} 支柱产业 新兴产业 政府",
                f"{place} 重点产业链 链主企业 政府",
                f"{place} 先进制造业集群 产业集群 政府",
                f"{place} 现代化产业体系 政府工作报告",
                f"{place} 十四五 产业发展规划 新兴产业 支柱产业",
            ],
            official,
        ),
        (
            "产业规模与统计",
            "获取规上工业、服务业、产业产值、增加值、营收、进出口等规模数据。",
            [
                f"{place} 统计公报 规上工业 产业 {recent_years}",
                f"{place} 统计年鉴 工业总产值 重点产业",
                f"{place} 工业经济运行 规上工业 营业收入 政府",
                f"{place} 产业规模 亿元 政府发布",
            ],
            ("统计局", "工信局", "发改委", "政府官网", "官方媒体"),
        ),
        (
            "技术突破与市场地位",
            "搜集全国/全球占有率、单项冠军、专精特新、标准、专利、重大技术突破。",
            [
                f"{place} 全国占有率 全球占有率 产业 政府",
                f"{place} 制造业单项冠军 专精特新 小巨人 产业链",
                f"{place} 技术突破 首台套 标准 产业 官方",
                f"{place} 重点企业 市场占有率 全球 官方",
            ],
            ("工信局", "科技局", "市场监管局", "政府发布", "企业官方公告"),
        ),
        (
            "上下游协同与生态",
            "梳理产业链完整性、园区承载、龙头企业与上下游配套。",
            [
                f"{place} 产业链 上下游 配套 企业 政府",
                f"{place} 链主企业 产业生态 园区",
                f"{place} 产业集群 图谱 重点企业 政府",
                f"{place} 开发区 产业链 招商图谱",
            ],
            ("发改委", "工信局", "开发区官网", "招商部门", "官方媒体"),
        ),
        (
            "近三年政策与规划",
            "获取城市规划、专项政策、产业行动方案、十五五衔接方向。",
            [
                f"{place} 2024 2025 2026 政府工作报告 产业",
                f"{place} 产业强市 行动方案 政府",
                f"{place} 十五五 产业 规划 编制 官方",
                f"{place} 新质生产力 产业 政府工作报告",
                f"{place} 中共中央 关于制定国民经济和社会发展第十五个五年规划 建议 产业 解读 官方",
            ],
            ("市政府官网", "发改委", "工信局", "新华社/人民日报等官方媒体"),
        ),
        (
            "双碳与数字化",
            "获取绿色工厂、零碳园区、节能改造、工业互联网、智能制造、算力等资料。",
            [
                f"{place} 双碳 绿色工厂 零碳园区 政府",
                f"{place} 节能降碳 工业领域 政府",
                f"{place} 数字化转型 智能工厂 工业互联网 政府",
                f"{place} 数据中心 算力 数字经济 规划 政府",
            ],
            ("发改委", "工信局", "生态环境局", "大数据局", "开发区官网"),
        ),
        (
            "人才与创新平台",
            "梳理高校院所、重点实验室、工程中心、人才政策、产教融合。",
            [
                f"{place} 人才政策 产业 创新平台 政府",
                f"{place} 重点实验室 工程技术研究中心 产业",
                f"{place} 产教融合 产业学院 官方",
                f"{place} 高校 院所 企业 技术创新 政府",
            ],
            ("科技局", "人社局", "教育局", "政府官网", "高校/院所官网"),
        ),
        (
            "企业榜单",
            "查找纳税百强、工业百强、民企百强、制造业百强等官方榜单及排名口径。",
            [
                f"{place} 纳税百强 企业 名单",
                f"{place} 百强企业 榜单 营收 纳税 官方",
                f"{place} 工业企业 前二十 排名 官方",
                f"{place} 民营企业百强 制造业百强 官方",
                f"{place} 亩均效益 领跑者 企业 官方",
            ],
            ("税务局", "工商联", "企业联合会", "工信局", "官方媒体"),
        ),
        (
            "上市公司与资本市场",
            "获取上市公司名单、市值口径、营收、年报、最新项目动态。",
            [
                f"{place} 上市公司 名单 市值",
                f"{place} A股 上市公司 年报 营业收入",
                f"{place} 上市后备企业 官方",
                f"{place} 上市公司 重大项目 投资 官方",
            ],
            ("交易所", "巨潮资讯", "证监局", "地方金融监管局", "公司官网"),
        ),
        (
            "外商投资企业",
            "识别外商投资企业、开放型经济龙头、重大外资项目。",
            [
                f"{place} 外商投资企业 十强 名单",
                f"{place} 重大外资项目 商务局",
                f"{place} 实际使用外资 重点企业 官方",
                f"{place} 开发区 外资企业 龙头",
            ],
            ("商务局", "开发区官网", "投资促进局", "官方媒体"),
        ),
        (
            "电气业务机会",
            "寻找供配电、自动化、能效管理、智能制造、储能、充电、绿色园区需求。",
            [
                f"{place} 工业企业 节能改造 配电 自动化",
                f"{place} 智能制造 数字化车间 电气 自动化",
                f"{place} 绿色工厂 能源管理 系统 官方",
                f"{place} 新能源 储能 充电桩 项目 政府",
                f"{place} 重大项目 供配电 变电站 园区",
            ],
            ("发改委", "工信局", "住建局", "供电公司官方渠道", "开发区官网"),
        ),
    ]

    queries: list[SearchQuery] = []
    for category, purpose, raw_queries, sources in query_specs:
        for raw_query in raw_queries:
            queries.append(
                SearchQuery(
                    category=category,
                    purpose=purpose,
                    query=raw_query,
                    preferred_sources=sources,
                )
            )
    return queries


def render_source_discovery_plan(city: str, province: str = "", report_year: int = 2026) -> str:
    queries = build_search_queries(city=city, province=province, report_year=report_year)
    lines = [
        f"# {province}{city}支柱产业与新兴产业研究：权威来源检索计划",
        "",
        "## 一、来源优先级",
        "",
        "1. 市政府官网、市统计局、市发改委、市工信局、市商务局、市税务局、市科技局、市生态环境局、市人社局、市市场监管局、市国资委。",
        "2. 区县政府官网、国家级/省级开发区、高新区、经开区、综合保税区、自贸片区等官方渠道。",
        "3. 市级官方媒体、政府发布微信公众号、部门微信公众号、园区微信公众号。",
        "4. 对上市公司、市值、营业收入、境外布局，可补充交易所、巨潮资讯、上市公司年报和企业官网等官方披露。",
        "5. 非官方数据库只能用于线索发现，不能单独作为报告结论来源。",
        "",
        "## 二、证据完整性清单",
        "",
        "| 标签 | 必须覆盖的材料 |",
        "|---|---|",
    ]
    for tag, description in SOURCE_TAG_REQUIREMENTS.items():
        lines.append(f"| `{tag}` | {description} |")

    lines.extend(
        [
            "",
            "## 三、检索式清单",
            "",
            "| 类别 | 目的 | 检索式 | 优先来源 | 搜索链接 |",
            "|---|---|---|---|---|",
        ]
    )
    for query in queries:
        lines.append(
            f"| {query.category} | {query.purpose} | `{query.query}` | "
            f"{'、'.join(query.preferred_sources)} | [Bing]({query.bing_url()}) |"
        )

    lines.extend(
        [
            "",
            "## 四、不可跳过的核验动作",
            "",
            "1. 同一产业至少交叉核验“规划/政策 + 统计数据 + 官方新闻/企业公告”三类材料。",
            "2. 对市场占有率、全球/全国排名、营业收入、市值、纳税排名等量化指标，记录来源、口径、年份和发布日期。",
            "3. 对企业地址、区县归属、主营业务、产品品牌，以企业官网、年报、政府招商资料、市场监管/园区资料交叉核验。",
            "4. 若未找到纳税百强或类似榜单，必须说明检索过哪些官方渠道，并列出可替代榜单及其排名标准。",
            "5. 所有无法确认的数据在报告中标记为“待核验”，不得用行业平均值或第三方传闻替代。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_evidence_template(city: str, province: str = "", report_year: int = 2026) -> dict:
    return {
        "city": city,
        "province": province,
        "report_year": report_year,
        "industry_inventory": {
            "pillar_industries": [
                {
                    "name": "",
                    "aliases": [],
                    "official_basis_source_ids": [],
                    "reason": "来自政府工作报告/产业规划/统计资料的支柱产业表述",
                }
            ],
            "emerging_industries": [
                {
                    "name": "",
                    "aliases": [],
                    "official_basis_source_ids": [],
                    "reason": "来自政府工作报告/产业规划/新兴产业行动方案的表述",
                }
            ],
        },
        "sources": [
            {
                "id": "S001",
                "title": "",
                "url": "",
                "publisher": "",
                "published_date": "",
                "source_type": "government_website / official_media / official_wechat / exchange_filing / company_annual_report",
                "credibility": "official",
                "tags": ["government_work_report"],
                "excerpt": "",
                "notes": "摘录必须保留原始数字、年份、排名口径和产业名称。",
            }
        ],
        "enterprise_records": [
            {
                "company_name": "",
                "industry_name": "",
                "company_type": "pillar_top10 / emerging_top10 / listed_top10 / foreign_invested_top10 / local_top20",
                "rank": "",
                "address": "",
                "district": "",
                "electrical_segment": "",
                "main_business": "",
                "products_and_brands": "",
                "latest_development": "",
                "electrical_opportunity": "",
                "revenue": "",
                "market_cap": "",
                "ranking_basis": "",
                "source_ids": [],
            }
        ],
        "assumptions": [
            "上年营业收入默认指报告年度的上一自然年；如官方披露滞后，需写明可得年份。",
            "上市公司市值必须标注统计日期。",
        ],
    }


def write_evidence_template(path: str | Path, city: str, province: str = "", report_year: int = 2026) -> None:
    data = build_evidence_template(city=city, province=province, report_year=report_year)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def validate_evidence(corpus: EvidenceCorpus) -> list[str]:
    tags = corpus.source_tags()
    missing = [
        f"缺少 `{tag}`：{description}"
        for tag, description in SOURCE_TAG_REQUIREMENTS.items()
        if tag not in tags
    ]
    if not corpus.pillar_industries:
        missing.append("缺少支柱产业清单：需要从官方规划/政府工作报告/统计资料确认。")
    if not corpus.emerging_industries:
        missing.append("缺少新兴产业清单：需要从官方规划/行动方案/官方报道确认。")
    if not corpus.enterprise_records:
        missing.append("缺少企业记录：无法生成前十/前二十企业榜单。")
    return missing
