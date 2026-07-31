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

from src import config, db, predictor, render  # noqa: E402
from src.api_client import FootballDataClient  # noqa: E402

# Αν η τρέχουσα σεζόν έχει λιγότερους τελειωμένους αγώνες από αυτό το όριο
# (π.χ. αρχή σεζόν), δανειζόμαστε και την περσινή για να έχει το μοντέλο
# αρκετά δεδομένα.
MIN_MATCHES_FOR_CURRENT_SEASON = 40  # περίπου 4 πλήρεις αγωνιστικές


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

    matchday, fixtures = db.next_matchday_fixtures(season)
    preds = []
    if matchday is None:
        print("Δεν βρέθηκε επόμενη αγωνιστική με προγραμματισμένους αγώνες.")
    else:
        print(f"Προβλέψεις για αγωνιστική {matchday} ({len(fixtures)} αγώνες)...")
        for m in fixtures:
            pred = predictor.predict_match(model, m["home_team_id"], m["away_team_id"])
            preds.append({"match_id": m["id"], **pred})
        db.save_predictions(preds)

    out_path = render.render_report(season, matchday, fixtures, preds)
    print(f"Ολοκληρώθηκε. Δες το {out_path}")


if __name__ == "__main__":
    main()
