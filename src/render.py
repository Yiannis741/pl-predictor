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


def _fixtures_table(fixtures: list[dict], preds_by_match: dict,
                     elo_preds_by_match: dict, teams: dict) -> str | None:
    if not fixtures:
        return None
    elo_preds_by_match = elo_preds_by_match or {}
    rows_html = []
    for m in fixtures:
        home = teams.get(m["home_team_id"], {}).get("name", "?")
        away = teams.get(m["away_team_id"], {}).get("name", "?")
        p = preds_by_match.get(m["id"])
        ep = elo_preds_by_match.get(m["id"])
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
        if ep:
            elo_letter = OUTCOME_LABELS.get(ep.get("predicted_outcome"), "?")
            elo_conf = max(ep["prob_home"], ep["prob_draw"], ep["prob_away"])
            elo_pick = f'{elo_letter} ({_fmt_pct(elo_conf * 100)})'
        else:
            elo_pick = "-"
        rows_html.append(f"""
        <tr>
          <td>{date}</td>
          <td class="team">{home}</td>
          <td class="team">{away}</td>
          <td class="pick">{pick}</td>
          <td class="score">{score}</td>
          <td class="xg">{xg}</td>
          <td class="probs">{probs}</td>
          <td class="pick pick-elo">{elo_pick}</td>
        </tr>""")
    return "".join(rows_html)


def _one_model_accuracy_html(label: str, accuracy: dict | None) -> str:
    if not accuracy or not accuracy.get("total"):
        return f'{label}: δεν υπάρχουν ακόμα τελειωμένοι αγώνες φέτος για αξιολόγηση.'
    exact = (f' &middot; <b>{_fmt_pct(accuracy["exact_pct"])}</b> ακριβές σκορ'
             if accuracy.get("exact_pct") is not None else "")
    return (f'{label} (σε {accuracy["total"]} αγώνες): '
            f'<b>{_fmt_pct(accuracy["result_pct"])}</b> σωστή πρόβλεψη 1/Χ/2{exact}')


def _accuracy_html(accuracy: dict | None, elo_accuracy: dict | None = None) -> str:
    lines = [_one_model_accuracy_html("Poisson", accuracy)]
    if elo_accuracy is not None:
        lines.append(_one_model_accuracy_html("Elo", elo_accuracy))
    return '<div class="accuracy">' + '<br>'.join(lines) + '</div>'


def _standings_table(table: list[dict], sim: dict, team_acc: dict | None = None,
                      elo_team_acc: dict | None = None) -> str:
    n_cols = 15 if elo_team_acc is not None else 14
    if not table:
        return (f'<tr><td colspan="{n_cols}">Δεν υπάρχουν ακόμα τελειωμένοι αγώνες φέτος '
                'για βαθμολογία.</td></tr>')
    team_acc = team_acc or {}
    elo_team_acc = elo_team_acc or {}
    rows = []
    for r in table:
        form_badges = "".join(
            f'<span class="badge badge-{f}">{FORM_LABELS.get(f, "?")}</span>'
            for f in r["form"]
        ) or "-"
        s = sim.get(r["team_id"], {})
        acc = team_acc.get(r["team_id"], {})
        acc_html = (f'{_fmt_pct(acc.get("pct"))} <span class="acc-n">({acc["total"]})</span>'
                    if acc.get("total") else "-")
        elo_acc_cell = ""
        if elo_team_acc is not None:
            eacc = elo_team_acc.get(r["team_id"], {})
            eacc_html = (f'{_fmt_pct(eacc.get("pct"))} <span class="acc-n">({eacc["total"]})</span>'
                         if eacc.get("total") else "-")
            elo_acc_cell = f'<td>{eacc_html}</td>'
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
          <td>{acc_html}</td>
          {elo_acc_cell}
          <td>{_fmt_pct(s.get("title_pct"))}</td>
          <td>{_fmt_pct(s.get("top4_pct"))}</td>
          <td>{_fmt_pct(s.get("relegation_pct"))}</td>
        </tr>""")
    return "".join(rows)


def build_section(section_id: str, label: str, season: int, matchday: int | None,
                   fixtures: list[dict], preds: list[dict], table: list[dict] | None = None,
                   accuracy: dict | None = None, sim: dict | None = None,
                   team_accuracy: dict | None = None, elo_accuracy: dict | None = None,
                   elo_team_accuracy: dict | None = None,
                   note: str | None = None, active: bool = False) -> str:
    """Χτίζει το περιεχόμενο ΜΙΑΣ καρτέλας (μία σεζόν). Καλείται μία φορά ανά
    σεζόν (τρέχουσα + ιστορικές) και οι καρτέλες συνδυάζονται στο
    render_site() παρακάτω. Το preds μπορεί να περιέχει προβλέψεις και από
    τα δύο μοντέλα (poisson/elo) -- ξεχωρίζουν εδώ με βάση το "model"."""
    teams = db.team_names()
    preds_by_match = {p["match_id"]: p for p in preds if p.get("model", "poisson") == "poisson"}
    elo_preds_by_match = {p["match_id"]: p for p in preds if p.get("model") == "elo"}
    table = table or []
    sim = sim or {}
    show_elo = elo_accuracy is not None or elo_team_accuracy is not None or elo_preds_by_match

    md_label = f"Αγωνιστική {matchday}" if matchday else "Τέλος σεζόν"
    fixtures_rows = _fixtures_table(fixtures, preds_by_match, elo_preds_by_match, teams)
    accuracy_html = _accuracy_html(accuracy, elo_accuracy if show_elo else None)
    standings_rows = _standings_table(table, sim, team_accuracy,
                                       elo_team_accuracy if show_elo else None)
    note_html = f'<div class="note">{note}</div>' if note else ""

    elo_th = '<th>Πρόβλεψη Elo</th>' if show_elo else ""
    fixtures_block = "" if fixtures_rows is None else f"""
  <h3>{md_label}</h3>
  <table>
    <thead>
      <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Φιλοξενούμενος</th>
          <th>Πρόβλεψη Poisson</th><th>Πιθανό σκορ</th><th>Αναμ. γκολ</th>
          <th>1 / Χ / 2</th>{elo_th}</tr>
    </thead>
    <tbody>
      {fixtures_rows}
    </tbody>
  </table>"""

    elo_acc_th = '<th>Ακρίβεια Elo</th>' if show_elo else ""
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
          <th>Ακρίβεια Poisson</th>{elo_acc_th}
          <th>Τίτλος</th><th>Top-4</th><th>Υποβ.</th></tr>
    </thead>
    <tbody>
      {standings_rows}
    </tbody>
  </table>
</section>"""


