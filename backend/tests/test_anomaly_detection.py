"""Behaviour of the outlier detector.

The detector answers one question: is this value far from the centre of its
own column? It is deliberately *not* asked whether the value is legal --
negative prices and zero weights are impossible values that the domain rules
reject, and they sit around 1.5 robust deviations from the median, so no
distributional method should flag them.
"""

import csv
import io
import statistics

import pytest

from app.services.data_generator import (
    NUMERIC_INJECTIONS,
    OUTLIER_INJECTIONS,
    generate_dataset_csv,
)
from app.services.data_quality import (
    ANOMALY_THRESHOLD,
    MIN_VALUES_FOR_ANOMALY,
    _profile,
    robust_scale,
    run_anomaly_detection,
)


def numeric_rows(field: str, values, **fixed) -> list[dict]:
    rows = []
    for index, value in enumerate(values):
        row = {"order_id": f"A{index}", field: "" if value is None else str(value)}
        row.update(fixed)
        rows.append(row)
    return rows


def flagged_values(result, field: str) -> list[float]:
    return [a["value"] for a in result["anomalies"] if a["field"] == field]


# --- 1. no anomalies --------------------------------------------------------


def test_a_clean_column_produces_no_anomalies():
    rows = numeric_rows("price", [100 + i for i in range(60)])
    result = run_anomaly_detection(rows, domain="ecommerce")

    assert result["anomaly_count"] == 0
    assert result["anomalies"] == []


def test_a_constant_column_produces_no_anomalies():
    """Every value is the centre; MAD and the mean deviation are both zero."""
    rows = numeric_rows("price", [50] * 40)
    result = run_anomaly_detection(rows, domain="ecommerce")

    assert result["anomaly_count"] == 0
    # The column is skipped rather than dividing by zero.
    assert "price" not in result["fields_analyzed"]


def test_a_generated_dataset_with_no_faults_has_no_anomalies():
    text = generate_dataset_csv(400, 0.0, seed=7, outlier_rate=0.0)
    records = list(csv.DictReader(io.StringIO(text)))

    result = run_anomaly_detection(records, domain="ecommerce-logistica")
    assert result["anomaly_count"] == 0


# --- 2. an obvious anomaly --------------------------------------------------


def test_an_order_of_magnitude_outlier_is_flagged():
    values = [round(100 + i * 3.7, 2) for i in range(60)]
    values[17] = 90000.0
    rows = numeric_rows("price", values)

    result = run_anomaly_detection(rows, domain="ecommerce")

    assert result["anomaly_count"] == 1
    assert flagged_values(result, "price") == [90000.0]
    assert abs(result["anomalies"][0]["score"]) >= ANOMALY_THRESHOLD


