# -*- coding: utf-8 -*-
"""Κύριο script: τραβάει τους αγώνες Premier League από το football-data.org,
τους αποθηκεύει τοπικά, χτίζει το μοντέλο πρόβλεψης και παράγει το
output/index.html με τις προβλέψεις της επόμενης αγωνιστικής.

Τρέξιμο:  python update.py
"""

import datetime
import sys
from pathlib import Path

if sys.platform == "win32":
    # Η κονσόλα των Windows χρησιμοποιεί συχνά cp1252, που δεν καταλαβαίνει
    # ελληνικά· το ξαναφτιάχνουμε σε utf-8 ώστε τα print() να μη σκάνε.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import config, db, elo, odds_client, predictor, render, simulate  # noqa: E402
from src.api_client import FootballDataClient  # noqa: E402

# Αν η τρέχουσα σεζόν έχει λιγότερους τελειωμένους αγώνες από αυτό το όριο
# (π.χ. αρχή σεζόν), δανειζόμαστε και την περσινή για να έχει το μοντέλο
# αρκετά δεδομένα.
MIN_MATCHES_FOR_CURRENT_SEASON = 40  # περίπου 4 πλήρεις αγωνιστικές

# Ιστορικές σεζόν που εμφανίζονται σαν επιπλέον καρτέλες, ΑΝ υπάρχουν ήδη
# δεδομένα γι' αυτές στη βάση (φορτώνονται μία φορά με `python backtest.py
# <σεζόν>` — το update.py δεν ξανακάνει τα ίδια API calls κάθε μέρα, απλά
# διαβάζει ό,τι υπάρχει ήδη τοπικά).
HISTORICAL_SEASONS = [2025, 2024, 2023]


def current_season_year(today: datetime.date | None = None) -> int:
    """Το football-data.org δηλώνει σεζόν με το έτος έναρξης (π.χ. 2025 για
    τη σεζόν 2025-26). Η Premier League ξεκινά Αύγουστο, οπότε πριν τον
    Ιούλιο θεωρούμε ότι είμαστε ακόμα στην προηγούμενη σεζόν."""
    today = today or datetime.date.today()
    return today.year if today.month >= 7 else today.year - 1


