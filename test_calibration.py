import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import calibration
from config import FEEDS


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch('calibration.CACHE_DIR', self.tmp.name)
        p.start()
        self.addCleanup(p.stop)
        self.plant = next(iter(FEEDS))
        self.now = datetime.now(timezone.utc)

    def sample(self, minutes, value, fallback=False):
        calibration.record_snapshot({self.plant: {
            'timestamp': (self.now + timedelta(minutes=minutes)).isoformat(),
            'moisture': value, 'raw': 400 + value * 3}}, fallback, self.now + timedelta(minutes=minutes))

    def learn(self):
        for minute, value in ((-10, 20), (-5, 22), (0, 21)):
            self.sample(minute, value)
        point = calibration.capture(self.plant, 'ready', self.now)
        for minute, value in ((10, 79), (15, 80), (20, 81)):
            self.sample(minute, value)
        calibration.capture(self.plant, 'watered', self.now + timedelta(minutes=20))
        return point

    def test_median_and_proposal_survive_reload(self):
        self.assertEqual(self.learn()['moisture'], 21)
        self.assertEqual(calibration.suggested_rules(self.plant),
                         {'dry': 21, 'ideal_low': 35.8, 'ideal_high': 80})
        self.assertEqual(len(calibration.references(self.plant)), 2)

    def test_duplicate_readings_do_not_count_as_three(self):
        for _ in range(3):
            self.sample(0, 20)
        with self.assertRaisesRegex(ValueError, '3 distinct'):
            calibration.capture(self.plant, 'ready', self.now)

    def test_cached_and_invalid_readings_are_not_samples(self):
        for minute in (-10, -5, 0):
            self.sample(minute, 20, fallback=True)
        self.sample(0, float('nan'))
        with self.assertRaisesRegex(ValueError, '3 distinct'):
            calibration.capture(self.plant, 'ready', self.now)

    def test_stale_and_noisy_samples_rejected(self):
        for minute, value in ((-10, 10), (-5, 30), (0, 40)):
            self.sample(minute, value)
        with self.assertRaisesRegex(ValueError, 'still changing'):
            calibration.capture(self.plant, 'ready', self.now)
        with self.assertRaisesRegex(ValueError, 'stale'):
            calibration.capture(self.plant, 'ready', self.now + timedelta(minutes=15))

    def test_reference_cannot_reuse_samples_from_other_capture(self):
        for minute in (-10, -5, 0):
            self.sample(minute, 20)
        calibration.capture(self.plant, 'ready', self.now)
        with self.assertRaisesRegex(ValueError, '3 distinct'):
            calibration.capture(self.plant, 'watered', self.now)

    def test_reversed_range_rejected_and_reset_clears_references(self):
        self.learn()
        with calibration._lock:
            state = calibration._read()
            state[self.plant]['watered']['moisture'] = 10
            calibration._write(state)
        with self.assertRaisesRegex(ValueError, 'too close or reversed'):
            calibration.suggested_rules(self.plant)
        calibration.reset(self.plant)
        self.assertEqual(calibration.references(self.plant), {})


if __name__ == '__main__':
    unittest.main()
