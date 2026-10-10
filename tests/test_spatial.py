import unittest

from tests import checks


class SpatialChecks(unittest.TestCase):
    def test_signature_split(self):
        checks.check_spatial_signature_split()

    def test_continuous_space_mapping(self):
        checks.check_continuous_space_scene_mapping()

    def test_layout_before_camera(self):
        checks.check_layout_before_camera_gate()

    def test_user_facing_labels(self):
        checks.check_user_facing_map_labels()

    def test_boundaries_and_routes(self):
        checks.check_spatial_boundary_and_reachability()


if __name__ == "__main__":
    unittest.main()
