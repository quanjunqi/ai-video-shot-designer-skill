import unittest

from tests import checks


class WorkflowChecks(unittest.TestCase):
    def test_workflow_config(self):
        checks.check_workflow_config()

    def test_module_boundaries(self):
        checks.check_coverage_module_boundary()
        checks.check_script_manifest_module_boundary()
        checks.check_visual_review_module_boundary()
        checks.check_spatial_review_module_boundary()

    def test_duration_and_capacity(self):
        checks.check_duration_and_capacity()

    def test_state_matrix(self):
        checks.check_state_matrix()

    def test_progressive_state_and_paths(self):
        checks.check_progressive_state_and_paths()


if __name__ == "__main__":
    unittest.main()
