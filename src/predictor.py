# -*- coding: utf-8 -*-
"""Στατιστικό μοντέλο πρόβλεψης βασισμένο σε κατανομή Poisson (ο κλασικός
τρόπος να προβλέπεις σκορ ποδοσφαίρου, βλ. Maher 1982 / Dixon-Coles 1997),
με στάθμιση πρόσφατης φόρμας.

Ιδέα:
  1. Υπολογίζουμε πόσα γκολ βάζει/δέχεται κάθε ομάδα σε σχέση με τον μέσο όρο
     της διοργάνωσης, ξεχωριστά ως γηπεδούχος και ως φιλοξενούμενος
     ("επιθετική"/"αμυντική δύναμη"). Οι πιο πρόσφατοι αγώνες μετράνε
     περισσότερο από τους παλιότερους (εκθετική απόσβεση βάρους — βλ.
     _match_weight), ώστε η τρέχουσα φόρμα μιας ομάδας να επηρεάζει την
     πρόβλεψη περισσότερο από αποτελέσματα πολλών μηνών πριν.
  2. Για έναν επερχόμενο αγώνα, πολλαπλασιάζουμε τις δυνάμεις των δύο ομάδων
     με τον μέσο όρο γκολ της διοργάνωσης, ώστε να βγει το αναμενόμενο σκορ
     (λ) για κάθε πλευρά.
  3. Χτίζουμε πίνακα πιθανοτήτων Poisson(λ_home) x Poisson(λ_away) και από
     εκεί βγάζουμε πιθανότητες 1/Χ/2 και το πιο πιθανό ακριβές σκορ.
"""

import datetime
import math
from collections import defaultdict

MAX_GOALS = 8  # αρκετό εύρος για ρεαλιστικά σκορ Premier League

# Πόσες μέρες χρειάζονται για να "μισέψει" η βαρύτητα ενός παλιού αγώνα.
# 60 μέρες ≈ οι τελευταίοι 8-9 αγώνες μετράνε πολύ περισσότερο από αγώνες
# της αρχής της σεζόν ή από την περσινή σεζόν.
HALF_LIFE_DAYS = 60.0


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _match_weight(utc_date_str: str | None, reference: datetime.datetime) -> float:
    """Βάρος αγώνα βάσει "φρεσκάδας": 1.0 για σημερινό αγώνα, 0.5 μετά από
    HALF_LIFE_DAYS μέρες, 0.25 μετά από 2×HALF_LIFE_DAYS κ.ο.κ."""
    if not utc_date_str:
        return 0.3  # άγνωστη ημερομηνία -> μικρό, ασφαλές βάρος
    try:
        dt = datetime.datetime.fromisoformat(utc_date_str.replace("Z", "+00:00"))
    except ValueError:
        return 0.3
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    age_days = max(0.0, (reference - dt).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def compute_strengths(matches: list[dict]) -> dict | None:
    """matches: λίστα από dict με home_team_id, away_team_id, home_score,
    away_score, utc_date. Κάθε αγώνας μετράει με βάρος ανάλογο της
    φρεσκάδας του (βλ. _match_weight), όχι όλοι το ίδιο."""
    now = datetime.datetime.now(datetime.timezone.utc)

    # κάθε accumulator: team -> [Σ(βάρος × γκολ), Σβάρος]
    home_for: dict = defaultdict(lambda: [0.0, 0.0])
    home_against: dict = defaultdict(lambda: [0.0, 0.0])
    away_for: dict = defaultdict(lambda: [0.0, 0.0])
    away_against: dict = defaultdict(lambda: [0.0, 0.0])
    league_home = [0.0, 0.0]
    league_away = [0.0, 0.0]

    for m in matches:
        hs, aw = m.get("home_score"), m.get("away_score")
        if hs is None or aw is None:
            continue
        h, a = m.get("home_team_id"), m.get("away_team_id")
        if h is None or a is None:
            continue

        w = _match_weight(m.get("utc_date"), now)
        if w <= 0:
            continue

        home_for[h][0] += w * hs
        home_for[h][1] += w
        home_against[h][0] += w * aw
        home_against[h][1] += w
        away_for[a][0] += w * aw
        away_for[a][1] += w
        away_against[a][0] += w * hs
        away_against[a][1] += w

        league_home[0] += w * hs
        league_home[1] += w
        league_away[0] += w * aw
        league_away[1] += w

    if league_home[1] == 0:
        return None

    avg_home = league_home[0] / league_home[1]
    avg_away = league_away[0] / league_away[1]

    def wavg(acc, fallback):
        return (acc[0] / acc[1]) if acc[1] > 0 else fallback

    teams = set(home_for) | set(away_for)
    strengths = {}
    for t in teams:
        h_for = wavg(home_for.get(t, [0.0, 0.0]), avg_home)
        h_against = wavg(home_against.get(t, [0.0, 0.0]), avg_away)
        a_for = wavg(away_for.get(t, [0.0, 0.0]), avg_away)
        a_against = wavg(away_against.get(t, [0.0, 0.0]), avg_home)
        strengths[t] = {
            "home_attack": (h_for / avg_home) if avg_home else 1.0,
            "home_defense": (h_against / avg_away) if avg_away else 1.0,
            "away_attack": (a_for / avg_away) if avg_away else 1.0,
            "away_defense": (a_against / avg_home) if avg_home else 1.0,
        }

    return {"avg_home_goals": avg_home, "avg_away_goals": avg_away, "teams": strengths}


def _neutral_strength() -> dict:
    # Ομάδα χωρίς ιστορικό (π.χ. μόλις ανέβηκε) -> ουδέτερη (μέση) δύναμη.
    return {"home_attack": 1.0, "home_defense": 1.0, "away_attack": 1.0, "away_defense": 1.0}


def expected_goals(model: dict, home_id: int, away_id: int) -> tuple[float, float]:
    """Το αναμενόμενο σκορ (λ) κάθε ομάδας, χωρίς να χτίσουμε ολόκληρο τον
    πίνακα Poisson — το χρησιμοποιεί και το predict_match() παρακάτω, και η
    προσομοίωση σεζόν (simulate.py) που χρειάζεται μόνο τα λ για χιλιάδες
    δείγματα."""
    teams = model["teams"]
    home_s = teams.get(home_id, _neutral_strength())
    away_s = teams.get(away_id, _neutral_strength())

    lam_home = home_s["home_attack"] * away_s["away_defense"] * model["avg_home_goals"]
    lam_away = away_s["away_attack"] * home_s["home_defense"] * model["avg_away_goals"]

    # Ασφάλεια ορίων ώστε ακραίες τιμές να μην τρελάνουν τον πίνακα Poisson.
    lam_home = max(0.05, min(lam_home, 6.0))
    lam_away = max(0.05, min(lam_away, 6.0))
    return lam_home, lam_away


def predict_match(model: dict, home_id: int, away_id: int) -> dict:
    lam_home, lam_away = expected_goals(model, home_id, away_id)

    matrix = [
        [_poisson_pmf(i, lam_home) * _poisson_pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
        for i in range(MAX_GOALS + 1)
    ]

    p_home = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i > j)
    p_draw = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i == j)
    p_away = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i < j)

    total = p_home + p_draw + p_away
    if total > 0:
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    best_i, best_j, best_p = 0, 0, -1.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            if matrix[i][j] > best_p:
                best_i, best_j, best_p = i, j, matrix[i][j]

    return {
        "lambda_home": lam_home,
        "lambda_away": lam_away,
        "predicted_home_score": best_i,
        "predicted_away_score": best_j,
        "prob_home": p_home,
        "prob_draw": p_draw,
        "prob_away": p_away,
    }
