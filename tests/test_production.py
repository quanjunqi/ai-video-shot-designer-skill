import unittest

from tests import checks


class ProductionChecks(unittest.TestCase):
    def test_submit_receipt(self):
        checks.check_submit_receipt_and_case_defaults()

    def test_video_provenance(self):
        checks.check_video_provenance()

    def test_context_reference(self):
        checks.check_context_reference()

    def test_text_and_h3_facts(self):
        checks.check_text_policy_and_h3_facts()


if __name__ == "__main__":
    unittest.main()
