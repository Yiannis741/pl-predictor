# -*- coding: utf-8 -*-
"""Αποθήκευση σε SQLite: ομάδες, αγώνες (τελειωμένοι + προγραμματισμένοι) και
οι προβλέψεις που παράγουμε γι' αυτούς."""

import sqlite3
from contextlib import contextmanager

from . import config

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

CREATE TABLE IF NOT EXISTS predictions (
    match_id INTEGER PRIMARY KEY,
    predicted_home_score REAL,
    predicted_away_score REAL,
    prob_home REAL,
    prob_draw REAL,
    prob_away REAL,
    model TEXT,
    generated_at TEXT
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


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


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


def _upsert_match(conn, match: dict, season: int) -> None:
    home = match.get("homeTeam") or {}
    away = match.get("awayTeam") or {}
    _upsert_team(conn, home)
    _upsert_team(conn, away)
    score = (match.get("score") or {}).get("fullTime") or {}
    conn.execute(
        """INSERT INTO matches (id, season, matchday, utc_date, status,
               home_team_id, away_team_id, home_score, away_score, winner)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             season=excluded.season, matchday=excluded.matchday,
             utc_date=excluded.utc_date, status=excluded.status,
             home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,
             home_score=excluded.home_score, away_score=excluded.away_score,
             winner=excluded.winner""",
        (match["id"], season, match.get("matchday"), match.get("utcDate"),
         match.get("status"), home.get("id"), away.get("id"),
         score.get("home"), score.get("away"),
         (match.get("score") or {}).get("winner")),
    )


def save_matches(matches: list[dict], season: int) -> None:
    with connect() as conn:
        for m in matches:
            _upsert_match(conn, m, season)


def finished_matches(season: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND status='FINISHED' "
            "AND home_score IS NOT NULL AND away_score IS NOT NULL",
            (season,),
        ).fetchall()
        return [dict(r) for r in rows]


def next_matchday_fixtures(season: int) -> tuple[int | None, list[dict]]:
    """Η πρώτη αγωνιστική της σεζόν που έχει έστω έναν αγώνα που δεν έχει
    τελειώσει ακόμα (SCHEDULED/TIMED)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT MIN(matchday) AS md FROM matches "
            "WHERE season=? AND status IN ('SCHEDULED','TIMED')",
            (season,),
        ).fetchone()
        md = row["md"] if row else None
        if md is None:
            return None, []
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND matchday=? ORDER BY utc_date",
            (season, md),
        ).fetchall()
        return md, [dict(r) for r in rows]


def distinct_matchdays(season: int) -> list[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT matchday FROM matches WHERE season=? "
            "AND matchday IS NOT NULL ORDER BY matchday", (season,),
        ).fetchall()
        return [r["matchday"] for r in rows]


def matchday_matches(season: int, matchday: int) -> list[dict]:
    """Οι αγώνες μιας συγκεκριμένης αγωνιστικής, ανεξαρτήτως status —
    χρησιμοποιείται στο backtest, όπου όλοι είναι ήδη FINISHED."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? AND matchday=? ORDER BY utc_date",
            (season, matchday),
        ).fetchall()
        return [dict(r) for r in rows]


def finished_matches_before(seasons: list[int], cutoff_iso: str) -> list[dict]:
    """Τελειωμένοι αγώνες από μία ή περισσότερες σεζόν, με ημερομηνία πριν
    από το cutoff — για να χτίζουμε το μοντέλο σε ένα backtest χωρίς να
    "βλέπουμε το μέλλον" (data leakage)."""
    if not seasons:
        return []
    placeholders = ",".join("?" for _ in seasons)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM matches WHERE season IN ({placeholders}) "
            f"AND status='FINISHED' AND home_score IS NOT NULL "
            f"AND away_score IS NOT NULL AND utc_date < ? ORDER BY utc_date",
            (*seasons, cutoff_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def team_names() -> dict[int, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, crest FROM teams").fetchall()
        return {r["id"]: dict(r) for r in rows}


def season_matches(season: int) -> list[dict]:
    """Όλοι οι αγώνες της σεζόν (τελειωμένοι + προγραμματισμένοι), για την
    προσομοίωση τελικής βαθμολογίας."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM matches WHERE season=? ORDER BY utc_date", (season,),
        ).fetchall()
        return [dict(r) for r in rows]


def standings_and_form(season: int, form_length: int = 5) -> list[dict]:
    """Πίνακας βαθμολογίας υπολογισμένος από τους τελειωμένους αγώνες της
    σεζόν (χωρίς να καλούμε ξανά το API), μαζί με τα τελευταία αποτελέσματα
    κάθε ομάδας (φόρμα). Ταξινόμηση: βαθμοί -> διαφορά τερμάτων -> γκολ υπέρ
    (χωρίς head-to-head, μικρή απλοποίηση σε σχέση με τον επίσημο κανονισμό)."""
    matches = finished_matches(season)
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


def accuracy_stats(season: int) -> dict:
    """Πόσο συχνά η πρόβλεψή μας (πριν τον αγώνα) πέτυχε το σωστό
    αποτέλεσμα (1/Χ/2) ή το ακριβές σκορ, στους αγώνες της σεζόν που έχουν
    ήδη τελειώσει."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT m.home_score, m.away_score,
                      p.predicted_home_score, p.predicted_away_score
               FROM matches m JOIN predictions p ON p.match_id = m.id
               WHERE m.season=? AND m.status='FINISHED'
                 AND m.home_score IS NOT NULL AND m.away_score IS NOT NULL""",
            (season,),
        ).fetchall()

    total = len(rows)
    correct_result = 0
    exact_score = 0
    for r in rows:
        actual = "H" if r["home_score"] > r["away_score"] else (
            "A" if r["home_score"] < r["away_score"] else "D")
        predicted = "H" if r["predicted_home_score"] > r["predicted_away_score"] else (
            "A" if r["predicted_home_score"] < r["predicted_away_score"] else "D")
        if actual == predicted:
            correct_result += 1
        if (r["home_score"] == r["predicted_home_score"]
                and r["away_score"] == r["predicted_away_score"]):
            exact_score += 1

    return {
        "total": total,
        "correct_result": correct_result,
        "exact_score": exact_score,
        "result_pct": (correct_result / total * 100) if total else None,
        "exact_pct": (exact_score / total * 100) if total else None,
    }


def save_predictions(preds: list[dict]) -> None:
    with connect() as conn:
        for p in preds:
            conn.execute(
                """INSERT INTO predictions (match_id, predicted_home_score,
                       predicted_away_score, prob_home, prob_draw, prob_away,
                       model, generated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(match_id) DO UPDATE SET
                     predicted_home_score=excluded.predicted_home_score,
                     predicted_away_score=excluded.predicted_away_score,
                     prob_home=excluded.prob_home, prob_draw=excluded.prob_draw,
                     prob_away=excluded.prob_away, model=excluded.model,
                     generated_at=excluded.generated_at""",
                (p["match_id"], p["predicted_home_score"], p["predicted_away_score"],
                 p["prob_home"], p["prob_draw"], p["prob_away"], p.get("model", "poisson")),
            )
