# -*- coding: utf-8 -*-
"""Στατιστικό μοντέλο πρόβλεψης βασισμένο σε κατανομή Poisson (ο κλασικός
τρόπος να προβλέπεις σκορ ποδοσφαίρου, βλ. Maher 1982 / Dixon-Coles 1997).

Ιδέα:
  1. Υπολογίζουμε πόσα γκολ βάζει/δέχεται κάθε ομάδα σε σχέση με τον μέσο όρο
     της διοργάνωσης, ξεχωριστά ως γηπεδούχος και ως φιλοξενούμενος
     ("επιθετική"/"αμυντική δύναμη").
  2. Για έναν επερχόμενο αγώνα, πολλαπλασιάζουμε τις δυνάμεις των δύο ομάδων
     με τον μέσο όρο γκολ της διοργάνωσης, ώστε να βγει το αναμενόμενο σκορ
     (λ) για κάθε πλευρά.
  3. Χτίζουμε πίνακα πιθανοτήτων Poisson(λ_home) x Poisson(λ_away) και από
     εκεί βγάζουμε πιθανότητες 1/Χ/2 και το πιο πιθανό ακριβές σκορ.
"""

import math
from collections import defaultdict

MAX_GOALS = 8  # αρκετό εύρος για ρεαλιστικά σκορ Premier League


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def compute_strengths(matches: list[dict]) -> dict | None:
    """matches: λίστα από dict με home_team_id, away_team_id, home_score, away_score."""
    home_goals_for = defaultdict(list)
    home_goals_against = defaultdict(list)
    away_goals_for = defaultdict(list)
    away_goals_against = defaultdict(list)

    total_home_goals = 0
    total_away_goals = 0
    n = 0

    for m in matches:
        hs, aw = m.get("home_score"), m.get("away_score")
        if hs is None or aw is None:
            continue
        h, a = m.get("home_team_id"), m.get("away_team_id")
        if h is None or a is None:
            continue
        home_goals_for[h].append(hs)
        home_goals_against[h].append(aw)
        away_goals_for[a].append(aw)
        away_goals_against[a].append(hs)
        total_home_goals += hs
        total_away_goals += aw
        n += 1

    if n == 0:
        return None

    avg_home = total_home_goals / n
    avg_away = total_away_goals / n

    teams = set(home_goals_for) | set(away_goals_for)

    def avg(lst, fallback):
        return (sum(lst) / len(lst)) if lst else fallback

    strengths = {}
    for t in teams:
        h_for = avg(home_goals_for.get(t, []), avg_home)
        h_against = avg(home_goals_against.get(t, []), avg_away)
        a_for = avg(away_goals_for.get(t, []), avg_away)
        a_against = avg(away_goals_against.get(t, []), avg_home)
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


def predict_match(model: dict, home_id: int, away_id: int) -> dict:
    teams = model["teams"]
    home_s = teams.get(home_id, _neutral_strength())
    away_s = teams.get(away_id, _neutral_strength())

    lam_home = home_s["home_attack"] * away_s["away_defense"] * model["avg_home_goals"]
    lam_away = away_s["away_attack"] * home_s["home_defense"] * model["avg_away_goals"]

    # Ασφάλεια ορίων ώστε ακραίες τιμές να μην τρελάνουν τον πίνακα Poisson.
    lam_home = max(0.05, min(lam_home, 6.0))
    lam_away = max(0.05, min(lam_away, 6.0))

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
