import unittest

from city_industry_research.blueprint import TABLE_SPECS, classify_electrical_segment
from city_industry_research.source_discovery import build_search_queries


class BlueprintTests(unittest.TestCase):
    def test_queries_cover_tax_and_wechat_style_official_sources(self):
        queries = build_search_queries("无锡市", "江苏省", 2026)
        text = "\n".join(query.query for query in queries)
        sources = "\n".join(" ".join(query.preferred_sources) for query in queries)
        self.assertIn("纳税百强", text)
        self.assertIn("官方媒体", sources)
        self.assertIn("官方微信公众号", sources)

    def test_table_specs_include_required_business_columns(self):
        all_columns = {column for spec in TABLE_SPECS for column in spec.columns}
        self.assertIn("企业名称", all_columns)
        self.assertIn("与电气领域的结合点", all_columns)
        self.assertIn("数据来源", all_columns)
        self.assertIn("市值", all_columns)

    def test_electrical_segment_classifier(self):
        self.assertEqual(
            classify_electrical_segment("新能源整车", "智能网联汽车零部件"),
            "拓-汽车(含新能源汽车)",
        )
        self.assertEqual(
            classify_electrical_segment("云计算数据中心", "服务器和通信网络"),
            "增-数据中心及通讯",
        )
        self.assertEqual(classify_electrical_segment("未知业务"), "其他-Other")


if __name__ == "__main__":
    unittest.main()