def test_several_outliers_in_one_column_are_all_flagged():
    values = [round(100 + i * 3.7, 2) for i in range(60)]
    for index in (5, 25, 44):
        values[index] = 50000.0
    rows = numeric_rows("price", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["anomaly_count"] == 3


def test_masking_does_not_hide_outliers_from_each_other():
    """The defect that made the old detector fail.

    With mean and population sigma, a block of outliers inflates the spread
    enough to fall inside its own threshold. The MAD has a 50% breakdown
    point, so it barely moves.
    """
    values = [round(100 + i * 0.5, 2) for i in range(80)]
    for index in range(0, 20):  # 20% of the column is contaminated
        values[index] = 9000.0
    rows = numeric_rows("price", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["anomaly_count"] == 20

    # The same data judged the old way: sigma is so inflated that nothing
    # reaches |z| >= 3.
    mean = statistics.mean(values)
    sigma = statistics.pstdev(values)
    assert max(abs((v - mean) / sigma) for v in values) < 3.0


# --- 3. a moderate anomaly --------------------------------------------------


def test_a_moderate_deviation_is_not_flagged_at_this_threshold():
    """A threshold is a trade-off, and this is the side it gives up.

    Values a little outside the usual range are left alone; only clearly
    extreme ones are reported. Documented rather than tuned away.
    """
    values = [round(10 + (i % 30), 2) for i in range(90)]
    values[3] = 55.0  # roughly 3 robust deviations out
    rows = numeric_rows("discount_pct", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["anomaly_count"] == 0

    # It is genuinely close to the line, not far from it.
    centre = statistics.median(values)
    scale = robust_scale(values, centre)
    assert 2.0 < abs((55.0 - centre) / scale) < ANOMALY_THRESHOLD


def test_lowering_the_threshold_catches_the_moderate_case():
    values = [round(10 + (i % 30), 2) for i in range(90)]
    values[3] = 55.0
    rows = numeric_rows("discount_pct", values)

    assert run_anomaly_detection(rows, domain="ecommerce", threshold=2.5)["anomaly_count"] == 1


# --- 4. normal values must not be flagged -----------------------------------


def test_a_wide_but_ordinary_spread_produces_no_anomalies():
    """Spread alone is not anomalous; only distance from the centre is."""
    values = list(range(0, 1000, 10))
    rows = numeric_rows("stock", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["anomaly_count"] == 0


def test_a_skewed_but_legitimate_distribution_is_not_all_flagged():
    """Most values small, a few large, no injected fault."""
    values = [1] * 50 + [2] * 20 + [3] * 10 + [4] * 5 + [5] * 3
    rows = numeric_rows("quantity", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    # Whatever it flags must be a small minority of a legitimate tail.
    assert result["anomaly_count"] <= 3


# --- 5. missing values ------------------------------------------------------


def test_missing_values_are_ignored_not_treated_as_zero():
    """A gap has no distance to a centre; completeness is the rules' job."""
    values = [100 + i for i in range(40)] + [None] * 20
    rows = numeric_rows("price", values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["anomaly_count"] == 0
    assert result["fields_analyzed"]["price"]["values_checked"] == 40


def test_missing_values_do_not_shift_the_centre():
    with_gaps = numeric_rows("price", [100 + i for i in range(40)] + [None] * 40)
    without_gaps = numeric_rows("price", [100 + i for i in range(40)])

    a = run_anomaly_detection(with_gaps, domain="ecommerce")["fields_analyzed"]["price"]
    b = run_anomaly_detection(without_gaps, domain="ecommerce")["fields_analyzed"]["price"]
    assert a["median"] == b["median"]
    assert a["scale"] == b["scale"]


def test_non_numeric_text_in_a_numeric_column_is_ignored():
    rows = numeric_rows("price", [100 + i for i in range(40)])
    rows += [{"order_id": "X", "price": "gratis"} for _ in range(5)]

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert result["fields_analyzed"]["price"]["values_checked"] == 40


# --- 6. impossible values belong to the rules, not here ---------------------


@pytest.mark.parametrize(
    "field,base,impossible",
    [
        ("stock", list(range(0, 200, 2)), -5),
        ("price", [round(10 + i * 4.9, 2) for i in range(100)], -120.0),
    ],
)
def test_impossible_values_are_not_reported_as_outliers(field, base, impossible):
    """They are rejected by the rules and are not statistically extreme.

    Reporting them here as well would count the same defect twice under two
    different names.
    """
    values = list(base)
    values[10] = impossible
    rows = numeric_rows(field, values)

    result = run_anomaly_detection(rows, domain="ecommerce")
    assert impossible not in flagged_values(result, field)


def test_the_impossible_values_the_rules_own_are_mostly_not_extreme():
    """Measured, not assumed: this is why the old recall figure was misleading.

    Negative stock and zero weight sit around 1.5 robust deviations from the
    median: no distributional method will ever flag them, and none should.
    Negative price is a sign flip, so its *typical* case is not extreme either,
    though the tail of the flipped distribution does cross the threshold.
    """
    labels: list[dict] = []
    text = generate_dataset_csv(600, 0.12, seed=4242, labels=labels, outlier_rate=0.0)
    records = list(csv.DictReader(io.StringIO(text)))
    fields = _profile("ecommerce-logistica")["anomaly_fields"]

    def distances(kind: str, field: str) -> list[float]:
        clean = [
            float(records[i][field])
            for i, label in enumerate(labels)
            if kind not in label["injected"] and records[i][field]
        ]
        centre = statistics.median(clean)
        scale = robust_scale(clean, centre)
        injected = [
            float(records[i][field])
            for i, label in enumerate(labels)
            if kind in label["injected"] and records[i][field]
        ]
        assert injected, kind
        return [abs((v - centre) / scale) for v in injected]

    # Never extreme, at any value the generator can produce.
    for kind in ("stock_negative", "weight_zero"):
        field = NUMERIC_INJECTIONS[kind]
        assert field in fields
        assert max(distances(kind, field)) < ANOMALY_THRESHOLD, kind

    # Typically not extreme, so counting them as missed anomalies understated
    # the detector; its extreme tail does cross, which is legitimate.
    price_distances = distances("price_negative", "price")
    assert statistics.median(price_distances) < ANOMALY_THRESHOLD
    assert max(price_distances) > ANOMALY_THRESHOLD


def test_issues_and_anomalies_may_overlap_on_the_same_value():
    """A lead time of 30 days is both impossible and far from the centre.

    The two views answer different questions and are not disjoint by design.
    The test pins the fact so nobody later adds the two counts together.
    """
    values = [1 + (i % 7) for i in range(80)]
    values[4] = 30  # rejected by invalid_lead_time and genuinely extreme
    rows = numeric_rows("lead_time_days", values)

    result = run_anomaly_detection(rows, domain="logistica")
    assert 30.0 in flagged_values(result, "lead_time_days")


# --- 7. several columns -----------------------------------------------------


def test_each_column_is_judged_against_its_own_distribution():
    rows = []
    for index in range(60):
        rows.append(
            {
                "order_id": f"A{index}",
                "price": str(100 + index),
                "quantity": str(1 + index % 4),
                "stock": str(50 + index),
            }
        )
    rows[7]["price"] = "80000"
    rows[31]["quantity"] = "900"

    result = run_anomaly_detection(rows, domain="ecommerce")

    flagged = {(a["field"], a["value"]) for a in result["anomalies"]}
    assert ("price", 80000.0) in flagged
    assert ("quantity", 900.0) in flagged
    assert result["anomaly_count"] == 2
    # Scales are per column, not shared.
    stats = result["fields_analyzed"]
    assert stats["price"]["scale"] != stats["quantity"]["scale"]


def test_only_the_domain_profile_columns_are_analysed():
    logistics = set(_profile("logistica")["anomaly_fields"])
    ecommerce = set(_profile("ecommerce")["anomaly_fields"])
    assert "price" in ecommerce and "price" not in logistics

    rows = numeric_rows("price", [100 + i for i in range(60)])
    rows[3]["price"] = "90000"

    assert run_anomaly_detection(rows, domain="ecommerce")["anomaly_count"] == 1
    assert run_anomaly_detection(rows, domain="logistica")["anomaly_count"] == 0


def test_disabled_rules_switch_a_column_off():
    rows = numeric_rows("price", [100 + i for i in range(60)])
    rows[3]["price"] = "90000"

    assert run_anomaly_detection(rows, domain="ecommerce")["anomaly_count"] == 1
    off = run_anomaly_detection(rows, domain="ecommerce", disabled_rules=["anomaly_price"])
    assert off["anomaly_count"] == 0


# --- 8. small datasets ------------------------------------------------------


def test_a_dataset_too_small_to_estimate_a_spread_is_skipped():
    rows = numeric_rows("price", [10, 20, 30, 9000])
    result = run_anomaly_detection(rows, domain="ecommerce")

    assert result["anomaly_count"] == 0
    assert result["fields_analyzed"] == {}


def test_the_minimum_sample_size_is_the_boundary():
    values = [100 + i for i in range(MIN_VALUES_FOR_ANOMALY - 1)]
    assert run_anomaly_detection(numeric_rows("price", values), domain="ecommerce")[
        "fields_analyzed"
    ] == {}

    values = [100 + i for i in range(MIN_VALUES_FOR_ANOMALY)]
    assert "price" in run_anomaly_detection(numeric_rows("price", values), domain="ecommerce")[
        "fields_analyzed"
    ]


def test_an_empty_dataset_is_handled():
    result = run_anomaly_detection([], domain="ecommerce")
    assert result["anomaly_count"] == 0
    assert result["fields_analyzed"] == {}


# --- 9. the demo dataset, against its own ground truth ----------------------


@pytest.mark.parametrize("seed", [3101, 3102, 3103])
def test_gross_outliers_in_the_demo_dataset_are_all_found(seed):
    """Reproducible check against the labels the generator itself records."""
    labels: list[dict] = []
    text = generate_dataset_csv(600, 0.12, seed=seed, labels=labels)
    records = list(csv.DictReader(io.StringIO(text)))
    fields = _profile("ecommerce-logistica")["anomaly_fields"]

    result = run_anomaly_detection(records, domain="ecommerce-logistica")
    found = {(a["order_id"], a["field"]) for a in result["anomalies"]}

    gross = {"price_extreme", "quantity_extreme", "weight_extreme", "stock_extreme"}
    expected = {
        (records[i]["order_id"], OUTLIER_INJECTIONS[kind])
        for i, label in enumerate(labels)
        for kind in label["injected"]
        if kind in gross and OUTLIER_INJECTIONS[kind] in fields
    }
    assert expected, "the generator must inject gross outliers"

    # The stored list is capped at 50, so only assert over what fits.
    if result["anomaly_count"] <= 50:
        assert expected <= found
    else:
        assert result["anomaly_count"] >= len(expected)


def test_the_demo_dataset_contains_genuine_outliers_that_break_no_rule():
    """Without these the detector would have nothing legitimate to find."""
    from app.services.data_quality import run_quality_checks

    labels: list[dict] = []
    text = generate_dataset_csv(600, 0.12, seed=3104, labels=labels)
    records = list(csv.DictReader(io.StringIO(text)))

    pure = [
        i
        for i, label in enumerate(labels)
        if label["injected"] and all(k in OUTLIER_INJECTIONS for k in label["injected"])
    ]
    assert pure, "there must be rows whose only defect is an outlier"

    summary, issues = run_quality_checks([records[i] for i in pure], domain="ecommerce")
    # Those rows are legal: nothing of consequence fires on them. A cancelled
    # order legitimately has no delivered_at, which the optional-field rule
    # notes at severity "low"; that is a completeness note, not a defect the
    # outlier introduced.
    assert summary["critical_rows"] == 0
    assert all(issue["severity"] == "low" for issue in issues), issues

    result = run_anomaly_detection([records[i] for i in pure], domain="ecommerce-logistica")
    assert result["anomaly_count"] > 0


# --- 10. the threshold and the reported method ------------------------------


def test_the_result_states_how_it_was_computed():
    rows = numeric_rows("price", [100 + i for i in range(40)])
    result = run_anomaly_detection(rows, domain="ecommerce")

    assert result["method"] == "modified_zscore_mad"
    assert result["threshold"] == ANOMALY_THRESHOLD
    stats = result["fields_analyzed"]["price"]
    assert set(stats) == {"median", "scale", "values_checked"}


def test_the_threshold_is_the_published_constant():
    # Iglewicz & Hoaglin (1993). Chosen from the literature, not tuned on the
    # demo data, whose bounded uniform columns cannot discriminate thresholds.
    assert ANOMALY_THRESHOLD == 3.5


def test_a_stricter_threshold_flags_a_subset_of_a_looser_one():
    values = [round(10 + (i % 40), 2) for i in range(120)]
    values[5] = 300.0
    values[9] = 62.0
    rows = numeric_rows("price", values)

    loose = run_anomaly_detection(rows, domain="ecommerce", threshold=2.0)
    strict = run_anomaly_detection(rows, domain="ecommerce", threshold=6.0)

    assert strict["anomaly_count"] <= loose["anomaly_count"]
    assert set(flagged_values(strict, "price")) <= set(flagged_values(loose, "price"))


def test_robust_scale_falls_back_when_the_mad_collapses():
    """More than half the values identical makes the MAD zero."""
    values = [5.0] * 30 + [5.0, 9.0, 40.0]
    centre = statistics.median(values)
    assert statistics.median([abs(v - centre) for v in values]) == 0
    assert robust_scale(values, centre) > 0


def test_robust_scale_is_zero_only_for_a_constant_column():
    assert robust_scale([7.0] * 20, 7.0) == 0.0
