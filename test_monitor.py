"""Run with python -m unittest -v test_monitor (no network required)."""
import copy
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import monitor
import notifications
from config import FEEDS, DEFAULT_PLANT_RULES


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target in ('monitor.CACHE_DIR', 'data_layer.CACHE_DIR'):
            p = patch(target, self.tmp.name)
            p.start()
            self.addCleanup(p.stop)
        notifications.init_notification_state(FEEDS)
        self.plant = next(iter(FEEDS))
        self.row = {'moisture': 10, 'temp_f': 70, 'raw': 100,
                    'timestamp': datetime.now(timezone.utc).isoformat()}

    def poll(self, fallback=False):
        with patch('monitor.data.fetch_latest_snapshot', return_value=({self.plant: self.row}, fallback)), \
             patch('monitor.data.log_to_csv') as log, \
             patch('monitor.data.should_log_reading', return_value=True), \
             patch('monitor.data.update_last_watered_if_needed') as watered, \
             patch('monitor.notifications.send_ntfy_alert', return_value=True) as send, \
             patch('monitor.notifications.maybe_send_daily_summary'):
            monitor.poll_once()
            return log, watered, send

    def test_collection_and_alerts_without_browser(self):
        log, watered, send = self.poll()
        log.assert_called_once()
        watered.assert_called_once()
        self.assertTrue(any(k['title'].startswith('Water alert') for a, k in send.call_args_list))
        self.assertEqual(monitor.snapshot_for_browser()['snapshot'][self.plant], self.row)

    def test_saved_rules_control_background_alerts(self):
        rules = copy.deepcopy(DEFAULT_PLANT_RULES)
        rules[self.plant]['dry'] = 5
        monitor.save_rules(rules)
        self.assertEqual(monitor.load_rules(), rules)
        _, _, send = self.poll()
        self.assertFalse(any(k['title'].startswith('Water alert') for a, k in send.call_args_list))

    def test_cached_readings_are_not_logged(self):
        log, watered, _ = self.poll(fallback=True)
        log.assert_not_called()
        watered.assert_not_called()

    def test_stale_and_missing_sensors_alert(self):
        self.row['timestamp'] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        _, _, send = self.poll()
        self.assertEqual(sum(k['title'].startswith('Sensor offline') for a, k in send.call_args_list), len(FEEDS))
        self.assertFalse(any(k['title'].startswith('Water alert') for a, k in send.call_args_list))

    def test_rate_limited_alert_retries(self):
        with patch('notifications.send_ntfy_alert', side_effect=[False, True]) as send:
            notifications.maybe_send_urgent_alert(self.plant, 10, 'Water now')
            self.assertFalse(notifications.alert_state[self.plant])
            notifications.maybe_send_urgent_alert(self.plant, 10, 'Water now')
            notifications.maybe_send_urgent_alert(self.plant, 10, 'Water now')
            self.assertEqual(send.call_count, 2)


if __name__ == '__main__':
    unittest.main()
