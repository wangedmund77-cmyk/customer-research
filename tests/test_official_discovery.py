import unittest

from city_industry_research.official_discovery import normalize_result_url, score_authority_url
from city_industry_research.source_discovery import SearchQuery


class OfficialDiscoveryTests(unittest.TestCase):
    def test_normalize_duckduckgo_redirect(self):
        url = normalize_result_url("/l/?uddg=https%3A%2F%2Fwww.wuxi.gov.cn%2Fdoc%2Fabc.html")
        self.assertEqual(url, "https://www.wuxi.gov.cn/doc/abc.html")

    def test_score_prefers_government_sources(self):
        query = SearchQuery(
            category="产业规模与统计",
            purpose="",
            query="无锡市 统计公报",
            preferred_sources=(),
        )
        score = score_authority_url(
            "https://www.wuxi.gov.cn/doc/2026/01/01/abc.html",
            "无锡市统计公报",
            "规上工业 重点产业",
            "无锡市",
            query,
        )
        self.assertGreaterEqual(score, 8)

    def test_score_rejects_noise_domain(self):
        query = SearchQuery(category="企业榜单", purpose="", query="", preferred_sources=())
        score = score_authority_url("https://zhihu.com/question/1", "无锡产业", "", "无锡市", query)
        self.assertEqual(score, 0)

    def test_score_rejects_non_official_mirror(self):
        query = SearchQuery(category="城市产业识别", purpose="", query="", preferred_sources=())
        score = score_authority_url(
            "https://example.com/file.pdf",
            "无锡市人民政府办公室文件",
            "",
            "无锡市",
            query,
        )
        self.assertEqual(score, 0)


if __name__ == "__main__":
    unittest.main()
