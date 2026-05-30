"""Report and prompt rendering."""

from __future__ import annotations

from datetime import date
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from .blueprint import ELECTRICAL_SEGMENTS, INDUSTRY_CHAPTERS, TABLE_SPECS
from .schemas import EvidenceCorpus
from .source_discovery import validate_evidence


def _industry_names(items: list[dict]) -> list[str]:
    return [str(item.get("name") or "").strip() for item in items if str(item.get("name") or "").strip()]


def render_report_template(city: str, province: str = "", report_year: int = 2026, corpus: EvidenceCorpus | None = None) -> str:
    corpus = corpus or EvidenceCorpus(city=city, province=province, report_year=report_year)
    pillar_names = _industry_names(corpus.pillar_industries) or ["待官方证据确认的支柱产业"]
    emerging_names = _industry_names(corpus.emerging_industries) or ["待官方证据确认的新兴产业"]
    validation_issues = validate_evidence(corpus)

    lines = [
        f"# {province}{city}支柱产业与新兴产业“双轮驱动”画像报告",
        "",
        f"- 报告年度：{report_year}",
        f"- 生成日期：{date.today().isoformat()}",
        "- 研究口径：仅以政府官网、官方媒体、官方微信公众号、交易所/公司官方披露等权威来源作为结论依据。",
        "- 引用方式：报告中的关键结论应以来源编号标注，如 `【S001】`。",
        "",
        "## 证据完整性状态",
        "",
    ]
    if validation_issues:
        lines.extend(f"- {issue}" for issue in validation_issues)
    else:
        lines.append("- 证据库已覆盖核心来源类别，可进入正式撰写。")

    lines.extend(
        [
            "",
            "## 摘要",
            "",
            "从“成熟支柱产业稳盘 + 新兴产业育新”的双轮驱动角度，概括城市产业结构、产业链完整度、技术与市场竞争力、未来3-5年方向、电气业务机会。",
            "",
            "## 第一部分：支柱产业画像",
            "",
        ]
    )
    for industry in pillar_names:
        lines.extend(_render_industry_section(industry, "支柱产业"))

    lines.extend(["", "## 第二部分：新兴产业画像", ""])
    for industry in emerging_names:
        lines.extend(_render_industry_section(industry, "新兴产业"))

    lines.extend(
        [
            "",
            "## 第三部分：企业榜单与电气业务机会表",
            "",
        ]
    )
    for spec in TABLE_SPECS:
        lines.extend(
            [
                f"### {spec.title}",
                "",
                _markdown_table_header(spec.columns),
                "",
            ]
        )

    lines.extend(
        [
            "## 第四部分：纳税百强或同类榜单核验",
            "",
            "说明是否存在纳税百强、百强企业、制造业百强、民营企业百强、亩均效益领跑者等官方榜单；如存在，写明发布机构、排名标准、年份和可替代性；如不存在，列出已检索官方渠道及证据缺口。",
            "",
            "## 第五部分：来源附录",
            "",
            corpus.source_appendix_markdown(),
        ]
    )
    return "\n".join(lines) + "\n"


def _render_industry_section(industry: str, kind: str) -> list[str]:
    lines = [f"### {industry}", ""]
    chapter_prompts = {
        "第一章：产业规模": "写明产业规模、核心定位、相关行业、头部企业，所有数字标注年份和来源。",
        "第二章：产业现状": "从技术突破、市场表现、上下游协同、跨行业协同、产业链完整性展开；全国/全球地位和市场占有率必须给出具体数据或标记来源缺口。",
        "第三章：产业发展趋势": "结合近3年城市规划、2025年10月23日关于十五五规划建议的方向、双碳、数字化、本土根基和全球布局，预判未来3-5年重点。",
        "第四章：产业支撑": "从近3年政策、技术、人才、创新平台、园区载体、资金项目等维度说明核心支撑。",
        "第五章：电气业务机会": "按供配电、智能配电、自动化、能效管理、储能、充电基础设施、绿色园区、运维服务等维度提出机会，并绑定企业/项目场景。",
    }
    for chapter in INDUSTRY_CHAPTERS:
        lines.extend([f"#### {chapter}", "", chapter_prompts[chapter], ""])
    if kind == "新兴产业":
        lines.extend(["#### 新兴产业培育动能", "", "补充产业成熟度、政策牵引、资本投入、场景开放、龙头/链主企业和风险约束。", ""])
    return lines


def _markdown_table_header(columns: tuple[str, ...]) -> str:
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    empty = "| " + " | ".join("" for _ in columns) + " |"
    return "\n".join([header, divider, empty])


