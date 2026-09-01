"""Measure the anomaly detector against a controlled ground truth.

Run it:

    cd backend && python scripts/eval_anomalies.py

The generator knows exactly which values it perturbed, so passing it a
``labels`` list gives a ground truth that was not reconstructed after the
fact. Two classes of perturbation are labelled separately, and the difference
between them is the whole point of this script:

* **rule faults** -- impossible values (negative price, zero weight, lead time
  of 30 days). They sit about 1.5 robust deviations from the median, which is
  to say they are not statistically extreme. The domain rules reject all of
  them. They are *not* the detector's job and are excluded from the ground
  truth.
* **statistical outliers** -- values that pass every rule but sit one or two
  orders of magnitude away from the rest of the column. A price of 6.000 in a
  catalogue that runs 10 to 500. No rule will ever catch these, which is
  precisely why an outlier detector exists.

The unit of evaluation is a (row, column) cell, not a row: a row can hold an
outlier in one column and be perfectly ordinary in another.
"""

from __future__ import annotations

import csv
import io
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.data_generator import (  # noqa: E402
    NUMERIC_INJECTIONS,
    OUTLIER_INJECTIONS,
    generate_dataset_csv,
)
from app.services.data_quality import (  # noqa: E402
    ANOMALY_THRESHOLD,
    _profile,
    _to_float,
    robust_scale,
    run_anomaly_detection,
)

DOMAIN = "ecommerce-logistica"
ROWS = 600
ANOMALY_RATE = 0.12

# Seeds used while developing the change, kept separate from the ones reported
# so a threshold is never chosen and validated on the same data.
DEV_SEEDS = (101, 102)
HELD_OUT_SEEDS = (2001, 2002, 2003, 2004, 2005)


@dataclass
class Scores:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def build_sample(seed: int):
    labels: list[dict] = []
    text = generate_dataset_csv(ROWS, ANOMALY_RATE, seed=seed, labels=labels)
    records = list(csv.DictReader(io.StringIO(text)))
    return records, labels


def ground_truth(labels, records, fields) -> set[tuple[int, str]]:
    """Cells holding a genuine statistical outlier."""
    truth = set()
    for index, label in enumerate(labels):
        for kind in label["injected"]:
            field = OUTLIER_INJECTIONS.get(kind)
            if field in fields and _to_float(records[index].get(field, "")) is not None:
                truth.add((index, field))
    return truth


def rule_fault_cells(labels, records, fields) -> set[tuple[int, str]]:
    """Cells holding an impossible value. Not outliers; the rules own them."""
    cells = set()
    for index, label in enumerate(labels):
        for kind in label["injected"]:
            field = NUMERIC_INJECTIONS.get(kind)
            if field in fields and _to_float(records[index].get(field, "")) is not None:
                cells.add((index, field))
    return cells


def evaluable_cells(records, fields) -> set[tuple[int, str]]:
    return {
        (index, field)
        for index, row in enumerate(records)
        for field in fields
        if _to_float(row.get(field, "")) is not None
    }


# --- detectors --------------------------------------------------------------


def detect_current_production(records, fields, threshold=ANOMALY_THRESHOLD):
    """Whatever run_anomaly_detection does today, re-keyed to cells."""
    result = run_anomaly_detection(records, domain=DOMAIN, threshold=threshold)
    # The stored list is capped at 50, so re-derive the cells rather than
    # reading them back.
    flagged = set()
    for field, stats in result["fields_analyzed"].items():
        centre, scale = stats["median"], stats["scale"]
        for index, row in enumerate(records):
            value = _to_float(row.get(field, ""))
            if value is None or scale <= 0:
                continue
            if abs((value - centre) / scale) >= threshold:
                flagged.add((index, field))
    return flagged, result["anomaly_count"]


def detect_legacy_zscore(records, fields, threshold=3.0):
    """The previous implementation: mean and population sigma, |z| >= 3."""
    flagged = set()
    for field in fields:
        values = [
            v for v in (_to_float(r.get(field, "")) for r in records) if v is not None
        ]
        if len(values) < 5:
            continue
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        if stdev == 0:
            continue
        for index, row in enumerate(records):
            value = _to_float(row.get(field, ""))
            if value is None:
                continue
            if abs((value - mean) / stdev) >= threshold:
                flagged.add((index, field))
    return flagged


def score(flagged, truth, universe, ignore) -> Scores:
    """Rule-fault cells are excluded from the denominator entirely.

    They are neither positives (they are not outliers) nor negatives (flagging
    one is not really a false alarm, just a duplicate of what the rules say),
    so counting them either way would distort the picture.
    """
    flagged = flagged - ignore
    considered = universe - ignore
    tp = len(flagged & truth)
    fp = len(flagged - truth)
    fn = len(truth - flagged)
    tn = len(considered) - tp - fp - fn
    return Scores(tp, fp, fn, tn)


