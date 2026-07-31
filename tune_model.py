# -*- coding: utf-8 -*-
"""Grid-search πάνω σε ήδη φορτωμένα ιστορικά δεδομένα (χρειάζεται να έχεις
τρέξει πρώτα `python backtest.py 2024` και `python backtest.py 2025`, ώστε
οι σεζόν αυτές να υπάρχουν στη βάση) για να βρεθεί ο καλύτερος συνδυασμός
HALF_LIFE_DAYS / DC_RHO στο src/predictor.py.

Δεν κάνει καμία κλήση στο API -- δουλεύει πάνω σε ό,τι υπάρχει ήδη τοπικά,
οπότε τρέχει μέσα σε δευτερόλεπτα.

Τρέξιμο:  python tune_model.py

Το τελευταίο τρέξιμο (Ιούλιος 2026, 760 αγώνες από τις σεζόν 2024-25 και
2025-26) έδειξε ότι HALF_LIFE_DAYS=365 και DC_RHO=-0.10 δίνουν το καλύτερο
% σωστού αποτελέσματος (~50.3%) ΚΑΙ αισθητά καλύτερο % ακριβούς σκορ
(~11.4%, από ~9.3% με rho=0) σε σχέση με την αρχική επιλογή (60, 0.0) που
έδινε ~48.6% / ~8.2%. Οι τιμές αυτές είναι ήδη εφαρμοσμένες στο
src/predictor.py -- ξανάτρεξε αυτό το script αν προστεθούν κι άλλες σεζόν
δεδομένων, για να επιβεβαιώσεις ότι οι τιμές παραμένουν οι καλύτερες.
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db, predictor  # noqa: E402

# Ζευγάρια (σεζόν-στόχος, προηγούμενη σεζόν) που χρησιμοποιούνται για το
# grid-search. Πρέπει να έχουν ήδη περάσει από backtest.py.
EVAL_PAIRS = [(2024, 2023), (2025, 2024)]

HALF_LIVES = [30, 45, 60, 90, 120, 182, 365]
RHOS = [0.0, -0.05, -0.10, -0.15, -0.20]


def evaluate(season: int, prev_season: int, half_life: float, rho: float) -> tuple[int, int, int]:
    predictor.HALF_LIFE_DAYS = half_life
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


def main() -> None:
    results = []
    for hl in HALF_LIVES:
        for rho in RHOS:
            c = e = t = 0
            for season, prev in EVAL_PAIRS:
                dc, de, dt = evaluate(season, prev, hl, rho)
                c, e, t = c + dc, e + de, t + dt
            if t == 0:
                print("Δεν βρέθηκαν δεδομένα -- τρέξε πρώτα backtest.py για τις σεζόν "
                      f"{EVAL_PAIRS}.")
                return
            pct, expct = c / t * 100, e / t * 100
            results.append((hl, rho, pct, expct, t))
            print(f"hl={hl:4d}  rho={rho:+.2f}  correct={pct:5.1f}%  exact={expct:4.1f}%  n={t}")

    results.sort(key=lambda r: -r[2])
    print("\n== TOP 8 κατά % σωστού αποτελέσματος ==")
    for r in results[:8]:
        print(r)

    print("\n== σύγκριση: πάντα πρόβλεψη νίκης γηπεδούχου ==")
    for season, _prev in EVAL_PAIRS:
        matches = db.finished_matches(season)
        h = sum(1 for m in matches if m["home_score"] > m["away_score"])
        n = len(matches)
        if n:
            print(f"  σεζόν {season}: {h / n * 100:.1f}% θα πετύχαινε")


if __name__ == "__main__":
    main()
