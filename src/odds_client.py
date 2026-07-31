# -*- coding: utf-8 -*-
"""Client για το The Odds API (https://the-odds-api.com/): φέρνει πραγματικές
αποδόσεις στοιχήματος (1/Χ/2) από πολλά γραφεία για την Premier League, και
τις μετατρέπει σε "implied probabilities" -- ένα τρίτο σημείο σύγκρισης
δίπλα στα δικά μας μοντέλα Poisson/Elo.

ΣΗΜΑΝΤΙΚΟ: το free/base πλάνο δίνει μόνο ΖΩΝΤΑΝΕΣ αποδόσεις -- το ιστορικό
odds endpoint (/v4/historical/...) θέλει πληρωμένο πλάνο και δεν είναι
διαθέσιμο εδώ (δοκιμάστηκε, γυρνάει άδειο). Άρα δεν μπορούμε να βάλουμε την
"αγορά" στο backtest.py σε παλιές σεζόν -- μόνο από εδώ και πέρα, καθώς το
update.py τρέχει καθημερινά και αποθηκεύει τις τρέχουσες αποδόσεις πριν
παιχτεί κάθε αγωνιστική, χτίζοντας σιγά-σιγά δικό μας ιστορικό ακρίβειας."""

import requests

from . import config

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT = "soccer_epl"

# "Sharp" bookmaker με πολύ χαμηλό περιθώριο (vig) -- προτιμάται σαν η πιο
# αξιόπιστη εκτίμηση της "αληθινής" πιθανότητας. Αν λείπει από έναν αγώνα,
# πέφτουμε σε μέσο όρο όλων των διαθέσιμων γραφείων.
PREFERRED_BOOKMAKER = "pinnacle"

# Odds API -> football-data.org ονόματα ομάδων. Χρειάζεται έλεγχο/ενημέρωση
# αν αλλάξουν οι ομάδες της Premier League την επόμενη σεζόν (προβιβασμοί/
# υποβιβασμοί).
TEAM_NAME_MAP = {
    "Arsenal": "Arsenal FC",
    "Aston Villa": "Aston Villa FC",
    "Bournemouth": "AFC Bournemouth",
    "Brentford": "Brentford FC",
    "Brighton and Hove Albion": "Brighton & Hove Albion FC",
    "Chelsea": "Chelsea FC",
    "Coventry City": "Coventry City FC",
    "Crystal Palace": "Crystal Palace FC",
    "Everton": "Everton FC",
    "Fulham": "Fulham FC",
    "Hull City": "Hull City AFC",
    "Ipswich Town": "Ipswich Town FC",
    "Leeds United": "Leeds United FC",
    "Liverpool": "Liverpool FC",
    "Manchester City": "Manchester City FC",
    "Manchester United": "Manchester United FC",
    "Newcastle United": "Newcastle United FC",
    "Nottingham Forest": "Nottingham Forest FC",
    "Sunderland": "Sunderland AFC",
    "Tottenham Hotspur": "Tottenham Hotspur FC",
}


def _map_name(odds_name: str) -> str:
    return TEAM_NAME_MAP.get(odds_name, odds_name)


def fetch_epl_odds(regions: str = "eu", markets: str = "h2h") -> list[dict]:
    """Ακατέργαστη λίστα events από το API. Ρίχνει exception αν αποτύχει το
    request (π.χ. εξαντλημένο μηνιαίο όριο) -- ο caller αποφασίζει τι κάνει."""
    url = f"{BASE_URL}/sports/{SPORT}/odds/"
    params = {
        "apiKey": config.ODDS_API_TOKEN,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _implied_probs(home_price: float, draw_price: float, away_price: float) -> tuple[float, float, float]:
    """Δεκαδικές αποδόσεις -> πιθανότητες, αφαιρώντας το περιθώριο του
    γραφείου (overround) με απλή αναλογική κανονικοποίηση (ώστε το άθροισμα
    να κάνει ακριβώς 1.0)."""
    raw_h, raw_d, raw_a = 1.0 / home_price, 1.0 / draw_price, 1.0 / away_price
    total = raw_h + raw_d + raw_a
    return raw_h / total, raw_d / total, raw_a / total


def _probs_from_bookmaker(bookmaker: dict, home_name: str, away_name: str):
    for market in bookmaker.get("markets", []):
        if market.get("key") != "h2h":
            continue
        prices = {o["name"]: o["price"] for o in market.get("outcomes", [])
                   if o.get("name") and o.get("price")}
        if home_name in prices and away_name in prices and "Draw" in prices:
            return _implied_probs(prices[home_name], prices["Draw"], prices[away_name])
    return None


def _build_result(home_name: str, away_name: str, ph: float, pd: float, pa: float) -> dict:
    if ph >= pd and ph >= pa:
        outcome = "H"
    elif pa >= pd:
        outcome = "A"
    else:
        outcome = "D"
    return {
        "home_name": _map_name(home_name),
        "away_name": _map_name(away_name),
        "prob_home": ph,
        "prob_draw": pd,
        "prob_away": pa,
        "predicted_outcome": outcome,
    }


def extract_match_odds(event: dict) -> dict | None:
    """Από ένα event του Odds API, implied probabilities H/D/A -- Pinnacle
    αν υπάρχει, αλλιώς μέσος όρος όλων των γραφείων που έχουν πλήρη αγορά
    h2h (και οι τρεις εκβάσεις)."""
    home_name = event.get("home_team")
    away_name = event.get("away_team")
    bookmakers = event.get("bookmakers") or []
    if not home_name or not away_name or not bookmakers:
        return None

    pinnacle = next((b for b in bookmakers if b.get("key") == PREFERRED_BOOKMAKER), None)
    if pinnacle:
        probs = _probs_from_bookmaker(pinnacle, home_name, away_name)
        if probs:
            return _build_result(home_name, away_name, *probs)

    all_probs = [p for p in (_probs_from_bookmaker(bk, home_name, away_name)
                              for bk in bookmakers) if p]
    if not all_probs:
        return None
    ph = sum(p[0] for p in all_probs) / len(all_probs)
    pd = sum(p[1] for p in all_probs) / len(all_probs)
    pa = sum(p[2] for p in all_probs) / len(all_probs)
    return _build_result(home_name, away_name, ph, pd, pa)


def fetch_predictions_by_team_names() -> dict[tuple[str, str], dict]:
    """{(home_name, away_name): prediction} με ονόματα ήδη μεταφρασμένα στη
    μορφή football-data.org, για όλα τα events που επέστρεψε το API. Αν
    λείπει το token ή αποτύχει το request, επιστρέφει άδειο dict -- το
    update.py συνεχίζει κανονικά μόνο με Poisson/Elo."""
    if not config.ODDS_API_TOKEN:
        return {}
    try:
        events = fetch_epl_odds()
    except Exception:
        return {}
    out = {}
    for ev in events:
        r = extract_match_odds(ev)
        if r:
            out[(r["home_name"], r["away_name"])] = r
    return out
