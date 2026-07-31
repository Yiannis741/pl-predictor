# -*- coding: utf-8 -*-
"""Backtest: ξαναπαίζει μια παλιά, ήδη ολοκληρωμένη σεζόν αγωνιστική προς
αγωνιστική, χρησιμοποιώντας σε κάθε βήμα μόνο δεδομένα που θα ήταν ήδη
γνωστά εκείνη τη στιγμή (καμία διαρροή από το μέλλον) — έτσι βλέπουμε πόσο
καλά θα δούλευε πραγματικά το μοντέλο αν το είχαμε φτιάξει τότε, με
πραγματικά δεδομένα από την αρχή ως το τέλος της σεζόν.

Τρέξιμο:
  python backtest.py           -> προεπιλεγμένη παλιά σεζόν (βλ. παρακάτω)
  python backtest.py 2024      -> συγκεκριμένη σεζόν (εδώ: 2024-25)

ΣΗΜΕΙΩΣΗ για το δωρεάν πλάνο του football-data.org: δίνει πρόσβαση μόνο
στις τελευταίες ~3-4 σεζόν (δοκιμάστηκε: 2023, 2024, 2025 δουλεύουν, 2022
και παλιότερα γυρνάνε 403). Άρα "5 χρόνια πριν" δεν είναι διαθέσιμο· η
προεπιλογή εδώ διαλέγει την παλιότερη σεζόν που έχει ΚΑΙ την προηγούμενή
της διαθέσιμη (ώστε να υπάρχει βάση για το μοντέλο από την 1η αγωνιστική).
"""

import sys
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, db, predictor, render, simulate  # noqa: E402
from src.api_client import FootballDataClient  # noqa: E402
from update import current_season_year  # noqa: E402


def run_backtest(season: int) -> None:
    print(f"== Backtest σεζόν {season}-{season + 1} ==")
    db.init_db()
    client = FootballDataClient()

    print("Λήψη αγώνων της σεζόν...")
    matches = client.get_matches(competition=config.COMPETITION_CODE, season=season)
    db.save_matches(matches, season)
    print(f"  {len(matches)} αγώνες.")

    prev_season = season - 1
    print(f"Λήψη αγώνων της προηγούμενης σεζόν ({prev_season}-{prev_season + 1}) "
          f"ως αρχική εικόνα των ομάδων...")
    prev_matches = client.get_matches(competition=config.COMPETITION_CODE, season=prev_season)
    db.save_matches(prev_matches, prev_season)
    print(f"  {len(prev_matches)} αγώνες.")

    # Το μοντέλο όπως θα ήταν ΠΡΙΝ την 1η αγωνιστική -- μόνο η προηγούμενη
    # σεζόν είναι γνωστή ακόμα. Χρησιμοποιείται στην προσομοίωση παρακάτω,
    # ώστε να συγκρίνουμε "τι θα προβλέπαμε" με το πραγματικό τελικό αποτέλεσμα.
    preseason_model = predictor.compute_strengths(db.finished_matches(prev_season))

    matchdays = db.distinct_matchdays(season)
    if not matchdays:
        print("Δεν βρέθηκαν αγωνιστικές γι' αυτή τη σεζόν.")
        return

    print(f"Αναπαραγωγή {len(matchdays)} αγωνιστικών (μία-μία, χωρίς να "
          f"'βλέπει' το μέλλον)...")
    for md in matchdays:
        fixtures = db.matchday_matches(season, md)
        fixtures = [f for f in fixtures if f.get("home_team_id") and f.get("away_team_id")]
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

        preds = []
        for m in fixtures:
            pred = predictor.predict_match(model, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], **pred})
        db.save_predictions(preds)

        if md % 5 == 0 or md == matchdays[-1]:
            print(f"  ...αγωνιστική {md}/{matchdays[-1]} έγινε")

    print("Υπολογισμός τελικής βαθμολογίας και ακρίβειας σε όλη τη σεζόν...")
    table = db.standings_and_form(season)
    accuracy = db.accuracy_stats(season)

    sim = {}
    if preseason_model is not None:
        print(f"Προσομοίωση όλης της σεζόν ({simulate.N_SIMULATIONS} φορές) με ό,τι "
              f"ήξερε το μοντέλο ΠΡΙΝ την 1η αγωνιστική...")
        all_matches = db.season_matches(season)
        sim = simulate.simulate_season(preseason_model, all_matches, season)

    note = (f"Backtest: αναπαραγωγή της σεζόν {season}-{season + 1} αγωνιστική προς "
            f"αγωνιστική. Κάθε πρόβλεψη έγινε χρησιμοποιώντας μόνο ό,τι ήταν ήδη "
            f"γνωστό πριν από εκείνη την αγωνιστική — καμία διαρροή από το μέλλον. Οι "
            f"στήλες Τίτλος/Top-4/Υποβ. δείχνουν τι θα προέβλεπε το μοντέλο ΠΡΙΝ την 1η "
            f"αγωνιστική, με μόνο την προηγούμενη σεζόν σαν βάση (γι' αυτό μπορεί να "
            f"δείχνουν υπερβολικά σίγουρες τιμές όπως 100% — έχουν μόνο ένα έτος δεδομένων "
            f"να στηριχτούν) — σύγκρινέ τες με το πραγματικό τελικό αποτέλεσμα στα αριστερά.")

    out_path = render.render_report(
        season, None, [], [], table=table, accuracy=accuracy, sim=sim,
        out_filename=f"backtest_{season}.html", note=note,
    )
    print(f"Ολοκληρώθηκε. Δες το {out_path}")
    if accuracy.get("total"):
        print(f"Ακρίβεια σε {accuracy['total']} αγώνες όλης της σεζόν: "
              f"{accuracy['result_pct']:.0f}% σωστό αποτέλεσμα (1/Χ/2), "
              f"{accuracy['exact_pct']:.0f}% ακριβές σκορ")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target_season = int(sys.argv[1])
    else:
        # Το δωρεάν πλάνο δείχνει να καλύπτει μόνο τις τελευταίες ~3-4 σεζόν.
        # -2 από την τρέχουσα σεζόν αφήνει μια ολόκληρη σεζόν διαθέσιμη πριν
        # απ' αυτήν, ως βάση για το μοντέλο από την 1η αγωνιστική.
        target_season = current_season_year() - 2
    try:
        run_backtest(target_season)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"\nΤο football-data.org δεν επιτρέπει πρόσβαση στη σεζόν {target_season} "
                  f"με το δωρεάν πλάνο (403). Δοκίμασε πιο πρόσφατη σεζόν, π.χ.:\n"
                  f"  python backtest.py {current_season_year() - 1}")
        else:
            raise
