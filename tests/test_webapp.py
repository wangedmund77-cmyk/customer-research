import unittest

from city_industry_research.webapp import _slugify


class WebAppTests(unittest.TestCase):
    def test_slugify_keeps_city_names(self):
        self.assertIn("江苏省-无锡市", _slugify("江苏省-无锡市"))

    def test_slugify_removes_symbols(self):
        self.assertEqual(_slugify("  a/b:c  "), "a-b-c")


if __name__ == "__main__":
    unittest.main()
