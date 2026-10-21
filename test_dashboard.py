"""Dashboard regressions using fixture readings, without calling external APIs."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

_runtime = tempfile.TemporaryDirectory()
for key, filename in (("CSV_LOG_PATH", "readings.csv"), ("WATERING_LOG_PATH", "watering.csv"),
                      ("ERROR_LOG_PATH", "errors.csv"), ("CACHE_DIR", "cache")):
    os.environ[key] = os.path.join(_runtime.name, filename)

import app
from charts import build_figures
from config import DEFAULT_PLANT_RULES


class DashboardTests(unittest.TestCase):
    def test_assets_and_layout_load(self):
        client = app.server.test_client()
        for path in ('/', '/_dash-layout', '/assets/dashboard.css'):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_unchecking_all_plants_shows_no_traces(self):
        self.assertEqual(app.filter_histories_by_selection({'Peace Lily': {}}, []), {})
        fig, _ = build_figures({}, DEFAULT_PLANT_RULES)
        self.assertEqual(len(fig.data), 0)
        self.assertTrue(fig.layout.annotations)

    def test_cards_keep_their_plant_identity(self):
        now = datetime.now(timezone.utc).isoformat()
        snapshot = {plant: {'moisture': 70 - i * 20, 'temp_f': 72, 'raw': 100,
                            'timestamp': now} for i, plant in enumerate(app.plant_names)}
        with patch('app.monitor.load_rules', return_value=DEFAULT_PLANT_RULES):
            result = app.update_cards({'snapshot': snapshot}, {}, DEFAULT_PLANT_RULES)
        for plant, card in zip(app.plant_names, result):
            self.assertIn(plant, card.children[0].children[0].children)

    def test_chart_colors_stable_and_bands_not_shared(self):
        t = datetime.now(timezone.utc)
        plants = app.plant_names[:2]
        histories = {p: {'times': [t], 'moisture': [50], 'temp': [70]} for p in plants}
        both, _ = build_figures(histories, DEFAULT_PLANT_RULES)
        single, _ = build_figures({plants[1]: histories[plants[1]]}, DEFAULT_PLANT_RULES)
        self.assertEqual(both.data[1].line.color, single.data[0].line.color)
        self.assertFalse(both.layout.shapes)
        self.assertTrue(single.layout.shapes)
        self.assertEqual(single.layout.uirevision, 'Moisture')


if __name__ == '__main__':
    unittest.main()
