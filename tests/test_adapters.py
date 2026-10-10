import unittest

from tests import checks


class AdapterChecks(unittest.TestCase):
    def test_seedance_prompt_contract(self):
        checks.check_seedance_prompt_contract()

    def test_adapter_config(self):
        checks.check_adapter_config()

    def test_audio_bindings(self):
        checks.check_audio_bindings()

    def test_execution_target_routing(self):
        checks.check_execution_target_routing()


if __name__ == "__main__":
    unittest.main()
