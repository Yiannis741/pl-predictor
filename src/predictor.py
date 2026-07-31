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
# Επιλέχθηκε με grid-search πάνω σε 760 πραγματικούς αγώνες (backtest, σεζόν
# 2024-25 + 2025-26, matchday-by-matchday, χωρίς διαρροή από το μέλλον).
# Δοκιμάστηκαν 30-365 μέρες: το 365 έδωσε το καλύτερο % σωστού αποτελέσματος
# ΚΑΙ αισθητά καλύτερο % ακριβούς σκορ — μια πιο "αργή" απόσβεση (δηλαδή
# όλη η τελευταία σεζόν μετράει, όχι μόνο οι τελευταίοι μήνες) γενίκευε
# καλύτερα από την αρχική επιλογή των 60 ημερών.
HALF_LIFE_DAYS = 365.0  # βλ. tune_model.py

# Διόρθωση Dixon-Coles (1997) για τη γνωστή αδυναμία του απλού διπλού
# Poisson να υποεκτιμά κάποια χαμηλά σκορ (κυρίως ισοπαλίες 0-0/1-1).
# Επιλέχθηκε με το ίδιο grid-search: rho=-0.10 βελτίωσε το % ακριβούς σκορ
# από ~9.3% σε ~11.4% χωρίς να χειροτερέψει το % σωστού αποτελέσματος.
DC_RHO = -0.10

# Πόσο "τραβιέται" η εκτίμηση μιας ομάδας προς τον μέσο όρο της λίγκας όταν
# έχει λίγα δεδομένα (empirical-Bayes shrinkage). Το βάρος στα δικά της
# στατιστικά είναι n/(n+SHRINKAGE_MATCHES), όπου n το σταθμισμένο πλήθος
# αγώνων της -- δηλαδή SHRINKAGE_MATCHES ισοδυναμεί περίπου με "τόσους
# φανταστικούς αγώνες στον μέσο όρο" πριν εμπιστευτούμε πλήρως τη δική της
# φόρμα. Grid-search (tune_model.py, 760 αγώνες): shrink=3 κράτησε το ίδιο
# % σωστού αποτελέσματος (50.3%) ΚΑΙ βελτίωσε το % ακριβούς σκορ (11.4%->
# 12.1%). Μεγαλύτερες τιμές (8+) άρχισαν να χειροτερεύουν το % σωστού
# αποτελέσματος -- σημάδι υπερβολικής εξομάλυνσης.
SHRINKAGE_MATCHES = 3.0

# Ομάδα χωρίς ΚΑΘΟΛΟΥ ιστορικό στο παράθυρο δεδομένων μας (τυπικά μόλις
# ανέβηκε από Championship) -- υποθέτουμε ότι είναι πιο αδύναμη από τον μέσο
# όρο Premier League, όχι ουδέτερη. Grid-search: η διαφορά ανάμεσα σε
# διάφορες τιμές ποινής ήταν μέσα στο στατιστικό θόρυβο (n=760, ±1.8%), οπότε
# κρατήσαμε μια μέτρια, ρεαλιστική τιμή αντί για την ελαφρώς "καλύτερη" στο
# δείγμα (που πιθανώς είναι θόρυβος, όχι πραγματικό σήμα).
PROMOTED_ATTACK = 0.95
PROMOTED_DEFENSE = 1.05


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
        n = acc[1]
        if n <= 0:
            return fallback
        raw = acc[0] / n
        if SHRINKAGE_MATCHES <= 0:
            return raw
        w = n / (n + SHRINKAGE_MATCHES)
        return w * raw + (1 - w) * fallback

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


def _fallback_strength() -> dict:
    # Ομάδα χωρίς ΚΑΘΟΛΟΥ ιστορικό στο παράθυρο δεδομένων μας -- τυπικά
    # νεοφώτιστη. Βλ. PROMOTED_ATTACK/PROMOTED_DEFENSE παραπάνω.
    return {
        "home_attack": PROMOTED_ATTACK, "home_defense": PROMOTED_DEFENSE,
        "away_attack": PROMOTED_ATTACK, "away_defense": PROMOTED_DEFENSE,
    }