def build_llm_prompt(city: str, province: str = "", report_year: int = 2026, corpus: EvidenceCorpus | None = None) -> str:
    corpus = corpus or EvidenceCorpus(city=city, province=province, report_year=report_year)
    source_blocks = corpus.prompt_sources()
    validation_issues = validate_evidence(corpus)
    electrical_segments = "、".join(ELECTRICAL_SEGMENTS)
    table_schema = "\n".join(
        f"- {spec.title}（{spec.filename}）：{ '、'.join(spec.columns) }" for spec in TABLE_SPECS
    )

    return f"""你是一名顶级城市产业研究员、电气业务战略顾问和严谨事实核查员。请基于下方证据库，为“{province}{city}”撰写地级市支柱产业与新兴产业“双轮驱动”深度研究报告。

硬性规则：
1. 只能使用证据库中的政府官网、官方媒体、官方微信公众号、交易所/公司官方披露等权威来源；不得编造数据。
2. 每一个关键判断、数字、企业排名、市场占有率、政策表述，都必须使用 `【Sxxx】` 标注来源。
3. 若证据不足，明确写“待核验/来源缺口”，并说明缺少哪类官方来源。
4. 先识别所有支柱产业，再识别所有新兴产业；同义产业要合并，合并理由写清楚。
5. 报告要比常规 Deep Research 更严谨：产业、企业、政策、项目、技术、市场、上下游、电气机会之间要形成证据链。
6. 上年营业收入默认指 {report_year - 1} 年；如只能取得更早年度，必须注明。
7. 上市公司市值必须注明统计日期；外商投资企业必须注明外资口径或项目口径。
8. 电气领域分类只能从以下枚举中选择：{electrical_segments}。

报告结构：
# {province}{city}支柱产业与新兴产业“双轮驱动”画像报告

## 0. 研究摘要
- 双轮驱动总体判断
- 支柱产业清单及规模
- 新兴产业清单及培育动能
- 电气业务优先机会
- 数据缺口与核验建议

## 1. 支柱产业画像
对每一个支柱产业分别写：
### 产业名称
#### 第一章：产业规模
包含产业规模、核心定位、相关行业、重点行业头部企业。
#### 第二章：产业现状
从技术突破与市场表现拆解竞争力；分析上下游和跨行业协同；说明重点行业在全国及全球地位、市场占有率，并给出具体数据。
#### 第三章：产业发展趋势
结合近3年城市规划和2025年10月23日关于十五五规划建议的方向，预判未来3-5年发展重点；覆盖双碳、数字化、本土根基、全球布局、国际竞争力、区域融合度。
#### 第四章：产业支撑
从近3年政策、技术、人才、创新平台、园区、重大项目维度解析。
#### 第五章：电气业务机会
写出可落地的业务机会、目标客户类型、触发项目、产品/解决方案、进入路径。

## 2. 新兴产业画像
对每一个新兴产业重复上述五章，并额外说明产业成熟度、场景牵引、政策资金、龙头企业和风险。

## 3. 企业表格
请输出以下 Markdown 表格，列完整字段，不要省略列：
{table_schema}

## 4. 纳税百强/同类榜单说明
说明该地级市是否有纳税百强或类似排名；参考什么标准排名；若没有，说明已核验渠道和替代榜单。

## 5. 来源附录
按来源编号列出标题、发布方、日期、链接、使用位置。

当前证据完整性提醒：
{json.dumps(validation_issues, ensure_ascii=False, indent=2)}

证据库：
{source_blocks}

企业线索：
{json.dumps(corpus.enterprise_records, ensure_ascii=False, indent=2)}

已知假设：
{json.dumps(corpus.assumptions, ensure_ascii=False, indent=2)}
"""


def write_table_templates(out_dir: str | Path) -> None:
    table_dir = Path(out_dir)
    table_dir.mkdir(parents=True, exist_ok=True)
    for spec in TABLE_SPECS:
        path = table_dir / spec.filename
        path.write_text(",".join(spec.columns) + "\n", encoding="utf-8")


