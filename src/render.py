# -*- coding: utf-8 -*-
"""Παράγει το output/index.html: μία σελίδα με καρτέλες/μενού (χωρίς reload,
απλό vanilla JS) — μία καρτέλα για την τρέχουσα σεζόν και μία ανά διαθέσιμη
ιστορική σεζόν, αντί για μία μακριά σελίδα scroll."""

import datetime

from . import competitions, config, db

FORM_LABELS = {"W": "Ν", "D": "Ι", "L": "Η"}  # Νίκη / Ισοπαλία / Ήττα
OUTCOME_LABELS = {"H": "1", "D": "Χ", "A": "2"}

# Πόσο πρέπει να διαφωνεί το Poisson με την αγορά (στην ΙΔΙΑ έκβαση) για να
# το σημειώσουμε σαν "αξίας" (value) -- αν το μοντέλο μας δίνει σημαντικά
# μεγαλύτερη πιθανότητα από ό,τι υπονοούν οι αποδόσεις, η αγορά πιθανώς
# υποτιμά αυτή την έκβαση. Καθαρά πληροφοριακό, όχι συμβουλή στοιχηματισμού.
VALUE_EDGE_THRESHOLD = 0.08


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
                     elo_preds_by_match: dict, teams: dict,
                     market_preds_by_match: dict | None = None) -> str | None:
    if not fixtures:
        return None
    elo_preds_by_match = elo_preds_by_match or {}
    market_preds_by_match = market_preds_by_match or {}
    show_market = bool(market_preds_by_match)
    rows_html = []
    for m in fixtures:
        home = teams.get(m["home_team_id"], {}).get("name", "?")
        away = teams.get(m["away_team_id"], {}).get("name", "?")
        p = preds_by_match.get(m["id"])
        ep = elo_preds_by_match.get(m["id"])
        mp = market_preds_by_match.get(m["id"])
        date = _fmt_date(m.get("utc_date"))
        if p:
            pick_letter = OUTCOME_LABELS.get(p.get("predicted_outcome"), "?")
            pick_conf = max(p["prob_home"], p["prob_draw"], p["prob_away"])
            pick = f'{pick_letter} ({_fmt_pct(pick_conf * 100)})'
            score = f'{p["predicted_home_score"]}-{p["predicted_away_score"]}'
            probs = (f'{_fmt_pct(p["prob_home"] * 100)} / {_fmt_pct(p["prob_draw"] * 100)} / '
                     f'{_fmt_pct(p["prob_away"] * 100)}')
            xg = f'{p["lambda_home"]:.1f} &ndash; {p["lambda_away"]:.1f}'
            if p.get("prob_over25") is not None:
                over_pct = p["prob_over25"] * 100
                ou_label = "Over 2.5" if over_pct >= 50 else "Under 2.5"
                ou = f'{ou_label} ({_fmt_pct(over_pct if over_pct >= 50 else 100 - over_pct)})'
            else:
                ou = "-"
            btts = _fmt_pct(p["prob_btts"] * 100) if p.get("prob_btts") is not None else "-"
        else:
            pick, score, probs, xg, ou, btts = "-", "-", "-", "-", "-", "-"

        # Value bet σήμα: το Poisson δίνει σημαντικά μεγαλύτερη πιθανότητα
        # από την αγορά στην ΙΔΙΑ έκβαση που προβλέπουμε.
        if p and mp:
            outcome = p.get("predicted_outcome")
            p_by_outcome = {"H": p["prob_home"], "D": p["prob_draw"], "A": p["prob_away"]}
            m_by_outcome = {"H": mp["prob_home"], "D": mp["prob_draw"], "A": mp["prob_away"]}
            edge = p_by_outcome.get(outcome, 0) - m_by_outcome.get(outcome, 0)
            if edge >= VALUE_EDGE_THRESHOLD:
                pick += (f' <span class="value-badge" title="Το Poisson δίνει {_fmt_pct(edge * 100)} '
                         f'μονάδες παραπάνω πιθανότητα από την αγορά σε αυτή την έκβαση">&#9650; value</span>')
        if ep:
            elo_letter = OUTCOME_LABELS.get(ep.get("predicted_outcome"), "?")
            elo_conf = max(ep["prob_home"], ep["prob_draw"], ep["prob_away"])
            elo_pick = f'{elo_letter} ({_fmt_pct(elo_conf * 100)})'
        else:
            elo_pick = "-"
        market_cell = ""
        if show_market:
            if mp:
                m_letter = OUTCOME_LABELS.get(mp.get("predicted_outcome"), "?")
                m_conf = max(mp["prob_home"], mp["prob_draw"], mp["prob_away"])
                market_pick = f'{m_letter} ({_fmt_pct(m_conf * 100)})'
            else:
                market_pick = "-"
            market_cell = f'<td class="pick pick-market">{market_pick}</td>'
        rows_html.append(f"""
        <tr>
          <td>{date}</td>
          <td class="team">{home}</td>
          <td class="team">{away}</td>
          <td class="pick">{pick}</td>
          <td class="score">{score}</td>
          <td class="xg">{xg}</td>
          <td class="probs">{probs}</td>
          <td class="ou">{ou}</td>
          <td class="ou">{btts}</td>
          <td class="pick pick-elo">{elo_pick}</td>
          {market_cell}
        </tr>""")
    return "".join(rows_html)


