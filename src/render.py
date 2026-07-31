# -*- coding: utf-8 -*-
"""Παράγει το output/index.html: προβλέψεις επόμενης αγωνιστικής, ακρίβεια
προηγούμενων προβλέψεων, βαθμολογία/φόρμα, και προσομοίωση τελικής θέσης."""

import datetime

from . import config, db

FORM_LABELS = {"W": "Ν", "D": "Ι", "L": "Η"}  # Νίκη / Ισοπαλία / Ήττα


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x:.0f}%"


def _fmt_date(iso_str: str | None) -> str:
    """Μετατρέπει π.χ. '2026-08-21T19:00:00Z' σε '21/08/2026 19:00'."""
    if not iso_str:
        return "-"
    try:
        dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso_str


def _fixtures_table(fixtures: list[dict], preds_by_match: dict, teams: dict) -> str:
    rows_html = []
    for m in fixtures:
        home = teams.get(m["home_team_id"], {}).get("name", "?")
        away = teams.get(m["away_team_id"], {}).get("name", "?")
        p = preds_by_match.get(m["id"])
        date = _fmt_date(m.get("utc_date"))
        if p:
            score = f'{p["predicted_home_score"]}-{p["predicted_away_score"]}'
            probs = (f'{_fmt_pct(p["prob_home"] * 100)} / {_fmt_pct(p["prob_draw"] * 100)} / '
                     f'{_fmt_pct(p["prob_away"] * 100)}')
            xg = f'{p["lambda_home"]:.1f} &ndash; {p["lambda_away"]:.1f}'
        else:
            score, probs, xg = "-", "-", "-"
        rows_html.append(f"""
        <tr>
          <td>{date}</td>
          <td class="team">{home}</td>
          <td class="score">{score}</td>
          <td class="team">{away}</td>
          <td class="xg">{xg}</td>
          <td class="probs">{probs}</td>
        </tr>""")
    return "".join(rows_html) if rows_html else (
        '<tr><td colspan="6">Καμία επερχόμενη αγωνιστική βρέθηκε.</td></tr>')


def _accuracy_html(accuracy: dict | None) -> str:
    if not accuracy or not accuracy.get("total"):
        return ('<div class="accuracy">Ακρίβεια μοντέλου: δεν υπάρχουν ακόμα '
                'τελειωμένοι αγώνες φέτος για αξιολόγηση.</div>')
    return (f'<div class="accuracy">Ακρίβεια μοντέλου φέτος (σε {accuracy["total"]} '
            f'αγώνες): <b>{_fmt_pct(accuracy["result_pct"])}</b> σωστό αποτέλεσμα '
            f'(1/Χ/2) &middot; <b>{_fmt_pct(accuracy["exact_pct"])}</b> ακριβές σκορ</div>')


def _standings_table(table: list[dict], sim: dict) -> str:
    if not table:
        return ('<tr><td colspan="13">Δεν υπάρχουν ακόμα τελειωμένοι αγώνες φέτος '
                'για βαθμολογία.</td></tr>')
    rows = []
    for r in table:
        form_badges = "".join(
            f'<span class="badge badge-{f}">{FORM_LABELS.get(f, "?")}</span>'
            for f in r["form"]
        ) or "-"
        s = sim.get(r["team_id"], {})
        row_class = ""
        if r["position"] <= 4:
            row_class = "zone-top4"
        elif r["position"] >= len(table) - 2:
            row_class = "zone-releg"
        rows.append(f"""
        <tr class="{row_class}">
          <td>{r["position"]}</td>
          <td class="team">{r["name"]}</td>
          <td>{r["played"]}</td>
          <td>{r["won"]}</td>
          <td>{r["draw"]}</td>
          <td>{r["lost"]}</td>
          <td>{r["gf"]}</td>
          <td>{r["ga"]}</td>
          <td>{r["gd"]:+d}</td>
          <td class="points">{r["points"]}</td>
          <td>{form_badges}</td>
          <td>{_fmt_pct(s.get("title_pct"))}</td>
          <td>{_fmt_pct(s.get("top4_pct"))}</td>
          <td>{_fmt_pct(s.get("relegation_pct"))}</td>
        </tr>""")
    return "".join(rows)


