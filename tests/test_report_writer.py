import unittest

from city_industry_research.report_writer import _supports_temperature


class ReportWriterTests(unittest.TestCase):
    def test_gpt5_family_does_not_send_temperature(self):
        self.assertFalse(_supports_temperature("gpt-5.5"))
        self.assertFalse(_supports_temperature("gpt-5"))

    def test_other_models_can_send_temperature(self):
        self.assertTrue(_supports_temperature("gpt-4.1"))


if __name__ == "__main__":
    unittest.main()