def main() -> None:
    print("== pl-predictor: ενημέρωση ==")
    db.init_db()

    client = FootballDataClient()
    season = current_season_year()
    print(f"Σεζόν: {season}-{season + 1}")

    print("Λήψη αγώνων τρέχουσας σεζόν από football-data.org ...")
    matches = client.get_matches(competition=config.COMPETITION_CODE, season=season)
    db.save_matches(matches, season)
    print(f"  {len(matches)} αγώνες αποθηκεύτηκαν/ενημερώθηκαν.")

    finished = db.finished_matches(season)

    if len(finished) < MIN_MATCHES_FOR_CURRENT_SEASON:
        prev_season = season - 1
        print(f"Λίγοι τελειωμένοι αγώνες ({len(finished)}) στην τρέχουσα σεζόν· "
              f"τραβάω και την περσινή ({prev_season}-{prev_season + 1}) για το μοντέλο.")
        prev_matches = client.get_matches(competition=config.COMPETITION_CODE, season=prev_season)
        db.save_matches(prev_matches, prev_season)
        finished = finished + db.finished_matches(prev_season)

    model = predictor.compute_strengths(finished)
    if model is None:
        print("Δεν βρέθηκαν αρκετά τελειωμένα ματς για μοντέλο πρόβλεψης. Σταματάω.")
        return

    finished_sorted = sorted(finished, key=lambda m: m.get("utc_date") or "")
    ratings = elo.compute_ratings(finished_sorted)

    matchday, fixtures = db.next_matchday_fixtures(season)
    preds = []
    market_matched = 0
    market_by_names = {}
    if matchday is None:
        print("Δεν βρέθηκε επόμενη αγωνιστική με προγραμματισμένους αγώνες.")
    else:
        print(f"Προβλέψεις για αγωνιστική {matchday} ({len(fixtures)} αγώνες)...")
        print("Λήψη αποδόσεων στοιχήματος (The Odds API) για σύγκριση...")
        market_by_names = odds_client.fetch_predictions_by_team_names()
        teams_lookup = db.team_names()
        for m in fixtures:
            pred = predictor.predict_match(model, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], "model": "poisson", **pred})
            epred = elo.predict_match(ratings, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], "model": "elo", **epred})

            home_name = teams_lookup.get(m["home_team_id"], {}).get("name")
            away_name = teams_lookup.get(m["away_team_id"], {}).get("name")
            mpred = market_by_names.get((home_name, away_name))
            if mpred:
                market_matched += 1
                preds.append({
                    "match_id": m["id"], "model": "market",
                    "prob_home": mpred["prob_home"], "prob_draw": mpred["prob_draw"],
                    "prob_away": mpred["prob_away"],
                    "predicted_outcome": mpred["predicted_outcome"],
                })
        if market_by_names:
            print(f"  Αποδόσεις αγοράς: {market_matched}/{len(fixtures)} αγώνες ταιριάχτηκαν.")
        else:
            print("  Δεν βρέθηκαν αποδόσεις αγοράς (λείπει token ή εξαντλήθηκε το όριο) -- "
                  "συνεχίζω μόνο με Poisson/Elo.")
        db.save_predictions(preds)

    print("Υπολογισμός βαθμολογίας/φόρμας...")
    table = db.standings_and_form(season)

    print("Έλεγχος ακρίβειας προηγούμενων προβλέψεων (Poisson, Elo & Αγορά)...")
    accuracy = db.accuracy_stats(season, model="poisson")
    team_accuracy = db.team_accuracy(season, model="poisson")
    elo_accuracy = db.accuracy_stats(season, model="elo")
    elo_team_accuracy = db.team_accuracy(season, model="elo")
    market_accuracy = db.accuracy_stats(season, model="market")
    market_team_accuracy = db.team_accuracy(season, model="market")
    # Η "αγορά" δεν έχει ιστορικό (μόνο ζωντανές αποδόσεις) -- δείχνουμε τη
    # στήλη μόνο αν όντως υπάρχουν δεδομένα (τρέξιμο με έγκυρο token, έστω
    # και μία φορά στο παρελθόν για τη φετινή σεζόν).
    show_market_current = bool(market_by_names) or bool(market_accuracy.get("total"))

    print(f"Προσομοίωση υπόλοιπης σεζόν ({simulate.N_SIMULATIONS} φορές, μοντέλο Poisson)...")
    all_matches = db.season_matches(season)
    sim = simulate.simulate_season(model, all_matches, season)

    current_label = f"Τρέχουσα σεζόν {season}-{season + 1}"
    sections = [{
        "id": "current",
        "label": current_label,
        "html": render.build_section(
            "current", current_label, season, matchday, fixtures, preds,
            table=table, accuracy=accuracy, sim=sim, team_accuracy=team_accuracy,
            elo_accuracy=elo_accuracy, elo_team_accuracy=elo_team_accuracy,
            market_accuracy=market_accuracy if show_market_current else None,
            market_team_accuracy=market_team_accuracy if show_market_current else None,
            active=True,
        ),
    }]
    detail_sections = [{
        "id": "detail-current",
        "label": f"Αναλυτικά {season}-{season + 1}",
        "html": render.build_detail_section(
            "detail-current", f"Αναλυτικά {season}-{season + 1}", season,
            all_matches, db.predictions_for_season(season, model="poisson"),
            db.predictions_for_season(season, model="elo"),
            db.predictions_for_season(season, model="market") if show_market_current else None,
        ),
    }]

    print("Έλεγχος για ήδη φορτωμένες ιστορικές σεζόν...")
    for hist_season in HISTORICAL_SEASONS:
        if hist_season == season:
            continue
        hist_matches = db.season_matches(hist_season)
        if not hist_matches:
            continue
        hist_table = db.standings_and_form(hist_season)
        hist_accuracy = db.accuracy_stats(hist_season, model="poisson")
        hist_team_accuracy = db.team_accuracy(hist_season, model="poisson")
        hist_elo_accuracy = db.accuracy_stats(hist_season, model="elo")
        hist_elo_team_accuracy = db.team_accuracy(hist_season, model="elo")
        if not hist_table:
            continue

        # Προσομοίωση "πριν την 1η αγωνιστική" γι' αυτή τη σεζόν, βασισμένη
        # στην ΠΡΟΗΓΟΥΜΕΝΗ της (αν υπάρχει ήδη τοπικά -- δεν κάνουμε κλήση
        # στο API εδώ). Μόνο για Poisson -- το Elo δεν παράγει αναμενόμενα
        # γκολ, οπότε δεν τροφοδοτεί την προσομοίωση Monte Carlo.
        prev_hist = db.finished_matches(hist_season - 1)
        hist_sim = {}
        if prev_hist:
            hist_preseason_model = predictor.compute_strengths(prev_hist)
            if hist_preseason_model is not None:
                hist_sim = simulate.simulate_season(hist_preseason_model, hist_matches, hist_season)

        print(f"  προσθήκη καρτέλας {hist_season}-{hist_season + 1} "
              f"({len(hist_table)} ομάδες στη βαθμολογία)")
        hist_id = f"season{hist_season}"
        hist_label = f"{hist_season}-{hist_season + 1}"
        sections.append({
            "id": hist_id,
            "label": hist_label,
            "html": render.build_section(
                hist_id, hist_label, hist_season, None, [], [], table=hist_table,
                accuracy=hist_accuracy, sim=hist_sim, team_accuracy=hist_team_accuracy,
                elo_accuracy=hist_elo_accuracy, elo_team_accuracy=hist_elo_team_accuracy,
                note="Ιστορική σεζόν (backtest) — δείχνει πόσο καλά θα δούλευε "
                     "το μοντέλο αν το είχαμε τρέξει τότε. Τίτλος/Top-4/Υποβ. "
                     "= τι θα προέβλεπε το μοντέλο Poisson ΠΡΙΝ την 1η αγωνιστική.",
            ),
        })
        detail_id = f"detail-{hist_season}"
        detail_label = f"Αναλυτικά {hist_season}-{hist_season + 1}"
        detail_sections.append({
            "id": detail_id,
            "label": detail_label,
            "html": render.build_detail_section(
                detail_id, detail_label, hist_season, hist_matches,
                db.predictions_for_season(hist_season, model="poisson"),
                db.predictions_for_season(hist_season, model="elo"),
            ),
        })

    out_path = render.render_site(sections + detail_sections)
    print(f"Ολοκληρώθηκε. Δες το {out_path}")


if __name__ == "__main__":
    main()
