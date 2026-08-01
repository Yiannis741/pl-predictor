# -*- coding: utf-8 -*-
"""Backtest: ξαναπαίζει μια παλιά, ήδη ολοκληρωμένη σεζόν αγωνιστική προς
αγωνιστική, χρησιμοποιώντας σε κάθε βήμα μόνο δεδομένα που θα ήταν ήδη
γνωστά εκείνη τη στιγμή (καμία διαρροή από το μέλλον) — έτσι βλέπουμε πόσο
καλά θα δούλευε πραγματικά το μοντέλο αν το είχαμε φτιάξει τότε, με
πραγματικά δεδομένα από την αρχή ως το τέλος της σεζόν.

Οι ίδιες παράμετροι μοντέλων (HALF_LIFE_DAYS, DC_RHO, shrinkage, Elo K/
HOME_ADV -- βλ. src/predictor.py, src/elo.py) χρησιμοποιούνται σε ΟΛΑ τα
πρωταθλήματα, συντονισμένες πάνω σε δεδομένα Premier League -- δεν
ξανατρέχουμε grid-search ανά πρωτάθλημα (θα πολλαπλασίαζε τον χρόνο x9 για
οριακό όφελος).

Τρέξιμο:
  python backtest.py                 -> Premier League, προεπιλεγμένη σεζόν
  python backtest.py 2024            -> Premier League, συγκεκριμένη σεζόν
  python backtest.py PD 2024         -> La Liga, σεζόν 2024-25
  python backtest.py BSA 2025        -> Brasileirão, σεζόν 2025

ΣΗΜΕΙΩΣΗ για το δωρεάν πλάνο του football-data.org: δίνει πρόσβαση μόνο
στις τελευταίες ~3-4 σεζόν. Χωρίς όρισμα σεζόν, το script διαλέγει
αυτόματα την παλιότερη διαθέσιμη σεζόν που έχει ΚΑΙ την προηγούμενή της
διαθέσιμη (ώστε να υπάρχει βάση για το μοντέλο από την 1η αγωνιστική).
"""

import sys
from pathlib import Path

import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import competitions, config, db, elo, predictor, render, simulate  # noqa: E402
from src.api_client import FootballDataClient  # noqa: E402