def build_autonomous_web_research_prompt(city: str, province: str = "", report_year: int = 2026) -> str:
    """Build a web-search-enabled prompt for city-name-only research."""

    electrical_segments = "、".join(ELECTRICAL_SEGMENTS)
    table_schema = "\n".join(
        f"- {spec.title}（{spec.filename}）：{ '、'.join(spec.columns) }" for spec in TABLE_SPECS
    )
    return f"""你是一名顶级城市产业研究员、电气业务战略顾问和严谨事实核查员。请对“{province}{city}”执行联网深度研究，并生成地级市支柱产业与新兴产业“双轮驱动”画像报告。

研究硬性规则：
1. 必须优先搜索并引用地级市政府官网、统计局、发改委、工信局、商务局、税务局、科技局、生态环境局、人社局、市场监管局、国资委、区县政府/开发区官网、市级官方媒体、政府发布微信公众号、部门微信公众号。
2. 对上市公司、市值、营业收入、境外布局，可补充交易所、巨潮资讯、上市公司年报、公司官网等官方披露。
3. 非官方数据库只能用于发现线索，不能单独支撑结论。
4. 每一个关键判断、产业清单、数字、企业排名、市场占有率、政策表述，都必须标注来源链接、发布方和发布日期。
5. 找不到权威来源时，明确写“待核验/来源缺口”，并说明已尝试核验的官方渠道。
6. 上年营业收入默认指 {report_year - 1} 年；如只能取得更早年度，必须注明。
7. 上市公司市值必须注明统计日期；外商投资企业必须注明外资口径或项目口径。
8. 电气领域分类只能从以下枚举中选择：{electrical_segments}。
9. 研究需要覆盖近3年城市规划，并结合2025年10月23日中共中央关于制定国民经济和社会发展第十五个五年规划的建议，判断未来3-5年产业方向。

检索策略：
- 先确认该地级市官方表述中的全部支柱产业、重点产业链、新兴产业、未来产业，避免漏项。
- 每个产业至少交叉核验“政府规划/政策 + 统计数据 + 官方新闻/企业公告”三类材料。
- 对产业规模、全国/全球地位、市场占有率、头部企业、上下游协同、双碳、数字化、人才政策、重大项目、电气业务机会分别建立证据链。
- 对企业榜单优先查纳税百强、工业百强、民营企业百强、制造业百强、亩均效益领跑者、开发区重点企业榜单；写明排名标准。

报告结构：
# {province}{city}支柱产业与新兴产业“双轮驱动”画像报告

## 0. 研究摘要
- 双轮驱动总体判断
- 支柱产业清单及规模
- 新兴产业清单及培育动能
- 电气业务优先机会
- 数据缺口与核验建议

## 1. 支柱产业画像
先列出全部支柱产业清单和认定依据。对每一个支柱产业分别写：
### 产业名称
#### 第一章：产业规模
包含产业规模、核心定位、相关行业、重点行业头部企业。
#### 第二章：产业现状
从技术突破与市场表现拆解竞争力；分析上下游和跨行业协同；说明重点行业在全国及全球地位、市场占有率，并给出具体数据。
#### 第三章：产业发展趋势
结合近3年城市规划和2025年10月23日关于十五五规划建议的方向，预判未来3-5年发展重点；覆盖双碳、数字化、本土根基、全球布局、国际竞争力、区域融合度。
#### 第四章：产业支撑
从近3年政策、技术、人才、创新平台、园区、重大项目维度解析。
#### 第五章：电气业务机会
写出可落地的业务机会、目标客户类型、触发项目、产品/解决方案、进入路径。

## 2. 新兴产业画像
先列出全部新兴产业清单和认定依据。对每一个新兴产业重复上述五章，并额外说明产业成熟度、场景牵引、政策资金、龙头企业和风险。

## 3. 企业表格
请输出以下 Markdown 表格，列完整字段，不要省略列：
{table_schema}

## 4. 纳税百强/同类榜单说明
说明该地级市是否有纳税百强或类似排名；参考什么标准排名；若没有，说明已核验渠道和替代榜单。

## 5. 来源附录
按来源编号列出标题、发布方、日期、链接、使用位置。
"""


def generate_with_openai(
    prompt: str,
    model: str,
    timeout_seconds: int = 240,
    web_search: bool = False,
) -> str:
    """Generate a report through the OpenAI Responses API using stdlib HTTP."""

    text, _ = generate_with_openai_response(
        prompt=prompt,
        model=model,
        timeout_seconds=timeout_seconds,
        web_search=web_search,
    )
    return text


def generate_with_openai_response(
    prompt: str,
    model: str,
    timeout_seconds: int = 240,
    web_search: bool = False,
) -> tuple[str, dict]:
    """Generate a report and return both text and raw Responses API payload."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，无法调用模型生成报告。")
    if not model:
        raise RuntimeError("请通过 --model 或 OPENAI_MODEL 指定模型。")

    payload = {
        "model": model,
        "input": prompt,
    }
    if _supports_temperature(model):
        payload["temperature"] = 0.2
    if web_search:
        payload["tools"] = [{"type": "web_search"}]
        payload["tool_choice"] = "auto"
        payload["include"] = ["web_search_call.action.sources"]
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API 调用失败：{exc.code} {detail}") from exc

    if data.get("output_text"):
        return str(data["output_text"]), data

    chunks: list[str] = []
    for item in data.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if text:
                chunks.append(text)
    if chunks:
        return "\n".join(chunks), data
    return json.dumps(data, ensure_ascii=False, indent=2), data


def extract_response_sources(response_payload: dict) -> list[dict[str, str]]:
    """Extract URL citations from a Responses API payload when available."""

    seen: set[str] = set()
    sources: list[dict[str, str]] = []
    for item in response_payload.get("output") or []:
        action = item.get("action") or {}
        for source in action.get("sources") or []:
            url = source.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            sources.append(
                {
                    "url": str(url),
                    "title": str(source.get("title") or ""),
                    "type": str(item.get("type") or "web_search_call"),
                }
            )
        for content in item.get("content") or []:
            for annotation in content.get("annotations") or []:
                url = annotation.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                sources.append(
                    {
                        "url": str(url),
                        "title": str(annotation.get("title") or ""),
                        "type": str(annotation.get("type") or ""),
                    }
                )
    return sources


def _supports_temperature(model: str) -> bool:
    normalized = model.lower().strip()
    return not normalized.startswith("gpt-5")
