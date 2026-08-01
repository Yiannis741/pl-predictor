# -*- coding: utf-8 -*-
"""Προσομοίωση (Monte Carlo) της υπόλοιπης σεζόν: παίρνει το ίδιο μοντέλο
Poisson που χρησιμοποιείται για τις προβλέψεις αγωνιστικής, και το τρέχει
χιλιάδες φορές πάνω σε όλους τους αγώνες που δεν έχουν παιχτεί ακόμα, ώστε
να βγουν πιθανότητες τίτλου / θέσης Champions League / υποβιβασμού για κάθε
ομάδα.

Γιατί έτσι: μια μεμονωμένη πρόβλεψη σκορ δεν λέει τίποτα για το πώς
"κλείνει" η σεζόν συνολικά. Προσομοιώνοντας τυχαία αποτελέσματα σύμφωνα με
τις ίδιες πιθανότητες Poisson, βλέπουμε σε πόσα από τα πιθανά "μέλλοντα"
κάθε ομάδα καταλήγει πρώτη, στην τετράδα, ή στην υποβιβαστική ζώνη.
"""

import numpy as np

from . import predictor

N_SIMULATIONS = 3000
TOP4 = 4  # προεπιλογή -- βλ. παράμετρο top_n παρακάτω για ρύθμιση ανά πρωτάθλημα
RELEGATION_SPOTS = 3  # προεπιλογή -- βλ. παράμετρο releg_n παρακάτω


def _simulation_seed(season: int, matches: list[dict]) -> int:
    """Σταθερό seed από τη σεζόν και τα IDs των αγώνων, ανεξάρτητο από Python hash."""
    seed = int(season) & 0xFFFFFFFF
    match_ids = sorted(int(m["id"]) for m in matches if m.get("id") is not None)
    for match_id in match_ids:
        seed = (seed * 1664525 + match_id + 1013904223) & 0xFFFFFFFF
    return seed


def _rank_teams(points: np.ndarray, gd: np.ndarray, gf: np.ndarray,
                rng: np.random.Generator | None = None,
                randomize_exact_ties: bool = True) -> np.ndarray:
    """Βαθμοί -> διαφορά -> γκολ, με δίκαιο τελευταίο κριτήριο στις πλήρεις ισοβαθμίες."""
    if randomize_exact_ties:
        if rng is None:
            raise ValueError("rng is required when exact ties are randomized")
        tie_break = rng.random(len(points))
    else:
        tie_break = np.arange(len(points))
    return np.lexsort((tie_break, -gf, -gd, -points))


def simulate_season(model: dict, all_matches: list[dict], season: int,
                     top_n: int = TOP4, releg_n: int = RELEGATION_SPOTS,
                     random_seed: int | None = None) -> dict[int, dict]:
    """all_matches: όλοι οι αγώνες της σεζόν (τελειωμένοι + προγραμματισμένοι).
    top_n/releg_n: μέγεθος της "κορυφαίας" και της "υποβιβαστικής" ζώνης --
    διαφέρει ανά πρωτάθλημα (βλ. src/competitions.py). Επιστρέφει
    team_id -> {"title_pct", "top4_pct", "relegation_pct"}."""

    finished = [m for m in all_matches if m.get("status") == "FINISHED"
                and m.get("home_score") is not None and m.get("away_score") is not None]
    remaining = [m for m in all_matches
                 if m.get("status") in ("SCHEDULED", "TIMED", "POSTPONED")
                 and m.get("home_team_id") and m.get("away_team_id")]

    teams = sorted({m["home_team_id"] for m in all_matches} | {m["away_team_id"] for m in all_matches})
    if not teams:
        return {}
    idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)

    # Βαθμοί/γκολ ήδη κερδισμένα από τους πραγματικούς αγώνες.
    base_points = np.zeros(n_teams)
    base_gd = np.zeros(n_teams)
    base_gf = np.zeros(n_teams)
    for m in finished:
        h, a = idx[m["home_team_id"]], idx[m["away_team_id"]]
        hs, aw = m["home_score"], m["away_score"]
        base_gf[h] += hs
        base_gf[a] += aw
        base_gd[h] += hs - aw
        base_gd[a] += aw - hs
        if hs > aw:
            base_points[h] += 3
        elif hs < aw:
            base_points[a] += 3
        else:
            base_points[h] += 1
            base_points[a] += 1

    if not remaining:
        # Η σεζόν έχει ήδη τελειώσει· ο πίνακας είναι οριστικός, καμία τυχαιότητα.
        n_sim = 1
        home_idx = np.array([], dtype=int)
        away_idx = np.array([], dtype=int)
        lam_home = np.array([])
        lam_away = np.array([])
    else:
        n_sim = N_SIMULATIONS
        home_idx = np.array([idx[m["home_team_id"]] for m in remaining])
        away_idx = np.array([idx[m["away_team_id"]] for m in remaining])
        lams = [predictor.expected_goals(model, m["home_team_id"], m["away_team_id"])
                for m in remaining]
        lam_home = np.array([lh for lh, _ in lams])
        lam_away = np.array([la for _, la in lams])

    title = np.zeros(n_teams, dtype=int)
    top4 = np.zeros(n_teams, dtype=int)
    releg = np.zeros(n_teams, dtype=int)

    seed = _simulation_seed(season, all_matches) if random_seed is None else random_seed
    rng = np.random.default_rng(seed)

    if len(lam_home) > 0:
        sim_home_goals = rng.poisson(lam_home, size=(n_sim, len(lam_home)))
        sim_away_goals = rng.poisson(lam_away, size=(n_sim, len(lam_away)))
    else:
        sim_home_goals = np.zeros((n_sim, 0), dtype=int)
        sim_away_goals = np.zeros((n_sim, 0), dtype=int)

    for s in range(n_sim):
        points = base_points.copy()
        gd = base_gd.copy()
        gf = base_gf.copy()

        if len(home_idx) > 0:
            hg, ag = sim_home_goals[s], sim_away_goals[s]
            home_pts = np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
            away_pts = np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
            np.add.at(points, home_idx, home_pts)
            np.add.at(points, away_idx, away_pts)
            np.add.at(gd, home_idx, hg - ag)
            np.add.at(gd, away_idx, ag - hg)
            np.add.at(gf, home_idx, hg)
            np.add.at(gf, away_idx, ag)

        # Σε ενεργή προσομοίωση η πλήρης ισοβαθμία λύνεται τυχαία, ώστε να μην
        # ευνοούνται συστηματικά τα μικρότερα team IDs. Σε τελειωμένη σεζόν
        # κρατάμε ντετερμινιστική σειρά, αφού δεν προσομοιώνεται κανένα μέλλον.
        order = _rank_teams(
            points, gd, gf, rng=rng, randomize_exact_ties=bool(remaining)
        )

        champion = order[0]
        title[champion] += 1
        for pos_i in order[:top_n]:
            top4[pos_i] += 1
        for pos_i in order[-releg_n:]:
            releg[pos_i] += 1

    out = {}
    for t in teams:
        i = idx[t]
        out[t] = {
            "title_pct": title[i] / n_sim * 100,
            "top4_pct": top4[i] / n_sim * 100,
            "relegation_pct": releg[i] / n_sim * 100,
        }
    return out