def _one_model_accuracy_html(label: str, accuracy: dict | None) -> str:
    if not accuracy or not accuracy.get("total"):
        return f'{label}: δεν υπάρχουν ακόμα τελειωμένοι αγώνες φέτος για αξιολόγηση.'
    exact = (f' &middot; <b>{_fmt_pct(accuracy["exact_pct"])}</b> ακριβές σκορ'
             if accuracy.get("exact_pct") is not None else "")
    quality = ""
    if accuracy.get("log_loss") is not None and accuracy.get("brier_score") is not None:
        quality = (f' &middot; Log loss <strong>{accuracy["log_loss"]:.3f}</strong>'
                   f' &middot; Brier <strong>{accuracy["brier_score"]:.3f}</strong>')
    return (f'{label} (σε {accuracy["total"]} αγώνες): '
            f'<b>{_fmt_pct(accuracy["result_pct"])}</b> σωστή πρόβλεψη 1/Χ/2{exact}{quality}')


def _accuracy_html(accuracy: dict | None, elo_accuracy: dict | None = None,
                    market_accuracy: dict | None = None) -> str:
    lines = [_one_model_accuracy_html("Poisson", accuracy)]
    if elo_accuracy is not None:
        lines.append(_one_model_accuracy_html("Elo", elo_accuracy))
    if market_accuracy is not None:
        lines.append(_one_model_accuracy_html("Αγορά (αποδόσεις)", market_accuracy))
    return '<div class="accuracy">' + '<br>'.join(lines) + '</div>'


