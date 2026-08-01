# -*- coding: utf-8 -*-
"""Αποθήκευση σε SQLite: ομάδες, αγώνες (τελειωμένοι + προγραμματισμένοι) και
οι προβλέψεις που παράγουμε γι' αυτούς -- για ΟΛΑ τα πρωταθλήματα που
καλύπτει το πρόγραμμα (μία κοινή βάση, ξεχωρίζουν με τη στήλη
matches.competition)."""

import math
import sqlite3
from contextlib import contextmanager

from . import config, elo

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT,
    tla TEXT,
    crest TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    competition TEXT NOT NULL DEFAULT 'PL',
    season INTEGER NOT NULL,
    matchday INTEGER,
    utc_date TEXT,
    status TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    winner TEXT
);

-- Μία γραμμή ΑΝΑ (αγώνας, μοντέλο) -- έτσι μπορούν να συνυπάρχουν οι
-- προβλέψεις Poisson, Elo και Αγοράς για τον ίδιο αγώνα, για σύγκριση. Το
-- match_id είναι global unique (football-data.org), οπότε δεν χρειάζεται
-- competition εδώ -- ήδη ξεχωρίζει μέσω του matches.competition με JOIN.
CREATE TABLE IF NOT EXISTS predictions (
    match_id INTEGER NOT NULL,
    model TEXT NOT NULL,
    predicted_home_score REAL,
    predicted_away_score REAL,
    prob_home REAL,
    prob_draw REAL,
    prob_away REAL,
    rating_home REAL,
    rating_away REAL,
    calibration_version INTEGER NOT NULL DEFAULT 0,
    generated_at TEXT,
    PRIMARY KEY (match_id, model)
);
"""


@contextmanager
def connect():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn) -> None:
    """Παλιές βάσεις (πριν το multi-league) δεν έχουν τη στήλη
    'competition' -- προσθέτουμε την με DEFAULT 'PL', ώστε όλα τα ήδη
    αποθηκευμένα δεδομένα (που ήταν πάντα Premier League) να παραμείνουν
    σωστά χωρίς να χρειαστεί rebuild."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(matches)").fetchall()]
    if "competition" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN competition TEXT NOT NULL DEFAULT 'PL'")
    prediction_cols = [
        r["name"] for r in conn.execute("PRAGMA table_info(predictions)").fetchall()
    ]
    if "calibration_version" not in prediction_cols:
        conn.execute(
            "ALTER TABLE predictions ADD COLUMN calibration_version INTEGER NOT NULL DEFAULT 0"
        )


def _calibrated_probabilities(row, model: str) -> tuple[float, float, float] | None:
    values = (row["prob_home"], row["prob_draw"], row["prob_away"])
    if any(value is None for value in values):
        return None
    probabilities = tuple(float(value) for value in values)
    version = row["calibration_version"] if "calibration_version" in row.keys() else 0
    if model == "elo" and not version:
        return elo.calibrate_probabilities(probabilities)
    total = sum(probabilities)
    if total <= 0:
        return None
    return tuple(max(value / total, 1e-12) for value in probabilities)


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _upsert_team(conn, team: dict | None) -> None:
    if not team or not team.get("id"):
        return
    conn.execute(
        """INSERT INTO teams (id, name, short_name, tla, crest)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             name=excluded.name, short_name=excluded.short_name,
             tla=excluded.tla, crest=excluded.crest""",
        (team["id"], team.get("name"), team.get("shortName"),
         team.get("tla"), team.get("crest")),
    )


def _upsert_match(conn, match: dict, season: int, competition: str) -> None:
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    _upsert_team(conn, home)
    _upsert_team(conn, away)
    score = (match.get("score") or {}).get("fullTime") or {}
    conn.execute(
        """INSERT INTO matches (id, competition, season, matchday, utc_date, status,
               home_team_id, away_team_id, home_score, away_score, winner)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             competition=excluded.competition, season=excluded.season,
             matchday=excluded.matchday, utc_date=excluded.utc_date, status=excluded.status,
             home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,
             home_score=excluded.home_score, away_score=excluded.away_score,
             winner=excluded.winner""",
        (match["id"], competition, season, match.get("matchday"), match.get("utcDate"),
         match.get("status"), home.get("id"), away.get("id"),
         score.get("home"), score.get("away"),
         (match.get("score") or {}).get("winner")),
    )


def save_matches(matches: list[dict], season: int, competition: str = "PL") -> None:
    with connect() as conn:
        for m in matches:
            _upsert_match(conn, m, season, competition)


