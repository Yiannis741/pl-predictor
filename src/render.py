# -*- coding: utf-8 -*-
"""Παράγει το output/index.html: μία σελίδα με καρτέλες/μενού (χωρίς reload,
απλό vanilla JS) — μία καρτέλα για την τρέχουσα σεζόν και μία ανά διαθέσιμη
ιστορική σεζόν, αντί για μία μακριά σελίδα scroll."""

import datetime

from . import config, db

FORM_LABELS = {"W": "Ν", "D": "Ι", "L": "Η"}  # Νίκη / Ισοπαλία / Ήττα
OUTCOME_LABELS = {"H": "1", "D": "Χ", "A": "2"}


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


def _fixtures_table(fixtures: list[dict], preds_by_match: dict, teams: dict) -> str | None:
    if not fixtures:
        return None
    rows_html = []
    for m in fixtures:
        home = teams.get(m["home_team_id"], {}).get("name", "?")
        away = teams.get(m["away_team_id"], {}).get("name", "?")
        p = preds_by_match.get(m["id"])
        date = _fmt_date(m.get("utc_date"))
        if p:
            pick_letter = OUTCOME_LABELS.get(p.get("predicted_outcome"), "?")
            pick_conf = max(p["prob_home"], p["prob_draw"], p["prob_away"])
            pick = f'{pick_letter} ({_fmt_pct(pick_conf * 100)})'
            score = f'{p["predicted_home_score"]}-{p["predicted_away_score"]}'
            probs = (f'{_fmt_pct(p["prob_home"] * 100)} / {_fmt_pct(p["prob_draw"] * 100)} / '
                     f'{_fmt_pct(p["prob_away"] * 100)}')
            xg = f'{p["lambda_home"]:.1f} &ndash; {p["lambda_away"]:.1f}'
        else:
            pick, score, probs, xg = "-", "-", "-", "-"
        rows_html.append(f"""
        <tr>
          <td>{date}</td>
          <td class="team">{home}</td>
          <td class="team">{away}</td>
          <td class="pick">{pick}</td>
          <td class="score">{score}</td>
          <td class="xg">{xg}</td>
          <td class="probs">{probs}</td>
        </tr>""")
    return "".join(rows_html)


def _accuracy_html(accuracy: dict | None) -> str:
    if not accuracy or not accuracy.get("total"):
        return ('<div class="accuracy">Ακρίβεια μοντέλου: δεν υπάρχουν ακόμα '
                'τελειωμένοι αγώνες φέτος για αξιολόγηση.</div>')
    return (f'<div class="accuracy">Ακρίβεια μοντέλου (σε {accuracy["total"]} '
            f'αγώνες): <b>{_fmt_pct(accuracy["result_pct"])}</b> σωστή πρόβλεψη 1/Χ/2 '
            f'&middot; <b>{_fmt_pct(accuracy["exact_pct"])}</b> ακριβές σκορ</div>')


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


def build_section(section_id: str, label: str, season: int, matchday: int | None,
                   fixtures: list[dict], preds: list[dict], table: list[dict] | None = None,
                   accuracy: dict | None = None, sim: dict | None = None,
                   note: str | None = None, active: bool = False) -> str:
    """Χτίζει το περιεχόμενο ΜΙΑΣ καρτέλας (μία σεζόν). Καλείται μία φορά ανά
    σεζόν (τρέχουσα + ιστορικές) και οι καρτέλες συνδυάζονται στο
    render_site() παρακάτω."""
    teams = db.team_names()
    preds_by_match = {p["match_id"]: p for p in preds}
    table = table or []
    sim = sim or {}

    md_label = f"Αγωνιστική {matchday}" if matchday else "Τέλος σεζόν"
    fixtures_rows = _fixtures_table(fixtures, preds_by_match, teams)
    accuracy_html = _accuracy_html(accuracy)
    standings_rows = _standings_table(table, sim)
    note_html = f'<div class="note">{note}</div>' if note else ""

    fixtures_block = "" if fixtures_rows is None else f"""
  <h3>{md_label}</h3>
  <table>
    <thead>
      <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Φιλοξενούμενος</th>
          <th>Πρόβλεψη</th><th>Πιθανό σκορ</th><th>Αναμ. γκολ</th><th>1 / Χ / 2</th></tr>
    </thead>
    <tbody>
      {fixtures_rows}
    </tbody>
  </table>"""

    display = "block" if active else "none"
    return f"""
<section id="{section_id}" class="tab-panel" style="display:{display}">
  <div class="meta">Σεζόν {season}-{season + 1}</div>
  {note_html}
  {accuracy_html}
  {fixtures_block}

  <h3>Βαθμολογία &amp; προσομοίωση τελικής θέσης</h3>
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
</section>"""