def _standings_table(table: list[dict], sim: dict, team_acc: dict | None = None,
                      elo_team_acc: dict | None = None,
                      market_team_acc: dict | None = None,
                      top_n: int = 4, releg_n: int = 3) -> str:
    n_cols = 14 + (1 if elo_team_acc is not None else 0) + (1 if market_team_acc is not None else 0)
    if not table:
        return (f'<tr><td colspan="{n_cols}">Δεν υπάρχουν ακόμα τελειωμένοι αγώνες φέτος '
                'για βαθμολογία.</td></tr>')
    team_acc = team_acc or {}
    elo_team_acc = elo_team_acc or {}
    market_team_acc = market_team_acc or {}
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
        market_acc_cell = ""
        if market_team_acc is not None:
            macc = market_team_acc.get(r["team_id"], {})
            macc_html = (f'{_fmt_pct(macc.get("pct"))} <span class="acc-n">({macc["total"]})</span>'
                         if macc.get("total") else "-")
            market_acc_cell = f'<td>{macc_html}</td>'
        row_class = ""
        if r["position"] <= top_n:
            row_class = "zone-top4"
        elif r["position"] > len(table) - releg_n:
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
          {market_acc_cell}
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
                   market_accuracy: dict | None = None,
                   market_team_accuracy: dict | None = None,
                   note: str | None = None, active: bool = False,
                   competition: str = "PL") -> str:
    """Χτίζει το περιεχόμενο ΜΙΑΣ καρτέλας (μία σεζόν). Καλείται μία φορά ανά
    σεζόν (τρέχουσα + ιστορικές) και οι καρτέλες συνδυάζονται στο
    render_site() παρακάτω. Το preds μπορεί να περιέχει προβλέψεις και από
    τα τρία μοντέλα (poisson/elo/market) -- ξεχωρίζουν εδώ με βάση το
    "model". Το "market" (αποδόσεις στοιχήματος) υπάρχει μόνο όσο δίνεται
    ρητά market_accuracy/market_team_accuracy -- π.χ. δεν υπάρχει ιστορικό
    γι' αυτό στις παλιές σεζόν."""
    teams = db.team_names()
    preds_by_match = {p["match_id"]: p for p in preds if p.get("model", "poisson") == "poisson"}
    elo_preds_by_match = {p["match_id"]: p for p in preds if p.get("model") == "elo"}
    market_preds_by_match = {p["match_id"]: p for p in preds if p.get("model") == "market"}
    table = table or []
    sim = sim or {}
    show_elo = elo_accuracy is not None or elo_team_accuracy is not None or elo_preds_by_match
    show_market = (market_accuracy is not None or market_team_accuracy is not None
                   or market_preds_by_match)

    md_label = f"Αγωνιστική {matchday}" if matchday else "Τέλος σεζόν"
    fixtures_rows = _fixtures_table(fixtures, preds_by_match, elo_preds_by_match, teams,
                                     market_preds_by_match if show_market else None)
    accuracy_html = _accuracy_html(accuracy, elo_accuracy if show_elo else None,
                                    market_accuracy if show_market else None)
    comp_meta = competitions.BY_CODE.get(competition, {})
    top_n = comp_meta.get("top_zone", 4)
    releg_n = comp_meta.get("releg_zone", 3)
    standings_rows = _standings_table(table, sim, team_accuracy,
                                       elo_team_accuracy if show_elo else None,
                                       market_team_accuracy if show_market else None,
                                       top_n=top_n, releg_n=releg_n)
    note_html = f'<div class="note">{note}</div>' if note else ""

    elo_th = '<th>Πρόβλεψη Elo</th>' if show_elo else ""
    market_th = '<th>Πρόβλεψη Αγοράς</th>' if show_market else ""
    fixtures_block = "" if fixtures_rows is None else f"""
  <h3>{md_label}</h3>
  <table>
    <thead>
      <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Φιλοξενούμενος</th>
          <th>Πρόβλεψη Poisson</th><th>Πιθανό σκορ</th><th>Αναμ. γκολ</th>
          <th>1 / Χ / 2</th><th>O/U 2.5</th><th>BTTS</th>{elo_th}{market_th}</tr>
    </thead>
    <tbody>
      {fixtures_rows}
    </tbody>
  </table>"""

    elo_acc_th = '<th>Ακρίβεια Elo</th>' if show_elo else ""
    market_acc_th = '<th>Ακρίβεια Αγοράς</th>' if show_market else ""
    display = "block" if active else "none"
    season_txt = competitions.season_label(season, competition)
    return f"""
<section id="{section_id}" class="tab-panel" style="display:{display}">
  <div class="meta">Σεζόν {season_txt}</div>
  {note_html}
  {accuracy_html}
  {fixtures_block}

  <h3>Βαθμολογία &amp; προσομοίωση τελικής θέσης</h3>
  <table>
    <thead>
      <tr><th>#</th><th>Ομάδα</th><th>Αγ</th><th>Ν</th><th>Ι</th><th>Η</th>
          <th>ΓΦ</th><th>ΓΚ</th><th>Δ</th><th>Β</th><th>Φόρμα</th>
          <th>Ακρίβεια Poisson</th>{elo_acc_th}{market_acc_th}
          <th>Τίτλος</th><th>Top-{top_n}</th><th>Υποβ. ({releg_n})</th></tr>
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
                          market_preds_by_match: dict | None = None,
                          active: bool = False, competition: str = "PL") -> str:
    """Αναλυτική καρτέλα: όλοι οι αγώνες της σεζόν, ομαδοποιημένοι ανά
    αγωνιστική μέσα σε &lt;details&gt; (κλειστά εξ ορισμού) ώστε η σελίδα να
    ανοίγει συμπαγής -- 380 αγώνες σε μία επίπεδη λίστα θα ήταν αδιάβαστοι.
    Δείχνει τις προβλέψεις ΚΑΙ των τριών μοντέλων δίπλα-δίπλα, αν δοθούν
    elo_preds_by_match / market_preds_by_match."""
    teams = db.team_names()
    elo_preds_by_match = elo_preds_by_match or {}
    market_preds_by_match = market_preds_by_match or {}
    show_elo = bool(elo_preds_by_match)
    show_market = bool(market_preds_by_match)

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
            mp = market_preds_by_match.get(m["id"])
            played = m.get("home_score") is not None and m.get("away_score") is not None

            actual = f'{m["home_score"]}-{m["away_score"]}' if played else "-"
            pick, pred_outcome = _pred_pick(p)
            elo_pick, elo_outcome = _pred_pick(ep)
            market_pick, market_outcome = _pred_pick(mp)

            mark = '<span class="mark mark-none">-</span>'
            elo_mark = '<span class="mark mark-none">-</span>'
            market_mark = '<span class="mark mark-none">-</span>'
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
                if mp:
                    if actual_outcome == market_outcome:
                        market_mark = '<span class="mark mark-ok">&#10003;</span>'
                    else:
                        market_mark = '<span class="mark mark-bad">&#10007;</span>'

            elo_cells = (f'<td class="pick pick-elo">{elo_pick}</td><td>{elo_mark}</td>'
                         if show_elo else "")
            market_cells = (f'<td class="pick pick-market">{market_pick}</td><td>{market_mark}</td>'
                             if show_market else "")
            rows.append(f"""
            <tr>
              <td>{date}</td>
              <td class="team">{home}</td>
              <td class="team">{away}</td>
              <td class="score">{actual}</td>
              <td class="pick">{pick}</td>
              <td>{mark}</td>
              {elo_cells}
              {market_cells}
            </tr>""")

        summary_acc = f" &middot; Poisson {hits}/{total} σωστά" if total else ""
        elo_th = '<th>Elo</th><th>&#10003;</th>' if show_elo else ""
        market_th = '<th>Αγορά</th><th>&#10003;</th>' if show_market else ""
        blocks.append(f"""
      <details>
        <summary>Αγωνιστική {md}{summary_acc}</summary>
        <table>
          <thead>
            <tr><th>Ημ/νία</th><th>Γηπεδούχος</th><th>Φιλοξενούμενος</th>
                <th>Αποτέλεσμα</th><th>Poisson</th><th>&#10003;</th>{elo_th}{market_th}</tr>
          </thead>
          <tbody>{"".join(rows)}</tbody>
        </table>
      </details>""")

    display = "block" if active else "none"
    body = "".join(blocks) if blocks else "<p>Δεν υπάρχουν αγώνες.</p>"
    season_txt = competitions.season_label(season, competition)
    return f"""
