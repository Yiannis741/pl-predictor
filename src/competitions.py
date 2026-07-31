# -*- coding: utf-8 -*-
"""Μεταδεδομένα των πρωταθλημάτων που καλύπτει το πρόγραμμα -- τα 9 εγχώρια
πρωταθλήματα που δίνει το δωρεάν πλάνο του football-data.org (εκτός Παγκοσμίου
Κυπέλου, Euro και Champions League -- τα δύο πρώτα γιατί δεν είναι
πρωταθλήματα συλλόγων, το Champions League γιατί έχει εντελώς διαφορετική
δομή: όμιλοι + knockout, χωρίς υποβιβασμό, δεν κόβει στο μοντέλο βαθμολογίας/
προσομοίωσης που φτιάξαμε)."""

import datetime

# code: κωδικός football-data.org (χρησιμοποιείται σε API calls & στη βάση)
# slug: όνομα αρχείου εξόδου (output/<slug>.html)
# odds_sport: κωδικός sport του The Odds API (None αν δεν υποστηρίζεται)
# single_year_season: True για πρωταθλήματα που τρέχουν μέσα σε ΕΝΑ
#   ημερολογιακό έτος (π.χ. Βραζιλία, Μάρτιος-Δεκέμβριος) αντί για τη
#   συνηθισμένη ευρωπαϊκή σεζόν Αύγουστος-Μάιος που καλύπτει δύο έτη.
COMPETITIONS = [
    {
        "code": "PL", "name": "Premier League", "country": "Αγγλία",
        "emblem": "https://crests.football-data.org/PL.png",
        "slug": "premier-league", "odds_sport": "soccer_epl",
        "single_year_season": False,
    },
    {
        "code": "ELC", "name": "Championship", "country": "Αγγλία",
        "emblem": "https://crests.football-data.org/ELC.png",
        "slug": "championship", "odds_sport": "soccer_efl_champ",
        "single_year_season": False,
    },
    {
        "code": "PD", "name": "La Liga", "country": "Ισπανία",
        "emblem": "https://crests.football-data.org/laliga.png",
        "slug": "la-liga", "odds_sport": "soccer_spain_la_liga",
        "single_year_season": False,
    },
    {
        "code": "BL1", "name": "Bundesliga", "country": "Γερμανία",
        "emblem": "https://crests.football-data.org/BL1.png",
        "slug": "bundesliga", "odds_sport": "soccer_germany_bundesliga",
        "single_year_season": False,
    },
    {
        "code": "SA", "name": "Serie A", "country": "Ιταλία",
        "emblem": "https://crests.football-data.org/c111.png",
        "slug": "serie-a", "odds_sport": "soccer_italy_serie_a",
        "single_year_season": False,
    },
    {
        "code": "FL1", "name": "Ligue 1", "country": "Γαλλία",
        "emblem": "https://crests.football-data.org/FL1.png",
        "slug": "ligue-1", "odds_sport": "soccer_france_ligue_one",
        "single_year_season": False,
    },
    {
        "code": "DED", "name": "Eredivisie", "country": "Ολλανδία",
        "emblem": "https://crests.football-data.org/ED.png",
        "slug": "eredivisie", "odds_sport": "soccer_netherlands_eredivisie",
        "single_year_season": False,
    },
    {
        "code": "PPL", "name": "Primeira Liga", "country": "Πορτογαλία",
        "emblem": "https://crests.football-data.org/PPL.png",
        "slug": "primeira-liga", "odds_sport": "soccer_portugal_primeira_liga",
        "single_year_season": False,
    },
    {
        "code": "BSA", "name": "Campeonato Brasileiro Série A", "country": "Βραζιλία",
        "emblem": "https://crests.football-data.org/bsa.png",
        "slug": "brasileirao", "odds_sport": "soccer_brazil_campeonato",
        "single_year_season": True,
    },
]

BY_CODE = {c["code"]: c for c in COMPETITIONS}


def get(code: str) -> dict:
    return BY_CODE[code]


def season_label(season: int, code: str) -> str:
    """'2025-2026' για τις ευρωπαϊκές σεζόν, '2025' για τη Βραζιλία (τρέχει
    μέσα σε ένα ημερολογιακό έτος)."""
    if BY_CODE[code]["single_year_season"]:
        return str(season)
    return f"{season}-{season + 1}"


def current_season_year(code: str, today: datetime.date | None = None) -> int:
    """Ποιο έτος (όπως το δηλώνει το football-data.org, δηλ. το έτος
    έναρξης) θεωρούμε 'τρέχουσα σεζόν' σήμερα, για το δοσμένο πρωτάθλημα."""
    today = today or datetime.date.today()
    if BY_CODE[code]["single_year_season"]:
        # Η σεζόν Βραζιλίας ταυτίζεται περίπου με το ημερολογιακό έτος.
        return today.year
    # Ευρωπαϊκή σύμβαση: η σεζόν ξεκινά Αύγουστο, οπότε πριν τον Ιούλιο
    # είμαστε ακόμα στην προηγούμενη σεζόν.
    return today.year if today.month >= 7 else today.year - 1
