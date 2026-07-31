# -*- coding: utf-8 -*-
"""Κύριο script: τραβάει τους αγώνες από το football-data.org για ΟΛΑ τα
πρωταθλήματα που καλύπτει το πρόγραμμα (βλ. src/competitions.py), τους
αποθηκεύει τοπικά, χτίζει τα μοντέλα πρόβλεψης (Poisson + Elo, και όπου
υπάρχουν ζωντανές αποδόσεις στοιχήματος -- Αγορά) και παράγει μία σελίδα
output/<slug>.html ανά πρωτάθλημα, συν μία κεντρική output/index.html με
κάρτες/λογότυπα για να διαλέγεις πρωτάθλημα.

Τρέξιμο:  python update.py             -> όλα τα πρωταθλήματα
          python update.py PL          -> μόνο ένα (π.χ. για γρήγορο τεστ)
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    # Η κονσόλα των Windows χρησιμοποιεί συχνά cp1252, που δεν καταλαβαίνει
    # ελληνικά· το ξαναφτιάχνουμε σε utf-8 ώστε τα print() να μη σκάνε.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import competitions, db, elo, odds_client, predictor, render, simulate  # noqa: E402
from src.api_client import FootballDataClient  # noqa: E402

# Αν η τρέχουσα σεζόν έχει λιγότερους τελειωμένους αγώνες από αυτό το όριο
# (π.χ. αρχή σεζόν), δανειζόμαστε και την περσινή για να έχει το μοντέλο
# αρκετά δεδομένα.
MIN_MATCHES_FOR_CURRENT_SEASON = 40  # περίπου 4 πλήρεις αγωνιστικές

# Πόσες προηγούμενες σεζόν εμφανίζονται σαν επιπλέον καρτέλες, ΑΝ υπάρχουν
# ήδη δεδομένα γι' αυτές στη βάση (φορτώνονται μία φορά με
# `python backtest.py <code> <σεζόν>` -- το update.py δεν ξανακάνει τα ίδια
# API calls κάθε μέρα, απλά διαβάζει ό,τι υπάρχει ήδη τοπικά).
HISTORICAL_SEASONS_BACK = 3


def current_season_year(today=None) -> int:
    """Backward-compat βοηθός για την Premier League (έτσι το εισάγει το
    backtest.py ιστορικά). Για άλλα πρωταθλήματα δες
    src/competitions.current_season_year(code)."""
    return competitions.current_season_year("PL", today)


def run_update(client: FootballDataClient, code: str) -> str | None:
    """Ενημερώνει ΕΝΑ πρωτάθλημα (fetch -> db -> προβλέψεις -> html).
    Επιστρέφει το path του html που παρήγαγε, ή None αν δεν υπήρχαν αρκετά
    δεδομένα."""
    comp = competitions.get(code)
    print(f"\n=== {comp['name']} ({code}) ===")

    season = competitions.current_season_year(code)
    label_now = competitions.season_label(season, code)
    print(f"Σεζόν: {label_now}")

    print("Λήψη αγώνων τρέχουσας σεζόν από football-data.org ...")
    matches = client.get_matches(competition=code, season=season)
    db.save_matches(matches, season, competition=code)
    print(f"  {len(matches)} αγώνες αποθηκεύτηκαν/ενημερώθηκαν.")

    finished = db.finished_matches(season, competition=code)

    if len(finished) < MIN_MATCHES_FOR_CURRENT_SEASON:
        prev_season = season - 1
        print(f"Λίγοι τελειωμένοι αγώνες ({len(finished)}) στην τρέχουσα σεζόν· "
              f"τραβάω και την περσινή ({competitions.season_label(prev_season, code)}) "
              f"για το μοντέλο.")
        prev_matches = client.get_matches(competition=code, season=prev_season)
        db.save_matches(prev_matches, prev_season, competition=code)
        finished = finished + db.finished_matches(prev_season, competition=code)

    model = predictor.compute_strengths(finished)
    if model is None:
        print("Δεν βρέθηκαν αρκετά τελειωμένα ματς για μοντέλο πρόβλεψης. Παραλείπεται.")
        return None

    finished_sorted = sorted(finished, key=lambda m: m.get("utc_date") or "")
    ratings = elo.compute_ratings(finished_sorted)

    matchday, fixtures = db.next_matchday_fixtures(season, competition=code)
    preds = []
    market_matched = 0
    market_by_names = {}
    if matchday is None:
        print("Δεν βρέθηκε επόμενη αγωνιστική με προγραμματισμένους αγώνες.")
    else:
        print(f"Προβλέψεις για αγωνιστική {matchday} ({len(fixtures)} αγώνες)...")
        odds_sport = comp.get("odds_sport")
        if odds_sport:
            print("Λήψη αποδόσεων στοιχήματος (The Odds API) για σύγκριση...")
            market_by_names = odds_client.fetch_predictions_by_team_names(odds_sport)
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
        elif odds_sport:
            print("  Δεν βρέθηκαν/ταιριάξανε αποδόσεις αγοράς -- συνεχίζω μόνο με Poisson/Elo.")
        db.save_predictions(preds)

    print("Υπολογισμός βαθμολογίας/φόρμας...")
    table = db.standings_and_form(season, competition=code)

    print("Έλεγχος ακρίβειας προηγούμενων προβλέψεων (Poisson, Elo & Αγορά)...")
    accuracy = db.accuracy_stats(season, model="poisson", competition=code)
    team_accuracy = db.team_accuracy(season, model="poisson", competition=code)
    elo_accuracy = db.accuracy_stats(season, model="elo", competition=code)
    elo_team_accuracy = db.team_accuracy(season, model="elo", competition=code)
    market_accuracy = db.accuracy_stats(season, model="market", competition=code)
    market_team_accuracy = db.team_accuracy(season, model="market", competition=code)
    # Η "αγορά" δεν έχει ιστορικό (μόνο ζωντανές αποδόσεις) -- δείχνουμε τη
    # στήλη μόνο αν όντως υπάρχουν δεδομένα.
    show_market_current = bool(market_by_names) or bool(market_accuracy.get("total"))

    print(f"Προσομοίωση υπόλοιπης σεζόν ({simulate.N_SIMULATIONS} φορές, μοντέλο Poisson)...")
    all_matches = db.season_matches(season, competition=code)
    sim = simulate.simulate_season(model, all_matches, season,
                                    top_n=comp["top_zone"], releg_n=comp["releg_zone"])

    current_label = f"Τρέχουσα σεζόν {label_now}"
    sections = [{
        "id": "current",
        "label": current_label,
        "html": render.build_section(
            "current", current_label, season, matchday, fixtures, preds,
            table=table, accuracy=accuracy, sim=sim, team_accuracy=team_accuracy,
            elo_accuracy=elo_accuracy, elo_team_accuracy=elo_team_accuracy,
            market_accuracy=market_accuracy if show_market_current else None,
            market_team_accuracy=market_team_accuracy if show_market_current else None,
            active=True, competition=code,
        ),
    }]
    detail_sections = [{
        "id": "detail-current",
        "label": f"Αναλυτικά {label_now}",
        "html": render.build_detail_section(
            "detail-current", f"Αναλυτικά {label_now}", season,
            all_matches, db.predictions_for_season(season, model="poisson", competition=code),
            db.predictions_for_season(season, model="elo", competition=code),
            db.predictions_for_season(season, model="market", competition=code)
            if show_market_current else None,
            competition=code,
        ),
    }]

    print("Έλεγχος για ήδη φορτωμένες ιστορικές σεζόν...")
    for back in range(1, HISTORICAL_SEASONS_BACK + 1):
        hist_season = season - back
        hist_matches = db.season_matches(hist_season, competition=code)
        if not hist_matches:
            continue
        hist_table = db.standings_and_form(hist_season, competition=code)
        hist_accuracy = db.accuracy_stats(hist_season, model="poisson", competition=code)
        hist_team_accuracy = db.team_accuracy(hist_season, model="poisson", competition=code)
        hist_elo_accuracy = db.accuracy_stats(hist_season, model="elo", competition=code)
        hist_elo_team_accuracy = db.team_accuracy(hist_season, model="elo", competition=code)
        if not hist_table:
            continue

        # Προσομοίωση "πριν την 1η αγωνιστική" γι' αυτή τη σεζόν, βασισμένη
        # στην ΠΡΟΗΓΟΥΜΕΝΗ της (αν υπάρχει ήδη τοπικά -- δεν κάνουμε κλήση
        # στο API εδώ). Μόνο για Poisson.
        prev_hist = db.finished_matches(hist_season - 1, competition=code)
        hist_sim = {}
        if prev_hist:
            hist_preseason_model = predictor.compute_strengths(prev_hist)
            if hist_preseason_model is not None:
                hist_sim = simulate.simulate_season(hist_preseason_model, hist_matches, hist_season,
                                                     top_n=comp["top_zone"], releg_n=comp["releg_zone"])

        hist_label = competitions.season_label(hist_season, code)
        print(f"  προσθήκη καρτέλας {hist_label} ({len(hist_table)} ομάδες στη βαθμολογία)")
        hist_id = f"season{hist_season}"
        sections.append({
            "id": hist_id,
            "label": hist_label,
            "html": render.build_section(
                hist_id, hist_label, hist_season, None, [], [], table=hist_table,
                accuracy=hist_accuracy, sim=hist_sim, team_accuracy=hist_team_accuracy,
                elo_accuracy=hist_elo_accuracy, elo_team_accuracy=hist_elo_team_accuracy,
                note="Ιστορική σεζόν (backtest) — δείχνει πόσο καλά θα δούλευε "
                     "το μοντέλο αν το είχαμε τρέξει τότε. Τίτλος/Top-N/Υποβ. "
                     "= τι θα προέβλεπε το μοντέλο Poisson ΠΡΙΝ την 1η αγωνιστική.",
                competition=code,
            ),
        })
        detail_id = f"detail-{hist_season}"
        detail_label = f"Αναλυτικά {hist_label}"
        detail_sections.append({
            "id": detail_id,
            "label": detail_label,
            "html": render.build_detail_section(
                detail_id, detail_label, hist_season, hist_matches,
                db.predictions_for_season(hist_season, model="poisson", competition=code),
                db.predictions_for_season(hist_season, model="elo", competition=code),
                competition=code,
            ),
        })

    out_path = render.render_site(sections + detail_sections, comp,
                                   out_filename=f"{comp['slug']}.html")
    print(f"Ολοκληρώθηκε. Δες το {out_path}")
    return out_path


def main() -> None:
    print("== pl-predictor: ενημέρωση ==")
    db.init_db()
    client = FootballDataClient()

    only = sys.argv[1] if len(sys.argv) > 1 else None
    codes = [only] if only else [c["code"] for c in competitions.COMPETITIONS]

    ok = []
    for code in codes:
        try:
            out_path = run_update(client, code)
            if out_path:
                ok.append(competitions.get(code))
        except Exception as e:
            print(f"  !! ΣΦΑΛΜΑ στο {code}: {e} -- προσπερνάω.")

    if not only:
        print("\nΧτίζω την κεντρική σελίδα (hub)...")
        hub_path = render.build_hub_page(ok)
        print(f"Ολοκληρώθηκε. Δες το {hub_path}")


if __name__ == "__main__":
    main()