<section id="{section_id}" class="tab-panel" style="display:{display}">
  <div class="meta">Αναλυτικά αποτελέσματα &amp; προβλέψεις &middot; Σεζόν {season_txt}</div>
  {body}
</section>"""


_CSS = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#0d1b2a;
          color:#e0e6ed; margin:0; padding:2rem; }
  h1 { color:#fff; margin-bottom:0.2rem; display:flex; align-items:center; gap:0.6rem; }
  .league-logo { height:2rem; width:2rem; object-fit:contain; }
  .back-link { display:inline-block; color:#9db4c0; text-decoration:none; font-size:0.85rem;
               margin-bottom:0.8rem; }
  .back-link:hover { color:#fff; }
  h3 { color:#fff; font-size:1.05rem; margin:2rem 0 0.7rem; }
  .meta { color:#9db4c0; margin-bottom:1rem; font-size:0.9rem; }
  .accuracy { color:#9db4c0; margin-bottom:1rem; font-size:0.9rem; }
  .accuracy b { color:#4ade80; }
  .accuracy strong { color:#dbe7ee; font-weight:600; }
  .generated { color:#5c7182; font-size:0.8rem; margin-bottom:1.2rem; }
  .nav-shell { display:flex; align-items:flex-end; justify-content:space-between; gap:1.5rem;
               flex-wrap:wrap; margin-bottom:1.5rem; border-bottom:1px solid #1c3a52;
               padding-bottom:1rem; }
  nav { display:flex; gap:0.5rem; flex-wrap:wrap; margin:0; }
  .nav-group { display:grid; gap:0.4rem; }
  .nav-label { color:#5c7182; font-size:0.7rem; font-weight:700; text-transform:uppercase; }
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
  .pick-market { color:#c084fc; }
  .value-badge { display:inline-block; background:#164e3488; color:#4ade80; font-size:0.68rem;
                 font-weight:700; padding:0.1rem 0.35rem; border-radius:4px; margin-left:0.3rem;
                 vertical-align:middle; cursor:help; }
  .score { font-weight:700; color:#4ade80; }
  .xg { color:#7fa3b8; font-size:0.85rem; }
  .probs { color:#9db4c0; font-size:0.85rem; }
  .ou { color:#7fa3b8; font-size:0.85rem; }
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
let activeSeason = 'current';
let activeView = 'overview';

function showTab(id) {
  document.querySelectorAll('.tab-panel').forEach(function (el) {
    el.style.display = (el.id === id) ? 'block' : 'none';
  });
  document.querySelectorAll('nav button').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.target === id);
  });
}

function showSelection(season, view) {
  activeSeason = season || activeSeason;
  activeView = view || activeView;
  let panel = document.querySelector(
    '.tab-panel[data-season="' + activeSeason + '"][data-view="' + activeView + '"]'
  );
  if (!panel) {
    activeView = 'overview';
    panel = document.querySelector(
      '.tab-panel[data-season="' + activeSeason + '"][data-view="overview"]'
    );
  }
  if (!panel) return;
  document.querySelectorAll('.tab-panel').forEach(function (el) {
    el.style.display = (el === panel) ? 'block' : 'none';
  });
  document.querySelectorAll('[data-season-choice]').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.seasonChoice === activeSeason);
  });
  document.querySelectorAll('[data-view-choice]').forEach(function (btn) {
    btn.classList.toggle('active', btn.dataset.viewChoice === activeView);
  });
}
"""


