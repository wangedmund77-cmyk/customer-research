import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from switchgear_customer_insight.citations import link_markdown_citations, parse_source_registry
from switchgear_customer_insight.docx_writer import write_docx_from_markdown
from switchgear_customer_insight.framework import FRAMEWORK, module_names
from switchgear_customer_insight.report_writer import render_research_prompt, write_customer_project
from switchgear_customer_insight.webapp import (
    _attachment_header,
    _build_insight_dashboard,
    _framework_catalog,
    _is_chint_customer,
    _is_tianyu_customer,
    _is_zhonghuan_customer,
    CustomerProject,
)


class SwitchgearCustomerInsightTests(unittest.TestCase):
    def test_framework_matches_user_workbook_shape(self):
        self.assertEqual(len(module_names()), 9)
        self.assertGreaterEqual(len(FRAMEWORK), 100)
        self.assertIn("3. 供应链与采购模块", module_names())

    def test_framework_catalog_exposes_excel_fields(self):
        catalog = _framework_catalog()
        nested_fields = [
            field
            for module in catalog
            for category in module["categories"]
            for field in category["fields"]
        ]
        self.assertEqual(len(nested_fields), len(FRAMEWORK))
        self.assertEqual(catalog[0]["categories"][0]["name"], "企业基本信息")
        self.assertEqual(catalog[0]["categories"][0]["fields"][0]["field"], "企业名称")
        self.assertEqual(catalog[-1]["categories"][-1]["fields"][-1]["field"], "售后纠纷")

    def test_prompt_includes_internal_gap_rule(self):
        prompt = render_research_prompt("浙江正泰电器股份有限公司", 2026)
        self.assertIn("待内部补充/需访谈核验", prompt)
        self.assertIn("施耐德合作情况", prompt)

    def test_project_writer_outputs_expected_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = write_customer_project("浙江正泰电器股份有限公司", tmp, 2026)
            names = {Path(path).name for path in files}
            self.assertEqual(
                names,
                {
                    "00_source_plan.md",
                    "01_field_register.csv",
                    "02_research_prompt.md",
                    "03_report_template.md",
                },
            )
            self.assertTrue((Path(tmp) / "01_field_register.csv").exists())

    def test_chint_customer_detection(self):
        self.assertTrue(_is_chint_customer("浙江正泰电器股份有限公司"))
        self.assertTrue(_is_chint_customer("CHINT Electrics"))
        self.assertFalse(_is_chint_customer("某某成套设备有限公司"))

    def test_chint_pain_opportunities_include_panel_ka_playbook(self):
        project = CustomerProject(id="demo", customer="浙江正泰电器股份有限公司", year=2026)
        dashboard = _build_insight_dashboard(project)
        pain_rows = {row["field"]: row for section in dashboard["pain_opportunities"] for row in section["rows"]}
        summary = dashboard["competitor_summary"]

        self.assertIn("盘厂KA", pain_rows["市场竞争压力"]["pain"])
        self.assertIn("BlokSeT", pain_rows["质量管控痛点"]["schneider_advantage"])
        self.assertIn("Power Commission", pain_rows["生产效率痛点"]["schneider_advantage"])
        self.assertIn("Power Build", pain_rows["人才痛点"]["schneider_playbook"])
        self.assertIn("设计院/EPC", pain_rows["设计能力痛点"]["schneider_playbook"])
        self.assertIn("BOM冻结", pain_rows["供应链痛点"]["schneider_playbook"])
        self.assertIn("FAT/SAT", pain_rows["生产效率痛点"]["schneider_playbook"])
        self.assertIn("TCO", pain_rows["技术成本痛点"]["schneider_playbook"])
        self.assertEqual("施耐德盘厂KA经营链路", summary["chain_heading"])
        self.assertIn("盘厂KA", summary["title"])
        self.assertIn("项目入口", summary["substitution_chain"][1]["step"])
        self.assertIn("FAT/SAT", summary["substitution_chain"][4]["insight"])
        self.assertIn("SE5", pain_rows["质量管控痛点"]["source_ids"])
        self.assertIn("SE7", pain_rows["市场竞争压力"]["source_ids"])
        self.assertIn("KB1", pain_rows["人才痛点"]["source_ids"])

    def test_chint_supply_procurement_marks_competitor_purchase_boundary(self):
        project = CustomerProject(id="demo", customer="浙江正泰电器股份有限公司", year=2026)
        dashboard = _build_insight_dashboard(project)
        supply_rows = {row["field"]: row for section in dashboard["supply_procurement"] for row in section["rows"]}

        self.assertIn("未发现权威公开资料显示正泰电器本体批量采购", supply_rows["主要竞品品牌"]["value"])
        self.assertIn("未披露施耐德、ABB、西门子等竞品品牌采购比例", supply_rows["竞品采购比例"]["value"])
        self.assertIn("项目BOM口径测算", supply_rows["竞品采购比例"]["value"])
        self.assertIn("排除施耐德、ABB、西门子、伊顿", supply_rows["其他器件供应商"]["value"])
        self.assertIn("宏丰股份", supply_rows["其他器件供应商"]["value"])
        self.assertIn("S62", supply_rows["其他器件供应商"]["source_ids"])
        supplier_segments = supply_rows["其他器件供应商"]["supplier_segments"]
        self.assertGreaterEqual(len(supplier_segments), 7)
        supplier_segment_text = "\n".join(
            f'{row["segment"]} {row["public_evidence"]} {row["business_meaning"]} {row["se_implication"]}'
            for row in supplier_segments
        )
        self.assertIn("银点/电接触材料", supplier_segment_text)
        self.assertIn("采购云", supplier_segment_text)
        self.assertIn("柜体/钣金", supplier_segment_text)
        self.assertIn("POWGRID-S", supply_rows["柜体供应商"]["value"])
        self.assertIn("PZ30", supply_rows["柜体供应商"]["value"])
        self.assertIn("S64", supply_rows["柜体供应商"]["source_ids"])
        self.assertIn("S68", supply_rows["柜体供应商"]["source_ids"])
        cabinet_evidence_rows = supply_rows["柜体供应商"]["evidence_rows"]
        cabinet_evidence_text = "\n".join(
            f'{row["segment"]} {row["public_evidence"]} {row["judgement"]} {row["se_implication"]}'
            for row in cabinet_evidence_rows
        )
        self.assertIn("自有低压箱体/成套产品", cabinet_evidence_text)
        self.assertIn("盘厂伙伴生态", cabinet_evidence_text)
        self.assertIn("外协柜体/钣金/母排", cabinet_evidence_text)
        self.assertIn("泰乐购", supply_rows["供应链稳定性"]["value"])
        self.assertIn("区域销售总公司", supply_rows["供应链稳定性"]["value"])
        self.assertIn("S67", supply_rows["供应链稳定性"]["source_ids"])
        channel_evidence_rows = supply_rows["供应链稳定性"]["evidence_rows"]
        channel_evidence_text = "\n".join(
            f'{row["segment"]} {row["public_evidence"]} {row["judgement"]} {row["se_implication"]}'
            for row in channel_evidence_rows
        )
        self.assertIn("智慧物流/前置仓", channel_evidence_text)
        self.assertIn("采购云/供应商治理", channel_evidence_text)
        self.assertIn("可持续供应链准入", channel_evidence_text)
        self.assertIn("S55", supply_rows["主要竞品品牌"]["source_ids"])
        self.assertIn("S56", supply_rows["竞品使用原因"]["source_ids"])
        self.assertIn("S57", supply_rows["其他器件供应商"]["source_ids"])
        self.assertIn("S58", supply_rows["竞品优势感知"]["source_ids"])
        comparison_rows = supply_rows["竞品优势感知"]["comparison_rows"]
        self.assertGreaterEqual(len(comparison_rows), 7)
        comparison_text = "\n".join(
            f'{row["business_need"]} {row["schneider_solution"]} {row["competitor_solution"]} {row["schneider_gap"]}'
            for row in comparison_rows
        )
        self.assertIn("数据中心", comparison_text)
        self.assertIn("MasterPacT", comparison_text)
        self.assertIn("ABB", comparison_text)
        self.assertIn("SIVACON", comparison_text)
        self.assertIn("xEnergy", comparison_text)
        self.assertIn("SE9", comparison_rows[1]["source_ids"])
        self.assertIn("ABB1", comparison_rows[1]["source_ids"])

    def test_zhonghuan_customer_detection(self):
        self.assertTrue(_is_zhonghuan_customer("中环电气集团"))
        self.assertTrue(_is_zhonghuan_customer("江苏中环电气集团有限公司"))
        self.assertFalse(_is_zhonghuan_customer("TCL中环新能源科技股份有限公司"))

    def test_tianyu_customer_detection(self):
        self.assertTrue(_is_tianyu_customer("天宇电气股份有限公司"))
        self.assertTrue(_is_tianyu_customer("福州天宇电气股份有限公司"))
        self.assertTrue(_is_tianyu_customer("Tianyu Electric Co., Ltd."))
        self.assertFalse(_is_tianyu_customer("浙江天宇药业股份有限公司"))

    def test_markdown_report_can_be_written_as_docx(self):
        markdown = """# 测试企业深度企业洞察报告

## 0. 高层摘要

- 机会一：低压柜标准化。
- 机会二：智能配电。

| 字段 | 信息 |
| --- | --- |
| 企业名称 | 测试客户【ZH1】 |
"""
        registry = """# 来源登记

| 编号 | 来源 | 发布方/载体 | 日期 | 链接 | 主要用途 |
| --- | --- | --- | --- | --- | --- |
| ZH1 | 主体信息 | 测试来源 | 2026-05-26 | https://example.com/source | 基础信息 |
"""
        with tempfile.TemporaryDirectory() as tmp:
            docx_path = write_docx_from_markdown(markdown, Path(tmp) / "report.docx", source_registry_markdown=registry)
            self.assertTrue(docx_path.exists())
            with ZipFile(docx_path) as archive:
                names = set(archive.namelist())
                self.assertIn("word/document.xml", names)
                self.assertIn("word/header1.xml", names)
                self.assertIn("word/footer1.xml", names)
                self.assertIn("word/_rels/document.xml.rels", names)
                self.assertIn("word/numbering.xml", names)
                document_xml = archive.read("word/document.xml").decode("utf-8")
                self.assertIn("深度企业洞察报告", document_xml)
                self.assertIn('w:pStyle w:val="TocTitle"', document_xml)
                self.assertIn('w:pStyle w:val="Heading1"', document_xml)
                self.assertIn("<w:tbl>", document_xml)
                self.assertIn('<w:numId w:val="1"/>', document_xml)
                self.assertIn("<w:hyperlink", document_xml)
                relationships_xml = archive.read("word/_rels/document.xml.rels").decode("utf-8")
                self.assertIn("https://example.com/source", relationships_xml)
                self.assertIn('TargetMode="External"', relationships_xml)

    def test_source_registry_citations_can_be_linked_in_markdown(self):
        registry = """| 编号 | 来源 | 发布方/载体 | 日期 | 链接 | 主要用途 |
| --- | --- | --- | --- | --- | --- |
| ZH1 | 主体信息 | 测试来源 | 2026-05-26 | https://example.com/source | 基础信息 |
"""
        references = parse_source_registry(registry)
        linked = link_markdown_citations("依据【ZH1】和【ZH9】。", references)
        self.assertIn("[【ZH1】](https://example.com/source)", linked)
        self.assertIn("【ZH9】", linked)

    def test_chinese_attachment_header_has_ascii_fallback(self):
        header = _attachment_header("福州天宇电气股份有限公司_深度企业洞察报告.docx")
        self.assertIn("filename=download.docx", header)
        self.assertIn("filename*=UTF-8''", header)

    def test_dashboard_preserves_full_excel_framework(self):
        project = CustomerProject(id="demo", customer="江苏中环电气集团有限公司", year=2026)
        dashboard = _build_insight_dashboard(project)
        self.assertEqual(len(_framework_catalog()), 9)
        self.assertEqual(len(dashboard["framework_matrix"]), len(FRAMEWORK))
        self.assertEqual(len(dashboard["module_summary"]), 9)
        self.assertIn("portrait", dashboard)
        self.assertIn("headline", dashboard["portrait"])
        self.assertEqual(len(dashboard["basic_info"]), 9)
        self.assertEqual(
            [row["field"] for row in dashboard["basic_info"]],
            ["企业名称", "统一社会信用代码", "成立时间", "注册资本", "企业性质", "股权结构", "法人代表", "注册地址", "实际经营地址"],
        )
        self.assertEqual(len(dashboard["certifications"]), 7)
        self.assertEqual(
            [row["field"] for row in dashboard["certifications"]],
            ["低压成套设备生产资质", "高压成套设备资质", "ISO体系认证", "特种设备生产许可证", "电力承包施工资质", "承装修试资质", "施耐德授权等级"],
        )
        self.assertEqual(len(dashboard["scale_finance"]["enterprise_scale"]), 7)
        self.assertEqual(len(dashboard["scale_finance"]["financial_status"]), 4)
        self.assertEqual(
            [row["field"] for row in dashboard["scale_finance"]["enterprise_scale"]],
            ["员工总数", "技术人员数量", "生产人员数量", "销售人员数量", "厂房面积", "生产基地数量", "年产能"],
        )
        self.assertEqual(
            [row["field"] for row in dashboard["scale_finance"]["financial_status"]],
            ["年营业收入", "净利润", "资产负债率", "现金流状况"],
        )
        self.assertEqual(len(dashboard["business_capability"]), 4)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["business_capability"]), 19)
        self.assertEqual(
            [section["category"] for section in dashboard["business_capability"]],
            ["主营业务", "技术能力", "生产能力", "项目经验"],
        )
        business_fields = [row["field"] for section in dashboard["business_capability"] for row in section["rows"]]
        self.assertEqual(
            business_fields,
            [
                "主营产品类型",
                "产品线覆盖",
                "主营行业领域",
                "业务收入结构",
                "设计团队规模",
                "设计软件使用",
                "研发投入占比",
                "专利数量",
                "技术合作方",
                "生产设备水平",
                "质量控制体系",
                "生产周期",
                "准时交付率",
                "质量合格率",
                "代表性项目",
                "项目类型分布",
                "项目地域分布",
                "大型项目经验",
                "行业标杆客户",
            ],
        )
        self.assertEqual(len(dashboard["supply_procurement"]), 3)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["supply_procurement"]), 14)
        self.assertEqual(
            [section["category"] for section in dashboard["supply_procurement"]],
            ["施耐德合作情况", "竞品采购情况", "其他供应商"],
        )
        supply_procurement_fields = [row["field"] for section in dashboard["supply_procurement"] for row in section["rows"]]
        self.assertEqual(
            supply_procurement_fields,
            [
                "合作年限",
                "合作模式",
                "历史采购额",
                "采购增长率",
                "主要采购产品",
                "授权柜体型号",
                "合作满意度",
                "主要竞品品牌",
                "竞品采购比例",
                "竞品使用原因",
                "竞品优势感知",
                "其他器件供应商",
                "柜体供应商",
                "供应链稳定性",
            ],
        )
        self.assertEqual(len(dashboard["customer_resources"]), 2)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["customer_resources"]), 8)
        self.assertEqual(
            [section["category"] for section in dashboard["customer_resources"]],
            ["客户结构", "客户关系"],
        )
        resource_fields = [row["field"] for section in dashboard["customer_resources"] for row in section["rows"]]
        self.assertEqual(
            resource_fields,
            [
                "主要客户类型",
                "客户行业分布",
                "客户地域分布",
                "头部客户名单",
                "头部客户收入占比",
                "客户粘性",
                "客户获取方式",
                "客户满意度",
            ],
        )
        self.assertEqual(len(dashboard["sales_market"]), 3)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["sales_market"]), 11)
        self.assertEqual(
            [section["category"] for section in dashboard["sales_market"]],
            ["销售体系", "市场覆盖", "价格策略"],
        )
        sales_market_fields = [row["field"] for section in dashboard["sales_market"] for row in section["rows"]]
        self.assertEqual(
            sales_market_fields,
            [
                "销售团队规模",
                "销售模式",
                "销售区域划分",
                "销售渠道",
                "招投标能力",
                "覆盖省份",
                "重点市场",
                "市场定位",
                "品牌影响力",
                "价格水平",
                "价格敏感度",
            ],
        )
        self.assertEqual(len(dashboard["org_decision"]), 3)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["org_decision"]), 12)
        self.assertEqual(
            [section["category"] for section in dashboard["org_decision"]],
            ["组织架构", "关键决策人", "决策流程"],
        )
        org_decision_fields = [row["field"] for section in dashboard["org_decision"] for row in section["rows"]]
        self.assertEqual(
            org_decision_fields,
            [
                "公司组织架构图",
                "决策层级",
                "关键部门",
                "董事长/总经理",
                "采购负责人",
                "技术负责人",
                "生产负责人",
                "销售负责人",
                "采购决策流程",
                "技术选型流程",
                "决策周期",
                "决策影响因素",
            ],
        )
        self.assertEqual(len(dashboard["strategy_needs"]), 4)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["strategy_needs"]), 13)
        self.assertEqual(
            [section["category"] for section in dashboard["strategy_needs"]],
            ["战略方向", "数字化转型", "绿色低碳", "电气升级需求"],
        )
        strategy_needs_fields = [row["field"] for section in dashboard["strategy_needs"] for row in section["rows"]]
        self.assertEqual(
            strategy_needs_fields,
            [
                "短期目标",
                "中长期规划",
                "业务扩张计划",
                "区域扩张计划",
                "数字化现状",
                "数字化需求",
                "数字化预算",
                "双碳目标",
                "绿色产品需求",
                "ESG评级",
                "智能配电需求",
                "能效管理需求",
                "设备更新需求",
            ],
        )
        self.assertEqual(len(dashboard["pain_opportunities"]), 3)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["pain_opportunities"]), 10)
        self.assertEqual(
            [section["category"] for section in dashboard["pain_opportunities"]],
            ["业务痛点", "技术痛点", "市场痛点"],
        )
        pain_opportunity_fields = [row["field"] for section in dashboard["pain_opportunities"] for row in section["rows"]]
        self.assertEqual(
            pain_opportunity_fields,
            [
                "生产效率痛点",
                "质量管控痛点",
                "供应链痛点",
                "人才痛点",
                "设计能力痛点",
                "技术成本痛点",
                "技术人才痛点",
                "市场竞争压力",
                "客户需求变化",
                "行业政策变化",
            ],
        )
        self.assertTrue(all(row["opportunity"] for section in dashboard["pain_opportunities"] for row in section["rows"]))
        self.assertEqual(len(dashboard["risk_assessment"]), 2)
        self.assertEqual(sum(len(section["rows"]) for section in dashboard["risk_assessment"]), 6)
        self.assertEqual(
            [section["category"] for section in dashboard["risk_assessment"]],
            ["经营风险", "信用风险"],
        )
        risk_assessment_fields = [row["field"] for section in dashboard["risk_assessment"] for row in section["rows"]]
        self.assertEqual(
            risk_assessment_fields,
            [
                "财务风险",
                "法律风险",
                "经营稳定性",
                "付款信用",
                "合同履约",
                "售后纠纷",
            ],
        )
        fields = {row["field"] for row in dashboard["framework_matrix"]}
        self.assertIn("施耐德授权等级", fields)
        self.assertIn("付款信用", fields)
        summary = dashboard["competitor_summary"]
        self.assertEqual(summary["chain_heading"], "施耐德项目经营链路")
        self.assertIn("中环电气企业洞察摘要", summary["title"])
        self.assertIn("项目型重点盘厂客户", summary["one_sentence"])
        self.assertIn("Prisma E", summary["one_sentence"])
        self.assertIn("MVnex", summary["one_sentence"])
        self.assertIn("BlokSeT", summary["one_sentence"])
        self.assertIn("标准BOM", summary["module_takeaways"][7]["takeaway"])
        self.assertIn("ZH17", summary["module_takeaways"][6]["source_ids"])
        self.assertIn("ZH16", summary["substitution_chain"][0]["source_ids"])

        scale_rows = {row["field"]: row for row in dashboard["scale_finance"]["enterprise_scale"]}
        self.assertIn("约280人", scale_rows["员工总数"]["value"])
        self.assertIn("数控多位高速转塔冲床", scale_rows["生产人员数量"]["value"])
        business_rows = {row["field"]: row for section in dashboard["business_capability"] for row in section["rows"]}
        self.assertIn("南京国博电子", business_rows["代表性项目"]["value"])
        self.assertIn("数控电液式剪板机", business_rows["生产设备水平"]["value"])
        strategy_rows = {row["field"]: row for section in dashboard["strategy_needs"] for row in section["rows"]}
        self.assertIn("省三星级上云企业", strategy_rows["数字化现状"]["value"])
        pain_rows = {row["field"]: row for section in dashboard["pain_opportunities"] for row in section["rows"]}
        self.assertIn("项目类型模板", pain_rows["生产效率痛点"]["opportunity"])
        self.assertIn("FAT/SAT", pain_rows["质量管控痛点"]["opportunity"])

    def test_shenghong_dashboard_uses_switchgear_ka_summary(self):
        project = CustomerProject(id="demo", customer="江苏东方盛虹股份有限公司 / 东方盛虹", year=2026)
        dashboard = _build_insight_dashboard(project)
        summary = dashboard["competitor_summary"]
        self.assertEqual(summary["chain_heading"], "施耐德机会链路")
        self.assertIn("企业洞察摘要", summary["title"])
        self.assertNotIn("method_note", summary)
        self.assertIn("14.32亿元", summary["one_sentence"])
        self.assertIn("SH7", summary["substitution_chain"][0]["source_ids"])
        self.assertIn("SH9", summary["module_takeaways"][1]["source_ids"])
        self.assertIn("盛虹流程工业智能大模型平台", dashboard["strategy_needs"][1]["rows"][0]["value"])
        self.assertIn("SH4", summary["substitution_chain"][2]["source_ids"])
        pain_rows = {row["field"]: row for section in dashboard["pain_opportunities"] for row in section["rows"]}
        self.assertIn("营业收入1,255.87亿元", pain_rows["生产效率痛点"]["pain"])
        self.assertIn("扣非净利润-5.43亿元", pain_rows["生产效率痛点"]["pain"])
        self.assertIn("2026年一季度净利润和经营现金流显著修复", pain_rows["生产效率痛点"]["pain"])
        self.assertIn("1600万吨/年炼油", pain_rows["质量管控痛点"]["pain"])
        self.assertIn("425万立方仓储", pain_rows["质量管控痛点"]["pain"])
        self.assertIn("DCS、OTS", pain_rows["供应链痛点"]["pain"])
        self.assertIn("设备故障", pain_rows["人才痛点"]["pain"])
        self.assertIn("SH6", pain_rows["质量管控痛点"]["source_ids"])
        self.assertIn("EcoStruxure Power and Process", pain_rows["生产效率痛点"]["schneider_advantage"])
        self.assertIn("TCO", pain_rows["生产效率痛点"]["schneider_playbook"])
        self.assertIn("BlokSeT", pain_rows["质量管控痛点"]["schneider_advantage"])
        self.assertIn("FAT/SAT", pain_rows["质量管控痛点"]["schneider_playbook"])
        self.assertIn("四方BOM冻结会", pain_rows["供应链痛点"]["schneider_playbook"])
        self.assertIn("SE5", pain_rows["质量管控痛点"]["source_ids"])
        self.assertIn("SE7", pain_rows["人才痛点"]["source_ids"])
        self.assertEqual(len(dashboard["framework_matrix"]), len(FRAMEWORK))


if __name__ == "__main__":
    unittest.main()
