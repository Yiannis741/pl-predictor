import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src import config, db, elo, odds_client, predictor, render, simulate


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


class SimulationTests(unittest.TestCase):
    def test_seed_is_stable_when_match_order_changes(self):
        matches = [{"id": 30}, {"id": 10}, {"id": 20}]
        self.assertEqual(
            simulate._simulation_seed(2026, matches),
            simulate._simulation_seed(2026, list(reversed(matches))),
        )

    def test_exact_ties_do_not_favor_first_team(self):
        rng = np.random.default_rng(123)
        points = np.zeros(4)
        gd = np.zeros(4)
        gf = np.zeros(4)
        first_counts = np.zeros(4, dtype=int)

        for _ in range(2000):
            order = simulate._rank_teams(points, gd, gf, rng=rng)
            first_counts[order[0]] += 1

        self.assertTrue(all(400 < count < 600 for count in first_counts))

    def test_same_inputs_produce_same_simulation(self):
        model = {
            "avg_home_goals": 1.4,
            "avg_away_goals": 1.1,
            "teams": {
                team: {
                    "home_attack": 1.0, "home_defense": 1.0,
                    "away_attack": 1.0, "away_defense": 1.0,
                }
                for team in (1, 2)
            },
        }
        matches = [
            {
                "id": 1, "status": "SCHEDULED",
                "home_team_id": 1, "away_team_id": 2,
            },
            {
                "id": 2, "status": "SCHEDULED",
                "home_team_id": 2, "away_team_id": 1,
            },
        ]

        with patch.object(simulate, "N_SIMULATIONS", 250):
            first = simulate.simulate_season(model, matches, 2026, top_n=1, releg_n=1)
            second = simulate.simulate_season(model, matches, 2026, top_n=1, releg_n=1)

        self.assertEqual(first, second)


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

    def test_fixture_signal_uses_ev_only_when_decimal_odds_exist(self):
        fixture = {
            "id": 1, "home_team_id": 10, "away_team_id": 20,
            "utc_date": "2026-08-10T18:00:00Z",
        }
        teams = {
            10: {"name": "Home FC", "short_name": "Home", "crest": None},
            20: {"name": "Away FC", "short_name": "Away", "crest": None},
        }
        poisson = {
            1: {
                "predicted_outcome": "H", "prob_home": 0.55, "prob_draw": 0.25,
                "prob_away": 0.20, "predicted_home_score": 2,
                "predicted_away_score": 1, "lambda_home": 1.8, "lambda_away": 1.0,
                "prob_over25": 0.54, "prob_btts": 0.49,
            }
        }
        market_with_odds = {
            1: {
                "prob_home": 0.45, "prob_draw": 0.30, "prob_away": 0.25,
                "odds_home": 2.20, "odds_draw": 3.20, "odds_away": 3.80,
                "bookmaker": "Pinnacle",
            }
        }
        market_without_odds = {
            1: {"prob_home": 0.45, "prob_draw": 0.30, "prob_away": 0.25}
        }

        ev_html = render._fixtures_table(
            [fixture], poisson, {}, teams, market_with_odds
        )
        gap_html = render._fixtures_table(
            [fixture], poisson, {}, teams, market_without_odds
        )

        self.assertIn("EV +21%", ev_html)
        self.assertIn("απόκλιση +10", gap_html)
        self.assertNotIn("EV ", gap_html)


class OddsExtractionTests(unittest.TestCase):
    def test_pinnacle_quote_keeps_decimal_odds_and_source(self):
        event = {
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [{
                "key": "pinnacle",
                "title": "Pinnacle",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Home", "price": 2.1},
                        {"name": "Draw", "price": 3.2},
                        {"name": "Away", "price": 3.8},
                    ],
                }],
            }],
        }

        result = odds_client.extract_match_odds(event)

        self.assertEqual(result["bookmaker"], "Pinnacle")
        self.assertEqual(result["odds_home"], 2.1)
        self.assertAlmostEqual(
            result["prob_home"] + result["prob_draw"] + result["prob_away"], 1.0
        )


if __name__ == "__main__":
    unittest.main()