_CSS = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#0d1b2a;
          color:#e0e6ed; margin:0; padding:2rem; }
  h1 { color:#fff; margin-bottom:0.2rem; }
  h3 { color:#fff; font-size:1.05rem; margin:2rem 0 0.7rem; }
  .meta { color:#9db4c0; margin-bottom:1rem; font-size:0.9rem; }
  .accuracy { color:#9db4c0; margin-bottom:1rem; font-size:0.9rem; }
  .accuracy b { color:#4ade80; }
  .generated { color:#5c7182; font-size:0.8rem; margin-bottom:1.2rem; }
  nav { display:flex; gap:0.5rem; flex-wrap:wrap; margin-bottom:1.5rem;
        border-bottom:1px solid #1c3a52; padding-bottom:1rem; }
  nav button { background:#132a3e; color:#9db4c0; border:1px solid #1c3a52;
               border-radius:6px; padding:0.5rem 1rem; font-size:0.9rem;
               cursor:pointer; font-family:inherit; }
  nav button:hover { background:#1c3a52; color:#fff; }
  nav button.active { background:#4ade80; color:#0d1b2a; font-weight:700; border-color:#4ade80; }
  table { width:100%; border-collapse:collapse; background:#132a3e; border-radius:8px;
          overflow:hidden; font-size:0.9rem; }
  th, td { padding:0.55rem 0.7rem; text-align:center; }
  th { background:#1c3a52; color:#9db4c0; font-weight:600; text-transform:uppercase;
       font-size:0.72rem; letter-spacing:0.03em; }
  tr:nth-child(even) { background:#0f2436; }
  .team { font-weight:600; color:#fff; text-align:left; }
  .pick { font-weight:700; color:#facc15; }
  .score { font-weight:700; color:#4ade80; }
  .xg { color:#7fa3b8; font-size:0.85rem; }
  .probs { color:#9db4c0; font-size:0.85rem; }
  .points { font-weight:700; color:#fff; }
  .zone-top4 { box-shadow: inset 3px 0 0 #4ade80; }
  .zone-releg { box-shadow: inset 3px 0 0 #f87171; }
  .badge { display:inline-block; width:1.3rem; height:1.3rem; line-height:1.3rem;
           border-radius:3px; font-size:0.7rem; font-weight:700; margin:0 1px; }
  .badge-W { background:#16653488; color:#4ade80; }
  .badge-D { background:#374151; color:#cbd5e1; }
  .badge-L { background:#7f1d1d88; color:#f87171; }
  .note { background:#3730a3; color:#e0e7ff; padding:0.7rem 1rem; border-radius:6px;
          margin-bottom:1rem; font-size:0.85rem; }
  footer { margin-top:2rem; color:#5c7182; font-size:0.8rem; }
"""

_JS = """
function showTab(id) {
  document.querySelectorAll('.tab-panel').forEach(function (el) {
    el.style.display = (el.id === id) ? 'block' : 'none';
  });
  document.querySelectorAll('nav button').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.target === id);
  });
}
"""


def render_site(sections: list[dict], out_filename: str = "index.html") -> str:
    """sections: λίστα από {"id","label","html"} (βλ. build_section). Η πρώτη
    καρτέλα είναι ενεργή κατά το άνοιγμα."""
    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    nav_buttons = "".join(
        f'<button data-target="{s["id"]}" class="{"active" if i == 0 else ""}" '
        f'onclick="showTab(\'{s["id"]}\')">{s["label"]}</button>'
        for i, s in enumerate(sections)
    )
    panels = "".join(s["html"] for s in sections)

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PL Predictor</title>
<style>{_CSS}</style>
</head>
<body>
  <h1>Premier League &mdash; Προβλέψεις</h1>
  <div class="generated">ενημερώθηκε {generated}</div>
  <nav>{nav_buttons}</nav>
  {panels}
  <footer>Δεδομένα: football-data.org &middot; Μοντέλο: Poisson με στάθμιση
    πρόσφατης φόρμας και διόρθωση Dixon-Coles &middot; Προσομοίωση τελικής
    βαθμολογίας: Monte Carlo, χωρίς head-to-head στα ισοβαθμίσαντα.</footer>
  <script>{_JS}</script>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / out_filename
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def render_report(season: int, matchday: int | None, fixtures: list[dict],
                   preds: list[dict], table: list[dict] | None = None,
                   accuracy: dict | None = None, sim: dict | None = None,
                   out_filename: str = "index.html", note: str | None = None) -> str:
    """Σελίδα με μία μόνο καρτέλα (χρησιμοποιείται από το backtest.py για
    γρήγορο, αυτόνομο έλεγχο μιας σεζόν)."""
    section = build_section("season", f"Σεζόν {season}-{season + 1}", season, matchday,
                             fixtures, preds, table=table, accuracy=accuracy, sim=sim,
                             note=note, active=True)
    return render_site([{"id": "season", "label": f"Σεζόν {season}-{season + 1}",
                          "html": section}], out_filename=out_filename)
