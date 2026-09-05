import unittest

from tools.enroll import Guide


class EnrollGuideTests(unittest.TestCase):
    def test_six_stages_include_initial_check_and_prompt_once_per_stage(self):
        messages = []
        guide = Guide(6, messages.append)
        self.assertEqual(messages, [])
        for stage in range(6):
            guide.finger_needed(True)
            guide.finger_needed(True)
            guide.finger_needed(False)
            if stage < 5:
                guide.status('enroll-stage-passed', False)
            else:
                guide.status('enroll-completed', True)
        prompts = [line for line in messages if 'Moment ' in line]
        self.assertEqual(len(prompts), 6)
        self.assertIn('6/6', prompts[-1])
        self.assertTrue(guide.completed)
        guide.finger_needed(True)
        self.assertEqual(len([line for line in messages if 'Moment ' in line]), 6)

    def test_retry_does_not_advance_and_tolerates_property_signal_order(self):
        for property_first in (True, False):
            with self.subTest(property_first=property_first):
                messages = []
                guide = Guide(6, messages.append)
                guide.finger_needed(True)
                guide.finger_needed(False)
                if property_first:
                    guide.finger_needed(True)
                guide.status('enroll-retry-scan', False)
                if not property_first:
                    guide.finger_needed(True)
                self.assertEqual(guide.passed, 0)
                self.assertEqual(len([line for line in messages if 'Moment 1/6' in line]), 2)

    def test_terminal_error_never_reports_success_or_prompts_again(self):
        messages = []
        guide = Guide(6, messages.append)
        guide.finger_needed(True)
        guide.status('enroll-unknown-error', True)
        guide.finger_needed(True)
        self.assertFalse(guide.completed)
        self.assertTrue(guide.done)
        self.assertEqual(len([line for line in messages if 'Moment ' in line]), 1)
        self.assertTrue(any('STOPP' in line for line in messages))


if __name__ == '__main__':
    unittest.main()
