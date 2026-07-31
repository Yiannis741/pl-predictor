# -*- coding: utf-8 -*-
"""Client για το The Odds API (https://the-odds-api.com/): φέρνει πραγματικές
αποδόσεις στοιχήματος (1/Χ/2) από πολλά γραφεία, για οποιοδήποτε από τα
πρωταθλήματα που καλύπτει το πρόγραμμα (βλ. src/competitions.py -- κάθε
πρωτάθλημα έχει το δικό του "odds_sport" key), και τις μετατρέπει σε
"implied probabilities" -- ένα τρίτο σημείο σύγκρισης δίπλα στα δικά μας
μοντέλα Poisson/Elo.

ΣΗΜΑΝΤΙΚΟ: το free/base πλάνο δίνει μόνο ΖΩΝΤΑΝΕΣ αποδόσεις -- το ιστορικό
odds endpoint (/v4/historical/...) θέλει πληρωμένο πλάνο και δεν είναι
διαθέσιμο εδώ (δοκιμάστηκε, γυρνάει άδειο). Άρα δεν μπορούμε να βάλουμε την
"αγορά" στο backtest.py σε παλιές σεζόν -- μόνο από εδώ και πέρα.

ΤΑΙΡΙΑΣΜΑ ΟΝΟΜΑΤΩΝ ΟΜΑΔΩΝ: το Odds API και το football-data.org δεν
χρησιμοποιούν πάντα το ίδιο ακριβώς όνομα για μια ομάδα (π.χ. διαφορετική
γλώσσα/συντομογραφία). Κάνουμε κανονικοποίηση (χωρίς τόνους/πεζά/συνηθισμένα
προθέματα όπως FC/CF/AC) και ταιριάζουμε ΜΟΝΟ σε ακριβή αντιστοιχία μετά την
κανονικοποίηση -- αν μια ομάδα δεν ταιριάξει (π.χ. εντελώς διαφορετικό
όνομα σε άλλη γλώσσα), απλά δεν εμφανίζεται η στήλη "Αγορά" για εκείνον τον
αγώνα, αντί να μαντεύουμε λάθος."""

import re
import unicodedata

import requests

from . import config, db

BASE_URL = "https://api.the-odds-api.com/v4"

# "Sharp" bookmaker με πολύ χαμηλό περιθώριο (vig) -- προτιμάται σαν η πιο
# αξιόπιστη εκτίμηση της "αληθινής" πιθανότητας. Αν λείπει από έναν αγώνα,
# πέφτουμε σε μέσο όρο όλων των διαθέσιμων γραφείων.
PREFERRED_BOOKMAKER = "pinnacle"

# Λέξεις/συντομογραφίες που αγνοούνται κατά την κανονικοποίηση ονομάτων --
# εμφανίζονται σαν "διακοσμητικά" προθέματα/επιθέματα σε πολλές γλώσσες και
# διαφέρουν συχνά ανάμεσα σε football-data.org και Odds API για την ΙΔΙΑ
# ομάδα (π.χ. "Arsenal FC" vs "Arsenal").
_STRIP_TOKENS = {
    "fc", "cf", "sc", "ac", "afc", "cd", "ud", "rc", "sd", "ca", "cr", "ec",
    "ssc", "calcio", "clube", "club", "futebol", "esporte", "clube de regatas",
    "and", "the",
}


def _normalize(name: str) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))  # αφαίρεση τόνων
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    tokens = [t for t in s.split() if t not in _STRIP_TOKENS]
    return " ".join(tokens)


def fetch_odds(sport_key: str, regions: str = "eu", markets: str = "h2h") -> list[dict]:
    """Ακατέργαστη λίστα events από το API. Ρίχνει exception αν αποτύχει το
    request (π.χ. εξαντλημένο μηνιαίο όριο) -- ο caller αποφασίζει τι κάνει."""
    url = f"{BASE_URL}/sports/{sport_key}/odds/"
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


def _build_result(ph: float, pd: float, pa: float) -> dict:
    if ph >= pd and ph >= pa:
        outcome = "H"
    elif pa >= pd:
        outcome = "A"
    else:
        outcome = "D"
    return {"prob_home": ph, "prob_draw": pd, "prob_away": pa, "predicted_outcome": outcome}


def extract_match_odds(event: dict) -> dict | None:
    """Από ένα event του Odds API, implied probabilities H/D/A (με τα
    ΑΚΑΤΕΡΓΑΣΤΑ ονόματα ομάδων του Odds API, όχι ακόμα ταιριασμένα) --
    Pinnacle αν υπάρχει, αλλιώς μέσος όρος όλων των γραφείων που έχουν
    πλήρη αγορά h2h (και οι τρεις εκβάσεις)."""
    home_name = event.get("home_team")
    away_name = event.get("away_team")
    bookmakers = event.get("bookmakers") or []
    if not home_name or not away_name or not bookmakers:
        return None

    pinnacle = next((b for b in bookmakers if b.get("key") == PREFERRED_BOOKMAKER), None)
    if pinnacle:
        probs = _probs_from_bookmaker(pinnacle, home_name, away_name)
        if probs:
            r = _build_result(*probs)
            r["home_name_raw"], r["away_name_raw"] = home_name, away_name
            return r

    all_probs = [p for p in (_probs_from_bookmaker(bk, home_name, away_name)
                              for bk in bookmakers) if p]
    if not all_probs:
        return None
    ph = sum(p[0] for p in all_probs) / len(all_probs)
    pd = sum(p[1] for p in all_probs) / len(all_probs)
    pa = sum(p[2] for p in all_probs) / len(all_probs)
    r = _build_result(ph, pd, pa)
    r["home_name_raw"], r["away_name_raw"] = home_name, away_name
    return r


def fetch_predictions_by_team_names(sport_key: str) -> dict[tuple[str, str], dict]:
    """{(home_name, away_name): prediction} με ονόματα ήδη ταιριασμένα στη
    μορφή football-data.org (μέσω κανονικοποιημένης αντιστοίχισης με τις
    ομάδες που ήδη έχουμε στη βάση), για όλα τα events που επέστρεψε το API.
    Ζευγάρια που δεν ταιριάζουν παραλείπονται σιωπηλά -- προτιμάμε να
    λείπει η "Αγορά" από ένα ματς παρά να δείξουμε λάθος αντιστοίχιση.
    Αν λείπει το token, δεν υπάρχει sport_key, ή αποτύχει το request,
    επιστρέφει άδειο dict."""
    if not config.ODDS_API_TOKEN or not sport_key:
        return {}
    try:
        events = fetch_odds(sport_key)
    except Exception:
        return {}

    # Ευρετήριο κανονικοποιημένο-όνομα -> επίσημο όνομα football-data.org,
    # από ΟΛΕΣ τις ομάδες που έχουμε ήδη στη βάση (global, δεν χρειάζεται
    # φιλτράρισμα ανά πρωτάθλημα -- τα ονόματα ομάδων είναι μοναδικά αρκετά
    # ώστε συγκρούσεις ανάμεσα σε πρωταθλήματα να είναι απίθανες).
    known = db.team_names()
    norm_to_official = {_normalize(t["name"]): t["name"] for t in known.values() if t.get("name")}

    out = {}
    for ev in events:
        r = extract_match_odds(ev)
        if not r:
            continue
        home_official = norm_to_official.get(_normalize(r["home_name_raw"]))
        away_official = norm_to_official.get(_normalize(r["away_name_raw"]))
        if not home_official or not away_official:
            continue
        out[(home_official, away_official)] = r
    return out
