import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import config, db, elo, predictor, render


class EloCalibrationTests(unittest.TestCase):
    def test_calibration_preserves_order_and_probability_mass(self):
        raw = (0.72, 0.18, 0.10)
        calibrated = elo.calibrate_probabilities(raw)

        self.assertAlmostEqual(sum(calibrated), 1.0, places=12)
        self.assertEqual(max(range(3), key=raw.__getitem__),
                         max(range(3), key=calibrated.__getitem__))
        self.assertLess(max(calibrated), max(raw))

    def test_predict_match_returns_valid_probabilities(self):
        prediction = elo.predict_match({1: 1620.0, 2: 1480.0}, 1, 2)
        probabilities = (
            prediction["prob_home"],
            prediction["prob_draw"],
            prediction["prob_away"],
        )

        self.assertAlmostEqual(sum(probabilities), 1.0, places=12)
        self.assertTrue(all(0.0 < probability < 1.0 for probability in probabilities))

    def test_temperature_must_be_positive(self):
        with self.assertRaises(ValueError):
            elo.calibrate_probabilities((0.5, 0.3, 0.2), temperature=0)


class PoissonProbabilityTests(unittest.TestCase):
    def test_prediction_probabilities_sum_to_one(self):
        model = {
            "avg_home_goals": 1.5,
            "avg_away_goals": 1.1,
            "teams": {
                1: {
                    "home_attack": 1.2, "home_defense": 0.9,
                    "away_attack": 1.0, "away_defense": 1.0,
                },
                2: {
                    "home_attack": 1.0, "home_defense": 1.0,
                    "away_attack": 0.9, "away_defense": 1.1,
                },
            },
        }
        prediction = predictor.predict_match(model, 1, 2)

        self.assertAlmostEqual(
            prediction["prob_home"] + prediction["prob_draw"] + prediction["prob_away"],
            1.0,
            places=12,
        )
        self.assertGreaterEqual(prediction["prob_over25"], 0.0)
        self.assertLessEqual(prediction["prob_over25"], 1.0)
        self.assertGreaterEqual(prediction["prob_btts"], 0.0)
        self.assertLessEqual(prediction["prob_btts"], 1.0)


class AccuracyMetricTests(unittest.TestCase):
    def test_accuracy_log_loss_and_brier(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(config, "DB_PATH", db_path):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """INSERT INTO matches
                           (id, competition, season, status, home_score, away_score)
                           VALUES (1, 'PL', 2025, 'FINISHED', 2, 0),
                                  (2, 'PL', 2025, 'FINISHED', 1, 1)"""
                    )
                    conn.execute(
                        """INSERT INTO predictions
                           (match_id, model, prob_home, prob_draw, prob_away,
                            calibration_version)
                           VALUES (1, 'elo', 0.7, 0.2, 0.1, 1),
                                  (2, 'elo', 0.2, 0.6, 0.2, 1)"""
                    )

                stats = db.accuracy_stats(2025, model="elo", competition="PL")

        expected_log_loss = (-math.log(0.7) - math.log(0.6)) / 2
        expected_brier = (
            ((0.7 - 1) ** 2 + 0.2 ** 2 + 0.1 ** 2)
            + (0.2 ** 2 + (0.6 - 1) ** 2 + 0.2 ** 2)
        ) / 2
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["result_pct"], 100.0)
        self.assertAlmostEqual(stats["log_loss"], expected_log_loss)
        self.assertAlmostEqual(stats["brier_score"], expected_brier)

    def test_legacy_elo_probabilities_are_calibrated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with patch.object(config, "DB_PATH", db_path):
                db.init_db()
                with db.connect() as conn:
                    conn.execute(
                        """INSERT INTO matches
                           (id, competition, season, status, home_score, away_score)
                           VALUES (1, 'PL', 2025, 'FINISHED', 2, 0)"""
                    )
                    conn.execute(
                        """INSERT INTO predictions
                           (match_id, model, prob_home, prob_draw, prob_away,
                            calibration_version)
                           VALUES (1, 'elo', 0.8, 0.15, 0.05, 0)"""
                    )
                legacy = db.all_predictions_with_results("elo")[0]

        expected = elo.calibrate_probabilities((0.8, 0.15, 0.05))
        self.assertAlmostEqual(legacy["prob_home"], expected[0])
        self.assertLess(legacy["prob_home"], 0.8)


class RenderNavigationTests(unittest.TestCase):
    def test_structured_navigation_separates_season_and_view(self):
        sections = [
            {
                "id": "current", "label": "Τρέχουσα σεζόν 2026-2027",
                "season_key": "current", "season_label": "2026-2027", "view": "overview",
                "html": '<section id="current" class="tab-panel" style="display:block"></section>',
            },
            {
                "id": "detail-current", "label": "Αναλυτικά 2026-2027",
                "season_key": "current", "season_label": "2026-2027", "view": "details",
                "html": (
                    '<section id="detail-current" class="tab-panel" '
                    'style="display:none"></section>'
                ),
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(config, "OUTPUT_DIR", Path(tmp)):
                output = Path(render.render_site(sections, out_filename="test.html"))
                html = output.read_text(encoding="utf-8")

        self.assertIn("Σεζόν", html)
        self.assertIn("Επισκόπηση", html)
        self.assertIn("Αγώνες", html)
        self.assertIn('data-season="current" data-view="details"', html)


if __name__ == "__main__":
    unittest.main()
