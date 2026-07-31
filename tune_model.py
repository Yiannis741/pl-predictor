# -*- coding: utf-8 -*-
"""Grid-search πάνω σε ήδη φορτωμένα ιστορικά δεδομένα (χρειάζεται να έχεις
τρέξει πρώτα `python backtest.py 2024` και `python backtest.py 2025`, ώστε
οι σεζόν αυτές να υπάρχουν στη βάση) για να βρεθεί ο καλύτερος συνδυασμός
παραμέτρων στο src/predictor.py.

Δεν κάνει καμία κλήση στο API -- δουλεύει πάνω σε ό,τι υπάρχει ήδη τοπικά,
οπότε τρέχει μέσα σε δευτερόλεπτα.

Τρέξιμο:  python tune_model.py

Ιστορικό συντονισμού (760 αγώνες, σεζόν 2024-25 + 2025-26, backtest χωρίς
διαρροή από το μέλλον):

  Φάση 1 -- HALF_LIFE_DAYS / DC_RHO: 365 / -0.10 έδωσαν το καλύτερο
  % σωστού αποτελέσματος (~50.3%) ΚΑΙ αισθητά καλύτερο % ακριβούς σκορ
  (~11.4%, από ~9.3% με rho=0), έναντι της αρχικής επιλογής (60, 0.0) που
  έδινε ~48.6% / ~8.2%.

  Φάση 2 -- SHRINKAGE_MATCHES / PROMOTED_ATTACK / PROMOTED_DEFENSE: βλ.
  σχόλια στο src/predictor.py για τα τελευταία νούμερα -- ξανάτρεξε το
  script για να τα επιβεβαιώσεις ή να τα ξαναβρείς αν προστεθούν άλλες
  σεζόν δεδομένων.

  Φάση 3/4 -- Elo K / HOME_ADV / DRAW_D / DRAW_S: βλ. σχόλια στο
  src/elo.py για τα τελευταία νούμερα.
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db, elo, predictor  # noqa: E402

# Ζευγάρια (σεζόν-στόχος, προηγούμενη σεζόν) που χρησιμοποιούνται για το
# grid-search. Πρέπει να έχουν ήδη περάσει από backtest.py. Η 2022 δεν είναι
# διαθέσιμη στο δωρεάν πλάνο (403), οπότε η 2023 συμμετέχει χωρίς "βάση"
# από προηγούμενη σεζόν -- οι πρώτες της αγωνιστικές θα είναι πιο αδύναμο
# σήμα, αλλά προσθέτει ~370 επιπλέον αγώνες στο grid-search.
EVAL_PAIRS = [(2023, 2022), (2024, 2023), (2025, 2024)]


def evaluate(season: int, prev_season: int, half_life: float, rho: float,
             shrink: float = 0.0, promo_atk: float = 1.0,
             promo_def: float = 1.0) -> tuple[int, int, int]:
    predictor.HALF_LIFE_DAYS = half_life
    predictor.SHRINKAGE_MATCHES = shrink
    predictor.PROMOTED_ATTACK = promo_atk
    predictor.PROMOTED_DEFENSE = promo_def

    matchdays = db.distinct_matchdays(season)
    correct = exact = total = 0
    for md in matchdays:
        fixtures = db.matchday_matches(season, md)
        fixtures = [f for f in fixtures if f.get("home_team_id") and f.get("away_team_id")
                    and f.get("home_score") is not None and f.get("away_score") is not None]
        if not fixtures:
            continue
        dates = [f["utc_date"] for f in fixtures if f.get("utc_date")]
        if not dates:
            continue
        cutoff = min(dates)
        history = db.finished_matches_before([season, prev_season], cutoff)
        model = predictor.compute_strengths(history)
        if model is None:
            continue
        for m in fixtures:
            pred = predictor.predict_match(model, m["home_team_id"], m["away_team_id"], dc_rho=rho)
            actual = "H" if m["home_score"] > m["away_score"] else (
                "A" if m["home_score"] < m["away_score"] else "D")
            total += 1
            if pred["predicted_outcome"] == actual:
                correct += 1
            if (m["home_score"] == pred["predicted_home_score"]
                    and m["away_score"] == pred["predicted_away_score"]):
                exact += 1
    return correct, exact, total


def evaluate_elo(season: int, prev_season: int, k: float, home_adv: float,
                  draw_d: float, draw_s: float) -> tuple[int, int]:
    elo.K = k
    elo.HOME_ADV = home_adv
    elo.DRAW_D = draw_d
    elo.DRAW_S = draw_s

    matchdays = db.distinct_matchdays(season)
    correct = total = 0
    for md in matchdays:
        fixtures = db.matchday_matches(season, md)
        fixtures = [f for f in fixtures if f.get("home_team_id") and f.get("away_team_id")
                    and f.get("home_score") is not None and f.get("away_score") is not None]
        if not fixtures:
            continue
        dates = [f["utc_date"] for f in fixtures if f.get("utc_date")]
        if not dates:
            continue
        cutoff = min(dates)
        history = db.finished_matches_before([season, prev_season], cutoff)
        history_sorted = sorted(history, key=lambda m: m.get("utc_date") or "")
        ratings = elo.compute_ratings(history_sorted)
        for m in fixtures:
            pred = elo.predict_match(ratings, m["home_team_id"], m["away_team_id"])
            actual = "H" if m["home_score"] > m["away_score"] else (
                "A" if m["home_score"] < m["away_score"] else "D")
            total += 1
            if pred["predicted_outcome"] == actual:
                correct += 1
    return correct, total


def _run_grid_elo(label: str, combos, key_names) -> list[tuple]:
    print(f"\n== {label} ==")
    results = []
    for combo in combos:
        c = t = 0
        for season, prev in EVAL_PAIRS:
            dc, dt = evaluate_elo(season, prev, *combo)
            c, t = c + dc, t + dt
        if t == 0:
            print("Δεν βρέθηκαν δεδομένα -- τρέξε πρώτα backtest.py για τις σεζόν "
                  f"{EVAL_PAIRS}.")
            return []
        pct = c / t * 100
        results.append((*combo, pct, t))
        combo_str = "  ".join(f"{k}={v}" for k, v in zip(key_names, combo))
        print(f"{combo_str}  correct={pct:5.1f}%  n={t}")

    results.sort(key=lambda r: -r[-2])
    print(f"-- TOP 5 ({label}) --")
    for r in results[:5]:
        print(r)
    return results


def phase3_elo_k_homeadv() -> tuple[float, float]:
    ks = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
    home_advs = [30.0, 50.0, 70.0, 90.0, 110.0]
    combos = [(k, ha, 50.0, 300.0) for k in ks for ha in home_advs]
    results = _run_grid_elo("Φάση 3: Elo K x HOME_ADV (draw_d=50, draw_s=300 σταθερά)",
                             combos, ["K", "home_adv", "draw_d", "draw_s"])
    best = results[0]
    return best[0], best[1]


def phase4_elo_draw_buffer(k: float, home_adv: float) -> None:
    draw_ds = [0.0, 25.0, 50.0, 75.0, 100.0, 125.0]
    draw_ss = [150.0, 200.0, 250.0, 300.0, 400.0, 500.0]
    combos = [(k, home_adv, dd, ds) for dd in draw_ds for ds in draw_ss]
    _run_grid_elo(f"Φάση 4: Elo DRAW_D x DRAW_S [K={k}, home_adv={home_adv}]",
                  combos, ["K", "home_adv", "draw_d", "draw_s"])


def _run_grid(label: str, combos, key_names) -> list[tuple]:
    print(f"\n== {label} ==")
    results = []
    for combo in combos:
        c = e = t = 0
        for season, prev in EVAL_PAIRS:
            dc, de, dt = evaluate(season, prev, *combo)
            c, e, t = c + dc, e + de, t + dt
        if t == 0:
            print("Δεν βρέθηκαν δεδομένα -- τρέξε πρώτα backtest.py για τις σεζόν "
                  f"{EVAL_PAIRS}.")
            return []
        pct, expct = c / t * 100, e / t * 100
        results.append((*combo, pct, expct, t))
        combo_str = "  ".join(f"{k}={v:+.2f}" if isinstance(v, float) and v < 0
                               else f"{k}={v}" for k, v in zip(key_names, combo))
        print(f"{combo_str}  correct={pct:5.1f}%  exact={expct:4.1f}%  n={t}")

    results.sort(key=lambda r: -r[-3])
    print(f"-- TOP 5 ({label}) --")
    for r in results[:5]:
        print(r)
    return results


def phase1_half_life_rho() -> tuple[float, float]:
    half_lives = [30, 45, 60, 90, 120, 182, 365]
    rhos = [0.0, -0.05, -0.10, -0.15, -0.20]
    combos = [(hl, rho, 0.0, 1.0, 1.0) for hl in half_lives for rho in rhos]
    results = _run_grid("Φάση 1: HALF_LIFE_DAYS x DC_RHO",
                         combos, ["hl", "rho", "shrink", "p_atk", "p_def"])
    best = results[0]
    return best[0], best[1]


def phase2_shrinkage_promoted(half_life: float, rho: float) -> None:
    shrinks = [0.0, 3.0, 5.0, 8.0, 12.0, 20.0]
    promo_pairs = [(1.00, 1.00), (0.95, 1.05), (0.90, 1.10),
                   (0.85, 1.15), (0.80, 1.20), (0.75, 1.25)]
    combos = [(half_life, rho, s, pa, pd) for s in shrinks for pa, pd in promo_pairs]
    _run_grid(f"Φάση 2: SHRINKAGE_MATCHES x (PROMOTED_ATTACK, PROMOTED_DEFENSE) "
              f"[hl={half_life}, rho={rho}]",
              combos, ["hl", "rho", "shrink", "p_atk", "p_def"])


def main() -> None:
    phase1_half_life_rho()
    # Χρησιμοποιούμε τις ήδη τεκμηριωμένες τιμές (365, -0.10) για τη Φάση 2,
    # όχι ό,τι βγάλει η Φάση 1 σαν "νικητή" -- η διαφορά ανάμεσα σε -0.05 και
    # -0.10 είναι μέσα στο στατιστικό θόρυβο (n=760, ~1.8% τυπικό σφάλμα),
    # και το -0.10 δίνει σταθερά καλύτερο % ακριβούς σκορ.
    phase2_shrinkage_promoted(365.0, -0.10)

    best_k, best_ha = phase3_elo_k_homeadv()
    phase4_elo_draw_buffer(best_k, best_ha)

    print("\n== σύγκριση: πάντα πρόβλεψη νίκης γηπεδούχου ==")
    for season, _prev in EVAL_PAIRS:
        matches = db.finished_matches(season)
        h = sum(1 for m in matches if m["home_score"] > m["away_score"])
        n = len(matches)
        if n:
            print(f"  σεζόν {season}: {h / n * 100:.1f}% θα πετύχαινε")


if __name__ == "__main__":
    main()