def _pred_pick(p: dict | None) -> tuple[str, str | None]:
    """(κείμενο pick, outcome-γράμμα) από ένα prediction row -- λειτουργεί
    και για Poisson (έχει predicted_home_score) και για Elo (δεν έχει)."""
    if not p:
        return "-", None
    ph, pd, pa = p["prob_home"], p["prob_draw"], p["prob_away"]
    if ph >= pd and ph >= pa:
        outcome = "H"
    elif pa >= pd:
        outcome = "A"
    else:
        outcome = "D"
    letter = OUTCOME_LABELS.get(outcome, "?")
    if p.get("predicted_home_score") is not None:
        score = f'{int(p["predicted_home_score"])}-{int(p["predicted_away_score"])}'
        return f"{letter} ({score})", outcome
    return letter, outcome


def build_detail_section(section_id: str, label: str, season: int, matches: list[dict],
                          preds_by_match: dict, elo_preds_by_match: dict | None = None,
                          active: bool = False) -> str:
    """Αναλυτική καρτέλα: όλοι οι αγώνες της σεζόν, ομαδοποιημένοι ανά
    αγωνιστική μέσα σε &lt;details&gt; (κλειστά εξ ορισμού) ώστε η σελίδα να
    ανοίγει συμπαγής -- 380 αγώνες σε μία επίπεδη λίστα θα ήταν αδιάβαστοι.
    Δείχνει τις προβλέψεις ΚΑΙ των δύο μοντέλων δίπλα-δίπλα, αν δοθεί
    elo_preds_by_match."""
    teams = db.team_names()
    elo_preds_by_match = elo_preds_by_match or {}
    show_elo = bool(elo_preds_by_match)

    by_matchday: dict[int, list[dict]] = {}
    for m in matches:
        by_matchday.setdefault(m.get("matchday") or 0, []).append(m)

    blocks = []
    for md in sorted(by_matchday):
        md_matches = sorted(by_matchday[md], key=lambda m: m.get("utc_date") or "")
        rows = []
        hits = total = 0
        for m in md_matches:
            home = teams.get(m["home_team_id"], {}).get("name", "?")
            away = teams.get(m["away_team_id"], {}).get("name", "?")
            date = _fmt_date(m.get("utc_date"))
            p = preds_by_match.get(m["id"])
            ep = elo_preds_by_match.get(m["id"])
            played = m.get("home_score") is not None and m.get("away_score") is not None

            actual = f'{m["home_score"]}-{m["away_score"]}' if played else "-"
            pick, pred_outcome = _pred_pick(p)
            elo_pick, elo_outcome = _pred_pick(ep)

            mark = '<span class="mark mark-none">-</span>'
            elo_mark = '<span class="mark mark-none">-</span>'
            if played:
                actual_outcome = ("H" if m["home_score"] > m["away_score"] else
                                   ("A" if m["home_score"] < m["away_score"] else "D"))
                if p:
                    total += 1
                    if actual_outcome == pred_outcome:
                        hits += 1
                        mark = '<span class="mark mark-ok">&#10003;</span>'
                    else:
                        mark = '<span class="mark mark-bad">&#10007;</span>'
                if ep:
                    if actual_outcome == elo_outcome:
                        elo_mark = '<span class="mark mark-ok">&#10003;</span>'
                    else:
                        elo_mark = '<span class="mark mark-bad">&#10007;</span>'

            elo_cells = (f'<td class="pick pick-elo">{elo_pick}</td><td>{elo_mark}</td>'
                         if show_elo else "")
            rows.append(f"""
            <tr>
              <td>{date}</td>
              <td class="team">{home}</td>
              <td class="team">{away}</td>
              <td class="score">{actual}</td>
              <td class="pick">{pick}</td>
              <td>{mark}</td>
              {elo_cells}
            </tr>""")

        summary_acc = f" &middot; Poisson {hits}/{total} σωστά" if total else ""
        elo_th = '<th>Elo</th><th>&#10003;</th>' if show_elo else ""
        blocks.append(f"""
      <details>
        <summary>Αγωνιστική {md}{summary_acc}</summary>
        <table>
          <thead>
            <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Φιλοξενούμενος</th>
                <th>Αποτέλεσμα</th><th>Poisson</th><th>&#10003;</th>{elo_th}</tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </details>""")

    display = "block" if active else "none"
    body = "".join(blocks) if blocks else "<p>Δεν υπάρχουν αγώνες.</p>"
    return f"""
<section id="{section_id}" class="tab-panel" style="display:{display}">
  <div class="meta">Αναλυτικά αποτελέσματα &amp; προβλέψεις &middot; Σεζόν {season}-{season + 1}</div>
  {body}
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
  .pick-elo { color:#60a5fa; }
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
  .acc-n { color:#5c7182; font-size:0.78rem; }
  details { background:#132a3e; border-radius:8px; margin-bottom:0.6rem; overflow:hidden; }
  summary { padding:0.6rem 1rem; cursor:pointer; color:#e0e6ed; font-weight:600;
            font-size:0.88rem; list-style:none; }
  summary::-webkit-details-marker { display:none; }
  summary::before { content:'\\25B8'; display:inline-block; margin-right:0.5rem;
                     transition:transform 0.15s; color:#4ade80; }
  details[open] summary::before { transform:rotate(90deg); }
  details table { border-radius:0; font-size:0.85rem; }
  details th { font-size:0.68rem; }
  .mark { font-weight:700; }
  .mark-ok { color:#4ade80; }
  .mark-bad { color:#f87171; }
  .mark-none { color:#5c7182; }
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
  <footer>Δεδομένα: football-data.org &middot; Δύο μοντέλα πρόβλεψης:
    <span style="color:#facc15">Poisson</span> (μέσοι όροι γκολ με στάθμιση
    πρόσφατης φόρμας + διόρθωση Dixon-Coles) και
    <span style="color:#60a5fa">Elo</span> (rating που ενημερώνεται
    αγώνα-αγώνα, πιο ευαίσθητο σε ξαφνικές αλλαγές φόρμας) &middot;
    Προσομοίωση τελικής βαθμολογίας: Monte Carlo πάνω στο μοντέλο Poisson,
    χωρίς head-to-head στα ισοβαθμίσαντα.</footer>
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
                   team_accuracy: dict | None = None, elo_accuracy: dict | None = None,
                   elo_team_accuracy: dict | None = None,
                   out_filename: str = "index.html", note: str | None = None) -> str:
    """Σελίδα με μία μόνο καρτέλα (χρησιμοποιείται από το backtest.py για
    γρήγορο, αυτόνομο έλεγχο μιας σεζόν)."""
    section = build_section("season", f"Σεζόν {season}-{season + 1}", season, matchday,
                             fixtures, preds, table=table, accuracy=accuracy, sim=sim,
                             team_accuracy=team_accuracy, elo_accuracy=elo_accuracy,
                             elo_team_accuracy=elo_team_accuracy, note=note, active=True)
    return render_site([{"id": "season", "label": f"Σεζόν {season}-{season + 1}",
                          "html": section}], out_filename=out_filename)
