import unittest

from city_industry_research.ingest import read_url_list


class IngestTests(unittest.TestCase):
    def test_read_url_list_skips_comments_and_blanks(self):
        urls = read_url_list(["", "# comment", "https://example.gov.cn/a.html  "])
        self.assertEqual(urls, ["https://example.gov.cn/a.html"])


if __name__ == "__main__":
    unittest.main()
