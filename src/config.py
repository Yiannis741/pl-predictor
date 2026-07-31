# -*- coding: utf-8 -*-
"""Ρυθμίσεις project: διαβάζει το .env (χωρίς εξωτερική εξάρτηση) και εκθέτει
σταθερές που χρησιμοποιούν τα υπόλοιπα modules."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")

FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
COMPETITION_CODE = "PL"  # Premier League στο football-data.org

DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "pl_predictor.db"
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"


def require_token() -> str:
    if not FOOTBALL_DATA_TOKEN:
        raise RuntimeError(
            "Δεν βρέθηκε FOOTBALL_DATA_TOKEN. Αντίγραψε το .env.example σε .env "
            "και βάλε εκεί το token σου από το football-data.org."
        )
    return FOOTBALL_DATA_TOKEN
