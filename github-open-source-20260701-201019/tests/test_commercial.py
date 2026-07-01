import tempfile
import unittest
from pathlib import Path

from gaokao_decision.commercial import system_info_payload


class CommercialMetadataTests(unittest.TestCase):
    def test_system_info_has_no_local_authorization_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = system_info_payload(Path(tmp))

        self.assertIn("app_version", payload)
        self.assertIn("release", payload)
        self.assertNotIn("license", payload)
        self.assertNotIn("machine_code", payload)


if __name__ == "__main__":
    unittest.main()
