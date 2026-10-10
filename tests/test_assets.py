import unittest

from tests import checks


class AssetChecks(unittest.TestCase):
    def test_ledger_authority(self):
        checks.check_asset_ledger_authority()

    def test_asset_contracts(self):
        checks.check_asset_contracts()


if __name__ == "__main__":
    unittest.main()
