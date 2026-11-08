import os
import sys
from pathlib import Path
import unittest

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

class TestSystemConfigBlackbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Acceptance Criteria 1: Module import must succeed without NameError (Any, etc.)
        try:
            import config.system_config as cfg
            cls.cfg = cfg
        except Exception as e:
            raise RuntimeError(f"Failed to import config.system_config: {e}") from e

    def test_acceptance_criteria_normalize_direction(self):
        """
        Acceptance Criteria 2:
        normalize_direction with: 0, 1, 'go', 're', '0', '1'
        """
        expected_mappings = [
            (0, "go"),
            (1, "re"),
            ("go", "go"),
            ("re", "re"),
            ("0", "go"),
            ("1", "re"),
        ]
        for val, expected in expected_mappings:
            with self.subTest(input_val=val, expected=expected):
                result = self.cfg.normalize_direction(val)
                self.assertEqual(
                    result,
                    expected,
                    f"normalize_direction({val!r}) returned {result!r}, expected {expected!r}",
                )

    def test_acceptance_criteria_normalize_direction_int(self):
        """
        Acceptance Criteria 2:
        normalize_direction_int with: 0, 1, 'go', 're', '0', '1'
        """
        expected_mappings = [
            (0, 0),
            (1, 1),
            ("go", 0),
            ("re", 1),
            ("0", 0),
            ("1", 1),
        ]
        for val, expected in expected_mappings:
            with self.subTest(input_val=val, expected=expected):
                result = self.cfg.normalize_direction_int(val)
                self.assertEqual(
                    result,
                    expected,
                    f"normalize_direction_int({val!r}) returned {result!r}, expected {expected!r}",
                )

    def test_case_insensitivity_and_vietnamese_labels(self):
        """
        Edge cases: case insensitivity and common Vietnamese bus direction strings.
        """
        test_cases = [
            ("GO", "go", 0),
            ("RE", "re", 1),
            ("Go", "go", 0),
            ("Re", "re", 1),
            ("Chiều đi", "go", 0),
            ("Chiều về", "re", 1),
        ]
        for val, exp_str, exp_int in test_cases:
            with self.subTest(input_val=val):
                self.assertEqual(self.cfg.normalize_direction(val), exp_str)
                self.assertEqual(self.cfg.normalize_direction_int(val), exp_int)

    def test_fallback_robustness(self):
        """
        Safety check: gracefully handles unexpected/None inputs with deterministic default.
        """
        fallback_inputs = [None, "", "unknown", 999]
        for val in fallback_inputs:
            with self.subTest(input_val=val):
                res_str = self.cfg.normalize_direction(val)
                res_int = self.cfg.normalize_direction_int(val)
                self.assertIn(res_str, ("go", "re"))
                self.assertIn(res_int, (0, 1))

if __name__ == "__main__":
    unittest.main(verbosity=2)
