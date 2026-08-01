# -*- coding: utf-8 -*-
"""Holdout αξιολόγηση των αποθηκευμένων προβλέψεων, χωρίς κλήσεις σε APIs."""

import math
import sys

from src import competitions, db

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def evaluate_rows(rows: list[dict]) -> dict:
    total = correct = 0
    log_loss = brier = 0.0
    for row in rows:
        probabilities = [
            float(row["prob_home"]),
            float(row["prob_draw"]),
            float(row["prob_away"]),
        ]
        probability_sum = sum(probabilities)
        if probability_sum <= 0:
            continue
        probabilities = [max(value / probability_sum, 1e-12) for value in probabilities]
        actual = 0 if row["home_score"] > row["away_score"] else (
            2 if row["home_score"] < row["away_score"] else 1
        )
        predicted = max(range(3), key=probabilities.__getitem__)
        correct += predicted == actual
        log_loss -= math.log(probabilities[actual])
        brier += sum(
            (probability - (1.0 if index == actual else 0.0)) ** 2
            for index, probability in enumerate(probabilities)
        )
        total += 1
    return {
        "total": total,
        "accuracy": correct / total if total else None,
        "log_loss": log_loss / total if total else None,
        "brier": brier / total if total else None,
    }


def baseline_probabilities(training_rows: list[dict]) -> tuple[float, float, float]:
    counts = [1.0, 1.0, 1.0]
    for row in training_rows:
        actual = 0 if row["home_score"] > row["away_score"] else (
            2 if row["home_score"] < row["away_score"] else 1
        )
        counts[actual] += 1
    total = sum(counts)
    return tuple(count / total for count in counts)


def evaluate_baseline(rows: list[dict],
                      probabilities: tuple[float, float, float]) -> dict:
    augmented = [
        {
            **row,
            "prob_home": probabilities[0],
            "prob_draw": probabilities[1],
            "prob_away": probabilities[2],
        }
        for row in rows
    ]
    return evaluate_rows(augmented)


def _print_result(label: str, result: dict) -> None:
    if not result["total"]:
        print(f"{label:<14} χωρίς δεδομένα")
        return
    print(
        f"{label:<14} n={result['total']:>4}  "
        f"accuracy={result['accuracy'] * 100:5.1f}%  "
        f"log loss={result['log_loss']:.3f}  Brier={result['brier']:.3f}"
    )


def print_by_league(by_model: dict[str, list[dict]], holdout: int) -> None:
    print("\nΑνάλυση holdout ανά πρωτάθλημα")
    print("Πρωτάθλημα                 Μοντέλο       n   accuracy  log loss  Brier")
    print("-" * 76)
    for competition in competitions.COMPETITIONS:
        code = competition["code"]
        first = True
        for model in ("poisson", "elo"):
            rows = [
                row for row in by_model[model]
                if row["season"] == holdout and row["competition"] == code
            ]
            result = evaluate_rows(rows)
            if not result["total"]:
                continue
            league_name = competition["name"] if first else ""
            first = False
            print(
                f"{league_name:<28} {model.capitalize():<9} "
                f"{result['total']:>5}  {result['accuracy'] * 100:7.1f}%  "
                f"{result['log_loss']:8.3f}  {result['brier']:6.3f}"
            )


def main() -> None:
    by_model = {
        model: db.all_predictions_with_results(model)
        for model in ("poisson", "elo", "market")
    }
    seasons = sorted({
        row["season"] for rows in by_model.values() for row in rows
    })
    if len(seasons) < 2:
        raise SystemExit("Χρειάζονται τουλάχιστον δύο σεζόν με αποτελέσματα.")

    holdout = seasons[-1]
    print(f"Holdout σεζόν: {holdout} (εκτός calibration/tuning)\n")
    for model, rows in by_model.items():
        test_rows = [row for row in rows if row["season"] == holdout]
        _print_result(model.capitalize(), evaluate_rows(test_rows))

    poisson_rows = by_model["poisson"]
    training_rows = [row for row in poisson_rows if row["season"] < holdout]
    test_rows = [row for row in poisson_rows if row["season"] == holdout]
    baseline = baseline_probabilities(training_rows)
    _print_result("Baseline", evaluate_baseline(test_rows, baseline))
    print(
        f"\nBaseline πιθανότητες από παλιότερες σεζόν: "
        f"1={baseline[0] * 100:.1f}%  Χ={baseline[1] * 100:.1f}%  "
        f"2={baseline[2] * 100:.1f}%"
    )
    if "--by-league" in sys.argv[1:]:
        print_by_league(by_model, holdout)


if __name__ == "__main__":
    main()