def run_backtest(code: str, season: int) -> None:
    comp = competitions.get(code)
    label = competitions.season_label(season, code)
    print(f"== Backtest {comp['name']} ({code}), σεζόν {label} ==")
    db.init_db()
    client = FootballDataClient()

    print("Λήψη αγώνων της σεζόν...")
    matches = client.get_matches(competition=code, season=season)
    db.save_matches(matches, season, competition=code)
    print(f"  {len(matches)} αγώνες.")

    prev_season = season - 1
    prev_label = competitions.season_label(prev_season, code)
    print(f"Λήψη αγώνων της προηγούμενης σεζόν ({prev_label}) ως αρχική εικόνα των ομάδων...")
    try:
        prev_matches = client.get_matches(competition=code, season=prev_season)
        db.save_matches(prev_matches, prev_season, competition=code)
        print(f"  {len(prev_matches)} αγώνες.")
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"  Μη διαθέσιμη με το δωρεάν πλάνο (403) — συνεχίζω χωρίς αυτήν. "
                  f"Οι πρώτες αγωνιστικές της {label} δεν θα έχουν αρκετό "
                  f"ιστορικό για πρόβλεψη, αλλά οι επόμενες θα δουλέψουν κανονικά μόλις "
                  f"συσσωρευτούν αγώνες μέσα στη σεζόν.")
            prev_season = None
        else:
            raise

    # Το μοντέλο όπως θα ήταν ΠΡΙΝ την 1η αγωνιστική -- μόνο η προηγούμενη
    # σεζόν είναι γνωστή ακόμα. Χρησιμοποιείται στην προσομοίωση παρακάτω,
    # ώστε να συγκρίνουμε "τι θα προβλέπαμε" με το πραγματικό τελικό αποτέλεσμα.
    preseason_model = (predictor.compute_strengths(db.finished_matches(prev_season, competition=code))
                        if prev_season is not None else None)

    matchdays = db.distinct_matchdays(season, competition=code)
    if not matchdays:
        print("Δεν βρέθηκαν αγωνιστικές γι' αυτή τη σεζόν.")
        return

    print(f"Αναπαραγωγή {len(matchdays)} αγωνιστικών (μία-μία, χωρίς να "
          f"'βλέπει' το μέλλον)...")
    for md in matchdays:
        fixtures = db.matchday_matches(season, md, competition=code)
        fixtures = [f for f in fixtures if f.get("home_team_id") and f.get("away_team_id")]
        if not fixtures:
            continue
        dates = [f["utc_date"] for f in fixtures if f.get("utc_date")]
        if not dates:
            continue
        cutoff = min(dates)

        seasons_for_history = [season] + ([prev_season] if prev_season is not None else [])
        history = db.finished_matches_before(seasons_for_history, cutoff, competition=code)
        model = predictor.compute_strengths(history)
        if model is None:
            continue

        # Το Elo θέλει τους αγώνες σε ΧΡΟΝΟΛΟΓΙΚΗ σειρά -- τους ξαναπαίζει
        # έναν-έναν για να φτάσει στο τρέχον rating κάθε ομάδας.
        history_sorted = sorted(history, key=lambda m: m.get("utc_date") or "")
        ratings = elo.compute_ratings(history_sorted)

        preds = []
        for m in fixtures:
            pred = predictor.predict_match(model, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], "model": "poisson", **pred})

            epred = elo.predict_match(ratings, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], "model": "elo", **epred})
        db.save_predictions(preds)

        if md % 5 == 0 or md == matchdays[-1]:
            print(f"  ...αγωνιστική {md}/{matchdays[-1]} έγινε")

    print("Υπολογισμός τελικής βαθμολογίας και ακρίβειας σε όλη τη σεζόν...")
    table = db.standings_and_form(season, competition=code)
    accuracy = db.accuracy_stats(season, model="poisson", competition=code)
    elo_accuracy = db.accuracy_stats(season, model="elo", competition=code)
    team_accuracy = db.team_accuracy(season, model="poisson", competition=code)
    elo_team_accuracy = db.team_accuracy(season, model="elo", competition=code)

    sim = {}
    if preseason_model is not None:
        print(f"Προσομοίωση όλης της σεζόν ({simulate.N_SIMULATIONS} φορές) με ό,τι "
              f"ήξερε το μοντέλο ΠΡΙΝ την 1η αγωνιστική...")
        all_matches = db.season_matches(season, competition=code)
        sim = simulate.simulate_season(preseason_model, all_matches, season,
                                        top_n=comp["top_zone"], releg_n=comp["releg_zone"])

    note = (f"Backtest: αναπαραγωγή της σεζόν {label} αγωνιστική προς "
            f"αγωνιστική. Κάθε πρόβλεψη έγινε χρησιμοποιώντας μόνο ό,τι ήταν ήδη "
            f"γνωστό πριν από εκείνη την αγωνιστική — καμία διαρροή από το μέλλον. Οι "
            f"στήλες Τίτλος/Top-N/Υποβ. δείχνουν τι θα προέβλεπε το μοντέλο ΠΡΙΝ την 1η "
            f"αγωνιστική, με μόνο την προηγούμενη σεζόν σαν βάση (γι' αυτό μπορεί να "
            f"δείχνουν υπερβολικά σίγουρες τιμές όπως 100% — έχουν μόνο ένα έτος δεδομένων "
            f"να στηριχτούν) — σύγκρινέ τες με το πραγματικό τελικό αποτέλεσμα στα αριστερά.")

    out_path = render.render_report(
        season, None, [], [], table=table, accuracy=accuracy, sim=sim,
        team_accuracy=team_accuracy, elo_accuracy=elo_accuracy,
        elo_team_accuracy=elo_team_accuracy,
        out_filename=f"backtest_{code}_{season}.html", note=note, competition=code,
    )
    print(f"Ολοκληρώθηκε. Δες το {out_path}")
    if accuracy.get("total"):
        exact_txt = (f", {accuracy['exact_pct']:.0f}% ακριβές σκορ"
                     if accuracy.get("exact_pct") is not None else "")
        print(f"Poisson σε {accuracy['total']} αγώνες: "
              f"{accuracy['result_pct']:.0f}% σωστό αποτέλεσμα{exact_txt}, "
              f"log loss={accuracy['log_loss']:.3f}, Brier={accuracy['brier_score']:.3f}")
    if elo_accuracy.get("total"):
        print(f"Elo σε {elo_accuracy['total']} αγώνες: "
              f"{elo_accuracy['result_pct']:.0f}% σωστό αποτέλεσμα, "
              f"log loss={elo_accuracy['log_loss']:.3f}, "
              f"Brier={elo_accuracy['brier_score']:.3f}")


if __name__ == "__main__":
    args = sys.argv[1:]
    code = "PL"
    target_season = None

    if len(args) == 2:
        code, target_season = args[0].upper(), int(args[1])
    elif len(args) == 1:
        if args[0].isdigit():
            target_season = int(args[0])
        else:
            code = args[0].upper()

    if target_season is None:
        # Το δωρεάν πλάνο δείχνει να καλύπτει μόνο τις τελευταίες ~3-4 σεζόν.
        # -2 από την τρέχουσα σεζόν αφήνει μια ολόκληρη σεζόν διαθέσιμη πριν
        # απ' αυτήν, ως βάση για το μοντέλο από την 1η αγωνιστική.
        target_season = competitions.current_season_year(code) - 2

    try:
        run_backtest(code, target_season)
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            print(f"\nΤο football-data.org δεν επιτρέπει πρόσβαση στη σεζόν {target_season} "
                  f"({code}) με το δωρεάν πλάνο (403). Δοκίμασε πιο πρόσφατη σεζόν, π.χ.:\n"
                  f"  python backtest.py {code} {competitions.current_season_year(code) - 1}")
        else:
            raise