def render_site(sections: list[dict], comp: dict | None = None,
                 out_filename: str = "index.html") -> str:
    """sections: λίστα από {"id","label","html"} (βλ. build_section). Η πρώτη
    καρτέλα είναι ενεργή κατά το άνοιγμα. comp: μεταδεδομένα πρωταθλήματος
    (βλ. src/competitions.py) -- αν δοθούν, ο τίτλος/λογότυπο της σελίδας
    και ο σύνδεσμος επιστροφής στο hub προσαρμόζονται ανάλογα."""
    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    structured_nav = bool(sections) and all(
        s.get("season_key") and s.get("view") and s.get("season_label") for s in sections
    )
    if structured_nav:
        seasons = []
        seen = set()
        for section in sections:
            key = section["season_key"]
            if key not in seen:
                seasons.append((key, section["season_label"]))
                seen.add(key)
        season_buttons = "".join(
            f'<button data-season-choice="{key}" class="{"active" if i == 0 else ""}" '
            f'onclick="showSelection(\'{key}\', null)">'
            f'{"Τρέχουσα · " if key == "current" else ""}{label}</button>'
            for i, (key, label) in enumerate(seasons)
        )
        view_buttons = (
            '<button data-view-choice="overview" class="active" '
            'onclick="showSelection(null, \'overview\')">Επισκόπηση</button>'
            '<button data-view-choice="details" '
            'onclick="showSelection(null, \'details\')">Αγώνες</button>'
        )
        nav_html = (
            '<div class="nav-shell">'
            '<div class="nav-group"><span class="nav-label">Σεζόν</span>'
            f'<nav>{season_buttons}</nav></div>'
            '<div class="nav-group"><span class="nav-label">Προβολή</span>'
            f'<nav>{view_buttons}</nav></div></div>'
        )
        panels = "".join(
            s["html"].replace(
                f'<section id="{s["id"]}" class="tab-panel"',
                f'<section id="{s["id"]}" class="tab-panel" '
                f'data-season="{s["season_key"]}" data-view="{s["view"]}"',
                1,
            )
            for s in sections
        )
    else:
        nav_buttons = "".join(
            f'<button data-target="{s["id"]}" class="{"active" if i == 0 else ""}" '
            f'onclick="showTab(\'{s["id"]}\')">{s["label"]}</button>'
            for i, s in enumerate(sections)
        )
        nav_html = f"<nav>{nav_buttons}</nav>"
        panels = "".join(s["html"] for s in sections)

    page_title = comp["name"] if comp else "PL Predictor"
    emblem_html = (f'<img src="{comp["emblem"]}" alt="" class="league-logo">' if comp else "")
    back_link = ('<a class="back-link" href="index.html">&larr; Όλα τα πρωταθλήματα</a>'
                 if comp else "")

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title} &mdash; Προβλέψεις</title>
<style>{_CSS}</style>
</head>
<body>
  {back_link}
  <h1>{emblem_html}{page_title} &mdash; Προβλέψεις</h1>
  <div class="generated">ενημερώθηκε {generated}</div>
  {nav_html}
  {panels}
  <footer>Δεδομένα: football-data.org &middot; Μοντέλα πρόβλεψης:
    <span style="color:#facc15">Poisson</span> (μέσοι όροι γκολ με στάθμιση
    πρόσφατης φόρμας + διόρθωση Dixon-Coles),
    <span style="color:#60a5fa">Elo</span> (rating που ενημερώνεται
    αγώνα-αγώνα, πιο ευαίσθητο σε ξαφνικές αλλαγές φόρμας) και
    <span style="color:#c084fc">Αγορά</span> (implied probabilities από
    πραγματικές αποδόσεις στοιχήματος, The Odds API -- μόνο ζωντανές, χωρίς
    ιστορικό, οπότε εμφανίζεται μόνο στην τρέχουσα σεζόν από εδώ και πέρα)
    &middot; Προσομοίωση τελικής βαθμολογίας: Monte Carlo πάνω στο μοντέλο
    Poisson, χωρίς head-to-head στα ισοβαθμίσαντα. Οι ίδιες παράμετροι
    μοντέλων χρησιμοποιούνται σε όλα τα πρωταθλήματα (συντονισμένες πάνω σε
    δεδομένα Premier League). Η ετικέτα <span class="value-badge" style="margin-left:0">&#9650; value</span>
    σημαίνει ότι το Poisson δίνει αισθητά μεγαλύτερη πιθανότητα από την
    αγορά στην ίδια έκβαση -- καθαρά πληροφοριακό, όχι συμβουλή στοιχηματισμού.</footer>
  <script>{_JS}</script>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / out_filename
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