def render_report(season: int, matchday: int | None, fixtures: list[dict],
                   preds: list[dict], table: list[dict] | None = None,
                   accuracy: dict | None = None, sim: dict | None = None,
                   out_filename: str = "index.html", note: str | None = None) -> str:
    teams = db.team_names()
    preds_by_match = {p["match_id"]: p for p in preds}
    table = table or []
    sim = sim or {}

    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    md_label = f"Αγωνιστική {matchday}" if matchday else "Τέλος σεζόν"
    fixtures_rows = _fixtures_table(fixtures, preds_by_match, teams)
    accuracy_html = _accuracy_html(accuracy)
    standings_rows = _standings_table(table, sim)
    note_html = f'<div class="note">{note}</div>' if note else ""

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
  h2 {{ color:#fff; font-size:1.1rem; margin:2.5rem 0 0.8rem; }}
  .meta {{ color:#9db4c0; margin-bottom:1rem; }}
  .accuracy {{ color:#9db4c0; margin-bottom:1.5rem; font-size:0.9rem; }}
  .accuracy b {{ color:#4ade80; }}
  table {{ width:100%; border-collapse:collapse; background:#132a3e; border-radius:8px;
           overflow:hidden; font-size:0.92rem; }}
  th, td {{ padding:0.6rem 0.8rem; text-align:center; }}
  th {{ background:#1c3a52; color:#9db4c0; font-weight:600; text-transform:uppercase;
        font-size:0.75rem; letter-spacing:0.03em; }}
  tr:nth-child(even) {{ background:#0f2436; }}
  .team {{ font-weight:600; color:#fff; text-align:left; }}
  .score {{ font-size:1.15rem; font-weight:700; color:#4ade80; }}
  .xg {{ color:#7fa3b8; font-size:0.85rem; }}
  .probs {{ color:#9db4c0; font-size:0.88rem; }}
  .points {{ font-weight:700; color:#fff; }}
  .zone-top4 {{ box-shadow: inset 3px 0 0 #4ade80; }}
  .zone-releg {{ box-shadow: inset 3px 0 0 #f87171; }}
  .badge {{ display:inline-block; width:1.3rem; height:1.3rem; line-height:1.3rem;
            border-radius:3px; font-size:0.7rem; font-weight:700; margin:0 1px; }}
  .badge-W {{ background:#16653488; color:#4ade80; }}
  .badge-D {{ background:#374151; color:#cbd5e1; }}
  .badge-L {{ background:#7f1d1d88; color:#f87171; }}
  .note {{ background:#3730a3; color:#e0e7ff; padding:0.7rem 1rem; border-radius:6px;
           margin-bottom:1.2rem; font-size:0.88rem; }}
  footer {{ margin-top:2rem; color:#5c7182; font-size:0.8rem; }}
</style>
</head>
<body>
  <h1>Premier League &mdash; Προβλέψεις</h1>
  <div class="meta">Σεζόν {season}-{season + 1} &middot; {md_label} &middot;
    ενημερώθηκε {generated}</div>
  {note_html}
  {accuracy_html}

  <table>
    <thead>
      <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Πρόβλεψη</th>
          <th>Φιλοξενούμενος</th><th>Αναμ. γκολ</th><th>1 / Χ / 2</th></tr>
    </thead>
    <tbody>
      {fixtures_rows}
    </tbody>
  </table>

  <h2>Βαθμολογία &amp; προσομοίωση τελικής θέσης</h2>
  <table>
    <thead>
      <tr><th>#</th><th>Ομάδα</th><th>Αγ</th><th>Ν</th><th>Ι</th><th>Η</th>
          <th>ΓΦ</th><th>ΓΚ</th><th>Δ</th><th>Β</th><th>Φόρμα</th>
          <th>Τίτλος</th><th>Top-4</th><th>Υποβ.</th></tr>
    </thead>
    <tbody>
      {standings_rows}
    </tbody>
  </table>

  <footer>Δεδομένα: football-data.org &middot; Μοντέλο: Poisson (επιθετική/αμυντική
    δύναμη ομάδων, με μεγαλύτερο βάρος στην πρόσφατη φόρμα) &middot;
    Προσομοίωση τελικής βαθμολογίας: Monte Carlo πάνω στο ίδιο μοντέλο,
    χωρίς head-to-head στα ισοβαθμίσαντα.</footer>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / out_filename
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)
