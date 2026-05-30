"""Shared research blueprint for city industry reports."""

from __future__ import annotations

from dataclasses import dataclass


ELECTRICAL_SEGMENTS = [
    "保-商业楼宇",
    "保-公共建筑",
    "保-住宅",
    "保-PSB",
    "保-OEM",
    "保-地铁",
    "增-医院",
    "增-数据中心及通讯",
    "增-电子",
    "增-航空航天",
    "增-水务及环保公用事业",
    "增-化工(非石化)",
    "增-石油天然气",
    "增-新能源",
    "拓-铁路",
    "拓-M&M(矿业与建材)",
    "拓-冶金",
    "拓-生命科学",
    "拓-路桥隧道",
    "拓-船舶制造",
    "拓-汽车(含新能源汽车)",
    "拓-食品饮料（含烟酒）",
    "拓-智慧照明",
    "其他-港口",
    "其他-核电",
    "其他-火电",
    "其他-水电",
    "其他-造纸",
    "其他-Other",
]


SEGMENT_KEYWORDS: dict[str, list[str]] = {
    "增-数据中心及通讯": ["数据中心", "算力", "通信", "通讯", "5G", "IDC", "云计算", "服务器"],
    "增-电子": ["电子", "半导体", "集成电路", "显示", "面板", "芯片", "PCB", "传感器"],
    "增-航空航天": ["航空", "航天", "卫星", "无人机", "飞行器", "发动机"],
    "增-水务及环保公用事业": ["水务", "污水", "环保", "固废", "垃圾焚烧", "供水", "排水"],
    "增-化工(非石化)": ["化工", "新材料", "精细化工", "农药", "涂料", "树脂"],
    "增-石油天然气": ["石油", "天然气", "LNG", "炼化", "油气", "石化"],
    "增-新能源": ["新能源", "光伏", "风电", "储能", "氢能", "锂电", "电池", "充电桩"],
    "拓-铁路": ["铁路", "轨道交通", "高铁", "动车", "列车"],
    "拓-M&M(矿业与建材)": ["矿业", "矿山", "建材", "水泥", "玻璃", "砂石", "陶瓷"],
    "拓-冶金": ["钢铁", "冶金", "有色", "铝", "铜", "稀土", "金属"],
    "拓-生命科学": ["医药", "生物", "医疗器械", "疫苗", "制药", "生命科学"],
    "拓-路桥隧道": ["路桥", "隧道", "高速公路", "市政工程", "桥梁"],
    "拓-船舶制造": ["船舶", "海工", "造船", "舰船", "港机"],
    "拓-汽车(含新能源汽车)": ["汽车", "新能源汽车", "整车", "零部件", "智能网联", "电驱"],
    "拓-食品饮料（含烟酒）": ["食品", "饮料", "白酒", "啤酒", "烟草", "乳制品", "粮油"],
    "拓-智慧照明": ["照明", "灯具", "LED", "智慧路灯"],
    "保-商业楼宇": ["商业综合体", "写字楼", "办公楼", "酒店", "商场"],
    "保-公共建筑": ["学校", "机关", "公共建筑", "文化馆", "体育馆", "会展"],
    "保-住宅": ["住宅", "房地产", "社区", "物业"],
    "保-PSB": ["公安", "消防", "应急", "监狱", "司法", "公共安全"],
    "保-OEM": ["装备制造", "OEM", "机械", "电气设备", "自动化设备", "成套设备"],
    "保-地铁": ["地铁", "城市轨道", "轨交"],
    "其他-港口": ["港口", "码头", "航运", "集装箱"],
    "其他-核电": ["核电", "核能"],
    "其他-火电": ["火电", "燃煤发电", "燃气发电"],
    "其他-水电": ["水电", "水力发电"],
    "其他-造纸": ["造纸", "纸浆", "纸业"],
}


@dataclass(frozen=True)
class TableSpec:
    filename: str
    title: str
    columns: tuple[str, ...]


BASE_ENTERPRISE_COLUMNS = (
    "排名",
    "产业名称",
    "企业名称",
    "企业地址",
    "所属城市区县",
    "所属行业",
    "企业主营业务",
    "企业主要产品及品牌",
    "企业最新发展重点或者动态",
    "与电气领域的结合点",
    "排名/规模口径",
    "数据来源",
)


TABLE_SPECS = [
    TableSpec(
        filename="pillar_enterprises_top10.csv",
        title="支柱产业按规模排名前十企业",
        columns=BASE_ENTERPRISE_COLUMNS + ("上年营业收入",),
    ),
    TableSpec(
        filename="emerging_enterprises_top10.csv",
        title="新兴产业按企业规模排名前十企业",
        columns=BASE_ENTERPRISE_COLUMNS + ("2025年营业收入",),
    ),
    TableSpec(
        filename="listed_companies_top10.csv",
        title="上市公司市值排名前十",
        columns=BASE_ENTERPRISE_COLUMNS + ("证券代码", "上市地点", "市值", "市值日期"),
    ),
    TableSpec(
        filename="foreign_invested_enterprises_top10.csv",
        title="外商投资企业排名前十",
        columns=BASE_ENTERPRISE_COLUMNS + ("投资方/国家或地区", "注册资本或投资额"),
    ),
    TableSpec(
        filename="local_top20_enterprises.csv",
        title="纳税百强/百强企业榜单前二十",
        columns=BASE_ENTERPRISE_COLUMNS + ("榜单名称", "榜单发布机构", "榜单排名标准"),
    ),
]


SOURCE_TAG_REQUIREMENTS = {
    "government_work_report": "近3年市政府工作报告或年度重点任务",
    "statistics_bulletin": "近3年统计公报/统计年鉴/工业经济运行数据",
    "industry_plan": "市级或区县级产业规划、产业链行动方案、先进制造业集群方案",
    "development_reform": "发改委重大项目、产业投资、未来产业布局",
    "industry_it": "工信局/工业和信息化部门产业链、规上工业、专精特新资料",
    "commerce_fdi": "商务局外资、外贸、招商、开发区开放型经济资料",
    "tax_or_top_list": "税务局、工商联、企业联合会或官方媒体发布的纳税/百强榜单",
    "listed_company": "交易所、巨潮资讯、上市公司年报或官方公告",
    "official_media": "市级官方媒体、政府发布微信公众号、部门微信公众号",
    "dual_carbon": "双碳、节能降耗、绿色工厂、零碳园区、能耗强度资料",
    "digital_transformation": "数字化转型、智能工厂、工业互联网、算力基础设施资料",
    "talent_policy": "人才政策、高校院所、创新平台、产教融合资料",
}


INDUSTRY_CHAPTERS = [
    "第一章：产业规模",
    "第二章：产业现状",
    "第三章：产业发展趋势",
    "第四章：产业支撑",
    "第五章：电气业务机会",
]


def classify_electrical_segment(*texts: str) -> str:
    """Classify a company into the user's electrical opportunity taxonomy."""

    haystack = " ".join(text for text in texts if text).lower()
    if not haystack.strip():
        return "其他-Other"

    best_segment = "其他-Other"
    best_score = 0
    for segment, keywords in SEGMENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.lower() in haystack)
        if score > best_score:
            best_segment = segment
            best_score = score

    return best_segment
