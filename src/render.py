# -*- coding: utf-8 -*-
"""Παράγει το output/index.html: πίνακας με την επόμενη αγωνιστική, τις
προβλέψεις σκορ και τις πιθανότητες 1-Χ-2."""

import datetime

from . import config, db


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _fmt_date(iso_str: str | None) -> str:
    """Μετατρέπει π.χ. '2026-08-21T19:00:00Z' σε '21/08/2026 19:00'."""
    if not iso_str:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso_str


def render_report(season: int, matchday: int | None, fixtures: list[dict],
                   preds: list[dict]) -> str:
    teams = db.team_names()
    preds_by_match = {p["match_id"]: p for p in preds}

    rows_html = []
    for m in fixtures:
        home = teams.get(m["home_team_id"], {}).get("name", "?")
        away = teams.get(m["away_team_id"], {}).get("name", "?")
        p = preds_by_match.get(m["id"])
        date = _fmt_date(m.get("utc_date"))
        if p:
            score = f'{p["predicted_home_score"]}-{p["predicted_away_score"]}'
            probs = (f'{_fmt_pct(p["prob_home"])} / {_fmt_pct(p["prob_draw"])} / '
                     f'{_fmt_pct(p["prob_away"])}')
        else:
            score, probs = "-", "-"
        rows_html.append(f"""
        <tr>
          <td>{date}</td>
          <td class="team">{home}</td>
          <td class="score">{score}</td>
          <td class="team">{away}</td>
          <td class="probs">{probs}</td>
        </tr>""")

    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    md_label = f"Αγωνιστική {matchday}" if matchday else "Δεν υπάρχει προγραμματισμένη αγωνιστική"
    body_rows = "".join(rows_html) if rows_html else (
        '<tr><td colspan="5">Καμία επερχόμενη αγωνιστική βρέθηκε.</td></tr>')

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PL Predictor &middot; {md_label}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#0d1b2a;
          color:#e0e6ed; margin:0; padding:2rem; }}
  h1 {{ color:#fff; margin-bottom:0.2rem; }}
  .meta {{ color:#9db4c0; margin-bottom:1.5rem; }}
  table {{ width:100%; border-collapse:collapse; background:#132a3e; border-radius:8px;
           overflow:hidden; }}
  th, td {{ padding:0.7rem 1rem; text-align:center; }}
  th {{ background:#1c3a52; color:#9db4c0; font-weight:600; text-transform:uppercase;
        font-size:0.8rem; letter-spacing:0.03em; }}
  tr:nth-child(even) {{ background:#0f2436; }}
  .team {{ font-weight:600; color:#fff; }}
  .score {{ font-size:1.2rem; font-weight:700; color:#4ade80; }}
  .probs {{ color:#9db4c0; font-size:0.9rem; }}
  footer {{ margin-top:2rem; color:#5c7182; font-size:0.8rem; }}
</style>
</head>
<body>
  <h1>Premier League &mdash; Προβλέψεις</h1>
  <div class="meta">Σεζόν {season}-{season + 1} &middot; {md_label} &middot;
    ενημερώθηκε {generated}</div>
  <table>
    <thead>
      <tr><th>Ημ/νία (UTC)</th><th>Γηπεδούχος</th><th>Πρόβλεψη</th>
          <th>Φιλοξενούμενος</th><th>1 / Χ / 2</th></tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
  <footer>Δεδομένα: football-data.org &middot; Μοντέλο: Poisson (επιθετική/αμυντική
    δύναμη ομάδων, με μεγαλύτερο βάρος στην πρόσφατη φόρμα)</footer>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)