_HUB_CSS = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#0d1b2a;
          color:#e0e6ed; margin:0; padding:2rem; }
  h1 { color:#fff; margin-bottom:0.2rem; }
  .subtitle { color:#9db4c0; margin-bottom:2rem; font-size:0.95rem; }
  .generated { color:#5c7182; font-size:0.8rem; margin-bottom:1.5rem; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr));
          gap:1rem; }
  .card { background:#132a3e; border:1px solid #1c3a52; border-radius:10px;
          padding:1.3rem; display:flex; align-items:center; gap:1rem;
          text-decoration:none; color:#e0e6ed; transition:background 0.15s, border-color 0.15s; }
  .card:hover { background:#1c3a52; border-color:#4ade80; }
  .card img { height:3rem; width:3rem; object-fit:contain; flex-shrink:0; }
  .card .info { min-width:0; }
  .card .league-name { font-weight:700; color:#fff; font-size:1rem; }
  .card .country { color:#9db4c0; font-size:0.82rem; margin-top:0.15rem; }
  footer { margin-top:2.5rem; color:#5c7182; font-size:0.8rem; }
  footer a { color:#9db4c0; }
  footer a:hover { color:#fff; }
"""


def build_hub_page(available: list[dict]) -> str:
    """Κεντρική σελίδα (output/index.html): κάρτες με το λογότυπο κάθε
    πρωταθλήματος, που οδηγούν στην αντίστοιχη σελίδα προβλέψεων.
    available: υποσύνολο του competitions.COMPETITIONS για τα οποία όντως
    παράχθηκε σελίδα (π.χ. αν κάποιο απέτυχε να ενημερωθεί, δεν εμφανίζεται
    σπασμένος σύνδεσμος)."""
    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    cards = "".join(f"""
    <a class="card" href="{c['slug']}.html">
      <img src="{c['emblem']}" alt="">
      <div class="info">
        <div class="league-name">{c['name']}</div>
        <div class="country">{c['country']}</div>
      </div>
    </a>""" for c in available)

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Predictor &mdash; Πρωταθλήματα</title>
<style>{_HUB_CSS}</style>
</head>
<body>
  <h1>&#9917; Predictor</h1>
  <div class="subtitle">Διάλεξε πρωτάθλημα για προβλέψεις, βαθμολογία και προσομοίωση τελικής θέσης.</div>
  <div class="generated">ενημερώθηκε {generated}</div>
  <div class="grid">{cards}</div>
  <footer>Δεδομένα: football-data.org &middot; Αποδόσεις αγοράς: The Odds API &middot;
    Ίδιες παράμετροι μοντέλων (Poisson/Elo) σε όλα τα πρωταθλήματα, συντονισμένες
    πάνω σε δεδομένα Premier League. &middot; <a href="calibration.html">Πόσο σωστές
    είναι οι πιθανότητες;</a></footer>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


_MODEL_LABELS = {"poisson": "Poisson", "elo": "Elo", "market": "Αγορά (αποδόσεις)"}
_MODEL_COLORS = {"poisson": "#facc15", "elo": "#60a5fa", "market": "#c084fc"}

_CALIBRATION_CSS = """
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#0d1b2a;
          color:#e0e6ed; margin:0; padding:2rem; }
  h1 { color:#fff; margin-bottom:0.2rem; }
  h2 { color:#fff; font-size:1.1rem; margin:2rem 0 0.6rem; }
  .subtitle { color:#9db4c0; margin-bottom:1rem; font-size:0.9rem; max-width:60rem; line-height:1.5; }
  .back-link { display:inline-block; color:#9db4c0; text-decoration:none; font-size:0.85rem;
               margin-bottom:0.8rem; }
  .back-link:hover { color:#fff; }
  table { width:100%; max-width:46rem; border-collapse:collapse; background:#132a3e;
          border-radius:8px; overflow:hidden; font-size:0.88rem; margin-bottom:0.5rem; }
  th, td { padding:0.5rem 0.7rem; text-align:center; }
  th { background:#1c3a52; color:#9db4c0; font-weight:600; text-transform:uppercase;
       font-size:0.7rem; letter-spacing:0.03em; }
  tr:nth-child(even) { background:#0f2436; }
  .bar-cell { text-align:left; min-width:10rem; }
  .bar-track { background:#1c3a52; border-radius:4px; height:0.9rem; position:relative;
               overflow:hidden; }
  .bar-fill { background:#4ade80; height:100%; border-radius:4px; }
  .bar-fill.pred { background:#5c7182; }
  .n-note { color:#5c7182; font-size:0.78rem; }
  footer { margin-top:2.5rem; color:#5c7182; font-size:0.8rem; }
"""


def build_calibration_page(model_results: dict) -> str:
    """model_results: {"poisson": [...], "elo": [...], "market": [...]},
    κάθε λίστα από {"range","n","avg_pred","actual"} (βλ. calibration.py).
    Σελίδα "πόσο βαθμονομημένες" είναι οι πιθανότητες κάθε μοντέλου -- αν
    στους αγώνες που το μοντέλο έδωσε π.χ. ~70% σε μια έκβαση, κερδίζει
    πράγματι περίπου το 70% των φορών."""
    generated = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    sections = []
    for model, rows in model_results.items():
        if not rows:
            continue
        label = _MODEL_LABELS.get(model, model)
        color = _MODEL_COLORS.get(model, "#4ade80")
        total_n = sum(r["n"] for r in rows)
        trs = []
        for r in rows:
            trs.append(f"""
        <tr>
          <td>{r['range']}</td>
          <td>{r['n']}</td>
          <td>{r['avg_pred']:.0f}%</td>
          <td>{r['actual']:.0f}%</td>
          <td class="bar-cell">
            <div class="bar-track">
              <div class="bar-fill" style="width:{min(r['actual'],100):.0f}%; background:{color};"></div>
            </div>
          </td>
        </tr>""")
        sections.append(f"""
    <h2>{label} <span class="n-note">({total_n} προβλέψεις συνολικά, όλα τα πρωταθλήματα/σεζόν)</span></h2>
    <table>
      <thead>
        <tr><th>Δηλωμένη πιθανότητα</th><th>Ν</th><th>Μ.Ο. δηλωμένη</th>
            <th>Πραγματικό ποσοστό</th><th>Πραγματικό (γράφημα)</th></tr>
      </thead>
      <tbody>{"".join(trs)}</tbody>
    </table>""")

    body = "".join(sections) if sections else "<p>Δεν υπάρχουν ακόμα αρκετά δεδομένα.</p>"

    html = f"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Calibration &mdash; Predictor</title>
<style>{_CALIBRATION_CSS}</style>
</head>
<body>
  <a class="back-link" href="index.html">&larr; Όλα τα πρωταθλήματα</a>
  <h1>Πόσο "σωστές" είναι οι πιθανότητες;</h1>
  <div class="subtitle">Ομαδοποιούμε όλες τις προβλέψεις κάθε μοντέλου (σε όλα τα πρωταθλήματα
    και τις σεζόν που έχουμε) ανάλογα με τη δηλωμένη πιθανότητα της έκβασης που προβλέφθηκε,
    και συγκρίνουμε με το πραγματικό ποσοστό επιτυχίας σε κάθε ομάδα. Αν το μοντέλο είναι
    "καλά βαθμονομημένο", οι δύο στήλες (δηλωμένη / πραγματικό) πρέπει να είναι κοντά --
    π.χ. στους αγώνες που δώσαμε ~70% σε μια έκβαση, θα έπρεπε να κερδίζει περίπου το 70%
    των φορών. Αν το πραγματικό ποσοστό είναι σταθερά χαμηλότερο, το μοντέλο είναι υπερβολικά
    σίγουρο (overconfident)· αν είναι ψηλότερο, είναι υπερβολικά συντηρητικό.</div>
  <div class="generated">ενημερώθηκε {generated}</div>
  {body}
  <footer>Υπολογίζεται από όλα τα ήδη τελειωμένα ματς (backtest ιστορικών σεζόν + ό,τι
    έχει ήδη παιχτεί φέτος) σε όλα τα πρωταθλήματα -- τρέξε <code>python calibration.py</code>
    για να ξαναϋπολογιστεί μετά από νέα δεδομένα.</footer>
</body>
</html>"""

    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = config.OUTPUT_DIR / "calibration.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


def render_report(season: int, matchday: int | None, fixtures: list[dict],
                   preds: list[dict], table: list[dict] | None = None,
                   accuracy: dict | None = None, sim: dict | None = None,
                   team_accuracy: dict | None = None, elo_accuracy: dict | None = None,
                   elo_team_accuracy: dict | None = None,
                   market_accuracy: dict | None = None,
                   market_team_accuracy: dict | None = None,
                   out_filename: str = "index.html", note: str | None = None,
                   competition: str = "PL") -> str:
    """Σελίδα με μία μόνο καρτέλα (χρησιμοποιείται από το backtest.py για
    γρήγορο, αυτόνομο έλεγχο μιας σεζόν)."""
    label = f"Σεζόν {competitions.season_label(season, competition)}"
    section = build_section("season", label, season, matchday,
                             fixtures, preds, table=table, accuracy=accuracy, sim=sim,
                             team_accuracy=team_accuracy, elo_accuracy=elo_accuracy,
                             elo_team_accuracy=elo_team_accuracy,
                             market_accuracy=market_accuracy,
                             market_team_accuracy=market_team_accuracy, note=note, active=True,
                             competition=competition)
    comp = competitions.BY_CODE.get(competition)
    return render_site([{"id": "season", "label": label, "html": section}],
                        comp, out_filename=out_filename)