def finished_matches(season: int, competition: str = "PL") -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND competition=? AND status='FINISHED' "
            "AND home_score IS NOT NULL AND away_score IS NOT NULL",
            (season, competition),
        ).fetchall()
        return [dict(r) for r in rows]


def next_matchday_fixtures(season: int, competition: str = "PL") -> tuple[int | None, list[dict]]:
    """Η πρώτη αγωνιστική της σεζόν που έχει έστω έναν αγώνα που δεν έχει
    τελειώσει ακόμα (SCHEDULED/TIMED)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT MIN(matchday) AS md FROM matches "
            "WHERE season=? AND competition=? AND status IN ('SCHEDULED','TIMED')",
            (season, competition),
        ).fetchone()
        md = row["md"] if row else None
        if md is None:
            return None, []
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND competition=? AND matchday=? ORDER BY utc_date",
            (season, competition, md),
        ).fetchall()
        return md, [dict(r) for r in rows]


def distinct_matchdays(season: int, competition: str = "PL") -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT matchday FROM matches WHERE season=? AND competition=? "
            "AND matchday IS NOT NULL ORDER BY matchday", (season, competition),
        ).fetchall()
        return [r["matchday"] for r in rows]


def matchday_matches(season: int, matchday: int, competition: str = "PL") -> list[dict]:
    """Οι αγώνες μιας συγκεκριμένης αγωνιστικής, ανεξαρτήτως status —
    χρησιμοποιείται στο backtest, όπου όλοι είναι ήδη FINISHED."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND competition=? AND matchday=? ORDER BY utc_date",
            (season, competition, matchday),
        ).fetchall()
        return [dict(r) for r in rows]


