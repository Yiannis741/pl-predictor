# -*- coding: utf-8 -*-
"""Λεπτός client για το API του football-data.org (v4), μόνο για ό,τι
χρειαζόμαστε: αγώνες Premier League. Κρατάει απλό rate-limiting ώστε να μη
σκάσουμε το όριο του δωρεάν πλάνου (10 αιτήματα/λεπτό)."""

import time
import requests

from . import config

BASE_URL = "https://api.football-data.org/v4"


class FootballDataClient:
    def __init__(self, token: str | None = None, min_gap: float = 6.5):
        self.token = token or config.require_token()
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": self.token})
        self._last_call = 0.0
        self._min_gap = min_gap  # δευτερόλεπτα ανάμεσα σε αιτήματα

    def _get(self, path: str, params: dict | None = None) -> dict:
        wait = self._min_gap - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)

        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=30)
        self._last_call = time.time()

        if resp.status_code == 429:
            # Ξεπεράσαμε το όριο αιτημάτων· περιμένουμε όσο λέει το API και
            # ξαναδοκιμάζουμε ακριβώς μία φορά.
            retry_after = int(resp.headers.get("Retry-After", 60))
            time.sleep(retry_after + 1)
            resp = self.session.get(url, params=params, timeout=30)
            self._last_call = time.time()

        resp.raise_for_status()
        return resp.json()

    def get_matches(self, competition: str = "PL", season: int | None = None,
                     matchday: int | None = None, status: str | None = None) -> list[dict]:
        params: dict = {}
        if season is not None:
            params["season"] = season
        if matchday is not None:
            params["matchday"] = matchday
        if status is not None:
            params["status"] = status
        data = self._get(f"/competitions/{competition}/matches", params=params)
        return data.get("matches", [])

    def get_standings(self, competition: str = "PL", season: int | None = None) -> dict:
        params: dict = {}
        if season is not None:
            params["season"] = season
        return self._get(f"/competitions/{competition}/standings", params=params)
