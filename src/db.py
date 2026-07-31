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


def team_names() -> dict[int, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, crest FROM teams").fetchall()
        return {r["id"]: dict(r) for r in rows}


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