def expected_goals(model: dict, home_id: int, away_id: int) -> tuple[float, float]:
    """Το αναμενόμενο σκορ (λ) κάθε ομάδας, χωρίς να χτίσουμε ολόκληρο τον
    πίνακα Poisson — το χρησιμοποιεί και το predict_match() παρακάτω, και η
    προσομοίωση σεζόν (simulate.py) που χρειάζεται μόνο τα λ για χιλιάδες
    δείγματα."""
    teams = model["teams"]
    home_s = teams.get(home_id, _fallback_strength())
    away_s = teams.get(away_id, _fallback_strength())

    lam_home = home_s["home_attack"] * away_s["away_defense"] * model["avg_home_goals"]
    lam_away = away_s["away_attack"] * home_s["home_defense"] * model["avg_away_goals"]

    # Ασφάλεια ορίων ώστε ακραίες τιμές να μην τρελάνουν τον πίνακα Poisson.
    lam_home = max(0.05, min(lam_home, 6.0))
    lam_away = max(0.05, min(lam_away, 6.0))
    return lam_home, lam_away


def _dc_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Πολλαπλασιαστής Dixon-Coles για τα 4 χαμηλά σκορ όπου το απλό
    διπλό-Poisson μοντέλο είναι γνωστό ότι δεν είναι ακριβές."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def predict_match(model: dict, home_id: int, away_id: int,
                   dc_rho: float | None = None) -> dict:
    lam_home, lam_away = expected_goals(model, home_id, away_id)
    rho = DC_RHO if dc_rho is None else dc_rho

    matrix = [
        [_poisson_pmf(i, lam_home) * _poisson_pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
        for i in range(MAX_GOALS + 1)
    ]

    if rho:
        for i in (0, 1):
            for j in (0, 1):
                matrix[i][j] *= _dc_tau(i, j, lam_home, lam_away, rho)
        mass = sum(sum(row) for row in matrix)
        if mass > 0:
            matrix = [[v / mass for v in row] for row in matrix]

    p_home = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i > j)
    p_draw = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i == j)
    p_away = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1) if i < j)

    total = p_home + p_draw + p_away
    if total > 0:
        p_home, p_draw, p_away = p_home / total, p_draw / total, p_away / total

    # Over/Under 2.5 γκολ και "σκοράρουν και οι δύο" (BTTS) -- βγαίνουν
    # σχεδόν δωρεάν από τον ίδιο πίνακα Poisson που ήδη χτίσαμε, καμία
    # επιπλέον υπόθεση χρειάζεται.
    prob_over25 = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)
                       if i + j > 2)
    prob_btts = sum(matrix[i][j] for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)
                     if i > 0 and j > 0)

    best_i, best_j, best_p = 0, 0, -1.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            if matrix[i][j] > best_p:
                best_i, best_j, best_p = i, j, matrix[i][j]

    # Η "πρόβλεψη 1/Χ/2" πρέπει να είναι η έκβαση με τη μεγαλύτερη αθροιστική
    # πιθανότητα -- ΟΧΙ η έκβαση που τυχαίνει να συνεπάγεται το πιο πιθανό
    # ΜΕΜΟΝΩΜΕΝΟ ακριβές σκορ. Σε ισόρροπους αγώνες το πιο πιθανό μεμονωμένο
    # σκορ είναι συχνά μια ισοπαλία (π.χ. 1-1) ακόμα κι όταν το άθροισμα των
    # νικηφόρων σκορ μιας ομάδας (1-0, 2-0, 2-1, ...) δίνει μεγαλύτερη συνολική
    # πιθανότητα νίκης· το ακριβές σκορ είναι ένα ενδιαφέρον στοιχείο, αλλά η
    # επίσημη πρόβλεψη 1/Χ/2 πρέπει να βασίζεται στις αθροισμένες πιθανότητες.
    if p_home >= p_draw and p_home >= p_away:
        predicted_outcome = "H"
    elif p_away >= p_draw:
        predicted_outcome = "A"
    else:
        predicted_outcome = "D"

    return {
        "lambda_home": lam_home,
        "lambda_away": lam_away,
        "predicted_home_score": best_i,
        "predicted_away_score": best_j,
        "prob_home": p_home,
        "prob_draw": p_draw,
        "prob_away": p_away,
        "predicted_outcome": predicted_outcome,
        "prob_over25": prob_over25,
        "prob_btts": prob_btts,
    }
