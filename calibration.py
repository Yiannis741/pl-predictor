# -*- coding: utf-8 -*-
"""Calibration check: πόσο "σωστές" είναι οι πιθανότητες που δίνουν τα
μοντέλα -- ομαδοποιεί όλες τις προβλέψεις (backtest + ό,τι έχει ήδη παιχτεί
φέτος, σε ΟΛΑ τα πρωταθλήματα) ανά επίπεδο δηλωμένης πιθανότητας, και
συγκρίνει με το πραγματικό ποσοστό επιτυχίας σε κάθε επίπεδο.

Δεν κάνει καμία κλήση σε εξωτερικό API -- δουλεύει πάνω σε ό,τι υπάρχει ήδη
στη βάση, οπότε τρέχει μέσα σε δευτερόλεπτα.

Τρέξιμο:  python calibration.py
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src import db, render  # noqa: E402

# (κάτω όριο, άνω όριο) δηλωμένης πιθανότητας -- ξεκινάει από 0.34 γιατί
# στα 1/Χ/2 η "νικήτρια" πρόβλεψη έχει πάντα τουλάχιστον ~1/3.
BUCKETS = [
    (0.33, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 0.75),
    (0.75, 0.85), (0.85, 1.01),
]


def compute_calibration(model: str) -> list[dict]:
    rows = db.all_predictions_with_results(model)
    bucket_stats = {b: [0, 0, 0.0] for b in BUCKETS}  # n, hits, sum_conf

    for r in rows:
        ph, pd, pa = r["prob_home"], r["prob_draw"], r["prob_away"]
        conf = max(ph, pd, pa)
        predicted = "H" if ph >= pd and ph >= pa else ("A" if pa >= pd else "D")
        actual = "H" if r["home_score"] > r["away_score"] else (
            "A" if r["home_score"] < r["away_score"] else "D")
        hit = 1 if predicted == actual else 0

        for lo, hi in BUCKETS:
            if lo <= conf < hi or (hi >= 1.0 and conf <= 1.0):
                b = bucket_stats[(lo, hi)]
                b[0] += 1
                b[1] += hit
                b[2] += conf
                break

    results = []
    for (lo, hi), (n, hits, sum_conf) in bucket_stats.items():
        if n == 0:
            continue
        results.append({
            "range": f"{round(lo * 100)}-{round(hi * 100)}%",
            "n": n,
            "avg_pred": sum_conf / n * 100,
            "actual": hits / n * 100,
        })
    return results


def main() -> None:
    print("== Calibration check (πόσο σωστές είναι οι πιθανότητες) ==")
    model_results = {}
    for model in ("poisson", "elo", "market"):
        results = compute_calibration(model)
        model_results[model] = results
        total = sum(r["n"] for r in results)
        print(f"\n{model} -- {total} προβλέψεις:")
        for r in results:
            diff = r["actual"] - r["avg_pred"]
            flag = "" if abs(diff) < 5 else ("  <- overconfident" if diff < 0 else "  <- underconfident")
            print(f"  {r['range']:>8}  n={r['n']:>4}  δηλωμένη={r['avg_pred']:5.1f}%  "
                  f"πραγματικό={r['actual']:5.1f}%{flag}")

    out_path = render.build_calibration_page(model_results)
    print(f"\nΟλοκληρώθηκε. Δες το {out_path}")


if __name__ == "__main__":
    main()