def finished_matches_before(seasons: list[int], cutoff_iso: str, competition: str = "PL") -> list[dict]:
    """Τελειωμένοι αγώνες από μία ή περισσότερες σεζόν ΤΟΥ ΙΔΙΟΥ
    πρωταθλήματος, με ημερομηνία πριν από το cutoff — για να χτίζουμε το
    μοντέλο σε ένα backtest χωρίς να "βλέπουμε το μέλλον" (data leakage)."""
    if not seasons:
        return []
    placeholders = ",".join("?" for _ in seasons)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM matches WHERE season IN ({placeholders}) AND competition=? "
            f"AND status='FINISHED' AND home_score IS NOT NULL "
            f"AND away_score IS NOT NULL AND utc_date < ? ORDER BY utc_date",
            (*seasons, competition, cutoff_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def team_names() -> dict[int, dict]:
    """Global -- τα team_id είναι μοναδικά σε όλο το football-data.org,
    ανεξαρτήτως πρωταθλήματος."""
    with connect() as conn:
        rows = conn.execute("SELECT id, name, crest FROM teams").fetchall()
        return {r["id"]: dict(r) for r in rows}


def season_matches(season: int, competition: str = "PL") -> list[dict]:
    """Όλοι οι αγώνες της σεζόν (τελειωμένοι + προγραμματισμένοι), για την
    προσομοίωση τελικής βαθμολογίας."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND competition=? ORDER BY utc_date",
            (season, competition),
        ).fetchall()
        return [dict(r) for r in rows]


def standings_and_form(season: int, competition: str = "PL", form_length: int = 5) -> list[dict]:
    """Πίνακας βαθμολογίας υπολογισμένος από τους τελειωμένους αγώνες της
    σεζόν (χωρίς να καλούμε ξανά το API), μαζί με τα τελευταία αποτελέσματα
    κάθε ομάδας (φόρμα). Ταξινόμηση: βαθμοί -> διαφορά τερμάτων -> γκολ υπέρ
    (χωρίς head-to-head, μικρή απλοποίηση σε σχέση με τον επίσημο κανονισμό)."""
    matches = finished_matches(season, competition)
    names = team_names()

    table: dict[int, dict] = {}
    history: dict[int, list] = {}

    def row(team_id):
        if team_id not in table:
            table[team_id] = {
                "team_id": team_id,
                "name": names.get(team_id, {}).get("name", f"Team {team_id}"),
                "played": 0, "won": 0, "draw": 0, "lost": 0,
                "gf": 0, "ga": 0, "points": 0,
            }
            history[team_id] = []
        return table[team_id]

    matches_sorted = sorted(matches, key=lambda m: m.get("utc_date") or "")
    for m in matches_sorted:
        h, a = m["home_team_id"], m["away_team_id"]
        hs, aw = m["home_score"], m["away_score"]
        if h is None or a is None:
            continue
        rh, ra = row(h), row(a)
        rh["played"] += 1
        ra["played"] += 1
        rh["gf"] += hs
        rh["ga"] += aw
        ra["gf"] += aw
        ra["ga"] += hs
        if hs > aw:
            rh["won"] += 1
            ra["lost"] += 1
            rh["points"] += 3
            history[h].append("W")
            history[a].append("L")
        elif hs < aw:
            ra["won"] += 1
            rh["lost"] += 1
            ra["points"] += 3
            history[h].append("L")
            history[a].append("W")
        else:
            rh["draw"] += 1
            ra["draw"] += 1
            rh["points"] += 1
            ra["points"] += 1
            history[h].append("D")
            history[a].append("D")

    result = []
    for team_id, r in table.items():
        r = dict(r)
        r["gd"] = r["gf"] - r["ga"]
        r["form"] = history[team_id][-form_length:][::-1]  # πιο πρόσφατο πρώτο
        result.append(r)

    result.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"]))
    for i, r in enumerate(result, start=1):
        r["position"] = i
    return result


def accuracy_stats(season: int, model: str = "poisson", competition: str = "PL") -> dict:
    """Πόσο συχνά η πρόβλεψή μας (πριν τον αγώνα) πέτυχε το σωστό
    αποτέλεσμα (1/Χ/2) ή το ακριβές σκορ, στους αγώνες της σεζόν που έχουν
    ήδη τελειώσει, για το δοσμένο μοντέλο ("poisson"/"elo"/"market").

    ΣΗΜΑΝΤΙΚΟ: η "σωστή πρόβλεψη" 1/Χ/2 κρίνεται από ποια από τις τρεις
    αθροισμένες πιθανότητες (prob_home/prob_draw/prob_away) ήταν η
    μεγαλύτερη — ΟΧΙ από το αν το πιο πιθανό μεμονωμένο ΑΚΡΙΒΕΣ σκορ
    συνέπιπτε τυχαία με το αποτέλεσμα."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.home_score, m.away_score,
                      p.predicted_home_score, p.predicted_away_score,
                      p.prob_home, p.prob_draw, p.prob_away,
                      p.calibration_version
               FROM matches m JOIN predictions p ON p.match_id = m.id
               WHERE m.season=? AND m.competition=? AND p.model=? AND m.status='FINISHED'
                 AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL""",
            (season, competition, model),
        ).fetchall()

    total = len(rows)
    correct_result = 0
    exact_score = 0
    exact_eligible = 0
    log_loss = 0.0
    brier_score = 0.0
    probability_eligible = 0
    for r in rows:
        actual = "H" if r["home_score"] > r["away_score"] else (
            "A" if r["home_score"] < r["away_score"] else "D")

        probabilities = _calibrated_probabilities(r, model)
        if probabilities is None:
            continue
        ph, pd, pa = probabilities
        actual_index = {"H": 0, "D": 1, "A": 2}[actual]
        log_loss -= math.log(probabilities[actual_index])
        brier_score += sum(
            (probability - (1.0 if index == actual_index else 0.0)) ** 2
            for index, probability in enumerate(probabilities)
        )
        probability_eligible += 1
        if ph >= pd and ph >= pa:
            predicted = "H"
        elif pa >= pd:
            predicted = "A"
        else:
            predicted = "D"

        if actual == predicted:
            correct_result += 1
        if r["predicted_home_score"] is not None:
            exact_eligible += 1
            if (r["home_score"] == r["predicted_home_score"]
                    and r["away_score"] == r["predicted_away_score"]):
                exact_score += 1

    return {
        "total": total,
        "correct_result": correct_result,
        "exact_score": exact_score,
        "result_pct": (correct_result / total * 100) if total else None,
        "log_loss": (log_loss / probability_eligible) if probability_eligible else None,
        "brier_score": (brier_score / probability_eligible) if probability_eligible else None,
        # Το Elo/η Αγορά δεν προβλέπουν ακριβές σκορ (predicted_home_score=NULL)
        # -- None σημαίνει "δεν εφαρμόζεται", διαφορετικό από 0%.
        "exact_pct": (exact_score / exact_eligible * 100) if exact_eligible else None,
    }


def team_accuracy(season: int, model: str = "poisson", competition: str = "PL") -> dict[int, dict]:
    """Ποσοστό επιτυχίας του μοντέλου (σωστό 1/Χ/2) στους αγώνες κάθε
    ομάδας -- πιστώνεται και στις δύο ομάδες ενός αγώνα το ίδιο
    σωστό/λάθος, αφού η πρόβλεψη αφορά τον αγώνα συνολικά."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.home_team_id, m.away_team_id, m.home_score, m.away_score,
                      p.prob_home, p.prob_draw, p.prob_away,
                      p.calibration_version
               FROM matches m JOIN predictions p ON p.match_id = m.id
               WHERE m.season=? AND m.competition=? AND p.model=? AND m.status='FINISHED'
                 AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL""",
            (season, competition, model),
        ).fetchall()

    stats: dict[int, list[int]] = {}  # team_id -> [σωστές, σύνολο]
    for r in rows:
        actual = "H" if r["home_score"] > r["away_score"] else (
            "A" if r["home_score"] < r["away_score"] else "D")
        probabilities = _calibrated_probabilities(r, model)
        if probabilities is None:
            continue
        ph, pd, pa = probabilities
        if ph >= pd and ph >= pa:
            predicted = "H"
        elif pa >= pd:
            predicted = "A"
        else:
            predicted = "D"
        hit = 1 if predicted == actual else 0

        for team_id in (r["home_team_id"], r["away_team_id"]):
            s = stats.setdefault(team_id, [0, 0])
            s[1] += 1
            s[0] += hit

    return {tid: {"correct": c, "total": t, "pct": (c / t * 100 if t else None)}
            for tid, (c, t) in stats.items()}


def predictions_for_season(season: int, model: str = "poisson", competition: str = "PL") -> dict[int, dict]:
    """Όλες οι αποθηκευμένες προβλέψεις της σεζόν για ΕΝΑ μοντέλο, keyed by
    match_id -- για την αναλυτική σελίδα αποτελεσμάτων (όχι μόνο η επόμενη
    αγωνιστική)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT p.* FROM predictions p
               JOIN matches m ON m.id = p.match_id
               WHERE m.season=? AND m.competition=? AND p.model=?""",
            (season, competition, model),
        ).fetchall()
        predictions = {}
        for row in rows:
            prediction = dict(row)
            probabilities = _calibrated_probabilities(row, model)
            if probabilities is not None:
                (prediction["prob_home"], prediction["prob_draw"],
                 prediction["prob_away"]) = probabilities
            predictions[row["match_id"]] = prediction
        return predictions


def all_predictions_with_results(model: str = "poisson") -> list[dict]:
    """Όλες οι προβλέψεις ΕΝΟΣ μοντέλου με το πραγματικό αποτέλεσμα, σε ΟΛΑ
    τα πρωταθλήματα και τις σεζόν που έχουμε στη βάση -- για το calibration
    check (πόσο "καλά βαθμονομημένες" είναι οι πιθανότητες συνολικά)."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.competition, m.season, m.home_score, m.away_score,
                      p.prob_home, p.prob_draw, p.prob_away,
                      p.calibration_version
               FROM matches m JOIN predictions p ON p.match_id = m.id
               WHERE p.model=? AND m.status='FINISHED'
                 AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL""",
            (model,),
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            probabilities = _calibrated_probabilities(row, model)
            if probabilities is not None:
                result["prob_home"], result["prob_draw"], result["prob_away"] = probabilities
            results.append(result)
        return results


def save_predictions(preds: list[dict]) -> None:
    """Κάθε dict στο preds πρέπει να έχει "match_id" και "model"
    ("poisson"/"elo"/"market"). Το predicted_home_score/away_score είναι
    προαιρετικά (μόνο το Poisson προβλέπει σκορ)."""
    with connect() as conn:
        for p in preds:
            conn.execute(
                """INSERT INTO predictions (match_id, model, predicted_home_score,
                       predicted_away_score, prob_home, prob_draw, prob_away,
                       rating_home, rating_away, calibration_version, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(match_id, model) DO UPDATE SET
                     predicted_home_score=excluded.predicted_home_score,
                     predicted_away_score=excluded.predicted_away_score,
                     prob_home=excluded.prob_home, prob_draw=excluded.prob_draw,
                      prob_away=excluded.prob_away, rating_home=excluded.rating_home,
                      rating_away=excluded.rating_away,
                      calibration_version=excluded.calibration_version,
                      generated_at=excluded.generated_at""",
                (p["match_id"], p.get("model", "poisson"),
                 p.get("predicted_home_score"), p.get("predicted_away_score"),
                  p["prob_home"], p["prob_draw"], p["prob_away"],
                  p.get("rating_home"), p.get("rating_away"),
                  p.get("calibration_version", 0)),
            )
