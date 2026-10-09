"""Developer validation must report the checker actually attempted."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import validate_release as V


class ValidatorReportingTests(unittest.TestCase):
    def run_checker(self, code, output='', error=''):
        with patch.object(Path, 'is_file', return_value=True), patch.object(
                V.subprocess, 'run', return_value=subprocess.CompletedProcess([], code, output, error)) as run:
            report = V.official_validation(Path('package'), Path('validator.py'))
        self.assertEqual(run.call_args.args[0][-1], 'package')
        self.assertTrue(report['attempted'])
        return report

    def test_success_is_reported_from_actual_result(self):
        self.assertEqual(self.run_checker(0, 'Skill is valid!')['status'], 'passed')

    def test_missing_yaml_is_unavailable_but_invalid_skill_is_failure(self):
        self.assertEqual(self.run_checker(1, error="ModuleNotFoundError: No module named 'yaml'")['status'], 'unavailable')
        self.assertEqual(self.run_checker(1, 'Invalid frontmatter')['status'], 'failed')

    def test_missing_checker_is_not_claimed_attempted(self):
        with patch.object(Path, 'is_file', return_value=False), patch.object(V.subprocess, 'run') as run:
            report = V.official_validation(Path('package'), Path('missing.py'))
        self.assertEqual(report['status'], 'unavailable')
        self.assertFalse(report['attempted'])
        run.assert_not_called()

    def test_timeout_is_unavailable_without_fake_pass(self):
        with patch.object(Path, 'is_file', return_value=True), patch.object(
                V.subprocess, 'run', side_effect=subprocess.TimeoutExpired('checker', 30)):
            report = V.official_validation(Path('package'), Path('validator.py'))
        self.assertEqual(report['status'], 'unavailable')
        self.assertTrue(report['attempted'])


if __name__ == '__main__':
    unittest.main()
