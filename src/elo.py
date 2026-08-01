# -*- coding: utf-8 -*-
"""Εναλλακτικό μοντέλο πρόβλεψης: Elo rating ανά ομάδα.

Διαφορά φιλοσοφίας από το src/predictor.py (Poisson): εκεί υπολογίζουμε
μέσους όρους γκολ πάνω σε ένα παράθυρο αγώνων (με χρονική απόσβεση). Εδώ
κάθε αγώνας ενημερώνει ΑΜΕΣΩΣ το rating των δύο ομάδων, σαν σκάκι --
δεν υπάρχει "παράθυρο" ή "μέσος όρος", το rating ΕΙΝΑΙ η συσσωρευμένη
ιστορία. Αυτό το κάνει πιο ευαίσθητο σε απότομες αλλαγές φόρμας: μια σειρά
ανατροπών μετακινεί το rating αμέσως, χωρίς να περιμένει να αλλάξει ο
μέσος όρος πολλών αγώνων.

Το κλασικό Elo δίνει πιθανότητα νίκης/ήττας (δύο εκβάσεις, όπως το σκάκι).
Το ποδόσφαιρο έχει και ισοπαλία, οπότε προσθέτουμε μια ζώνη "buffer" γύρω
από τη διαφορά rating μέσα στην οποία η ισοπαλία γίνεται πιο πιθανή.
"""

DEFAULT_RATING = 1500.0

# Παράμετροι -- τιμές από grid-search (βλ. tune_model.py, phase3/4, ίδιο
# backtest με το μοντέλο Poisson, n=1140 σε 3 σεζόν 2023-24/2024-25/2025-26).
#
# Φάση 3 (K x HOME_ADV, draw_d/draw_s σταθερά στα προεπιλεγμένα): K=40,
# home_adv=70 έδωσαν το καλύτερο % σωστού αποτελέσματος (~53.0%, από ~52.0%
# με K=20/home_adv=60). Το μεγαλύτερο K επιβεβαιώνει τη λογική του Elo εδώ:
# θέλουμε μοντέλο πιο ευαίσθητο σε πρόσφατη φόρμα, άρα μεγαλύτερο βήμα
# ενημέρωσης ανά αγώνα.
#
# Φάση 4 (DRAW_D x DRAW_S, με K/home_adv σταθερά): πολλοί συνδυασμοί βγήκαν
# ισοδύναμοι (~53.0%) -- η επιλογή ισοπαλίας εδώ δεν επηρεάζει πολύ το
# "ποιος κερδίζει" 1/Χ/2, μόνο πόσο συχνά προβλέπεται Χ. Κρατήσαμε τις ίδιες
# προεπιλογές (50, 300) αφού είναι μέσα στην κορυφαία ομάδα ΚΑΙ παράγουν
# πραγματικές προβλέψεις ισοπαλίας (draw_d=0 θα εξαφάνιζε τελείως το Χ).
K = 40.0             # πόσο μετακινείται το rating μετά από έναν αγώνα
HOME_ADV = 70.0      # bonus rating για τον γηπεδούχο
DRAW_D = 50.0        # πλάτος της "ζώνης ισοπαλίας" γύρω από διαφορά rating=0
DRAW_S = 300.0       # κλίμακα της λογιστικής καμπύλης για νίκη/ήττα εκτός ζώνης

# Temperature scaling των τριών πιθανοτήτων. Το 1.71 επιλέχθηκε αποκλειστικά
# στις σεζόν 2023-24 και 2024-25 (6.508 αγώνες) και ελέγχθηκε στην ανεξάρτητη
# σεζόν 2025-26 (3.295 αγώνες): log loss 1.059 -> 1.016, Brier 0.630 -> 0.607.
# Δεν αλλάζει ποια έκβαση είναι πιθανότερη, μόνο διορθώνει την υπερβολική
# βεβαιότητα του ακατέργαστου Elo.
PROBABILITY_TEMPERATURE = 1.71


def _expected(rating_diff: float) -> float:
    """Κλασικός τύπος Elo: πιθανότητα νίκης (ή 'αναμενόμενο σκορ' 0-1)."""
    return 1.0 / (1.0 + 10 ** (-rating_diff / 400.0))


def calibrate_probabilities(probabilities: tuple[float, float, float],
                            temperature: float = PROBABILITY_TEMPERATURE
                            ) -> tuple[float, float, float]:
    """Temperature scaling για πιθανότητες 1/Χ/2, χωρίς αλλαγή της κατάταξής τους."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    powered = [max(float(p), 1e-12) ** (1.0 / temperature) for p in probabilities]
    total = sum(powered)
    return tuple(p / total for p in powered)


def compute_ratings(matches_sorted: list[dict]) -> dict[int, float]:
    """matches_sorted: αγώνες σε ΧΡΟΝΟΛΟΓΙΚΗ σειρά (παλιότερος πρώτος).
    Επιστρέφει team_id -> τελικό rating, αφού «παίξει» ξανά όλους τους
    αγώνες με τη σειρά που έγιναν."""
    ratings: dict[int, float] = {}

    def get(t: int) -> float:
        return ratings.get(t, DEFAULT_RATING)

    for m in matches_sorted:
        hs, aw = m.get("home_score"), m.get("away_score")
        if hs is None or aw is None:
            continue
        h, a = m.get("home_team_id"), m.get("away_team_id")
        if h is None or a is None:
            continue

        rh, ra = get(h), get(a)
        exp_home = _expected((rh + HOME_ADV) - ra)

        if hs > aw:
            actual_home = 1.0
        elif hs < aw:
            actual_home = 0.0
        else:
            actual_home = 0.5

        delta = K * (actual_home - exp_home)
        ratings[h] = rh + delta
        ratings[a] = ra - delta

    return ratings


def predict_match(ratings: dict[int, float], home_id: int, away_id: int) -> dict:
    rh = ratings.get(home_id, DEFAULT_RATING)
    ra = ratings.get(away_id, DEFAULT_RATING)
    diff = (rh + HOME_ADV) - ra

    p_home = 1.0 / (1.0 + 10 ** (-(diff - DRAW_D) / DRAW_S))
    p_away = 1.0 / (1.0 + 10 ** ((diff + DRAW_D) / DRAW_S))

    if p_home + p_away > 1.0:
        # Ακραία σπάνια περίπτωση σε πολύ μεγάλη διαφορά rating -- κόβουμε
        # αναλογικά ώστε να μείνει έστω μια μικρή πιθανότητα ισοπαλίας.
        total = p_home + p_away
        p_home, p_away = p_home / total * 0.98, p_away / total * 0.98
    p_draw = 1.0 - p_home - p_away
    p_home, p_draw, p_away = calibrate_probabilities((p_home, p_draw, p_away))

    if p_home >= p_draw and p_home >= p_away:
        outcome = "H"
    elif p_away >= p_draw:
        outcome = "A"
    else:
        outcome = "D"

    return {
        "prob_home": p_home,
        "prob_draw": p_draw,
        "prob_away": p_away,
        "predicted_outcome": outcome,
        "rating_home": rh,
        "rating_away": ra,
        "calibration_version": 1,
    }