def evaluate(seed: int, threshold: float = ANOMALY_THRESHOLD):
    records, labels = build_sample(seed)
    fields = _profile(DOMAIN)["anomaly_fields"]
    truth = ground_truth(labels, records, fields)
    ignore = rule_fault_cells(labels, records, fields)
    universe = evaluable_cells(records, fields)

    new_cells, _ = detect_current_production(records, fields, threshold)
    old_cells = detect_legacy_zscore(records, fields)

    return {
        "seed": seed,
        "outliers": len(truth),
        "rule_faults": len(ignore),
        "cells": len(universe),
        "before": score(old_cells, truth, universe, ignore),
        "after": score(new_cells, truth, universe, ignore),
    }


def _row(label: str, s: Scores) -> str:
    return (
        f"  {label:<28} TP={s.tp:>4}  FP={s.fp:>4}  FN={s.fn:>4}  TN={s.tn:>5}  "
        f"P={s.precision:.3f}  R={s.recall:.3f}  F1={s.f1:.3f}"
    )


def main() -> None:
    fields = _profile(DOMAIN)["anomaly_fields"]
    print(f"dominio={DOMAIN}  filas={ROWS}  tasa_faltas={ANOMALY_RATE}")
    print(f"columnas vigiladas: {', '.join(fields)}")
    print(f"umbral robusto: {ANOMALY_THRESHOLD} (Iglewicz-Hoaglin)\n")

    print("=" * 104)
    print("SEEDS DE DESARROLLO (usados para construir el cambio; no son validacion)")
    print("=" * 104)
    for seed in DEV_SEEDS:
        result = evaluate(seed)
        print(f"seed {seed}: outliers={result['outliers']} faltas_de_regla={result['rule_faults']}")
        print(_row("antes (z-score sigma, 3.0)", result["before"]))
        print(_row("despues (MAD, 3.5)", result["after"]))

    print()
    print("=" * 104)
    print("SEEDS RESERVADOS (no vistos al elegir el metodo ni el umbral)")
    print("=" * 104)
    totals = {"before": Scores(0, 0, 0, 0), "after": Scores(0, 0, 0, 0)}
    for seed in HELD_OUT_SEEDS:
        result = evaluate(seed)
        print(f"seed {seed}: outliers={result['outliers']} faltas_de_regla={result['rule_faults']}")
        print(_row("antes", result["before"]))
        print(_row("despues", result["after"]))
        for key in ("before", "after"):
            current, addition = totals[key], result[key]
            totals[key] = Scores(
                current.tp + addition.tp,
                current.fp + addition.fp,
                current.fn + addition.fn,
                current.tn + addition.tn,
            )

    print()
    print("=" * 104)
    print("AGREGADO SOBRE LOS SEEDS RESERVADOS")
    print("=" * 104)
    print(_row("antes", totals["before"]))
    print(_row("despues", totals["after"]))

    print()
    print("=" * 104)
    print("SENSIBILIDAD AL UMBRAL (seeds reservados agregados)")
    print("=" * 104)
    for threshold in (2.5, 3.0, 3.5, 4.0, 5.0):
        total = Scores(0, 0, 0, 0)
        for seed in HELD_OUT_SEEDS:
            result = evaluate(seed, threshold)["after"]
            total = Scores(
                total.tp + result.tp,
                total.fp + result.fp,
                total.fn + result.fn,
                total.tn + result.tn,
            )
        marker = "  <- elegido" if threshold == ANOMALY_THRESHOLD else ""
        print(_row(f"umbral {threshold}", total) + marker)

    print()
    print("=" * 104)
    print("CONTROL: dataset sin ninguna falta ni outlier (tasa 0)")
    print("=" * 104)
    for seed in HELD_OUT_SEEDS[:3]:
        labels: list[dict] = []
        text = generate_dataset_csv(ROWS, 0.0, seed=seed, labels=labels, outlier_rate=0.0)
        records = list(csv.DictReader(io.StringIO(text)))
        result = run_anomaly_detection(records, domain=DOMAIN)
        legacy = detect_legacy_zscore(records, fields)
        print(
            f"  seed {seed}: falsos positivos  antes={len(legacy):>3}  "
            f"despues={result['anomaly_count']:>3}"
        )

    print()
    print("=" * 104)
    print("DESCOMPOSICION: cuanto aporta el estimador y cuanto el umbral (umbral fijo 3.0)")
    print("=" * 104)
    totals = {"sigma": Scores(0, 0, 0, 0), "mad": Scores(0, 0, 0, 0)}
    for seed in HELD_OUT_SEEDS:
        records, labels = build_sample(seed)
        truth = ground_truth(labels, records, fields)
        ignore = rule_fault_cells(labels, records, fields)
        universe = evaluable_cells(records, fields)
        pairs = {
            "sigma": detect_legacy_zscore(records, fields, 3.0),
            "mad": detect_current_production(records, fields, 3.0)[0],
        }
        for key, cells in pairs.items():
            addition = score(cells, truth, universe, ignore)
            current = totals[key]
            totals[key] = Scores(
                current.tp + addition.tp,
                current.fp + addition.fp,
                current.fn + addition.fn,
                current.tn + addition.tn,
            )
    print(_row("media + sigma (viejo)", totals["sigma"]))
    print(_row("mediana + MAD (nuevo)", totals["mad"]))

    print()
    print("=" * 104)
    print("EFECTO ENMASCARAMIENTO: recall segun cuanta contaminacion tiene la columna")
    print("=" * 104)
    print(f"  {'tasa outliers':>14} {'outliers':>9} {'recall sigma':>13} {'recall MAD':>11} {'sigma/MAD price':>17}")
    for outlier_rate in (0.01, 0.02, 0.05, 0.10, 0.20, 0.30):
        agg = {"sigma": Scores(0, 0, 0, 0), "mad": Scores(0, 0, 0, 0)}
        ratios = []
        for seed in HELD_OUT_SEEDS:
            labels: list[dict] = []
            text = generate_dataset_csv(
                ROWS, ANOMALY_RATE, seed=seed, labels=labels, outlier_rate=outlier_rate
            )
            records = list(csv.DictReader(io.StringIO(text)))
            truth = ground_truth(labels, records, fields)
            ignore = rule_fault_cells(labels, records, fields)
            universe = evaluable_cells(records, fields)
            for key, cells in {
                "sigma": detect_legacy_zscore(records, fields, 3.0),
                "mad": detect_current_production(records, fields, ANOMALY_THRESHOLD)[0],
            }.items():
                addition = score(cells, truth, universe, ignore)
                current = agg[key]
                agg[key] = Scores(
                    current.tp + addition.tp,
                    current.fp + addition.fp,
                    current.fn + addition.fn,
                    current.tn + addition.tn,
                )
            values = [
                v for v in (_to_float(r.get("price", "")) for r in records) if v is not None
            ]
            centre = statistics.median(values)
            sigma = statistics.pstdev(values)
            mad_scale = robust_scale(values, centre)
            ratios.append(sigma / mad_scale if mad_scale else 0.0)
        n = agg["mad"].tp + agg["mad"].fn
        print(
            f"  {outlier_rate:>13.0%} {n:>9} {agg['sigma'].recall:>13.3f} "
            f"{agg['mad'].recall:>11.3f} {statistics.mean(ratios):>17.2f}x"
        )

    print()
    print("=" * 104)
    print("POR QUE LAS FALTAS DE REGLA NO SON OUTLIERS (distancia robusta a la mediana)")
    print("=" * 104)
    records, labels = build_sample(HELD_OUT_SEEDS[0])
    for kind, field in NUMERIC_INJECTIONS.items():
        if field not in fields:
            continue
        clean = [
            _to_float(records[i].get(field, ""))
            for i, label in enumerate(labels)
            if kind not in label["injected"]
        ]
        clean = [v for v in clean if v is not None]
        if len(clean) < 12:
            continue
        centre = statistics.median(clean)
        scale = robust_scale(clean, centre)
        injected = [
            _to_float(records[i].get(field, ""))
            for i, label in enumerate(labels)
            if kind in label["injected"]
        ]
        injected = [v for v in injected if v is not None]
        if not injected or scale <= 0:
            continue
        scores = [abs((v - centre) / scale) for v in injected]
        print(
            f"  {kind:<26} {field:<16} |z| medio={statistics.mean(scores):5.2f} "
            f"max={max(scores):5.2f}   {'EXTREMO' if max(scores) >= ANOMALY_THRESHOLD else 'no extremo'}"
        )
    for kind, field in OUTLIER_INJECTIONS.items():
        if field not in fields:
            continue
        clean = [
            _to_float(records[i].get(field, ""))
            for i, label in enumerate(labels)
            if kind not in label["injected"]
        ]
        clean = [v for v in clean if v is not None]
        centre = statistics.median(clean)
        scale = robust_scale(clean, centre)
        injected = [
            _to_float(records[i].get(field, ""))
            for i, label in enumerate(labels)
            if kind in label["injected"]
        ]
        injected = [v for v in injected if v is not None]
        if not injected or scale <= 0:
            continue
        scores = [abs((v - centre) / scale) for v in injected]
        print(
            f"  {kind:<26} {field:<16} |z| medio={statistics.mean(scores):5.2f} "
            f"max={max(scores):5.2f}   {'EXTREMO' if max(scores) >= ANOMALY_THRESHOLD else 'no extremo'}"
        )


if __name__ == "__main__":
    main()
