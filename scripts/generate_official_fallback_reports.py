"""Generate official-source fallback reports for Xinjiang county-level cities.

This is used when ChatGPT Deep Research is unavailable, stuck, or only available
at a broader prefecture/region scope. It does not pretend to be a Deep Research
export; each report states its evidence limits and keeps unsupported enterprise
rankings marked as pending verification.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import argparse
import csv
import json
import re
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from city_industry_research.official_discovery import (  # noqa: E402
    SearchHit,
    build_evidence_from_discovered_sources,
    discover_official_sources,
)


DEFAULT_OUT_DIR = ROOT / "outputs" / f"xinjiang_county_cities_{date.today().strftime('%Y%m%d')}"


@dataclass(frozen=True)
class City:
    index: int
    name: str
    prefecture: str
    governance_note: str


CITIES: tuple[City, ...] = (
    City(1, "石河子市", "新疆生产建设兵团第八师", "兵团师市合一县级市，请区分石河子市、第八师、兵团及自治区口径。"),
    City(2, "阿拉尔市", "新疆生产建设兵团第一师", "兵团师市合一县级市，请区分阿拉尔市、第一师、兵团及自治区口径。"),
    City(3, "图木舒克市", "新疆生产建设兵团第三师", "兵团师市合一县级市，请区分图木舒克市、第三师、兵团及自治区口径。"),
    City(4, "五家渠市", "新疆生产建设兵团第六师", "兵团师市合一县级市，请区分五家渠市、第六师、兵团及自治区口径。"),
    City(5, "北屯市", "新疆生产建设兵团第十师", "兵团师市合一县级市，请区分北屯市、第十师、兵团及自治区口径。"),
    City(6, "铁门关市", "新疆生产建设兵团第二师", "兵团师市合一县级市，请区分铁门关市、第二师、兵团及自治区口径。"),
    City(7, "双河市", "新疆生产建设兵团第五师", "兵团师市合一县级市，请区分双河市、第五师、兵团及自治区口径。"),
    City(8, "可克达拉市", "新疆生产建设兵团第四师", "兵团师市合一县级市，请区分可克达拉市、第四师、兵团及自治区口径。"),
    City(9, "昆玉市", "新疆生产建设兵团第十四师", "兵团师市合一县级市，请区分昆玉市、第十四师、兵团及自治区口径。"),
    City(10, "胡杨河市", "新疆生产建设兵团第七师", "兵团师市合一县级市，请区分胡杨河市、第七师、兵团及自治区口径。"),
    City(11, "新星市", "新疆生产建设兵团第十三师", "兵团师市合一县级市，请区分新星市、第十三师、兵团及自治区口径。"),
    City(12, "白杨市", "新疆生产建设兵团第九师", "兵团师市合一县级市，请区分白杨市、第九师、兵团及自治区口径。"),
    City(13, "昌吉市", "昌吉回族自治州", "自治州下辖县级市，请区分昌吉市本级、昌吉州、昌吉国家高新区/准东等园区口径。"),
    City(14, "阜康市", "昌吉回族自治州", "自治州下辖县级市，请区分阜康市本级、昌吉州、准东及天池景区等口径。"),
    City(15, "博乐市", "博尔塔拉蒙古自治州", "自治州首府县级市，请区分博乐市本级、博州及阿拉山口综保区口径。"),
    City(16, "阿拉山口市", "博尔塔拉蒙古自治州", "口岸型县级市，请区分阿拉山口市、博州、综合保税区及口岸数据口径。"),
    City(17, "库尔勒市", "巴音郭楞蒙古自治州", "自治州首府县级市，请区分库尔勒市本级、巴州、库尔勒经开区和上库高新区口径。"),
    City(18, "阿克苏市", "阿克苏地区", "地区行署驻地县级市，请区分阿克苏市本级、阿克苏地区及阿克苏纺织工业城等园区口径。"),
    City(19, "库车市", "阿克苏地区", "县级市，请区分库车市本级、阿克苏地区、库车经开区及油气化工园区口径。"),
    City(20, "阿图什市", "克孜勒苏柯尔克孜自治州", "自治州首府县级市，请区分阿图什市本级、克州及边境口岸口径。"),
    City(21, "喀什市", "喀什地区", "地区行署驻地县级市，请区分喀什市本级、喀什地区、喀什经济开发区及综保区口径。"),
    City(22, "和田市", "和田地区", "地区行署驻地县级市，请区分和田市本级、和田地区及和田产业园区口径。"),
    City(23, "伊宁市", "伊犁哈萨克自治州", "自治州首府县级市，请区分伊宁市本级、伊犁州直及霍尔果斯经开区口径。"),
    City(24, "奎屯市", "伊犁哈萨克自治州", "县级市，请区分奎屯市、伊犁州直、奎独乌区域及兵地融合口径。"),
    City(25, "霍尔果斯市", "伊犁哈萨克自治州", "口岸型县级市，请区分霍尔果斯市、霍尔果斯经开区、综保区和中哈合作中心口径。"),
    City(26, "塔城市", "塔城地区", "地区行署驻地县级市，请区分塔城市本级、塔城地区和巴克图口岸口径。"),
    City(27, "乌苏市", "塔城地区", "县级市，请区分乌苏市本级、塔城地区、乌苏工业园区及奎独乌区域口径。"),
    City(28, "沙湾市", "塔城地区", "县级市，请区分沙湾市本级、塔城地区及沙湾工业园区口径。"),
    City(29, "阿勒泰市", "阿勒泰地区", "地区行署驻地县级市，请区分阿勒泰市本级、阿勒泰地区、冰雪旅游及边境口岸相关口径。"),
)


INDUSTRY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "现代农业与农产品加工": ("农业", "棉花", "红枣", "葡萄", "番茄", "粮", "果", "畜牧", "肉牛", "乳", "食品", "农产品", "加工"),
    "纺织服装与轻工制造": ("纺织", "棉纺", "服装", "织布", "针织", "鞋", "轻工", "箱包", "印染"),
    "能源电力与煤电油气化工": ("煤", "煤电", "电力", "火电", "石油", "天然气", "油气", "化工", "煤化工", "石化", "页岩油"),
    "矿业与建材": ("矿", "矿产", "水泥", "建材", "砂石", "石灰石", "铁", "铜", "铅锌", "钒钛", "陶瓷"),
    "商贸物流与口岸经济": ("口岸", "综保", "保税", "外贸", "进出口", "跨境", "物流", "铁路", "陆港", "班列", "互市", "商贸"),
    "文化旅游与现代服务": ("旅游", "文旅", "景区", "冰雪", "天池", "消费", "服务业", "酒店", "夜间经济", "康养"),
    "装备制造与新型工业": ("装备", "制造业", "机械", "智能制造", "汽车", "零部件", "无人机", "农机", "机电"),
    "新能源与新型电力系统": ("新能源", "光伏", "风电", "储能", "氢能", "绿电", "零碳", "源网荷储", "充电"),
    "新材料": ("新材料", "硅基", "碳基", "锂", "铝基", "钒钛", "高性能", "复合材料", "电子材料"),
    "数字经济与算力": ("数字经济", "算力", "智算", "数据中心", "5G", "云计算", "智慧", "软件", "电商"),
    "生物医药与生命健康": ("生物", "医药", "药", "中药", "微藻", "医疗", "生命", "健康", "制药"),
    "节能环保与水务": ("环保", "污水", "水务", "节能", "固废", "循环经济", "绿色园区", "再生"),
}


EMERGING_INDUSTRIES = {
    "新能源与新型电力系统",
    "新材料",
    "数字经济与算力",
    "生物医药与生命健康",
    "节能环保与水务",
}


ELECTRICAL_SEGMENT_BY_INDUSTRY = {
    "现代农业与农产品加工": "拓-食品饮料（含烟酒）",
    "纺织服装与轻工制造": "保-OEM",
    "能源电力与煤电油气化工": "增-石油天然气",
    "矿业与建材": "拓-M&M(矿业与建材)",
    "商贸物流与口岸经济": "拓-铁路",
    "文化旅游与现代服务": "保-商业楼宇",
    "装备制造与新型工业": "保-OEM",
    "新能源与新型电力系统": "增-新能源",
    "新材料": "增-化工(非石化)",
    "数字经济与算力": "增-数据中心及通讯",
    "生物医药与生命健康": "拓-生命科学",
    "节能环保与水务": "增-水务及环保公用事业",
}


COMPANY_PATTERN = re.compile(
    r"(?:(?:新疆|兵团|中国|中交|中建|中铁|中石油|中石化|国能|华电|华能|天富|天业|大全|合盛|特变|金风|西部|天康|冠农|青松|梅花|新赛|伊力特|汇嘉|新农|新天|中泰|天润|广汇|昌源|海螺|昆仑|新希望)[\u4e00-\u9fa5A-Za-z0-9（）()·-]{0,30}|[\u4e00-\u9fa5A-Za-z0-9（）()·-]{2,40})"
    r"(?:集团有限公司|集团股份有限公司|股份有限公司|有限责任公司|有限公司|公司|集团|厂|合作社|农场)"
)


ORG_NOISE = (
    "人民政府",
    "政府",
    "委员会",
    "管理局",
    "办公室",
    "厅",
    "局",
    "法院",
    "检察",
    "学校",
    "医院",
    "协会",
    "日报",
    "网",
)

COMPANY_NAME_NOISE = (
    "我们公司",
    "为了推进公司",
    "推进公司",
    "公司治理",
    "公司债",
    "工业生产者出厂",
    "绿色工厂",
    "智能工厂",
    "示范工厂",
    "数字工厂",
    "灯塔工厂",
)

COMPANY_NOISE_PREFIXES = (
    "我们",
    "为了",
    "推进",
    "通过",
    "加快",
    "支持",
    "鼓励",
    "培育",
    "认定",
    "建设",
    "打造",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--city", action="append", help="Only process selected city name; can be repeated.")
    parser.add_argument("--all", action="store_true", help="Process every city, including those with exact Deep Research reports.")
    parser.add_argument("--query-limit", type=int, default=14)
    parser.add_argument("--results-per-query", type=int, default=6)
    parser.add_argument("--max-sources", type=int, default=36)
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    status_path = out_dir / "deep_research_status.csv"
    rows, fieldnames = read_status(status_path)
    selected_names = set(args.city or [])

    for city in CITIES:
        row = next((item for item in rows if item["序号"] == str(city.index)), None)
        if row is None:
            continue
        if selected_names and city.name not in selected_names:
            continue
        if not args.all and not should_generate_fallback(row):
            continue
        print(f"[{city.index:02d}/29] {city.name}: discovering official sources...", flush=True)
        city_dir = out_dir / "artifacts" / "official_fallback" / f"{city.index:02d}_{city.name}"
        city_dir.mkdir(parents=True, exist_ok=True)
        report_path = out_dir / "reports" / f"{city.index:02d}_{city.name}_官方来源补充画像报告.md"

        hits = discover_official_sources(
            city=city.name,
            province="新疆",
            report_year=2026,
            query_limit=args.query_limit,
            results_per_query=args.results_per_query,
            max_sources=args.max_sources,
            sleep_seconds=0.1,
        )
        (city_dir / "discovered_sources.json").write_text(
            json.dumps(
                {
                    "city": city.name,
                    "source_count": len(hits),
                    "sources": [hit.__dict__ for hit in hits],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if args.skip_fetch:
            evidence = evidence_from_hits(city, hits)
        else:
            evidence = build_evidence_from_discovered_sources(
                city=city.name,
                province="新疆",
                report_year=2026,
                hits=hits,
                max_excerpt_chars=4200,
                fetch_timeout_seconds=12,
                max_workers=6,
            )
        (city_dir / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        report_path.write_text(build_report(city, row, evidence), encoding="utf-8")
        row["报告文件"] = merge_report_path(row.get("报告文件", ""), report_path)
        row["Deep Research状态"] = update_fallback_status(row.get("Deep Research状态", ""))
        row["备注"] = merge_note(
            row.get("备注", ""),
            f"已生成官方来源补充报告；检索保留{len(hits)}条权威候选来源，证据文件见 {city_dir / 'evidence.json'}。",
        )
        write_status(status_path, rows, fieldnames)
        print(f"[{city.index:02d}/29] {city.name}: wrote {report_path}", flush=True)


def should_generate_fallback(row: dict[str, str]) -> bool:
    status = row.get("Deep Research状态", "")
    report = row.get("报告文件", "")
    if "官方来源补充报告已生成" in status and "官方来源补充" in report:
        return False
    if not report:
        return True
    if "需" in status and "复核" in status:
        return True
    if "失败" in status or "待重试" in status:
        return True
    return False


def read_status(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader), list(reader.fieldnames or [])


def write_status(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def evidence_from_hits(city: City, hits: list[SearchHit]) -> dict:
    return {
        "city": city.name,
        "province": "新疆",
        "report_year": 2026,
        "sources": [
            {
                "id": f"S{index:03d}",
                "title": hit.title,
                "url": hit.url,
                "publisher": "",
                "published_date": "",
                "source_type": "official_candidate",
                "credibility": "official_candidate",
                "tags": [],
                "excerpt": hit.snippet,
                "notes": f"检索式：{hit.query}",
            }
            for index, hit in enumerate(hits, start=1)
        ],
    }


def build_report(city: City, status_row: dict[str, str], evidence: dict) -> str:
    sources = evidence.get("sources", [])
    analysis = analyze_sources(city, sources)
    pillar = analysis["pillar"]
    emerging = analysis["emerging"]
    companies = analysis["companies"]
    key_sources = sources[:12]

    lines: list[str] = []
    lines.append(f"# 新疆{city.name}支柱产业与新兴产业“双轮驱动”官方来源补充画像报告")
    lines.append("")
    lines.append("> 说明：本文件是 ChatGPT Deep Research 新建任务失败、卡住或仅获得上级地区口径时的官方来源补充稿；它不伪装为 Deep Research 导出。所有判断均基于本次抓取到的政府网站、兵团/师市官网、官方媒体、官方微信和权威公开渠道候选来源；企业排名、2025营收、市值、外资和纳税榜如无官方披露，一律标为“未披露/待核验”。")
    lines.append("")
    lines.append("## 0. 研究摘要")
    lines.append("")
    lines.append(f"- 研究对象：{city.name}；上级/兵团口径：{city.prefecture}。{city.governance_note}")
    lines.append(f"- Deep Research登记状态：{status_row.get('Deep Research状态', '未登记')}。")
    lines.append(f"- 本次官方来源检索保留来源：{len(sources)}条；其中可读取正文摘录的来源：{sum(1 for s in sources if s.get('excerpt'))}条。")
    lines.append(f"- 支柱产业识别：{join_names(pillar)}。")
    lines.append(f"- 新兴产业识别：{join_names(emerging)}。")
    lines.append("- 电气业务优先机会：园区供配电、工业电机与自动化、能效管理、储能与新能源接入、冷链/物流/口岸智能化、污水环保与公共建筑运维。")
    lines.append("- 数据缺口：县级市本级GDP排名、工业用电量、企业2025营收、纳税百强、上市公司市值和外资排名经常没有统一公开口径，需以后续政府榜单或企业年报核验。")
    lines.append("")

    lines.append("## 第一章 城市画像")
    lines.append("")
    lines.append(f"{city.name}的城市画像需要放在“本级城市+{city.prefecture}+园区/口岸/兵团师市”三层口径中审慎理解。官方材料中高频出现的产业关键词显示，本地产业基础集中在{join_names(pillar)}，增量培育方向集中在{join_names(emerging)}。")
    lines.append("")
    lines.append("### 城市特点与政策事件")
    lines.append("")
    lines.extend(bullets_from_sources(key_sources[:5]))
    lines.append("")
    lines.append("### 经济指标与投资热点")
    lines.append("")
    lines.append("本补充稿只列出本次官方来源可支持的指标线索；没有抓取到县级市本级统计公报或工作报告明细时，不使用上级地区数据硬替代。")
    lines.extend(metric_bullets(sources))
    lines.append("")
    lines.append("### 交通特点")
    lines.append("")
    lines.append(traffic_paragraph(city, sources))
    lines.append("")
    lines.append("### 过去三年重点投资行业及KA")
    lines.append("")
    lines.append(investment_paragraph(pillar, emerging, companies))
    lines.append("")
    lines.append("### 未来三年机会热点")
    lines.append("")
    lines.append(f"结合近三年政府工作报告、产业规划和官方新闻线索，{city.name}未来3年更值得跟踪的机会包括：{future_hotspots(pillar, emerging)}。这些方向与十五五建议中关于现代化产业体系、绿色低碳、数字化转型、现代基础设施和区域开放的导向一致。")
    lines.append("")

    lines.append("## 第二章 支柱产业画像")
    lines.append("")
    for industry in pillar:
        lines.extend(industry_section(industry, "支柱产业", analysis, sources, companies))
    lines.append("")

    lines.append("## 第三章 新兴产业画像")
    lines.append("")
    for industry in emerging:
        lines.extend(industry_section(industry, "新兴产业", analysis, sources, companies))
    lines.append("")

    lines.append("## 第四章 企业表格")
    lines.append("")
    lines.append("### 4.1 支柱产业按规模摸排前十企业")
    lines.append("")
    lines.extend(company_table(companies, pillar, 10, include_revenue=True))
    lines.append("")
    lines.append("### 4.2 新兴产业按企业规模摸排前十企业")
    lines.append("")
    lines.extend(company_table(companies, emerging, 10, include_revenue=True))
    lines.append("")
    lines.append("### 4.3 上市公司排名前十")
    lines.append("")
    lines.extend(listed_table(city, sources))
    lines.append("")
    lines.append("### 4.4 外商投资企业排名前十")
    lines.append("")
    lines.extend(fdi_table(city, sources))
    lines.append("")
    lines.append("### 4.5 纳税百强/同类榜单前二十")
    lines.append("")
    lines.append(f"本次检索未必能获得{city.name}本级“纳税百强”榜单。若来源清单中未出现税务局、工商联或政府发布的榜单文件，本表按“官方材料中反复出现的重点企业/重大项目/园区企业”作为代理线索，排名不等同于纳税排名。")
    lines.extend(tax_table(companies, 20))
    lines.append("")

    lines.append("## 第五章 来源附录")
    lines.append("")
    lines.extend(source_appendix(sources))
    lines.append("")
    return "\n".join(lines)


def analyze_sources(city: City, sources: list[dict]) -> dict:
    industry_scores: Counter[str] = Counter()
    evidence_by_industry: dict[str, list[str]] = defaultdict(list)
    for source in sources:
        text = source_text(source)
        for industry, keywords in INDUSTRY_KEYWORDS.items():
            score = sum(text.count(keyword) for keyword in keywords)
            if score:
                industry_scores[industry] += score
                evidence_by_industry[industry].append(source.get("id", ""))

    sorted_industries = [name for name, _ in industry_scores.most_common()]
    pillar = [name for name in sorted_industries if name not in EMERGING_INDUSTRIES][:5]
    emerging = [name for name in sorted_industries if name in EMERGING_INDUSTRIES][:5]
    if not pillar:
        pillar = ["现代农业与农产品加工", "商贸物流与口岸经济", "文化旅游与现代服务"]
    if not emerging:
        emerging = ["新能源与新型电力系统", "数字经济与算力", "节能环保与水务"]
    companies = extract_companies(sources, pillar + emerging)
    return {
        "scores": industry_scores,
        "evidence": evidence_by_industry,
        "pillar": pillar,
        "emerging": emerging,
        "companies": companies,
    }


def extract_companies(sources: list[dict], industries: list[str]) -> list[dict]:
    records: dict[str, dict] = {}
    for source in sources:
        text = source_text(source)
        for match in COMPANY_PATTERN.finditer(text):
            name = clean_company_name(match.group(0))
            if not is_company_name(name):
                continue
            start = max(match.start() - 90, 0)
            end = min(match.end() + 140, len(text))
            context = text[start:end]
            industry = infer_industry(context, industries)
            item = records.setdefault(
                name,
                {
                    "name": name,
                    "industry": industry,
                    "source_ids": set(),
                    "contexts": [],
                    "score": 0,
                },
            )
            item["source_ids"].add(source.get("id", ""))
            item["contexts"].append(clean_space(context)[:240])
            item["score"] += 1 + len(source.get("excerpt", "")) // 1200
            if item["industry"] not in industries:
                item["industry"] = industry
    out = []
    for item in records.values():
        item["source_ids"] = sorted(item["source_ids"])
        item["contexts"] = item["contexts"][:2]
        out.append(item)
    return sorted(out, key=lambda row: (row["score"], len(row["source_ids"])), reverse=True)


def infer_industry(text: str, industries: Iterable[str]) -> str:
    scores = {}
    for industry in industries:
        scores[industry] = sum(text.count(keyword) for keyword in INDUSTRY_KEYWORDS.get(industry, ()))
    best, score = max(scores.items(), key=lambda item: item[1], default=("其他", 0))
    return best if score else "其他"


def clean_company_name(name: str) -> str:
    name = clean_space(name)
    name = re.sub(r"^[，。、；：:（）()《》“”\"'0-9一二三四五六七八九十]+", "", name)
    return name.strip("，。、；：:（）()《》“”\"'")


def is_company_name(name: str) -> bool:
    if len(name) < 4 or len(name) > 60:
        return False
    if any(noise in name for noise in ORG_NOISE):
        return False
    if any(noise == name or noise in name for noise in COMPANY_NAME_NOISE):
        return False
    if any(name.startswith(prefix) for prefix in COMPANY_NOISE_PREFIXES):
        return False
    if name.endswith("厂") and not any(keyword in name for keyword in ("有限", "公司", "集团", "新疆", "水泥", "纺织", "化工", "材料", "食品", "矿", "煤", "电")):
        return False
    return any(suffix in name for suffix in ("公司", "集团", "厂", "合作社", "农场"))


def industry_section(industry: str, kind: str, analysis: dict, sources: list[dict], companies: list[dict]) -> list[str]:
    source_ids = sorted(set(analysis["evidence"].get(industry, [])))[:8]
    related = [company for company in companies if company["industry"] == industry][:6]
    segment = ELECTRICAL_SEGMENT_BY_INDUSTRY.get(industry, "其他-Other")
    lines = [
        f"### {industry}",
        "",
        f"#### 1. 产业规模",
        "",
        f"本次官方来源检索中，“{industry}”相关线索出现强度为 {analysis['scores'].get(industry, 0)}。可引用来源包括：{', '.join(source_ids) if source_ids else '待核验'}。企业线索包括：{', '.join(item['name'] for item in related) if related else '未检出足够企业线索'}。",
        "",
        "#### 2. 产业现状",
        "",
        f"从技术和市场两个层面看，该{kind}的可证据支持点主要来自政府工作报告、产业规划、园区新闻或官方媒体报道。现阶段不宜在缺少全国/全球市场占有率官方数据时给出硬排名；后续应补充行业协会、上市公司年报和主管部门统计。",
        "",
        "#### 3. 产业发展趋势",
        "",
        f"未来3-5年，该产业的重点更可能落在项目落地、园区承载、绿色低碳改造、数字化运营和区域市场外联。若{industry}涉及外贸、能源或新材料，还应持续跟踪十五五期间现代化产业体系、绿色低碳技术和高水平开放政策。 ",
        "",
        "#### 4. 产业支撑",
        "",
        f"核心支撑来自政策规划、园区载体、招商项目、交通通道、援疆/兵团资源和本地劳动力供给。当前证据来源：{', '.join(source_ids) if source_ids else '待补充官方来源'}。",
        "",
        "#### 5. 电气业务机会",
        "",
        f"电气领域分类建议为“{segment}”。机会场景包括：新建/扩建项目供配电、低压/中压配电柜、变频与电机系统、能效监测、智能照明、储能接入、光伏/风电消纳、环保水务电控、园区综合能源管理和预测性运维。",
        "",
    ]
    return lines


def bullets_from_sources(sources: list[dict]) -> list[str]:
    if not sources:
        return ["- 待补充官方来源。"]
    bullets = []
    for source in sources:
        excerpt = first_sentence(source.get("excerpt", "") or source.get("notes", ""))
        bullets.append(f"- {source.get('id')}: {source.get('title', '未命名来源')}。{excerpt}")
    return bullets


def metric_bullets(sources: list[dict]) -> list[str]:
    metric_keywords = ("GDP", "生产总值", "增长", "规上", "固定资产", "投资", "用电", "进出口", "财政", "工业")
    bullets = []
    for source in sources:
        text = source.get("excerpt", "")
        if any(keyword in text for keyword in metric_keywords):
            bullets.append(f"- {source.get('id')}: {source.get('title')}。{first_sentence(text)}")
        if len(bullets) >= 8:
            break
    return bullets or ["- 未在本轮自动抓取摘录中识别出可直接引用的本级经济指标，需补充统计公报、政府工作报告或统计局数据。"]


def traffic_paragraph(city: City, sources: list[dict]) -> str:
    text = "\n".join(source_text(source) for source in sources)
    keys = [word for word in ("铁路", "高速", "公路", "机场", "口岸", "物流", "综保区", "陆港", "班列") if word in text]
    if keys:
        return f"本次来源中出现的交通关键词包括：{', '.join(keys)}。这说明{city.name}的产业机会需要结合交通通道和园区物流组织来判断，尤其是重载运输、农产品冷链、口岸外贸和工业品外运。"
    return f"本轮来源未充分抓取到{city.name}本级交通数据，建议补充交通运输局、发改委重大项目、口岸/园区官网和政府工作报告。"


def investment_paragraph(pillar: list[str], emerging: list[str], companies: list[dict]) -> str:
    names = [company["name"] for company in companies[:8]]
    return f"投资主线可按“成熟支柱产业稳产扩能+新兴产业项目导入”理解：支柱侧为{join_names(pillar)}，新兴侧为{join_names(emerging)}。本轮检索识别的KA/项目企业线索包括：{', '.join(names) if names else '未检出足够企业线索'}。"


def future_hotspots(pillar: list[str], emerging: list[str]) -> str:
    hotspots = []
    for industry in pillar[:3] + emerging[:4]:
        if industry == "现代农业与农产品加工":
            hotspots.append("特色农产品精深加工、冷链仓储和品牌化外销")
        elif industry == "商贸物流与口岸经济":
            hotspots.append("口岸物流、跨境电商、保税加工和国际通道服务")
        elif industry == "能源电力与煤电油气化工":
            hotspots.append("煤电油气化工延链、节能降碳和安全生产自动化")
        elif industry == "矿业与建材":
            hotspots.append("绿色矿山、建材智能产线和大宗物流电气化")
        elif industry == "文化旅游与现代服务":
            hotspots.append("景区提升、公共建筑智慧运维和夜间消费场景")
        elif industry == "新能源与新型电力系统":
            hotspots.append("风光储、源网荷储和园区综合能源")
        elif industry == "数字经济与算力":
            hotspots.append("算力中心、政企数字化和智慧园区")
        elif industry == "新材料":
            hotspots.append("新材料中试放大、绿色制造和高耗能设备能效管理")
        elif industry == "生物医药与生命健康":
            hotspots.append("生物制造、特色药食同源产品和洁净厂房")
        elif industry == "节能环保与水务":
            hotspots.append("污水处理、固废资源化和环保公用事业自动化")
    return "；".join(dict.fromkeys(hotspots))


def company_table(companies: list[dict], industries: list[str], limit: int, include_revenue: bool) -> list[str]:
    headers = [
        "产业名称",
        "排名",
        "企业名称",
        "企业地址",
        "所属城市区县",
        "所属行业",
        "企业主营业务",
        "企业主要产品及品牌",
        "企业最新发展重点或者动态",
        "与电气领域的结合点",
        "2025年营业收入",
        "排名/规模口径",
        "数据来源",
    ]
    rows = [headers, ["---"] * len(headers)]
    filtered = [company for company in companies if company["industry"] in industries][:limit]
    if not filtered:
        rows.append(["待核验", "1", "未披露/待核验", "未披露/待核验", "待核验", "其他-Other", "未披露/待核验", "未披露/待核验", "未披露/待核验", "待核验", "未披露/待核验", "本轮官方来源未检出足够企业", "来源附录"])
    for rank, company in enumerate(filtered, start=1):
        rows.append(
            [
                company["industry"],
                str(rank),
                company["name"],
                "未披露/待核验",
                "待核验",
                ELECTRICAL_SEGMENT_BY_INDUSTRY.get(company["industry"], "其他-Other"),
                infer_business(company["industry"]),
                infer_products(company["industry"]),
                company["contexts"][0] if company["contexts"] else "官方材料提及，需补充动态",
                electrical_opportunity(company["industry"]),
                "未披露/待核验" if include_revenue else "",
                "按本轮官方来源出现频次和重点项目语境排序，非正式规模排名",
                ", ".join(company["source_ids"]),
            ]
        )
    return markdown_table(rows)


def listed_table(city: City, sources: list[dict]) -> list[str]:
    headers = ["排名", "企业名称", "企业地址", "所属城市区县", "所属行业", "企业主营业务", "企业主要产品及品牌", "企业最新发展重点或者动态", "与电气领域的结合点", "市值", "市值日期", "证券代码", "上市地点", "数据来源"]
    rows = [headers, ["---"] * len(headers)]
    listed_sources = [s for s in sources if any(k in source_text(s) for k in ("上市", "证券", "年报", "股份有限公司", "交易所", "公告"))]
    rows.append(["1", "未披露/待核验", "未披露/待核验", city.name, "其他-Other", "未披露/待核验", "未披露/待核验", "本轮未获得可确认注册地在该县级市本级的上市公司前十榜单", "待核验", "未披露/待核验", "未披露/待核验", "未披露/待核验", "未披露/待核验", ", ".join(s.get("id", "") for s in listed_sources[:5]) or "来源附录"])
    return markdown_table(rows)


def fdi_table(city: City, sources: list[dict]) -> list[str]:
    headers = ["排名", "企业名称", "企业地址", "所属城市区县", "所属行业", "企业主营业务", "企业主要产品及品牌", "企业最新发展重点或者动态", "与电气领域的结合点", "投资方/国家或地区", "注册资本或投资额", "排名口径", "数据来源"]
    rows = [headers, ["---"] * len(headers)]
    fdi_sources = [s for s in sources if any(k in source_text(s) for k in ("外资", "外商", "港澳台", "投资方", "商务"))]
    rows.append(["1", "未披露/待核验", "未披露/待核验", city.name, "其他-Other", "未披露/待核验", "未披露/待核验", "本轮未获得县级市本级外商投资企业前十官方榜单", "待核验", "未披露/待核验", "未披露/待核验", "官方榜单缺口", ", ".join(s.get("id", "") for s in fdi_sources[:5]) or "来源附录"])
    return markdown_table(rows)


def tax_table(companies: list[dict], limit: int) -> list[str]:
    headers = ["排名", "企业名称", "企业地址", "所属城市区县", "所属行业", "企业主营业务", "企业主要产品及品牌", "企业最新发展重点或者动态", "与电气领域的结合点", "榜单名称", "榜单发布机构", "榜单排名标准", "数据来源"]
    rows = [headers, ["---"] * len(headers)]
    if not companies:
        rows.append(["1", "未披露/待核验", "未披露/待核验", "待核验", "其他-Other", "未披露/待核验", "未披露/待核验", "未披露/待核验", "待核验", "未检出本级纳税百强榜", "待核验", "待核验", "来源附录"])
    for rank, company in enumerate(companies[:limit], start=1):
        industry = company["industry"]
        rows.append(
            [
                str(rank),
                company["name"],
                "未披露/待核验",
                "待核验",
                ELECTRICAL_SEGMENT_BY_INDUSTRY.get(industry, "其他-Other"),
                infer_business(industry),
                infer_products(industry),
                company["contexts"][0] if company["contexts"] else "官方材料提及",
                electrical_opportunity(industry),
                "未检出本级纳税百强榜，按官方材料出现频次代理",
                "待核验",
                "非纳税排名；仅为重点企业线索排序",
                ", ".join(company["source_ids"]),
            ]
        )
    return markdown_table(rows)


def source_appendix(sources: list[dict]) -> list[str]:
    if not sources:
        return ["- 暂无来源。"]
    lines = []
    for source in sources:
        excerpt = clean_space(source.get("excerpt", ""))[:280]
        lines.append(f"- {source.get('id')}: {source.get('title')}；发布方/域名：{source.get('publisher')}; 链接：{source.get('url')}；摘录：{excerpt or source.get('notes', '')}")
    return lines


def infer_business(industry: str) -> str:
    return {
        "现代农业与农产品加工": "特色种养殖、农产品加工、冷链仓储",
        "纺织服装与轻工制造": "棉纺、织造、服装及轻工生产",
        "能源电力与煤电油气化工": "能源开发、发电、油气化工及配套服务",
        "矿业与建材": "矿产开发、水泥建材、砂石骨料",
        "商贸物流与口岸经济": "口岸贸易、仓储物流、跨境电商",
        "文化旅游与现代服务": "景区运营、文旅消费、住宿餐饮",
        "装备制造与新型工业": "装备制造、机械加工、零部件",
        "新能源与新型电力系统": "风光储、综合能源和电力配套",
        "新材料": "新材料生产、深加工和中试放大",
        "数字经济与算力": "数据中心、软件服务和智慧应用",
        "生物医药与生命健康": "生物制造、药品健康产品",
        "节能环保与水务": "污水处理、固废资源化、环保设施运营",
    }.get(industry, "未披露/待核验")


def infer_products(industry: str) -> str:
    return {
        "现代农业与农产品加工": "棉花、果蔬、粮油、乳肉制品、预制/休闲食品",
        "纺织服装与轻工制造": "纱线、坯布、服装、轻工产品",
        "能源电力与煤电油气化工": "电力、煤炭、油气、化工品",
        "矿业与建材": "矿产品、水泥、商砼、建材制品",
        "商贸物流与口岸经济": "仓储、通关、运输、保税加工服务",
        "文化旅游与现代服务": "景区、酒店、演艺、商业消费服务",
        "装备制造与新型工业": "机械装备、零部件、机电产品",
        "新能源与新型电力系统": "风电、光伏、储能、充电设施",
        "新材料": "硅基/铝基/钒钛/复合材料等",
        "数字经济与算力": "算力、云服务、智慧城市/园区应用",
        "生物医药与生命健康": "药品、保健品、生物制造产品",
        "节能环保与水务": "污水处理、环保运维、资源化产品",
    }.get(industry, "未披露/待核验")


def electrical_opportunity(industry: str) -> str:
    return {
        "现代农业与农产品加工": "冷链供配电、分拣包装自动化、泵站与温室能效",
        "纺织服装与轻工制造": "纺机电控、空压站节能、车间配电与能耗监测",
        "能源电力与煤电油气化工": "防爆电气、DCS/PLC、变配电、余热与能效管理",
        "矿业与建材": "破碎筛分电控、矿山变频、窑磨系统和除尘配电",
        "商贸物流与口岸经济": "仓储自动化、冷链、道闸安防、充电与岸电类设施",
        "文化旅游与现代服务": "商业楼宇配电、智慧照明、景区充电与运维",
        "装备制造与新型工业": "产线自动化、机器人/机床配电、测试台和MES能耗",
        "新能源与新型电力系统": "箱变、逆变升压、储能PCS、EMS和源网荷储",
        "新材料": "高耗能装备配电、洁净/恒温系统、节能改造",
        "数字经济与算力": "数据中心供配电、UPS、液冷/空调、电力监控",
        "生物医药与生命健康": "洁净厂房配电、工艺自控、冷链和质量追溯",
        "节能环保与水务": "泵站变频、污水厂自控、在线监测、配电运维",
    }.get(industry, "待核验")


def markdown_table(rows: list[list[str]]) -> list[str]:
    return ["| " + " | ".join(escape_cell(cell) for cell in row) + " |" for row in rows]


def escape_cell(value: str) -> str:
    return clean_space(str(value)).replace("|", "\\|")


def first_sentence(text: str) -> str:
    text = clean_space(text)
    if not text:
        return "摘录为空，需打开来源核验。"
    parts = re.split(r"[。！？\n]", text)
    return (parts[0] + "。")[:220]


def source_text(source: dict) -> str:
    return f"{source.get('title', '')}\n{source.get('excerpt', '')}\n{source.get('notes', '')}"


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def join_names(names: Iterable[str]) -> str:
    items = list(names)
    return "、".join(items) if items else "待核验"


def merge_report_path(existing: str, new_path: Path) -> str:
    new_text = str(new_path)
    if not existing:
        return new_text
    parts = [part.strip() for part in existing.split(";") if part.strip()]
    if new_text not in parts:
        parts.append(new_text)
    return ";".join(parts)


def update_fallback_status(existing: str) -> str:
    if "官方来源补充报告已生成" in existing:
        return existing
    return f"{existing}；官方来源补充报告已生成" if existing else "官方来源补充报告已生成"


def merge_note(existing: str, note: str) -> str:
    if note in existing:
        return existing
    return f"{existing} {note}".strip()


if __name__ == "__main__":
    main()
